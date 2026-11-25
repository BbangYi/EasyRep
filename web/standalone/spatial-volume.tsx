import { useEffect, useRef, useState } from 'react';
import type { SpatialLayout } from './live-data';
import { interpolateTemperature, projectPoint, type Position, type SpatialReading } from './spatial-data';
import { temperatureColor, type TemperatureStop } from './spatial-temperature-profile';

function draw(canvas: HTMLCanvasElement, layout: SpatialLayout, sensors: SpatialReading[], range: [number, number], stops: TemperatureStop[] | undefined, view: [number, number], opacity: number, showField: boolean) {
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (width <= 100 || height <= 72) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
  canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(ratio, ratio); ctx.clearRect(0, 0, width, height);
  const [w, d, h] = layout.dimensionsCm;
  const corners: Position[] = [[0,0,0],[w,0,0],[w,d,0],[0,d,0],[0,0,h],[w,0,h],[w,d,h],[0,d,h]];
  const projected = corners.map(p => projectPoint(p, layout.dimensionsCm, ...view));
  const xs = projected.map(p=>p.x), ys = projected.map(p=>p.y);
  const scale = Math.min((width - 100) / (Math.max(...xs)-Math.min(...xs)), (height - 72) / (Math.max(...ys)-Math.min(...ys)));
  const project = (p: Position) => { const point=projectPoint(p, layout.dimensionsCm, ...view); return {...point,x:width/2+point.x*scale,y:height/2+point.y*scale}; };
  const vertices = corners.map(project);
  const sorted = [...vertices].sort((a,b)=>a.x-b.x||a.y-b.y);
  type Vertex = typeof vertices[number];
  const cross = (a: Vertex,b: Vertex,c: Vertex) => (b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);
  const half = (points: Vertex[]) => { const out: Vertex[]=[]; for(const point of points){while(out.length>1 && cross(out[out.length-2],out[out.length-1],point)<=0)out.pop();out.push(point);}return out; };
  const hull=[...half(sorted).slice(0,-1),...half([...sorted].reverse()).slice(0,-1)];
  ctx.save(); ctx.beginPath(); hull.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y)); ctx.closePath();ctx.clip();
  if (showField && sensors.length >= 3) {
    const field = document.createElement('canvas');
    field.width=canvas.width;field.height=canvas.height;
    const fieldContext=field.getContext('2d')!;fieldContext.scale(ratio,ratio);
    const cells: {position: Position; value: number; depth: number}[]=[];
    for(let z=0;z<16;z++)for(let y=0;y<11;y++)for(let x=0;x<11;x++) {
      const position: Position=[w*x/10,d*y/10,h*z/15];
      cells.push({position,value:interpolateTemperature(position,sensors)!,depth:project(position).depth});
    }
    cells.sort((a,b)=>a.depth-b.depth);
    const radius=Math.max(w/10,d/10,h/15)*scale*1.05;
    for(const cell of cells) {
      const p=project(cell.position), rgb=temperatureColor(cell.value,range,stops);
      const gradient=fieldContext.createRadialGradient(p.x,p.y,0,p.x,p.y,radius);
      gradient.addColorStop(0,`rgba(${rgb},${opacity*.07})`);gradient.addColorStop(1,`rgba(${rgb},0)`);
      fieldContext.fillStyle=gradient;fieldContext.fillRect(p.x-radius,p.y-radius,radius*2,radius*2);
    }
    ctx.filter='blur(1px)';ctx.drawImage(field,0,0,width,height);ctx.filter='none';
  }
  ctx.restore();ctx.strokeStyle='#55756599';ctx.lineWidth=1.2;
  for(const [a,b] of [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]]) {
    ctx.beginPath();ctx.moveTo(vertices[a].x,vertices[a].y);ctx.lineTo(vertices[b].x,vertices[b].y);ctx.stroke();
  }
  const labels: {left:number;right:number;top:number;bottom:number}[]=[];
  for(const sensor of sensors) {
    const p=project(sensor.positionCm);
    ctx.beginPath();ctx.arc(p.x,p.y,5.5,0,Math.PI*2);ctx.fillStyle='#2a6548';ctx.fill();ctx.strokeStyle='#f8fbf5';ctx.lineWidth=2;ctx.stroke();
    ctx.font='600 14px system-ui, sans-serif';ctx.textAlign=p.x>width*.7?'right':'left';
    const x=p.x+(p.x>width*.7?-12:12), text=`${sensor.id} ${sensor.value.toFixed(2)}°C`;
    const textWidth=ctx.measureText(text).width;let y=p.y-12;
    const left=ctx.textAlign==='right'?x-textWidth:x, right=left+textWidth;
    for(let attempt=0;attempt<sensors.length;attempt++){
      if(!labels.some(label=>left<label.right+4 && right>label.left-4 && y-15<label.bottom+4 && y>label.top-4))break;
      y-=22;
    }
    labels.push({left,right,top:y-15,bottom:y});
    ctx.lineWidth=3;ctx.strokeStyle='#f8fbf5';ctx.strokeText(text,x,y);ctx.fillStyle='#1d4632';ctx.fillText(text,x,y);
  }
}

export function SpatialVolume({layout,sensors,range,stops,opacity,showField}: {layout:SpatialLayout;sensors:SpatialReading[];range:[number,number];stops?:TemperatureStop[];opacity:number;showField:boolean}) {
  const canvas=useRef<HTMLCanvasElement>(null);
  const [view,setView]=useState<[number,number]>([-.62,.28]);
  const drag=useRef<{x:number;y:number;view:[number,number]}|null>(null);
  const frame=useRef<number|null>(null);
  useEffect(()=>{const target=canvas.current;if(!target)return;const render=()=>draw(target,layout,sensors,range,stops,view,opacity,showField);render();const observer=new ResizeObserver(render);observer.observe(target);return()=>observer.disconnect();},[layout,sensors,range,stops,view,opacity,showField]);
  useEffect(()=>()=>{if(frame.current!==null)cancelAnimationFrame(frame.current);},[]);
  const rotate=(yaw:number,pitch=0)=>setView(v=>[v[0]+yaw,Math.max(-.65,Math.min(.8,v[1]+pitch))]);
  return <>
    <canvas ref={canvas} className="live-spatial-canvas" role="img" tabIndex={0} aria-label="사육장 3차원 온도 추정. 방향키 또는 아래 회전 버튼으로 회전할 수 있습니다. 센서 실측값은 위 목록에 표시됩니다."
      onKeyDown={e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();rotate(e.key==='ArrowLeft'?-.15:e.key==='ArrowRight'?.15:0,e.key==='ArrowUp'?.1:e.key==='ArrowDown'?-.1:0);}}}
      onPointerDown={e=>{drag.current={x:e.clientX,y:e.clientY,view};e.currentTarget.setPointerCapture(e.pointerId);}}
      onPointerMove={e=>{const start=drag.current;if(!start)return;const next:[number,number]=[start.view[0]+(e.clientX-start.x)*.008,Math.max(-.65,Math.min(.8,start.view[1]+(e.clientY-start.y)*.005))];if(frame.current!==null)cancelAnimationFrame(frame.current);frame.current=requestAnimationFrame(()=>{frame.current=null;setView(next);});}}
      onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}} onLostPointerCapture={()=>{drag.current=null;}} />
    <div className="live-spatial-rotate"><button onClick={()=>rotate(-.2)} aria-label="사육장 왼쪽으로 회전">↶ 회전</button><button onClick={()=>rotate(.2)} aria-label="사육장 오른쪽으로 회전">회전 ↷</button><button onClick={()=>setView([-.62,.28])}>정면 복귀</button><span>드래그하여 회전 · {layout.dimensionsCm.join(' × ')}cm</span></div>
  </>;
}
