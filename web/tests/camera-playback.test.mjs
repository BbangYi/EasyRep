import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";

const built = await build({ entryPoints: ["standalone/camera-playback.ts"], bundle: true,
  write: false, platform: "node", format: "esm" });
const { createCameraPlayback, CAMERA_RECOVERY } = await import(
  "data:text/javascript;base64," + Buffer.from(built.outputFiles[0].text).toString("base64"));
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

function rig({ codes = [], initiallyPaused = false, pending = false, frameCallback = true, synchronousReady = false, synchronousFault = false, deferredReady = false } = {}) {
  let now = 0, next = 0, hidden = false, active = 0, probeCalls = 0, probeActive = 0, maxProbeActive = 0;
  let rejectPlay = false, decodedFrames = 0, nextFrame = 0, aborted = 0;
  const timers = new Map(), frames = new Map(), statuses = [], intents = [], connections = [];
  const video = Object.assign(new EventTarget(), {
    paused: true, seeking: false, ended: false, error: null,
    play() {
      if (rejectPlay) return Promise.reject(new DOMException("Playback failed", typeof rejectPlay === "string" ? rejectPlay : "NotAllowedError"));
      this.paused = false; this.dispatchEvent(new Event("play")); return Promise.resolve();
    },
    removeAttribute() {}, load() {},
    getVideoPlaybackQuality: () => ({ totalVideoFrames: decodedFrames, droppedVideoFrames: 0 }),
    ...(frameCallback ? {
      requestVideoFrameCallback(fn) { frames.set(++nextFrame, fn); return nextFrame; },
      cancelVideoFrameCallback(id) { frames.delete(id); },
    } : {}),
  });
  const options = {
    initiallyPaused, now: () => now, hidden: () => hidden,
    setTimer(fn, delay) { timers.set(++next, { at: now + delay, fn }); return next; },
    clearTimer: (id) => timers.delete(id),
    onStatus: (status) => statuses.push(status), onPauseIntent: (paused) => intents.push(paused),
    probe(signal) {
      probeCalls++; probeActive++; maxProbeActive = Math.max(maxProbeActive, probeActive);
      if (pending) return new Promise((_, reject) => signal.addEventListener("abort", () => {
        aborted++; probeActive--; reject(new DOMException("Aborted", "AbortError"));
      }, { once: true }));
      probeActive--; return Promise.resolve(codes.shift() ?? 200);
    },
    connect(ready, failed) {
      active++;
      const connection = { ready, failed, destroyed: false, suspended: false };
      connections.push(connection);
      if (synchronousReady) ready(); else if (!deferredReady) queueMicrotask(ready);
      if (synchronousFault) failed({ network: true, status: 503 });
      return {
        suspend() { connection.suspended = true; },
        resume() { connection.suspended = false; },
        destroy() { if (!connection.destroyed) { connection.destroyed = true; active--; } },
      };
    },
  };
  const controller = createCameraPlayback(video, options);
  async function advance(ms) {
    await settle(); const end = now + ms;
    for (;;) {
      const due = [...timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      now = due[1].at; timers.delete(due[0]); due[1].fn(); await settle();
    }
    now = end; await settle();
  }
  return { controller, video, statuses, intents, connections, timers, frames, advance,
    get probeCalls() { return probeCalls; }, get active() { return active; },
    get maxProbeActive() { return maxProbeActive; }, get aborted() { return aborted; },
    rejectPlay(value) { rejectPlay = value; },
    hidden(value) { hidden = value; controller.visibility(); },
    frame(count) { decodedFrames = count; const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach((fn) => fn(now, { presentedFrames: count })); },
    pause() { video.paused = true; video.dispatchEvent(new Event("pause")); },
  };
}

test("nonfatal503/404 errors reload once; fast budget becomes slow probes without overlapping", async () => {
  const r = rig(); await settle(); assert.equal(r.active, 1);
  const old = r.connections[0];
  old.failed({ network: true, fatal: false, status: 503 });
  old.failed({ network: true, fatal: false, status: 404 });
  assert.equal(r.active, 0); assert.equal(r.probeCalls, 1);
  for (const [index, delay] of CAMERA_RECOVERY.retryDelays.entries()) {
    await r.advance(delay); assert.equal(r.probeCalls, index + 2);
    r.connections.at(-1).failed({ network: true, fatal: false, status: 404 });
  }
  assert.equal(r.statuses.at(-1), "waiting");
  await r.advance(29999); assert.equal(r.probeCalls, 5);
  await r.advance(1); assert.equal(r.probeCalls, 6);
  assert.equal(r.maxProbeActive, 1); r.controller.destroy();
});

test("probe timeout and unmount cancel the single in-flight request and timers", async () => {
  const r = rig({ pending: true }); await r.advance(8000);
  assert.equal(r.aborted, 1); await r.advance(1000); assert.equal(r.probeCalls, 2);
  r.controller.destroy(); await settle();
  assert.equal(r.aborted, 2); assert.equal(r.timers.size, 0); assert.equal(r.frames.size, 0);
  const count = r.statuses.length; await r.advance(60000);
  assert.equal(r.probeCalls, 2); assert.equal(r.statuses.length, count);
});

test("stable decoded playback, not manifest success or seeking, resets retry budget", async () => {
  const r = rig(); await settle();
  for (const delay of CAMERA_RECOVERY.retryDelays) {
    r.connections.at(-1).failed({ network: true }); await r.advance(delay);
  }
  for (let i = 1; i <= 22; i++) { r.frame(i * 20); await r.advance(1000); }
  r.connections.at(-1).failed({ network: true });
  const before = r.probeCalls; await r.advance(1000); assert.equal(r.probeCalls, before + 1);
  r.video.seeking = true; r.video.dispatchEvent(new Event("seeking"));
  await r.advance(30000); assert.equal(r.probeCalls, before + 1);
  r.video.seeking = false; r.video.dispatchEvent(new Event("seeked"));
  r.controller.destroy();
});

test("decoded-frame stall recovers; clock movement alone is not progress", async () => {
  const r = rig(); await settle(); r.frame(1); r.frame(2); r.video.currentTime = 500;
  await r.advance(8000); assert.equal(r.active, 0);
  await r.advance(1000); assert.equal(r.probeCalls, 2); r.controller.destroy();
});

test("playback-quality fallback detects real frame progress", async () => {
  const r = rig({ frameCallback: false }); await settle();
  for (let i = 1; i <= 12; i++) { r.frame(i * 20); await r.advance(1000); }
  assert.equal(r.probeCalls, 1); assert.equal(r.statuses.at(-1), "playing"); r.controller.destroy();
});

test("user pause survives availability refresh/recreation and hidden tabs never restart it", async () => {
  const r = rig(); await settle(); r.pause();
  assert.equal(r.intents.at(-1), true); assert.equal(r.statuses.at(-1), "paused");
  r.connections[0].failed({ network: true, status: 503 });
  r.hidden(true); await r.advance(40000); r.hidden(false); r.controller.retry(); await r.advance(40000);
  assert.equal(r.probeCalls, 1); r.controller.destroy();
  const remounted = rig({ initiallyPaused: r.intents.at(-1) }); await remounted.advance(40000);
  assert.equal(remounted.probeCalls, 0); remounted.controller.play(); await settle();
  assert.equal(remounted.probeCalls, 1); remounted.controller.destroy();
});

test("hidden-tab time is not a stall and late callbacks cannot revive disposed players", async () => {
  const r = rig(); await settle(); const old = r.connections[0];
  r.hidden(true); await r.advance(60000); r.hidden(false); await r.advance(1000);
  assert.equal(r.probeCalls, 1); r.frame(1); r.frame(2);
  r.controller.destroy(); old.failed({ fatal: true }); r.video.dispatchEvent(new Event("play"));
  await r.advance(60000); assert.equal(r.active, 0); assert.equal(r.probeCalls, 1);
});

test("autoplay rejection requires explicit play; authorization errors do not auto retry", async () => {
  const r = rig(); r.rejectPlay(true); await settle();
  assert.equal(r.statuses.at(-1), "play-required"); await r.advance(60000); assert.equal(r.probeCalls, 1);
  r.rejectPlay(false); r.controller.play(); await settle(); r.frame(1); r.frame(2);
  assert.equal(r.statuses.at(-1), "playing"); assert.equal(r.connections[0].suspended, false);
  r.connections[0].failed({ network: true, status: 403 }); await r.advance(60000);
  assert.equal(r.statuses.at(-1), "denied"); assert.equal(r.probeCalls, 1); r.controller.destroy();
});


test("synchronous ready/failure callbacks cannot strand or leak a constructed transport", async () => {
  const r = rig({ synchronousReady: true }); await settle();
  assert.equal(r.video.paused, false); r.controller.destroy();
  const failed = rig({ synchronousFault: true }); await settle();
  assert.equal(failed.active, 0); assert.equal(failed.statuses.at(-1), "retrying");
  await failed.advance(1000); assert.equal(failed.probeCalls, 2); assert.equal(failed.active, 0);
  failed.controller.destroy();
});


test("unsupported or failed media play is recovered rather than mislabeled as autoplay policy", async () => {
  const r = rig(); r.rejectPlay("NotSupportedError"); await settle();
  assert.equal(r.statuses.at(-1), "retrying"); assert.equal(r.active, 0);
  await r.advance(1000); assert.equal(r.probeCalls, 2);
  assert.ok(!r.statuses.includes("play-required")); r.controller.destroy();
});


test("pause from background media controls stays paused when the tab becomes visible", async () => {
  const r = rig(); await settle(); r.hidden(true); r.pause();
  r.hidden(false); await r.advance(60000);
  assert.equal(r.intents.at(-1), true); assert.equal(r.probeCalls, 1);
  assert.equal(r.statuses.at(-1), "paused"); r.controller.destroy();
});


test("native video Play after autoplay denial also resumes suspended HLS", async () => {
  const r = rig(); r.rejectPlay(true); await settle();
  assert.equal(r.connections[0].suspended, true); assert.equal(r.statuses.at(-1), "play-required");
  r.rejectPlay(false); await r.video.play(); await settle(); r.frame(1); r.frame(2);
  assert.equal(r.connections[0].suspended, false); assert.equal(r.statuses.at(-1), "playing");
  assert.equal(r.probeCalls, 1); r.controller.destroy();
});

test("manifest ready while hidden plays on return without rebuilding or overriding pause", async () => {
  const r = rig({ deferredReady: true }); await settle();
  r.hidden(true); r.connections[0].ready(); await r.advance(10000);
  assert.equal(r.video.paused, true); assert.equal(r.probeCalls, 1);
  r.hidden(false); await settle();
  assert.equal(r.video.paused, false); assert.equal(r.probeCalls, 1);
  r.pause(); r.hidden(true); r.hidden(false); await r.advance(10000);
  assert.equal(r.video.paused, true); assert.equal(r.probeCalls, 1); r.controller.destroy();
});
