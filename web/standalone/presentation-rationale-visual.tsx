import { Droplets, Eye, ScanSearch, MapPin, NotebookPen } from "lucide-react";
import TemperatureComparison from "./presentation-temperature-comparison";
import "./presentation-shedding-usecase.css";
import "./presentation-humidity-usecase.css";
import "./presentation-detection-usecase.css";
import "./presentation-overall-necessity.css";
import { sheddingUsecase, humidityUsecase, detectionUsecase, overallNecessity, type BriefingSlide } from "./presentation-briefing-content";

// Explanatory enclosure, not an installed layout or a recommended enclosure size.
function EnclosureSection({ measuring = false }: { measuring?: boolean }) {
  return <svg className="er21-enclosure" viewBox="0 0 430 340" role="img" aria-label={measuring ? "개념 단면도. 상단 가지와 하단 은신처의 센서, 점선 원은 추가 확인할 위치입니다. 치수와 실제 온도값은 표시하지 않습니다." : "생활 구역, 관찰 카메라, 분무 노즐의 역할을 설명하는 사육장 개념 단면도. 실제 설치 도면이 아닙니다."}>
    <path d="M72 36H350V304H72Z" fill="#e8eee0" stroke="#294f3d" strokeWidth="3"/>
    <path d="M72 292Q123 275 180 293T350 284V304H72Z" fill="#c1cba9"/>
    <path d="M140 287Q192 229 198 194T271 68M196 193 119 156M208 164 308 127" fill="none" stroke="#899568" strokeWidth="14" strokeLinecap="round"/>
    <path d="M106 285Q115 224 164 243Q182 250 189 285Z" fill="#839162"/>
    <path d="M126 287Q132 254 153 257Q166 260 168 287" fill="#405b40"/>
    <g fill="#6d8057"><ellipse cx="283" cy="170" rx="32" ry="12" transform="rotate(-35 283 170)"/><ellipse cx="300" cy="202" rx="35" ry="13" transform="rotate(26 300 202)"/><path d="M281 286Q305 227 283 170" fill="none" stroke="#6d8057" strokeWidth="4"/></g>
    <path d="M89 53H334M89 63H334" stroke="#9cac8d" strokeWidth="3"/>
    {measuring ? <>
      <g fill="#294f3d" stroke="#fff" strokeWidth="3"><circle cx="196" cy="107" r="11"/><circle cx="104" cy="251" r="11"/></g>
      <circle cx="273" cy="232" r="24" fill="#f5f7f1" stroke="#294f3d" strokeWidth="3" strokeDasharray="6 6"/>
      <path d="M273 220V244M261 232H285" stroke="#294f3d" strokeWidth="3"/>
      <path d="M208 107H382M115 251H50M298 232H382" fill="none" stroke="#647655" strokeWidth="2"/>
      <text x="227" y="96" fontSize="23" fill="#183429">상단</text><text x="78" y="235" fontSize="23" fill="#183429">하단</text>
    </> : <>
      <g fill="#294f3d" stroke="#fff" strokeWidth="3"><circle cx="199" cy="104" r="10"/><circle cx="100" cy="252" r="10"/></g>
      <rect x="191" y="20" width="40" height="27" rx="5" fill="#294f3d"/><circle cx="211" cy="34" r="7" fill="#e8eee0"/>
      <path d="M313 24V52H298" fill="none" stroke="#486e6d" strokeWidth="5"/><path d="M297 68 284 91M304 70V98M311 68 323 91" stroke="#779fa0" strokeWidth="3" strokeDasharray="4 6"/>
      <path d="M199 104H384M231 34H384M305 100H384" fill="none" stroke="#78916e" strokeWidth="2" strokeDasharray="5 6"/>
    </>}
  </svg>;
}

function ObservationStrip() {
  return <div className="er21-strip" aria-label="관찰과 미관찰 구간을 나누는 개념도. 실제 분석 결과나 비율이 아닙니다."><span>관찰</span><span className="er21-unknown">미관찰</span><span>관찰</span></div>;
}

export default function RationaleVisual({ slide }: { slide: BriefingSlide }) {
  switch (slide.id) {
    case "necessity-overview":
    case "necessity-approach": {
      const content = overallNecessity.find(item => item.id === slide.id);
      if (!content) return null;
      return <div className="er28-usecase" data-columns={content.columns.length}>
        <table className="er28-matrix" aria-label={content.title}>
          <colgroup>{content.columns.map(column => <col key={column}/>)}</colgroup>
          <thead><tr>{content.columns.map((column, i) => <th key={column} id={`${slide.id}-column-${i}`} scope="col">{column}</th>)}</tr></thead>
          <tbody>{content.rows.map((row, i) => <tr key={row[0]}>
            <th id={`${slide.id}-row-${i}`} scope="row" headers={`${slide.id}-column-0`}>{row[0]}</th>
            {row.slice(1).map((cell, j) => <td key={j} headers={`${slide.id}-row-${i} ${slide.id}-column-${j + 1}`} data-label={content.columns[j + 1]}>{cell}</td>)}
          </tr>)}</tbody>
        </table>
        <div className="er28-closing">{content.closing}</div>
      </div>;
    }
    case "rationale-goal": return <div className="er21 er21-purpose">
      <figure><EnclosureSection/><figcaption>사육장 구성 개념도</figcaption></figure>
      <div className="er21-purpose-lines">
        <div><MapPin aria-hidden="true"/><p><strong>{slide.body?.[0]}</strong><span>추가 측정 위치</span></p></div>
        <div><Eye aria-hidden="true"/><p><strong>{slide.body?.[1]}</strong><span>검토할 영상 구간</span></p></div>
        <div><Droplets aria-hidden="true"/><p><strong>{slide.body?.[2]}</strong><span>상태 확인·작동 대기</span></p></div>
      </div>
    </div>;
    case "rationale-spatial": return <div className="er21 er21-spatial">
      <figure><EnclosureSection measuring/><figcaption>측정 위치 개념도</figcaption></figure>
      <div className="er21-spatial-copy"><p className="er21-context">사육장 배치를 바꾼 뒤</p><h3>추가 측정 위치</h3><p>상단 활동 구역과<br/>하단 은신처 주변의 조건 비교</p><div className="er21-measure-key"><span><i/>측정 지점</span><span><i className="er21-dashed-dot"/>추가 확인 위치</span></div><p className="er21-decision">상단·하단 조건을 재측정하고<br/>센서 위치·배치를 점검</p></div>
    </div>;
    case "rationale-interpolation": return <TemperatureComparison/>;
    case "rationale-detection": return <div className="er27-usecase">
      <p className="er27-case">{detectionUsecase.caseLabel}</p>
      <table className="er27-matrix" aria-label="같은 영상 관찰 상황의 직접 확인, 탐지·추적 역할과 사육자 판단 비교">
        <colgroup><col className="er27-situation-col"/><col className="er27-alternative-col"/><col className="er27-research-col"/><col className="er27-decision-col"/></colgroup>
        <thead><tr>{detectionUsecase.columns.map((column, i) => <th key={column} id={`er27-column-${i}`} scope="col">{column}</th>)}</tr></thead>
        <tbody>{detectionUsecase.rows.map((row, i) => <tr key={row.situation}>
          <th id={`er27-row-${i}`} scope="row" headers="er27-column-0">{row.situation}</th>
          <td headers={`er27-row-${i} er27-column-1`} data-label={detectionUsecase.columns[1]}>{row.alternative}</td>
          <td headers={`er27-row-${i} er27-column-2`} data-label={detectionUsecase.columns[2]}><span className="er27-stage">{row.stage}</span><span>{row.additional}</span></td>
          <td headers={`er27-row-${i} er27-column-3`} data-label={detectionUsecase.columns[3]}>{row.decision}</td>
        </tr>)}</tbody>
      </table>
      <div className="er27-purpose">{detectionUsecase.purpose}</div>
      <div className="er27-context">{detectionUsecase.commonConditions}</div>
    </div>;
    case "rationale-association": return <div className="er21 er21-association">
      <div className="er21-time-guide"><span>관찰 시작</span><span>같은 시각</span><span>관찰 끝</span></div>
      <div className="er21-time-lane"><strong>환경 기록</strong><div className="er21-timeline"><svg viewBox="0 0 900 100" preserveAspectRatio="none" aria-hidden="true"><path d="M0 76H120L240 62 340 66 430 30 530 42 650 22 760 54 900 44" fill="none" stroke="#78916e" strokeWidth="5"/></svg><i className="er21-time-marker"/></div></div>
      <div className="er21-time-lane"><strong>개체 관찰</strong><div className="er21-timeline"><ObservationStrip/><i className="er21-time-marker"/></div></div>
      <div className="er21-align-notes"><span>같은 개체·구역·시각으로 대응</span><span>가림·미관찰은 별도 구간</span></div>
      <p className="er21-decision"><ScanSearch aria-hidden="true"/>센서 위치·조명·배치·관리 이력 점검</p>
      <p className="er21-concept">환경·개체 관찰의 시간 대응 개념도</p>
    </div>;
    case "rationale-shedding": return <div className="er25-usecase">
      <p className="er25-case">{sheddingUsecase.caseLabel}</p>
      <table className="er25-matrix" aria-label="탈피 관찰 상황별 기존 확인 방법, 연구 도구와 사육자의 판단">
        <colgroup><col className="er25-situation-col"/><col className="er25-alternative-col"/><col className="er25-research-col"/><col className="er25-decision-col"/></colgroup>
        <thead><tr>{sheddingUsecase.columns.map((column, i) => <th key={column} id={`er25-column-${i}`} scope="col">{column}</th>)}</tr></thead>
        <tbody>{sheddingUsecase.rows.map((row, i) => <tr key={row.situation}>
          <th id={`er25-row-${i}`} scope="row" headers="er25-column-0">{row.situation}</th>
          <td headers={`er25-row-${i} er25-column-1`} data-label={sheddingUsecase.columns[1]}>{row.alternative}</td>
          <td headers={`er25-row-${i} er25-column-2`} data-label={sheddingUsecase.columns[2]}><span className="er25-state">{row.state}</span><span>{row.additional}</span></td>
          <td headers={`er25-row-${i} er25-column-3`} data-label={sheddingUsecase.columns[3]}>{row.decision}</td>
        </tr>)}</tbody>
      </table>
      <div className="er25-purpose">{sheddingUsecase.commonPurpose}</div>
    </div>;
    case "rationale-misting": return <div className="er26-usecase">
      <p className="er26-case">{humidityUsecase.caseLabel}</p>
      <table className="er26-matrix" aria-label="같은 사육 상황의 타이머, 임계값·대기 규칙, 예측 연구와 분무 판단 비교">
        <colgroup><col className="er26-situation-col"/><col className="er26-timer-col"/><col className="er26-threshold-col"/><col className="er26-prediction-col"/><col className="er26-decision-col"/></colgroup>
        <thead><tr>{humidityUsecase.columns.map((column, i) => <th key={column} id={`er26-column-${i}`} scope="col">{column}</th>)}</tr></thead>
        <tbody>{humidityUsecase.rows.map((row, i) => <tr key={row.situation}>
          <th id={`er26-row-${i}`} scope="row" headers="er26-column-0">{row.situation}</th>
          <td headers={`er26-row-${i} er26-column-1`} data-label={humidityUsecase.columns[1]}>{row.timer}</td>
          <td headers={`er26-row-${i} er26-column-2`} data-label={humidityUsecase.columns[2]}>{row.threshold}</td>
          <td headers={`er26-row-${i} er26-column-3`} data-label={humidityUsecase.columns[3]}>{row.prediction}</td>
          <td headers={`er26-row-${i} er26-column-4`} data-label={humidityUsecase.columns[4]}>{row.decision}</td>
        </tr>)}</tbody>
      </table>
      <div className="er26-purpose">{humidityUsecase.purpose}</div>
      <div className="er26-context"><span>{humidityUsecase.commonConditions}</span><span>{humidityUsecase.historicalEvidence}</span></div>
    </div>;
    case "rationale-state": return <div className="er21 er21-state-grid">
      {[
        ["공간", "웹 실측 조회·IDW", "다음 · 독립 위치의 정확도"],
        ["영상", "저장 영상의 탐지·이동·체류", "다음 · 주야간·가림 조건 평가"],
        ["탈피", "수집·시계열·예측 연구 코드", "다음 · 실제 주기 평가"],
        ["분무", "과거 합성 예측·가상 명령", "다음 · 실제 작동 반응"]
      ].map(([name,now,next])=><section key={name}><span>{name}</span><h3>{now}</h3><p>{next}</p></section>)}
    </div>;
    case "rationale-evaluation": return <div className="er21 er21-research">
      <div className="er21-research-lanes">
        <section><MapPin aria-hidden="true"/><h3>공간·영상</h3><p>실제 위치·동일 시각의<br/>관측 비교</p><span>측정 오차·관찰 누락</span></section>
        <section><NotebookPen aria-hidden="true"/><h3>탈피</h3><p>검수 관찰·반복 주기<br/>이후 주기 평가</p><span>선행시간·놓친 주기·오경보</span></section>
        <section><Droplets aria-hidden="true"/><h3>분무</h3><p>빈 사육장 반응<br/>규칙·예측 비교</p><span>환경 이탈·작동 부담</span></section>
      </div><p className="er21-research-end">같은 정보와 조건에서 단순한 대안과 비교</p>
    </div>;
    default: return null;
  }
}
