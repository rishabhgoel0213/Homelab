import { createWriteStream } from "node:fs";
import { mkdir, rename, stat, writeFile } from "node:fs/promises";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import path from "node:path";
import process from "node:process";

const repo = "SyzygyResearch/Mach-1-Additive-35B";
const revision = "9d3ee31c56cd51fbc21f2777cb18e7993cdbec74";
const outputRoot = path.resolve(process.argv[2] ?? "models");
const concurrency = Math.max(1, Number(process.env.MACH1_DOWNLOAD_JOBS ?? 4));
const runtimeFiles = [
  "config.json",
  "tokenizer.json",
  "extras.safetensors",
  "packed/ne/embed_packed.safetensors",
  "packed/experts/codebook.safetensors",
  "packed/ne/tlut.safetensors",
  ...Array.from({ length: 40 }, (_, index) => `packed/ne/L${String(index).padStart(2, "0")}.safetensors`),
  ...Array.from({ length: 40 }, (_, index) => `packed/experts/L${String(index).padStart(2, "0")}.safetensors`),
  ...Array.from({ length: 8 }, (_, index) => `packed/head/head_c${index}of8.safetensors`),
];

function human(bytes) {
  return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
}

async function fileSize(filename) {
  try { return (await stat(filename)).size; } catch { return 0; }
}

console.log(`[metadata] ${repo}@${revision}`);
const metadataResponse = await fetch(`https://huggingface.co/api/models/${repo}/revision/${revision}?blobs=true`);
if (!metadataResponse.ok) throw new Error(`metadata HTTP ${metadataResponse.status}`);
const metadata = await metadataResponse.json();
if (metadata.sha !== revision) throw new Error(`revision mismatch: expected ${revision}, got ${metadata.sha}`);
const blobs = new Map(metadata.siblings.map((entry) => [entry.rfilename, entry]));
const missingMetadata = runtimeFiles.filter((filename) => !blobs.has(filename));
if (missingMetadata.length) throw new Error(`metadata is missing: ${missingMetadata.join(", ")}`);

const expectedBytes = runtimeFiles.reduce((sum, filename) => sum + blobs.get(filename).size, 0);
await mkdir(outputRoot, { recursive: true });
let completedBytes = 0;
for (const filename of runtimeFiles) {
  const finalPath = path.join(outputRoot, filename);
  const partialPath = `${finalPath}.part`;
  const expected = blobs.get(filename).size;
  const finalSize = await fileSize(finalPath);
  if (finalSize === expected) completedBytes += expected;
  else completedBytes += Math.min(await fileSize(partialPath), expected);
}
const started = Date.now();
const timer = setInterval(() => {
  const elapsed = Math.max(1, (Date.now() - started) / 1000);
  const speed = completedBytes / elapsed / 1024 ** 2;
  console.log(`[progress] ${human(completedBytes)} / ${human(expectedBytes)} (${(100 * completedBytes / expectedBytes).toFixed(1)}%) ${speed.toFixed(1)} MiB/s`);
}, 10_000);

async function download(filename) {
  const blob = blobs.get(filename);
  const expected = blob.size;
  const finalPath = path.join(outputRoot, filename);
  const partialPath = `${finalPath}.part`;
  await mkdir(path.dirname(finalPath), { recursive: true });
  const finalSize = await fileSize(finalPath);
  if (finalSize === expected) {
    console.log(`[cached] ${filename}`);
    return;
  }
  if (finalSize) throw new Error(`${filename}: existing final file has ${finalSize} bytes, expected ${expected}`);
  let offset = await fileSize(partialPath);
  if (offset > expected) throw new Error(`${filename}.part is larger than expected`);
  const headers = offset ? { Range: `bytes=${offset}-` } : {};
  const response = await fetch(`https://huggingface.co/${repo}/resolve/${revision}/${filename}`, { headers });
  if (!response.ok) throw new Error(`${filename}: HTTP ${response.status}`);
  const append = offset > 0 && response.status === 206;
  if (!append) offset = 0;
  let received = offset;
  const meter = new TransformStream({
    transform(chunk, controller) {
      received += chunk.byteLength;
      completedBytes += chunk.byteLength;
      controller.enqueue(chunk);
    },
  });
  await pipeline(
    Readable.fromWeb(response.body.pipeThrough(meter)),
    createWriteStream(partialPath, { flags: append ? "a" : "w" }),
  );
  const actual = await fileSize(partialPath);
  if (actual !== expected) throw new Error(`${filename}: downloaded ${actual} bytes, expected ${expected}`);
  await rename(partialPath, finalPath);
  console.log(`[done] ${filename} (${human(expected)})`);
}

let cursor = 0;
async function worker() {
  while (cursor < runtimeFiles.length) {
    const index = cursor++;
    await download(runtimeFiles[index]);
  }
}

try {
  await Promise.all(Array.from({ length: concurrency }, () => worker()));
} finally {
  clearInterval(timer);
}

const manifest = {
  repo,
  revision,
  downloaded_at: new Date().toISOString(),
  bytes: expectedBytes,
  files: runtimeFiles.map((filename) => ({
    path: filename,
    size: blobs.get(filename).size,
    sha256: blobs.get(filename).lfs?.sha256 ?? null,
  })),
};
await writeFile(path.join(outputRoot, ".mach1-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`[complete] ${runtimeFiles.length} files, ${human(expectedBytes)}, revision ${revision}`);
