import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { dirname, resolve, basename } from "node:path";
import { gzipSync } from "node:zlib";
import { init, parse } from "es-module-lexer";

// Run after the production build. Budget actual output, including shared dependencies.
await init;
const root = resolve("dist/client");
const chunks = resolve(root, "_next/static/chunks");
const files = await readdir(chunks);
const app = files.find((file) => /^habitat-app-.*\.js$/.test(file));
const chart = files.find((file) => /^environment-chart-.*\.js$/.test(file));
assert.ok(app && chart, "The dashboard and deferred chart must both be built");
const manifest = JSON.parse(await readFile(resolve(root, "vinext-client-entry-manifest.json"), "utf8"));
const pending = [resolve(chunks, app), resolve(root, manifest.appBrowserEntry)];
const initial = new Set();
let rawBytes = 0;
let gzipBytes = 0;
while (pending.length) {
  const file = pending.pop();
  if (initial.has(file)) continue;
  initial.add(file);
  const source = await readFile(file);
  rawBytes += source.length;
  gzipBytes += gzipSync(source).length;
  const [imports] = parse(source.toString());
  for (const item of imports) {
    if (item.d === -1 && item.n?.startsWith(".")) pending.push(resolve(dirname(file), item.n));
  }
}
assert.ok(!initial.has(resolve(chunks, chart)), "Home must not download the plotting code eagerly");
assert.ok(gzipBytes < 220_000, `Initial JavaScript exceeds the 220 kB compressed budget: ${gzipBytes}`);
console.log(JSON.stringify({ files: [...initial].map((file) => basename(file)), rawBytes, gzipBytes, chartDeferred: true }, null, 2));
