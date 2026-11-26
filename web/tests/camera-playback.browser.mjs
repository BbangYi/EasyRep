// Built actual CameraVideo + hls.js + Chromium, with synthetic local media only.
// No account credentials, actual Gateway/camera routes, or IR requests are used.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { createServer } from "node:http";
import react from "@vitejs/plugin-react";

const web = fileURLToPath(new URL("../", import.meta.url));
const temporary = await mkdtemp("/tmp/easyrep-camera-browser-");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const requests = [], pendingResponses = new Set(), errors = [], diagnostics = [], checks = [];
const modes = { A: "ok", B: "ok" };
let server, browser, socket, log = "", started = Date.now(), aborted = 0;
const passed = (name) => { checks.push(name); console.log(JSON.stringify({ passed: name })); };
const entry = `${web}standalone/__camera_fixture.tsx`;
const fixture = `
import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {CameraVideo} from './enclosure-viewer';
const counts={A:0,B:0}, intents={A:false,B:false};
const originalPlay=HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play=function(){
  if(window.__blockA && this.closest('#camera-A')) return Promise.reject(new DOMException('Blocked for test','NotAllowedError'));
  return originalPlay.call(this);
};
function Fixture(){
 const [available,setAvailable]=useState({A:true,B:true});
 const [mounted,setMounted]=useState({A:true,B:true});
 const [generation,setGeneration]=useState({A:0,B:0});
 const observed=useRef(new WeakSet());
 window.__fixture={counts,intents,
  available:(id,value)=>setAvailable(old=>({...old,[id]:value})),
  unmount:(id)=>setMounted(old=>({...old,[id]:false})),
  reset:(id)=>{intents[id]=false;setMounted(old=>({...old,[id]:true}));setGeneration(old=>({...old,[id]:old[id]+1}));},
  snapshot:()=>Object.fromEntries(['A','B'].map(id=>{
    const box=document.getElementById('camera-'+id),v=box?.querySelector('video');
    return [id,{frames:counts[id],paused:v?.paused,time:v?.currentTime,width:v?.videoWidth,
      bufferEnd:v?.buffered.length?v.buffered.end(v.buffered.length-1):null,
      status:box?.querySelector('[role=status]')?.textContent||'',mounted:!!v}];
  }))};
 useEffect(()=>{
  for(const id of ['A','B']){
   const v=document.querySelector('#camera-'+id+' video');
   if(!v||observed.current.has(v))continue;
   observed.current.add(v);
   const frame=()=>{if(!v.isConnected)return;counts[id]++;v.requestVideoFrameCallback(frame);};
   v.requestVideoFrameCallback(frame);
  }
 });
 return <main>{['A','B'].map(id=><section key={id} id={'camera-'+id}>
  <h2>{id}</h2>{mounted[id]&&<CameraVideo key={generation[id]} playlist={'/fixture/'+id+'/index.m3u8'}
    available={available[id]} initiallyPaused={intents[id]} onPauseIntent={paused=>{intents[id]=paused;}}/>}
 </section>)}</main>;
}
createRoot(document.getElementById('root')).render(<Fixture/>);
`;

async function generate() {
  const ffmpeg = spawn("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
    "testsrc2=size=320x240:rate=10", "-t", "480", "-an", "-c:v", "libx264", "-preset", "ultrafast",
    "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-threads", "1", "-g", "20", "-keyint_min", "20",
    "-sc_threshold", "0", "-bf", "0", "-b:v", "300k", "-f", "hls", "-hls_time", "2",
    "-hls_list_size", "0", "-hls_flags", "independent_segments", "-hls_segment_filename",
    `${temporary}/seg-%05d.ts`, `${temporary}/all.m3u8`], { stdio: ["ignore", "ignore", "pipe"] });
  let stderr = ""; ffmpeg.stderr.on("data", (part) => { stderr += part; });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { ffmpeg.kill("SIGKILL"); reject(Error("fixture encode timeout")); }, 60000);
    ffmpeg.on("error", reject);
    ffmpeg.on("exit", (code) => { clearTimeout(timer); code === 0 ? resolve() : reject(Error(stderr)); });
  });
}

try {
  await generate();
  await build({ configFile: false, root: `${web}standalone`, publicDir: false,
    logLevel: "warn", plugins: [react(), {
      name: "camera-browser-fixture",
      resolveId(id) { if (id === entry) return entry; },
      load(id) { if (id === entry) return fixture; },
    }], resolve: { alias: { "@": web } },
    build: { outDir: `${temporary}/bundle`, emptyOutDir: true,
      rollupOptions: { input: entry, output: { entryFileNames: "fixture.js" } } },
  });
  server = createServer(async (req, res) => {
    try {
      const path = new URL(req.url, "http://127.0.0.1").pathname;
      if (path === "/camera-browser-test") {
        res.setHeader("Content-Type", "text/html");
        res.end('<!doctype html><html><head><meta charset="utf-8"><style>video{width:320px;height:240px}main{display:flex}</style></head><body><div id="root"></div><script type="module" src="/fixture.js"></script></body></html>'); return;
      }
      if (/^\/(?:fixture\.js|assets\/[A-Za-z0-9_.-]+\.js)$/.test(path)) {
        res.setHeader("Content-Type", "application/javascript");
        res.end(await readFile(`${temporary}/bundle${path}`)); return;
      }
      const match = /^\/fixture\/([AB])\/(index\.m3u8|seg-(\d{5})\.ts)$/.exec(path);
      if (!match) { res.writeHead(404); res.end(); return; }
      const camera = match[1], kind = match[2] === "index.m3u8" ? "playlist" : "segment";
      const record = { camera, kind, sequence: match[3] === undefined ? null : Number(match[3]), at: Date.now(), status: null }; requests.push(record);
      res.setHeader("Cache-Control", "no-store");
      if (modes[camera] === "stall") {
        pendingResponses.add(res);
        res.on("close", () => { pendingResponses.delete(res); record.status = "aborted"; aborted++; });
        return;
      }
      if (kind === "playlist" && modes[camera] === "playlist503") {
        record.status = 503; res.writeHead(503); res.end("unavailable"); return;
      }
      if (kind === "segment" && modes[camera] === "segment404") {
        modes[camera] = "ok"; record.status = 404; res.writeHead(404); res.end("expired"); return;
      }
      record.status = 200;
      if (kind === "playlist") {
        const high = Math.floor((Date.now() - started) / 2000) + 5;
        let body = `#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n#EXT-X-INDEPENDENT-SEGMENTS\n#EXT-X-MEDIA-SEQUENCE:${high - 5}\n`;
        for (let sequence = high - 5; sequence <= high; sequence++) body += `#EXTINF:2.000000,\nseg-${String(sequence).padStart(5, "0")}.ts\n`;
        res.setHeader("Content-Type", "application/vnd.apple.mpegurl"); res.end(body);
      } else {
        res.setHeader("Content-Type", "video/mp2t");
        try { res.end(await readFile(`${temporary}/${match[2]}`)); }
        catch (error) { errors.push(error.message); res.destroy(); }
      }
    } catch (error) { errors.push(error.message); res.destroy(); }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve)); started = Date.now();
  const origin = `http://127.0.0.1:${server.address().port}`;
  const preflight = await fetch(origin + "/camera-browser-test", { signal: AbortSignal.timeout(8000) });
  assert.equal(preflight.status, 200); await preflight.text();
  browser = spawn(process.env.EASYREP_CHROMIUM || "/usr/bin/chromium", ["--headless", "--no-gl-override", "--disable-gpu", "--password-store=basic", "--js-flags=",
    "--no-first-run", "--no-default-browser-check", "--no-proxy-server", "--disable-background-networking",
    "--disable-sync", "--disable-extensions", "--autoplay-policy=no-user-gesture-required",
    "--window-size=1000,700", "--remote-debugging-port=0", `--user-data-dir=${temporary}/profile`,
    "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  browser.stderr.on("data", (part) => { log = (log + part).slice(-3000); });
  let port;
  for (let i = 0; i < 150; i++) {
    try { port = Number((await readFile(`${temporary}/profile/DevToolsActivePort`, "utf8")).split("\n")[0]); break; }
    catch { await delay(100); }
  }
  assert.ok(port, "Chromium debugger did not start");
  const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const page = pages.find((item) => item.type === "page"); assert.ok(page);
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0; const pending = new Map(), network = new Map();
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (message.method === "Runtime.exceptionThrown") errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") diagnostics.push({ console: message.params.args.map((arg) => arg.value ?? arg.description).join(" ").slice(0, 1000) });
    if (message.method === "Network.requestWillBeSent") network.set(message.params.requestId, message.params.request.url);
    if (message.method === "Network.responseReceived" && message.params.response.status >= 400 && !message.params.response.url.includes("/fixture/")) diagnostics.push({ url: message.params.response.url, status: message.params.response.status });
    if (message.method === "Network.loadingFailed") diagnostics.push({ url: network.get(message.params.requestId), networkError: message.params.errorText });
    if (message.id) { const work = pending.get(message.id); pending.delete(message.id); if (work) message.error ? work.reject(Error(message.error.message)) : work.resolve(message.result); }
  };
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(Error("CDP timeout " + method)); }, 15000);
    pending.set(id, { resolve: (value) => { clearTimeout(timer); resolve(value); }, reject: (error) => { clearTimeout(timer); reject(error); } });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const until = async (expression, seconds = 20) => {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) { if (await evaluate(expression)) return; await delay(150); }
    throw Error("condition timed out: " + expression + " snapshot=" + JSON.stringify(await evaluate("window.__fixture?.snapshot()")) + " diagnostics=" + JSON.stringify(diagnostics.slice(-20)));
  };
  const frames = async () => evaluate("window.__fixture.snapshot()");
  const latest = async () => {
    const state = await frames();
    // Hls.js rebases media time when reconnecting; compare source sequence and
    // actual decoded progress instead of treating currentTime as a wall clock.
    const high = Math.floor((Date.now() - started) / 2000) + 5;
    const segment = requests.findLast((item) => item.camera === "A" && item.kind === "segment" && item.status === 200);
    assert.ok(segment && segment.sequence >= high - 3, "recovered camera must request current live segments");
    assert.ok(state.A.bufferEnd !== null && state.A.bufferEnd - state.A.time < 10, "decoded playback must remain near the available live edge");
  };
  await call("Runtime.enable");
  await call("Network.enable");
  await call("Page.navigate", { url: origin + "/camera-browser-test" });
  await until("window.__fixture && ['A','B'].every(id=>window.__fixture.snapshot()[id].frames>12 && !window.__fixture.snapshot()[id].paused)", 45);
  const documentMarker = await evaluate("window.__documentMarker=Math.random()");
  passed("both actual components decode advancing frames");

  let before = await frames(); modes.A = "playlist503";
  await delay(8000); assert.ok((await frames()).B.frames > before.B.frames + 25, "B must continue during A503");
  assert.ok(requests.some((item) => item.camera === "A" && item.status === 503));
  modes.A = "ok"; before = await frames();
  await until(`window.__fixture.snapshot().A.frames>${before.A.frames + 15} && !window.__fixture.snapshot().A.paused`, 35);
  await latest(); passed("transient playlist503 recovers without stopping other camera");

  const since404 = Date.now(); modes.A = "segment404"; before = await frames();
  for (let i = 0; i < 150 && !requests.some((item) => item.at >= since404 && item.status === 404); i++) await delay(100);
  assert.ok(requests.some((item) => item.at >= since404 && item.status === 404), "segment404 was exercised");
  await until(`window.__fixture.snapshot().A.frames>${before.A.frames + 30} && !window.__fixture.snapshot().A.paused`, 35);
  await latest(); passed("segment404 reconnects to current stream");

  modes.A = "stall"; before = await frames(); const oldAborted = aborted;
  await evaluate("window.__fixture.reset('A')");
  for (let i = 0; i < 110 && aborted === oldAborted; i++) await delay(100);
  assert.ok(aborted > oldAborted, "8-second stalled probe must abort");
  modes.A = "ok";
  await until(`window.__fixture.snapshot().A.frames>${before.A.frames + 12}`, 35);
  assert.ok((await frames()).B.frames > before.B.frames + 30);
  await latest(); passed("stalled request times out and recovers independently");

  await evaluate("document.querySelector('#camera-A video').pause()");
  await until("window.__fixture.intents.A && window.__fixture.snapshot().A.paused");
  await delay(500); const pausedRequests = requests.filter((item) => item.camera === "A").length;
  before = await frames();
  await evaluate("window.__fixture.available('A',false)"); await delay(1500);
  await evaluate("window.__fixture.available('A',true)"); await delay(2000);
  assert.equal((await frames()).A.paused, true);
  assert.equal(requests.filter((item) => item.camera === "A").length, pausedRequests, "availability polling must not resume requests");
  assert.ok((await frames()).A.frames <= before.A.frames + 1, "paused camera must not render new frames");
  await evaluate("document.querySelector('#camera-A button').click()");
  await until(`window.__fixture.snapshot().A.frames>${before.A.frames + 12} && !window.__fixture.snapshot().A.paused`, 20);
  passed("explicit user pause survives availability changes until Play");

  await evaluate("window.__blockA=true;window.__fixture.reset('A')");
  await until("window.__fixture.snapshot().A.status.includes('자동 재생이 차단')", 20);
  assert.equal((await frames()).A.paused, true);
  before = await frames();
  await evaluate("window.__blockA=false;document.querySelector('#camera-A button').click()");
  await until(`window.__fixture.snapshot().A.frames>${before.A.frames + 12} && !window.__fixture.snapshot().A.paused`, 20);
  passed("autoplay rejection requires explicit Play and resumes actual HLS");

  modes.A = "playlist503"; const permanentStart = Date.now(); before = await frames();
  await evaluate("window.__fixture.reset('A')");
  await delay(18000);
  let probes = requests.filter((item) => item.camera === "A" && item.kind === "playlist" && item.at >= permanentStart);
  assert.equal(probes.length, 5, "initial+1/2/4/8s attempts are bounded");
  for (let index = 1; index < probes.length; index++) assert.ok(probes[index].at - probes[index - 1].at >= [900, 1900, 3900, 7900][index - 1]);
  await delay(19000);
  assert.equal(requests.filter((item) => item.camera === "A" && item.kind === "playlist" && item.at >= permanentStart).length, 5, "no fast retries after budget exhaustion");
  const slowDeadline = Date.now() + 16000;
  while (Date.now() < slowDeadline && requests.filter((item) => item.camera === "A" && item.kind === "playlist" && item.at >= permanentStart).length < 6) await delay(200);
  probes = requests.filter((item) => item.camera === "A" && item.kind === "playlist" && item.at >= permanentStart);
  assert.equal(probes.length, 6); assert.ok(probes[5].at - probes[4].at >= 29000);
  assert.ok((await frames()).B.frames > before.B.frames + 100);
  modes.A = "ok"; await evaluate("document.querySelector('#camera-A button').click()");
  await until(`window.__fixture.snapshot().A.frames>${before.A.frames + 12}`, 20);
  await latest(); passed("permanent503 uses bounded fast attempts then30s probes");

  modes.A = "stall"; await evaluate("window.__fixture.reset('A')");
  for (let i = 0; i < 80 && !pendingResponses.size; i++) await delay(100);
  assert.ok(pendingResponses.size, "cleanup must exercise an in-flight request");
  await evaluate("window.__fixture.unmount('A');window.__fixture.unmount('B')");
  await delay(500); const afterUnmount = requests.length;
  await delay(2000); assert.equal(pendingResponses.size, 0); assert.equal(requests.length, afterUnmount);
  assert.equal(await evaluate("window.__documentMarker"), documentMarker, "all recovery occurred without page reload");
  assert.deepEqual(errors, []); passed("unmount cancels pending request and future activity");
  console.log(JSON.stringify({ passed: true, checks: checks.length, synthetic_only: true,
    actual_component: "standalone/enclosure-viewer.tsx#CameraVideo", actual_hls_adapter: true,
    chromium_decoded_frames: true, requests: requests.length, slow_probe_gap_ms: probes[5].at - probes[4].at }));
} catch (error) {
  console.error(error.stack, JSON.stringify({ errors, diagnostics: diagnostics.slice(-20) }), log); process.exitCode = 1;
} finally {
  socket?.close();
  if (browser) {
    browser.kill("SIGTERM");
    if (browser.exitCode === null) await Promise.race([new Promise((resolve) => browser.once("exit", resolve)), delay(3000)]);
    if (browser.exitCode === null) browser.kill("SIGKILL");
  }
  for (const response of pendingResponses) response.destroy();
  if (server) { server.closeAllConnections(); await new Promise((resolve) => server.close(resolve)); }
  await rm(temporary, { recursive: true, force: true });
}
