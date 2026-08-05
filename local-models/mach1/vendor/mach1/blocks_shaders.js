// WGSL kernels for full decoder-block assembly: RMSNorm + residuals, the
// Qwen3.5 full-attention layer (per-head qk RMSNorm, partial RoPE, GQA,
// sigmoid output gate), and the MoE elementwise glue (silu-mul, scaled
// accumulate, sigmoid-gated shared-expert add).
//
// Validated end-to-end against transformers real-weight activations by
// test/test_blocks_gpu.mjs (tolerance contracts — fp math, not codecs).

const silu = /* wgsl */ `
fn silu(x: f32) -> f32 { return x / (1.0 + exp(-x)); }
`;

// RMSNorm per token: y = (1 + w) ⊙ x / sqrt(mean(x²) + eps). One workgroup
// per token; H strided by 256 threads. NOTE the zero-centered weight:
// Qwen3_5MoeRMSNorm multiplies by (1.0 + weight) — plain w·x silently
// changes every hidden state ~unit-scale and reroutes the MoE. The GDN
// tier's GATED norm (Qwen3_5MoeRMSNormGated) genuinely uses w·x — do not
// "fix" that one to match.
export function rmsnormWGSL(H, eps, wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read> x: array<f32>;      // [T, ${H}]
@group(0) @binding(1) var<storage, read> w: array<f32>;      // [${H}]
@group(0) @binding(2) var<storage, read_write> y: array<f32>;
var<workgroup> red: array<f32, ${wg}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let t = wid.x;
  var ss = 0.0;
  for (var i = lid.x; i < ${H}u; i = i + ${wg}u) {
    let v = x[t * ${H}u + i];
    ss = ss + v * v;
  }
  red[lid.x] = ss;
  workgroupBarrier();
  for (var s = ${wg / 2}u; s > 0u; s = s >> 1u) {
    if (lid.x < s) { red[lid.x] = red[lid.x] + red[lid.x + s]; }
    workgroupBarrier();
  }
  let inv = inverseSqrt(red[0] / ${H}.0 + ${eps});
  for (var i = lid.x; i < ${H}u; i = i + ${wg}u) {
    y[t * ${H}u + i] = (1.0 + w[i]) * x[t * ${H}u + i] * inv;
  }
}`;
}

// dst += src, elementwise.
export function addWGSL(wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> dst: array<f32>;
@group(0) @binding(1) var<storage, read> src: array<f32>;
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (gid.x < arrayLength(&dst)) { dst[gid.x] = dst[gid.x] + src[gid.x]; }
}`;
}

// dst[off + i] += scales[si] * src[i] — routed-expert accumulate. The scale
// index and dst offset arrive via a uniform so all dispatches of a layer
// encode into one command buffer with precomputed routing weights.
export function scaleAddWGSL(wg = 256) {
  return /* wgsl */ `
struct P { n: u32, si: u32, dstOff: u32, pad: u32 }
@group(0) @binding(0) var<storage, read_write> dst: array<f32>;
@group(0) @binding(1) var<storage, read> src: array<f32>;
@group(0) @binding(2) var<storage, read> scales: array<f32>;
@group(0) @binding(3) var<uniform> p: P;
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (gid.x < p.n) {
    dst[p.dstOff + gid.x] = dst[p.dstOff + gid.x] + scales[p.si] * src[gid.x];
  }
}`;
}

// silu-mul over a SINGLE buffer holding [gate | up] halves (the merged
// 16-slot expert layout): a[i] = silu(a[i]) * a[i + half] for i < half.
// The gate half then feeds the down projection in place, exactly like the
// two-buffer siluMulWGSL did with gY/uY.
export function siluMulPairWGSL(half, wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> a: array<f32>;
${silu}
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (gid.x < ${half}u) { a[gid.x] = silu(a[gid.x]) * a[gid.x + ${half}u]; }
}`;
}

// a = silu(a) ⊙ b (gate/up combine of an MLP).
export function siluMulWGSL(wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> a: array<f32>;
@group(0) @binding(1) var<storage, read> b: array<f32>;
${silu}
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (gid.x < arrayLength(&a)) { a[gid.x] = silu(a[gid.x]) * b[gid.x]; }
}`;
}

// dst[t, :] += sigmoid(gateLogit[t]) * src[t, :] — shared-expert add.
// `assign` writes dst = g*src instead of accumulating — the caller then
// skips the clearBuffer that used to zero dst, which also removes a
// compute-pass break per layer (clearBuffer is an encoder op).
export function sigmoidScaleAddWGSL(H, wg = 256, { assign = false } = {}) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> dst: array<f32>;   // [T, ${H}]
@group(0) @binding(1) var<storage, read> src: array<f32>;         // [T, ${H}]
@group(0) @binding(2) var<storage, read> gateLogit: array<f32>;   // [T]
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (gid.x >= arrayLength(&dst)) { return; }
  let t = gid.x / ${H}u;
  let g = 1.0 / (1.0 + exp(-gateLogit[t]));
  dst[gid.x] = ${assign ? "" : "dst[gid.x] + "}g * src[gid.x];
}`;
}

// Fused residual-add + RMSNorm: x += d in place, then y = rmsnorm(x) — the
// summed value feeds the reduction directly, so this is bit-identical to
// add followed by rmsnormWGSL (which re-read the freshly written x). Same
// zero-centered (1 + w) weight as rmsnormWGSL. One workgroup, like rmsnorm;
// replaces an 8-workgroup add + a 1-workgroup norm with a single dispatch.
export function addRmsWGSL(H, eps, wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> x: array<f32>;   // [${H}]
@group(0) @binding(1) var<storage, read> d: array<f32>;         // [${H}]
@group(0) @binding(2) var<storage, read> w: array<f32>;         // [${H}]
@group(0) @binding(3) var<storage, read_write> y: array<f32>;   // [${H}]
var<workgroup> red: array<f32, ${wg}>;
@compute @workgroup_size(${wg})
fn main(@builtin(local_invocation_id) lid: vec3<u32>) {
  var ss = 0.0;
  for (var i = lid.x; i < ${H}u; i = i + ${wg}u) {
    let v = x[i] + d[i];
    x[i] = v;
    ss = ss + v * v;
  }
  red[lid.x] = ss;
  workgroupBarrier();
  for (var s = ${wg / 2}u; s > 0u; s = s >> 1u) {
    if (lid.x < s) { red[lid.x] = red[lid.x] + red[lid.x + s]; }
    workgroupBarrier();
  }
  let inv = inverseSqrt(red[0] / ${H}.0 + ${eps});
  for (var i = lid.x; i < ${H}u; i = i + ${wg}u) {
    y[i] = (1.0 + w[i]) * x[i] * inv;
  }
}`;
}

// KV-cache append as a kernel: kCache[pos] = kn, vCache[pos] = v — replaces
// two copyBufferToBuffer encoder ops (each of which broke the compute pass).
// pos comes from the attn uniform's word 0, which the engine writes as
// pos + 1 every step.
export function appendKVWGSL(n, wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read> kSrc: array<f32>;        // [${n}]
@group(0) @binding(1) var<storage, read> vSrc: array<f32>;        // [${n}]
@group(0) @binding(2) var<storage, read_write> kCache: array<f32>;
@group(0) @binding(3) var<storage, read_write> vCache: array<f32>;
@group(0) @binding(4) var<uniform> u: vec4<u32>;                  // u.x = pos + 1
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (gid.x >= ${n}u) { return; }
  let base = (u.x - 1u) * ${n}u;
  kCache[base + gid.x] = kSrc[gid.x];
  vCache[base + gid.x] = vSrc[gid.x];
}`;
}

// Per-head RMSNorm + partial RoPE for q or k. Reads the projection output
// in its native layout (q ships interleaved with its gate: [T, NH, 2*D]),
// writes [T, NH, D] contiguous. rotate_half convention over the first
// rotDim dims: out[d] = x[d]·cos[d] − x[d+r/2]·sin[d] (d < r/2),
//                out[d] = x[d]·cos[d] + x[d−r/2]·sin[d] (r/2 ≤ d < r).
export function qkNormRopeWGSL(nHeads, headDim, rotDim, srcStride, eps) {
  const D = headDim, R = rotDim;
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read> src: array<f32>;   // [T, ${nHeads}, ${srcStride}]
@group(0) @binding(1) var<storage, read> w: array<f32>;     // [${D}]
@group(0) @binding(2) var<storage, read> cosB: array<f32>;  // [T, ${R}]
@group(0) @binding(3) var<storage, read> sinB: array<f32>;  // [T, ${R}]
@group(0) @binding(4) var<storage, read_write> dst: array<f32>; // [T, ${nHeads}, ${D}]
var<workgroup> sh: array<f32, ${D}>;
var<workgroup> red: array<f32, ${D}>;
@compute @workgroup_size(${D})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let h = wid.x;
  let t = wid.y;
  let d = lid.x;
  let v = src[(t * ${nHeads}u + h) * ${srcStride}u + d];
  sh[d] = v;
  red[d] = v * v;
  workgroupBarrier();
  for (var s = ${D / 2}u; s > 0u; s = s >> 1u) {
    if (d < s) { red[d] = red[d] + red[d + s]; }
    workgroupBarrier();
  }
  let inv = inverseSqrt(red[0] / ${D}.0 + ${eps});
  let n = sh[d] * inv * (1.0 + w[d]);        // zero-centered norm weight
  // stash normalized vector for the rope pair lookup
  workgroupBarrier();
  sh[d] = n;
  workgroupBarrier();
  var o = n;
  if (d < ${R}u) {
    let c = cosB[t * ${R}u + d];
    let s2 = sinB[t * ${R}u + d];
    if (d < ${R / 2}u) { o = n * c - sh[d + ${R / 2}u] * s2; }
    else { o = n * c + sh[d - ${R / 2}u] * s2; }
  }
  dst[(t * ${nHeads}u + h) * ${D}u + d] = o;
}`;
}

// Causal prefill attention, one workgroup per (head, token). Positions and
// head dim both ≤ the 256-thread workgroup (T ≤ 256 prefill; the engine's
// decode path calls this with T = past+1 and computes only the last row via
// tOffset). GQA: q head h reads kv head h / (NH/NKV).
export function attnPrefillWGSL(nHeads, nKv, headDim, maxPos = 256) {
  const D = headDim, G = nHeads / nKv;
  const scale = 1 / Math.sqrt(headDim);
  if (D > 256 || maxPos > 256) throw new Error("attnPrefill assumes <=256 dims/positions");
  const WG = Math.max(D, maxPos);
  return /* wgsl */ `
struct P { T: u32, tOffset: u32, pad0: u32, pad1: u32 }
@group(0) @binding(0) var<storage, read> q: array<f32>;   // [T, ${nHeads}, ${D}]
@group(0) @binding(1) var<storage, read> k: array<f32>;   // [T, ${nKv}, ${D}]
@group(0) @binding(2) var<storage, read> v: array<f32>;   // [T, ${nKv}, ${D}]
@group(0) @binding(3) var<storage, read_write> o: array<f32>; // [Tq, ${nHeads}, ${D}]
@group(0) @binding(4) var<uniform> p: P;
var<workgroup> sc: array<f32, ${WG}>;
var<workgroup> red: array<f32, ${WG}>;
@compute @workgroup_size(${WG})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let h = wid.x;
  let tq = wid.y + p.tOffset;              // absolute query position
  let hk = h / ${G}u;
  let i = lid.x;
  // scores
  if (i < p.T) {
    var s = 0.0;
    if (i <= tq) {
      for (var d = 0u; d < ${D}u; d = d + 1u) {
        s = s + q[(tq * ${nHeads}u + h) * ${D}u + d] * k[(i * ${nKv}u + hk) * ${D}u + d];
      }
      s = s * ${scale};
    } else { s = -1e30; }
    sc[i] = s;
    red[i] = s;
  } else { sc[i] = -1e30; red[i] = -1e30; }
  workgroupBarrier();
  for (var s = ${WG / 2}u; s > 0u; s = s >> 1u) {
    if (i < s) { red[i] = max(red[i], red[i + s]); }
    workgroupBarrier();
  }
  let mx = red[0];
  workgroupBarrier();
  let e = select(0.0, exp(sc[i] - mx), sc[i] > -1e29);
  sc[i] = e;
  red[i] = e;
  workgroupBarrier();
  for (var s = ${WG / 2}u; s > 0u; s = s >> 1u) {
    if (i < s) { red[i] = red[i] + red[i + s]; }
    workgroupBarrier();
  }
  let denom = red[0];
  workgroupBarrier();
  // weighted V sum — thread i is now dim d
  if (i < ${D}u) {
    var acc = 0.0;
    for (var s = 0u; s <= tq; s = s + 1u) {
      acc = acc + sc[s] * v[(s * ${nKv}u + hk) * ${D}u + i];
    }
    o[(wid.y * ${nHeads}u + h) * ${D}u + i] = acc / denom;
  }
}`;
}

// dst = dst ⊙ src, elementwise (per-expert basis coefficient multiply etc.;
// slicing comes from bind-group offsets).
export function mulWGSL(wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> dst: array<f32>;
@group(0) @binding(1) var<storage, read> src: array<f32>;
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (gid.x < arrayLength(&dst)) { dst[gid.x] = dst[gid.x] * src[gid.x]; }
}`;
}

// Single-token causal depthwise conv step: one thread per channel. Rolling
// state holds the last ck-1 inputs; emits silu(w·[state|x]) and shifts x in.
export function convStepWGSL(convDim, ck, wg = 256) {
  const S = ck - 1;
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read> x: array<f32>;              // [${convDim}]
@group(0) @binding(1) var<storage, read> w: array<f32>;              // [${convDim}, ${ck}]
@group(0) @binding(2) var<storage, read_write> state: array<f32>;    // [${convDim}, ${S}]
@group(0) @binding(3) var<storage, read_write> y: array<f32>;        // [${convDim}]
fn silu(v: f32) -> f32 { return v / (1.0 + exp(-v)); }
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let c = gid.x;
  if (c >= ${convDim}u) { return; }
  var acc = w[c * ${ck}u + ${S}u] * x[c];
  for (var j = 0u; j < ${S}u; j = j + 1u) {
    acc = acc + w[c * ${ck}u + j] * state[c * ${S}u + j];
  }
  y[c] = silu(acc);
  for (var j = 0u; j < ${S - 1}u; j = j + 1u) {
    state[c * ${S}u + j] = state[c * ${S}u + j + 1u];
  }
  state[c * ${S}u + ${S - 1}u] = x[c];
}`;
}

// Single-token cached attention over an arbitrary-length KV cache: one
// workgroup per head, positions strided over 256 threads with a scores
// scratch buffer (three phases: score+max, exp+sum, dim-parallel weighted V).
export function attnDecodeWGSL(nHeads, nKv, headDim, maxCtx, wg = 256) {
  const D = headDim, G = nHeads / nKv;
  const scale = 1 / Math.sqrt(headDim);
  return /* wgsl */ `
struct P { nPos: u32, pad0: u32, pad1: u32, pad2: u32 }
@group(0) @binding(0) var<storage, read> q: array<f32>;       // [${nHeads}, ${D}]
@group(0) @binding(1) var<storage, read> kc: array<f32>;      // [${maxCtx}, ${nKv}, ${D}]
@group(0) @binding(2) var<storage, read> vc: array<f32>;      // [${maxCtx}, ${nKv}, ${D}]
@group(0) @binding(3) var<storage, read_write> scr: array<f32>; // [${nHeads}, ${maxCtx}]
@group(0) @binding(4) var<storage, read_write> o: array<f32>;   // [${nHeads}, ${D}]
@group(0) @binding(5) var<uniform> p: P;
var<workgroup> red: array<f32, ${wg}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let h = wid.x;
  let hk = h / ${G}u;
  let i = lid.x;
  var lmax = -1e30;
  for (var s = i; s < p.nPos; s = s + ${wg}u) {
    var sc = 0.0;
    for (var d = 0u; d < ${D}u; d = d + 1u) {
      sc = sc + q[h * ${D}u + d] * kc[(s * ${nKv}u + hk) * ${D}u + d];
    }
    sc = sc * ${scale};
    scr[h * ${maxCtx}u + s] = sc;
    lmax = max(lmax, sc);
  }
  red[i] = lmax;
  workgroupBarrier();
  for (var st = ${wg / 2}u; st > 0u; st = st >> 1u) {
    if (i < st) { red[i] = max(red[i], red[i + st]); }
    workgroupBarrier();
  }
  let mx = red[0];
  workgroupBarrier();
  storageBarrier();
  var lsum = 0.0;
  for (var s = i; s < p.nPos; s = s + ${wg}u) {
    let e = exp(scr[h * ${maxCtx}u + s] - mx);
    scr[h * ${maxCtx}u + s] = e;
    lsum = lsum + e;
  }
  red[i] = lsum;
  workgroupBarrier();
  for (var st = ${wg / 2}u; st > 0u; st = st >> 1u) {
    if (i < st) { red[i] = red[i] + red[i + st]; }
    workgroupBarrier();
  }
  let denom = red[0];
  workgroupBarrier();
  storageBarrier();
  if (i < ${D}u) {
    var acc = 0.0;
    for (var s = 0u; s < p.nPos; s = s + 1u) {
      acc = acc + scr[h * ${maxCtx}u + s] * vc[(s * ${nKv}u + hk) * ${D}u + i];
    }
    o[h * ${D}u + i] = acc / denom;
  }
}`;
}

// GPU router top-k: one workgroup of nExperts threads over the router
// logits. k rounds of argmax reduction (ties -> lowest index, matching the
// CPU reference's stable sort), then softmax over the selected logits —
// mathematically identical to full-softmax-then-renormalize-over-top-k.
// Writes idxOut (u32[k]) and wOut (f32[k]) consumed by the routed expert
// kernels in the SAME submit — no CPU round-trip.
export function routerTopKWGSL(nExperts = 256, topK = 8) {
  const N = nExperts;
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read> logits: array<f32>;    // [${N}]
@group(0) @binding(1) var<storage, read_write> idxOut: array<u32>; // [${topK}]
@group(0) @binding(2) var<storage, read_write> wOut: array<f32>;   // [${topK}]
var<workgroup> v: array<f32, ${N}>;
var<workgroup> ix: array<u32, ${N}>;
var<workgroup> taken: array<u32, ${N}>;
@compute @workgroup_size(${N})
fn main(@builtin(local_invocation_id) lid: vec3<u32>) {
  let i = lid.x;
  taken[i] = 0u;
  workgroupBarrier();
  for (var kk = 0u; kk < ${topK}u; kk = kk + 1u) {
    v[i] = select(logits[i], -3.0e38, taken[i] == 1u);
    ix[i] = i;
    workgroupBarrier();
    for (var s = ${N / 2}u; s > 0u; s = s >> 1u) {
      if (i < s) {
        if (v[i + s] > v[i] || (v[i + s] == v[i] && ix[i + s] < ix[i])) {
          v[i] = v[i + s];
          ix[i] = ix[i + s];
        }
      }
      workgroupBarrier();
    }
    if (i == 0u) {
      idxOut[kk] = ix[0];
      wOut[kk] = v[0];          // stash the logit; softmaxed below
      taken[ix[0]] = 1u;
    }
    workgroupBarrier();
  }
  if (i == 0u) {
    let m = wOut[0];            // top-1 logit == max
    var den = 0.0;
    for (var kk = 0u; kk < ${topK}u; kk = kk + 1u) {
      let p = exp(wOut[kk] - m);
      wOut[kk] = p;
      den = den + p;
    }
    for (var kk = 0u; kk < ${topK}u; kk = kk + 1u) {
      wOut[kk] = wOut[kk] / den;
    }
  }
}`;
}

// Demoted-basis coefficient multiply over routed slots: t1[slot,i] =
// src ⊙ c[routeIdx[slot]] where src is a shared t0 vector (gate/up: A@x is
// slot-invariant because x is h2) or t1 itself (down: per-slot input).
// Kept slots (dmask 0) are skipped — their t1 stays stale and the guarded
// B-accumulate never reads it.
export function routedCMulWGSL(r = 256, topK = 8, inPlace = false, wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> t1: array<f32>;   // [${topK}, ${r}]
@group(0) @binding(1) var<storage, read> cvec: array<f32>;       // [nExperts, ${r}]
@group(0) @binding(2) var<storage, read> routeIdx: array<u32>;
@group(0) @binding(3) var<storage, read> dmask: array<u32>;
${inPlace ? "" : "@group(0) @binding(4) var<storage, read> t0: array<f32>;"}
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let g = gid.x;
  if (g >= ${topK * r}u) { return; }
  let slot = g / ${r}u;
  let i = g % ${r}u;
  let e = routeIdx[slot];
  if (dmask[e] == 0u) { return; }
  t1[g] = ${inPlace ? "t1[g]" : "t0[i]"} * cvec[e * ${r}u + i];
}`;
}

// moe[i] += Σ_k wts[k] * dY[k*H + i] — the routed-expert weighted combine,
// one kernel for all topK slots (weights straight from the GPU router).
export function moeReduceWGSL(H, topK = 8, wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> moe: array<f32>;  // [${H}]
@group(0) @binding(1) var<storage, read> dY: array<f32>;         // [${topK}, ${H}]
@group(0) @binding(2) var<storage, read> wts: array<f32>;        // [${topK}]
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let i = gid.x;
  if (i >= ${H}u) { return; }
  var acc = moe[i];
  for (var k = 0u; k < ${topK}u; k = k + 1u) {
    acc = acc + wts[k] * dY[k * ${H}u + i];
  }
  moe[i] = acc;
}`;
}

// moeReduce + residual add + next-layer RMSNorm in ONE dispatch: the routed
// accumulate (exact moeReduceWGSL order: acc = moe[i], then += wts[k]*dY in
// k order), then v = x[i] + acc (exact addWGSL order), then rmsnorm into y.
// One workgroup like addRms; replaces an 8-wg reduce + a 1-wg addRms.
export function addRmsMoeWGSL(H, eps, topK = 8, wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> x: array<f32>;   // [${H}]
@group(0) @binding(1) var<storage, read> moe: array<f32>;       // [${H}]
@group(0) @binding(2) var<storage, read> dY: array<f32>;        // [${topK}, ${H}]
@group(0) @binding(3) var<storage, read> wts: array<f32>;       // [${topK}]
@group(0) @binding(4) var<storage, read> w: array<f32>;         // [${H}]
@group(0) @binding(5) var<storage, read_write> y: array<f32>;   // [${H}]
var<workgroup> red: array<f32, ${wg}>;
@compute @workgroup_size(${wg})
fn main(@builtin(local_invocation_id) lid: vec3<u32>) {
  var ss = 0.0;
  for (var i = lid.x; i < ${H}u; i = i + ${wg}u) {
    var acc = moe[i];
    for (var k = 0u; k < ${topK}u; k = k + 1u) {
      acc = acc + wts[k] * dY[k * ${H}u + i];
    }
    let v = x[i] + acc;
    x[i] = v;
    ss = ss + v * v;
  }
  red[lid.x] = ss;
  workgroupBarrier();
  for (var s = ${wg / 2}u; s > 0u; s = s >> 1u) {
    if (lid.x < s) { red[lid.x] = red[lid.x] + red[lid.x + s]; }
    workgroupBarrier();
  }
  let inv = inverseSqrt(red[0] / ${H}.0 + ${eps});
  for (var i = lid.x; i < ${H}u; i = i + ${wg}u) {
    y[i] = (1.0 + w[i]) * x[i] * inv;
  }
}`;
}

// ---- GPU-compacted sampling over the 248320-entry logits vector ----------
// The CPU sampler only ever looks at logits above (max - 12*temperature)
// (its tail prune), so instead of reading back the whole 1 MB vector we
// compute the global max on the GPU and atomically compact the above-
// threshold entries into a small (idx, logit) buffer — typically a few
// hundred entries, read back in one ~32 KB staging map. The CPU then runs
// the EXACT same top-p logic on the compacted set (with a deterministic
// (logit desc, idx asc) order); if the compaction overflows its cap the
// engine falls back to a full logits readback.

// partial[wid.x] = max over one `blk`-sized block of logits.
export function maxReduceWGSL(blk = 1024, wg = 256) {
  return /* wgsl */ `
struct P { n: u32, pad0: u32, pad1: u32, pad2: u32 }
@group(0) @binding(0) var<storage, read> logits: array<f32>;
@group(0) @binding(1) var<storage, read_write> partial: array<f32>;
@group(0) @binding(2) var<uniform> p: P;
var<workgroup> red: array<f32, ${wg}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let base = wid.x * ${blk}u;
  var m = -3.0e38;
  for (var i = base + lid.x; i < min(base + ${blk}u, p.n); i = i + ${wg}u) {
    m = max(m, logits[i]);
  }
  red[lid.x] = m;
  workgroupBarrier();
  for (var s = ${wg / 2}u; s > 0u; s = s >> 1u) {
    if (lid.x < s) { red[lid.x] = max(red[lid.x], red[lid.x + s]); }
    workgroupBarrier();
  }
  if (lid.x == 0u) { partial[wid.x] = red[0]; }
}`;
}

// mx[0] = max over the partials (one workgroup).
export function maxFinalWGSL(wg = 256) {
  return /* wgsl */ `
struct P { n: u32, pad0: u32, pad1: u32, pad2: u32 }
@group(0) @binding(0) var<storage, read> partial: array<f32>;
@group(0) @binding(1) var<storage, read_write> mx: array<f32>;
@group(0) @binding(2) var<uniform> p: P;
var<workgroup> red: array<f32, ${wg}>;
@compute @workgroup_size(${wg})
fn main(@builtin(local_invocation_id) lid: vec3<u32>) {
  var m = -3.0e38;
  for (var i = lid.x; i < p.n; i = i + ${wg}u) { m = max(m, partial[i]); }
  red[lid.x] = m;
  workgroupBarrier();
  for (var s = ${wg / 2}u; s > 0u; s = s >> 1u) {
    if (lid.x < s) { red[lid.x] = max(red[lid.x], red[lid.x + s]); }
    workgroupBarrier();
  }
  if (lid.x == 0u) { mx[0] = red[0]; }
}`;
}

// Append every (i, logits[i]) with logits[i] >= mx - thr. Writes past `cap`
// are dropped but still counted, so the host can detect overflow and fall
// back to the full readback.
export function logitCompactWGSL(cap, wg = 256) {
  return /* wgsl */ `
struct P { n: u32, thr: f32, pad0: u32, pad1: u32 }
struct Ctr { c: atomic<u32> }
@group(0) @binding(0) var<storage, read> logits: array<f32>;
@group(0) @binding(1) var<storage, read> mx: array<f32>;
@group(0) @binding(2) var<storage, read_write> ctr: Ctr;
@group(0) @binding(3) var<storage, read_write> outIdx: array<u32>;
@group(0) @binding(4) var<storage, read_write> outVal: array<f32>;
@group(0) @binding(5) var<uniform> p: P;
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let i = gid.x;
  if (i >= p.n) { return; }
  let v = logits[i];
  if (v >= mx[0] - p.thr) {
    let j = atomicAdd(&ctr.c, 1u);
    if (j < ${cap}u) {
      outIdx[j] = i;
      outVal[j] = v;
    }
  }
}`;
}

// attnOut[t,h,d] *= sigmoid(gate) where gate lives in the q-projection
// output at [t, h, D + d] (q_proj emits [query | gate] per head).
export function attnGateMulWGSL(nHeads, headDim, wg = 256) {
  const D = headDim;
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> o: array<f32>;  // [T, ${nHeads}, ${D}]
@group(0) @binding(1) var<storage, read> qg: array<f32>;       // [T, ${nHeads}, ${2 * D}]
struct P { tOffset: u32, pad0: u32, pad1: u32, pad2: u32 }
@group(0) @binding(2) var<uniform> p: P;
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (gid.x >= arrayLength(&o)) { return; }
  let td = gid.x / (${nHeads}u * ${D}u);       // output-relative token
  let rem = gid.x % (${nHeads}u * ${D}u);
  let h = rem / ${D}u;
  let d = rem % ${D}u;
  let g = qg[((td + p.tOffset) * ${nHeads}u + h) * ${2 * D}u + ${D}u + d];
  o[gid.x] = o[gid.x] * (1.0 / (1.0 + exp(-g)));
}`;
}
