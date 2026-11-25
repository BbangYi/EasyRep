import assert from "node:assert/strict";
import { build } from "esbuild";
const result = await build({
  stdin: { contents: 'export * from "./standalone/live-route.ts"; export {EnvironmentInsights} from "./standalone/environment-insights.tsx"; export {renderToStaticMarkup} from "react-dom/server"; export {createElement} from "react";', resolveDir: process.cwd(), loader: "ts" },
  bundle: true, write: false, platform: "node", format: "cjs", jsx: "automatic",
});
// A single bundle keeps the renderer and component on the same React instance.
const { createRequire } = await import("node:module");
const module = { exports: {} };
new Function("module", "exports", "require", result.outputFiles[0].text)(module, module.exports, createRequire(import.meta.url));
const { readRoute, routeHash, selectedCage, EnvironmentInsights, createElement, renderToStaticMarkup } = module.exports;
const cages = [{id: "first", sampledAt: null}, {id: "measured", sampledAt: "2026-10-06T00:00:00Z"}];
assert.equal(selectedCage(cages, "missing"), undefined);
assert.equal(selectedCage(cages, "first").id, "first");
assert.equal(selectedCage(cages, "").id, "measured");
assert.equal(selectedCage([], ""), undefined);
for (const hash of ["#presentation", "#history/first?section=device", "#history/first?section=care", "#history/first", "#environment/first?mode=forecast", "#environment/first?mode=spatial", "#home/first"]) {
  assert.equal(routeHash(readRoute(hash)), hash);
}
assert.equal(readRoute("#history/first?section=bad").section, "overview");
assert.equal(readRoute("#environment/first?mode=bad").mode, "measured");
assert.equal(readRoute("#unknown/first").view, "home");
const cage = { ...cages[0], sensors: [], source: null, stale: true };
const render = (cage, mode = "forecast") => renderToStaticMarkup(createElement(EnvironmentInsights, {cage, mode, onMeasured() {}, onManagement() {}}));
assert.match(render(cage), /AI 미래 예측/);
assert.match(render(cage), /아직 생성된 예측 결과가 없습니다/);
assert.match(render(cage), /실측 이력 없음/);
assert.match(render({...cage, source: "simulation", sampledAt: "2026-10-06T00:00:00Z"}), /가상 데이터 · 학습 대상 제외/);
assert.match(render({...cage, source: "sensor", sampledAt: "2026-10-06T00:00:00Z"}), /실측 수신 · 이력 검토 필요/);
assert.match(render(cage, "spatial"), /아직 생성된 추정 결과가 없습니다/);
assert.doesNotMatch(render(cage), /<svg[^>]*recharts|<canvas/);
console.log("Route and AI preparation checks passed: explicit targets, return destinations, truthful empty states.");

assert.equal(readRoute("#history/first").section, "overview");
assert.equal(readRoute("#presentation").view, "presentation");
assert.equal(readRoute("#presentation").id, "");
assert.equal(routeHash({ view: "presentation", id: "first", section: "care", mode: "spatial" }), "#presentation");
assert.equal(readRoute(new URL("https://local.invalid/?care_saved=first#history/first?section=care").hash).section, "care");
