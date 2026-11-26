// Optional browser regression: Node 22+ and Chromium; synthetic local HTTP only.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';

const web=new URL('../../habitat/digital_twin/air/web/',import.meta.url);
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const counts=new Map();
function packet(cage, baseline=true){
 const value=cage==='CAGE-A'?22:29,stamp=new Date().toISOString();
 return {schema_version:1,source_mode:'live',cage_id:cage,status:'live',fresh:true,held:false,
  message_id:randomUUID(),generated_at:stamp,sampled_at:stamp,received_at_utc:stamp,
  accepted_samples:1,age_seconds:0,source_age_seconds:0,stale_after_s:30,
  dimensions_m:[.2,.2,.3],grid:{shape_zyx:[30,20,20]},color_range_c:[value-1,value+1],
  sensors:['T1','T2','T3'].map((id,i)=>({id,label:id,value_c:value,xyz_m:[[.1,.1,.28],[.02,.02,.08],[.18,.18,.08]][i]})),
  field:{values_c:Array(12000).fill(value)},baseline:baseline?{values_c:Array(12000).fill(value)}:null};
}
const historyStamp=new Date(Date.now()-600000).toISOString();
let historyFlow={...packet('CAGE-A'),data_origin:'history',status:'history',fresh:false,held:true,
 sampled_at:historyStamp,received_at_utc:null,age_seconds:null,source_age_seconds:600,
 history_samples:3,live_samples:0,accepted_samples:3,loaded_at:new Date().toISOString()};
const server=createServer(async(req,res)=>{
 try{
  const url=new URL(req.url,'http://127.0.0.1');counts.set(url.pathname,(counts.get(url.pathname)||0)+1);
  let data;
  if(url.pathname==='/api/cages')data={cage_ids:['CAGE-A','CAGE-B'],default_cage_id:'CAGE-A'};
  else if(url.pathname==='/api/air')data=packet(url.searchParams.get('cage_id')||'CAGE-A');
  else if(url.pathname==='/history-flow')data=historyFlow;
  else if(['/saas/a','/saas/b','/slow'].includes(url.pathname)){
   data=packet(url.pathname==='/saas/b'?'CAGE-B':'CAGE-A',false);
   if(url.pathname==='/slow')await delay(1000);
  }else if(url.pathname==='/'||url.pathname==='/app.js'){
   const body=await readFile(new URL(url.pathname==='/'?'index.html':'app.js',web));
   res.writeHead(200,{'Content-Type':url.pathname==='/'?'text/html; charset=utf-8':'application/javascript'});res.end(body);return;
  }else{res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(data));
 }catch{res.destroy();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const profile=await mkdtemp('/tmp/habitat-air-browser-test-');
const browser=spawn(process.env.HABITAT_CHROMIUM||'/usr/bin/chromium',[
 '--headless','--no-gl-override','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader',
 '--password-store=basic','--js-flags=','--no-first-run','--no-default-browser-check','--no-proxy-server',
 '--disable-background-networking','--disable-sync','--disable-extensions','--window-size=900,800',
 '--remote-debugging-port=0',`--user-data-dir=${profile}`,origin],{stdio:['ignore','ignore','pipe']});
let log='',socket;browser.stderr.on('data',b=>{log=(log+b).slice(-2000)});
try{
 let port;
 for(let i=0;i<100;i++){try{port=Number((await readFile(`${profile}/DevToolsActivePort`,'utf8')).split('\n')[0]);break;}catch{await delay(100);}}
 assert.ok(port,'browser endpoint unavailable');
 const pages=await(await fetch(`http://127.0.0.1:${port}/json`)).json();
 const page=pages.find(p=>p.type==='page'&&p.url.startsWith(origin));assert.ok(page);
 socket=new WebSocket(page.webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
 let sequence=0;const pending=new Map(),errors=[];
 socket.onmessage=e=>{const r=JSON.parse(e.data);if(r.method==='Runtime.exceptionThrown')errors.push(r.params.exceptionDetails.text);
  if(r.id){const task=pending.get(r.id);pending.delete(r.id);if(task){r.error?task.reject(Error(r.error.message)):task.resolve(r.result);}}};
 socket.onclose=()=>{for(const task of pending.values())task.reject(Error('browser closed'));pending.clear();};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(Error('timeout '+method));},12000);
  pending.set(id,{resolve:r=>{clearTimeout(timer);resolve(r);},reject:e=>{clearTimeout(timer);reject(e);}});socket.send(JSON.stringify({id,method,params}));});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value;};
 const until=async expression=>{for(let i=0;i<100;i++){if(await evaluate(expression))return;await delay(100);}throw Error('condition failed: '+expression);};
 await call('Runtime.enable');
 await until("document.getElementById('air-app')?.dataset.rendered === '1'");
 assert.equal(await evaluate("document.getElementById('T1').textContent"),'22.00');
 assert.match(await evaluate("document.getElementById('source-mode').textContent"),/실시간 센서/);
 assert.match(await evaluate("document.getElementById('source-host').textContent"),new RegExp(String(server.address().port)));
 await evaluate("document.getElementById('cage-select').value='CAGE-B';document.getElementById('cage-select').dispatchEvent(new Event('change'))");
 await until("document.getElementById('T1').textContent === '29.00'");
 await evaluate("window.HabitatAirView.setEndpoint('/saas/a')");
 await until("document.getElementById('T1').textContent === '22.00'");
 assert.equal(await evaluate("document.getElementById('baseline-option').hidden"),true);
 assert.equal(await evaluate("document.getElementById('cage-picker').hidden"),true);
 await evaluate("window.HabitatAirView.setEndpoint('/slow')");
 assert.equal(await evaluate("document.getElementById('T1').textContent"),'—');
 await delay(100);await evaluate("window.HabitatAirView.setEndpoint('/saas/b')");
 await until("document.getElementById('T1').textContent === '29.00'");
 await delay(1200);assert.equal(await evaluate("document.getElementById('cage').textContent"),'CAGE-B');
 const invalid=await evaluate("['//external.invalid/path','/\\\\external.invalid/path','/api/x?token=dummy','/api/x#fragment',null].map(v=>{try{window.HabitatAirView.setEndpoint(v);return false;}catch{return true;}})");
 assert.deepEqual(invalid,[true,true,true,true,true]);
 const before=counts.get('/saas/b');
 await evaluate("for(let i=0;i<10;i++)window.HabitatAirView.setEndpoint('/saas/b')");
 await delay(1500);assert.ok(counts.get('/saas/b')-before<=2,'duplicate polling loops');
 const canvas=await evaluate("document.getElementById('volume').toDataURL()");
 await evaluate("document.getElementById('right').click()");
 assert.notEqual(await evaluate("document.getElementById('volume').toDataURL()"),canvas);

 // Historical provenance and missing original receipt time must remain visible,
 // including while the device is offline. No synthetic data reaches MQTT/SaaS.
 await evaluate("window.HabitatAirView.setEndpoint('/history-flow')");
 await until("document.getElementById('air-app').dataset.rendered === '3'");
 assert.equal(await evaluate("document.getElementById('T1').textContent"),'22.00');
 assert.equal(await evaluate("document.getElementById('empty').hidden"),true);
 assert.equal(await evaluate("document.getElementById('stage').dataset.held"),'true');
 assert.match(await evaluate("document.getElementById('source-mode').textContent"),/저장된 센서 기록/);
 assert.match(await evaluate("document.getElementById('status-title').textContent"),/저장된 측정 기록/);
 assert.equal(await evaluate("document.getElementById('sample-count').textContent"),'기록 복원 3건 · 이후 수신 0건');
 assert.equal(await evaluate("document.getElementById('receipt-age').textContent"),'수신 시각 기록 없음');
 assert.match(await evaluate("document.getElementById('source-age').textContent"),/측정 후 60[0-9]초/);
 const originalTime=await evaluate("document.getElementById('sample-time').textContent");
 historyFlow={...historyFlow,status:'offline'};
 await until("document.getElementById('status').dataset.state === 'offline'");
 assert.match(await evaluate("document.getElementById('source-mode').textContent"),/저장된 센서 기록/);
 assert.equal(await evaluate("document.getElementById('empty').hidden"),true);

 // A new measurement with identical temperatures still advances the display.
 const freshPacket=packet('CAGE-A');
 historyFlow={...freshPacket,data_origin:'mqtt',history_samples:3,live_samples:1,accepted_samples:4};
 await until("document.getElementById('air-app').dataset.rendered === '4'");
 assert.equal(await evaluate("document.getElementById('T1').textContent"),'22.00');
 assert.equal(await evaluate("document.getElementById('stage').dataset.held"),'false');
 assert.match(await evaluate("document.getElementById('source-mode').textContent"),/실시간 센서/);
 assert.equal(await evaluate("document.getElementById('sample-count').textContent"),'기록 복원 3건 · 이후 수신 1건');
 assert.notEqual(await evaluate("document.getElementById('sample-time').textContent"),originalTime);
 assert.match(await evaluate("document.getElementById('receipt-age').textContent"),/수신 후 [0-9]+초/);

 // Advance the synthetic server clock: this source timestamp is newer than the
 // last sample, but the next message arrives 55 seconds after it was measured.
 const lateStamp=new Date(Date.parse(freshPacket.sampled_at)+5000).toISOString();
 const lateReceipt=new Date(Date.parse(lateStamp)+55000).toISOString();
 historyFlow={...packet('CAGE-A'),data_origin:'mqtt',status:'stale',fresh:false,held:true,
 sampled_at:lateStamp,received_at_utc:lateReceipt,generated_at:lateReceipt,
 age_seconds:0,source_age_seconds:55,history_samples:3,live_samples:2,accepted_samples:5,
 color_range_c:[22,24],sensors:historyFlow.sensors.map(sensor=>({...sensor,value_c:23.25})),
 field:{values_c:Array(12000).fill(23.25)},baseline:{values_c:Array(12000).fill(23.25)}};
 await until("document.getElementById('air-app').dataset.rendered === '5'");
 assert.equal(await evaluate("document.getElementById('T1').textContent"),'23.25');
 assert.equal(await evaluate("document.getElementById('stage').dataset.held"),'true');
 assert.equal(await evaluate("document.getElementById('empty').hidden"),true);
 assert.match(await evaluate("document.getElementById('source-mode').textContent"),/마지막 센서 측정/);
 assert.equal(await evaluate("document.getElementById('status').dataset.state"),'stale');
 assert.equal(await evaluate("document.getElementById('sample-count').textContent"),'기록 복원 3건 · 이후 수신 2건');
 await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await delay(300);
 assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false);
 assert.equal(await evaluate("document.getElementById('render-error').textContent"),'');
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,synthetic_only:true,local_cage_switch:true,saas_cage_switch:true,
  late_response_ignored:true,baseline_optional:true,no_duplicate_polls:true,rotation:true,mobile:true,
  history_visible:true,history_receipt_unknown:true,history_held_offline:true,equal_value_live_update:true,late_measurement_visible:true}));
}catch(error){console.error(error.message,log);process.exitCode=1;}
finally{
 if(socket)socket.close();browser.kill('SIGTERM');
 if(browser.exitCode===null)await Promise.race([new Promise(r=>browser.once('exit',r)),delay(3000)]);
 if(browser.exitCode===null)browser.kill('SIGKILL');
 await new Promise(resolve=>server.close(resolve));
 await rm(profile,{recursive:true,force:true});
}
