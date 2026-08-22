// Minimal safetensors reader with HTTP Range support, for pulling single
// tensors (one expert, the codebook, one NE matrix) out of the multi-GB
// shards on the HuggingFace Hub without downloading whole files.
//
// Pack v3: NE/embed shards ship every non-code-stream tensor (gscale, lut,
// mn, mx, …) inside a zstd sidecar — tensor `__zsc__` + metadata["zsc"] =
// {algo, raw_len, entries: [[key, numpyDtypeStr, shape, byteOff, nbytes]…]}.
// decode.py::_read_safetensors_np expands it transparently; so does this
// loader (vendored fzstd, MIT — no CDN, the Space is self-contained).
import { f16ToF32 } from "./reference.js";
import { decompress as zstdDecompress } from "./vendor/fzstd.js";

function bytesToData(dtypeTag, bytes) {
  // safetensors dtype tokens and numpy dtype strings, one converter table.
  switch (dtypeTag) {
    case "F32": case "<f4": return new Float32Array(bytes);
    case "F16": case "<f2": {
      const u = new Uint16Array(bytes);
      const data = new Float32Array(u.length);
      for (let i = 0; i < u.length; i++) data[i] = f16ToF32(u[i]);
      return data;
    }
    case "BF16": {
      const u = new Uint16Array(bytes);
      const out = new Uint32Array(u.length);
      for (let i = 0; i < u.length; i++) out[i] = u[i] << 16;
      return new Float32Array(out.buffer);
    }
    case "F64": case "<f8": return new Float64Array(bytes);
    case "I16": case "<i2": case "U16": case "<u2": return new Uint16Array(bytes);
    case "I8": case "|i1": return new Int8Array(bytes);
    case "U8": case "|u1": return new Uint8Array(bytes);
    case "I32": case "<i4": return new Int32Array(bytes);
    case "I64": case "<i8": return new BigInt64Array(bytes);
    default: throw new Error(`unhandled dtype ${dtypeTag}`);
  }
}

// Core reader over any byte source. rangeRead(start, end) -> ArrayBuffer
// of bytes [start, end) of the FILE.
async function makeSafetensors(rangeRead, urlForErrors = "") {
  const head = new DataView(await rangeRead(0, 8));
  const headerLen = Number(head.getBigUint64(0, true));
  if (!(headerLen > 0 && headerLen < 100 * 1024 * 1024)) {
    throw new Error(`implausible safetensors header length ${headerLen}`);
  }
  const headerBytes = await rangeRead(8, 8 + headerLen);
  const header = JSON.parse(new TextDecoder().decode(headerBytes));
  const dataStart = 8 + headerLen;
  const meta = header.__metadata__ || {};

  // pack v3 sidecar: parse the manifest now, decompress lazily exactly once
  const zsc = meta.zsc ? JSON.parse(meta.zsc) : null;
  const zscEntries = new Map();
  if (zsc) {
    if (zsc.algo !== "zstd") throw new Error(`unknown sidecar algo ${zsc.algo}`);
    for (const [key, dt, shape, off, nb] of zsc.entries) {
      zscEntries.set(key, { dt, shape, off, nb });
    }
  }
  let zscRawPromise = null;
  function zscRaw() {
    if (!zscRawPromise) {
      zscRawPromise = (async () => {
        const entry = header.__zsc__;
        if (!entry) throw new Error(`metadata has zsc but no __zsc__ tensor`);
        const [a, b] = entry.data_offsets;
        const comp = new Uint8Array(await rangeRead(dataStart + a, dataStart + b));
        const raw = zstdDecompress(comp);
        if (raw.length !== zsc.raw_len) {
          throw new Error(`sidecar decompressed to ${raw.length}, expected ${zsc.raw_len}`);
        }
        return raw;
      })();
    }
    return zscRawPromise;
  }

  async function fetchRaw(name) {
    const entry = header[name];
    if (!entry) throw new Error(`tensor ${name} not in ${urlForErrors}`);
    const [a, b] = entry.data_offsets;
    const bytes = await rangeRead(dataStart + a, dataStart + b);
    return { entry, bytes };
  }

  // Returns { dtype, shape, data } with float types converted to Float32Array
  // and integer code streams kept as raw bit views. Sidecar tensors are
  // sliced out of the decompressed blob transparently.
  async function fetchTensor(name) {
    const side = zscEntries.get(name);
    if (side) {
      const raw = await zscRaw();
      // copy: typed-array views need aligned offsets, the blob is packed
      const bytes = raw.slice(side.off, side.off + side.nb).buffer;
      return { dtype: side.dt, shape: side.shape, data: bytesToData(side.dt, bytes) };
    }
    const { entry, bytes } = await fetchRaw(name);
    return { dtype: entry.dtype, shape: entry.shape, data: bytesToData(entry.dtype, bytes) };
  }

  const names = Object.keys(header).filter((k) => k !== "__metadata__" && k !== "__zsc__");
  for (const k of zscEntries.keys()) names.push(k);
  const has = (name) => !!header[name] || zscEntries.has(name);
  return { header, meta, fetchTensor, names, has };
}

export async function openSafetensors(url, { token } = {}) {
  async function rangeRead(start, end) {
    const headers = { Range: `bytes=${start}-${end - 1}` };
    if (token) headers.Authorization = `Bearer ${token}`;
    const r = await fetch(url, { headers });
    if (!r.ok && r.status !== 206) {
      throw new Error(`fetch ${url.split("?")[0]}: HTTP ${r.status}`);
    }
    const body = await r.arrayBuffer();
    if (r.status === 206) return body;
    return body.slice(start, end);        // server ignored Range: slice locally
  }
  return makeSafetensors(rangeRead, url.split("?")[0]);
}

// In-memory variant (Node tests, preloaded files). buf: ArrayBuffer|Uint8Array.
export async function openSafetensorsBuffer(buf, label = "(buffer)") {
  const u8 = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  async function rangeRead(start, end) {
    // NOTE: not u8.slice(...).buffer — Node's Buffer overrides slice() with
    // subarray semantics, whose .buffer is the whole allocation pool.
    return u8.buffer.slice(u8.byteOffset + start, u8.byteOffset + end);
  }
  return makeSafetensors(rangeRead, label);
}

export function hubUrl(repo, file, revision = "main") {
  return `https://huggingface.co/${repo}/resolve/${revision}/${file}`;
}
