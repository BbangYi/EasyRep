import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";

// The entrance must be in the initial response, without waiting for client effects.
await mkdir("work", { recursive: true });
const temporary = await mkdtemp(resolve("work/forest-motion-test-"));
try {
  const outfile = resolve(temporary, "motion.mjs");
  await build({ entryPoints: ["components/habitat/forest-motion.tsx"], outfile,
    bundle: true, platform: "node", format: "esm", packages: "external" });
  const { ForestEntrance, useForestMotion } = await import(pathToFileURL(outfile).href);
  function InitialEntrance({ autoPlay = true }) {
    const motion = useForestMotion(autoPlay);
    return motion.playing ? createElement(ForestEntrance, { onSkip: motion.skip }) : null;
  }
  assert.equal(renderToStaticMarkup(createElement(InitialEntrance, { autoPlay: false })), "", "Returning from a management form skips the automatic entrance");
  const markup = renderToStaticMarkup(createElement(InitialEntrance));
  assert.ok(markup.includes('class="forest-entrance"'), "The first render includes the automatic entrance");
  assert.ok(markup.includes("--intro-duration:3200ms"), "The existing 3.2 second entrance is retained");
  assert.ok(markup.includes("바로 보기"), "An immediate skip remains available");
  console.log("Forest entrance: automatic first render, duration, and skip verified");
} finally {
  await rm(temporary, { recursive: true, force: true });
}
