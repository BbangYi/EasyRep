import { useMemo, useState } from 'react';
import { Layers3 } from 'lucide-react';
import type { Cage, HistoryData, Point, SpatialLayout } from './live-data';
import { dateTime } from './live-data';
import { Empty, Notice, Panel, QueryNotice } from './live-panels';
import { useLiveQuery } from './use-live-query';
import { spatialHistory, spatialReadings } from './spatial-data';
import { SpatialVolume } from './spatial-volume';
import { temperatureGradient, temperatureProfile } from './spatial-temperature-profile';

export function SpatialEnvironment({cage}:{cage:Cage}) {
  if(!cage.spatialLayout){
    const temperatureSensors=cage.sensors.filter(sensor=>sensor.unit==='degC').map(sensor=>sensor.id);
    return <Panel title="공간 추정" icon={Layers3}>
      <Empty>공간 배치 정보가 없습니다.</Empty>
      <dl className="live-description live-spatial-missing-layout"><dt>수신 온도 센서</dt><dd>{temperatureSensors.length ? temperatureSensors.join(" · ") : "미수신"}</dd><dt>계산에 필요한 정보</dt><dd>사육장 가로·세로·높이, 센서 설치 좌표</dd></dl>
      <p className="live-note">사육장 치수와 센서 위치를 연결하면, 수신 중인 실측값으로 공간 온도를 계산합니다.</p>
    </Panel>;
  }
  return <SpatialWorkspace key={`${cage.id}:${cage.spatialLayout.id}`} cage={cage} layout={cage.spatialLayout} />;
}

function SpatialWorkspace({cage,layout}:{cage:Cage;layout:SpatialLayout}) {
  const [hours,setHours]=useState(6),[selected,setSelected]=useState<string|null>(null);
  const [{anchor,before},setPage]=useState({anchor:'',before:''});
  const [opacity,setOpacity]=useState(87),[showField,setShowField]=useState(true);
  const query=useLiveQuery<HistoryData>(`/api/enclosures/${encodeURIComponent(cage.id)}/history/?hours=${hours}${anchor?`&end=${encodeURIComponent(anchor)}`:''}${before?`&before=${encodeURIComponent(before)}`:''}`,60000);
  const points=useMemo(()=>spatialHistory(query.data?.points??[],layout),[query.data,layout]);
  const selectedIndex=selected===null?points.length-1:Math.max(0,points.findIndex(p=>(p.id??p.eventId)===selected));
  const point=points[selectedIndex];
  const currentReadings=useMemo(()=>Object.fromEntries(cage.sensors.filter(s=>s.unit==='degC').map(s=>[s.id,{value:s.value,quality:s.quality}])),[cage.sensors]);
  const readings:Point['readings']=point?.readings??(cage.source==='sensor'&&!cage.configurationChanged?currentReadings:{});
  const sensors=useMemo(()=>spatialReadings(layout,readings),[layout,readings]);
  const measuredAt=point?.at??cage.sampledAt;
  const profile=useMemo(()=>temperatureProfile(cage.species,measuredAt),[cage.species,measuredAt]);
  const range=useMemo<[number,number]>(()=>{
    if(profile)return profile.range;
    const values=points.flatMap(point=>spatialReadings(layout,point.readings).map(sensor=>sensor.value));
    if(!values.length)values.push(...sensors.map(sensor=>sensor.value));
    return values.length?[Math.floor(Math.min(...values)*2)/2-1,Math.ceil(Math.max(...values)*2)/2+1]:[20,25];
  },[points,layout,sensors,profile]);
  const gap=point&&selectedIndex>0?(Date.parse(point.at)-Date.parse(points[selectedIndex-1].at))/1000:0;
  function changePeriod(value:number){setHours(value);setPage(page=>({...page,before:''}));setSelected(null);}
  function olderPage(){
    const data=query.data;
    if(!data)return;
    const boundary=data.olderThan??data.points[0]?.at;
    if(!data.next&&!boundary)return;
    // Page through raw records; spatial filters must not change the API boundary.
    setPage({anchor:data.next?(boundary??data.end):new Date(Date.parse(boundary!)-1).toISOString(),before:data.next||''});
    setSelected(null);
  }
  return <Panel title="사육장 공기 온도 · 공간 추정" icon={Layers3} className="live-spatial-panel" action={<span className="live-source">센서 실측 기반 · 등록 배치</span>}>
    <div className="live-spatial-toolbar">
      <label>조회 기간 <select value={hours} onChange={e=>changePeriod(Number(e.target.value))}><option value={1}>1시간</option><option value={6}>6시간</option><option value={24}>24시간</option></select></label>
      <div className="live-spatial-timestamp">
        {measuredAt?<time dateTime={measuredAt}>선택 측정 {dateTime(measuredAt)} KST</time>:<span>측정값 없음</span>}
        {!query.data&&!query.error&&!query.offline&&<span role="status">이력을 불러오는 중입니다…</span>}
      </div>
    </div>
    <div className="live-spatial-layout">
    <div className="live-spatial-sidebar">
    {cage.source!=='sensor'&&<Notice>실제 센서 출처가 확인된 측정값만 공간 추정에 사용합니다.</Notice>}
    <QueryNotice query={query}/>{query.data&&<div className="live-spatial-history">
      <label htmlFor="spatial-time">개별 측정 시각 · {points.length.toLocaleString()}건</label>
      <input id="spatial-time" type="range" min={0} max={Math.max(0,points.length-1)} value={Math.max(0,selectedIndex)} disabled={!points.length} aria-valuetext={point?`${dateTime(point.at)} KST`:'측정 없음'} onChange={e=>{const p=points[Number(e.target.value)];setSelected(p.id??p.eventId);}}/>
      <div><span>{points[0]?dateTime(points[0].at):'이력 없음'}</span><span>{points.at(-1)?dateTime(points.at(-1)!.at):''}</span></div>
      {query.data.points.length!==points.length&&<p className="live-note">가상 데이터·다른 센서 배치의 기록 {query.data.points.length-points.length}건 제외</p>}
      {gap>cage.staleAfterSeconds&&<p className="live-note">이전 측정과 {Math.round(gap).toLocaleString()}초 간격입니다. 빈 시간의 값을 생성하지 않습니다.</p>}
      {query.data.truncated&&<p className="live-note">이번 조회는 최근 {query.data.limit.toLocaleString()}건까지 표시합니다.</p>}
      {(query.data.next||query.data.olderThan||query.data.points[0])&&<button onClick={olderPage}>이전 기록 보기</button>}
      {!points.length&&<Empty>선택한 기간에 이 배치로 표시할 실측 기록이 없습니다.</Empty>}
    </div>}
    <div className="live-spatial-readings">{layout.sensors.map(sensor=>{const reading=sensors.find(s=>s.id===sensor.id);return <div key={sensor.id}><span>{sensor.id} · {sensor.label}</span><strong>{reading?reading.value.toFixed(2):'—'} <small>°C</small></strong><small>{reading?'실측':'유효 측정 없음'}</small></div>;})}</div>
      <details className="live-spatial-options"><summary>표시 설정</summary><div className="live-spatial-controls"><label>표시 방식 <select value={showField?'field':'sensors'} onChange={e=>setShowField(e.target.value==='field')}><option value="field">온도 보간 + 센서 실측</option><option value="sensors">센서 실측만</option></select></label><label>불투명도 {opacity}%<input type="range" aria-label="공간 추정 불투명도" min={10} max={100} value={opacity} onChange={e=>setOpacity(Number(e.target.value))}/></label></div>
</details>
    <a href={`#history/${cage.id}`}>기간별 종합 이력 보기</a>
    <details className="live-spatial-assumptions"><summary>센서 위치와 추정 조건</summary><p>{layout.source}</p><ul>{layout.sensors.map(s=><li key={s.id}>{s.id}: ({s.positionCm.join(', ')})cm</li>)}</ul><p>원점은 안쪽 앞·왼쪽 바닥입니다. 가까운 센서에 더 큰 가중치를 주는 거리 기반 보간이며 공기 흐름·장애물은 반영하지 않습니다. 센서 사이의 색상을 실측값이나 검증된 온도장으로 해석하지 마세요.</p></details>
    </div>
    <div className="live-spatial-stage">

      <SpatialVolume layout={layout} sensors={sensors} range={range} stops={profile?.stops} opacity={opacity/100} showField={showField}/>
      {showField&&sensors.length<3&&<p>유효한 온도 센서 3개가 있어야 공간 색상을 표시합니다.</p>}
      <div className="live-spatial-scale" aria-hidden="true" style={profile?{background:temperatureGradient(profile)}:undefined}/><div className="live-spatial-scale-labels"><span>{range[0].toFixed(1)}°C</span>{profile?<strong>{profile.label}</strong>:<span>{((range[0]+range[1])/2).toFixed(1)}°C</span>}<span>{range[1].toFixed(1)}°C</span></div>
      {profile&&<p className="live-spatial-boundary">{profile.boundary}</p>}
      <p>점은 센서 실측값, 반투명 공간은 온도 추정값입니다.</p>
    </div>
    </div>

  </Panel>;
}
