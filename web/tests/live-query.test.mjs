import assert from "node:assert/strict";
import { build } from "esbuild";

// Run the real hook with a tiny hook lifecycle harness; no browser or new dependency.
let slots = [], cursor = 0, effects = [];
globalThis.queryHooks = {
  useState(initial) {
    const index = cursor++;
    if (!(index in slots)) slots[index] = initial;
    return [slots[index], (value) => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
  },
  useRef(initial) {
    const index = cursor++;
    return slots[index] ||= { current: initial };
  },
  useEffect(callback, deps) {
    const index = cursor++;
    if (!slots[index] || deps.some((value, i) => value !== slots[index].deps[i])) {
      slots[index]?.cleanup?.();
      effects.push(() => { slots[index] = { deps, cleanup: callback() }; });
    }
  },
};
const bundled = await build({
  entryPoints: ["standalone/use-live-query.ts"], bundle: true, write: false,
  platform: "node", format: "esm",
  plugins: [{ name: "hook-harness", setup(builder) {
    builder.onResolve({ filter: /^react$/ }, () => ({ path: "react", namespace: "harness" }));
    builder.onLoad({ filter: /.*/, namespace: "harness" }, () => ({ contents:
      "export const {useState,useEffect,useRef} = globalThis.queryHooks;" }));
  } }],
});
const { useLiveQuery, refreshLiveQueries, loginReturnUrl } = await import(
  "data:text/javascript;base64," + Buffer.from(bundled.outputFiles[0].text).toString("base64")
);
const win = new EventTarget(), doc = new EventTarget();
let online = true, nextTimer = 0, calls = 0, nextResponse;
const timers = new Map(), intervals = new Map(), redirects = [];
Object.assign(win, {
  setTimeout(fn) { timers.set(++nextTimer, fn); return nextTimer; },
  clearTimeout(id) { timers.delete(id); },
  setInterval(fn) { intervals.set(++nextTimer, fn); return nextTimer; },
  clearInterval(id) { intervals.delete(id); },
  location: { hash: "#history/cage-01", replace: (url) => redirects.push(url) },
});
doc.hidden = false;
globalThis.window = win;
globalThis.document = doc;
Object.defineProperty(globalThis, "navigator", { configurable: true, value: { get onLine() { return online; } } });
globalThis.fetch = async (url, options) => {
  calls++;
  assert.equal(options.credentials, "same-origin");
  assert.equal(options.cache, "no-store");
  return nextResponse(url, options);
};
let url = "/api/enclosures/";
const success = (data) => { nextResponse = async () => Response.json(data); };
const status = (code) => { nextResponse = async () => new Response("", { status: code }); };
const render = () => {
  cursor = 0;
  const result = useLiveQuery(url, 10000);
  effects.splice(0).forEach((fn) => fn());
  return result;
};
const settle = async () => { await new Promise(setImmediate); return render(); };

success({ items: ["first"] });
render();
let state = await settle();
assert.deepEqual(state.data, { items: ["first"] });
const firstUpdated = state.updatedAt;
assert.ok(firstUpdated);

status(502); state.refresh(); state = await settle();
assert.deepEqual(state.data.items, ["first"]);
assert.equal(state.updatedAt, firstUpdated);
assert.ok(state.error);

online = false; win.dispatchEvent(new Event("offline")); state = render();
assert.equal(state.offline, true);
assert.deepEqual(state.data.items, ["first"]);
const offlineCalls = calls;
state.refresh(); await settle(); assert.equal(calls, offlineCalls);

success({ items: ["recovered"] });
online = true; win.dispatchEvent(new Event("online")); state = await settle();
assert.deepEqual(state.data.items, ["recovered"]);
assert.equal(state.error, undefined);
assert.equal(state.offline, false);

status(403); state.refresh(); state = await settle();
assert.equal(state.data, undefined); assert.equal(state.updatedAt, undefined);
success({ items: ["again"] }); state.refresh(); state = await settle();
status(503); state.refresh(); state = await settle();
assert.equal(state.data, undefined, "maintenance must hide cached data");

success({ items: ["another"] }); state.refresh(); state = await settle();
status(500); url = "/api/enclosures/other/history/";
assert.equal(render().data, undefined, "never show a previous URL's result");
state = await settle(); assert.equal(state.data, undefined);

success({ points: [] }); refreshLiveQueries(); state = await settle();
assert.deepEqual(state.data, { points: [] });
doc.hidden = true; const hiddenCalls = calls;
refreshLiveQueries(); assert.equal(calls, hiddenCalls);
doc.hidden = false; doc.dispatchEvent(new Event("visibilitychange")); await settle();
assert.equal(calls, hiddenCalls + 1);

status(401); state.refresh(); state = await settle();
assert.equal(state.data, undefined);
assert.equal(redirects.at(-1), "/login/?next=%2F%23history%2Fcage-01");
assert.equal(loginReturnUrl("https://evil.example"), "/login/?next=%2F");
assert.equal(new URL(loginReturnUrl("#//evil.example"), "https://habitatos.kro.kr").searchParams.get("next"), "/#//evil.example");

// A late response from an unmounted/changed URL cannot overwrite or redirect.
let resolveOld;
nextResponse = () => new Promise((resolve) => { resolveOld = resolve; });
url = "/api/enclosures/old/"; render();
success({ items: ["new URL"] }); url = "/api/enclosures/new/"; render();
state = await settle();
const redirectCount = redirects.length;
resolveOld(new Response("", { status: 401 })); state = await settle();
assert.equal(redirects.length, redirectCount);
assert.deepEqual(state.data.items, ["new URL"]);

// Timeout, in-flight deduplication, and listener cleanup.
nextResponse = (_url, { signal }) => new Promise((_resolve, reject) => {
  signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
});
state.refresh(); const pendingCalls = calls;
refreshLiveQueries(); assert.equal(calls, pendingCalls);
[...timers.values()].forEach((fn) => fn()); state = await settle();
assert.match(state.error, /응답이 늦/); assert.deepEqual(state.data.items, ["new URL"]);
slots.forEach((slot) => slot?.cleanup?.());
assert.equal(intervals.size, 0);
const cleanupCalls = calls; refreshLiveQueries(); win.dispatchEvent(new Event("online"));
assert.equal(calls, cleanupCalls);
console.log("Live query checks passed: recovery, cached values, access loss, return URL, cancellation, timeout, cleanup.");
