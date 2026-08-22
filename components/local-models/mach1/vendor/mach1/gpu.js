// WebGPU host-side runners for the Mach-1 packed-codec kernels.
import {
  decodeUnitWGSL, fwhtWGSL, fusedGemvWGSL, denseGemvWGSL,
  neDecodeWGSL, neFusedGemvWGSL, basisUpdateWGSL, int5GemvWGSL,
} from "./shaders.js";
import { f16Round, buildInt4Tlut } from "./reference.js";

export async function initGPU() {
  if (!navigator.gpu) throw new Error("WebGPU is not available in this browser");
  const adapter = await navigator.gpu.requestAdapter();
  if (!adapter) throw new Error("no WebGPU adapter (try enabling hardware acceleration)");
  // Default limits are 256 MiB buffers / 128 MiB storage bindings — a
  // 64-expert dense-f32 baseline (268 MB) silently exceeds them and every
  // dispatch no-ops, producing impossible bench numbers. Ask for what the
  // adapter actually has.
  // Same story for workgroup storage: the single-pass FWHT holds the whole
  // vector in shared memory (dim * 4 bytes), and the additive spine needs
  // dim = 8192 (in_proj_qkv / q_proj) = 32 KB against a 16 KB default. The
  // pipeline then fails to CREATE and every dispatch using it silently
  // no-ops — the model still "runs", on zeros. Ask for the adapter's real
  // limit; fwhtWGSL falls back to a two-pass split when it still doesn't fit.
  const device = await adapter.requestDevice({
    // `subgroups` (when the adapter has it) unlocks the shuffle-based FWHT
    // and subgroupAdd reductions; the engine PROBES the actual lane mapping
    // at load and silently falls back to the portable kernels otherwise.
    requiredFeatures: adapter.features.has("subgroups") ? ["subgroups"] : [],
    requiredLimits: {
      maxBufferSize: adapter.limits.maxBufferSize,
      maxStorageBufferBindingSize: adapter.limits.maxStorageBufferBindingSize,
      maxComputeWorkgroupStorageSize: adapter.limits.maxComputeWorkgroupStorageSize,
    },
  });
  let info = {};
  try {
    const ai = adapter.info || (adapter.requestAdapterInfo && await adapter.requestAdapterInfo());
    if (ai) info = { vendor: ai.vendor, architecture: ai.architecture, device: ai.device, description: ai.description };
  } catch { /* adapter info is optional */ }
  return { device, info };
}

function buf(device, data, usage) {
  let src = data;
  if (data.byteLength % 4 !== 0) {
    const padded = new Uint8Array(Math.ceil(data.byteLength / 4) * 4);
    padded.set(new Uint8Array(data.buffer, data.byteOffset, data.byteLength));
    src = padded;
  }
  const b = device.createBuffer({ size: Math.max(16, src.byteLength), usage });
  device.queue.writeBuffer(b, 0, src);
  return b;
}
// Lazy: GPUBufferUsage does not exist in Node, and verify.js's pure helpers
// (imported by test/test_guard.mjs) must load without a WebGPU global.
const STORAGE = () => GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST;
const STORAGE_SRC = () => GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST | GPUBufferUsage.COPY_SRC;

export async function readback(device, gpuBuf, byteLength) {
  const staging = device.createBuffer({ size: byteLength, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
  const enc = device.createCommandEncoder();
  enc.copyBufferToBuffer(gpuBuf, 0, staging, 0, byteLength);
  device.queue.submit([enc.finish()]);
  await staging.mapAsync(GPUMapMode.READ);
  const out = new Float32Array(staging.getMappedRange().slice(0));
  staging.unmap();
  staging.destroy();
  return out;
}

// Pipeline cache keyed by (device, generated WGSL) — a pipeline is bound to
// the device that created it; reusing across devices fails bind-group
// validation (multiple initGPU() calls on one page create fresh devices).
const _pipelines = new WeakMap();
function pipeline(device, code) {
  let perDev = _pipelines.get(device);
  if (!perDev) { perDev = new Map(); _pipelines.set(device, perDev); }
  let p = perDev.get(code);
  if (!p) {
    const module = device.createShaderModule({ code });
    p = device.createComputePipeline({ layout: "auto", compute: { module, entryPoint: "main" } });
    perDev.set(code, p);
  }
  return p;
}

function uniform(device, values) {
  // all uniform fields in these kernels are u32
  const u = new Uint32Array(Math.max(8, values.length));
  values.forEach((v, i) => { u[i] = v >>> 0; });
  return buf(device, u, GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST);
}

// Split n workgroups over a 2D grid within the 65535-per-dimension limit.
function grid2d(n) {
  const y = Math.ceil(n / 65535);
  const x = Math.ceil(n / y);
  return { x, y };
}

function bind(device, pipe, buffers) {
  return device.createBindGroup({
    layout: pipe.getBindGroupLayout(0),
    // each entry is a GPUBuffer or a {buffer, offset, size} descriptor
    entries: buffers.map((b, i) => ({
      binding: i, resource: b.buffer ? b : { buffer: b },
    })),
  });
}

// A prepared problem: all GPU buffers for E experts of one (m0, n0, codec).
// su/sv are Float32Array [E*n0]/[E*m0]; trellis Uint16Array [E*ntiles*wpt].
// The tlut is pre-rounded to f16 values on the host: decode.py's spec rounds
// every GATHERED value to fp16, and rounding the table entries once is
// bit-equivalent (rounding is elementwise; the component-0 negation commutes
// with RNE, which is sign-symmetric). decodeUnit's in-kernel f16_round is
// idempotent on the pre-rounded values, and the fused GEMV — which has no
// in-kernel round — streams exactly the f16 weights this way.
// `basis` (optional, nExperts must be 1): {A, B, c, r} Float32Arrays of the
// demoted-expert shared low-rank residual; c is folded into B host-side
// (numpy's own first step: (B * c) @ A).
// `gemvOnly` skips the m0*n0 dequant target buffer (the fused-GEMV consumer
// never materializes W — a routed-MoE engine prepares hundreds of these).
// `sharedTlut` reuses an existing GPU codebook buffer instead of uploading.
export function prepare(device, cb, { trellis, tlut, su, sv, wscales, x, m0, n0, nExperts, basis, gemvOnly, sharedTlut, gamma, waveIdx, int4, int4add }) {
  const ntx = m0 / cb.td_x, nty = n0 / cb.td_y;
  const ntiles = ntx * nty;
  const p = {
    cb, m0, n0, nExperts, ntiles,
    // additive v3t container: per-(expert, wavefront) gamma + tile->wave map
    gamma: gamma ? buf(device, gamma, STORAGE()) : null,
    waveIdx: waveIdx ? buf(device, waveIdx, STORAGE()) : null,
    trellis: buf(device, trellis, STORAGE()),
    tlut: sharedTlut || buf(device, Float32Array.from(tlut, f16Round), STORAGE()),
    sharedTlut: !!sharedTlut,
    // int4 (additive release): nibble-packed codebook, 4 B/row instead of
    // 16 B. Built from the RAW tlut so the integer lattice is exact; null
    // (and the f16 path is used unchanged) on any non-lattice alphabet.
    int4: int4 ? buildInt4Tlut(tlut, cb.V) : null,
    int4add: !!int4add,
    su: buf(device, su, STORAGE()),
    sv: buf(device, sv, STORAGE()),
    wscales: buf(device, wscales, STORAGE()),
    ones: buf(device, new Float32Array(nExperts).fill(1), STORAGE()),
    W: gemvOnly ? null
      : device.createBuffer({ size: nExperts * m0 * n0 * 4, usage: STORAGE_SRC() }),
    x: x ? buf(device, x, STORAGE_SRC()) : null,
    // sized from geometry, not from x — the engine prepares with x: null and
    // streams inputs in via encodeFusedGemv's xBuf override
    xhat: device.createBuffer({ size: nExperts * n0 * 4, usage: STORAGE_SRC() }),
    y: device.createBuffer({ size: nExperts * m0 * 4, usage: STORAGE_SRC() }),
    metaDecode: uniform(device, [ntx, nty, nExperts, 0]),
    metaGemv: uniform(device, [ntx, nty, nExperts, 0]),
  };
  // FWHT uniforms: [nvec, vecsPerExpert, expertStride, vecStride, elemStride,
  // signMode, gridX, 0]. One workgroup per vector on a 2D grid — nvec can
  // exceed the 65535 workgroups-per-dimension limit (e.g. 64 experts x 2048
  // rows), so each uniform carries its dispatch's x-extent.
  p.fwhtRowsD = grid2d(nExperts * m0);
  p.fwhtColsD = grid2d(nExperts * n0);
  p.fwhtBatchD = grid2d(nExperts);
  p.fwhtRowsU = uniform(device, [nExperts * m0, m0, m0 * n0, n0, 1, 2, p.fwhtRowsD.x, 0]);
  p.fwhtColsU = uniform(device, [nExperts * n0, n0, m0 * n0, 1, n0, 2, p.fwhtColsD.x, 0]);
  p.fwhtXU = uniform(device, [nExperts, 1, n0, 0, 1, 1, p.fwhtBatchD.x, 0]);
  p.fwhtYU = uniform(device, [nExperts, 1, m0, 0, 1, 2, p.fwhtBatchD.x, 0]);
  if (basis) {
    if (nExperts !== 1) throw new Error("basis path supports nExperts=1");
    const { A, B, c, r } = basis;
    const Bc = new Float32Array(B.length);
    for (let i = 0; i < m0; i++) {
      for (let k = 0; k < r; k++) Bc[i * r + k] = Math.fround(B[i * r + k] * c[k]);
    }
    p.basisR = r;
    p.basisA = buf(device, A, STORAGE());
    p.basisBc = buf(device, Bc, STORAGE());
    p.basisMeta = uniform(device, [m0, n0, r, 0]);
    p.t1 = device.createBuffer({ size: Math.max(16, r * 4), usage: STORAGE_SRC() });
    p.gemvAU = uniform(device, [r, n0, 1, 0]);      // t1 = A @ x
    p.gemvBU = uniform(device, [m0, r, 1, 0]);      // y += Bc @ t1
  }
  // packed nibble codebook (built in the literal above); null keeps the f16/f32 path
  p.tlutN = p.int4 ? buf(device, p.int4.packed, STORAGE()) : null;
  return p;
}

export function destroyPrepared(p) {
  if (p.sharedTlut) p.tlut = null;        // borrowed — owner destroys it
  for (const k of ["trellis", "tlut", "tlutN", "su", "sv", "wscales", "ones", "W", "x", "xhat", "y",
    "metaDecode", "metaGemv", "fwhtRowsU", "fwhtColsU", "fwhtXU", "fwhtYU",
    "basisA", "basisBc", "basisMeta", "t1", "gemvAU", "gemvBU", "gamma", "waveIdx"]) {
    if (p[k]) p[k].destroy();
  }
}

// Encode a full dequant: trellis bits -> W [E, m0, n0] (final, RHT applied).
// withBasis (default true when prepared with one): add the demoted-expert
// low-rank residual W += Bc @ A after the rotation — decode.py's op order.
export function encodeDecode(device, p, enc, { withBasis = true } = {}) {
  const { cb, m0, n0, nExperts, ntiles } = p;
  const nstep = (cb.td_x * cb.td_y) / cb.V;
  const decode = pipeline(device, decodeUnitWGSL(cb, { gamma: !!p.gamma }));
  const fwhtN = pipeline(device, fwhtWGSL(n0));
  const fwhtM = pipeline(device, fwhtWGSL(m0));
  {
    const pass = enc.beginComputePass();
    pass.setPipeline(decode);
    pass.setBindGroup(0, bind(device, decode, p.gamma
      ? [p.trellis, p.tlut, p.W, p.metaDecode, p.gamma, p.waveIdx]
      : [p.trellis, p.tlut, p.W, p.metaDecode, p.wscales]));
    pass.dispatchWorkgroups(Math.ceil((nExperts * ntiles * nstep) / 256));
    pass.end();
  }
  {
    const pass = enc.beginComputePass();
    pass.setPipeline(fwhtN);
    pass.setBindGroup(0, bind(device, fwhtN, [p.W, p.su, p.fwhtRowsU, p.ones]));
    pass.dispatchWorkgroups(p.fwhtRowsD.x, p.fwhtRowsD.y);
    pass.end();
  }
  {
    const pass = enc.beginComputePass();
    pass.setPipeline(fwhtM);
    pass.setBindGroup(0, bind(device, fwhtM, [p.W, p.sv, p.fwhtColsU, p.ones]));
    pass.dispatchWorkgroups(p.fwhtColsD.x, p.fwhtColsD.y);
    pass.end();
  }
  if (p.basisA && withBasis) {
    const upd = pipeline(device, basisUpdateWGSL());
    const pass = enc.beginComputePass();
    pass.setPipeline(upd);
    pass.setBindGroup(0, bind(device, upd, [p.basisA, p.basisBc, p.W, p.basisMeta]));
    pass.dispatchWorkgroups(Math.ceil((m0 * n0) / 256));
    pass.end();
  }
}

// Encode the fused GEMV: y = sv * H_m( U . H_n(su * x) ) * wscale,
// weights streamed from the packed bits (W never materialized).
// `xBuf`/`xOff` override the input source (a mid-pipeline GPU buffer slice;
// xOff must be 256-byte aligned for the basis bind path) — result lands in
// p.y as always.
export function encodeFusedGemv(device, p, enc, { xBuf = p.x, xOff = 0 } = {}) {
  const { cb, m0, n0, nExperts } = p;
  const fwhtN = pipeline(device, fwhtWGSL(n0));
  const fwhtM = pipeline(device, fwhtWGSL(m0));
  const useInt4 = !!p.int4;
  const fused = pipeline(device, fusedGemvWGSL(cb, 128, useInt4
    ? { gamma: !!p.gamma,
        int4: { ints: p.int4.ints, step: p.int4.step, additive: p.int4add } }
    : { gamma: !!p.gamma }));
  enc.copyBufferToBuffer(xBuf, xOff, p.xhat, 0, nExperts * n0 * 4);
  {
    const pass = enc.beginComputePass();
    pass.setPipeline(fwhtN);
    pass.setBindGroup(0, bind(device, fwhtN, [p.xhat, p.su, p.fwhtXU, p.ones]));
    pass.dispatchWorkgroups(p.fwhtBatchD.x, p.fwhtBatchD.y);
    pass.end();
  }
  {
    const pass = enc.beginComputePass();
    pass.setPipeline(fused);
    const tl = useInt4 ? p.tlutN : p.tlut;
    pass.setBindGroup(0, bind(device, fused, p.gamma
      ? [p.trellis, tl, p.xhat, p.y, p.metaGemv, p.gamma, p.waveIdx]
      : [p.trellis, tl, p.xhat, p.y, p.metaGemv]));
    pass.dispatchWorkgroups(m0 / cb.td_x, nExperts);
    pass.end();
  }
  {
    const pass = enc.beginComputePass();
    pass.setPipeline(fwhtM);
    pass.setBindGroup(0, bind(device, fwhtM, [p.y, p.sv, p.fwhtYU, p.wscales]));
    pass.dispatchWorkgroups(p.fwhtBatchD.x, p.fwhtBatchD.y);
    pass.end();
  }
  if (p.basisA) {
    // y += Bc (A x): the residual acts on the RAW x (p.x), not the FWHT'd
    // xhat — two small dense GEMVs, W still never materialized.
    const gA = pipeline(device, denseGemvWGSL("f32"));
    const gB = pipeline(device, denseGemvWGSL("f32", 256, true));
    {
      const pass = enc.beginComputePass();
      pass.setPipeline(gA);
      pass.setBindGroup(0, bind(device, gA,
        [p.basisA, { buffer: xBuf, offset: xOff, size: n0 * 4 }, p.t1, p.gemvAU]));
      pass.dispatchWorkgroups(p.basisR, 1);
      pass.end();
    }
    {
      const pass = enc.beginComputePass();
      pass.setPipeline(gB);
      pass.setBindGroup(0, bind(device, gB, [p.basisBc, p.t1, p.y, p.gemvBU]));
      pass.dispatchWorkgroups(m0, 1);
      pass.end();
    }
  }
}

export async function runDecode(device, p, opts = {}) {
  const enc = device.createCommandEncoder();
  encodeDecode(device, p, enc, opts);
  device.queue.submit([enc.finish()]);
  return readback(device, p.W, p.nExperts * p.m0 * p.n0 * 4);
}

export async function runFusedGemv(device, p) {
  const enc = device.createCommandEncoder();
  encodeFusedGemv(device, p, enc);
  device.queue.submit([enc.finish()]);
  return readback(device, p.y, p.nExperts * p.m0 * 4);
}

// ---------------------------------------------------------------- NE tier
// packed: Uint8Array [nrows * tlen*k/8]; lut/gscale: Float32Array (f16-exact
// values). x: Float32Array, OR an existing GPUBuffer to borrow (the engine
// chains NE GEMVs off mid-pipeline activations), or null. `gemvOnly` skips
// the nrows*tlen dequant target (engine GEMV path never materializes W).
// Non-transposed orientation only (every live NE shard is transposed:false;
// the JS reference covers the transposed read).
export function prepareNe(device, { packed, lut, gscale, x, nrows, tlen, k, group = 128, gemvOnly }) {
  const borrowedX = x && x.size !== undefined;   // GPUBuffer duck-type
  return {
    nrows, tlen, k, group, borrowedX,
    packed: buf(device, packed, STORAGE()),
    lut: buf(device, lut, STORAGE()),
    gscale: buf(device, gscale, STORAGE()),
    x: borrowedX ? x : (x ? buf(device, x, STORAGE()) : null),
    W: gemvOnly ? null : device.createBuffer({ size: nrows * tlen * 4, usage: STORAGE_SRC() }),
    y: device.createBuffer({ size: Math.max(16, nrows * 4), usage: STORAGE_SRC() }),
    meta: uniform(device, [nrows, tlen, 0, 0]),
  };
}

export function destroyNe(p) {
  if (p.borrowedX) p.x = null;
  for (const k of ["packed", "lut", "gscale", "x", "W", "y", "meta"]) {
    if (p[k]) p[k].destroy();
  }
}

export async function runNeDecode(device, p) {
  const pipe = pipeline(device, neDecodeWGSL(p.k, { group: p.group }));
  const enc = device.createCommandEncoder();
  const pass = enc.beginComputePass();
  pass.setPipeline(pipe);
  pass.setBindGroup(0, bind(device, pipe, [p.packed, p.lut, p.gscale, p.W, p.meta]));
  pass.dispatchWorkgroups(Math.ceil(p.tlen / 256), p.nrows);
  pass.end();
  device.queue.submit([enc.finish()]);
  return readback(device, p.W, p.nrows * p.tlen * 4);
}

export function encodeNeFusedGemv(device, p, enc) {
  const pipe = pipeline(device, neFusedGemvWGSL(p.k, { group: p.group }));
  const pass = enc.beginComputePass();
  pass.setPipeline(pipe);
  pass.setBindGroup(0, bind(device, pipe, [p.packed, p.lut, p.gscale, p.x, p.y, p.meta]));
  pass.dispatchWorkgroups(p.nrows);
  pass.end();
}

export async function runNeFusedGemv(device, p) {
  const enc = device.createCommandEncoder();
  encodeNeFusedGemv(device, p, enc);
  device.queue.submit([enc.finish()]);
  return readback(device, p.y, p.nrows * 4);
}

// ------------------------------------------- int5-g64 head tier (additive)
// qp: Uint8Array [nrows * tlen/8*5]; gscale: Float32Array (f16-exact values,
// one per 64 reduction weights). Fused GEMV only — the bit-exact dequant
// contract for this tier lives in reference.js decodeInt5g64 (pure CPU).
export function prepareInt5(device, { qp, gscale, x, nrows, tlen, group = 64 }) {
  const borrowedX = x && x.size !== undefined;
  return {
    nrows, tlen, group, borrowedX,
    qp: buf(device, qp, STORAGE()),
    gscale: buf(device, gscale, STORAGE()),
    x: borrowedX ? x : (x ? buf(device, x, STORAGE()) : null),
    y: device.createBuffer({ size: Math.max(16, nrows * 4), usage: STORAGE_SRC() }),
    meta: uniform(device, [nrows, tlen, 0, 0]),
  };
}

export function destroyInt5(p) {
  if (p.borrowedX) p.x = null;
  for (const k of ["qp", "gscale", "x", "y", "meta"]) {
    if (p[k]) p[k].destroy();
  }
}

export function encodeInt5Gemv(device, p, enc) {
  const pipe = pipeline(device, int5GemvWGSL({ group: p.group }));
  const pass = enc.beginComputePass();
  pass.setPipeline(pipe);
  pass.setBindGroup(0, bind(device, pipe, [p.qp, p.gscale, p.x, p.y, p.meta]));
  pass.dispatchWorkgroups(p.nrows);
  pass.end();
}

export async function runInt5Gemv(device, p) {
  const enc = device.createCommandEncoder();
  encodeInt5Gemv(device, p, enc);
  device.queue.submit([enc.finish()]);
  return readback(device, p.y, p.nrows * 4);
}

// Dense baseline: y = W x from a materialized weight buffer.
export function prepareDense(device, kind, W32, x, m0, n0, nExperts) {
  let wdata;
  if (kind === "f16") {
    const half = new Uint16Array(W32.length);
    const f32 = new Float32Array(1);
    const u32 = new Uint32Array(f32.buffer);
    for (let i = 0; i < W32.length; i++) {
      // quick f32->f16 (RNE) for baseline storage
      f32[0] = W32[i];
      const u = u32[0], sign = (u >>> 16) & 0x8000, a = u & 0x7fffffff;
      let h;
      if (a >= 0x47800000) h = sign | 0x7c00;
      else if (a < 0x38800000) {
        const shift = 126 - (a >>> 23);
        if (shift > 24) h = sign;
        else {
          const mant = (a & 0x7fffff) | 0x800000;
          const q = mant >>> shift, rem = mant & ((1 << shift) - 1), hf = 1 << (shift - 1);
          h = sign | (q + ((rem > hf || (rem === hf && (q & 1))) ? 1 : 0));
        }
      } else {
        h = sign | ((((a >>> 23) - 112) << 10) & 0x7c00) | ((a >>> 13) & 0x3ff);
        const rem = a & 0x1fff;
        if (rem > 0x1000 || (rem === 0x1000 && (h & 1))) h += 1;
      }
      half[i] = h;
    }
    wdata = half;
  } else {
    wdata = W32;
  }
  return {
    kind, m0, n0, nExperts,
    W: buf(device, wdata, STORAGE()),
    x: buf(device, x, STORAGE()),
    y: device.createBuffer({ size: nExperts * m0 * 4, usage: STORAGE_SRC() }),
    meta: uniform(device, [m0, n0, nExperts, 0]),
  };
}

export function encodeDense(device, d, enc) {
  const pipe = pipeline(device, denseGemvWGSL(d.kind));
  const pass = enc.beginComputePass();
  pass.setPipeline(pipe);
  pass.setBindGroup(0, bind(device, pipe, [d.W, d.x, d.y, d.meta]));
  pass.dispatchWorkgroups(d.m0, d.nExperts);
  pass.end();
}

export async function runDense(device, d) {
  const enc = device.createCommandEncoder();
  encodeDense(device, d, enc);
  device.queue.submit([enc.finish()]);
  return readback(device, d.y, d.nExperts * d.m0 * 4);
}

// Wall-clock benchmark: encode `encodeFn(enc)` REPS times per submit, time
// submit->onSubmittedWorkDone. Returns ms per single encoded iteration.
export async function bench(device, encodeFn, { reps = 20, warmup = 2 } = {}) {
  for (let w = 0; w < warmup; w++) {
    const enc = device.createCommandEncoder();
    encodeFn(enc);
    device.queue.submit([enc.finish()]);
    await device.queue.onSubmittedWorkDone();
  }
  const enc = device.createCommandEncoder();
  for (let i = 0; i < reps; i++) encodeFn(enc);
  const cmd = enc.finish();
  const t0 = performance.now();
  device.queue.submit([cmd]);
  await device.queue.onSubmittedWorkDone();
  const t1 = performance.now();
  return (t1 - t0) / reps;
}
