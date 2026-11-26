/* R12 whole-volume renderer, connected to the existing BB6 receiver. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), canvas=$('volume'), overlay=$('overlay');
  const state={method:'field',opacity:68,yaw:4.12,pitch:.30};
  let snapshot=null,gl,program,texture,palette,textureKey='',renderFailed=false;
  let configuredEndpoint=$('air-app').getAttribute('data-air-endpoint');
  let endpoint='/api/air',endpointError=null,selectedCage=new URLSearchParams(location.search).get('cage_id');
  let selectionVersion=0,pollTimer,snapshotReceivedAt=0,activeRequest=null;
  $('source-host').textContent='연결 서버 '+location.host;
  function checkedEndpoint(value){
    if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||/[\\\x00-\x20]/.test(value))throw Error('조회 주소는 같은 서버의 상대 경로여야 합니다.');
    const target=new URL(value,location.origin);
    if(target.origin!==location.origin||target.username||target.password||target.search||target.hash||value.includes('?')||value.includes('#'))throw Error('조회 주소에는 다른 서버, 인증정보, 쿼리 또는 조각을 사용할 수 없습니다.');
    return target.pathname;
  }
  try{
    if(configuredEndpoint!==null)endpoint=checkedEndpoint(configuredEndpoint);
  }catch(error){endpointError=error.message;}
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const dot=(a,b)=>a.reduce((v,x,i)=>v+x*b[i],0);
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const norm=a=>{const l=Math.hypot(...a);return a.map(x=>x/l);};
  function basis(){const eye=[Math.cos(state.pitch)*Math.sin(state.yaw),Math.cos(state.pitch)*Math.cos(state.yaw),Math.sin(state.pitch)];const right=norm(cross(eye.map(x=>-x),[0,0,1]));return {eye,right,up:norm(cross(right,eye.map(x=>-x)))};}
  function rgb(name){const c=document.createElement('canvas').getContext('2d');c.fillStyle=getComputedStyle(document.documentElement).getPropertyValue(name).trim();c.fillRect(0,0,1,1);return [...c.getImageData(0,0,1,1).data].slice(0,3).map(x=>x/255);}
  function colors(){palette=['--low','--mid','--high'].map(rgb);}
  function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error('3D 그래픽 초기화에 실패했습니다.');return s;}
  function initialize(){
    gl=canvas.getContext('webgl2',{alpha:true,premultipliedAlpha:true,antialias:false,preserveDrawingBuffer:true});
    if(!gl)throw Error('이 브라우저에서는 3D 표시를 지원하지 않습니다. 최신 Chrome 또는 Edge에서 열어 주세요.');
    const vs=`#version 300 es
    in vec2 position;out vec2 uv;
    void main(){uv=position;gl_Position=vec4(position,0.,1.);}`;
    const fs=`#version 300 es
    precision highp float;precision highp sampler3D;
    in vec2 uv;out vec4 outColor;
    uniform sampler3D volume;uniform vec3 eye,right,up,c0,c1,c2;uniform float aspect,density;
    vec3 heat(float t){return t<.5?mix(c0,c1,t*2.):mix(c1,c2,(t-.5)*2.);}
    void main(){
      vec3 origin=eye*.8+right*uv.x*.22*aspect+up*uv.y*.22,direction=-eye;
      vec3 inv=1./(direction+vec3(1.e-8));
      vec3 a=(vec3(-.1,-.1,-.15)-origin)*inv,b=(vec3(.1,.1,.15)-origin)*inv;
      vec3 lo=min(a,b),hi=max(a,b);
      float nearT=max(max(lo.x,lo.y),lo.z),farT=min(min(hi.x,hi.y),hi.z);
      if(farT<=nearT){outColor=vec4(0.);return;}
      float ds=(farT-nearT)/112.,alpha=1.-exp(-density*ds),trans=1.;vec3 color=vec3(0.);
      for(int i=0;i<112;i++){
        vec3 p=origin+direction*(nearT+(float(i)+.5)*ds);
        float t=texture(volume,(p+vec3(.1,.1,.15))/vec3(.2,.2,.3)).r;
        color+=trans*alpha*heat(t);trans*=1.-alpha;
      }
      outColor=vec4(color,1.-trans);
    }`;
    program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,vs));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fs));gl.linkProgram(program);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('3D 그래픽을 시작할 수 없습니다.');
    gl.useProgram(program);const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
    const p=gl.getAttribLocation(program,'position');gl.enableVertexAttribArray(p);gl.vertexAttribPointer(p,2,gl.FLOAT,false,0,0);
    texture=gl.createTexture();gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_3D,texture);
    for(const side of [gl.TEXTURE_WRAP_S,gl.TEXTURE_WRAP_T,gl.TEXTURE_WRAP_R])gl.texParameteri(gl.TEXTURE_3D,side,gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_3D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT,1);gl.uniform1i(gl.getUniformLocation(program,'volume'),0);colors();
  }
  function upload(){
    if(!snapshot?.field||renderFailed)return;
    const key=[snapshot.cage_id,snapshot.message_id,snapshot.generated_at,snapshot.accepted_samples,snapshot.sampled_at,state.method,...snapshot.color_range_c].join('|');if(key===textureKey)return;
    const [low,high]=snapshot.color_range_c;
    // Display colors use 8-bit precision; API temperatures retain their numeric precision.
    const bytes=Uint8Array.from(snapshot[state.method].values_c,v=>Math.round(clamp((v-low)/(high-low),0,1)*255));
    gl.bindTexture(gl.TEXTURE_3D,texture);gl.texImage3D(gl.TEXTURE_3D,0,gl.R8,20,20,30,0,gl.RED,gl.UNSIGNED_BYTE,bytes);textureKey=key;
  }
  function project(p,b,w,h){const c=[p[0]-.1,p[1]-.1,p[2]-.15];return [w/2+dot(c,b.right)*h/.44,h/2-dot(c,b.up)*h/.44];}
  function svg(tag,attrs,text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;overlay.appendChild(e);return e;}
  function overlayDraw(b,w,h){
    overlay.replaceChildren();overlay.setAttribute('viewBox',`0 0 ${w} ${h}`);
    const v=[];for(const z of [0,.3])for(const y of [0,.2])for(const x of [0,.2])v.push([x,y,z]);
    for(const[i,j]of [[0,1],[0,2],[1,3],[2,3],[4,5],[4,6],[5,7],[6,7],[0,4],[1,5],[2,6],[3,7]]){const a=project(v[i],b,w,h),c=project(v[j],b,w,h);svg('line',{x1:a[0],y1:a[1],x2:c[0],y2:c[1],stroke:'var(--fg)','stroke-width':1.2,opacity:.4});}
    const labels=[];
    for(const sensor of snapshot.sensors){
      const p=project(sensor.xyz_m,b,w,h),anchor=p[0]>w*.58?'end':'start';let x=p[0]+(anchor==='end'?-12:12),y=p[1]-12;
      x=clamp(x,anchor==='end'?126:4,anchor==='end'?w-4:w-126);
      for(const old of labels)if(Math.abs(y-old.y)<24&&Math.abs(x-old.x)<145)y+=26;
      y=clamp(y,18,h-16);labels.push({x,y});
      svg('text',{x,y,'text-anchor':anchor,'paint-order':'stroke',stroke:'var(--panel)','stroke-width':3,'stroke-linejoin':'round'},`${sensor.id} ${sensor.value_c.toFixed(2)}°C`);
    }
    for(const sensor of snapshot.sensors){const p=project(sensor.xyz_m,b,w,h);svg('circle',{cx:p[0],cy:p[1],r:6,fill:'var(--panel)',stroke:'var(--fg)','stroke-width':2});}
  }
  function draw(){
    if(!program||!snapshot?.field||renderFailed)return;
    const{width:w,height:h}=canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,1.5);
    canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);gl.useProgram(program);
    const b=basis();for(const name of ['eye','right','up'])gl.uniform3fv(gl.getUniformLocation(program,name),b[name]);
    palette.forEach((c,i)=>gl.uniform3fv(gl.getUniformLocation(program,'c'+i),c));
    gl.uniform1f(gl.getUniformLocation(program,'aspect'),w/h);gl.uniform1f(gl.getUniformLocation(program,'density'),-Math.log(1-state.opacity/100)/.25);
    gl.drawArrays(gl.TRIANGLES,0,6);overlayDraw(b,w,h);$('air-app').dataset.rendered=String(snapshot.accepted_samples);
  }
  function validate(data){
    if(data.schema_version!==1||!['live','replay'].includes(data.source_mode)||typeof data.cage_id!=='string'||!Array.isArray(data.sensors)||data.sensors.length!==3)throw Error('지원하지 않는 수신 형식입니다.');
    if(configuredEndpoint===null&&selectedCage!==null&&data.cage_id!==selectedCage)throw Error('선택한 사육장과 응답이 다릅니다.');
    if(new Set(data.sensors.map(s=>s.id)).size!==3||!data.sensors.every(s=>['T1','T2','T3'].includes(s.id)&&s.xyz_m?.length===3&&s.xyz_m.every((v,i)=>Number.isFinite(v)&&v>=0&&v<=data.dimensions_m?.[i])))throw Error('센서 위치와 값을 확인해 주세요.');
    if(!data.field)return;
    if(JSON.stringify(data.grid?.shape_zyx)!=='[30,20,20]'||JSON.stringify(data.dimensions_m)!=='[0.2,0.2,0.3]')throw Error('사육장 격자 설정을 확인해 주세요.');
    const range=data.color_range_c;if(!Array.isArray(range)||range.length!==2||!range.every(Number.isFinite)||range[1]<=range[0])throw Error('온도 척도가 올바르지 않습니다.');
    for(const method of data.baseline==null?['field']:['field','baseline'])if(!Array.isArray(data[method]?.values_c)||data[method].values_c.length!==12000||!data[method].values_c.every(Number.isFinite))throw Error('온도 추정 자료를 확인해 주세요.');
    if(!data.sensors.every(s=>Number.isFinite(s.value_c)))throw Error('센서 위치와 값을 확인해 주세요.');
  }
  const statusText={waiting:['BB6 측정값 대기','저장된 기록과 새 측정값을 확인하고 있습니다.'],history:['저장된 측정 기록 · 새 측정 대기','표시된 측정 시각의 기록으로 계산한 온도 추정입니다. 새 측정이 들어오면 갱신합니다.'],live:['실시간 수신 중','BB6의 새 측정값을 반영하고 있습니다.'],replay:['CSV 기록 재생','과거 측정 기록을 재생하고 있습니다. 실시간 장치 연결이 아닙니다.'],stale:['수신 지연 · 마지막 측정 표시','표시된 측정 시각의 추정입니다. 늦게 도착한 측정도 반영하며 현재 온도로 단정하지 않습니다.'],held:['측정 확인 필요 · 마지막 화면 보관','센서값 또는 측정 시각을 확인해 주세요. 새 유효값 수신 후 갱신합니다.'],offline:['BB6 연결 끊김 · 마지막 화면 보관','BB6의 전원과 통신 연결을 확인해 주세요.'],replay_complete:['CSV 재생 완료','마지막 기록의 온도 추정입니다.'],disconnected:['수신 프로그램 연결 끊김','마지막 화면을 보관합니다. Pi 수신 프로그램의 실행 상태를 확인해 주세요.']};
  function showSource(){
    if(!snapshot)return;
    const source=snapshot.source_mode==='replay'?'CSV 기록 재생':snapshot.data_origin==='history'?'저장된 센서 기록':snapshot.fresh===true&&$('status').dataset.state==='live'?'실시간 센서':snapshot.sampled_at?'마지막 센서 측정':'센서 수신 대기';
    $('source-mode').textContent='데이터 출처 · '+source;
  }
  function showStatus(code){const pair=statusText[code]||statusText.held;$('status').dataset.state=code;$('status-title').textContent=pair[0];$('status-detail').textContent=pair[1];$('stage').dataset.held=String(!['live','replay'].includes(code));showSource();}
  function refreshAges(){
    if(!snapshot)return;
    const elapsed=Math.max(0,(performance.now()-snapshotReceivedAt)/1000);
    const age=(value,stamp)=>Number.isFinite(value)?value+elapsed:(Number.isFinite(Date.parse(stamp))?(Date.now()-Date.parse(stamp))/1000:null);
    const sourceAge=age(snapshot.source_age_seconds,snapshot.sampled_at),receiptAge=age(snapshot.age_seconds,snapshot.received_at_utc);
    const label=value=>value===null?'—':value<0?'시각 확인 필요':Math.floor(value)+'초';
    $('source-age').textContent='측정 후 '+label(sourceAge);$('receipt-age').textContent=snapshot.data_origin==='history'&&receiptAge===null?'수신 시각 기록 없음':'수신 후 '+label(receiptAge);
    const limit=Number.isFinite(snapshot.stale_after_s)&&snapshot.stale_after_s>0?snapshot.stale_after_s:30;
    if(['live','replay'].includes($('status').dataset.state)&&((receiptAge!==null&&receiptAge>limit)||(snapshot.source_mode==='live'&&sourceAge!==null&&(sourceAge>limit||sourceAge < -5))))showStatus('stale');
  }
  function update(data){
    validate(data);snapshot=data;snapshotReceivedAt=performance.now();showStatus(data.status);$('cage').textContent=data.cage_id;
    $('stage').dataset.held=String(data.held===true||data.fresh===false||!['live','replay'].includes(data.status));
    if(data.source_mode==='replay'&&!['replay','replay_complete'].includes(data.status))$('status-title').textContent='CSV 재생 · '+$('status-title').textContent;
    $('baseline-option').disabled=$('baseline-option').hidden=!data.baseline;
    if(!data.baseline&&state.method==='baseline'){state.method='field';$('method').value='field';textureKey='';}
    for(const sensor of data.sensors)if(['T1','T2','T3'].includes(sensor.id))$(sensor.id).textContent=Number.isFinite(sensor.value_c)?sensor.value_c.toFixed(2):'—';
    $('sample-time').textContent='측정 시각 '+(data.sampled_at?new Date(data.sampled_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})+' (한국시간)':'—');
    const counts=data.source_mode==='live'&&Number.isInteger(data.history_samples)&&data.history_samples>=0&&Number.isInteger(data.live_samples)&&data.live_samples>=0;
    $('sample-count').textContent=counts?`기록 복원 ${data.history_samples}건 · 이후 수신 ${data.live_samples}건`:Number.isInteger(data.accepted_samples)?`유효 수신 ${data.accepted_samples}회`:'서버에 저장된 마지막 측정';
    refreshAges();
    $('positions').replaceChildren(...data.sensors.map(s=>{const li=document.createElement('li');li.textContent=`${s.id} ${s.label} · (${s.xyz_m.map(v=>(v*100).toFixed(1)).join(', ')})cm`;return li;}));
    if(data.field){const[l,h]=data.color_range_c;['range-low','range-mid','range-high'].forEach((id,i)=>$(id).textContent=[l,(l+h)/2,h][i].toFixed(1)+'°C');$('empty').hidden=true;upload();draw();}
    else{textureKey='';overlay.replaceChildren();if(gl&&!renderFailed)gl.clear(gl.COLOR_BUFFER_BIT);$('empty').hidden=false;['range-low','range-mid','range-high'].forEach(id=>$(id).textContent='—');}
  }
  function clearSelection(){
    snapshot=null;textureKey='';overlay.replaceChildren();if(gl&&!renderFailed)gl.clear(gl.COLOR_BUFFER_BIT);
    $('air-app').removeAttribute('data-rendered');$('empty').hidden=false;$('cage').textContent=selectedCage??'연결 확인 중';
    for(const key of ['T1','T2','T3','range-low','range-mid','range-high'])$(key).textContent='—';
    $('positions').replaceChildren();$('sample-time').textContent='측정 시각 —';$('sample-count').textContent='유효 수신 —';
    $('source-age').textContent='측정 후 —';$('receipt-age').textContent='수신 후 —';$('source-mode').textContent='출처 확인 중';showStatus('waiting');
  }
  function cancelSelection(){selectionVersion++;clearTimeout(pollTimer);activeRequest?.abort();}
  async function readJSON(target){
    activeRequest?.abort();const controller=new AbortController();activeRequest=controller;
    const timeout=setTimeout(()=>controller.abort(),4000);
    try{
      const response=await fetch(target,{cache:'no-store',credentials:'same-origin',redirect:'error',signal:controller.signal});
      if(!response.ok)throw Error(response.status===404?'선택한 사육장의 온도 화면이 없습니다.':'수신 프로그램 응답 오류');
      return await response.json();
    }finally{clearTimeout(timeout);if(activeRequest===controller)activeRequest=null;}
  }
  async function loadCages(){
    if(configuredEndpoint!==null)return;
    const version=selectionVersion,data=await readJSON('/api/cages');
    if(version!==selectionVersion)return;
    if(!Array.isArray(data.cage_ids)||!data.cage_ids.length||data.cage_ids.some(id=>typeof id!=='string'||!id)||new Set(data.cage_ids).size!==data.cage_ids.length||!data.cage_ids.includes(data.default_cage_id))throw Error('사육장 목록 형식을 확인해 주세요.');
    if(selectedCage===null)selectedCage=data.default_cage_id;
    $('cage-select').replaceChildren(...data.cage_ids.map(id=>{const option=document.createElement('option');option.value=id;option.textContent=id;return option;}));
    $('cage-select').value=selectedCage;$('cage-picker').hidden=false;$('cage').textContent=selectedCage;
  }
  async function poll(){
    clearTimeout(pollTimer);const version=selectionVersion;
    const target=configuredEndpoint!==null?endpoint:'/api/air'+(selectedCage===null?'':'?cage_id='+encodeURIComponent(selectedCage));
    try{const data=await readJSON(target);if(version===selectionVersion)update(data);}
    catch(error){if(version===selectionVersion){showStatus('disconnected');$('status-detail').textContent=['TypeError','TimeoutError','AbortError'].includes(error.name)?statusText.disconnected[1]:error.message;}}
    finally{if(version===selectionVersion)pollTimer=setTimeout(poll,1000);}
  }
  function setEndpoint(value){
    const next=checkedEndpoint(value);
    if(configuredEndpoint!==null&&endpoint===next&&!endpointError)return;
    cancelSelection();configuredEndpoint=next;endpoint=next;endpointError=null;selectedCage=null;
    $('cage-picker').hidden=true;clearSelection();poll();
  }
  Object.defineProperty(window,'HabitatAirView',{value:Object.freeze({setEndpoint}),writable:false,configurable:false});
  try{initialize();}catch(error){renderFailed=true;$('render-error').textContent=error.message;$('empty').textContent='센서 숫자값은 계속 확인할 수 있습니다.';}
  $('method').addEventListener('change',e=>{state.method=e.target.value;upload();draw();});
  $('cage-select').addEventListener('change',e=>{selectedCage=e.target.value;cancelSelection();const target=new URL(location.href);target.searchParams.set('cage_id',selectedCage);history.replaceState(null,'',target);clearSelection();poll();});
  $('opacity').addEventListener('input',e=>{state.opacity=Number(e.target.value);$('opacity-label').textContent=state.opacity+'%';draw();});
  $('left').addEventListener('click',()=>{state.yaw-=Math.PI/8;draw();});$('right').addEventListener('click',()=>{state.yaw+=Math.PI/8;draw();});
  let pointer=null;
  canvas.addEventListener('pointerdown',e=>{pointer={id:e.pointerId,x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener('pointermove',e=>{if(pointer?.id!==e.pointerId)return;state.yaw-=(e.clientX-pointer.x)*.008;state.pitch=clamp(state.pitch+(e.clientY-pointer.y)*.006,-1.05,1.05);pointer.x=e.clientX;pointer.y=e.clientY;draw();});
  const finish=e=>{if(pointer?.id===e.pointerId)pointer=null;};canvas.addEventListener('pointerup',finish);canvas.addEventListener('pointercancel',finish);
  new ResizeObserver(draw).observe($('stage'));
  matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>{if(!renderFailed){colors();draw();}});
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();renderFailed=true;$('render-error').textContent='3D 화면 연결이 끊겼습니다. 페이지를 다시 열어 주세요.';});
  setInterval(refreshAges,1000);
  if(endpointError){showStatus('disconnected');$('status-detail').textContent=endpointError;}
  else{const version=selectionVersion;loadCages().catch(error=>{if(version===selectionVersion){showStatus('disconnected');$('status-detail').textContent=error.message;}}).finally(()=>{if(version===selectionVersion)poll();});}
})();
