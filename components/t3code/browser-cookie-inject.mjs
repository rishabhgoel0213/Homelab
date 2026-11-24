import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function validatePayload(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("Expected JSON object on stdin");
  }
  if (typeof payload.profileDir !== "string" || !payload.profileDir) {
    throw new Error("Missing profileDir");
  }
  if (typeof payload.executablePath !== "string" || !payload.executablePath) {
    throw new Error("Missing executablePath");
  }
  if (typeof payload.playwrightPath !== "string" || !payload.playwrightPath) {
    throw new Error("Missing playwrightPath");
  }
  if (!Array.isArray(payload.cookies)) {
    throw new Error("Missing cookies array");
  }
}

async function main() {
  const raw = await readStdin();
  const payload = JSON.parse(raw);
  validatePayload(payload);

  fs.mkdirSync(payload.profileDir, { recursive: true, mode: 0o700 });
  const { chromium } = require(payload.playwrightPath);

  const context = await chromium.launchPersistentContext(payload.profileDir, {
    executablePath: payload.executablePath,
    headless: true,
    args: [
      "--disable-gpu",
      "--disable-blink-features=AutomationControlled",
    ],
    ignoreDefaultArgs: ["--enable-automation"],
  });

  let imported = 0;
  let skipped = 0;
  const skippedDomains = new Set();

  try {
    const batchSize = 200;
    for (let i = 0; i < payload.cookies.length; i += batchSize) {
      const batch = payload.cookies.slice(i, i + batchSize);
      try {
        await context.addCookies(batch);
        imported += batch.length;
      } catch {
        for (const cookie of batch) {
          try {
            await context.addCookies([cookie]);
            imported += 1;
          } catch {
            skipped += 1;
            if (typeof cookie?.domain === "string" && cookie.domain) {
              skippedDomains.add(cookie.domain.replace(/^\./, ""));
            }
          }
        }
      }
    }
  } finally {
    await context.close();
  }

  process.stdout.write(
    `${JSON.stringify({
      imported,
      skipped,
      skippedDomains: [...skippedDomains].sort().slice(0, 20),
    })}\n`,
  );
}

main().catch((err) => {
  process.stderr.write(`${err?.message ?? String(err)}\n`);
  process.exit(1);
});
