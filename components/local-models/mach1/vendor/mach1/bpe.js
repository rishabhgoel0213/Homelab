// Byte-level BPE tokenizer for Mach-1-Ternary-35B (Qwen2-family
// tokenizer.json: NFC → regex split → ByteLevel → BPE merges), plus special
// added-token handling. Validated against transformers' AutoTokenizer by
// test/test_bpe.mjs.

// GPT-2 byte<->unicode table (ByteLevel encoding).
function byteToUnicode() {
  const bs = [];
  for (let i = 0x21; i <= 0x7e; i++) bs.push(i);
  for (let i = 0xa1; i <= 0xac; i++) bs.push(i);
  for (let i = 0xae; i <= 0xff; i++) bs.push(i);
  const cs = bs.slice();
  let n = 0;
  for (let b = 0; b < 256; b++) {
    if (!bs.includes(b)) { bs.push(b); cs.push(256 + n); n++; }
  }
  const b2u = new Array(256), u2b = new Map();
  for (let i = 0; i < bs.length; i++) {
    b2u[bs[i]] = String.fromCharCode(cs[i]);
    u2b.set(String.fromCharCode(cs[i]), bs[i]);
  }
  return { b2u, u2b };
}

// The tokenizer.json split regex uses an inline (?i:…) group — unsupported
// in JS RegExp — so the contraction alternation is expanded case-explicitly.
const SPLIT = new RegExp(
  "'(?:[sS]|[tT]|[rR][eE]|[vV][eE]|[mM]|[lL][lL]|[dD])" +
  "|[^\\r\\n\\p{L}\\p{N}]?[\\p{L}\\p{M}]+" +
  "|\\p{N}" +
  "| ?[^\\s\\p{L}\\p{M}\\p{N}]+[\\r\\n]*" +
  "|\\s*[\\r\\n]+" +
  "|\\s+(?!\\S)" +
  "|\\s+",
  "gu");

export class Tokenizer {
  constructor(tokJson) {
    this.vocab = new Map(Object.entries(tokJson.model.vocab));
    this.idToTok = new Array(this.vocab.size);
    for (const [tok, id] of this.vocab) this.idToTok[id] = tok;
    this.ranks = new Map();
    tokJson.model.merges.forEach((m, i) => {
      this.ranks.set(Array.isArray(m) ? `${m[0]} ${m[1]}` : m, i);
    });
    this.special = new Map();
    for (const a of tokJson.added_tokens || []) {
      this.special.set(a.content, a.id);
      if (a.id >= this.idToTok.length || !this.idToTok[a.id]) this.idToTok[a.id] = a.content;
    }
    const specials = [...this.special.keys()]
      .sort((a, b) => b.length - a.length)
      .map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    this.specialRe = specials.length ? new RegExp(`(${specials.join("|")})`, "g") : null;
    const { b2u, u2b } = byteToUnicode();
    this.b2u = b2u;
    this.u2b = u2b;
    this.enc = new TextEncoder();
    this.dec = new TextDecoder();
    this.cache = new Map();
  }

  bpeWord(chars) {
    const cached = this.cache.get(chars);
    if (cached) return cached;
    let parts = [...chars];
    while (parts.length > 1) {
      let best = -1, bestRank = Infinity;
      for (let i = 0; i < parts.length - 1; i++) {
        const r = this.ranks.get(`${parts[i]} ${parts[i + 1]}`);
        if (r !== undefined && r < bestRank) { bestRank = r; best = i; }
      }
      if (best < 0) break;
      parts = [...parts.slice(0, best), parts[best] + parts[best + 1], parts.slice(best + 2)].flat();
    }
    const ids = parts.map((p) => {
      const id = this.vocab.get(p);
      if (id === undefined) throw new Error(`token not in vocab: ${JSON.stringify(p)}`);
      return id;
    });
    if (this.cache.size < 50000) this.cache.set(chars, ids);
    return ids;
  }

  encodeOrdinary(text) {
    const ids = [];
    const norm = text.normalize("NFC");
    for (const piece of norm.match(SPLIT) || []) {
      const bytes = this.enc.encode(piece);
      let chars = "";
      for (const b of bytes) chars += this.b2u[b];
      ids.push(...this.bpeWord(chars));
    }
    return ids;
  }

  // Splits on special tokens first (chat-template markup), BPE in between.
  encode(text) {
    if (!this.specialRe) return this.encodeOrdinary(text);
    const ids = [];
    let last = 0;
    for (const m of text.matchAll(this.specialRe)) {
      if (m.index > last) ids.push(...this.encodeOrdinary(text.slice(last, m.index)));
      ids.push(this.special.get(m[1]));
      last = m.index + m[1].length;
    }
    if (last < text.length) ids.push(...this.encodeOrdinary(text.slice(last)));
    return ids;
  }

  decode(ids) {
    const bytes = [];
    let out = "";
    const flush = () => {
      if (bytes.length) {
        out += this.dec.decode(new Uint8Array(bytes));
        bytes.length = 0;
      }
    };
    for (const id of ids) {
      const tok = this.idToTok[id];
      if (tok === undefined) continue;
      if (this.special.has(tok) && this.special.get(tok) === id) {
        flush();
        out += tok;
        continue;
      }
      for (const ch of tok) bytes.push(this.u2b.get(ch));
    }
    flush();
    return out;
  }
}
