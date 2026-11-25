import historyBoundary029 from "../public/presentation/er029-history-boundary-20261106.png?url";
import productionHistory029 from "../public/presentation/er029-production-history-20261106.jpg?url";
import { useState } from "react";
import type { BriefingSlide } from "./presentation-briefing-content";
import detection from "../public/presentation/detection-result-20261022.png?url";
import model from "../public/presentation/research-layout-20261105.jpg?url";
import periodControls from "../public/presentation/er020-period-controls.jpg?url";
import periodChart from "../public/presentation/er020-period-chart.jpg?url";
import spatialStage from "../public/presentation/er020-spatial-stage.jpg?url";
import spatialContext from "../public/presentation/er020-spatial-context.jpg?url";
import careDetail from "../public/presentation/er020-care-detail.jpg?url";

import periodControlsMobile from "../public/presentation/er020-period-controls-mobile.jpg?url";
import periodChartMobile from "../public/presentation/er020-period-chart-mobile.jpg?url";
import spatialStageMobile from "../public/presentation/er020-spatial-stage-mobile.jpg?url";
import spatialContextMobile from "../public/presentation/er020-spatial-context-mobile.jpg?url";
import careDetailMobile from "../public/presentation/er020-care-detail-mobile.jpg?url";

const mobileImages: Record<string, string> = { [periodControls]: periodControlsMobile, [periodChart]: periodChartMobile, [spatialStage]: spatialStageMobile, [spatialContext]: spatialContextMobile, [careDetail]: careDetailMobile };
const imageSizes: Record<string, [number, number]> = { [historyBoundary029]:[1440,1000], [productionHistory029]:[1478,1101], [detection]:[1024,576], [model]:[1280,720], [periodControls]:[721,44], [periodChart]:[721,270], [spatialStage]:[563,518], [spatialContext]:[962,90], [careDetail]:[480,320], [periodControlsMobile]:[240,167], [periodChartMobile]:[240,206], [spatialStageMobile]:[240,526], [spatialContextMobile]:[240,223], [careDetailMobile]:[320,800] };

// Each use is keyed by its slide, so a failed image never follows another slide.
export function EvidenceImage({ src, alt, className = "" }: { src: string; alt: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  const mobile = mobileImages[src];
  // New field evidence can be added independently of the older fixed-size captures.
  // Keep an explicit intrinsic fallback so one unregistered image cannot stop a slide.
  const [width, height] = imageSizes[src] ?? [1280, 720];
  const [mobileWidth, mobileHeight] = imageSizes[mobile ?? src] ?? [width, height];
  return failed ? <div className="er20-image-fallback" role="status"><strong>그림을 불러오지 못했습니다.</strong><p>{alt}</p><button onClick={event => {
    // Keep slide navigation reachable when the retry button is removed.
    event.currentTarget.closest(".briefing-slide")?.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
    setFailed(false);
  }}>그림 다시 보기</button></div>
    : <picture className={`er20-picture ${className}`}><source media="(max-width:560px)" srcSet={mobile ?? src} width={mobileWidth} height={mobileHeight} /><img src={src} width={width} height={height} alt={alt} onError={() => setFailed(true)} /></picture>;
}

function Situation({ kind }: { kind: "away" | "care" }) {
  return <svg viewBox="0 0 260 145" role="img" aria-label={kind === "away" ? "집을 비운 뒤 기록을 살펴보는 설계 상황" : "물그릇을 세척한 관리 행동의 설명 그림"}>
    {kind === "away" ? <g fill="none" stroke="currentColor" strokeWidth="4" strokeLinejoin="round"><path d="M24 71 85 20 147 71M41 58V126H130V58M76 126V86H102V126"/><circle cx="197" cy="72" r="38"/><path d="M197 47V73L216 84M16 133H243"/></g>
      : <g fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round"><ellipse cx="124" cy="86" rx="74" ry="18"/><path d="M50 86 65 124Q124 144 183 124L198 86M158 16C158 16 143 37 143 43a15 15 0 0 0 30 0c0-6-15-27-15-27ZM45 35V58M34 46H56M209 36V58M198 47H220"/></g>}
  </svg>;
}

const locations = [
  { id: "T1", label: "천장", position: [10, 10, 28] },
  { id: "T2", label: "앞·왼쪽", position: [2, 2, 8] },
  { id: "T3", label: "뒤·오른쪽", position: [18, 18, 8] },
];
// Match the registered 20 × 20 × 30 cm assumed layout; this is an explanatory view.
const project = ([x, y, z]: number[]) => [42 + x * 6 + y * 3, 300 - z * 7 - y * 2 + x * 1.5];
function PositionDrawing({ flat = false }: { flat?: boolean }) {
  const corners = [[0,0,0],[20,0,0],[20,20,0],[0,20,0],[0,0,30],[20,0,30],[20,20,30],[0,20,30]];
  return <svg className="er20-position" viewBox={flat ? "0 0 280 280" : "0 0 280 340"} role="img" aria-label={flat ? "2D 위치 도식. T1 중앙 천장, T2 앞 왼쪽, T3 뒤 오른쪽. 가정 배치." : "20×20×30cm 가정 배치 설명도. T1 천장, T2 앞 왼쪽, T3 뒤 오른쪽. 실제 설치 확인 전."}>
    {flat ? <rect x="34" y="28" width="210" height="215" fill="#e9eee3" stroke="currentColor" strokeWidth="2"/> : <>
      <polygon points={[0,1,2,3].map(i=>project(corners[i]).join(',')).join(' ')} fill="#d6dfce"/>
      <polygon points={[0,1,5,4].map(i=>project(corners[i]).join(',')).join(' ')} fill="#e4eadc"/>
      {[[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]].map(([a,b])=><line key={`${a}-${b}`} x1={project(corners[a])[0]} y1={project(corners[a])[1]} x2={project(corners[b])[0]} y2={project(corners[b])[1]} stroke="currentColor" strokeWidth="2"/>)}
    </>}
    {locations.map(({id,position})=>{const [x,y]=flat?[34+position[0]*10.5,243-position[1]*10.75]:project(position);return <g key={id}><circle cx={x} cy={y} r="8" fill="#294f3d" stroke="#fff" strokeWidth="2"/><text x={x+11} y={y-9} fill="currentColor" fontSize="24" fontWeight="700">{id}</text></g>;})}
    {flat && <text x="140" y="271" textAnchor="middle" fontSize="20" fill="currentColor">앞쪽</text>}
  </svg>;
}

const syntheticLabel = "합성 입력으로 재현한 실제 웹 · 실제 센서 자료 아님";
function PeriodEvidence() {
  return <figure className="er20-period"><figcaption>기간 선택과 시간별 기록 <span>같은 화면의 두 부분</span></figcaption>
    <EvidenceImage src={periodControls} alt="실제 환경 추세 화면의 24시간 선택 UI. 시간별 요약이며 한국 시간 기준입니다."/>
    <EvidenceImage src={periodChart} alt="T1 시간별 합성 예시 그래프. 전체 시간축과 10개 점이 보이며 빈 구간은 측정값 없음이라고 안내합니다. 실제 센서 자료가 아닙니다."/>
    <p className="er20-provenance">{syntheticLabel}<br/>2026.11.07 로컬 캡처 · 마지막 입력 11.06 18:00 KST · 오래된 데이터</p>
  </figure>;
}

export default function UsecaseVisual({ slide }: { slide: BriefingSlide }) {
  const alternative = slide.alternative && <p className="er20-alternative">{slide.alternative}</p>;
  if (slide.visual === "need-overview") return <div className="er20 er20-overview">
    <figure className="er20-model"><div className="er20-model-frame"><EvidenceImage src={model} alt="R3 발표에 사용한 세로형 사육장 가상 배치 모델. 상단 사육 공간과 하부 장치 공간. 실물 사진이 아닙니다."/></div><figcaption>R3 사육장 배치 모델 · 실물 사진 아님</figcaption></figure>
    <div className="er20-purposes"><div><span>시간</span><p><strong>외출 시간의<br/>환경 기록</strong></p></div><div><span>위치</span><p><strong>각 센서의<br/>측정 위치</strong></p></div><div><span>관리</span><p><strong>마지막으로 기록한<br/>관리 내역</strong></p></div><p className="er20-scope">지난 발표 · 사육장 구성과 연구 시험<br/><strong>이번 진행 · 기록 조회 보완과 사용 목적 정리</strong></p></div>
  </div>;
  if (slide.visual === "need-time") return <div className="er20 er20-scenario"><aside className="er20-context"><Situation kind="away"/><h3>귀가 후 확인</h3><strong>부재 시간에 남은<br/>기록을 확인</strong><p className="er20-limit">기록이 없는 구간은<br/>확인할 수 없습니다.</p>{alternative}</aside><PeriodEvidence/></div>;
  if (slide.visual === "need-location") return <div className="er20 er20-location"><aside className="er20-location-context"><div className="er20-position-pair"><PositionDrawing/><dl>{locations.map(({id,label})=><div key={id}><dt>{id}</dt><dd>{label}</dd></div>)}</dl></div><p>R3 형태를 참고한 등록 위치 도식<br/><strong>20 × 20 × 30 cm · 가정 배치</strong></p>{alternative}</aside><figure className="er20-spatial"><EvidenceImage src={spatialContext} alt="실제 공간 화면 상단. 가정 배치, 과거 시점, 선택 측정 11월 6일 18시 KST. 현재 상태가 아닙니다."/><div className="er20-spatial-detail"><EvidenceImage src={spatialStage} alt="합성 입력 23.60°C를 T1·T2·T3에 표시한 실제 공간 UI. 점은 센서 경로 값, 반투명 공간은 계산한 추정입니다."/><div><strong>점은 등록 위치의 값</strong><p>센서 사이의 색은<br/>계산한 온도 추정</p><p className="er20-provenance">{syntheticLabel}<br/>2026.11.07 캡처<br/>선택 시각 11.06 18:00 KST<br/>과거 기록 · 현재 상태 아님</p></div></div></figure></div>;
  if (slide.visual === "need-care") return <div className="er20 er20-care"><aside className="er20-context"><Situation kind="care"/><h3>다음 관리 전 확인</h3><p>마지막으로 남긴<br/>종류·시각·내용을 읽습니다.</p><div className="er20-time-note"><strong>발생 · 11.06 18:15</strong><span>청소했다고 기록한 때</span><strong>등록 · 11.07 01:05</strong><span>웹에 입력한 때</span></div>{alternative}</aside><figure className="er20-care-proof"><figcaption>직접 입력한 시연 기록</figcaption><EvidenceImage src={careDetail} alt="실제 청소 상세 화면. 물그릇 세척 후 물 교체라는 시연 예시. 발생 11월 6일 18시 15분, 등록 11월 7일 1시 5분 37초 KST. 실제 관리 기록이 아닙니다."/><p className="er20-outcome">늦게 작성했어도 <strong>발생 시각 기준</strong></p></figure></div>;
  if (slide.visual === "need-structure") return <div className="er20 er20-structure"><div className="er20-structure-head"><span>기존에 가능한 확인</span><strong>EasyRep · 같은 사육장 안에서 선택</strong></div>{[
    {name:'원격 이력 앱',info:'측정 시각과 값',answer:'환경 기록',src:periodChart,alt:'앞에서 본 합성 입력의 실제 기간 그래프'},
    {name:'위치명 표·2D',info:'센서와 등록 위치',answer:'배치 정보',src:spatialStage,alt:'앞에서 본 가정 배치의 실제 공간 화면'},
    {name:'메모·관리 앱',info:'발생 시각과 내용',answer:'관리 내역',src:careDetail,alt:'앞에서 본 직접 입력한 실제 청소 상세 화면'},
  ].map(row=><div className="er20-mapping" key={row.name}><div><strong>{row.name}</strong><p>{row.info}</p></div><div className="er20-mapping-target"><EvidenceImage src={row.src} alt={row.alt}/><div><strong>{row.answer}</strong><p>{row.info}</p></div></div></div>)}<p className="er20-provenance">그림은 앞 장의 로컬 시연 화면 일부 · 합성 환경값·가정 배치·직접 입력 예시</p></div>;
  if (slide.visual === "need-boundary") return <div className="er20 er20-boundary"><aside><h3>저장돼 있어도<br/>조회에서 빠지면<br/>확인할 수 없습니다.</h3><p>같은 시각에 몰린 기록의<br/>다음 페이지를 수정했습니다.</p></aside><figure><figcaption>동일 시각의 합성 기록 <strong>2,002건</strong></figcaption><table><thead><tr><th scope="col">조회</th><th scope="col">첫 페이지</th><th scope="col">다음 페이지</th></tr></thead><tbody><tr><th scope="row">수정 전</th><td>2,000<span>건</span></td><td>0<span>건</span></td></tr><tr><th scope="row">수정 후</th><td>2,000<span>건</span></td><td>2<span>건</span></td></tr></tbody></table><p className="er20-outcome">조회 ID 합집합 <strong>2,002건</strong> · 중복 <strong>0건</strong></p></figure></div>;
  return <div className="er20 er20-evaluation"><p className="er20-proposal">평가용 표현 예시 · 현재 제품 기능이나 평가 결과가 아닙니다</p><div className="er20-evaluation-grid"><section><h3>같은 센서·위치 정보</h3><div className="er20-equal-views"><figure><figcaption>위치명 표</figcaption><dl>{locations.map(({id,label})=><div key={id}><dt>{id}</dt><dd>{label}</dd></div>)}</dl></figure><figure><figcaption>2D</figcaption><PositionDrawing flat/></figure><figure><figcaption>3D</figcaption><PositionDrawing/></figure></div><p>같은 값·시각·센서·위치를 제공</p></section><section><h3>같은 관리·환경 기록</h3><div className="er20-equal-care"><figure><figcaption>메모</figcaption><div>사육장 A · 청소<br/>발생 11.06 18:15:00<br/>등록 11.07 01:05:37<br/>물그릇 세척·물 교체</div></figure><figure><figcaption>현재 웹</figcaption><EvidenceImage src={careDetail} alt="비교 계획에서 메모와 같은 종류·발생 시각·등록 시각·내용을 제공할 현재 웹의 시연 예시."/></figure></div><p>관리 내역과 환경 기록도 동일하게 제공</p></section></div><p className="er20-evaluation-decision">대상·시각·위치의 오독과 탐색 부담을 보고 <strong>유지·단순화 결정</strong></p></div>;
}
