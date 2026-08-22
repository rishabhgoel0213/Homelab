// In-browser inference engine for Mach-1-Ternary-35B: full 40-layer decode
// from PACKED bytes. Routed experts stream through the fused trellis GEMV
// (~1.375 bits/weight), NE linears + lm_head through the fused L=12 GEMV,
// the embedding is a CPU int3 gather, GDN layers keep resident recurrent
// state, attention layers keep an f32 KV cache.
//
// The token pipeline is fully GPU-resident: routing runs on the GPU (router
// GEMV + top-8 softmax kernel) and the routed expert kernels read the route
// buffer directly, batched over the 8 slots per dispatch — so one token is
// ONE recorded command submit plus ONE logits readback, with no per-layer
// CPU round-trips and no per-token bind-group creation.
//
// Every component here is individually validated against decode.py /
// transformers on real weights (see HANDOFF.md §6); the block assembly is
// validated by test/test_blocks_gpu.mjs; the GPU router is cross-checked
// against the CPU reference via debugRoutes/checkRoutes().
import { openSafetensors, openSafetensorsBuffer } from "./safetensors.js";
import {
  CB_EXPERT, CB_EXPERT_V3T, CB_NE_CANON, f16Round, decodeEmbed, waveIndexMap,
  bf16ToF32,
  buildInt4Tlut, buildPlaneTlut,
} from "./reference.js";
import {
  fwhtWGSL, fwhtSplitRowWGSL, fwhtSplitColWGSL, fwhtSplitRowMultiWGSL,
  fwhtSplitColMultiWGSL, fwhtSgWGSL, sgProbeWGSL, fusedGemvWGSL, denseGemvWGSL,
  neFusedGemvWGSL, codecConsts, int5GemvWGSL, int5GemvFastWGSL, canonGemvWGSL,
  expertGemvUnrolledWGSL,
} from "./shaders.js";
import { prepareNe, prepareInt5 } from "./gpu.js";
import { gdnRecurrenceWGSL, gatedNormWGSL } from "./gdn_shaders.js";
import {
  rmsnormWGSL, addWGSL, addRmsWGSL, addRmsMoeWGSL, siluMulWGSL, siluMulPairWGSL,
  sigmoidScaleAddWGSL,
  qkNormRopeWGSL, attnGateMulWGSL, convStepWGSL, attnDecodeWGSL, appendKVWGSL,
  routerTopKWGSL, routedCMulWGSL, moeReduceWGSL,
  maxReduceWGSL, maxFinalWGSL, logitCompactWGSL,
} from "./blocks_shaders.js";
import { Tokenizer } from "./bpe.js";

const ST = () => GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST;
const STS = () => GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST | GPUBufferUsage.COPY_SRC;

// ---------------------------------------------------------------- models
// Two shipped releases share this engine: the architecture, NE tier, router,
// GDN/attention and UI are identical — only the EXPERT container, lm_head
// codec and embedding tier differ. `bytes`/`shards` are the exact fetch
// totals of the loader's plan (used by the pages' progress HUD).
export const MODELS = {
  ternary: {
    repo: "SyzygyResearch/Mach-1-Ternary-35B",
    label: "mach-1-small",
    cb: CB_EXPERT,                       // K=1.375, per-expert keys
    container: "per-expert",             // e{i}.{proj}.*, kept + demoted
    neCodec: "lloyd",                    // transform-free L=12 group-128
    neFile: (i) => `packed/ne/L${i}.safetensors`,
    headCodec: "ne",                     // lloyd trellis K=3 chunks
    headFile: (i) => `packed/ne/head_c${i}of8.safetensors`,
    embedCodec: "int3",
    embedFile: "packed/ne/embed_int3.safetensors",
    bytes: 6999022925, shards: 93, gb: "7.0",
  },
  additive: {
    repo: "SyzygyResearch/Mach-1-Ternary-Additive-35B",
    label: "mach-1-small-additive",
    cb: CB_EXPERT_V3T,                   // K=1.5, chunk-stacked + wave_gamma
    container: "v3t",
    // canon int-lattice spine: same two-sided-RHT trellis as the demoted
    // experts (int8 SU/SV + scalar Wscale), K=4/V=2/tlut_bits=9, with a
    // tier-shared codebook. Shard names are ZERO-PADDED (L00..L39) — the
    // single-digit L{i} names exist only in legacy builds.
    neCodec: "canon",
    neFile: (i) => `packed/ne/L${String(i).padStart(2, "0")}.safetensors`,
    neTlut: "packed/ne/tlut.safetensors",
    headCodec: "int5",                   // int5-g64, packed/head/
    headFile: (i) => `packed/head/head_c${i}of8.safetensors`,
    embedCodec: "lut4",
    embedFile: "packed/ne/embed_packed.safetensors",
    // UNPINNED (2026-08-04): the repo squashed its history, killing the old
    // revision pin; the lut4 embed container was restored to `main` (gated
    // bit-exact vs the int4 tier's decode), so `main` now serves everything
    // this engine decodes. Do not re-pin a revision id — history squashes
    // delete them; `main` is the stable reference.
    rev: "main",
    // exact sum of the 94 planned files at main (2026-08-04, HEAD-checked)
    bytes: 7819664458, shards: 94, gb: "7.8",
  },
};

export class Engine {
  constructor(device) {
    this.device = device;
    this._pipes = new Map();
    this.maxCtx = 1024;
    this.prefillBatchSize = 8;
    this.prefillBackpressureBatches = 4;
    this._prefixCache = null;
  }

  buf(data, usage = ST()) {
    const b = this.device.createBuffer({ size: Math.max(16, data.byteLength), usage });
    this.device.queue.writeBuffer(b, 0, data);
    return b;
  }

  gbuf(size, usage = STS()) {
    return this.device.createBuffer({ size: Math.max(16, size), usage });
  }

  uni(values) {
    const u = new Uint32Array(Math.max(4, values.length));
    values.forEach((v, i) => { u[i] = v >>> 0; });
    return this.buf(u, GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST);
  }

  pipe(code) {
    let p = this._pipes.get(code);
    if (!p) {
      const module = this.device.createShaderModule({ code });
      p = this.device.createComputePipeline({ layout: "auto", compute: { module, entryPoint: "main" } });
      this._pipes.set(code, p);
    }
    return p;
  }

  bind(pipe, buffers) {
    return this.device.createBindGroup({
      layout: pipe.getBindGroupLayout(0),
      entries: buffers.map((b, i) => ({ binding: i, resource: b.buffer ? b : { buffer: b } })),
    });
  }

  pass(enc, pipe, buffers, dims) {
    const ps = enc.beginComputePass();
    ps.setPipeline(pipe);
    ps.setBindGroup(0, this.bind(pipe, buffers));
    ps.dispatchWorkgroups(...dims);
    ps.end();
  }

  async readBack(gpuBuf, byteLength, byteOffset = 0) {
    const staging = this.device.createBuffer({
      size: byteLength, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ,
    });
    const enc = this.device.createCommandEncoder();
    enc.copyBufferToBuffer(gpuBuf, byteOffset, staging, 0, byteLength);
    this.device.queue.submit([enc.finish()]);
    await staging.mapAsync(GPUMapMode.READ);
    const out = new Float32Array(staging.getMappedRange().slice(0));
    staging.unmap();
    staging.destroy();
    return out;
  }

  // ---------------------------------------------------------------- load
  static async load(device, baseUrl, { onProgress = () => {}, maxCtx = 1024,
    model = "ternary", addOnly = false } = {}) {
    const eng = new Engine(device);
    eng.maxCtx = maxCtx;
    // MUST be set before the warmup step below records the op list. The old
    // contract ("caller assigns engine.ADD_ONLY after load") broke silently
    // when the warmup was added: the ops were recorded with the flag unset,
    // so the shipped "multiply-free" pages were actually running the FMA
    // form. step() now also invalidates the op list if the flag changes.
    eng.ADD_ONLY = !!addOnly;
    const M = MODELS[model];
    if (!M) throw new Error(`unknown model "${model}" (have: ${Object.keys(MODELS)})`);
    eng.model = model;
    eng.M = M;
    const P = (stage, frac) => onProgress(stage, frac);
    // Retry transient failures. This loader pulls 93 files, 6 at a time
    // (PREFETCH below), anonymously — and the Hub answers throttled anonymous
    // traffic with 403, not 429. Without a retry ONE such response anywhere in
    // ~7.8 GB aborts the entire load, which is what "fetch extras.safetensors:
    // HTTP 403" on a healthy public repo means. A real permission 403 (gated
    // repo) still fails, just ~8 s later.
    const TRANSIENT = new Set([403, 408, 425, 429, 500, 502, 503, 504]);
    const RETRIES = 4;
    const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
    const fetchRaw = async (path) => {
      let lastErr;
      for (let attempt = 0; attempt <= RETRIES; attempt++) {
        if (attempt) await sleep(500 * 2 ** (attempt - 1) * (0.7 + Math.random() * 0.6));
        let status = 0;
        try {
          const r = await fetch(`${baseUrl}/${path}`);
          if (r.ok) return new Uint8Array(await r.arrayBuffer());
          status = r.status;
          lastErr = new Error(`fetch ${path}: HTTP ${r.status}`);
        } catch (e) {
          // A dropped connection mid-shard is common on a multi-GB pull, so
          // network failures retry too (status stays 0 = always retryable).
          lastErr = new Error(`fetch ${path}: ${e.message || e}`);
        }
        if (status && !TRANSIENT.has(status)) break;   // 404 etc: fail fast
      }
      throw lastErr;
    };

    P("config + tokenizer", 0);
    const cfgAll = await (await fetch(`${baseUrl}/config.json`)).json();
    const cfg = cfgAll.text_config || cfgAll;
    eng.cfg = cfg;

    // The Hub throttles per CONNECTION (~2-4 MB/s measured), not per client,
    // and this loader consumes its 93 files in a fixed order — so a single
    // sequential walk wastes ~6x of the visitor's bandwidth. Keep PREFETCH
    // downloads in flight ahead of the consumer (bounded: expert shards are
    // ~145 MB, so 6 in flight ≈ 0.9 GB transient). Errors surface when the
    // consumer awaits that file; the early catch just keeps a prefetched
    // failure from firing unhandledrejection first.
    const PREFETCH = 6;
    const nLayers = cfg.num_hidden_layers;
    const plan = [
      "tokenizer.json", "extras.safetensors", M.embedFile,
      "packed/experts/codebook.safetensors",
      ...(M.neTlut ? [M.neTlut] : []),
      ...Array.from({ length: nLayers }, (_, i) => M.neFile(i)),
      ...Array.from({ length: nLayers },
        (_, i) => `packed/experts/L${String(i).padStart(2, "0")}.safetensors`),
      ...Array.from({ length: 8 }, (_, i) => M.headFile(i)),
    ];
    const inflight = new Map();
    let cursor = 0;
    const pump = () => {
      while (inflight.size < PREFETCH && cursor < plan.length) {
        const path = plan[cursor++];
        const pr = fetchRaw(path);
        pr.catch(() => {});
        inflight.set(path, pr);
      }
    };
    const fetchBuf = (path) => {
      let pr = inflight.get(path);
      if (pr !== undefined) inflight.delete(path);
      else pr = fetchRaw(path);          // off-plan path: fetch directly
      pump();
      return pr;
    };
    pump();

    eng.tok = new Tokenizer(JSON.parse(new TextDecoder().decode(await fetchBuf("tokenizer.json"))));
    const H = cfg.hidden_size;
    eng.H = H;

    P("extras", 0.02);
    const extras = await openSafetensorsBuffer(await fetchBuf("extras.safetensors"), "extras");
    const ex = async (name) => (await extras.fetchTensor("model.language_model." + name)).data;

    P(`embedding (${M.embedCodec})`, 0.04);
    const emb = await openSafetensorsBuffer(await fetchBuf(M.embedFile), "embed");
    if (M.embedCodec === "int3") {
      eng.embed = {
        codec: "int3",
        q: (await emb.fetchTensor("q_packed")).data,
        mn: (await emb.fetchTensor("mn")).data,
        mx: (await emb.fetchTensor("mx")).data,
      };
    } else {
      // lut4: 8 vocab chunks, each codes uint8 [rows, hid/2] (two nibbles per
      // byte, LOW nibble = even column) + lut bf16 [rows*ngroups, 16].
      const chunks = [];
      let group = null;
      for (const name of emb.names.filter((n) => n.endsWith(".codes"))) {
        const stem = name.slice(0, -".codes".length);
        const [, s, e] = stem.split(":");
        const c = await emb.fetchTensor(name);
        // safetensors widens BF16 -> f32 exactly, so the LUT is ready to use
        const l = await emb.fetchTensor(`${stem}.lut`);
        // DERIVE the group — do not assume it. codes is [rows, hid/2] and lut
        // is [rows * hid/group, 16]; the live release groups by 64, an earlier
        // build by 128, and guessing wrong silently corrupts every row (the
        // page still generates, just fluent nonsense).
        const rows = c.shape[0], hid = c.shape[1] * 2;
        const g = hid / (l.shape[0] / rows);
        if (group !== null && g !== group) {
          throw new Error(`embed lut4 group ${g} != ${group} across chunks`);
        }
        group = g;
        chunks.push({ start: +s, end: +e, codes: c.data, lut: l.data });
      }
      if (!Number.isInteger(group) || group <= 0) {
        throw new Error(`embed lut4: bad derived group ${group}`);
      }
      chunks.sort((a, b) => a.start - b.start);
      eng.embed = { codec: "lut4", chunks, group };
    }

    P("codebook", 0.06);
    const book = await openSafetensorsBuffer(await fetchBuf("packed/experts/codebook.safetensors"), "codebook");
    const tlutRaw = (await book.fetchTensor("tlut")).data;
    const tlutRounded = Float32Array.from(tlutRaw, f16Round);
    eng.tlut = eng.buf(tlutRounded);
    // f16-packed copy for the routed fused GEMV: rows become one vec4<u32>
    // load (16 B) instead of a 32 B f32 row — bit-equivalent because every
    // entry is f16-exact after the pre-round above.
    const f32b = new Float32Array(1), u32b = new Uint32Array(f32b.buffer);
    const f16bits = (x) => {
      f32b[0] = x;
      const u = u32b[0], sign = (u >>> 16) & 0x8000, a = u & 0x7fffffff;
      if (a >= 0x47800000) return sign | (a > 0x7f800000 ? 0x7e00 : 0x7c00);
      if (a < 0x38800000) {
        const shift = 126 - (a >>> 23);
        if (shift > 24) return sign;
        const mant = (a & 0x7fffff) | 0x800000;
        const q = mant >>> shift, rem = mant & ((1 << shift) - 1), mid = 1 << (shift - 1);
        return sign | (q + ((rem > mid || (rem === mid && (q & 1))) ? 1 : 0));
      }
      let h = sign | ((((a >>> 23) - 112) << 10) & 0x7c00) | ((a >>> 13) & 0x3ff);
      const rem = a & 0x1fff;
      if (rem > 0x1000 || (rem === 0x1000 && (h & 1))) h += 1;
      return h;
    };
    eng.tlut16 = eng.buf(Uint16Array.from(tlutRounded, f16bits));

    // int4 codebook (additive release): 8 nibbles per row, one u32 — 4x fewer
    // gather bytes and a 128 KB table instead of 512 KB. Built from the RAW
    // tlut (not the f16-rounded copy) so the integer lattice is exact. null
    // when the alphabet is not a <=16-level lattice, in which case the f16
    // path is used unchanged.
    eng.tlutInt4 = buildInt4Tlut(tlutRaw, eng.M.cb.V);
    eng.tlutNB = eng.tlutInt4 ? eng.buf(eng.tlutInt4.packed) : null;
    // bit-plane mask table for the multiply-free kernel (same 4 B/row)
    eng.tlutPlanes = eng.tlutInt4 ? buildPlaneTlut(eng.tlutInt4) : null;
    eng.tlutPB = eng.tlutPlanes ? eng.buf(eng.tlutPlanes.packed) : null;
    if (eng.tlutInt4) {
      console.log(`[mach1] int4 codebook: ${eng.tlutInt4.levels} levels, `
        + `step ${eng.tlutInt4.step}, lattice err ${eng.tlutInt4.latticeErr.toExponential(2)}, `
        + `${(eng.tlutInt4.packed.byteLength / 1024) | 0} KB (was `
        + `${(tlutRaw.length * 2 / 1024) | 0} KB)`);
    }

    // shared activation buffers (T = 1)
    const cd = 2 * cfg.linear_num_key_heads * cfg.linear_key_head_dim
      + cfg.linear_num_value_heads * cfg.linear_value_head_dim;
    eng.convDim = cd;
    const Dv = cfg.linear_num_value_heads * cfg.linear_value_head_dim;
    const NH = cfg.num_attention_heads, NKV = cfg.num_key_value_heads, HD = cfg.head_dim;
    eng.b = {
      x: eng.gbuf(H * 4), h1: eng.gbuf(H * 4), h2: eng.gbuf(H * 4),
      convY: eng.gbuf(cd * 4),
      gdnAB: eng.gbuf(2 * cfg.linear_num_value_heads * 4),
      core: eng.gbuf(Dv * 4), normed: eng.gbuf(Dv * 4),
      qn: eng.gbuf(NH * HD * 4), kn: eng.gbuf(NKV * HD * 4), ao: eng.gbuf(NH * HD * 4),
      cos: eng.gbuf(64 * 4), sin: eng.gbuf(64 * 4),
      // routed-MoE scratch, slot-major over the 8 top-k slots
      xslot: eng.gbuf(8 * 2048 * 4), gY: eng.gbuf(8 * 512 * 4), uY: eng.gbuf(8 * 512 * 4),
      // merged gate|up path (v3t): 16 slot-major vectors per dispatch
      xslot16: eng.gbuf(16 * 2048 * 4), guY: eng.gbuf(16 * 512 * 4),
      dY: eng.gbuf(8 * 2048 * 4), t0: eng.gbuf(256 * 4), t1: eng.gbuf(8 * 256 * 4),
      rlogits: eng.gbuf(256 * 4), routeIdx: eng.gbuf(8 * 4),
      moe: eng.gbuf(H * 4), sg: eng.gbuf(16),
      scales: eng.gbuf(8 * 4), attnU: eng.uni([0, 0, 0, 0]),
      hf: eng.gbuf(H * 4),
      ones: eng.buf(new Float32Array([1])),
    };
    eng.b.routerU = eng.uni([256, H, 1, 0]);
    eng.normW = eng.buf(await ex("norm.weight"));

    // canon int-lattice NE spine (additive): ONE codebook shared by all 40
    // shards. f16-pre-round is bit-equivalent to decode.py rounding every
    // gathered unit value — rounding is elementwise and the component-0
    // negation commutes with RNE.
    const neCanon = M.neCodec === "canon";
    const neOnesB = eng.b.ones;
    let neTlutB = null;
    if (neCanon) {
      const ts = await openSafetensorsBuffer(await fetchBuf(M.neTlut), "ne tlut");
      neTlutB = eng.buf(Float32Array.from((await ts.fetchTensor("tlut")).data, f16Round));
    }

    // ------------------------------------------------------------ layers
    eng.layers = [];
    const nL = cfg.num_hidden_layers;
    for (let li = 0; li < nL; li++) {
      P(`layer ${li + 1}/${nL} (NE + extras)`, 0.08 + 0.12 * (li / nL));
      const kind = cfg.layer_types[li];
      const pfx = `layers.${li}.`;
      const L = { kind };
      L.inputLn = eng.buf(await ex(pfx + "input_layernorm.weight"));
      L.postLn = eng.buf(await ex(pfx + "post_attention_layernorm.weight"));
      L.routerW = await ex(pfx + "mlp.gate.weight");   // CPU copy: debug cross-check
      L.routerB = eng.buf(L.routerW);                  // GPU router GEMV
      L.sharedGateW = eng.buf(await ex(pfx + "mlp.shared_expert_gate.weight"));

      const neShard = await openSafetensorsBuffer(await fetchBuf(M.neFile(li)), `ne L${li}`);
      const neMan = neCanon ? null : JSON.parse(neShard.meta.manifest);
      const neDims = neCanon ? JSON.parse(neShard.meta.dims) : null;
      const nePrep = async (suffix, xBuf) => {
        const name = "model.language_model." + pfx + suffix;
        if (neCanon) {
          // Two-sided-RHT trellis, one dense matrix per prep (nExperts = 1):
          // y = sv * H_m( U . H_n(su * x) ) * Wscale, weights streamed from
          // the packed bits exactly as the demoted-expert path does.
          const d = neDims[name];
          if (!d) throw new Error(`NE tensor ${name} missing from dims`);
          const [m0, n0] = d;
          return {
            canon: true, m0, n0, nrows: m0,
            // trellis buffer creation is DEFERRED (_tr) so same-nty tensors
            // can concatenate into one group buffer — see mkGroup below
            _tr: (await neShard.fetchTensor(`${name}|trellis`)).data,
            trellis: null,
            su: eng.buf(Float32Array.from((await neShard.fetchTensor(`${name}|SU`)).data)),
            sv: eng.buf(Float32Array.from((await neShard.fetchTensor(`${name}|SV`)).data)),
            wsc: eng.buf(Float32Array.from((await neShard.fetchTensor(`${name}|Wscale`)).data)),
            tlut: neTlutB, ones: neOnesB, x: xBuf, borrowedX: !!xBuf,
            xhat: eng.gbuf(n0 * 4),
            y: eng.gbuf(Math.max(16, m0 * 4)),
            meta: eng.uni([m0 / 16, n0 / 16, 1, 0]),
            // [nvec, vecsPerExpert, expertStride, vecStride, elemStride,
            //  signMode, gridX, 0] — signMode 1 scales before the butterflies
            //  (su on the input), 2 scales after (sv on the output).
            fwhtXU: eng.uni([1, 1, n0, 0, 1, 1, 1, 0]),
            fwhtYU: eng.uni([1, 1, m0, 0, 1, 2, 1, 0]),
          };
        }
        const geom = neMan.tensors[name];
        if (!geom || geom.transposed) throw new Error(`NE tensor ${name} missing/transposed`);
        const [m0, n0] = geom.shape;
        return prepareNe(device, {
          packed: (await neShard.fetchTensor(`${name}|packed`)).data,
          gscale: (await neShard.fetchTensor(`${name}|gscale`)).data,
          lut: (await neShard.fetchTensor(`${name}|lut`)).data,
          x: xBuf, nrows: m0, tlen: n0, k: neMan.pattern[0], group: neMan.group,
          gemvOnly: true,
        });
      };
      L.shGate = await nePrep("mlp.shared_expert.gate_proj.weight", eng.b.h2);
      L.shUp = await nePrep("mlp.shared_expert.up_proj.weight", eng.b.h2);
      L.shDown = await nePrep("mlp.shared_expert.down_proj.weight", null);
      L.shDown.x = L.shGate.y;    // silu(gate)*up lands in gate.y
      L.shDown.borrowedX = true;  // gate.y is owned by shGate
      // NOTE: canonGemvWGSL's fusedRht (in-kernel input RHT) was MEASURED
      // here and REJECTED: even at only 32 workgroups the redundant
      // barrier-heavy transform cost 4x more than the two split dispatches
      // it saved (shared:gemv 512x2048 went 0.64 -> 2.96 ms/token).
      // Keep fuseIn unset.
      // Same-nty canon tensors GROUP into one concatenated-trellis GEMV
      // dispatch (Metal serializes separate dispatches in a pass — measured:
      // two independent dispatches cost the same as two dependent ones).
      const finTr = (pp) => {
        if (pp && pp.canon && pp._tr) { pp.trellis = eng.buf(pp._tr); pp._tr = null; }
      };
      const mkGroup = (pps) => {
        if (!pps[0].canon) return null;
        let total = 0;
        for (const p of pps) total += p._tr.byteLength;
        const cat = new Uint8Array(total);
        let off = 0;
        for (const p of pps) {
          cat.set(new Uint8Array(p._tr.buffer, p._tr.byteOffset, p._tr.byteLength), off);
          off += p._tr.byteLength;
          p._tr = null;
        }
        return { trellis: eng.buf(cat), tensors: pps,
          ranges: pps.map((p) => p.m0 / 16), nty: pps[0].n0 / 16 };
      };
      if (neCanon) {
        L.gGU = mkGroup([L.shGate, L.shUp]);
        finTr(L.shDown);
      }

      if (kind === "linear_attention") {
        L.qkv = await nePrep("linear_attn.in_proj_qkv.weight", eng.b.h1);
        L.z = await nePrep("linear_attn.in_proj_z.weight", eng.b.h1);
        L.outP = await nePrep("linear_attn.out_proj.weight", eng.b.normed);
        if (neCanon) { L.gQKVZ = mkGroup([L.qkv, L.z]); finTr(L.outP); }
        // conv1d.weight [convDim, 1, ck] flattens to the kernel's [c*ck+j]
        L.convW = eng.buf(await ex(pfx + "linear_attn.conv1d.weight"));
        L.aLog = eng.buf(await ex(pfx + "linear_attn.A_log"));
        L.dtBias = eng.buf(await ex(pfx + "linear_attn.dt_bias"));
        // wA and wB concatenated row-wise: ONE dense GEMV writes [a | b]
        // into gdnAB, and the recurrence (fusedScalars) reads both halves —
        // replaces two GEMV dispatches + the gdnScalars dispatch per layer.
        {
          const wA = await ex(pfx + "linear_attn.in_proj_a.weight");
          const wB = await ex(pfx + "linear_attn.in_proj_b.weight");
          const ab = new Float32Array(wA.length + wB.length);
          ab.set(wA, 0);
          ab.set(wB, wA.length);
          L.wAB = eng.buf(ab);
        }
        L.gdnNormW = eng.buf(await ex(pfx + "linear_attn.norm.weight"));
        L.convState = eng.gbuf(cd * (cfg.linear_conv_kernel_dim - 1) * 4);
        L.S = eng.gbuf(cfg.linear_num_value_heads * cfg.linear_value_head_dim
          * cfg.linear_key_head_dim * 4);
        L.abU = eng.uni([2 * cfg.linear_num_value_heads, H, 1, 0]);
      } else {
        L.q = await nePrep("self_attn.q_proj.weight", eng.b.h1);
        L.k = await nePrep("self_attn.k_proj.weight", eng.b.h1);
        L.v = await nePrep("self_attn.v_proj.weight", eng.b.h1);
        L.o = await nePrep("self_attn.o_proj.weight", eng.b.ao);
        if (neCanon) { L.gQKV = mkGroup([L.q, L.k, L.v]); finTr(L.o); }
        L.qNorm = eng.buf(await ex(pfx + "self_attn.q_norm.weight"));
        L.kNorm = eng.buf(await ex(pfx + "self_attn.k_norm.weight"));
        L.kCache = eng.gbuf(maxCtx * NKV * HD * 4);
        L.vCache = eng.gbuf(maxCtx * NKV * HD * 4);
        L.scr = eng.gbuf(NH * maxCtx * 4);
      }
      eng.layers.push(L);
    }

    // ---------------------------------------------------------- expert tier
    // ternary: per-expert keys e{i}.{proj}.*, kept + demoted (+ shared basis).
    // additive (v3t): 32-expert CHUNK-STACKED keys e{c0}.{proj}.{trellis|su|
    // sv|wave_gamma}, one uniform population, Wscale absorbed into sv, and a
    // per-(expert, wavefront) gamma replacing the scalar wscale.
    const geomOf = { gate: [512, 2048], up: [512, 2048], down: [2048, 512] };
    const v3t = M.container === "v3t";
    const c = codecConsts(M.cb);
    const trBytes = c.WORDS_PER_TILE * 2 * 4096;      // per expert per proj
    for (let li = 0; li < nL; li++) {
      P(`layer ${li + 1}/${nL} experts (${(trBytes * 3 * 256 / 1e6).toFixed(0)} MB packed)`,
        0.2 + 0.78 * (li / nL));
      const shard = await openSafetensorsBuffer(
        await fetchBuf(`packed/experts/L${String(li).padStart(2, "0")}.safetensors`), `experts L${li}`);
      const man = shard.meta.manifest ? JSON.parse(shard.meta.manifest) : null;
      const L = eng.layers[li];
      L.demoted = new Set(man && man.demoted ? man.demoted : []);
      L.basisR = man && man.basis ? man.basis.r : 0;
      const dm = new Uint32Array(256);
      for (const e of L.demoted) dm[e] = 1;
      L.dmaskB = eng.buf(dm);                // guards the routed basis kernels
      L.ex = {};
      const rawGU = {};      // v3t: gate/up CPU arrays held back for the merge
      for (const proj of ["gate", "up", "down"]) {
        const [m0, n0] = geomOf[proj];
        const tr = new Uint8Array(256 * trBytes);
        const su = new Float32Array(256 * n0);
        const sv = new Float32Array(256 * m0);
        const wsc = new Float32Array(256 * 64);
        const cc = new Float32Array(256 * 256);
        const nWave = m0 / 16 + n0 / 16;
        const gam = v3t ? new Float32Array(256 * nWave) : null;
        if (v3t) {
          for (let c0 = 0; c0 < 256; c0 += 32) {
            const t = await shard.fetchTensor(`e${c0}.${proj}.trellis`);
            tr.set(new Uint8Array(t.data.buffer, t.data.byteOffset, 32 * trBytes),
              c0 * trBytes);
            su.set((await shard.fetchTensor(`e${c0}.${proj}.su`)).data, c0 * n0);
            sv.set((await shard.fetchTensor(`e${c0}.${proj}.sv`)).data, c0 * m0);
            gam.set((await shard.fetchTensor(`e${c0}.${proj}.wave_gamma`)).data,
              c0 * nWave);
          }
        } else {
          for (let e = 0; e < 256; e++) {
            const t = await shard.fetchTensor(`e${e}.${proj}.trellis`);
            tr.set(new Uint8Array(t.data.buffer, t.data.byteOffset, trBytes), e * trBytes);
            if (L.demoted.has(e)) {
              su.set(Float32Array.from((await shard.fetchTensor(`e${e}.${proj}.SU`)).data), e * n0);
              sv.set(Float32Array.from((await shard.fetchTensor(`e${e}.${proj}.SV`)).data), e * m0);
              wsc[e * 64] = (await shard.fetchTensor(`e${e}.${proj}.Wscale`)).data[0];
              cc.set((await shard.fetchTensor(`e${e}.${proj}.c`)).data, e * 256);
            } else {
              su.set((await shard.fetchTensor(`e${e}.${proj}.su`)).data, e * n0);
              sv.set((await shard.fetchTensor(`e${e}.${proj}.sv`)).data, e * m0);
              wsc[e * 64] = 1;
            }
          }
        }
        if (v3t) wsc.fill(1);          // no Wscale: sv carries it (output pass)
        if (v3t && proj !== "down") {
          // gate/up GPU buffers are NOT created per-proj for the additive
          // container — they merge into ONE concatenated set below (same
          // total bytes; the up half is addressed as expert te + 256).
          rawGU[proj] = { tr, su, sv, wsc, gam, m0, n0 };
          continue;
        }
        L.ex[proj] = {
          m0, n0,
          trellis: eng.buf(tr),
          su: eng.buf(su), sv: eng.buf(sv), wsc: eng.buf(wsc),
          c: v3t ? null : eng.buf(cc),
          gamma: v3t ? eng.buf(gam) : null,
          basisA: L.basisR ? eng.buf((await shard.fetchTensor(`basis.${proj}.A`)).data) : null,
          basisB: L.basisR ? eng.buf((await shard.fetchTensor(`basis.${proj}.B`)).data) : null,
          // routed fast path: 8 slot-major vectors per dispatch
          meta: eng.uni([m0 / 16, n0 / 16, 8, 0]),
          fwhtXU: eng.uni([8, 1, n0, 0, 1, 1, 8, 0]),
          fwhtYU: eng.uni([8, 1, m0, 0, 1, 2, 8, 0]),
          gemvA1U: eng.uni([256, n0, 1, 0]),   // gate/up: A@h2, slot-invariant
          gemvAU: eng.uni([256, n0, 8, 0]),    // down: A@act per slot, guarded
          gemvBU: eng.uni([m0, 256, 8, 0]),
        };
      }
      if (v3t) {
        const g = rawGU.gate, u = rawGU.up;
        const cat = (A, B, T) => { const o = new T(A.length + B.length);
          o.set(A, 0); o.set(B, A.length); return o; };
        L.exGU = {
          m0: g.m0, n0: g.n0,
          trellis: eng.buf(cat(g.tr, u.tr, Uint8Array)),
          su: eng.buf(cat(g.su, u.su, Float32Array)),
          sv: eng.buf(cat(g.sv, u.sv, Float32Array)),
          wsc: eng.buf(cat(g.wsc, u.wsc, Float32Array)),
          gamma: eng.buf(cat(g.gam, u.gam, Float32Array)),
          meta: eng.uni([g.m0 / 16, g.n0 / 16, 16, 0]),
          fwhtYU: eng.uni([16, 1, g.m0, 0, 1, 2, 16, 0]),
        };
      }
    }
    // tile -> wavefront index maps (host-computed once per geometry; the
    // recurrence is decode.py's wave_index_map, ported in reference.js)
    if (v3t) {
      eng.waveIdxB = {};
      for (const [m0, n0] of [[512, 2048], [2048, 512]]) {
        eng.waveIdxB[`${m0}x${n0}`] = eng.buf(waveIndexMap(m0 / 16, n0 / 16));
      }
    }

    // ------------------------------------------------------------- lm_head
    P("lm_head", 0.985);
    eng.head = [];
    eng.vocab = 0;
    for (let ci = 0; ci < 8; ci++) {
      const shard = await openSafetensorsBuffer(
        await fetchBuf(M.headFile(ci)), `head ${ci}`);
      if (M.headCodec === "int5") {
        // additive: int5-g64, file-level metadata (no "manifest" key) —
        // dims maps the chunk name to [rows, hdim].
        const dims = JSON.parse(shard.meta.dims);
        const name = Object.keys(dims)[0];
        const [rows, hdim] = dims[name];
        eng.head.push({
          rows, int5: true,
          p: prepareInt5(device, {
            qp: (await shard.fetchTensor(`${name}|qp`)).data,
            gscale: (await shard.fetchTensor(`${name}|gscale`)).data,
            x: eng.b.hf, nrows: rows, tlen: hdim,
            group: parseInt(shard.meta.group, 10) || 64,
          }),
        });
        eng.vocab += rows;
        continue;
      }
      const man = JSON.parse(shard.meta.manifest);
      const name = Object.keys(man.tensors)[0];
      const [rows, hdim] = man.tensors[name].shape;
      eng.head.push({
        rows,
        p: prepareNe(device, {
          packed: (await shard.fetchTensor(`${name}|packed`)).data,
          gscale: (await shard.fetchTensor(`${name}|gscale`)).data,
          lut: (await shard.fetchTensor(`${name}|lut`)).data,
          x: eng.b.hf, nrows: rows, tlen: hdim, k: man.pattern[0], group: man.group,
          gemvOnly: true,
        }),
      });
      eng.vocab += rows;
    }
    eng.logitsBuf = eng.gbuf(eng.vocab * 4);
    // GPU-compacted sampling: global max + threshold compaction so the
    // per-token readback is ~32 KB instead of the 1 MB logits vector.
    eng.sampleCap = 4096;
    eng.nPartial = Math.ceil(eng.vocab / 1024);
    eng.partialMax = eng.gbuf(eng.nPartial * 4);
    eng.mxBuf = eng.gbuf(4);
    eng.ctrBuf = eng.gbuf(4);
    eng.topIdx = eng.gbuf(eng.sampleCap * 4);
    eng.topVal = eng.gbuf(eng.sampleCap * 4);
    eng.maxAU = eng.uni([eng.vocab, 0, 0, 0]);
    eng.maxBU = eng.uni([eng.nPartial, 0, 0, 0]);
    eng.compactU = eng.uni([eng.vocab, 0, 0, 0]);   // .thr (f32) written per step
    eng.sampleStaging = device.createBuffer({
      size: 4 + eng.sampleCap * 8,
      usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ,
    });
    eng._thr = 12 * 0.7;

    // Warmup, and a HARD failure gate. A compute pipeline that fails to
    // create (e.g. a shader over the workgroup-storage limit) is not an
    // exception in WebGPU: every dispatch using it silently becomes a no-op,
    // so the model still "runs", every activation stays zero, and the
    // sampler falls back to uniform-random tokens — fluent-looking multi-
    // lingual gibberish that no per-kernel bit-exactness test can catch.
    // ---- subgroup capability probe (before the op list is recorded).
    // The shuffle-based FWHT assumes lane == lid.x % subgroup_size, which
    // WGSL leaves implementation-defined: verify it with a real dispatch
    // and enable the subgroup kernels only when it holds and the size is a
    // power of two. The fallback kernels are bit-identical, so this is a
    // pure performance switch — never a correctness one.
    eng.sgS = 0;
    if (device.features.has("subgroups")) {
      try {
        const probe = eng.pipe(sgProbeWGSL(256));
        const outB = eng.gbuf(256 * 4);
        const encP = device.createCommandEncoder();
        const psP = encP.beginComputePass();
        psP.setPipeline(probe);
        psP.setBindGroup(0, eng.bind(probe, [outB]));
        psP.dispatchWorkgroups(1);
        psP.end();
        device.queue.submit([encP.finish()]);
        const words = new Uint32Array((await eng.readBack(outB, 256 * 4)).buffer);
        const S = words[0] >>> 16;
        let ok = S >= 8 && S <= 128 && (S & (S - 1)) === 0;
        for (let i = 0; ok && i < 256; i++) {
          ok = (words[i] & 0xffff) === i % S && (words[i] >>> 16) === S;
        }
        eng.sgS = ok ? S : 0;
        outB.destroy();
      } catch { eng.sgS = 0; }
    }
    // Build the op list and run one real token inside an error scope so that
    // failure is loud, here, with the driver's own message.
    P("warmup", 1);
    device.pushErrorScope("validation");
    await eng.step(eng.tok.encode("\n")[0] || 0, 0, true);
    const gpuErr = await device.popErrorScope();
    eng.resetState();
    if (gpuErr) {
      throw new Error("GPU validation error during warmup — the model would "
        + "have produced garbage silently: " + gpuErr.message);
    }
    P("ready", 1);
    return eng;
  }

  // -------------------------------------------------------------- helpers
  embedRow(id) {
    const H = this.H;
    if (this.embed.codec === "lut4") {
      // additive: 4-bit code per element (low nibble = even column) into a
      // per-row per-group 16-entry bf16 table (already f32-widened). `group`
      // is derived from the shipped shapes at load time, never assumed.
      const { chunks, group } = this.embed;
      const ch = chunks.find((c) => id >= c.start && id < c.end) || chunks[0];
      const r = id - ch.start;
      const ng = H / group;
      const out = new Float32Array(H);
      const cb = r * (H >> 1), lb = r * ng * 16;
      for (let j = 0; j < H; j++) {
        const byte = ch.codes[cb + (j >> 1)];
        const code = (j & 1) ? (byte >> 4) : (byte & 15);
        out[j] = ch.lut[lb + ((j / group) | 0) * 16 + code];
      }
      return out;
    }
    const { q, mn, mx } = this.embed;
    const group = 64, ng = H / group, lv = 7;
    const out = new Float32Array(H);
    const rowBytes = (H * 3) / 8;
    let pos = id * rowBytes * 8;
    for (let j = 0; j < H; j++) {
      let qv = 0;
      for (let b = 0; b < 3; b++, pos++) {
        qv = (qv << 1) | ((q[pos >>> 3] >>> (7 - (pos & 7))) & 1);
      }
      const g = (j / group) | 0;
      const d = Math.fround(mx[id * ng + g] - mn[id * ng + g]);
      const step = Math.fround(Math.max(d, Math.fround(1e-8)) / lv);
      out[j] = Math.fround(mn[id * ng + g] + Math.fround(qv * step));
    }
    return out;
  }

  ropeAt(pos) {
    const rot = Math.round(this.cfg.head_dim * this.cfg.rope_parameters.partial_rotary_factor);
    const theta = this.cfg.rope_parameters.rope_theta;
    const half = rot / 2;
    const cos = new Float32Array(rot), sin = new Float32Array(rot);
    for (let i = 0; i < half; i++) {
      const f = pos / Math.pow(theta, (2 * i) / rot);
      cos[i] = Math.cos(f); cos[i + half] = cos[i];
      sin[i] = Math.sin(f); sin[i + half] = sin[i];
    }
    return { cos, sin };
  }

  // ---------------------------------------------------- token op recording
  // Record the ENTIRE token — all 40 layers, GPU routing included, plus the
  // lm_head — as a static op list: pipelines and bind groups are created
  // exactly once, then every step() replays the list into one command
  // encoder and one submit. Only encoder-level commands (KV-cache copies at
  // the current position, moe clear, the logits->staging copy) are closures.
  _record() {
    const { cfg, H, b } = this;
    const ops = [];
    // `tg` is a profiling stage label captured onto every op — it has no
    // effect on execution; profileStages() groups and times ops by it.
    let tg = "misc";
    const push = (code, buffers, dims) => {
      const p = this.pipe(code);
      ops.push({ p, bg: this.bind(p, buffers), d: dims, t: tg });
    };
    const enc0 = (fn) => ops.push({ enc: fn, t: tg });
    // canon int-lattice NE tensor: copy x -> xhat, H_n(su*x), fused trellis
    // GEMV from the packed bits, then H_m(...)*sv*Wscale. Same y contract as
    // the lloyd path, so every downstream consumer is unchanged.
    // The one-pass FWHT needs dim*4 bytes of workgroup storage. The spine's
    // m0 reaches 8192 (in_proj_qkv / q_proj) = 32 KB, over the 16 KB WebGPU
    // default; gpu.js requests the adapter's real limit, and anything still
    // too big goes through the bit-identical two-pass split. A pipeline that
    // fails to create is NOT an exception — every dispatch using it silently
    // no-ops — so this must be decided up front, never discovered at runtime.
    const WGS = this.device.limits.maxComputeWorkgroupStorageSize;
    const splitC = (dim) => { let c = 1; while (c * 2 <= dim && c * 2 * 4 <= WGS) c *= 2; return c; };
    // Parallelism split for the OUTPUT RHT. The one-pass FWHT is a SINGLE
    // workgroup, so its cost scales with dim while the rest of the GPU idles:
    // measured 2048 -> 11 us, 4096 -> 21, 8192 -> 41.5. The two-pass split
    // (already the production path above the shared-memory limit, and pinned
    // bit-identical by test_browser's "[fwht split]" cases) spreads the same
    // work over dim/C + C workgroups:
    //   8192  41.5 -> 7.0 us  (5.9x, C=128)
    //   4096  21.0 -> 6.0 us  (3.5x)
    //   2048  11.0 -> 6.0 us  (1.8x)
    // Applied ONLY where src is null — i.e. the output RHT. The input RHT
    // reads its source through `bcast` (no staging copy, no pass break) and
    // the split has no bcast variant, so switching it there would trade a
    // measured win for a measured loss.
    // C near sqrt(dim) keeps BOTH passes wide; C == dim degenerates the row
    // pass back to one workgroup, which is how this looks like a regression
    // if you benchmark it wrong.
    const parC = (dim) => {
      let c = 1 << Math.round(Math.log2(Math.sqrt(dim)));
      c = Math.max(64, Math.min(256, c));
      while (c * 4 > WGS || (dim / c) * 4 > WGS) c >>= 1;
      return c;
    };
    // Subgroup FWHT (probe-gated, bit-identical to every fallback below):
    // one dispatch per transform regardless of dim, shuffle rounds instead
    // of most shared-memory rounds. SG = 0 keeps the portable kernels.
    const SG = this.sgS | 0;
    // sg viability: MEASURED to win only when the dispatch has >= 8
    // workgroups (the routed expert slots). A single-vector sg transform is
    // ONE workgroup on one core — fewer barriers, but the wide split's
    // dim/C + C workgroups across all cores beat it soundly (spine:fwht
    // 1.41 -> 1.85 ms when sg was applied there). nvec gates it.
    const sgOK = (dim, nvec) => {
      if (!SG || nvec < 8 || dim < 512) return false;
      const wg = Math.min(256, Math.max(SG, dim / 8));
      const E = dim / wg;
      return Number.isInteger(E) && E >= 2 && (E * SG >= dim || dim * 4 <= WGS);
    };
    const fwht1 = (data, signs, uni, scales, dim, mode, src) => {
      if (dim * 4 <= WGS && !src && dim >= 2048) {
        const C = parC(dim);
        push(fwhtSplitRowWGSL(dim, C, { preSign: false }), [data], [dim / C, 1]);
        push(fwhtSplitColWGSL(dim, C, { postSign: mode === 2 }),
          mode === 2 ? [data, signs, scales] : [data, scales], [C, 1]);
        return;
      }
      // Input RHT (src set, mode 1): the split's bcast variant reads x
      // straight from src — still no staging copy, no pass break — and
      // spreads the butterflies over dim/C + C workgroups instead of ONE.
      // Same measured win as the output RHT split (2048: 11 -> 6 us,
      // 4096: 21 -> 6), bit-identical by the same H_R (x) H_C argument.
      if (dim * 4 <= WGS && src && mode === 1 && dim >= 2048) {
        const C = parC(dim);
        push(fwhtSplitRowWGSL(dim, C, { preSign: true, bcast: true }),
          [data, signs, src], [dim / C, 1]);
        push(fwhtSplitColWGSL(dim, C, { postSign: false }), [data, scales], [C, 1]);
        return;
      }
      if (dim * 4 <= WGS) {
        // `bcast` reads the source vector directly, so the input RHT needs no
        // staging copy — and no copy means no compute-pass break. At ~250
        // spine tensors per token that removed 250 pass boundaries.
        push(fwhtWGSL(dim, 256, { bcast: !!src }),
          src ? [data, signs, uni, scales, src] : [data, signs, uni, scales], [1, 1]);
        return;
      }
      // Split path (adapter still under the one-pass limit) has no bcast
      // variant; fall back to the staging copy for those dims only.
      if (src) enc0((enc) => enc.copyBufferToBuffer(src, 0, data, 0, dim * 4));
      const C = splitC(dim);
      const pre = mode === 1, post = mode === 2;
      push(fwhtSplitRowWGSL(dim, C, { preSign: pre }),
        pre ? [data, signs] : [data], [dim / C, 1]);
      push(fwhtSplitColWGSL(dim, C, { postSign: post }),
        post ? [data, signs, scales] : [data, scales], [C, 1]);
    };
    // Single chain, deliberately. `dual` halves the 128-step serial register
    // walk and IS bit-exact here (the two chains own disjoint output rows),
    // but it measured 1.5-1.7x SLOWER at V=2 on Metal — 8192x2048 went
    // 161 -> 278 us, 2048x4096 111 -> 159. Two chains double the live
    // registers while each step still yields only V=2 values, so occupancy
    // falls faster than the chain shortens. It wins for the V=8 experts,
    // where a step does 4x the work per register. Do not "fix" this.
    // Specialized V=2 kernel (unrolled chain, register accumulators): 2.9-3.1x
    // over the generic fusedGemvWGSL on the wide spine shapes, 1.3-2.1x on the
    // shared-expert ones — MEASURED on apple metal-3 (M5 Max), qkv 8192x2048
    // 80 -> 26 us (645 Gw/s). Same wg-cap rule as the experts: never exceed
    // nty. The shared codebook lives in workgroup memory only where the
    // workgroup is too small to hide the L1 gather latency (wg < 128; the
    // only such shape, 2048x512, measured 16 -> 13 us with it, while at
    // wg=128 it is neutral-to-slightly-negative).
    // Outputs sit 1-2 ulp from the generic kernel (register accumulators let
    // the compiler contract mul+add to FMA; the scratch-array form didn't) —
    // within the fused-GEMV tolerance contract vs f64.
    const canonPipe = (n0) => {
      const wg = Math.min(128, n0 / 16);
      return canonGemvWGSL(CB_NE_CANON, wg, { sharedTlut: wg < 128, sgAdd: SG });
    };
    const canonNe = (pp) => {
      const t0 = tg;
      if (pp.fuseIn) {
        // shared-expert tensors (<=128 workgroups): the input RHT runs
        // inside the GEMV — no separate dispatches, no xhat round trip.
        // Bit-identical (same butterfly order as the standalone kernel).
        const wg = Math.min(128, pp.n0 / 16);
        tg = `${t0}:gemv ${pp.m0}x${pp.n0}`;
        push(canonGemvWGSL(CB_NE_CANON, wg,
          { sharedTlut: wg < 128, fusedRht: pp.n0, sgAdd: SG }),
          [pp.trellis, pp.tlut, pp.x, pp.y, pp.meta, pp.su], [pp.m0 / 16, 1]);
      } else {
        tg = `${t0}:fwht`;
        fwht1(pp.xhat, pp.su, pp.fwhtXU, pp.ones, pp.n0, 1, pp.x);
        tg = `${t0}:gemv ${pp.m0}x${pp.n0}`;
        push(canonPipe(pp.n0), [pp.trellis, pp.tlut, pp.xhat, pp.y, pp.meta], [pp.m0 / 16, 1]);
      }
      tg = `${t0}:fwht`;
      fwht1(pp.y, pp.sv, pp.fwhtYU, pp.wsc, pp.m0, 2, null);
      tg = t0;
    };
    const ne = (pp) => (pp.canon ? canonNe(pp)
      : push(neFusedGemvWGSL(pp.k, { group: pp.group }),
        [pp.packed, pp.lut, pp.gscale, pp.x, pp.y, pp.meta], [pp.nrows]));
    // Same-source input RHTs batched into one [dim/C, count] split pair:
    // qkv+z (and q/k/v) all transform h1 with different su, so their input
    // FWHTs are independent same-shape work — bit-identical per tensor,
    // count-1 fewer dispatch pairs.
    const neBatchIn = (pps) => {
      if (!pps[0].canon) { for (const pp of pps) ne(pp); return; }
      const t0 = tg;
      const dim = pps[0].n0;
      const C = parC(dim);
      tg = `${t0}:fwht`;
      push(fwhtSplitRowMultiWGSL(dim, C, pps.length),
        [...pps.map((p) => p.xhat), ...pps.map((p) => p.su), pps[0].x],
        [dim / C, pps.length]);
      push(fwhtSplitColMultiWGSL(dim, C, pps.length),
        [...pps.map((p) => p.xhat), pps[0].ones], [C, pps.length]);
      for (const pp of pps) {
        tg = `${t0}:gemv ${pp.m0}x${pp.n0}`;
        push(canonPipe(pp.n0), [pp.trellis, pp.tlut, pp.xhat, pp.y, pp.meta], [pp.m0 / 16, 1]);
        tg = `${t0}:fwht`;
        fwht1(pp.y, pp.sv, pp.fwhtYU, pp.wsc, pp.m0, 2, null);
      }
      tg = t0;
    };
    // Grouped canon tensors (same nty, concatenated trellis): batched
    // input RHT, then ONE GEMV dispatch covering every tensor's tile-rows,
    // then per-tensor output RHTs. Bit-identical per tensor.
    const neGroup = (grp) => {
      const pps = grp.tensors;
      const t0 = tg;
      const dim = pps[0].n0;
      const C = parC(dim);
      tg = `${t0}:fwht`;
      push(fwhtSplitRowMultiWGSL(dim, C, pps.length),
        [...pps.map((p) => p.xhat), ...pps.map((p) => p.su), pps[0].x],
        [dim / C, pps.length]);
      push(fwhtSplitColMultiWGSL(dim, C, pps.length),
        [...pps.map((p) => p.xhat), pps[0].ones], [C, pps.length]);
      tg = `${t0}:gemv group[${pps.map((p) => p.m0).join("+")}]x${dim}`;
      push(canonGemvWGSL(CB_NE_CANON, Math.min(128, grp.nty),
        { ranges: grp.ranges, nty: grp.nty, sgAdd: SG,
          sharedTlut: Math.min(128, grp.nty) < 128 }),
        [grp.trellis, pps[0].tlut, ...pps.map((p) => p.xhat), ...pps.map((p) => p.y)],
        [grp.ranges.reduce((a, b) => a + b, 0), 1]);
      tg = `${t0}:fwht`;
      for (const pp of pps) fwht1(pp.y, pp.sv, pp.fwhtYU, pp.wsc, pp.m0, 2, null);
      tg = t0;
    };
    // additive lm_head chunk: int5-g64 GEMV (same y/meta contract as `ne`).
    // The fast path (five aligned u32 loads per 32 codes, unrolled extract)
    // needs word-aligned rows and whole 4-block chunks: tlen % 32 == 0.
    const int5 = (pp) => push(pp.tlen % 32 === 0
      ? int5GemvFastWGSL({ group: pp.group, sgAdd: SG })
      : int5GemvWGSL({ group: pp.group }),
      [pp.qp, pp.gscale, pp.x, pp.y, pp.meta], [pp.nrows]);
    const nv = cfg.linear_num_value_heads;
    const NH = cfg.num_attention_heads, NKV = cfg.num_key_value_heads, HD = cfg.head_dim;
    const rms = rmsnormWGSL(H, cfg.rms_norm_eps);
    const add = addWGSL();
    const smul = siluMulWGSL();
    const gemvS = denseGemvWGSL("f32", 256, false, true);
    // vec4 weight loads for the H-wide dense GEMVs (router, GDN a|b,
    // shared gate) — 4 weights per 16-byte load; H % 4 == 0 always here
    const gemvS4 = denseGemvWGSL("f32v4", 256, false, true);
    // routed expert GEMV: gamma variant for the additive (v3t) container —
    // K=1.5 keeps the dual-chain seed u16-aligned (HALF*STEP = 192 bits).
    const v3t = this.M.container === "v3t";
    // int4 beats the f16-vec4 + dual-chain pairing by a wide margin: the
    // nibble gather measured 1.95x standalone where dual is worth ~1.5%, and
    // dual REQUIRES tlutF16 so the two are exclusive. Take the 1.95x.
    // ADD_ONLY makes the expert GEMV genuinely multiply-free (one lattice-step
    // multiply per output, in the epilogue) — correct but ~2.5x slower, so it
    // is a demonstrable toggle, not the default.
    const useInt4 = v3t && !!this.tlutInt4;
    const addOnly = useInt4 && !!this.ADD_ONLY;
    // multiply-free path upgrades to the BIT-PLANE form when the mask table
    // exists: A0 + 2*A1 + 4*A2 per state (one doubling per plane per state,
    // not per weight) — same adds-only execution, ~2x fewer ops.
    const usePlanes = addOnly && !!this.tlutPB;
    const fusedOpts = useInt4
      ? { routed: true, gamma: true, planes: usePlanes,
          int4: { ints: this.tlutInt4.ints, step: this.tlutInt4.step,
                  additive: addOnly } }
      : { routed: true, tlutF16: true, dual: true, gamma: v3t };
    // Workgroup size must not exceed the tile count it strides over: the tile
    // loop is `for (t = lid.x; t < nty; t += wg)`, so any thread with
    // lid.x >= nty does NOTHING. down is 2048x512 -> nty = 32, where a fixed
    // wg=128 idles 96 of 128 threads. MEASURED on apple metal-3, int4-add:
    //   512x2048 (nty=128)  wg64 250 / wg128 262 / wg256 227 Gw/s
    //   2048x512 (nty=32)   wg32 280 / wg64 271 / wg128 224 Gw/s
    // so cap at nty and keep 128 where the tiles are there to use it.
    const wgFor = (n0) => Math.min(128, n0 / 16);
    // int4 path: the unrolled generator (register accumulators, static refill
    // schedule, affine nibble->level arithmetic) — same bindings, same
    // multiply-free structure for the additive form. The non-int4 fallback
    // stays on the generic kernel.
    const expertGemv = (wg) => (useInt4
      ? expertGemvUnrolledWGSL(this.M.cb, wg, { ...fusedOpts, sgAdd: SG })
      : fusedGemvWGSL(this.M.cb, wg, fusedOpts));
    const fusedGU = expertGemv(wgFor(2048));
    const fusedDN = expertGemv(wgFor(512));
    const expTlut = useInt4 ? (usePlanes ? this.tlutPB : this.tlutNB) : this.tlut16;
    // per-geometry extra bindings for the gamma path
    const gext = (g) => (v3t ? [g.gamma, this.waveIdxB[`${g.m0}x${g.n0}`]] : []);

    // Fused residual+norm (addRmsWGSL): every add/rms pair collapses to one
    // dispatch — the attn/GDN output add with postLn, and each MoE output
    // add with the NEXT layer's inputLn (deferred across the loop edge).
    // Layer 0's inputLn has no pending add; the LAST MoE add stays plain so
    // the prefill slice (ops[0..headStart)) still completes the residual —
    // the final norm lives on the head side of that boundary.
    const addRms = addRmsWGSL(H, cfg.rms_norm_eps);
    for (let li = 0; li < this.layers.length; li++) {
      const L = this.layers[li];
      tg = "norm+add";
      if (li === 0) push(rms, [b.x, L.inputLn, b.h1], [1]);
      // li > 0: the previous layer's bottom emitted addRmsMoe, which already
      // applied the residual AND this layer's inputLn norm into h1
      if (L.kind === "linear_attention") {
        tg = "spine";
        if (L.gQKVZ) neGroup(L.gQKVZ); else neBatchIn([L.qkv, L.z]);
        tg = "gdn";
        // one GEMV for [a | b] (concat weights), scalars fused into the
        // recurrence: 4 dispatches per GDN block instead of 6
        push(gemvS4, [L.wAB, b.h1, b.gdnAB, L.abU], [2 * nv, 1]);
        push(convStepWGSL(this.convDim, cfg.linear_conv_kernel_dim),
          [L.qkv.y, L.convW, L.convState, b.convY], [Math.ceil(this.convDim / 256)]);
        push(gdnRecurrenceWGSL(cfg, 1,
          { fusedScalars: true, fusedNorm: cfg.rms_norm_eps }),
          [b.convY, b.gdnAB, L.aLog, L.S, b.normed, L.dtBias,
            L.z.y, L.gdnNormW], [nv]);
        tg = "spine";
        ne(L.outP);
      } else {
        tg = "spine";
        if (L.gQKV) neGroup(L.gQKV); else neBatchIn([L.q, L.k, L.v]);
        tg = "attn";
        const rot = Math.round(HD * cfg.rope_parameters.partial_rotary_factor);
        push(qkNormRopeWGSL(NH, HD, rot, 2 * HD, cfg.rms_norm_eps),
          [L.q.y, L.qNorm, b.cos, b.sin, b.qn], [NH, 1]);
        push(qkNormRopeWGSL(NKV, HD, rot, HD, cfg.rms_norm_eps),
          [L.k.y, L.kNorm, b.cos, b.sin, b.kn], [NKV, 1]);
        // cache append as a kernel (pos from the attn uniform) — the old
        // copyBufferToBuffer pair broke the compute pass every attn layer
        push(appendKVWGSL(NKV * HD),
          [b.kn, L.v.y, L.kCache, L.vCache, b.attnU], [Math.ceil((NKV * HD) / 256)]);
        push(attnDecodeWGSL(NH, NKV, HD, this.maxCtx),
          [b.qn, L.kCache, L.vCache, L.scr, b.ao, b.attnU], [NH]);
        push(attnGateMulWGSL(NH, HD),
          [b.ao, L.q.y, b.attnU2 || (b.attnU2 = this.uni([0, 0, 0, 0]))],
          [Math.ceil((NH * HD) / 256)]);
        tg = "spine";
        ne(L.o);
      }
      tg = "norm+add";
      push(addRms, [b.x, L.kind === "linear_attention" ? L.outP.y : L.o.y,
        L.postLn, b.h2], [1]);

      // GPU router: logits GEMV -> top-8 indices + softmaxed weights
      tg = "router";
      push(gemvS4, [L.routerB, b.h2, b.rlogits, b.routerU], [256, 1]);
      push(routerTopKWGSL(256, 8), [b.rlogits, b.routeIdx, b.scales], [1]);
      if (this.debugRoutes) {
        enc0((enc) => {
          enc.copyBufferToBuffer(b.h2, 0, this.dbgH2, li * H * 4, H * 4);
          enc.copyBufferToBuffer(b.routeIdx, 0, this.dbgIdx, li * 8 * 4, 8 * 4);
          enc.copyBufferToBuffer(b.scales, 0, this.dbgW, li * 8 * 4, 8 * 4);
        });
      }

      // shared expert + sigmoid gate. The gated add WRITES moe (assign
      // variant) — no clearBuffer, so the whole layer stays in one pass.
      // gate and up read the same h2: their input RHTs batch like qkv+z.
      tg = "shared";
      if (L.gGU) neGroup(L.gGU); else neBatchIn([L.shGate, L.shUp]);
      push(smul, [L.shGate.y, L.shUp.y], [2]);
      ne(L.shDown);
      push(gemvS4, [L.sharedGateW, b.h2, b.sg, b.sgU || (b.sgU = this.uni([1, H, 1, 0]))], [1, 1]);
      push(sigmoidScaleAddWGSL(H, 256, { assign: true }),
        [b.moe, L.shDown.y, b.sg], [Math.ceil(H / 256)]);

      // routed experts: all 8 slots batched per dispatch, expert indices
      // read from the route buffer inside the kernels
      // 2048-dim routed FWHTs (gate/up input, down output) use the routed
      // split: [dim/C + C, 8] workgroups instead of 8 one-vector workgroups.
      // Bit-identical (same H_R (x) H_C factoring as every other split use);
      // the 512-dim ones stay one-pass — at that size the split's second
      // dispatch costs more than it saves.
      const CE = parC(2048);
      const gd = L.ex.down;
      if (L.exGU) {
        // MERGED gate|up (v3t): one 16-slot chain — slots 0..7 gate, 8..15
        // up (expert te + 256 in the concatenated buffers). Halves the
        // dispatch count of the gate/up stage and doubles GEMV occupancy;
        // per-slot math is bit-identical to the unmerged dispatches.
        const gu = L.exGU;
        const guWave = this.waveIdxB[`${gu.m0}x${gu.n0}`];
        tg = "expert:fwht";
        if (sgOK(2048, 16)) {
          push(fwhtSgWGSL(2048, SG, { mode: 1, routed: true, pair: 256, bcast: true }),
            [b.xslot16, gu.su, b.ones, b.routeIdx, b.h2], [16, 1]);
        } else {
          push(fwhtSplitRowWGSL(2048, CE, { preSign: true, bcast: true,
            routed: true, pair: 256 }),
            [b.xslot16, gu.su, b.h2, b.routeIdx], [2048 / CE, 16]);
          push(fwhtSplitColWGSL(2048, CE, { routed: true }),
            [b.xslot16, b.ones], [CE, 16]);
        }
        tg = "expert:gemv";
        push(expertGemvUnrolledWGSL(this.M.cb, wgFor(2048),
          { ...fusedOpts, pair: 256, sgAdd: SG }),
          [gu.trellis, expTlut, b.xslot16, b.guY, gu.meta, b.routeIdx,
            gu.gamma, guWave], [512 / 16, 16]);
        tg = "expert:fwht";
        if (sgOK(512, 16)) {
          push(fwhtSgWGSL(512, SG, { mode: 2, routed: true, pair: 256, scaleStride: 64 }),
            [b.guY, gu.sv, gu.wsc, b.routeIdx], [16, 1]);
        } else {
          push(fwhtWGSL(512, 256, { routed: 2, scaleStride: 64, pair: 256 }),
            [b.guY, gu.sv, gu.fwhtYU, gu.wsc, b.routeIdx], [16]);
        }
        tg = "expert:misc";
        push(siluMulPairWGSL(8 * 512), [b.guY], [Math.ceil((8 * 512) / 256)]);
        tg = "expert:fwht";
        if (sgOK(512, 8)) {
          push(fwhtSgWGSL(512, SG, { mode: 1, routed: true }),
            [b.guY, gd.su, b.ones, b.routeIdx], [8, 1]);
        } else {
          push(fwhtWGSL(512, 256, { routed: 1 }),
            [b.guY, gd.su, gd.fwhtXU, b.ones, b.routeIdx], [8]);
        }
        tg = "expert:gemv";
        push(fusedDN, [gd.trellis, expTlut, b.guY, b.dY, gd.meta, b.routeIdx,
          ...gext(gd)], [2048 / 16, 8]);
      } else {
      for (const proj of ["gate", "up"]) {
        const g = L.ex[proj];
        const out = proj === "gate" ? b.gY : b.uY;
        tg = "expert:fwht";
        push(fwhtSplitRowWGSL(2048, CE, { preSign: true, bcast: true, routed: true }),
          [b.xslot, g.su, b.h2, b.routeIdx], [2048 / CE, 8]);
        push(fwhtSplitColWGSL(2048, CE, { routed: true }),
          [b.xslot, b.ones], [CE, 8]);
        tg = "expert:gemv";
        push(fusedGU, [g.trellis, expTlut, b.xslot, out, g.meta, b.routeIdx,
          ...gext(g)], [512 / 16, 8]);
        tg = "expert:fwht";
        push(fwhtWGSL(512, 256, { routed: 2, scaleStride: 64 }),
          [out, g.sv, g.fwhtYU, g.wsc, b.routeIdx], [8]);
        if (L.basisR) {
          tg = "expert:basis";
          push(gemvS, [g.basisA, b.h2, b.t0, g.gemvA1U], [256, 1]);
          push(routedCMulWGSL(256, 8, false), [b.t1, g.c, b.routeIdx, L.dmaskB, b.t0], [8]);
          push(denseGemvWGSL("f32", 256, true, true, true),
            [g.basisB, b.t1, out, g.gemvBU, b.routeIdx, L.dmaskB], [512, 8]);
        }
      }
      tg = "expert:misc";
      push(smul, [b.gY, b.uY], [Math.ceil((8 * 512) / 256)]);
      if (L.basisR) {
        // down's basis input is the RAW per-slot activation — capture it
        // before the in-place input FWHT below overwrites gY
        tg = "expert:basis";
        push(denseGemvWGSL("f32", 256, false, true, true),
          [gd.basisA, b.gY, b.t1, gd.gemvAU, b.routeIdx, L.dmaskB], [256, 8]);
        push(routedCMulWGSL(256, 8, true), [b.t1, gd.c, b.routeIdx, L.dmaskB], [8]);
      }
      tg = "expert:fwht";
      push(fwhtWGSL(512, 256, { routed: 1 }), [b.gY, gd.su, gd.fwhtXU, b.ones, b.routeIdx], [8]);
      tg = "expert:gemv";
      push(fusedDN, [gd.trellis, expTlut, b.gY, b.dY, gd.meta, b.routeIdx,
        ...gext(gd)], [2048 / 16, 8]);
      }
      tg = "expert:fwht";
      if (sgOK(2048, 8)) {
        push(fwhtSgWGSL(2048, SG, { mode: 2, routed: true, scaleStride: 64 }),
          [b.dY, gd.sv, gd.wsc, b.routeIdx], [8, 1]);
      } else {
        push(fwhtSplitRowWGSL(2048, CE, { routed: true }), [b.dY], [2048 / CE, 8]);
        push(fwhtSplitColWGSL(2048, CE, { postSign: true, routed: true,
          routedScale: true, scaleStride: 64 }),
          [b.dY, gd.sv, gd.wsc, b.routeIdx], [CE, 8]);
      }
      if (L.basisR) {
        tg = "expert:basis";
        push(denseGemvWGSL("f32", 256, true, true, true),
          [gd.basisB, b.t1, b.dY, gd.gemvBU, b.routeIdx, L.dmaskB], [2048, 8]);
      }
      // routed reduce + residual + NEXT layer's inputLn in one dispatch;
      // the last layer keeps the plain pair (the final norm is on the head
      // side of the prefill slice)
      if (li === this.layers.length - 1) {
        tg = "expert:misc";
        push(moeReduceWGSL(H, 8), [b.moe, b.dY, b.scales], [Math.ceil(H / 256)]);
        tg = "norm+add";
        push(add, [b.x, b.moe], [Math.ceil(H / 256)]);
      } else {
        tg = "norm+add";
        push(addRmsMoeWGSL(H, cfg.rms_norm_eps, 8),
          [b.x, b.moe, b.dY, b.scales, this.layers[li + 1].inputLn, b.h1], [1]);
      }
    }

    // final norm + lm_head + GPU-compacted sampling (same submit).
    // Everything from here on is only needed when the caller wants logits —
    // prefill replays ops.slice(0, headStart) and skips the readback.
    this._headStart = ops.length;
    tg = "head";
    push(rms, [b.x, this.normW, b.hf], [1]);
    let off = 0;
    for (const hc of this.head) {
      const o = off;
      if (hc.int5 && hc.p.tlen % 32 === 0) {
        // fast path writes logitsBuf directly at yOff (meta word 2) — no
        // per-chunk staging copy, no compute-pass break between chunks
        push(int5GemvFastWGSL({ group: hc.p.group, sgAdd: SG }),
          [hc.p.qp, hc.p.gscale, hc.p.x, this.logitsBuf,
            this.uni([hc.p.nrows, hc.p.tlen, o, 0])], [hc.p.nrows]);
      } else {
        if (hc.int5) int5(hc.p); else ne(hc.p);
        enc0((enc) => enc.copyBufferToBuffer(hc.p.y, 0, this.logitsBuf, o * 4, hc.rows * 4));
      }
      off += hc.rows;
    }
    // max -> threshold compaction -> small staging readback
    tg = "sample";
    enc0((enc) => enc.clearBuffer(this.ctrBuf));
    push(maxReduceWGSL(1024), [this.logitsBuf, this.partialMax, this.maxAU], [this.nPartial]);
    push(maxFinalWGSL(), [this.partialMax, this.mxBuf, this.maxBU], [1]);
    push(logitCompactWGSL(this.sampleCap),
      [this.logitsBuf, this.mxBuf, this.ctrBuf, this.topIdx, this.topVal, this.compactU],
      [Math.ceil(this.vocab / 256)]);
    enc0((enc) => {
      enc.copyBufferToBuffer(this.ctrBuf, 0, this.sampleStaging, 0, 4);
      enc.copyBufferToBuffer(this.topIdx, 0, this.sampleStaging, 4, this.sampleCap * 4);
      enc.copyBufferToBuffer(this.topVal, 0, this.sampleStaging, 4 + this.sampleCap * 4, this.sampleCap * 4);
    });
    return ops;
  }

  // ---------------------------------------------------------- profiling
  // Times the recorded op list stage by stage. Chrome quantizes
  // timestamp-query to ~65 us and wall-clock around one submit swings 2x, so
  // each measurement packs `inner` replays of a (sub)list into ONE submit and
  // takes the min over `trials` — the same methodology as bench_expert_ab.
  // Values are GPU-only ms per token-equivalent. Replaying a stage in
  // isolation corrupts activations (fine: timing only, the shapes and
  // buffers are the real ones); call from the console via window.__engine.
  async profileStages({ inner = 30, trials = 5 } = {}) {
    if (!this._ops) this._ops = this._record();
    const timeList = async (list, n) => {
      const run = async () => {
        const enc = this.device.createCommandEncoder();
        let ps = null;
        for (let i = 0; i < n; i++) {
          for (const op of list) {
            if (op.enc) { if (ps) { ps.end(); ps = null; } op.enc(enc); }
            else {
              if (!ps) ps = enc.beginComputePass();
              ps.setPipeline(op.p);
              ps.setBindGroup(0, op.bg);
              ps.dispatchWorkgroups(op.d[0], op.d[1] || 1, op.d[2] || 1);
            }
          }
        }
        if (ps) ps.end();
        this.device.queue.submit([enc.finish()]);
        await this.device.queue.onSubmittedWorkDone();
      };
      await run(); // warm (pipelines already compiled, caches hot)
      let best = Infinity;
      for (let t = 0; t < trials; t++) {
        const t0 = performance.now();
        await run();
        best = Math.min(best, (performance.now() - t0) / n);
      }
      return best;
    };
    const groups = new Map();
    for (const op of this._ops) {
      const t = op.t || "untagged";
      if (!groups.has(t)) groups.set(t, []);
      groups.get(t).push(op);
    }
    const total = await timeList(this._ops, inner);
    const stages = {};
    for (const [t, list] of groups) {
      stages[t] = { ms: await timeList(list, inner), n: list.length };
    }
    let sum = 0;
    for (const t of Object.keys(stages)) sum += stages[t].ms;
    const fmt = Object.entries(stages).sort((a, z) => z[1].ms - a[1].ms)
      .map(([t, v]) => `${t.padEnd(24)} ${v.ms.toFixed(3).padStart(8)} ms  ${(100 * v.ms / total).toFixed(1).padStart(5)}%  (${v.n} ops)`)
      .join("\n");
    console.log(`TOTAL ${total.toFixed(3)} ms/token  (stage sum ${sum.toFixed(3)} ms)\n${fmt}`);
    return { total, sum, stages };
  }

  // ------------------------------------------------------------- one token
  // One submit, one readback. Per-token CPU work: embedding gather, rope
  // table, three uniform writes, op-list replay (cached bind groups).
  // wantLogits=false (prefill, all but the last prompt token) skips the
  // lm_head ops AND the readback — successive prefill submits pipeline on
  // the GPU with no per-token sync.
  _encodeListInto(enc, list) {
    let ps = null;
    for (const op of list) {
      if (op.enc) {
        if (ps) { ps.end(); ps = null; }
        op.enc(enc);
      } else {
        if (!ps) ps = enc.beginComputePass();
        ps.setPipeline(op.p);
        ps.setBindGroup(0, op.bg);
        ps.dispatchWorkgroups(op.d[0], op.d[1] || 1, op.d[2] || 1);
      }
    }
    if (ps) ps.end();
  }

  _encodeList(list) {
    const enc = this.device.createCommandEncoder();
    this._encodeListInto(enc, list);
    return enc.finish();
  }

  _ensureOps() {
    // self-healing: a late ADD_ONLY flip (the in-page ?additive toggle, or a
    // caller using the old post-load assignment) invalidates the recorded
    // op list instead of being silently ignored
    if (this._ops && this._opsAddOnly !== !!this.ADD_ONLY) {
      this._ops = null;
      this._cbNext = null;
    }
    if (!this._ops) {
      if (this.debugRoutes) {
        this.dbgH2 = this.gbuf(this.layers.length * this.H * 4);
        this.dbgIdx = this.gbuf(this.layers.length * 8 * 4);
        this.dbgW = this.gbuf(this.layers.length * 8 * 4);
      }
      this._ops = this._record();
      this._opsAddOnly = !!this.ADD_ONLY;
    }
  }

  _prefillBuffers(batchSize) {
    if (this._prefillStage?.batchSize >= batchSize) return this._prefillStage;
    this._prefillStage?.x.destroy();
    this._prefillStage?.cos.destroy();
    this._prefillStage?.sin.destroy();
    this._prefillStage?.attn.destroy();
    const usage = GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST;
    this._prefillStage = {
      batchSize,
      x: this.gbuf(batchSize * this.H * 4, usage),
      cos: this.gbuf(batchSize * 64 * 4, usage),
      sin: this.gbuf(batchSize * 64 * 4, usage),
      attn: this.gbuf(batchSize * 16, usage),
    };
    return this._prefillStage;
  }

  // Record several causally-dependent token steps into one command buffer.
  // The actual model operations and their order are unchanged; only the
  // number of queue submissions falls from one per token to one per batch.
  async prefill(promptIds, start, end, {
    batchSize = this.prefillBatchSize, onPrefill = () => {}, shouldStop = () => false,
  } = {}) {
    if (start >= end) return;
    this._ensureOps();
    const { device, b } = this;
    const ops = this._ops.slice(0, this._headStart);
    const requestedBatch = Number.isFinite(batchSize) ? Math.floor(batchSize) : this.prefillBatchSize;
    const nBatch = Math.max(1, Math.min(32, requestedBatch));
    const stage = this._prefillBuffers(nBatch);
    let submitted = 0;
    for (let base = start; base < end; base += nBatch) {
      if (shouldStop()) throw new DOMException("client cancelled generation", "AbortError");
      const count = Math.min(nBatch, end - base);
      const xs = new Float32Array(count * this.H);
      const cosines = new Float32Array(count * 64);
      const sines = new Float32Array(count * 64);
      const attn = new Uint32Array(count * 4);
      for (let j = 0; j < count; j++) {
        xs.set(this.embedRow(promptIds[base + j]), j * this.H);
        const rope = this.ropeAt(base + j);
        cosines.set(rope.cos, j * 64);
        sines.set(rope.sin, j * 64);
        attn[j * 4] = base + j + 1;
      }
      device.queue.writeBuffer(stage.x, 0, xs);
      device.queue.writeBuffer(stage.cos, 0, cosines);
      device.queue.writeBuffer(stage.sin, 0, sines);
      device.queue.writeBuffer(stage.attn, 0, attn);
      const enc = device.createCommandEncoder();
      for (let j = 0; j < count; j++) {
        enc.copyBufferToBuffer(stage.x, j * this.H * 4, b.x, 0, this.H * 4);
        enc.copyBufferToBuffer(stage.cos, j * 64 * 4, b.cos, 0, 64 * 4);
        enc.copyBufferToBuffer(stage.sin, j * 64 * 4, b.sin, 0, 64 * 4);
        enc.copyBufferToBuffer(stage.attn, j * 16, b.attnU, 0, 16);
        this._encodeListInto(enc, ops);
      }
      device.queue.submit([enc.finish()]);
      submitted++;
      for (let j = 0; j < count; j++) onPrefill(base + j + 1, promptIds.length);
      // Bound queued work so an interrupted long Pi prompt does not leave the
      // GPU occupied for minutes after the HTTP client has disconnected.
      if (submitted % this.prefillBackpressureBatches === 0) {
        await device.queue.onSubmittedWorkDone();
        if (shouldStop()) throw new DOMException("client cancelled generation", "AbortError");
      } else {
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    }
  }

  async step(tokenId, pos, wantLogits = true) {
    const { device, b } = this;
    this._pos = pos;
    this._ensureOps();
    device.queue.writeBuffer(b.x, 0, this.embedRow(tokenId));
    const { cos, sin } = this.ropeAt(pos);
    device.queue.writeBuffer(b.cos, 0, cos);
    device.queue.writeBuffer(b.sin, 0, sin);
    device.queue.writeBuffer(b.attnU, 0, new Uint32Array([pos + 1, 0, 0, 0]));
    if (wantLogits) {
      this.device.queue.writeBuffer(this.compactU, 4, new Float32Array([this._thr]));
    }
    // The op list is POSITION-INDEPENDENT (everything per-token arrives via
    // the uniform/buffer writes above — the last pos-dependent encoder op
    // died with the appendKV kernel), so a decode step can reuse a command
    // buffer that was encoded while the GPU was busy with the PREVIOUS
    // token. That moves ~1.5 ms of JS encode off the critical path: the old
    // sequence was readback -> sample -> encode (GPU idle) -> submit.
    let cb;
    if (wantLogits && this._cbNext) {
      cb = this._cbNext;
      this._cbNext = null;
    } else {
      cb = this._encodeList(wantLogits ? this._ops : this._ops.slice(0, this._headStart));
    }
    device.queue.submit([cb]);
    if (!wantLogits) return null;
    // pre-encode the next decode step's command buffer while the GPU runs
    this._cbNext = this._encodeList(this._ops);
    await this.sampleStaging.mapAsync(GPUMapMode.READ);
    const buf = this.sampleStaging.getMappedRange().slice(0);
    this.sampleStaging.unmap();
    const cap = this.sampleCap;
    return {
      count: new Uint32Array(buf, 0, 1)[0],
      idx: new Uint32Array(buf, 4, cap),
      val: new Float32Array(buf, 4 + cap * 4, cap),
    };
  }

  // Full logits readback (debug / compaction-overflow fallback).
  readLogits() {
    return this.readBack(this.logitsBuf, this.vocab * 4);
  }

  // Sample from the GPU-compacted (idx, logit) set. The compaction keeps
  // every logit >= max - thr with thr = 12*temperature — the same tail
  // prune sample() applies — so the distribution is identical to sampling
  // the full vector. Deterministic (logit desc, idx asc) order; greedy is
  // exact argmax. Overflow (count > cap) falls back to the full readback.
  async samplePacked(pk, { temperature = 0.7, topP = 0.9 } = {}) {
    if (pk.count === 0 || pk.count > this.sampleCap) {
      // count 0 should be impossible (max is always kept) — treat it like
      // overflow and use the full vector rather than crash.
      return this.sample(await this.readLogits(), { temperature, topP });
    }
    const n = pk.count;
    const ord = Array.from({ length: n }, (_, i) => i)
      .sort((a, b2) => (pk.val[b2] - pk.val[a]) || (pk.idx[a] - pk.idx[b2]));
    if (temperature <= 0 || n === 1) return pk.idx[ord[0]];
    const mx = pk.val[ord[0]];
    const keep = ord.filter((i) => pk.val[i] > mx - 12 * temperature);  // sample()'s strict prune
    let denom = 0;
    const ps = keep.map((i) => {
      const p = Math.exp((pk.val[i] - mx) / temperature);
      denom += p;
      return p;
    });
    let cum = 0, cut = ps.length;
    for (let i = 0; i < ps.length; i++) {
      cum += ps[i] / denom;
      if (cum >= topP) { cut = i + 1; break; }
    }
    let r = Math.random() * cum;
    for (let i = 0; i < cut; i++) {
      r -= ps[i] / denom;
      if (r <= 0) return pk.idx[keep[i]];
    }
    return pk.idx[keep[0]];
  }

  // Cross-check the GPU router against the CPU f64 reference for the LAST
  // stepped token. Set engine.debugRoutes = true BEFORE the first step.
  // Returns [] on parity; each mismatch carries layer/slot/GPU/CPU values.
  async checkRoutes() {
    const nL = this.layers.length;
    const h2 = await this.readBack(this.dbgH2, nL * this.H * 4);
    const idx = new Uint32Array((await this.readBack(this.dbgIdx, nL * 8 * 4)).buffer);
    const w = await this.readBack(this.dbgW, nL * 8 * 4);
    const bad = [];
    for (let li = 0; li < nL; li++) {
      const ref = routeTopK(this.layers[li].routerW,
        h2.subarray(li * this.H, (li + 1) * this.H), this.H);
      for (let k = 0; k < 8; k++) {
        const gi = idx[li * 8 + k], gw = w[li * 8 + k];
        if (gi !== ref[k].e || Math.abs(gw - ref[k].w) > 2e-4) {
          bad.push({ li, k, gpu: [gi, gw], cpu: [ref[k].e, ref[k].w] });
        }
      }
    }
    return bad;
  }

  resetState() {
    const enc = this.device.createCommandEncoder();
    for (const L of this.layers) {
      if (L.kind === "linear_attention") {
        enc.clearBuffer(L.convState);
        enc.clearBuffer(L.S);
      }
    }
    this.device.queue.submit([enc.finish()]);
  }

  _destroyPrefixCache() {
    if (!this._prefixCache) return;
    for (const layer of this._prefixCache.layers) {
      for (const buffer of Object.values(layer)) buffer?.destroy?.();
    }
    this._prefixCache = null;
  }

  _prefixMatches(promptIds, prefixLength) {
    const cache = this._prefixCache;
    if (!cache || cache.tokens.length !== prefixLength) return false;
    for (let i = 0; i < prefixLength; i++) {
      if (cache.tokens[i] !== promptIds[i]) return false;
    }
    return true;
  }

  _capturePrefix(promptIds, prefixLength) {
    this._destroyPrefixCache();
    if (prefixLength <= 0) return;
    const enc = this.device.createCommandEncoder();
    const layers = [];
    const kvBytes = prefixLength * this.cfg.num_key_value_heads * this.cfg.head_dim * 4;
    for (const L of this.layers) {
      if (L.kind === "linear_attention") {
        const convState = this.gbuf(L.convState.size);
        const S = this.gbuf(L.S.size);
        enc.copyBufferToBuffer(L.convState, 0, convState, 0, L.convState.size);
        enc.copyBufferToBuffer(L.S, 0, S, 0, L.S.size);
        layers.push({ convState, S });
      } else {
        const kCache = this.gbuf(kvBytes);
        const vCache = this.gbuf(kvBytes);
        enc.copyBufferToBuffer(L.kCache, 0, kCache, 0, kvBytes);
        enc.copyBufferToBuffer(L.vCache, 0, vCache, 0, kvBytes);
        layers.push({ kCache, vCache });
      }
    }
    this.device.queue.submit([enc.finish()]);
    this._prefixCache = { tokens: Uint32Array.from(promptIds.slice(0, prefixLength)), layers };
  }

  _restorePrefix() {
    const enc = this.device.createCommandEncoder();
    for (let i = 0; i < this.layers.length; i++) {
      const L = this.layers[i], cached = this._prefixCache.layers[i];
      if (L.kind === "linear_attention") {
        enc.copyBufferToBuffer(cached.convState, 0, L.convState, 0, L.convState.size);
        enc.copyBufferToBuffer(cached.S, 0, L.S, 0, L.S.size);
      } else {
        enc.copyBufferToBuffer(cached.kCache, 0, L.kCache, 0, cached.kCache.size);
        enc.copyBufferToBuffer(cached.vCache, 0, L.vCache, 0, cached.vCache.size);
      }
    }
    this.device.queue.submit([enc.finish()]);
  }

  sample(logits, { temperature = 0.7, topP = 0.9 } = {}) {
    if (temperature <= 0) {
      let best = 0;
      for (let i = 1; i < logits.length; i++) if (logits[i] > logits[best]) best = i;
      return best;
    }
    let mx = -Infinity;
    for (const v of logits) mx = Math.max(mx, v);
    const idx = [];
    for (let i = 0; i < logits.length; i++) {
      if (logits[i] > mx - 12 * temperature) idx.push(i);   // prune tail
    }
    idx.sort((a, b) => logits[b] - logits[a]);
    let denom = 0;
    const ps = idx.map((i) => {
      const p = Math.exp((logits[i] - mx) / temperature);
      denom += p;
      return p;
    });
    let cum = 0, cut = ps.length;
    for (let i = 0; i < ps.length; i++) {
      cum += ps[i] / denom;
      if (cum >= topP) { cut = i + 1; break; }
    }
    let r = Math.random() * cum;
    for (let i = 0; i < cut; i++) {
      r -= ps[i] / denom;
      if (r <= 0) return idx[i];
    }
    return idx[0];
  }

  chatPrompt(userText, systemText = null) {
    let s = "";
    if (systemText) s += `<|im_start|>system\n${systemText}<|im_end|>\n`;
    s += `<|im_start|>user\n${userText}<|im_end|>\n<|im_start|>assistant\n`;
    return this.tok.encode(s);
  }

  async generate(promptIds, { maxTokens = 128, temperature = 0.7, topP = 0.9,
    onToken = () => {}, onPrefill = () => {}, shouldStop = () => false,
    prefixLength = 0, usePrefixCache = true, prefillBatchSize = this.prefillBatchSize } = {}) {
    const prefillStarted = performance.now();
    this.resetState();
    this._thr = 12 * Math.max(temperature, 0);   // compaction threshold = sampler prune
    const eosIds = new Set([this.tok.special.get("<|im_end|>"),
      this.tok.special.get("<|endoftext|>")]);
    const cacheLength = Math.max(0, Math.min(prefixLength, promptIds.length - 1));
    const cacheHit = usePrefixCache && this._prefixMatches(promptIds, cacheLength);
    let start = 0;
    if (cacheHit) {
      this._restorePrefix();
      start = cacheLength;
      onPrefill(start, promptIds.length);
    } else if (usePrefixCache && cacheLength > 0) {
      await this.prefill(promptIds, 0, cacheLength,
        { batchSize: prefillBatchSize, onPrefill, shouldStop });
      this._capturePrefix(promptIds, cacheLength);
      start = cacheLength;
    }
    const last = promptIds.length - 1;
    await this.prefill(promptIds, start, last,
      { batchSize: prefillBatchSize, onPrefill, shouldStop });
    if (shouldStop()) throw new DOMException("client cancelled generation", "AbortError");
    let pk = await this.step(promptIds[last], last, true);
    onPrefill(promptIds.length, promptIds.length);
    const prefillMs = performance.now() - prefillStarted;
    const outIds = [];
    let pos = promptIds.length;
    for (let n = 0; n < maxTokens; n++) {
      const id = await this.samplePacked(pk, { temperature, topP });
      if (eosIds.has(id)) break;
      outIds.push(id);
      onToken(this.tok.decode([id]), id);
      if (pos >= this.maxCtx - 1) break;
      pk = await this.step(id, pos);
      pos++;
    }
    return {
      ids: outIds, text: this.tok.decode(outIds), prefillMs,
      prefillBatchSize: Math.max(1, Math.min(32,
        Number.isFinite(prefillBatchSize) ? Math.floor(prefillBatchSize) : this.prefillBatchSize)),
      prefixCacheHit: cacheHit, cachedPromptTokens: cacheHit ? cacheLength : 0,
    };
  }
}

// CPU router (per token): full softmax over experts, top-8, renormalized.
export function routeTopK(routerW, h2, H, nExperts = 256, topK = 8) {
  const logits = new Float64Array(nExperts);
  for (let e = 0; e < nExperts; e++) {
    let acc = 0;
    const base = e * H;
    for (let i = 0; i < H; i++) acc += routerW[base + i] * h2[i];
    logits[e] = acc;
  }
  let mx = -Infinity;
  for (const v of logits) mx = Math.max(mx, v);
  const probs = new Float64Array(nExperts);
  let denom = 0;
  for (let e = 0; e < nExperts; e++) { probs[e] = Math.exp(logits[e] - mx); denom += probs[e]; }
  const idx = Array.from(probs.keys()).sort((a, b) => probs[b] - probs[a]).slice(0, topK);
  let s = 0;
  for (const e of idx) s += probs[e];
  return idx.map((e) => ({ e, w: probs[e] / s }));
}
