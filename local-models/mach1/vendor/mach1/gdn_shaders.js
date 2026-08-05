// WGSL kernels for the Gated-DeltaNet (GDN) linear-attention layer —
// the WGSL port of gdn.js (which is validated against transformers on real
// Mach-1-Ternary-35B layer-0 weights; see test/make_gdn_ref.py).
//
// Layer pipeline (host in gdn_gpu.js):
//   1. qkv/z/a/b projections    — existing denseGemvWGSL, batched over T
//   2. causal depthwise conv+silu (convSiluWGSL)
//   3. per-(token, head) gate scalars: exp(g), beta (gdnScalarsWGSL)
//   4. sequential delta-rule recurrence (gdnRecurrenceWGSL) — the novel
//      kernel: one workgroup per v-head, one thread per state COLUMN j,
//      t-loop inside the dispatch. Per token: q/k head vectors are
//      l2-normalized via workgroup reductions, then each thread updates its
//      own S[:, j] column (decay → kv read → delta write → q readout).
//      State layout S[h][j][i] keeps a thread's column contiguous.
//   5. gated RMSNorm per (token, head) (gatedNormWGSL)
//   6. out_proj — denseGemvWGSL again
//
// All math f32 (torch reference is f32 too); tolerance contract, not
// bit-exact — accumulation orders differ. Config constants are baked into
// the generated WGSL (the pipeline cache keys on the code string).

const silu = /* wgsl */ `
fn silu(x: f32) -> f32 { return x / (1.0 + exp(-x)); }
`;

// One thread per (channel, token): y[t,c] = silu(Σ_j w[c,j] · x[t-ck+1+j, c]).
// Prefill form (all tokens parallel, zero left-pad); a decode-mode rolling
// window is the same math over the cached last ck-1 columns.
export function convSiluWGSL(convDim, ck, wg = 256) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read> x: array<f32>;      // [T, ${convDim}]
@group(0) @binding(1) var<storage, read> w: array<f32>;      // [${convDim}, ${ck}]
@group(0) @binding(2) var<storage, read_write> y: array<f32>;
${silu}
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let c = gid.x;
  let t = gid.y;
  if (c >= ${convDim}u) { return; }
  var acc = 0.0;
  for (var j = 0u; j < ${ck}u; j = j + 1u) {
    let tt = i32(t) - ${ck - 1} + i32(j);
    if (tt >= 0) { acc = acc + w[c * ${ck}u + j] * x[u32(tt) * ${convDim}u + c]; }
  }
  y[t * ${convDim}u + c] = silu(acc);
}`;
}

// One thread per (token, head): gexp = exp(-exp(A_log)·softplus(a+dt_bias)),
// beta = sigmoid(b). exp/log are implementation-precision — fine under the
// layer's tolerance contract.
export function gdnScalarsWGSL(nv, wg = 64) {
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read> a: array<f32>;      // [T, ${nv}]
@group(0) @binding(1) var<storage, read> b: array<f32>;      // [T, ${nv}]
@group(0) @binding(2) var<storage, read> aLog: array<f32>;   // [${nv}]
@group(0) @binding(3) var<storage, read> dtBias: array<f32>; // [${nv}]
@group(0) @binding(4) var<storage, read_write> gexp: array<f32>;
@group(0) @binding(5) var<storage, read_write> beta: array<f32>;
fn softplus(x: f32) -> f32 {
  if (x > 20.0) { return x; }
  return log(1.0 + exp(x));
}
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let idx = gid.x;
  if (idx >= arrayLength(&a)) { return; }
  let h = idx % ${nv}u;
  let g = -exp(aLog[h]) * softplus(a[idx] + dtBias[h]);
  gexp[idx] = exp(g);
  beta[idx] = 1.0 / (1.0 + exp(-b[idx]));
}`;
}

// The recurrence. Workgroup = one v-head (dispatch nv groups), thread j owns
// state column S[h][j][:] (dk floats, contiguous). Sequential t-loop inside.
// `fusedScalars`: the gate scalars (gdnScalarsWGSL) are computed INLINE from
// the raw a/b projections instead of read from gexp/beta buffers — bindings
// 1/2 become ab ([T, 2*nv]: the wA+wB GEMVs merged into one output) plus
// aLog/dtBias. Same expressions, same builtins, one fewer dispatch and no
// gexp/beta round-trip. Every thread evaluates the two scalars redundantly
// (a handful of transcendentals per token — cheaper than a barrier).
// `fusedNorm: eps` — the gated RMSNorm (gatedNormWGSL) runs in the
// recurrence's epilogue: each head's core vector is already distributed one
// element per thread, so the norm is one more shared-memory reduction and
// the separate dispatch (plus the core round-trip through memory) goes
// away. Same expressions as gatedNormWGSL, including the PLAIN w (gated
// norm is w*x, not (1+w)*x — see the rmsnorm note).
export function gdnRecurrenceWGSL(cfg, T, { fusedScalars = false,
  fusedNorm = 0 } = {}) {
  const { linear_num_value_heads: nv, linear_num_key_heads: nk,
    linear_key_head_dim: dk, linear_value_head_dim: dv } = cfg;
  const Dk = nk * dk, Dv = nv * dv;
  const convDim = 2 * Dk + Dv;
  const rep = nv / nk;
  const scale = 1 / Math.sqrt(dk);
  if (dv < dk) throw new Error("recurrence kernel assumes dv >= dk threads for the reductions");
  if (fusedNorm && T !== 1) throw new Error("fusedNorm assumes T=1");
  const SC = fusedScalars ? `
@group(0) @binding(1) var<storage, read> ab: array<f32>;     // [T, ${2 * nv}]
@group(0) @binding(2) var<storage, read> aLog: array<f32>;   // [${nv}]
@group(0) @binding(5) var<storage, read> dtBias: array<f32>; // [${nv}]
fn softplus(x: f32) -> f32 {
  if (x > 20.0) { return x; }
  return log(1.0 + exp(x));
}` : `
@group(0) @binding(1) var<storage, read> gexp: array<f32>;   // [T, ${nv}]
@group(0) @binding(2) var<storage, read> beta: array<f32>;   // [T, ${nv}]`;
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read> conv: array<f32>;   // [T, ${convDim}]${SC}
@group(0) @binding(3) var<storage, read_write> S: array<f32>;    // [${nv}, ${dv}, ${dk}]
${fusedNorm ? `@group(0) @binding(4) var<storage, read_write> normed: array<f32>; // [T, ${Dv}]
@group(0) @binding(6) var<storage, read> zg: array<f32>;      // [T, ${Dv}]
@group(0) @binding(7) var<storage, read> nw: array<f32>;      // [${dv}]
fn silu_(x: f32) -> f32 { return x / (1.0 + exp(-x)); }
var<workgroup> nred: array<f32, ${dv}>;`
  : `@group(0) @binding(4) var<storage, read_write> core: array<f32>; // [T, ${Dv}]`}
var<workgroup> qsh: array<f32, ${dk}>;
var<workgroup> ksh: array<f32, ${dk}>;
var<workgroup> red: array<f32, ${dk}>;
var<workgroup> invQ: f32;
var<workgroup> invK: f32;
@compute @workgroup_size(${dv})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let h = wid.x;
  let hk = h / ${rep}u;                        // repeat_interleave of k-heads
  let j = lid.x;
  let sBase = (h * ${dv}u + j) * ${dk}u;
  for (var t = 0u; t < ${T}u; t = t + 1u) {
    // ---- load + l2norm q and k for this (t, head) — FLA eps INSIDE sqrt
    if (j < ${dk}u) {
      let q = conv[t * ${convDim}u + hk * ${dk}u + j];
      let k = conv[t * ${convDim}u + ${Dk}u + hk * ${dk}u + j];
      qsh[j] = q;
      ksh[j] = k;
      red[j] = q * q;
    }
    workgroupBarrier();
    for (var s = ${dk / 2}u; s > 0u; s = s >> 1u) {
      if (j < s) { red[j] = red[j] + red[j + s]; }
      workgroupBarrier();
    }
    if (j == 0u) { invQ = inverseSqrt(red[0] + 1e-6); }
    workgroupBarrier();
    if (j < ${dk}u) { red[j] = ksh[j] * ksh[j]; }
    workgroupBarrier();
    for (var s = ${dk / 2}u; s > 0u; s = s >> 1u) {
      if (j < s) { red[j] = red[j] + red[j + s]; }
      workgroupBarrier();
    }
    if (j == 0u) { invK = inverseSqrt(red[0] + 1e-6); }
    workgroupBarrier();
    if (j < ${dk}u) {
      qsh[j] = qsh[j] * invQ * ${scale};
      ksh[j] = ksh[j] * invK;
    }
    workgroupBarrier();
    // ---- column phase: thread j owns S[h][j][*]
${fusedScalars ? `    let g_ = -exp(aLog[h]) * softplus(ab[t * ${2 * nv}u + h] + dtBias[h]);
    let gt = exp(g_);
    let bt = 1.0 / (1.0 + exp(-ab[t * ${2 * nv}u + ${nv}u + h]));` : `    let gt = gexp[t * ${nv}u + h];
    let bt = beta[t * ${nv}u + h];`}
    var kv = 0.0;
    for (var i = 0u; i < ${dk}u; i = i + 1u) {
      let s = S[sBase + i] * gt;
      S[sBase + i] = s;
      kv = kv + s * ksh[i];
    }
    let delta = (conv[t * ${convDim}u + ${2 * Dk}u + h * ${dv}u + j] - kv) * bt;
    var o = 0.0;
    for (var i = 0u; i < ${dk}u; i = i + 1u) {
      let s = S[sBase + i] + ksh[i] * delta;
      S[sBase + i] = s;
      o = o + s * qsh[i];
    }
${fusedNorm ? `    // gated RMSNorm fused in: same math as gatedNormWGSL, same dispatch
    // (core is not materialized — normed is this kernel's only output)
    nred[j] = o * o;
    workgroupBarrier();
    for (var s2 = ${dv / 2}u; s2 > 0u; s2 = s2 >> 1u) {
      if (j < s2) { nred[j] = nred[j] + nred[j + s2]; }
      workgroupBarrier();
    }
    let ninv = inverseSqrt(nred[0] / ${dv}.0 + ${fusedNorm});
    normed[t * ${Dv}u + h * ${dv}u + j] = o * ninv * nw[j]
      * silu_(zg[t * ${Dv}u + h * ${dv}u + j]);
` : `    core[t * ${Dv}u + h * ${dv}u + j] = o;
`}    workgroupBarrier();                        // qsh/ksh reused next token
  }
}`;
}

// Gated RMSNorm per (token, head): out = core/rms(core) · w · silu(z).
export function gatedNormWGSL(nv, dv, eps) {
  const Dv = nv * dv;
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read> core: array<f32>;   // [T, ${Dv}]
@group(0) @binding(1) var<storage, read> z: array<f32>;      // [T, ${Dv}]
@group(0) @binding(2) var<storage, read> w: array<f32>;      // [${dv}]
@group(0) @binding(3) var<storage, read_write> y: array<f32>;
${silu}
var<workgroup> red: array<f32, ${dv}>;
@compute @workgroup_size(${dv})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let h = wid.x;
  let t = wid.y;
  let j = lid.x;
  let base = t * ${Dv}u + h * ${dv}u;
  let v = core[base + j];
  red[j] = v * v;
  workgroupBarrier();
  for (var s = ${dv / 2}u; s > 0u; s = s >> 1u) {
    if (j < s) { red[j] = red[j] + red[j + s]; }
    workgroupBarrier();
  }
  let inv = inverseSqrt(red[0] / ${dv}.0 + ${eps});
  y[base + j] = v * inv * w[j] * silu(z[base + j]);
}`;
}
