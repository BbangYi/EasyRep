import type { BriefingSlide } from "./presentation-briefing-content";
import { progressNarrative } from "./presentation-progress-content";
import { EvidenceImage } from "./presentation-usecase-visual";
import boundaryImage from "../public/presentation/er029-history-boundary-20261106.png?url";
import productionImage from "../public/presentation/er029-production-history-20261106.jpg?url";
import cameraIntegrationImage from "../public/presentation/camera-site-integration-20261109.png?url";
import fieldWiringImage from "../public/presentation/field-wiring-20261109.jpg?url";
import "./presentation-progress.css";

function Flow({ items, vertical = false }: { items: readonly string[]; vertical?: boolean }) {
  return <ol className={`er29-flow${vertical ? " er29-flow-vertical" : ""}`}>{items.map((item, index) => <li key={item}><span className="er29-step">{String(index + 1).padStart(2, "0")}</span><strong>{item}</strong></li>)}</ol>;
}

function Closing({ children }: { children: string }) {
  return children ? <p className="er29-closing">{children}</p> : null;
}

function EvidenceFigure({ src, alt, caption, className = "" }: { src: string; alt: string; caption: string; className?: string }) {
  return <figure className={`er29-evidence ${className}`}><EvidenceImage key={src} src={src} alt={alt}/><figcaption>{caption} <a href={src} target="_blank" rel="noopener noreferrer">원본 전체 보기<span className="briefing-sr-only"> (새 창)</span></a></figcaption></figure>;
}

export default function ProgressVisual({ slide }: { slide: BriefingSlide }) {
  const item = progressNarrative.find(entry => entry.id === slide.id);
  if (!item) return null;
  switch (item.id) {
    case "progress-need-observation": return <div className="er29 er49-necessity">
      <ol aria-label="서비스 필요성의 세 가지 근거">
        {item.content.evidence.map((entry) => <li key={entry.label}>
          <span>{entry.label}</span><strong>{entry.metric}</strong><em>{entry.study}</em><h3>{entry.title}</h3><p>{entry.description}</p><small>{entry.source}</small>
        </li>)}
      </ol>
      <Closing>{item.content.closing}</Closing>
    </div>;
    case "progress-need-evidence": return <div className="er29 er52-spatial-rationale">
      <ol aria-label="공간 온도 모델의 설계 전환">
        {item.content.stages.map(([label, title, description]) => <li key={label}>
          <span>{label}</span>
          <section><h3>{title}</h3><p>{description}</p></section>
        </li>)}
      </ol>
      <Closing>{item.content.closing}</Closing>
    </div>;
    case "progress-need-prediction": return <div className="er29 er53-project-gantt">
      <ol className="er53-earlier" aria-label="R3 이전 주요 진행">
        {item.content.earlier.map(([date, title, description]) => <li key={date}><time>{date}</time><h3>{title}</h3><p>{description}</p></li>)}
      </ol>
      <section className="er53-gantt" aria-label="R3 이후 작업 흐름">
        <header><span>작업 흐름</span><div>{item.content.ticks.map(tick => <time key={tick}>{tick}</time>)}</div></header>
        <ol>
          {item.content.lanes.map(lane => <li key={lane.title}>
            <h3>{lane.title}</h3>
            <div className="er53-bars">
              {lane.segments.map(segment => <div key={`${lane.title}-${segment.date}`} className={`er53-bar er53-${segment.kind}`} style={{ gridColumn: `${segment.start} / ${segment.end}` }}>
                <time>{segment.date}</time><strong>{segment.title}</strong><span>{segment.description}</span>
              </div>)}
            </div>
          </li>)}
        </ol>
      </section>
      <aside className="er53-evidence" aria-label="현장 연결 기록">
        <EvidenceFigure src={cameraIntegrationImage} alt="2026년 11월 10일 EasyRep 화면에서 천장과 전면 카메라가 영상 수신·재생 중인 상태." caption="11.10 천장·전면 영상 수신"/>
        <EvidenceFigure src={fieldWiringImage} alt="2026년 11월 9일 카메라와 적외선 장치를 연결한 현장 배선 사진." caption="11.09 카메라·적외선 장치 배선"/>
      </aside>
      <Closing>{item.content.closing}</Closing>
    </div>;
    case "progress-after-r3": return <div className="er29 er55-r3-decisions">
      <header aria-hidden="true"><span>검증 대상</span><span>확인 결과</span><span>현재 판단</span></header>
      <ol aria-label="R3 이후 운영 기록, 개체 탐지, 탈피 예측 검증 결과">
        {item.content.decisions.map((decision) => <li key={decision.area}>
          <section><span>{decision.area}</span><h3>{decision.focus}</h3></section>
          <section><strong>{decision.result}</strong><p>{decision.scope}</p></section>
          <aside><b>{decision.decision}</b></aside>
        </li>)}
      </ol>
    </div>;
    case "progress-spatial-method": return <div className="er29 er57-history-status er57-history-summary">
      <header><section className="er57-snapshot"><span>{item.content.snapshot.label}</span><strong>{item.content.snapshot.value}</strong><h3>{item.content.snapshot.title}</h3><p>{item.content.snapshot.detail}</p></section></header>
      <ol aria-label="운영 환경 이력의 현재 활용과 다음 연구">
        {item.content.status.map(entry => <li key={entry.label}><span>{entry.label}</span><h3>{entry.title}</h3><p>{entry.detail}</p></li>)}
      </ol>
      <Closing>{item.content.closing}</Closing>
    </div>;
    case "progress-history-result": return <div className="er29"><div className="er29-split er29-history"><div className="er29-boundary"><div><span>수정 전</span><strong>2,000 <i>+</i> 0</strong></div><div><span>수정 후</span><strong>2,000 <i>+</i> 2</strong></div><p className="er29-cursor">{item.content.cursorFlow[0]}<br/><span aria-hidden="true">↓</span><br/>{item.content.cursorFlow[1]}</p><b>{item.content.result}</b></div><EvidenceFigure src={boundaryImage} alt="11월6일 로컬 합성 경계 시험 화면. 동일 시각2002건 중 두 번째 페이지2건이 표시된 상태." caption="로컬 합성 경계 시험"/></div><Closing>{item.content.closing}</Closing></div>;
    case "progress-history-production": return <div className="er29 er29-production"><div className="er29-split"><EvidenceFigure src={productionImage} alt="11월6일 운영 공간 이력 화면. 가상 검증 사육장의 과거 시점,6시간 조회,이전 기록 보기와 센서값 표시." caption="11.06 운영 조회 확인" className="er29-production-image"/><dl className="er29-verified">{item.content.verifiedResults.map(row=><div key={row[0]}><dt>{row[0]}</dt><dd>{row[1]}</dd></div>)}</dl></div><ol className="er29-inline-flow">{item.content.flow.map(text=><li key={text}>{text}</li>)}</ol><Closing>{item.content.closing}</Closing></div>;
    case "progress-detection-method": return <div className="er29 er60-detection-training">
      <p className="er60-summary">{item.content.summary}</p>
      <ol aria-label="도마뱀 탐지 학습과 결합 경로">
        {item.content.pipeline.map((step, index) => <li key={step.label}>
          <span>{String(index + 1).padStart(2, "0")}</span><p>{step.label}</p><h3>{step.title}</h3><small>{step.detail}</small>
          {index < item.content.pipeline.length - 1 && <i aria-hidden="true">→</i>}
        </li>)}
      </ol>
      <aside>
        <span>{item.content.trial.label}</span><h3>{item.content.trial.title}</h3><p>{item.content.trial.detail}</p>
      </aside>
      <Closing>{item.content.decision}</Closing>
    </div>;
    case "progress-detection-result": return <div className="er29 er56-detection-review">
      <section className="er49-model-general"><p>{item.content.general.label}</p><div className="er49-model-head"><span>{item.content.general.before}</span><i aria-hidden="true">→</i><strong>{item.content.general.after}</strong></div><dl>{item.content.general.metrics.map(([name, before, after]) => <div key={name}><dt>{name}</dt><dd><span>{before}</span><i aria-hidden="true">→</i><strong>{after}</strong></dd></div>)}</dl><b>{item.content.general.summary}</b></section>
      <aside className="er49-model-night"><p>{item.content.issue.label}</p><strong>{item.content.issue.value}</strong><span>{item.content.issue.context}</span><b>{item.content.issue.summary}</b></aside>
      <section className="er56-next-evaluation"><span>{item.content.next.label}</span><h3>{item.content.next.title}</h3><p>{item.content.next.description}</p></section>
      <Closing>{item.content.closing}</Closing>
    </div>;
    case "progress-appearance-input": return <div className="er29 er61-shedding-state">
      <ol aria-label="탈피 상태 분류 학습과 평가">
        {item.content.runs.map(run => <li key={run.label}>
          <header><span>{run.label}</span><h3>{run.title}</h3></header>
          <dl><div><dt>학습</dt><dd>{run.method}</dd></div><div><dt>입력</dt><dd>{run.data}</dd></div><div><dt>평가</dt><dd>{run.result}</dd></div></dl>
        </li>)}
      </ol>
      <section className="er61-decision"><div><span>{item.content.decision.label}</span><h3>{item.content.decision.title}</h3><p>{item.content.decision.detail}</p></div><div><span>{item.content.next.label}</span><h3>{item.content.next.title}</h3><p>{item.content.next.detail}</p></div></section>
    </div>;
    case "progress-appearance-prediction": return <div className="er29 er55-baseline-review">
      <section className="er55-baseline-method" aria-label="탈피 날짜 예측 비교 방법">
        <p>{item.content.cohort}</p>
        <ol>{item.content.steps.map((step, index) => <li key={step.label}><span>{step.label}</span><strong>{step.value}</strong><p>{step.description}</p>{index < item.content.steps.length - 1 && <i aria-hidden="true">→</i>}</li>)}</ol>
      </section>
      <section className="er55-baseline-comparison" aria-label="탈피 날짜 예측 비교 결과">
        {item.content.comparison.map(entry => <div key={entry.label}><span>{entry.label}</span><strong>{entry.value}</strong></div>)}
        <aside><p>{item.content.featureFinding}</p><small>{item.content.pending}</small><b>{item.content.decision}</b></aside>
      </section>
    </div>;
    case "progress-appearance-result": return <div className="er29 er29-execution"><Flow items={item.content.stages}/><dl className="er29-outcomes">{item.content.outputs.map(row=><div key={row[0]}><dt>{row[0]}</dt><dd>{row[1]}</dd></div>)}</dl><Closing>{item.content.closing}</Closing></div>;
    case "progress-humidity-method": return <div className="er29 er62-humidity-field">
      <EvidenceFigure src={cameraIntegrationImage} alt="2026년 11월 10일 EasyRep 화면에서 천장과 전면 카메라가 영상 수신·재생 중인 상태." caption="11.10 천장·전면 영상 수신"/>
      <section>
        <header><span>{item.content.status.label}</span><h3>{item.content.status.title}</h3><p>{item.content.status.detail}</p></header>
        <ol aria-label="현장 영상 연동 진행 순서">{item.content.steps.map(([index, title, detail]) => <li key={title}><span>{index}</span><h3>{title}</h3><p>{detail}</p></li>)}</ol>
      </section>
    </div>;
    case "progress-conclusion": return <div className="er29 er56-report-draft"><p>{item.content.summary}</p><table className="er29-conclusion-table" aria-label="결과보고서 검증 축"><thead><tr>{item.content.columns.map(label=><th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{item.content.rows.map(row=><tr key={row[0]}><th scope="row">{row[0]}</th><td data-label={item.content.columns[1]}>{row[1]}</td><td data-label={item.content.columns[2]}>{row[2]}</td></tr>)}</tbody></table><Closing>{item.content.closing}</Closing></div>;
  }
}
