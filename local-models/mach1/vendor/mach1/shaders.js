// WGSL kernels for the Mach-1-Ternary-35B packed format
// (SyzygyResearch/Mach-1-Ternary-35B).
//
// Expert tier — one generated code path per codec parameter set:
//   experts: K=1.375, V=8, L=16, 15-bit F32 Lloyd LUT (codec_name v8b15g);
//   the same generator still covers the additive release's K=1.5 experts
//   and K=4/V=2 spine — only the parameter set changes.
//
// Expert format recap (decode.py is the executable spec):
//  * a weight matrix is cut into 16x16 tiles; each tile is a T=256 scalar
//    sequence emitted V scalars at a time by an L-bit shift register
//  * the register at step j is a sliding L-bit window at bit j*(K*V) of the
//    tile's T*K-bit stream (MSB-first big-endian u16 words, tail-biting)
//  * state s -> LUT row (s*(s+1) >> (16-tlut_bits-1)) & mask, component 0
//    negated iff bit 15 of s*(s+1)
//  * W = diag(sv) . H_m . (f16(unit) [* wscale]) . H_n . diag(su)
//    kept experts: continuous fp16 su/sv, no wscale (absorbed in sv);
//    demoted: ±1 su/sv + scalar wscale + rank-r basis W += (B ⊙ c) @ A
//
// The fused GEMV never materializes W: y = sv * H_m( U . H_n(su * x) ) * ws,
// where U's entries stream out of the 1.375-bit trellis on the fly.
//
// NE tier (attn/GDN/shared-expert linears + lm_head) — transform-free Lloyd
// bitshift trellis (decode.py::decode_ne_ll_tensor): s_t = ((s_{t-1} << k) |
// b_t) & (2^12 - 1); W[r,t] = f32(lut[s_t]) * f32(gscale[r, t/128]). Because
// the register is PURELY shifted-in bits, state t is just the 12 stream bits
// ending at bit (t+1)*k (zero-padded before bit 0) — random access, no
// sequential dependency, no tail-biting.

const fr = Math.fround;

// Exact f32 literal (emitted as a bitcast so WGSL parsing cannot re-round).
function f32lit(x) {
  const b = new Uint32Array(new Float32Array([fr(x)]).buffer)[0];
  return `bitcast<f32>(0x${b.toString(16).padStart(8, "0")}u)`;
}

// Software correctly-rounded f32 division by a positive normal CONSTANT.
// WGSL only guarantees 2.5 ulp for `/` (SwiftShader is measurably 1 ulp off),
// but the reference decode divides by f32(sqrt(dim)) with IEEE semantics, so
// bit-exactness requires doing the division in integer arithmetic: 27-bit
// restoring long division of the mantissas + round-to-nearest-even with a
// sticky bit from the remainder.
function divConstWGSL(name, cval) {
  const bits = new Uint32Array(new Float32Array([fr(cval)]).buffer)[0];
  const EC = (bits >>> 23) & 0xff;
  const MC = (bits & 0x7fffff) | 0x800000;
  return /* wgsl */ `
fn ${name}(x: f32) -> f32 {
  let xu = bitcast<u32>(x);
  let sgn = xu & 0x80000000u;
  let ax = xu & 0x7FFFFFFFu;
  if (ax == 0u) { return bitcast<f32>(sgn); }            // ±0
  let ex = ax >> 23u;
  if (ex == 0u || ex == 255u) { return x / ${f32lit(cval)}; } // sub/inf/nan: punt
  let mx = (ax & 0x7FFFFFu) | 0x800000u;
  var eq = i32(ex) - ${EC} + 127;
  var rem = mx;
  var q = 0u;
  for (var i = 0u; i < 27u; i = i + 1u) {                // q = 27-bit quotient
    q = q << 1u;
    if (rem >= ${MC}u) { rem = rem - ${MC}u; q = q | 1u; }
    rem = rem << 1u;
  }
  var shift = 3u;                                        // q in [2^25, 2^27)
  if (q < 0x4000000u) { shift = 2u; eq = eq - 1; }       // quotient < 1
  let low = q & ((1u << shift) - 1u);
  var mant = q >> shift;                                 // 24 bits
  let mid = 1u << (shift - 1u);
  if (low > mid || (low == mid && (rem != 0u || (mant & 1u) == 1u))) {
    mant = mant + 1u;
    if (mant == 0x1000000u) { mant = 0x800000u; eq = eq + 1; }
  }
  if (eq <= 0 || eq >= 255) { return x / ${f32lit(cval)}; } // out of normal range
  return bitcast<f32>(sgn | (u32(eq) << 23u) | (mant & 0x7FFFFFu));
}`;
}

// Shared helpers: u16 reads from a u32-packed buffer named `trellis`,
// bit reads (MSB-first within big-endian u16 words), and the fp16 spec
// rounding (IEEE RNE f32->f16->f32, done in integer arithmetic so it is
// deterministic on every backend — no shader-f16 feature required).
const COMMON = (c) => /* wgsl */ `
fn read_u16(idx: u32) -> u32 {
  let w = trellis[idx >> 1u];
  return (w >> ((idx & 1u) * 16u)) & 0xFFFFu;
}
fn tile_bit(wordBase: u32, pos0: u32) -> u32 {
  var pos = pos0;
  if (pos >= ${c.NBITS}u) { pos = pos - ${c.NBITS}u; }   // tail-biting wrap
  let w = read_u16(wordBase + (pos >> 4u));
  return (w >> (15u - (pos & 15u))) & 1u;
}
fn f16_to_f32(h: u32) -> f32 {
  let sgn = select(1.0, -1.0, (h & 0x8000u) != 0u);
  let e = (h >> 10u) & 0x1Fu;
  let m = h & 0x3FFu;
  if (e == 0u) { return sgn * ldexp(f32(m), -24); }      // subnormal (exact)
  return sgn * ldexp(f32(m + 1024u), i32(e) - 25);       // normal (exact)
}
fn f16_round(x: f32) -> f32 {
  let u = bitcast<u32>(x);
  let sign16 = (u >> 16u) & 0x8000u;
  let a = u & 0x7FFFFFFFu;
  var h: u32;
  if (a >= 0x47800000u) {                                // overflow -> inf/nan
    h = select(sign16 | 0x7C00u, sign16 | 0x7E00u, a > 0x7F800000u);
  } else if (a < 0x38800000u) {                          // f16-subnormal range
    // q = round(m32 * 2^(e-126)) onto the 2^-24 subnormal grid
    let shift = 126u - (a >> 23u);
    if (shift > 24u) { h = sign16; }                     // underflow to zero
    else {
      let mant = (a & 0x7FFFFFu) | 0x800000u;
      let q = mant >> shift;
      let rem = mant & ((1u << shift) - 1u);
      let mid = 1u << (shift - 1u);
      var r = q;
      if (rem > mid || (rem == mid && (q & 1u) == 1u)) { r = r + 1u; }
      h = sign16 | r;
    }
  } else {                                               // normal, RNE on 13 bits
    let e = ((a >> 23u) - 112u) << 10u;
    var hh = sign16 | (e & 0x7C00u) | ((a >> 13u) & 0x3FFu);
    let rem = a & 0x1FFFu;
    if (rem > 0x1000u || (rem == 0x1000u && (hh & 1u) == 1u)) { hh = hh + 1u; }
    h = hh;
  }
  return f16_to_f32(h);
}
fn lut_row_neg(s: u32) -> vec2<u32> {
  let p = s * (s + 1u);                    // s < 2^16 -> exact in u32
  let row = (p >> ${c.TLUT_SHIFT}u) & ${c.TLUT_MASK}u;
  let neg = (p >> 15u) & 1u;
  return vec2<u32>(row, neg);
}
`;

// Derived per-codec constants.
export function codecConsts(cb) {
  const T = cb.td_x * cb.td_y;
  return {
    V: cb.V, L: cb.L, T,
    STEP: cb.K * cb.V,
    NBITS: T * cb.K,
    NSTEP: T / cb.V,
    WORDS_PER_TILE: (T * cb.K) / 16,
    TLUT_SHIFT: 16 - cb.tlut_bits - 1,
    TLUT_MASK: (1 << cb.tlut_bits) - 1,
    REG_MASK: (1 << cb.L) - 1,
  };
}

// ------------------------------------------------------------------------
// Kernel 1: DEQUANT. One thread per register state -> V weights of the
// codebook-unit matrix, f16-rounded and scaled (the pre-RHT tensor).
// Batched over experts: gid.x spans experts * ntiles * NSTEP states.
// ------------------------------------------------------------------------
export function decodeUnitWGSL(cb, opts = {}) {
  // opts.gamma (additive v3t container): the per-expert scale becomes a
  // per-TILE scale gamma[expert, waveIdx[tile]] — binding 4 holds gamma
  // [nExperts, ntx+nty] f32 (f16-exact values) and binding 5 the tile ->
  // wavefront index map [ntiles] u32 (host-computed, decode.py
  // wave_index_map verbatim). W = f16_round(val) * g is then ONE correctly
  // rounded f32 multiply — identical to fr(f16Round(val) * gamma).
  const gamma = !!opts.gamma;
  const c = codecConsts(cb);
  return /* wgsl */ `
struct Meta {
  ntx: u32,          // tiles down (m/16)
  nty: u32,          // tiles across (n/16)
  nExperts: u32,
  pad0: u32,
}
@group(0) @binding(0) var<storage, read> trellis: array<u32>;
@group(0) @binding(1) var<storage, read> tlut: array<f32>;
@group(0) @binding(2) var<storage, read_write> W: array<f32>;
@group(0) @binding(3) var<uniform> mp: Meta;
@group(0) @binding(4) var<storage, read> wscales: array<f32>;
${gamma ? "@group(0) @binding(5) var<storage, read> waveIdx: array<u32>;" : ""}
${COMMON(c)}
@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let ntiles = mp.ntx * mp.nty;
  let statesPerExpert = ntiles * ${c.NSTEP}u;
  let g = gid.x;
  if (g >= statesPerExpert * mp.nExperts) { return; }
  let expert = g / statesPerExpert;
  let rem = g % statesPerExpert;
  let tile = rem / ${c.NSTEP}u;
  let j = rem % ${c.NSTEP}u;
  let n = mp.nty * 16u;
  let wordBase = (expert * ntiles + tile) * ${c.WORDS_PER_TILE}u;
  // register state j = sliding L-bit window at bit j*STEP (tail-biting)
  var s = 0u;
  let start = j * ${c.STEP}u;
  for (var b = 0u; b < ${c.L}u; b = b + 1u) {
    s = (s << 1u) | tile_bit(wordBase, start + b);
  }
  let rn = lut_row_neg(s);
  let ti = tile / mp.nty;
  let tj = tile % mp.nty;
  ${gamma
    ? "let ws = wscales[expert * (mp.ntx + mp.nty) + waveIdx[tile]];"
    : "let ws = wscales[expert];"}
  let outBase = expert * (mp.ntx * 16u) * n;
  for (var v = 0u; v < ${c.V}u; v = v + 1u) {
    var val = tlut[rn.x * ${c.V}u + v];
    if (v == 0u && rn.y == 1u) { val = -val; }
    let idx = j * ${c.V}u + v;
    let rr = ti * 16u + (idx >> 4u);
    let cc = tj * 16u + (idx & 15u);
    W[outBase + rr * n + cc] = f16_round(val) * ws;
  }
}`;
}

// ------------------------------------------------------------------------
// Kernel 2: FWHT. Orthonormal Walsh-Hadamard butterfly over vectors of
// length DIM (in workgroup shared memory), with optional pre/post sign
// vectors and a per-expert final scale. Exact op order of the reference:
// butterflies span 1,2,4,... then ONE f32 division by f32(sqrt(f32(DIM))).
// Vector addressing supports row and column passes over batched matrices:
//   base = (vec / vecsPerExpert)*expertStride + (vec % vecsPerExpert)*vecStride
// signMode: 0 none, 1 multiply before the transform, 2 multiply after.
// ------------------------------------------------------------------------
// `routed` (engine fast path): the sign/scale EXPERT index comes from a
// routeIdx buffer (GPU top-k output) instead of the vector index — the data
// stays slot-major [topK, dim] while signs/scales address the routed expert's
// row of the layer-concatenated buffers. routed=1 reads scales[0] (unit-scale
// input pass, `ones` bound); routed=2 reads scales[re*scaleStride] (wscale
// output pass). `bcast` loads the input from a single shared src vector
// (binding 5) so h2 fans out to all slots without a broadcast copy.
// `pair: N` (routed modes): slot s >= 8 addresses expert routeIdx[s-8] + N
// (the gate|up concatenated buffers — see expertGemvUnrolledWGSL).
export function fwhtWGSL(dim, wg = 256, opts = {}) {
  const routed = opts.routed || 0;
  const bcast = !!opts.bcast;
  const pair = opts.pair | 0;
  const ss = opts.scaleStride || 1;
  const scaleExpr = routed === 1 ? "scales[0]"
    : routed === 2 ? `scales[re * ${ss}u]` : "scales[expert]";
  return /* wgsl */ `
struct P {
  nvec: u32,
  vecsPerExpert: u32,
  expertStride: u32,
  vecStride: u32,
  elemStride: u32,
  signMode: u32,
  gridX: u32,          // x-extent of the 2D dispatch (nvec can exceed 65535)
  pad1: u32,
}
@group(0) @binding(0) var<storage, read_write> data: array<f32>;
@group(0) @binding(1) var<storage, read> signs: array<f32>;   // [nExperts*DIM]
@group(0) @binding(2) var<uniform> p: P;
@group(0) @binding(3) var<storage, read> scales: array<f32>;  // [nExperts]
${routed ? "@group(0) @binding(4) var<storage, read> routeIdx: array<u32>;" : ""}
${bcast ? `@group(0) @binding(${routed ? 5 : 4}) var<storage, read> srcv: array<f32>;` : ""}
${divConstWGSL("div_sqrtdim", Math.sqrt(fr(dim)))}
var<workgroup> sh: array<f32, ${dim}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  // one workgroup per vector, 2D grid (65535-per-dimension dispatch limit)
  let vidx = wid.y * p.gridX + wid.x;
  if (vidx >= p.nvec) { return; }        // uniform per-workgroup: barriers safe
  let expert = vidx / p.vecsPerExpert;
  let base = expert * p.expertStride + (vidx % p.vecsPerExpert) * p.vecStride;
  ${pair ? `let re = routeIdx[expert & 7u] + select(0u, ${pair}u, expert >= 8u);`
    : routed ? "let re = routeIdx[expert];" : ""}
  let sBase = ${routed ? "re" : "expert"} * ${dim}u;
  for (var i = lid.x; i < ${dim}u; i = i + ${wg}u) {
    var v = ${bcast ? "srcv[i]" : "data[base + i * p.elemStride]"};
    if (p.signMode == 1u) { v = v * signs[sBase + i]; }
    sh[i] = v;
  }
  workgroupBarrier();
  var span = 1u;
  while (span < ${dim}u) {
    for (var pr = lid.x; pr < ${dim / 2}u; pr = pr + ${wg}u) {
      let blk = pr / span;
      let k = pr % span;
      let i = blk * 2u * span + k;
      let a = sh[i];
      let b = sh[i + span];
      sh[i] = a + b;
      sh[i + span] = a - b;
    }
    workgroupBarrier();
    span = span << 1u;
  }
  let sc = ${scaleExpr};
  for (var i = lid.x; i < ${dim}u; i = i + ${wg}u) {
    var v = div_sqrtdim(sh[i]);
    if (p.signMode == 2u) { v = v * signs[sBase + i]; }
    data[base + i * p.elemStride] = v * sc;
  }
}`;
}

// ------------------------------------------------------------------------
// TWO-PASS FWHT for vectors too large for one workgroup's shared memory.
// fwhtWGSL holds the whole vector in `var<workgroup>` (dim*4 bytes), so the
// additive spine's dim = 8192 (in_proj_qkv / q_proj) needs 32 KB against a
// 16 KB default limit. The pipeline then fails to CREATE, and WebGPU makes
// every dispatch using it a silent no-op — the model runs on zeros and emits
// uniform-random tokens. gpu.js asks the adapter for its real limit; this is
// the fallback when even that is not enough.
//
// Factor dim = R * C with C the largest power of two that fits. Sylvester
// order means H_dim = H_R (x) H_C, so viewing the vector as [R][C]:
//   row pass  -> butterflies at span 1..C/2   (never cross a row boundary)
//   col pass  -> butterflies at span C..dim/2 (stride-C gather down a column)
// which is EXACTLY the one-pass kernel's span order, with the single
// normalization divide kept at the very end. Results are bit-identical.
//
// Sign vectors index the FLAT vector in both passes: `preSign` (the one-pass
// signMode 1) belongs to the row pass, `postSign` (signMode 2) to the col
// pass, after the divide. The col pass always applies scales[0], so pass a
// ones-buffer when there is no scale.
// `bcast` (input-RHT fast path): the row pass READS from a separate source
// vector (binding after signs) instead of data, so H_n(su * x) needs no
// staging copy of x — the same contract as fwhtWGSL's bcast. This lets the
// one-workgroup input RHTs (2048/4096) use the wide two-pass split: same
// butterflies in the same order, bit-identical, but dim/C + C workgroups
// instead of 1.
// `routed` (both split passes): wid.y is a SLOT into slot-major [nslots, dim]
// data — dispatch [dim/C, nslots] (row) / [C, nslots] (col) — and the
// sign/scale expert index comes from routeIdx (same contract as fwhtWGSL's
// routed modes). With bcast the SOURCE stays a single shared vector (h2
// fanning out to all slots), only signs/data are per-slot.
export function fwhtSplitRowWGSL(dim, C, { preSign = false, bcast = false,
  routed = false, pair = 0, wg = 256 } = {}) {
  const useRI = routed && preSign;   // routeIdx only feeds the sign base
  let nb = 1;
  const B = {
    signs: preSign ? nb++ : 0,
    srcv: bcast ? nb++ : 0,
    routeIdx: useRI ? nb++ : 0,
  };
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> data: array<f32>;
${preSign ? `@group(0) @binding(${B.signs}) var<storage, read> signs: array<f32>;` : ""}
${bcast ? `@group(0) @binding(${B.srcv}) var<storage, read> srcv: array<f32>;` : ""}
${useRI ? `@group(0) @binding(${B.routeIdx}) var<storage, read> routeIdx: array<u32>;` : ""}
var<workgroup> sh: array<f32, ${C}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let flat = wid.x * ${C}u;
  let base = ${routed ? `wid.y * ${dim}u + flat` : "flat"};
  ${routed && preSign ? (pair
    ? `let sBase = (routeIdx[wid.y & 7u] + select(0u, ${pair}u, wid.y >= 8u)) * ${dim}u;`
    : `let sBase = routeIdx[wid.y] * ${dim}u;`) : ""}
  for (var i = lid.x; i < ${C}u; i = i + ${wg}u) {
    var v = ${bcast ? "srcv[flat + i]" : "data[base + i]"};
    ${preSign ? `v = v * signs[${routed ? "sBase + flat" : "flat"} + i];` : ""}
    sh[i] = v;
  }
  workgroupBarrier();
  var span = 1u;
  while (span < ${C}u) {
    for (var pr = lid.x; pr < ${C / 2}u; pr = pr + ${wg}u) {
      let blk = pr / span;
      let k = pr % span;
      let i = blk * 2u * span + k;
      let a = sh[i];
      let b = sh[i + span];
      sh[i] = a + b;
      sh[i + span] = a - b;
    }
    workgroupBarrier();
    span = span << 1u;
  }
  for (var i = lid.x; i < ${C}u; i = i + ${wg}u) { data[base + i] = sh[i]; }
}`;
}

export function fwhtSplitColWGSL(dim, C, { postSign = false, routed = false,
  routedScale = false, scaleStride = 1, wg = 64 } = {}) {
  const R = dim / C;
  const useRI = routed && (postSign || routedScale);  // routeIdx for signs/scale
  let nb = 1;
  const B = { signs: postSign ? nb++ : 0, scales: nb++, routeIdx: useRI ? nb++ : 0 };
  return /* wgsl */ `
@group(0) @binding(0) var<storage, read_write> data: array<f32>;
${postSign ? `@group(0) @binding(${B.signs}) var<storage, read> signs: array<f32>;` : ""}
@group(0) @binding(${B.scales}) var<storage, read> scales: array<f32>;
${useRI ? `@group(0) @binding(${B.routeIdx}) var<storage, read> routeIdx: array<u32>;` : ""}
${divConstWGSL("div_sqrtdim", Math.sqrt(fr(dim)))}
var<workgroup> sh: array<f32, ${R}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let col = wid.x;
  let base = ${routed ? `wid.y * ${dim}u` : "0u"};
  ${useRI ? "let re = routeIdx[wid.y];" : ""}
  for (var i = lid.x; i < ${R}u; i = i + ${wg}u) { sh[i] = data[base + i * ${C}u + col]; }
  workgroupBarrier();
  var span = 1u;
  while (span < ${R}u) {
    for (var pr = lid.x; pr < ${Math.max(1, R / 2)}u; pr = pr + ${wg}u) {
      let blk = pr / span;
      let k = pr % span;
      let i = blk * 2u * span + k;
      let a = sh[i];
      let b = sh[i + span];
      sh[i] = a + b;
      sh[i + span] = a - b;
    }
    workgroupBarrier();
    span = span << 1u;
  }
  let sc = ${routed && routedScale ? `scales[re * ${scaleStride}u]` : "scales[0]"};
  for (var i = lid.x; i < ${R}u; i = i + ${wg}u) {
    let flat = i * ${C}u + col;
    var v = div_sqrtdim(sh[i]);
    ${postSign ? `v = v * signs[${routed ? `re * ${dim}u + flat` : "flat"}];` : ""}
    data[base + flat] = v * sc;
  }
}`;
}

// ------------------------------------------------------------------------
// Kernel 3: FUSED GEMV core, t = U . xhat, straight from the packed bits —
// the weight matrix is never materialized. One workgroup per (tile-row,
// expert); threads stride the tiles along n, decoding the register
// sequentially (sliding window == shift register, so the whole tile costs
// one 16-bit seed + (T/V - 1) refills from a rolling bit buffer).
// The LUT rows are integer vectors: each weight contributes ±1..±c adds of
// an activation — the add/subtract-only property of the codec. On GPU the
// accumulate is an FMA, but the memory traffic is the 1.5-bit stream.
// ------------------------------------------------------------------------
// `routed` (engine fast path): wid.y is a SLOT index into slot-major x/y
// buffers; the trellis expert is routeIdx[slot], addressing one expert's
// packed bits inside the layer-concatenated trellis buffer.
// `tlutF16` (V=8 only): the codebook is bound as f16 pairs packed in
// vec4<u32> rows — ONE 16-byte load per state instead of a 32-byte f32 row.
// Bit-equivalent: the f32 table is f16-pre-rounded on the host (see
// prepare()), so unpack2x16float yields the exact same values.
// `dual`: each thread walks TWO independent state chains interleaved —
// chain 0 seeds at word 0 (states 0..NSTEP/2-1), chain 1 seeds mid-stream
// (states NSTEP/2..): the register is a sliding window, so a mid-tile seed
// is just the 16 bits at bit (NSTEP/2)*STEP, which lands exactly on a u16
// boundary when (NSTEP/2)*STEP % 16 == 0 (v8b15g: 16*11 = 176 = word 11).
// The serial walk is the latency bottleneck; two chains give the scheduler
// independent gathers to overlap. Per-row accumulation order is unchanged
// (each row's states stay consecutive within one chain) — outputs are
// bit-identical to the single-chain kernel.
export function fusedGemvWGSL(cb, wg = 128, opts = {}) {
  const routed = !!opts.routed;
  const tlutF16 = !!opts.tlutF16;
  const dual = !!opts.dual;
  // opts.gamma (additive v3t): each 16x16 tile's contribution is scaled by
  // gamma[te, waveIdx[tile]]. The scale is folded into the tile's x window
  // (xg) once per tile — associativity-free placement is not required here,
  // the fused GEMV carries a tolerance contract vs f64 (dequant carries the
  // bit-exact one).
  const gamma = !!opts.gamma;
  // opts.int4 (additive release only): the expert alphabet is an exact scaled
  // integer lattice — 10 levels, step * {-5..4} — so an 8-value codebook row
  // packs into 8 NIBBLES (one u32, 4 B) instead of 8 f16 (vec4<u32>, 16 B).
  // The random codebook gather is this kernel's hot spot, so cutting it 4x
  // (and the table 512 KB -> 128 KB) is the single biggest lever available:
  // MEASURED 1.95x vs tlutF16 at 512x2048/E=8 on apple metal-3, outputs
  // agreeing to 2e-4. Levels are baked as shader constants — no extra binding,
  // no extra traffic.
  //   {int4: {ints, step}}                  -> nibble gather, levels*step FMA
  //   {int4: {ints, step, additive: true}}  -> nibble gather, ADD/SUB ONLY
  // The additive form is the honest multiply-free execution (one lattice-step
  // multiply per OUTPUT, in the epilogue). It is ~2.5x slower than the FMA
  // form because a GPU FMA is one instruction and the shift-add replacement is
  // ~6 — multiply-free is an ASIC/FPGA area argument, not a GPU one. Keep it
  // as a demonstrable toggle, not the default.
  const int4 = opts.int4 || null;
  const int4add = !!(int4 && int4.additive);
  if (int4 && tlutF16) throw new Error("int4 and tlutF16 are exclusive");
  if (int4 && Math.max(...int4.ints.map(Math.abs)) > 5) {
    throw new Error("int4 additive form assumes |level| <= 5");
  }
  const gB = routed ? 6 : 5;             // gamma binding (waveIdx at gB+1)
  const GAMMA_BIND = gamma ? `
@group(0) @binding(${gB}) var<storage, read> gamma: array<f32>;
@group(0) @binding(${gB + 1}) var<storage, read> waveIdx: array<u32>;` : "";
  // per-tile x window, gamma-scaled when the container carries it
  const XG = gamma ? `
    let gv = gamma[te * (mp.ntx + mp.nty) + waveIdx[tile]];
    var xg: array<f32, 16>;
    for (var i = 0u; i < 16u; i = i + 1u) { xg[i] = gv * xhat[colBase + i]; }` : "";
  const X = (idxExpr) => gamma ? `xg[${idxExpr}]` : `xhat[colBase + (${idxExpr})]`;
  const c = codecConsts(cb);
  if (tlutF16 && c.V !== 8) throw new Error("tlutF16 requires V=8");
  if (int4 && c.V !== 8) throw new Error("int4 requires V=8");
  const HALF = c.NSTEP / 2;
  const SEEDW = (HALF * c.STEP) / 16;
  // `dual` needs only a u16-aligned mid-stream seed: the register is a sliding
  // window, so chain 1 can seed at bit (NSTEP/2)*STEP when that lands on a u16
  // boundary. It is independent of how the LUT row is fetched (V=8 f16 pairs
  // or the generic f32 table), so the canon int-lattice spine (V=2, K=4:
  // HALF*STEP = 64*8 = 512 bits = word 32) can use it too — halving a 128-step
  // serial state walk that dominates the spine GEMV.
  if (dual && (HALF * c.STEP) % 16 !== 0) {
    throw new Error(`dual needs a u16-aligned mid-stream seed (HALF*STEP=${HALF * c.STEP})`);
  }
  if (dual) {
    return /* wgsl */ `
struct Meta {
  ntx: u32,
  nty: u32,
  nExperts: u32,
  pad0: u32,
}
@group(0) @binding(0) var<storage, read> trellis: array<u32>;
${tlutF16
    ? "@group(0) @binding(1) var<storage, read> tlut4: array<vec4<u32>>;"
    : "@group(0) @binding(1) var<storage, read> tlut: array<f32>;"}
@group(0) @binding(2) var<storage, read> xhat: array<f32>;    // [nExperts*n]
@group(0) @binding(3) var<storage, read_write> tout: array<f32>; // [nExperts*m]
@group(0) @binding(4) var<uniform> mp: Meta;
${routed ? "@group(0) @binding(5) var<storage, read> routeIdx: array<u32>;" : ""}${GAMMA_BIND}
${COMMON(c)}
var<workgroup> acc: array<f32, ${wg * 16}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let tileRow = wid.x;
  let expert = wid.y;
  ${routed ? "let te = routeIdx[expert];" : "let te = expert;"}
  let ntiles = mp.ntx * mp.nty;
  let n = mp.nty * 16u;
  let xBase = expert * n;
  var yloc: array<f32, 16>;
  for (var t = lid.x; t < mp.nty; t = t + ${wg}u) {
    let tile = tileRow * mp.nty + t;
    let wordBase = (te * ntiles + tile) * ${c.WORDS_PER_TILE}u;
    let colBase = xBase + t * 16u;${XG}
    var s0 = read_u16(wordBase);
    var s1 = read_u16(wordBase + ${SEEDW}u);
    var wi0 = 1u;
    var wi1 = ${SEEDW + 1}u;
    var bb0 = 0u;
    var bb1 = 0u;
    var nb0 = 0u;
    var nb1 = 0u;
    for (var j = 0u; j < ${HALF}u; j = j + 1u) {
      let rn0 = lut_row_neg(s0);
      let rn1 = lut_row_neg(s1);
      var vals0: array<f32, ${c.V}>;
      var vals1: array<f32, ${c.V}>;
${tlutF16 ? `
      let tv0 = tlut4[rn0.x];
      let tv1 = tlut4[rn1.x];
      {
        let u0 = unpack2x16float(tv0.x);
        let u1 = unpack2x16float(tv0.y);
        let u2 = unpack2x16float(tv0.z);
        let u3 = unpack2x16float(tv0.w);
        vals0[0] = u0.x; vals0[1] = u0.y; vals0[2] = u1.x; vals0[3] = u1.y;
        vals0[4] = u2.x; vals0[5] = u2.y; vals0[6] = u3.x; vals0[7] = u3.y;
      }
      {
        let u0 = unpack2x16float(tv1.x);
        let u1 = unpack2x16float(tv1.y);
        let u2 = unpack2x16float(tv1.z);
        let u3 = unpack2x16float(tv1.w);
        vals1[0] = u0.x; vals1[1] = u0.y; vals1[2] = u1.x; vals1[3] = u1.y;
        vals1[4] = u2.x; vals1[5] = u2.y; vals1[6] = u3.x; vals1[7] = u3.y;
      }` : `
      let lb0 = rn0.x * ${c.V}u;
      let lb1 = rn1.x * ${c.V}u;
      for (var v = 0u; v < ${c.V}u; v = v + 1u) {
        vals0[v] = tlut[lb0 + v];
        vals1[v] = tlut[lb1 + v];
      }`}
      vals0[0] = vals0[0] * select(1.0, -1.0, rn0.y == 1u);
      vals1[0] = vals1[0] * select(1.0, -1.0, rn1.y == 1u);
      for (var v = 0u; v < ${c.V}u; v = v + 1u) {
        let idx0 = j * ${c.V}u + v;
        let idx1 = (j + ${HALF}u) * ${c.V}u + v;
        yloc[idx0 >> 4u] = yloc[idx0 >> 4u] + vals0[v] * ${X("idx0 & 15u")};
        yloc[idx1 >> 4u] = yloc[idx1 >> 4u] + vals1[v] * ${X("idx1 & 15u")};
      }
      // unconditional refills (the modulo wrap is the tail-biting behavior)
      if (nb0 < ${c.STEP}u) {
        bb0 = (bb0 << 16u) | read_u16(wordBase + (wi0 % ${c.WORDS_PER_TILE}u));
        wi0 = wi0 + 1u;
        nb0 = nb0 + 16u;
      }
      if (nb1 < ${c.STEP}u) {
        bb1 = (bb1 << 16u) | read_u16(wordBase + (wi1 % ${c.WORDS_PER_TILE}u));
        wi1 = wi1 + 1u;
        nb1 = nb1 + 16u;
      }
      s0 = ((s0 << ${c.STEP}u) & ${c.REG_MASK}u) | ((bb0 >> (nb0 - ${c.STEP}u)) & ${(1 << c.STEP) - 1}u);
      nb0 = nb0 - ${c.STEP}u;
      s1 = ((s1 << ${c.STEP}u) & ${c.REG_MASK}u) | ((bb1 >> (nb1 - ${c.STEP}u)) & ${(1 << c.STEP) - 1}u);
      nb1 = nb1 - ${c.STEP}u;
    }
  }
  for (var r = 0u; r < 16u; r = r + 1u) { acc[lid.x * 16u + r] = yloc[r]; }
  workgroupBarrier();
  if (lid.x < 16u) {
    var total = 0.0;
    for (var t = 0u; t < ${wg}u; t = t + 1u) {
      total = total + acc[t * 16u + lid.x];
    }
    tout[expert * (mp.ntx * 16u) + tileRow * 16u + lid.x] = total;
  }
}`;
  }
  return /* wgsl */ `
struct Meta {
  ntx: u32,
  nty: u32,
  nExperts: u32,
  pad0: u32,
}
@group(0) @binding(0) var<storage, read> trellis: array<u32>;
${int4
    ? "@group(0) @binding(1) var<storage, read> tlutN: array<u32>;"
    : tlutF16
    ? "@group(0) @binding(1) var<storage, read> tlut4: array<vec4<u32>>;"
    : "@group(0) @binding(1) var<storage, read> tlut: array<f32>;"}
@group(0) @binding(2) var<storage, read> xhat: array<f32>;    // [nExperts*n]
@group(0) @binding(3) var<storage, read_write> tout: array<f32>; // [nExperts*m]
@group(0) @binding(4) var<uniform> mp: Meta;
${routed ? "@group(0) @binding(5) var<storage, read> routeIdx: array<u32>;" : ""}${GAMMA_BIND}
${int4 ? `const LV = array<${int4add ? "i32" : "f32"}, 16>(${
  Array.from({ length: 16 }, (_, i) => int4add
    ? (int4.ints[i] ?? 0)
    : ((int4.ints[i] ?? 0) * int4.step).toFixed(9) + "f").join(", ")});` : ""}
${COMMON(c)}
var<workgroup> acc: array<f32, ${wg * 16}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let tileRow = wid.x;
  let expert = wid.y;
  ${routed ? "let te = routeIdx[expert];" : "let te = expert;"}
  let ntiles = mp.ntx * mp.nty;
  let n = mp.nty * 16u;
  let xBase = expert * n;
  var yloc: array<f32, 16>;
  for (var t = lid.x; t < mp.nty; t = t + ${wg}u) {
    let tile = tileRow * mp.nty + t;
    let wordBase = (te * ntiles + tile) * ${c.WORDS_PER_TILE}u;
    let colBase = xBase + t * 16u;${XG}
    var s = read_u16(wordBase);            // state 0 = the L=16 seed bits
    var wordIdx = 1u;                      // rolling refill buffer
    var bitbuf = 0u;
    var nbuf = 0u;
    for (var j = 0u; j < ${c.NSTEP}u; j = j + 1u) {
      let rn = lut_row_neg(s);
      let sgn0 = select(1.0, -1.0, rn.y == 1u);
${int4 ? `
      let nib = tlutN[rn.x];                 // 4 B gather (was 16 B)
      // idx = j*8 + v, so idx>>4 == j>>1 and idx&15 == 8*(j&1)+v: the
      // accumulator row is INVARIANT across the v loop. Accumulate the
      // state's 8 weights in a scalar register and touch yloc ONCE per
      // state instead of 8x — yloc is indexed dynamically, so those
      // read-modify-writes were the compiler's reason to keep it in scratch
      // memory rather than registers.
      let row = j >> 1u;
      let xoff = (j & 1u) * 8u;
      var accv = 0.0;
      for (var v = 0u; v < 8u; v = v + 1u) {
        var a = LV[(nib >> (4u * v)) & 0xFu];
        if (v == 0u && rn.y == 1u) { a = -a; }
        let xv = ${X("xoff + v")};` + (int4add ? `
        // multiply-free: sign-select + doubled-partial adds. |a| <= 5 so
        // a*x = (m>3 ? 4x : m>1 ? 2x : 0) + (m odd ? x : 0), x sign-flipped.
        let s1 = select(xv, -xv, a < 0);
        let mm = u32(abs(a));
        let s2 = s1 + s1;
        let s4 = s2 + s2;
        accv = accv
          + select(select(0.0, s2, mm > 1u), s4, mm > 3u)
          + select(0.0, s1, (mm & 1u) != 0u);` : `
        accv = accv + a * xv;`) + `
      }
      yloc[row] = yloc[row] + accv;` : tlutF16 ? `
      let tv = tlut4[rn.x];
      var vals: array<f32, 8>;
      let u0 = unpack2x16float(tv.x);
      let u1 = unpack2x16float(tv.y);
      let u2 = unpack2x16float(tv.z);
      let u3 = unpack2x16float(tv.w);
      vals[0] = u0.x; vals[1] = u0.y; vals[2] = u1.x; vals[3] = u1.y;
      vals[4] = u2.x; vals[5] = u2.y; vals[6] = u3.x; vals[7] = u3.y;
      vals[0] = vals[0] * sgn0;
      for (var v = 0u; v < 8u; v = v + 1u) {
        let idx = j * 8u + v;
        yloc[idx >> 4u] = yloc[idx >> 4u] + vals[v] * ${X("idx & 15u")};
      }` : `
      let lutBase = rn.x * ${c.V}u;
      for (var v = 0u; v < ${c.V}u; v = v + 1u) {
        var val = tlut[lutBase + v];
        if (v == 0u) { val = val * sgn0; }
        let idx = j * ${c.V}u + v;
        yloc[idx >> 4u] = yloc[idx >> 4u] + val * ${X("idx & 15u")};
      }`}
      if (j + 1u < ${c.NSTEP}u) {          // shift in STEP fresh bits
        if (nbuf < ${c.STEP}u) {
          // tail-biting: the last L-STEP bits of the final window wrap to the
          // stream start (L + (NSTEP-1)*STEP = NBITS + L - STEP > NBITS)
          bitbuf = (bitbuf << 16u) |
            read_u16(wordBase + (wordIdx % ${c.WORDS_PER_TILE}u));
          wordIdx = wordIdx + 1u;
          nbuf = nbuf + 16u;
        }
        let fresh = (bitbuf >> (nbuf - ${c.STEP}u)) & ${(1 << c.STEP) - 1}u;
        nbuf = nbuf - ${c.STEP}u;
        s = ((s << ${c.STEP}u) & ${c.REG_MASK}u) | fresh;
      }
    }
  }
  for (var r = 0u; r < 16u; r = r + 1u) { acc[lid.x * 16u + r] = yloc[r]; }
  workgroupBarrier();
  if (lid.x < 16u) {
    var total = 0.0;
    for (var t = 0u; t < ${wg}u; t = t + 1u) {
      total = total + acc[t * 16u + lid.x];
    }
    // additive form: THE one multiply — the lattice step, once per output
    // element rather than once per weight.
    tout[expert * (mp.ntx * 16u) + tileRow * 16u + lid.x] = total${
      int4add ? ` * ${int4.step.toFixed(9)}f` : ""};
  }
}`;
}

// ------------------------------------------------------------------------
// SUBGROUP FWHT — the orthonormal Walsh-Hadamard transform with each thread
// holding E = dim/wg CONSECUTIVE elements in registers:
//   spans < E                : register-local butterflies (free)
//   spans E .. E*S/2         : subgroupShuffleXor, no barrier, no shared mem
//   spans E*S .. dim/2       : shared-memory exchange (log2(wg/S) rounds,
//                              2 barriers each — vs log2(dim) rounds before)
// The pairwise adds are IDENTICAL in operands and order to fwhtWGSL /
// the split pair (out_i = a + b, out_{i+span} = a - b with a = the lower
// element), so results are BIT-IDENTICAL to the portable kernels.
//
// S (the subgroup size) is baked at codegen. The lane<->invocation mapping
// this layout assumes (lane == lid.x % S) is implementation-defined in
// WGSL, so the engine PROBES it at load (sgProbeWGSL) and only selects
// these kernels when the probe passes — every current Metal/Vulkan/D3D
// backend maps linearly, but the fallback path stays bit-identical anyway.
//
// Modes mirror fwhtWGSL/the splits exactly:
//   mode 1: v = src * signs BEFORE butterflies; store div_sqrtdim(v) * sc(=1)
//   mode 2: store div_sqrtdim(v) * signs * sc
//   routed: grid.x = slot, data slot-major, re = routeIdx[slot] (+pair)
//   count>1: grid.x = tensor index into dataK/signsK (shared srcv)
// ------------------------------------------------------------------------
export function sgProbeWGSL(wg = 256) {
  return /* wgsl */ `
enable subgroups;
@group(0) @binding(0) var<storage, read_write> out: array<u32>;
@compute @workgroup_size(${wg})
fn main(@builtin(local_invocation_id) lid: vec3<u32>,
        @builtin(subgroup_invocation_id) lane: u32,
        @builtin(subgroup_size) ss: u32) {
  out[lid.x] = lane | (ss << 16u);
}`;
}

export function fwhtSgWGSL(dim, S, opts = {}) {
  const mode = opts.mode | 0;
  const count = opts.count || 1;
  const routed = !!opts.routed;
  const pair = opts.pair | 0;
  const bcast = !!opts.bcast;
  const ss = opts.scaleStride || 1;
  const routedScale = mode === 2 && routed;
  if (count > 1 && routed) throw new Error("sg fwht: count>1 is non-routed only");
  const wg = Math.min(256, Math.max(S, dim / 8));
  const E = dim / wg;                       // elements per thread (>= 8 or dim/S)
  if (!Number.isInteger(E) || E < 2) throw new Error(`sg fwht: bad E for dim ${dim}`);
  const nb = [];
  let bindings = "";
  if (count > 1) {
    for (let k = 0; k < count; k++) {
      bindings += `@group(0) @binding(${k}) var<storage, read_write> data${k}: array<f32>;\n`;
    }
    for (let k = 0; k < count; k++) {
      bindings += `@group(0) @binding(${count + k}) var<storage, read> signs${k}: array<f32>;\n`;
    }
    bindings += `@group(0) @binding(${2 * count}) var<storage, read> scales: array<f32>;\n`;
    bindings += `@group(0) @binding(${2 * count + 1}) var<storage, read> srcv: array<f32>;\n`;
  } else {
    bindings += `@group(0) @binding(0) var<storage, read_write> data: array<f32>;
@group(0) @binding(1) var<storage, read> signs: array<f32>;
@group(0) @binding(2) var<storage, read> scales: array<f32>;\n`;
    let b = 3;
    if (routed) { nb.routeIdx = b++; bindings += `@group(0) @binding(${nb.routeIdx}) var<storage, read> routeIdx: array<u32>;\n`; }
    if (bcast) { nb.srcv = b++; bindings += `@group(0) @binding(${nb.srcv}) var<storage, read> srcv: array<f32>;\n`; }
  }
  // ---- round emission (all indices static; r[] is constant-indexed)
  let rounds = "";
  for (let span = 1; span < E; span *= 2) {
    let body = "";
    for (let base = 0; base < E; base += 2 * span) {
      for (let k = 0; k < span; k++) {
        body += `
  { let a = r[${base + k}]; let b = r[${base + k + span}];
    r[${base + k}] = a + b; r[${base + k + span}] = a - b; }`;
      }
    }
    rounds += body;
  }
  for (let L = 1; L < S && E * L < dim; L *= 2) {
    // shuffle round, span = E*L: partner lane = lane ^ L
    rounds += `
  {
    let bit = (lane & ${L}u) != 0u;`;
    for (let e = 0; e < E; e++) {
      rounds += `
    { let th = subgroupShuffleXor(r[${e}], ${L}u);
      r[${e}] = select(r[${e}] + th, th - r[${e}], bit); }`;
    }
    rounds += `
  }`;
  }
  for (let span = E * S; span < dim; span *= 2) {
    const LT = span / E;                    // partner thread xor
    rounds += `
  {
    for (var e = 0u; e < ${E}u; e = e + 1u) { sh[t * ${E}u + e] = rr(e); }
    workgroupBarrier();
    let pb = (t ^ ${LT}u) * ${E}u;
    let bit = (t & ${LT}u) != 0u;`;
    for (let e = 0; e < E; e++) {
      rounds += `
    { let th = sh[pb + ${e}u];
      r[${e}] = select(r[${e}] + th, th - r[${e}], bit); }`;
    }
    rounds += `
    workgroupBarrier();
  }`;
  }
  const loadV = count > 1
    ? Array.from({ length: count }, (_, k) => `${k ? "else " : ""}if (wid.x == ${k}u) {
    for (var e = 0u; e < ${E}u; e = e + 1u) {
      var v = srcv[gb + e];
      ${mode === 1 ? `v = v * signs${k}[gb + e];` : ""}
      wr(e, v);
    }
  }`).join(" ")
    : `for (var e = 0u; e < ${E}u; e = e + 1u) {
    var v = ${bcast ? "srcv[gb + e]" : "data[base + gb + e]"};
    ${mode === 1 ? `v = v * signs[sBase + gb + e];` : ""}
    wr(e, v);
  }`;
  const storeV = count > 1
    ? Array.from({ length: count }, (_, k) => `${k ? "else " : ""}if (wid.x == ${k}u) {
    for (var e = 0u; e < ${E}u; e = e + 1u) {
      data${k}[gb + e] = div_sqrtdim(rr(e)) * sc;
    }
  }`).join(" ")
    : `for (var e = 0u; e < ${E}u; e = e + 1u) {
    var v = div_sqrtdim(rr(e));
    ${mode === 2 ? `v = v * signs[sBase + gb + e];` : ""}
    data[base + gb + e] = v * sc;
  }`;
  // r[] must be constant-indexed to live in registers, but load/store loops
  // want dynamic e — emit tiny accessor switches (compiles to selects).
  const wrCases = Array.from({ length: E }, (_, e) =>
    `    case ${e}u: { r[${e}] = v; }`).join("\n");
  const rrCases = Array.from({ length: E }, (_, e) =>
    `    case ${e}u: { return r[${e}]; }`).join("\n");
  return /* wgsl */ `
enable subgroups;
${bindings}
${divConstWGSL("div_sqrtdim", Math.sqrt(fr(dim)))}
var<private> r: array<f32, ${E}>;
fn wr(e: u32, v: f32) {
  switch e {
${wrCases}
    default: {}
  }
}
fn rr(e: u32) -> f32 {
  switch e {
${rrCases}
    default: { return 0.0; }
  }
}
${E * S < dim ? `var<workgroup> sh: array<f32, ${dim}>;` : ""}
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>,
        @builtin(subgroup_invocation_id) lane: u32) {
  let t = lid.x;
  let gb = t * ${E}u;
${count > 1 ? "" : routed
    ? `  let re = ${pair
      ? `routeIdx[wid.x & 7u] + select(0u, ${pair}u, wid.x >= 8u)`
      : "routeIdx[wid.x]"};
  let base = wid.x * ${dim}u;
  let sBase = re * ${dim}u;`
    : `  let base = 0u;
  let sBase = 0u;`}
  ${loadV}
${rounds}
  let sc = ${count > 1 ? "scales[0]" : routedScale ? `scales[re * ${ss}u]` : "scales[0]"};
  ${storeV}
}`;
}

// ------------------------------------------------------------------------
// MULTI-TENSOR input RHT split: `count` same-dim tensors that share ONE
// source vector (qkv+z read h1; q/k/v read h1) transform in a single
// [dim/C, count] + [C, count] dispatch pair instead of one pair each.
// wid.y picks the tensor; workgroup_id is uniform, so the per-tensor
// branches are uniform control flow and the barriers sit outside them.
// Butterfly order is the standard split order — bit-identical per tensor.
// ------------------------------------------------------------------------
export function fwhtSplitRowMultiWGSL(dim, C, count, wg = 256) {
  const dataB = Array.from({ length: count }, (_, k) =>
    `@group(0) @binding(${k}) var<storage, read_write> data${k}: array<f32>;`).join("\n");
  const signB = Array.from({ length: count }, (_, k) =>
    `@group(0) @binding(${count + k}) var<storage, read> signs${k}: array<f32>;`).join("\n");
  const loadK = Array.from({ length: count }, (_, k) => `${k ? "else " : ""}if (wid.y == ${k}u) {
    for (var i = lid.x; i < ${C}u; i = i + ${wg}u) { sh[i] = srcv[flat + i] * signs${k}[flat + i]; }
  }`).join(" ");
  const storeK = Array.from({ length: count }, (_, k) => `${k ? "else " : ""}if (wid.y == ${k}u) {
    for (var i = lid.x; i < ${C}u; i = i + ${wg}u) { data${k}[flat + i] = sh[i]; }
  }`).join(" ");
  return /* wgsl */ `
${dataB}
${signB}
@group(0) @binding(${2 * count}) var<storage, read> srcv: array<f32>;
var<workgroup> sh: array<f32, ${C}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let flat = wid.x * ${C}u;
  ${loadK}
  workgroupBarrier();
  var span = 1u;
  while (span < ${C}u) {
    for (var pr = lid.x; pr < ${C / 2}u; pr = pr + ${wg}u) {
      let blk = pr / span;
      let k = pr % span;
      let i = blk * 2u * span + k;
      let a = sh[i];
      let b = sh[i + span];
      sh[i] = a + b;
      sh[i + span] = a - b;
    }
    workgroupBarrier();
    span = span << 1u;
  }
  ${storeK}
}`;
}

export function fwhtSplitColMultiWGSL(dim, C, count, wg = 64) {
  const R = dim / C;
  const dataB = Array.from({ length: count }, (_, k) =>
    `@group(0) @binding(${k}) var<storage, read_write> data${k}: array<f32>;`).join("\n");
  const loadK = Array.from({ length: count }, (_, k) => `${k ? "else " : ""}if (wid.y == ${k}u) {
    for (var i = lid.x; i < ${R}u; i = i + ${wg}u) { sh[i] = data${k}[i * ${C}u + col]; }
  }`).join(" ");
  const storeK = Array.from({ length: count }, (_, k) => `${k ? "else " : ""}if (wid.y == ${k}u) {
    for (var i = lid.x; i < ${R}u; i = i + ${wg}u) { data${k}[i * ${C}u + col] = div_sqrtdim(sh[i]) * sc; }
  }`).join(" ");
  return /* wgsl */ `
${dataB}
@group(0) @binding(${count}) var<storage, read> scales: array<f32>;
${divConstWGSL("div_sqrtdim", Math.sqrt(fr(dim)))}
var<workgroup> sh: array<f32, ${R}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let col = wid.x;
  ${loadK}
  workgroupBarrier();
  var span = 1u;
  while (span < ${R}u) {
    for (var pr = lid.x; pr < ${Math.max(1, R / 2)}u; pr = pr + ${wg}u) {
      let blk = pr / span;
      let k = pr % span;
      let i = blk * 2u * span + k;
      let a = sh[i];
      let b = sh[i + span];
      sh[i] = a + b;
      sh[i + span] = a - b;
    }
    workgroupBarrier();
    span = span << 1u;
  }
  let sc = scales[0];
  ${storeK}
}`;
}

// ------------------------------------------------------------------------
// CANON SPINE GEMV — fusedGemvWGSL specialized for the additive release's
// V=2/K=4/L=16 int-lattice spine (CB_NE_CANON), which carries every spine
// and shared-expert linear (~1/3 of the token in the generic kernel).
//
// Same contract, three targeted changes, everything else verbatim:
//  1. The 128-step chain walk is UNROLLED AT CODEGEN TIME. In the generic
//     kernel the accumulator row `idx >> 4` is a runtime value, so yloc[]
//     is dynamically indexed and the compiler keeps it in scratch memory —
//     256 read-modify-writes of thread-private memory per tile. Unrolled,
//     row = j>>3 is a CONSTANT per step: the 16 accumulators become named
//     registers (y0..y15) and scratch traffic disappears. Per-step
//     accumulation ORDER is preserved (two sequential adds, v=0 then v=1),
//     so outputs are bit-identical to the generic kernel at equal wg.
//  2. The codebook row is ONE vec2<f32> load (same bytes, vec2 view)
//     instead of two scalar f32 gathers.
//  3. The refill schedule is static: STEP=8 means one u16 feeds exactly two
//     steps, so even j reads word (1 + j/2) % WORDS_PER_TILE (the % is the
//     tail-biting wrap, resolved at codegen) and odd j takes the low byte.
//     No rolling nbuf/bitbuf bookkeeping at runtime.
// Callers must also cap wg at nty (the tile loop strides `t = lid.x`), same
// rule as the expert kernels: 2048x512 has nty=32, where wg=128 idles 96 of
// 128 threads. Dropping idle threads only removes +0.0 terms from the
// epilogue sum, which cannot change a finite f32 total.
// ------------------------------------------------------------------------
// `dual` (unrolled form): two independent half-tile chains interleaved per
// thread for ILP — chain 0 walks states 0..NSTEP/2-1 (rows 0..7), chain 1
// seeds at the u16-aligned mid-stream window (bit NSTEP/2*STEP) and walks
// the rest (rows 8..15). Rows are disjoint and each row's states stay in
// order, so outputs are bit-identical to the single-chain unrolled kernel.
// The ORIGINAL dual lost 1.5-1.7x at V=2 because yloc lived in scratch and
// two chains doubled that traffic; with register accumulators the tradeoff
// is different — measure, don't assume.
// `fusedRht: n0` — the INPUT RHT runs inside the kernel: binding 2 becomes
// the raw x vector, binding 5 the su signs; every workgroup computes
// H_n(su * x) in shared memory (identical butterfly order to fwhtWGSL, so
// values are bit-identical to the separate dispatch) and the x window reads
// div_sqrtdim(xsh[...]). Worth it ONLY where the workgroup count is small
// (shared-expert tensors: 32-128 wgs) — for the wide spine tensors the
// redundant per-workgroup transform costs more than the dispatch it saves.
// `ranges: [r0, r1, ...]` — SEVERAL same-nty tensors whose trellis buffers
// were CONCATENATED at load run as ONE dispatch of r0+r1+... tile-rows:
// workgroups in [start_k, start_k + r_k) read x from binding x_k and write
// binding y_k (uniform branches on workgroup_id). Metal serializes separate
// dispatches in a pass, so this is how independent same-shape GEMVs
// actually run wide. Per-tensor math identical => bit-identical outputs.
// Bindings: 0 trellis, 1 tlut2, then x0..x{n-1}, then y0..y{n-1}.
export function canonGemvWGSL(cb, wg = 128, opts = {}) {
  const c = codecConsts(cb);
  if (cb.V !== 2) throw new Error("canonGemvWGSL is specialized for V=2");
  if (c.STEP !== 8 || c.L !== 16) {
    throw new Error(`canonGemvWGSL assumes STEP=8/L=16 (got STEP=${c.STEP}, L=${c.L})`);
  }
  const sharedTlut = !!opts.sharedTlut;
  const dual = !!opts.dual;
  const frht = opts.fusedRht | 0;      // n0 when fused, 0 otherwise
  const ranges = opts.ranges || null;
  if (ranges && (frht || dual || opts.tiles2 || opts.tree)) {
    throw new Error("ranges excludes frht/dual/tiles2/tree");
  }
  if (ranges && !opts.nty) throw new Error("ranges requires nty");
  const ROWS = 1 << cb.tlut_bits;
  const lut = sharedTlut ? "shlut" : "tlut2";
  const HALF = c.NSTEP / 2;
  // `tiles2`: each thread walks TWO INDEPENDENT TILES' chains interleaved
  // (wg must equal nty/2 — the engine only selects this when it does).
  // Unlike `dual` (two chains in ONE tile), the tiles accumulate into the
  // SAME 16 row registers, so the register cost is one extra x window while
  // the serial state walk gets a second independent stream to overlap.
  const tiles2 = !!opts.tiles2;
  // one chain step: state j, register suffix q ("" single / "0"/"1" dual /
  // "a"/"b" tiles2 — tiles2 suffixes also pick the x window)
  const stepAt = (j, q, jFirst, jCount) => {
    const r = j >> 3;
    const xva = q === "a" || q === "b" ? `xv${q}` : "xv";
    let s = `
    {
      let rn = lut_row_neg(s${q});
      let t2 = ${lut}[rn.x];
      y${r} = y${r} + select(t2.x, -t2.x, rn.y == 1u) * ${xva}[${(2 * j) & 15}];
      y${r} = y${r} + t2.y * ${xva}[${(2 * j + 1) & 15}];
    }`;
    const wb = q === "a" || q === "b" ? `wordBase${q}` : "wordBase";
    const jl = j - jFirst;                     // chain-local index
    if (jl + 1 < jCount) {
      s += jl % 2 === 0 ? `
    bb${q} = read_u16(${wb} + ${(jFirst / 2 + 1 + (jl >> 1)) % c.WORDS_PER_TILE}u);
    s${q} = ((s${q} << 8u) & 0xFFFFu) | (bb${q} >> 8u);` : `
    s${q} = ((s${q} << 8u) & 0xFFFFu) | (bb${q} & 0xFFu);`;
    }
    return s;
  };
  let body = "";
  if (tiles2) {
    for (let j = 0; j < c.NSTEP; j++) {
      body += stepAt(j, "a", 0, c.NSTEP);
      body += stepAt(j, "b", 0, c.NSTEP);
    }
  } else if (dual) {
    for (let jl = 0; jl < HALF; jl++) {
      body += stepAt(jl, "0", 0, HALF);
      body += stepAt(HALF + jl, "1", HALF, HALF);
    }
  } else {
    for (let j = 0; j < c.NSTEP; j++) body += stepAt(j, "", 0, c.NSTEP);
  }
  const seeds = tiles2 ? `
    var sa = read_u16(wordBasea);
    var sb = read_u16(wordBaseb);
    var bba = 0u;
    var bbb = 0u;` : dual ? `
    var s0 = read_u16(wordBase);
    var s1 = read_u16(wordBase + ${(HALF * c.STEP) / 16}u);
    var bb0 = 0u;
    var bb1 = 0u;` : `
    var s = read_u16(wordBase);
    var bb = 0u;`;
  if (tiles2 && (frht || dual)) throw new Error("tiles2 excludes frht/dual");
  const starts = ranges ? ranges.map((_, k) =>
    ranges.slice(0, k).reduce((a, b) => a + b, 0)) : null;
  const xload = tiles2
    ? Array.from({ length: 16 }, (_, i) =>
      `  xva[${i}] = xhat[colBasea + ${i}u];
  xvb[${i}] = xhat[colBaseb + ${i}u];`).join("\n")
    : ranges
    ? ranges.map((r, k) => `  ${k ? "else " : ""}if (tileRow < ${starts[k] + r}u) {
${Array.from({ length: 16 }, (_, i) => `    xv[${i}] = x${k}[colBase + ${i}u];`).join("\n")}
  }`).join("\n")
    : Array.from({ length: 16 }, (_, i) => frht
      ? `  xv[${i}] = div_sqrtdim(xsh[colBase + ${i}u]);`
      : `  xv[${i}] = xhat[colBase + ${i}u];`).join("\n");
  const ydecl = Array.from({ length: 16 }, (_, i) => `  var y${i} = 0.0;`).join("\n");
  const ystore = Array.from({ length: 16 }, (_, i) =>
    `  acc[lid.x * 16u + ${i}u] = y${i};`).join("\n");
  const NTY = ranges ? `${opts.nty}u` : "mp.nty";
  return /* wgsl */ `${opts.sgAdd ? "\nenable subgroups;" : ""}
${ranges ? `@group(0) @binding(0) var<storage, read> trellis: array<u32>;
@group(0) @binding(1) var<storage, read> tlut2: array<vec2<f32>>;
${ranges.map((_, k) =>
    `@group(0) @binding(${2 + k}) var<storage, read> x${k}: array<f32>;`).join("\n")}
${ranges.map((_, k) =>
    `@group(0) @binding(${2 + ranges.length + k}) var<storage, read_write> y${k}out: array<f32>;`).join("\n")}` : `struct Meta {
  ntx: u32,
  nty: u32,
  nExperts: u32,
  pad0: u32,
}
@group(0) @binding(0) var<storage, read> trellis: array<u32>;
@group(0) @binding(1) var<storage, read> tlut2: array<vec2<f32>>;
@group(0) @binding(2) var<storage, read> xhat: array<f32>;
@group(0) @binding(3) var<storage, read_write> tout: array<f32>;
@group(0) @binding(4) var<uniform> mp: Meta;`}
${frht ? `@group(0) @binding(5) var<storage, read> su: array<f32>;
${divConstWGSL("div_sqrtdim", Math.sqrt(fr(frht)))}` : ""}
${COMMON(c)}
var<workgroup> acc: array<f32, ${(opts.sgAdd ? Math.max(1, Math.ceil(wg / opts.sgAdd)) : wg) * 16}>;
${sharedTlut ? `var<workgroup> shlut: array<vec2<f32>, ${ROWS}>;` : ""}
${frht ? `var<workgroup> xsh: array<f32, ${frht}>;` : ""}
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>${opts.sgAdd ? `,
        @builtin(subgroup_invocation_id) lane: u32` : ""}) {
${sharedTlut ? `  for (var i = lid.x; i < ${ROWS}u; i = i + ${wg}u) { shlut[i] = tlut2[i]; }
  workgroupBarrier();` : ""}
${frht ? `  // in-kernel input RHT: H_n(su * x), same butterfly order as fwhtWGSL
  for (var i = lid.x; i < ${frht}u; i = i + ${wg}u) { xsh[i] = xhat[i] * su[i]; }
  workgroupBarrier();
  var span = 1u;
  while (span < ${frht}u) {
    for (var pr = lid.x; pr < ${frht / 2}u; pr = pr + ${wg}u) {
      let blk = pr / span;
      let k = pr % span;
      let i = blk * 2u * span + k;
      let a = xsh[i];
      let b2 = xsh[i + span];
      xsh[i] = a + b2;
      xsh[i + span] = a - b2;
    }
    workgroupBarrier();
    span = span << 1u;
  }` : ""}
  let tileRow = wid.x;
${ydecl}
${tiles2 ? `  {
    let t = lid.x;
    let tileA = tileRow * mp.nty + t;
    let wordBasea = tileA * ${c.WORDS_PER_TILE}u;
    let wordBaseb = (tileA + ${wg}u) * ${c.WORDS_PER_TILE}u;
    let colBasea = t * 16u;
    let colBaseb = (t + ${wg}u) * 16u;
    var xva: array<f32, 16>;
    var xvb: array<f32, 16>;
${xload}${seeds}
${body}
  }` : `  for (var t = lid.x; t < ${ranges ? NTY : "mp.nty"}; t = t + ${wg}u) {
    let tile = tileRow * ${ranges ? NTY : "mp.nty"} + t;
    let wordBase = tile * ${c.WORDS_PER_TILE}u;
    let colBase = t * 16u;
    var xv: array<f32, 16>;
${xload}${seeds}
${body}
  }`}
${(() => {
  const store = ranges
    ? ranges.map((r, k) => `${k ? "else " : ""}if (tileRow < ${starts[k] + r}u) {
      y${k}out[(tileRow - ${starts[k]}u) * 16u + lid.x] = total;
    }`).join(" ")
    : "tout[tileRow * 16u + lid.x] = total;";
  return opts.sgAdd ? `${Array.from({ length: 16 }, (_, r) => `  let p${r} = subgroupAdd(y${r});`).join("\n")}
  if (lane == 0u) {
${Array.from({ length: 16 }, (_, r) => `    acc[(lid.x / ${opts.sgAdd}u) * 16u + ${r}u] = p${r};`).join("\n")}
  }
  workgroupBarrier();
  if (lid.x < 16u) {
    var total = 0.0;
    for (var g = 0u; g < ${Math.max(1, Math.ceil(wg / opts.sgAdd))}u; g = g + 1u) {
      total = total + acc[g * 16u + lid.x];
    }
    ${store}
  }` : `${ystore}
  workgroupBarrier();
${opts.tree ? `  for (var s = ${wg / 2}u; s >= 1u; s = s >> 1u) {
    if (lid.x < s) {
      for (var r = 0u; r < 16u; r = r + 1u) {
        acc[lid.x * 16u + r] = acc[lid.x * 16u + r] + acc[(lid.x + s) * 16u + r];
      }
    }
    workgroupBarrier();
  }
  if (lid.x < 16u) {
    tout[tileRow * 16u + lid.x] = acc[lid.x];
  }` : `  if (lid.x < 16u) {
    var total = 0.0;
    for (var t = 0u; t < ${wg}u; t = t + 1u) {
      total = total + acc[t * 16u + lid.x];
    }
    ${store}
  }`}`;
})()}
}`;
}

// ------------------------------------------------------------------------
// EXPERT GEMV, UNROLLED — the int4 nibble kernel from fusedGemvWGSL with the
// same codegen treatment as canonGemvWGSL: the 32-step chain walk (V=8,
// STEP=12) is unrolled so the accumulator row j>>1 is a constant and the 16
// row sums live in named registers instead of a dynamically-indexed scratch
// array, and the refill schedule (nbuf cycles 0,4,8,12 across a 4-step
// period) is resolved at codegen into fixed word reads and shifts.
// When the nibble->level map is AFFINE (ints[i] = i + ints[0], true for the
// live 10-level lattice), the per-weight table lookup LV[nib] becomes
// arithmetic: level = i32(nibble) + I0. In the FMA form the lattice step is
// folded into the per-tile x window (xw = step * gv * x) — same values,
// different association, covered by the same tolerance contract as int4
// itself (which is not bitwise vs the f32 path either). In the additive form
// the level stays an INTEGER (sign-select + doubled-partial adds, epilogue
// step multiply) — the multiply-free claim is unchanged.
// Supports exactly the shipping configs: {routed, gamma, int4:{ints, step,
// additive}}. Bindings are IDENTICAL to fusedGemvWGSL's int4 layout.
// ------------------------------------------------------------------------
// `pair: N` (routed only): slots 0..7 address expert routeIdx[slot], slots
// 8..15 address routeIdx[slot-8] + N — the gate and up projections of a
// layer concatenated into ONE set of buffers (trellis/su/sv/gamma), so both
// halves of the MoE MLP run in a single [ntx, 16] dispatch. Per-slot math
// is identical to the unmerged dispatches (the concat preserves per-expert
// layout), so outputs are bit-identical.
export function expertGemvUnrolledWGSL(cb, wg = 128, opts = {}) {
  const routed = !!opts.routed;
  const gamma = !!opts.gamma;
  const pair = opts.pair | 0;
  if (pair && !routed) throw new Error("pair requires routed");
  const int4 = opts.int4;
  if (!int4) throw new Error("expertGemvUnrolledWGSL requires int4");
  const add = !!int4.additive;
  const c = codecConsts(cb);
  if (cb.V !== 8 || c.L !== 16 || c.STEP !== 12) {
    throw new Error(`expertGemvUnrolledWGSL assumes V=8/L=16/STEP=12 (got V=${cb.V}, STEP=${c.STEP})`);
  }
  if (Math.max(...int4.ints.map(Math.abs)) > 5) {
    throw new Error("additive form assumes |level| <= 5");
  }
  const affine = int4.ints.every((v, i) => v === i + int4.ints[0]);
  const I0 = int4.ints[0] ?? 0;
  const gB = routed ? 6 : 5;
  // level expression for nibble slot v of `nib` (i32 for additive, f32 else)
  const lvl = (v) => {
    const nv = v === 0 ? "(nib & 0xFu)" : `((nib >> ${4 * v}u) & 0xFu)`;
    if (affine) return add ? `i32(${nv}) + ${I0}` : `f32(i32(${nv}) + ${I0})`;
    return `LV[${nv}]`;
  };
  const dual = !!opts.dual;
  const HALF = c.NSTEP / 2;
  if (dual && (HALF * c.STEP) % 16 !== 0) {
    throw new Error("dual needs a u16-aligned mid-stream seed");
  }
  // one chain step; q is the register suffix, sim carries {nbuf, W} across
  // the chain's statically-scheduled refills
  // `acc2`: two independent accumulators per state (even/odd v) instead of
  // one — halves the serial FP-add dependency chain in the additive form
  // (whose sign-select expansion is ~4 chained adds per weight). Changes
  // summation order (tolerance contract, like every accumulator layout
  // choice in this file).
  const acc2 = !!opts.acc2;
  // `planes` (additive only): binding 1 holds the buildPlaneTlut mask table
  // instead of nibbles, and each state's 8-weight contribution factors by
  // BIT-PLANE: accv = A0 + 2*A1 + 4*A2, each A_p a sign-selected sum. The
  // doubling happens once per plane per STATE instead of once per WEIGHT
  // (~39 ops/state vs ~85), the three plane chains run independently (ILP),
  // and the kernel stays exactly as multiply-free as before. Summation
  // order changes vs the per-weight form: tolerance contract.
  const planes = !!opts.planes;
  if (planes && !add) throw new Error("planes is an additive-form option");
  const planeStep = (j, q) => {
    const r = j >> 1;
    const xo = (j & 1) * 8;
    let s = `
    {
      let rn = lut_row_neg(s${q});
      let m = tlutN[rn.x];
      let sm = (m & 0xFFu) ^ rn.y;`;
    for (let v = 0; v < 8; v++) {
      s += `
      let sx${v} = select(xw[${xo + v}], -xw[${xo + v}], (sm & ${1 << v}u) != 0u);`;
    }
    for (let p = 0; p < 3; p++) {
      s += `
      var A${p} = select(0.0, sx0, (m & ${(1 << (8 * (p + 1))) >>> 0}u) != 0u);`;
      for (let v = 1; v < 8; v++) {
        s += `
      A${p} = A${p} + select(0.0, sx${v}, (m & ${(1 << (8 * (p + 1) + v)) >>> 0}u) != 0u);`;
      }
    }
    s += `
      let A22 = A2 + A2;
      y${r} = y${r} + (A0 + (A1 + A1) + (A22 + A22));
    }`;
    return s;
  };
  const stepAt = (j, q, jFirst, jCount, sim) => {
    if (planes) {
      let step = planeStep(j, q);
      if (j - jFirst + 1 < jCount) {
        if (sim.nbuf < c.STEP) {
          step += `
    bb${q} = (bb${q} << 16u) | read_u16(wordBase + ${sim.W % c.WORDS_PER_TILE}u);`;
          sim.W += 1;
          sim.nbuf += 16;
        }
        step += `
    s${q} = ((s${q} << 12u) & 0xFFFFu) | ((bb${q} >> ${sim.nbuf - c.STEP}u) & 0xFFFu);`;
        sim.nbuf -= c.STEP;
      }
      return step;
    }
    const r = j >> 1;
    const xo = (j & 1) * 8;
    let step = `
    {
      let rn = lut_row_neg(s${q});
      let nib = tlutN[rn.x];
      var accv = 0.0;${acc2 ? `
      var accw = 0.0;` : ""}`;
    for (let v = 0; v < 8; v++) {
      const A = acc2 && v % 2 === 1 ? "accw" : "accv";
      if (add) {
        step += `
      {
        var a = ${lvl(v)};${v === 0 ? `
        if (rn.y == 1u) { a = -a; }` : ""}
        let s1 = select(xw[${xo + v}], -xw[${xo + v}], a < 0);
        let mm = u32(abs(a));
        let s2 = s1 + s1;
        let s4 = s2 + s2;
        ${A} = ${A}
          + select(select(0.0, s2, mm > 1u), s4, mm > 3u)
          + select(0.0, s1, (mm & 1u) != 0u);
      }`;
      } else {
        step += v === 0 ? `
      var a0 = ${lvl(0)};
      if (rn.y == 1u) { a0 = -a0; }
      accv = accv + a0 * xw[${xo}];` : `
      ${A} = ${A} + ${lvl(v)} * xw[${xo + v}];`;
      }
    }
    step += acc2 ? `
      y${r} = y${r} + (accv + accw);
    }` : `
      y${r} = y${r} + accv;
    }`;
    if (j - jFirst + 1 < jCount) {
      if (sim.nbuf < c.STEP) {
        step += `
    bb${q} = (bb${q} << 16u) | read_u16(wordBase + ${sim.W % c.WORDS_PER_TILE}u);`;
        sim.W += 1;
        sim.nbuf += 16;
      }
      step += `
    s${q} = ((s${q} << 12u) & 0xFFFFu) | ((bb${q} >> ${sim.nbuf - c.STEP}u) & 0xFFFu);`;
      sim.nbuf -= c.STEP;
    }
    return step;
  };
  let body = "";
  if (dual) {
    const sim0 = { nbuf: 0, W: 1 };
    const sim1 = { nbuf: 0, W: (HALF * c.STEP) / 16 + 1 };
    for (let jl = 0; jl < HALF; jl++) {
      body += stepAt(jl, "0", 0, HALF, sim0);
      body += stepAt(HALF + jl, "1", HALF, HALF, sim1);
    }
  } else {
    const sim = { nbuf: 0, W: 1 };
    for (let j = 0; j < c.NSTEP; j++) body += stepAt(j, "", 0, c.NSTEP, sim);
  }
  const seeds = dual ? `
    var s0 = read_u16(wordBase);
    var s1 = read_u16(wordBase + ${(HALF * c.STEP) / 16}u);
    var bb0 = 0u;
    var bb1 = 0u;` : `
    var s = read_u16(wordBase);
    var bb = 0u;`;
  // per-tile x window: gamma and (FMA form only) the lattice step folded in
  const xmul = add
    ? (gamma ? "gv * " : "")
    : (gamma ? `gv * ${f32lit(int4.step)} * ` : `${f32lit(int4.step)} * `);
  const xload = Array.from({ length: 16 }, (_, i) =>
    `    xw[${i}] = ${xmul}xhat[colBase + ${i}u];`).join("\n");
  const ydecl = Array.from({ length: 16 }, (_, i) => `  var y${i} = 0.0;`).join("\n");
  const ystore = Array.from({ length: 16 }, (_, i) =>
    `  acc[lid.x * 16u + ${i}u] = y${i};`).join("\n");
  return /* wgsl */ `${opts.sgAdd ? "\nenable subgroups;" : ""}
struct Meta {
  ntx: u32,
  nty: u32,
  nExperts: u32,
  pad0: u32,
}
@group(0) @binding(0) var<storage, read> trellis: array<u32>;
@group(0) @binding(1) var<storage, read> tlutN: array<u32>;
@group(0) @binding(2) var<storage, read> xhat: array<f32>;
@group(0) @binding(3) var<storage, read_write> tout: array<f32>;
@group(0) @binding(4) var<uniform> mp: Meta;
${routed ? "@group(0) @binding(5) var<storage, read> routeIdx: array<u32>;" : ""}${gamma ? `
@group(0) @binding(${gB}) var<storage, read> gamma: array<f32>;
@group(0) @binding(${gB + 1}) var<storage, read> waveIdx: array<u32>;` : ""}
${affine ? "" : `const LV = array<${add ? "i32" : "f32"}, 16>(${
  Array.from({ length: 16 }, (_, i) => add
    ? (int4.ints[i] ?? 0)
    : ((int4.ints[i] ?? 0) * int4.step).toFixed(9) + "f").join(", ")});`}
${COMMON(c)}
var<workgroup> acc: array<f32, ${(opts.sgAdd ? Math.max(1, Math.ceil(wg / opts.sgAdd)) : wg) * 16}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>${opts.sgAdd ? `,
        @builtin(subgroup_invocation_id) lane: u32` : ""}) {
  let tileRow = wid.x;
  let expert = wid.y;
  ${pair
    ? `let te = routeIdx[expert & 7u] + select(0u, ${pair}u, expert >= 8u);`
    : routed ? "let te = routeIdx[expert];" : "let te = expert;"}
  let ntiles = mp.ntx * mp.nty;
  let n = mp.nty * 16u;
  let xBase = expert * n;
${ydecl}
  for (var t = lid.x; t < mp.nty; t = t + ${wg}u) {
    let tile = tileRow * mp.nty + t;
    let wordBase = (te * ntiles + tile) * ${c.WORDS_PER_TILE}u;
    let colBase = xBase + t * 16u;${gamma ? `
    let gv = gamma[te * (mp.ntx + mp.nty) + waveIdx[tile]];` : ""}
    var xw: array<f32, 16>;
${xload}${seeds}
${body}
  }
${opts.sgAdd ? `${Array.from({ length: 16 }, (_, r) => `  let p${r} = subgroupAdd(y${r});`).join("\n")}
  if (lane == 0u) {
${Array.from({ length: 16 }, (_, r) => `    acc[(lid.x / ${opts.sgAdd}u) * 16u + ${r}u] = p${r};`).join("\n")}
  }
  workgroupBarrier();
  if (lid.x < 16u) {
    var total = 0.0;
    for (var g = 0u; g < ${Math.max(1, Math.ceil(wg / opts.sgAdd))}u; g = g + 1u) {
      total = total + acc[g * 16u + lid.x];
    }
    tout[expert * (mp.ntx * 16u) + tileRow * 16u + lid.x] = total${
      add ? ` * ${f32lit(int4.step)}` : ""};
  }` : `${ystore}
  workgroupBarrier();
${opts.tree ? `  for (var s = ${wg / 2}u; s >= 1u; s = s >> 1u) {
    if (lid.x < s) {
      for (var r = 0u; r < 16u; r = r + 1u) {
        acc[lid.x * 16u + r] = acc[lid.x * 16u + r] + acc[(lid.x + s) * 16u + r];
      }
    }
    workgroupBarrier();
  }
  if (lid.x < 16u) {
    tout[expert * (mp.ntx * 16u) + tileRow * 16u + lid.x] = acc[lid.x]${
      add ? ` * ${f32lit(int4.step)}` : ""};
  }` : `  if (lid.x < 16u) {
    var total = 0.0;
    for (var t = 0u; t < ${wg}u; t = t + 1u) {
      total = total + acc[t * 16u + lid.x];
    }
    tout[expert * (mp.ntx * 16u) + tileRow * 16u + lid.x] = total${
      add ? ` * ${f32lit(int4.step)}` : ""};
  }`}`}
}`;
}

// ------------------------------------------------------------------------
// NE tier kernel 1: DEQUANT. One thread per (row, position). The state is
// the 12 stream bits ending at bit (t+1)*k, zero-padded before bit 0 —
// exactly decode.py's shift register unrolled. Bytes are np.packbits
// (MSB-first within each byte); the buffer is read as u32 words whose
// little-endian byte lanes are the original bytes. BIT-EXACT contract:
// W[r,t] = f32(lut[s]) * f32(gscale[r, t/group]) is one correctly-rounded
// f32 multiply of two f16-exact values.
// ------------------------------------------------------------------------
export function neCommonWGSL(k, L, group) {
  return /* wgsl */ `
fn ne_byte(i: u32) -> u32 {
  return (packed[i >> 2u] >> (8u * (i & 3u))) & 0xFFu;
}
fn ne_state(rowBitBase: u32, t: u32) -> u32 {
  // state t = the ${L} stream bits ending at bit (t+1)*k; the first states
  // have short windows (register seeded with zeros). Assemble from ONE
  // big-endian 4-byte window instead of a ${L}-iteration bit loop: the used
  // bits span offset+width <= 7+${L} = ${7 + L} < 24, so the 4th (possibly
  // out-of-row / out-of-bounds-clamped) byte never reaches them.
  let e = (t + 1u) * ${k}u;
  let width = min(e, ${L}u);
  let p0 = rowBitBase + e - width;
  let b0 = p0 >> 3u;
  let off = p0 & 7u;
  let w = (ne_byte(b0) << 24u) | (ne_byte(b0 + 1u) << 16u) |
          (ne_byte(b0 + 2u) << 8u) | ne_byte(b0 + 3u);
  return (w >> (32u - off - width)) & ((1u << width) - 1u);
}`;
}

export function neDecodeWGSL(k, { L = 12, group = 128, wg = 256 } = {}) {
  return /* wgsl */ `
struct Meta { nrows: u32, tlen: u32, pad0: u32, pad1: u32 }
@group(0) @binding(0) var<storage, read> packed: array<u32>;
@group(0) @binding(1) var<storage, read> lut: array<f32>;
@group(0) @binding(2) var<storage, read> gscale: array<f32>;
@group(0) @binding(3) var<storage, read_write> W: array<f32>;
@group(0) @binding(4) var<uniform> mp: Meta;
${neCommonWGSL(k, L, group)}
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  // 2D dispatch: x spans positions, y spans rows — a 1D grid over
  // rows*positions overflows the 65535 workgroups-per-dimension limit on
  // real tensors (e.g. in_proj_qkv 8192x2048 = 16.7M threads).
  let r = gid.y;
  let t = gid.x;
  if (r >= mp.nrows || t >= mp.tlen) { return; }
  let ng = mp.tlen / ${group}u;
  let s = ne_state(r * mp.tlen * ${k}u, t);
  W[r * mp.tlen + t] = lut[s] * gscale[r * ng + t / ${group}u];
}`;
}

// ------------------------------------------------------------------------
// NE tier kernel 2: FUSED GEMV, y = W x streamed from the packed bits —
// k bits/weight of traffic (plus the 8 KB LUT), W never materialized.
// One workgroup per row; threads process CHUNKS of 8 consecutive positions
// with a ROLLING register — the codec's own recurrence
// s_t = ((s_{t-1} << k) | fresh) & (2^L - 1), seeded either with zeros
// (chunk 0, exactly the spec's zero-padded start) or with the L bits ending
// at t0*k extracted once. The 3 words covering the chunk are loaded once
// and byte-swapped to big-endian bit order, so a refill is one
// shift-and-mask (k=4 never straddles a word: every fresh offset is a
// multiple of 4; k=3 uses a two-word funnel via select — be[] is padded to
// 4 entries because select evaluates both arms). Per-group-128 scale is
// hoisted per chunk. Requires tlen % 8 == 0 and row bit-length % 32 == 0
// (true for every live tensor: tlen 512/2048/4096, k 3/4); trailing window
// words may read past the row's used bytes (bits provably shifted out;
// final-row reads are OOB-clamped). Tolerance contract on the SUM only —
// every decoded state is integer-exact.
// ------------------------------------------------------------------------
export function neFusedGemvWGSL(k, { L = 12, group = 128, wg = 128 } = {}) {
  const P = 8;
  const M = (1 << L) - 1;
  const fresh = k === 4
    ? "let f = (be[q >> 5u] >> (28u - (q & 31u))) & 15u;"
    : /* wgsl */ `let sh = q & 31u;
      let e2 = sh + ${k}u;
      let qw = q >> 5u;
      let f = select((be[qw] >> (32u - e2)) & ${(1 << k) - 1}u,
                     ((be[qw] << (e2 - 32u)) | (be[qw + 1u] >> (64u - e2))) & ${(1 << k) - 1}u,
                     e2 > 32u);`;
  return /* wgsl */ `
struct Meta { nrows: u32, tlen: u32, pad0: u32, pad1: u32 }
@group(0) @binding(0) var<storage, read> packed: array<u32>;
@group(0) @binding(1) var<storage, read> lut: array<f32>;
@group(0) @binding(2) var<storage, read> gscale: array<f32>;
@group(0) @binding(3) var<storage, read> x: array<f32>;
@group(0) @binding(4) var<storage, read_write> y: array<f32>;
@group(0) @binding(5) var<uniform> mp: Meta;
var<workgroup> red: array<f32, ${wg}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let r = wid.x;
  let ng = mp.tlen / ${group}u;
  let rowWordBase = r * (mp.tlen * ${k}u / 32u);
  var acc = 0.0;
  let nch = mp.tlen / ${P}u;
  for (var c = lid.x; c < nch; c = c + ${wg}u) {
    let t0 = c * ${P}u;
    let bit0 = t0 * ${k}u;                   // first fresh bit of the chunk
    let wStart = select((bit0 - ${L}u) >> 5u, 0u, bit0 < ${L}u);
    var be: array<u32, 4>;
    for (var j = 0u; j < 3u; j = j + 1u) {
      let w = packed[rowWordBase + wStart + j];
      be[j] = ((w & 0xFFu) << 24u) | ((w & 0xFF00u) << 8u) |
              ((w >> 8u) & 0xFF00u) | (w >> 24u);
    }
    be[3] = 0u;
    var s = 0u;
    if (bit0 >= ${L}u) {                     // seed: the L bits ending at bit0
      let e0 = ((bit0 - ${L}u) & 31u) + ${L}u;
      s = select((be[0] >> (32u - e0)) & ${M}u,
                 ((be[0] << (e0 - 32u)) | (be[1] >> (64u - e0))) & ${M}u,
                 e0 > 32u);
    }
    var q = bit0 - (wStart << 5u);
    let gs = gscale[r * ng + t0 / ${group}u];
    var csum = 0.0;
    for (var i = 0u; i < ${P}u; i = i + 1u) {
      ${fresh}
      s = ((s << ${k}u) | f) & ${M}u;
      csum = csum + lut[s] * x[t0 + i];
      q = q + ${k}u;
    }
    acc = acc + gs * csum;
  }
  red[lid.x] = acc;
  workgroupBarrier();
  var rw = ${wg / 2}u;
  while (rw > 0u) {
    if (lid.x < rw) { red[lid.x] = red[lid.x] + red[lid.x + rw]; }
    workgroupBarrier();
    rw = rw >> 1u;
  }
  if (lid.x == 0u) { y[r] = red[0]; }
}`;
}

// ------------------------------------------------------------------------
// Demoted-expert shared basis: W += Bc @ A with Bc = B ⊙ c folded on the
// host (numpy's own first step). One thread per output element, r-length
// f32 accumulation. Tolerance contract — numpy's BLAS order differs.
// ------------------------------------------------------------------------
// ------------------------------------------------------------------------
// int5-g64 head GEMV (Mach-1-Ternary-Additive-35B lm_head): symmetric int5
// codes, 8 per 5 little-endian bytes (code i at bits [5i, 5i+5), stored
// q+16), one fp16 scale per 64 reduction-dim weights, RAW domain.
// y[r] = sum_j (q[r,j] * gscale[r, j/64]) * x[j]. One workgroup per row;
// threads stride the 40-bit blocks; each block's partial is scaled by its
// group's scale (8 blocks per group), matching decode.py's W = q*gs up to
// f32 summation order (the GEMV tier carries a tolerance contract; the
// DEQUANT bit-exact contract lives in reference.js decodeInt5g64).
// ------------------------------------------------------------------------
export function int5GemvWGSL({ group = 64, wg = 128 } = {}) {
  return /* wgsl */ `
struct Meta { nrows: u32, tlen: u32, pad0: u32, pad1: u32 }
@group(0) @binding(0) var<storage, read> qp: array<u32>;
@group(0) @binding(1) var<storage, read> gscale: array<f32>;
@group(0) @binding(2) var<storage, read> x: array<f32>;
@group(0) @binding(3) var<storage, read_write> y: array<f32>;
@group(0) @binding(4) var<uniform> mp: Meta;
fn qp_byte(i: u32) -> u32 {
  return (qp[i >> 2u] >> (8u * (i & 3u))) & 0xFFu;
}
var<workgroup> red: array<f32, ${wg}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let r = wid.x;
  let bytesPerRow = (mp.tlen / 8u) * 5u;
  let rowByteBase = r * bytesPerRow;
  let ng = mp.tlen / ${group}u;
  var acc = 0.0;
  let nblk = mp.tlen / 8u;
  for (var b = lid.x; b < nblk; b = b + ${wg}u) {
    let base = rowByteBase + b * 5u;
    // 40-bit little-endian block as lo32 + high byte
    let lo = qp_byte(base) | (qp_byte(base + 1u) << 8u)
           | (qp_byte(base + 2u) << 16u) | (qp_byte(base + 3u) << 24u);
    let hi = qp_byte(base + 4u);
    let col0 = b * 8u;
    var part = 0.0;
    for (var i = 0u; i < 6u; i = i + 1u) {          // codes fully in lo32... i<=5
      let q = f32(((lo >> (5u * i)) & 31u)) - 16.0;
      part = part + q * x[col0 + i];
    }
    {                                               // code 6: bits 30..34
      let q = f32(((lo >> 30u) | (hi << 2u)) & 31u) - 16.0;
      part = part + q * x[col0 + 6u];
    }
    {                                               // code 7: bits 35..39
      let q = f32((hi >> 3u) & 31u) - 16.0;
      part = part + q * x[col0 + 7u];
    }
    acc = acc + part * gscale[r * ng + col0 / ${group}u];
  }
  red[lid.x] = acc;
  workgroupBarrier();
  var rw = ${wg / 2}u;
  while (rw > 0u) {
    if (lid.x < rw) { red[lid.x] = red[lid.x] + red[lid.x + rw]; }
    workgroupBarrier();
    rw = rw >> 1u;
  }
  if (lid.x == 0u) { y[r] = red[0]; }
}`;
}

// ------------------------------------------------------------------------
// int5-g64 head GEMV, FAST PATH. Same contract and bindings as int5GemvWGSL
// but the row is consumed in 4-BLOCK CHUNKS (32 codes = 160 bits = exactly
// five ALIGNED u32 loads; rows are word-aligned since bytesPerRow =
// tlen/8*5 with tlen % 32 == 0) instead of per-block byte gathers — the
// old inner loop issued 20 single-byte buffer reads per 8 weights, this
// one issues 5 word reads per 32. The 32 code extractions are unrolled at
// codegen with static word/offset (a code crosses a word boundary only at
// offsets > 27, resolved statically). A 4-block chunk sits entirely inside
// one 64-weight scale group (64/8 = 8 blocks/group), so gs applies once
// per chunk. Summation ORDER differs from the block-strided kernel — the
// head GEMV carries a tolerance contract vs decode.py, same as before.
// wg=64: tlen=2048 has 64 chunks, so 64 threads take one chunk each;
// wg=128 would idle half the workgroup (the expert-kernel lesson).
// ------------------------------------------------------------------------
// meta.pad0 doubles as an OUTPUT OFFSET (yOff): the engine binds logitsBuf
// directly and each head chunk writes y[yOff + r], removing the 8 per-chunk
// copyBufferToBuffer ops (each of which also broke the compute pass).
// Chunk-local y buffers just pass yOff = 0.
// `sgAdd: S` — the row reduction becomes one subgroupAdd (wg=32 is a single
// subgroup on every probe-passing device we target), killing the 5-round
// shared-memory tree and its barriers. Order changes: tolerance contract.
export function int5GemvFastWGSL({ group = 64, wg = 32, sgAdd = 0 } = {}) {
  if (sgAdd && wg > sgAdd) throw new Error("int5 sgAdd assumes wg <= subgroup size");
  let ext = "";
  for (let i = 0; i < 32; i++) {
    const bit = 5 * i;
    const w = bit >> 5, off = bit & 31;
    const code = off <= 27
      ? `(w${w} >> ${off}u) & 31u`
      : `((w${w} >> ${off}u) | (w${w + 1} << ${32 - off}u)) & 31u`;
    ext += `
    part = part + (f32(${code}) - 16.0) * x[col0 + ${i}u];`;
  }
  return /* wgsl */ `${sgAdd ? "\nenable subgroups;" : ""}
struct Meta { nrows: u32, tlen: u32, yOff: u32, pad1: u32 }
@group(0) @binding(0) var<storage, read> qp: array<u32>;
@group(0) @binding(1) var<storage, read> gscale: array<f32>;
@group(0) @binding(2) var<storage, read> x: array<f32>;
@group(0) @binding(3) var<storage, read_write> y: array<f32>;
@group(0) @binding(4) var<uniform> mp: Meta;
${sgAdd ? "" : `var<workgroup> red: array<f32, ${wg}>;`}
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let r = wid.x;
  let rowWordBase = r * ((mp.tlen / 8u) * 5u / 4u);
  let ng = mp.tlen / ${group}u;
  let nchunk = mp.tlen / 32u;
  var acc = 0.0;
  for (var cc = lid.x; cc < nchunk; cc = cc + ${wg}u) {
    let wb = rowWordBase + cc * 5u;
    let w0 = qp[wb];
    let w1 = qp[wb + 1u];
    let w2 = qp[wb + 2u];
    let w3 = qp[wb + 3u];
    let w4 = qp[wb + 4u];
    let col0 = cc * 32u;
    var part = 0.0;${ext}
    acc = acc + part * gscale[r * ng + col0 / ${group}u];
  }
${sgAdd ? `  let total = subgroupAdd(acc);
  if (lid.x == 0u) { y[mp.yOff + r] = total; }` : `  red[lid.x] = acc;
  workgroupBarrier();
  var rw = ${wg / 2}u;
  while (rw > 0u) {
    if (lid.x < rw) { red[lid.x] = red[lid.x] + red[lid.x + rw]; }
    workgroupBarrier();
    rw = rw >> 1u;
  }
  if (lid.x == 0u) { y[mp.yOff + r] = red[0]; }`}
}`;
}

export function basisUpdateWGSL(wg = 256) {
  return /* wgsl */ `
struct Meta { m: u32, n: u32, r: u32, pad0: u32 }
@group(0) @binding(0) var<storage, read> Abuf: array<f32>;   // [r, n]
@group(0) @binding(1) var<storage, read> Bc: array<f32>;     // [m, r], c folded
@group(0) @binding(2) var<storage, read_write> W: array<f32>;
@group(0) @binding(3) var<uniform> mp: Meta;
@compute @workgroup_size(${wg})
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let g = gid.x;
  if (g >= mp.m * mp.n) { return; }
  let i = g / mp.n;
  let j = g % mp.n;
  var acc = 0.0;
  for (var kk = 0u; kk < mp.r; kk = kk + 1u) {
    acc = acc + Bc[i * mp.r + kk] * Abuf[kk * mp.n + j];
  }
  W[g] = W[g] + acc;
}`;
}

// ------------------------------------------------------------------------
// Baselines: dense GEMV from materialized weights (what a normal engine
// does), one workgroup per (row, expert). f32 = 32 bits/weight of traffic;
// f16 = 16 bits/weight via unpack2x16float (no shader-f16 needed).
// The packed kernel above moves ~1.4 bits/weight for the same math.
// `accumulate` makes y += Wx (the fused demoted-basis path: y += Bc(Ax)).
// `sharedW` reuses ONE weight matrix for every expert/batch index (the GDN
// pipeline batches tokens on the expert axis; default keeps E stacked
// matrices as the expert bench expects).
// ------------------------------------------------------------------------
// `guarded` (engine fast path, demoted-basis GEMVs): wid.y is a SLOT whose
// routed expert is routeIdx[slot]; if dmask[expert]==0 (kept expert) the
// accumulation loop and the output write are skipped — no W traffic, y
// untouched. The skip is a predicate, not an early return, so the reduction
// barriers stay in uniform control flow.
// kind "f32v4": same math as "f32" with the weight row read as vec4<f32>
// (one 16-byte load per 4 weights). Per-thread column partition changes
// (4 consecutive per step instead of 1), so the reduction order differs —
// tolerance contract, same as the f16 kind.
export function denseGemvWGSL(kind, wg = 256, accumulate = false, sharedW = false, guarded = false) {
  const isF16 = kind === "f16";
  const isV4 = kind === "f32v4";
  const wOff = sharedW ? "0u" : "expert * mp.m";
  return /* wgsl */ `
struct Meta { m: u32, n: u32, nExperts: u32, pad0: u32 }
@group(0) @binding(0) var<storage, read> W: array<${isF16 ? "u32" : isV4 ? "vec4<f32>" : "f32"}>;
@group(0) @binding(1) var<storage, read> x: array<f32>;       // [nExperts*n]
@group(0) @binding(2) var<storage, read_write> y: array<f32>; // [nExperts*m]
@group(0) @binding(3) var<uniform> mp: Meta;
${guarded ? `@group(0) @binding(4) var<storage, read> routeIdx: array<u32>;
@group(0) @binding(5) var<storage, read> dmask: array<u32>;` : ""}
var<workgroup> red: array<f32, ${wg}>;
@compute @workgroup_size(${wg})
fn main(@builtin(workgroup_id) wid: vec3<u32>,
        @builtin(local_invocation_id) lid: vec3<u32>) {
  let row = wid.x;
  let expert = wid.y;
  ${guarded ? "let act = dmask[routeIdx[expert]] != 0u;" : "let act = true;"}
  let n = mp.n;
  let xBase = expert * n;
  var acc = 0.0;
  if (act) {
${isF16 ? `
  let rowBase = (${wOff} + row) * (n / 2u);
  for (var cw = lid.x; cw < n / 2u; cw = cw + ${wg}u) {
    let pair = unpack2x16float(W[rowBase + cw]);
    acc = acc + pair.x * x[xBase + cw * 2u] + pair.y * x[xBase + cw * 2u + 1u];
  }` : isV4 ? `
  let rowBase = (${wOff} + row) * (n / 4u);
  for (var cw = lid.x; cw < n / 4u; cw = cw + ${wg}u) {
    let w4 = W[rowBase + cw];
    let xb = xBase + cw * 4u;
    acc = acc + w4.x * x[xb] + w4.y * x[xb + 1u]
              + w4.z * x[xb + 2u] + w4.w * x[xb + 3u];
  }` : `
  let rowBase = (${wOff} + row) * n;
  for (var cc = lid.x; cc < n; cc = cc + ${wg}u) {
    acc = acc + W[rowBase + cc] * x[xBase + cc];
  }`}
  }
  red[lid.x] = acc;
  workgroupBarrier();
  var rw = ${wg / 2}u;
  while (rw > 0u) {
    if (lid.x < rw) { red[lid.x] = red[lid.x] + red[lid.x + rw]; }
    workgroupBarrier();
    rw = rw >> 1u;
  }
  if (lid.x == 0u && act) {
    ${accumulate
    ? "y[expert * mp.m + row] = y[expert * mp.m + row] + red[0];"
    : "y[expert * mp.m + row] = red[0];"}
  }
}`;
}
