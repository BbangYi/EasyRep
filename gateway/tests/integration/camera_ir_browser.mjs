// Optional regression: Node 22+ and Chromium. All camera/IR APIs are local mocks;
// this test never contacts a camera, MQTT broker, or physical actuator.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {mkdtemp, readFile, rm} from 'node:fs/promises';

const html = await readFile(new URL('../../habitat_gateway/camera.html', import.meta.url));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let loggedIn = false, canControl = false, postDelay = 0, statusDelay = 0;
let failStatus = false, failCommand = false, denyCommand = false;
const commands = [], errors = [];
const state = {cage_id: 'CAGE-001', configured: true, status: 'off', online: true,
  outputs_locked: false, gpio_requested_on: false, actual_ir_on: null,
  active: false, mode: null, remaining_s: 0, max_on_seconds: 900, error: null};
const unconfigured = {cage_id: 'CAGE-002', configured: false, status: 'unconfigured',
  online: false, outputs_locked: true, gpio_requested_on: null, actual_ir_on: null,
  active: false, mode: null, remaining_s: 0, max_on_seconds: 900, error: null};
const server = createServer(async (req, res) => {
  const send = (status, data) => {res.writeHead(status, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}); res.end(JSON.stringify(data));};
  try {
    const path = new URL(req.url, 'http://127.0.0.1').pathname;
    if (path === '/camera') {res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'}); res.end(html); return;}
    if (path === '/camera/hls.js') {res.writeHead(200, {'Content-Type': 'application/javascript'}); res.end('window.Hls={isSupported:()=>false};'); return;}
    if (path === '/camera/session') {
      if (req.method === 'DELETE') {loggedIn = false; canControl = false; send(200, {}); return;}
      const key = req.headers.authorization;
      if (!['Bearer view-test', 'Bearer control-test'].includes(key)) {send(401, {}); return;}
      loggedIn = true; canControl = key === 'Bearer control-test'; send(200, {}); return;
    }
    if (!loggedIn) {send(401, {}); return;}
    if (path === '/camera/control/session') {send(200, {can_control: canControl, csrf_token: canControl ? 'test-csrf' : null}); return;}
    if (path === '/camera/api/cameras') {send(200, {site_id: 'STORE-TEST', cage_ids: ['CAGE-001', 'CAGE-002'], cameras: []}); return;}
    if (path.startsWith('/camera/api/ir/')) {
      const cage = decodeURIComponent(path.split('/').at(-1));
      if (req.method === 'POST') {
        let body = ''; for await (const chunk of req) body += chunk;
        const command = JSON.parse(body); commands.push({cage, ...command, csrf: req.headers['x-habitat-csrf']});
        if (!canControl || denyCommand) {canControl = false; send(403, {}); return;}
        if (failCommand) {send(503, {detail: 'INTERNAL_SECRET_MUST_NOT_APPEAR'}); return;}
        assert.equal(cage, 'CAGE-001'); assert.equal(req.headers['x-habitat-csrf'], 'test-csrf');
        Object.assign(state, {status: command.action === 'on' ? 'on' : 'off', gpio_requested_on: command.action === 'on', active: command.action === 'on', mode: command.action === 'on' ? command.seconds === null ? 'continuous' : 'timed' : null, remaining_s: command.action === 'on' ? command.seconds : 0});
        const snapshot = {...state};
        if (command.action === 'on') await delay(postDelay);
        send(200, snapshot); return;
      }
      const snapshot = {...(cage === 'CAGE-001' ? state : unconfigured)};
      const wait = statusDelay; statusDelay = 0;
      await delay(wait);
      send(failStatus ? 503 : 200, snapshot); return;
    }
    send(404, {});
  } catch (error) {errors.push(error.message); res.destroy();}
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const profile = await mkdtemp('/tmp/habitat-camera-ir-browser-');
const browser = spawn(process.env.HABITAT_CHROMIUM || '/usr/bin/chromium', [
  '--headless', '--no-gl-override', '--disable-gpu', '--password-store=basic', '--js-flags=', '--no-first-run',
  '--no-default-browser-check', '--no-proxy-server', '--disable-background-networking',
  '--disable-sync', '--disable-extensions', '--window-size=1000,900', '--remote-debugging-port=0',
  `--user-data-dir=${profile}`, origin + '/camera#key=view-test'
], {stdio: ['ignore', 'ignore', 'pipe']});
let log = '', socket;
browser.stderr.on('data', chunk => {log = (log + chunk).slice(-2000);});
try {
  let port;
  for (let i = 0; i < 100; i++) {
    try {port = Number((await readFile(`${profile}/DevToolsActivePort`, 'utf8')).split('\n')[0]); break;} catch {await delay(100);}
  }
  assert.ok(port, 'Chromium debugging endpoint unavailable');
  const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const page = pages.find(page => page.type === 'page' && page.url.startsWith(origin)); assert.ok(page);
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject;});
  let sequence = 0; const pending = new Map();
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
    if (message.id) {const task = pending.get(message.id); pending.delete(message.id); if (task) message.error ? task.reject(Error(message.error.message)) : task.resolve(message.result);}
  };
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence, timer = setTimeout(() => {pending.delete(id); reject(Error('timeout ' + method));}, 12000);
    pending.set(id, {resolve: value => {clearTimeout(timer); resolve(value);}, reject: error => {clearTimeout(timer); reject(error);}});
    socket.send(JSON.stringify({id, method, params}));
  });
  const evaluate = async expression => {
    const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const until = async expression => {for (let i = 0; i < 100; i++) {if (await evaluate(expression)) return; await delay(100);} throw Error('condition failed: ' + expression);};
  const click = id => evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);
  const select = cage => evaluate(`document.getElementById('cages').value=${JSON.stringify(cage)};document.getElementById('cages').dispatchEvent(new Event('change'))`);
  const unlock = async () => {
    await evaluate("document.getElementById('ir-key').value='control-test';document.getElementById('ir-unlock').requestSubmit()");
    await until("document.getElementById('ir-unlock').hidden");
  };
  await call('Runtime.enable');
  await until("document.getElementById('viewer') && !document.getElementById('viewer').hidden && document.getElementById('ir-status').textContent.includes('꺼짐')");
  assert.equal(await evaluate('location.hash'), '');
  assert.equal(await evaluate("document.getElementById('ir-unlock').hidden"), false);
  assert.equal(await evaluate("document.getElementById('ir-on').disabled"), true);
  assert.equal(await evaluate("document.getElementById('ir-off').disabled"), true);
  await click('ir-on'); assert.equal(commands.length, 0, 'view key must not command');
  await unlock();
  await until("!document.getElementById('ir-on').disabled");
  assert.equal(commands.length, 0, 'unlock must not turn on');
  assert.equal(await evaluate("document.getElementById('ir-key').value"), '');
  assert.equal(await evaluate("document.getElementById('ir-seconds').value"), 'continuous');
  assert.equal(await evaluate("document.getElementById('ir-on').textContent"), '계속 켜기');
  await click('ir-on');
  await until("document.getElementById('ir-status').textContent.includes('켜짐')");
  assert.deepEqual(commands.at(-1), {cage: 'CAGE-001', action: 'on', seconds: null, csrf: 'test-csrf'});
  assert.equal(await evaluate("document.getElementById('ir-remaining').textContent"), '계속 켜짐 · 끄기를 누르면 종료');
  assert.equal(await evaluate("document.getElementById('ir-on').disabled"), true);
  const beforeActiveClick = commands.length; await click('ir-on');
  assert.equal(commands.length, beforeActiveClick, 'active operation must not send another ON');
  await call('Page.reload');
  await until("document.getElementById('ir-remaining')?.textContent === '계속 켜짐 · 끄기를 누르면 종료' && document.getElementById('ir-unlock').hidden");
  assert.equal(commands.length, beforeActiveClick, 'reloading continuous mode must not command');
  assert.equal(await evaluate("document.getElementById('ir-on').disabled"), true);
  assert.equal(await evaluate("document.getElementById('ir-off').disabled"), false);
  await click('ir-off');
  await until("document.getElementById('ir-status').textContent.includes('꺼짐')");
  await evaluate("document.getElementById('ir-seconds').value='300';document.getElementById('ir-seconds').dispatchEvent(new Event('change'))");
  assert.equal(await evaluate("document.getElementById('ir-on').textContent"), 'IR 켜기');
  await click('ir-on');
  await until("document.getElementById('ir-status').textContent.includes('켜짐')");
  assert.deepEqual(commands.at(-1), {cage: 'CAGE-001', action: 'on', seconds: 300, csrf: 'test-csrf'});
  assert.match(await evaluate("document.getElementById('ir-remaining').textContent"), /300초/);
  await click('ir-off');
  await until("document.getElementById('ir-status').textContent.includes('꺼짐')");
  assert.equal(commands.at(-1).action, 'off');

  // A late ON response cannot overwrite the later OFF response.
  postDelay = 1000;
  await evaluate("document.getElementById('ir-seconds').value='10'");
  await click('ir-on');
  await until("document.getElementById('ir-status').textContent.includes('켜기 요청')");
  assert.equal(await evaluate("document.getElementById('ir-off').disabled"), false);
  await click('ir-off');
  assert.equal(commands.at(-1).action, 'on', 'OFF must await pending ON before sending');
  assert.match(await evaluate("document.getElementById('ir-status').textContent"), /끄기 요청/);
  await until("document.getElementById('ir-status').textContent.includes('꺼짐')");
  await delay(1200);
  assert.match(await evaluate("document.getElementById('ir-status').textContent"), /꺼짐/);
  assert.deepEqual(commands.slice(-2).map(command => [command.action, command.seconds]), [['on', 10], ['off', undefined]]);
  // Even if the browser times out waiting for ON, the explicit OFF follows it.
  postDelay = 5500; await click('ir-on'); await delay(100); await click('ir-off');
  await until("document.getElementById('ir-status').textContent.includes('꺼짐')");
  await delay(700);
  assert.deepEqual(commands.slice(-2).map(command => command.action), ['on', 'off']);
  assert.match(await evaluate("document.getElementById('ir-status').textContent"), /꺼짐/);
  postDelay = 0;

  // Late status from a previous cage cannot enable control on an unconfigured cage.
  await select('CAGE-002'); await until("document.getElementById('ir-status').textContent.includes('등록되지')");
  statusDelay = 900; await select('CAGE-001'); await delay(100); await select('CAGE-002');
  await until("document.getElementById('ir-status').textContent.includes('등록되지')"); await delay(1100);
  assert.equal(await evaluate("document.getElementById('ir-on').disabled"), true);
  assert.equal(await evaluate("document.getElementById('ir-off').disabled"), true);
  assert.match(await evaluate("document.getElementById('ir-title').textContent"), /CAGE-002/);
  await select('CAGE-001'); await until("!document.getElementById('ir-on').disabled");

  Object.assign(state, {online: false, status: 'offline'}); await click('retry');
  await until("document.getElementById('ir-status').textContent.includes('연결 대기')");
  assert.equal(await evaluate("document.getElementById('ir-on').disabled"), true);
  assert.equal(await evaluate("document.getElementById('ir-off').disabled"), false);
  await click('ir-off'); await until("!document.getElementById('ir-off').disabled");
  Object.assign(state, {online: true, outputs_locked: true, status: 'locked'}); await click('retry');
  await until("document.getElementById('ir-status').textContent.includes('잠겨')");
  assert.equal(await evaluate("document.getElementById('ir-on').disabled"), true);
  assert.equal(await evaluate("document.getElementById('ir-off').disabled"), false);
  Object.assign(state, {outputs_locked: false, status: 'off', max_on_seconds: 60}); await click('retry');
  await until("!document.getElementById('ir-on').disabled");
  assert.equal(await evaluate("[...document.getElementById('ir-seconds').options].find(option => option.value === '300').disabled"), true);
  assert.equal(await evaluate("[...document.getElementById('ir-seconds').options].find(option => option.value === 'continuous').disabled"), false);

  failCommand = true; const beforeOnFailure = commands.length; await click('ir-on');
  await until("document.getElementById('ir-error').textContent.includes('완료하지 못')");
  await delay(3300); assert.equal(commands.length, beforeOnFailure + 1, 'failed ON must never retry');
  failCommand = false;

  // Failed reads still allow stopping a known configured cage; failures never retry ON.
  failStatus = true;
  await until("document.getElementById('ir-status').textContent.includes('다시 확인')");
  assert.equal(await evaluate("document.getElementById('ir-on').disabled"), true);
  assert.equal(await evaluate("document.getElementById('ir-off').disabled"), false);
  failStatus = false; failCommand = true;
  const beforeFailure = commands.length; await click('ir-off');
  await until("document.getElementById('ir-error').textContent.includes('확인하지 못')");
  await delay(3300); assert.equal(commands.length, beforeFailure + 2, 'explicit OFF retries at most once');
  assert.equal(await evaluate("document.body.textContent.includes('INTERNAL_SECRET')"), false);
  failCommand = false; denyCommand = true; await click('ir-off');
  await until("!document.getElementById('ir-unlock').hidden");
  assert.equal(await evaluate("document.getElementById('ir-on').disabled"), true);
  denyCommand = false; await unlock();

  // Logout discards a pending command response and clears control state.
  postDelay = 900; await click('ir-on'); await delay(100); await click('logout');
  await delay(1100);
  assert.equal(await evaluate("document.getElementById('viewer').hidden"), true);
  assert.equal(await evaluate("document.getElementById('ir-on').disabled"), true);
  assert.equal(await evaluate("document.getElementById('ir-key').value"), '');
  const beforeReload = commands.length;
  await call('Page.navigate', {url: origin + '/camera?reconnect=1#control_key=control-test'});
  await until("document.getElementById('viewer') && !document.getElementById('viewer').hidden && document.getElementById('ir-unlock').hidden");
  assert.equal(await evaluate('location.hash'), '');
  assert.equal(commands.length, beforeReload, 'reload must not command');
  await call('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true}); await delay(200);
  assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'), false);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({passed: true, synthetic_only: true, view_only_enforced: true,
    explicit_on_and_off: true, csrf: true, default_continuous: true, continuous_null_payload: true,
    continuous_reload_no_command: true, active_on_disabled: true, optional_timed_on: true,
    off_during_on: true, off_after_on_timeout: true,
    stale_cage_ignored: true, offline_off_available: true, locked_on_disabled: true,
    max_duration: true, off_retry_bounded: true, no_on_retries: true, logout_pending_guard: true,
    control_fragment_scrubbed: true, no_automatic_on: true, mobile: true}));
} catch (error) {console.error(error.stack, log); process.exitCode = 1;}
finally {
  if (socket) socket.close(); browser.kill('SIGTERM');
  if (browser.exitCode === null) await Promise.race([new Promise(resolve => browser.once('exit', resolve)), delay(3000)]);
  if (browser.exitCode === null) browser.kill('SIGKILL');
  server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  await rm(profile, {recursive: true, force: true});
}
