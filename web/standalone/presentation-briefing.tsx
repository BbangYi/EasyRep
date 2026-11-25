/// <reference types="vite/client" />
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { briefingGroups, overallNecessity, currentBriefingSlides, archivedBriefingSlides, briefingProductComparison, milestones, milestoneTargets, archivedMilestones, resolveBriefingSlide, briefingOutline, type BriefingSlide } from "./presentation-briefing-content";
import researchLayout from "../public/presentation/research-layout-20261105.jpg?url";
import exterior from "../public/presentation/research-exterior-20261105.jpg?url";
import environmentReading from "../public/presentation/environment-reading-local-20261106.jpg?url";
import environmentReadingMobile from "../public/presentation/environment-reading-mobile-local-20261106.jpg?url";
import careHistoryMobile from "../public/presentation/care-history-mobile-local-20261106.jpg?url";
import careHistory from "../public/presentation/care-history-local-20261106.jpg?url";
import spatialHistory from "../public/presentation/spatial-history-local-20261106.jpg?url";
import detection from "../public/presentation/detection-result-20261022.png?url";
import detectionError from "../public/presentation/detection-false-positive-20261022.png?url";
import pumpOn from "../public/presentation/pump-on-20261105.png?url";
import pumpOff from "../public/presentation/pump-off-20261105.png?url";
import temperatureVideo from "../public/presentation/temperature-replay-20261105.mp4?url";
import cameraVideo from "../public/presentation/dual-camera-synthetic-20261105.mp4?url";
import "./presentation-briefing.css";
import RationaleVisual from "./presentation-rationale-visual";
import ProgressVisual from "./presentation-progress-visual";
import { progressNarrative } from "./presentation-progress-content";
import "./presentation-rationale.css";
import UsecaseVisual from "./presentation-usecase-visual";
import PresentationReport from "./presentation-report";
import PresentationReferences, { type ReferenceContext } from "./presentation-references";
import PresentationVideo from "./presentation-video";
import { presentationScenarios } from "./presentation-content";
import { reportChapters, reportReviewItems, reportSources } from "./presentation-report-content";

export const slideSources: Record<string, string[]> = {
  ...Object.fromEntries(progressNarrative.map(item => [item.id, [...item.sourceRefs]])),
  "necessity-overview": [...overallNecessity[0].sourceIds],
  "necessity-approach": [...overallNecessity[1].sourceIds],
  "rationale-goal": ["rspca-crested", "reptilearn-2024", "web", "r3"],
  "rationale-spatial": ["rspca-crested", "spatial", "r3"],
  "rationale-interpolation": ["esri-idw", "spatial", "r3"],
  "rationale-detection": ["reptilearn-2024", "technicalAudit", "geckoVideo", "geckoLicense"],
  "rationale-association": ["reptilearn-2024", "technicalAudit"],
  "rationale-shedding": ["appearanceResearchCurrent", "rspca-crested", "technicalAudit"],
  "rationale-misting": ["prediction", "r3", "technicalAudit", "monsoon", "ecc"],
  "rationale-state": ["appearanceResearchCurrent", "technicalAudit", "r3", "prediction"],
  "rationale-evaluation": ["technicalAudit", "technicalResearch"],
  "post-r3-overview": ["r3", "web", "remoteHistory"],
  "outdoor-environment": ["web", "remoteHistory", "release"],
  "spatial-context": ["spatialMeaning", "r3", "positionContext"],
  "care-history": ["web", "careAlternatives"],
  "post-r3-changes": ["web", "spatialMeaning", "remoteHistory", "careAlternatives", "necessityPlan"],
  "spatial-history": ["spatial", "release"], "post-r3-next": ["necessityPlan", "r3"],
  intro: ["web", "prediction", "detection", "r3"], service: ["web", "search"],
  system: ["r3", "assembly"], current: ["web", "spatial", "release"],
  timeline: ["prediction", "assembly", "detection", "r3", "release"],
  prediction: ["prediction"], detection: ["detection", "geckoVideo", "geckoLicense"], tracking: ["detection", "geckoVideo", "geckoLicense"],
  temperature: ["r3", "spatial"], camera: ["r3"], misting: ["r3"],
  comparison: ["monsoon", "ecc", "slither", "web"], status: ["web", "assembly", "prediction", "detection", "r3", "release"], next: ["r3", "web"],
};

type PresentationView = "timeline" | "slides" | "evidence" | "report";

export default function PresentationBriefing({ onReturn, evidence }: { onReturn: () => void; evidence: (scenario: { id: string } | null, onScenarioReferences: (id: string) => void) => ReactNode }) {
  const [view, setView] = useState<PresentationView>("slides");
  const [index, setIndex] = useState(0);
  const [deck, setDeck] = useState<"current" | "archive">("current");
  const [reportChapterId, setReportChapterId] = useState<string | null>(null);
  const [viewNavigation, setViewNavigation] = useState<{ next: PresentationView; targetId?: string } | null>(null);
  const [referenceContext, setReferenceContext] = useState<ReferenceContext | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [fullscreenMessage, setFullscreenMessage] = useState("");
  const stage = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const fullscreenButton = useRef<HTMLButtonElement>(null);
  const previousButton = useRef<HTMLButtonElement>(null);
  const nextButton = useRef<HTMLButtonElement>(null);
  const viewPositions = useRef<Partial<Record<PresentationView, { top: number; focus: HTMLElement | null }>>>({});
  const [scenarioRequest, setScenarioRequest] = useState<{ id: string } | null>(null);
  const slides = deck === "current" ? currentBriefingSlides : archivedBriefingSlides;
  const slide = slides[index];
  const milestone = milestones.find(m => m.id === slide.group);

  useEffect(() => {
    if (!viewNavigation) return;
    const { next, targetId } = viewNavigation;
    // Focus only after the destination view and its heading have rendered.
    if (targetId) {
      const target = document.getElementById(targetId);
      target?.focus({ preventScroll: true });
      target?.scrollIntoView({ block: "start", behavior: "instant" });
      return;
    }
    const saved = viewPositions.current[next];
    const fallback = document.getElementById(next === "report" ? "report-reading-title" : next === "timeline" ? "briefing-timeline-title" : next === "evidence" ? "briefing-evidence-title" : "briefing-slide-title");
    window.scrollTo({ top: next === "slides" ? 0 : saved?.top ?? 0 });
    (saved?.focus?.isConnected && next !== "slides" ? saved.focus : fallback)?.focus({ preventScroll: true });
  }, [viewNavigation]);

  useEffect(() => {
    if (view !== "slides") return;
    // Read the newly rendered slide from its title, including long mobile slides.
    // Keep native select keyboard navigation active until the user leaves it.
    if (document.activeElement?.tagName !== "SELECT") heading.current?.focus({ preventScroll: true });
    heading.current?.scrollIntoView({ block: "start", behavior: "instant" });
  }, [view, slide.id]);

  useEffect(() => {
    if (view !== "slides") return;
    const element = stage.current;
    function onFullscreenChange() {
      const active = document.fullscreenElement === element;
      setFullscreen(active);
      if (!active) fullscreenButton.current?.focus({ preventScroll: true });
    }
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      if (document.fullscreenElement === element) void document.exitFullscreen().catch(() => {});
    };
  }, [view]);

  async function changeView(next: PresentationView | "return", targetId?: string) {
    if (next === view && !targetId) return;
    const position = { top: window.scrollY, focus: document.activeElement instanceof HTMLElement ? document.activeElement : null };
    if (document.fullscreenElement === stage.current && document.fullscreenElement) {
      try { await document.exitFullscreen(); }
      catch { setFullscreenMessage("전체화면을 닫지 못했습니다. Escape를 누른 뒤 다시 이동하세요."); return; }
    }
    viewPositions.current[view] = position;
    setFullscreen(false);
    if (next === "return") { onReturn(); return; }
    setView(next);
    setViewNavigation({ next, targetId });
  }
  function start(nextIndex: number, nextDeck = deck) {
    setDeck(nextDeck); setIndex(nextIndex); setFullscreenMessage("");
    if (view === "slides") heading.current?.focus({ preventScroll: true });
    else void changeView("slides");
  }
  function openReportDetail(section: string, scenario?: string) {
    if (scenario) setScenarioRequest({ id: scenario });
    void changeView("evidence", scenario ? "presentation-scenario-title" : `presentation-${section}`);
  }
  function move(next: number) {
    const bounded = Math.max(0, Math.min(slides.length - 1, next));
    // Keep navigation reachable when the focused paging button becomes disabled.
    if ((bounded === 0 && document.activeElement === previousButton.current) ||
        (bounded === slides.length - 1 && document.activeElement === nextButton.current)) {
      heading.current?.focus({ preventScroll: true });
    }
    setIndex(bounded);
  }
  function keydown(event: KeyboardEvent<HTMLDivElement>) {
    const target = event.target as HTMLElement;
    if (referenceContext || target.closest("dialog") || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.nativeEvent.isComposing ||
        target.isContentEditable || target.closest("input,select,textarea,video,audio,[role=slider]")) return;
    if (event.key === "Escape" && document.fullscreenElement === event.currentTarget) {
      const element = event.currentTarget;
      event.preventDefault();
      void document.exitFullscreen().catch(() => {
        if (document.fullscreenElement === element) setFullscreenMessage("전체화면을 닫지 못했습니다. 종료 버튼이나 브라우저의 전체화면 종료를 사용하세요.");
      });
      return;
    }
    if (event.key === " " && target.closest("button,a,summary,[role=button]")) return;
    let next: number;
    if (["ArrowRight", "ArrowDown", "PageDown"].includes(event.key) || (event.key === " " && !event.shiftKey)) next = index + 1;
    else if (["ArrowLeft", "ArrowUp", "PageUp"].includes(event.key) || (event.key === " " && event.shiftKey)) next = index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = slides.length - 1;
    else return;
    event.preventDefault(); move(next);
  }
  async function toggleFullscreen() {
    setFullscreenMessage("");
    try {
      if (document.fullscreenElement === stage.current && document.fullscreenElement) await document.exitFullscreen();
      else if (stage.current?.requestFullscreen && document.fullscreenEnabled) await stage.current.requestFullscreen();
      else setFullscreenMessage("이 브라우저에서는 전체화면을 지원하지 않습니다. 현재 화면에서 계속 발표할 수 있습니다.");
    } catch { setFullscreenMessage("전체화면 요청이 허용되지 않았습니다. 현재 화면에서 계속 발표할 수 있습니다."); }
  }

  function startById(id: string) {
    const target = resolveBriefingSlide(id);
    if (target) start(target.index, target.deck);
  }
  function showRelatedSection() {
    const target = document.getElementById(`presentation-${slide.detailSection}`);
    target?.focus({ preventScroll: true });
    target?.scrollIntoView({ block: "start", behavior: "instant" });
  }

  function openReportChapter(id: string) {
    setReportChapterId(id);
    void changeView("report", "report-reading-title");
  }
  function openReferences(context?: ReferenceContext) {
    if (context) { setReferenceContext(context); return; }
    if (view === "slides") {
      setReferenceContext({ title: `${deck === "current" ? "이번 발표" : ["post-r3", "technical-rationale"].includes(slide.group) ? "이전 로컬 검토" : "지난 자료"} ${index + 1}장 · ${slide.title.replace(/\n/g, " ")}`, sourceIds: slideSources[slide.id] ?? [], notes: slide.notes, sourceNote: slide.source, slides: [...(progressNarrative.find(item => item.id === slide.id)?.relatedSlides ?? overallNecessity.find(item => item.id === slide.id)?.relatedSlideIds ?? [])], detail: slide.detailSection, scenarios: slide.scenarioId ? [slide.scenarioId] : undefined });
      return;
    }
    if (view === "evidence") {
      setReferenceContext({ title: "상세 설명 · 전체 자료", sourceIds: Object.keys(reportSources), gaps: reportReviewItems, slides: [slide.id], detail: slide.detailSection });
      return;
    }
    const chapter = view === "report" ? reportChapters.find(item => item.id === reportChapterId) : undefined;
    setReferenceContext(chapter ? { title: chapter.title, sourceIds: chapter.sections.flatMap(section => section.sources), gaps: chapter.gaps, slides: chapter.slides, scenarios: chapter.scenarios, detail: chapter.detail } : { title: view === "report" ? "프로젝트 개요 · 전체 자료" : "프로젝트 진행 경과 · 전체 자료", sourceIds: Object.keys(reportSources), gaps: reportReviewItems, slides: ["intro", "timeline", "status"] });
  }
  function openScenarioReferences(id: string) {
    const scenario = presentationScenarios.find(item => item.id === id);
    if (!scenario) return;
    const sourceIds = id === "D3" ? ["web", "spatial", "release"] : ["D2", "D4"].includes(id) ? ["web", "release"] : ["web"];
    setReferenceContext({ title: scenario.title, sourceIds, notesTitle: "구현 상태와 관련 흐름", notes: [scenario.features, scenario.limits], scenarios: scenario.related, detail: "scenarios" });
  }
  const referencePanel = referenceContext && <PresentationReferences context={referenceContext} onClose={() => setReferenceContext(null)} onSlide={startById} onDetail={openReportDetail} onTimeline={() => void changeView("timeline")} onReport={openReportChapter} />;

  return <section className="briefing-shell" aria-label="EasyRep 발표 자료">
    <nav hidden={view === "slides"} className="briefing-views" aria-label="발표 보기 방식">
      <button aria-current={view === "timeline" ? "page" : undefined} onClick={() => void changeView("timeline")}>전체 타임라인</button>
      <button aria-current={view === "report" ? "page" : undefined} onClick={() => void changeView("report")}>결과보고서 개요</button>
      <button onClick={() => start(0, "current")}>이번 발표</button>
      <button aria-current={view === "evidence" ? "page" : undefined} onClick={() => void changeView("evidence")}>상세 설명</button>
      <button className="briefing-reference-button" onClick={() => openReferences()} aria-haspopup="dialog">참고 자료</button>
    </nav>
    <div hidden={view !== "timeline"}>
      <header className="briefing-overview">
        <div><h2 id="briefing-timeline-title" tabIndex={-1}>프로젝트 전체 자료</h2><p>날짜별 연구 결과와 누적 보고서</p></div>
        <button className="briefing-primary" onClick={() => start(0, "current")}>처음부터 발표 <span aria-hidden="true">▶</span></button>
      </header>
      <nav className="briefing-outline" aria-label="발표 순서">
        {briefingOutline.map(item => <button key={item.slideId} onClick={() => startById(item.slideId)}><span>{item.range}</span><strong>{item.title}</strong><small>{item.detail}</small></button>)}
      </nav>
      <div className="briefing-timeline-heading"><h3>프로젝트 진행 경과</h3><button onClick={() => startById("intro")}>기존 누적 자료 14장</button><button onClick={() => startById("post-r3-overview")}>이전 로컬 검토 7장</button><button onClick={() => startById("rationale-goal")}>기술별 상세 7장</button><button onClick={() => startById("necessity-overview")}>이전 개요 4장</button></div>
      <ol className="briefing-timeline">
        {milestones.map(m => <li key={m.id}>
          <div className="briefing-date"><time dateTime={m.date}>{m.label}</time><span>{m.kind}</span></div>
          <div className="briefing-milestone"><div><h3>{m.title}</h3><p>{m.result}</p></div>{milestoneTargets[m.id]?.map(target => <button key={target.slideId} onClick={() => startById(target.slideId)}>{target.label}</button>)}</div>
        </li>)}
      </ol>
    </div>
    {view === "slides" && <div className="briefing-stage" ref={stage} onKeyDown={keydown} aria-label="슬라이드 발표" data-deck={deck} data-design={slide.visual.startsWith("need-") || slide.visual === "rationale" || slide.visual === "progress-narrative" ? "current" : "archive"}>
      {fullscreenMessage && <p className="briefing-fullscreen-message" role="status">{fullscreenMessage}</p>}
      <article className={`briefing-slide briefing-layout-${slide.visual}`} aria-labelledby="briefing-slide-title" data-slide-id={slide.id}>
        <header className="briefing-slide-heading">
          <p className="briefing-kicker"><span>{deck === "archive" ? ["post-r3", "technical-rationale"].includes(slide.group) ? "이전 로컬 검토 · " : "지난 자료 · " : ""}{String(index + 1).padStart(2, "0")} / {milestone ? milestone.label + " · " + milestone.kind : briefingGroups.find(g => g.id === slide.group)?.label}</span>{deck === "archive" && <button onClick={() => start(0, "current")}>이번 발표로</button>}</p>
          <h2 ref={heading} id="briefing-slide-title" tabIndex={-1}>{slide.title}</h2>
          <p className="briefing-conclusion">{slide.visual === "cover" ? "환경 기록 · 영상 관찰 · 분무 제어" : slide.conclusion}</p>
        </header>
        <div className="briefing-slide-body"><SlideVisual slide={slide} onSelect={startById} /></div>
      </article>
      <nav className="briefing-toolbar" aria-label="발표 조작">
        <div className="briefing-paging"><button ref={previousButton} disabled={index === 0} onClick={() => move(index - 1)}>이전</button><span role="status" aria-live="polite" aria-atomic="true">{index + 1} / {slides.length}<span className="briefing-sr-only"> {slide.title.replace(/\n/g, " ")}</span></span><button ref={nextButton} disabled={index === slides.length - 1} onClick={() => move(index + 1)}>다음</button></div>
        <label><span className="briefing-sr-only">목차</span><select aria-label="발표 목차" value={index} onChange={e => move(Number(e.target.value))}>{slides.map((s, i) => <option key={s.id} value={i}>{String(i + 1).padStart(2, "0")} {s.title.replace(/\n/g, " ")}</option>)}</select></label>
        <button onClick={() => void changeView("evidence")}>상세 설명</button>
        <button ref={fullscreenButton} onClick={() => void toggleFullscreen()}>{fullscreen ? "전체화면 종료" : "전체화면"}</button>
        <button onClick={() => void changeView("timeline")}>전체 타임라인</button>
        <button onClick={() => void changeView("report")}>결과보고서 개요</button>
        <button onClick={() => openReferences()} aria-haspopup="dialog">참고 자료</button>
        <button onClick={() => void changeView("return")}>운영 화면으로</button>
      </nav>
      {referencePanel}
    </div>}
    <div hidden={view !== "report"}><PresentationReport selected={reportChapterId} onSelect={setReportChapterId} onReferences={openReferences} /></div>
    <div hidden={view !== "evidence"} className="briefing-evidence">
      <div className="briefing-evidence-heading"><h2 id="briefing-evidence-title" tabIndex={-1}>상세 설명</h2><button onClick={() => start(index)}>선택한 슬라이드로 돌아가기</button></div>
      <section className="briefing-notes" aria-labelledby="briefing-note-title">
        <p>선택한 장 {index + 1} / {slides.length}</p><h3 id="briefing-note-title">{slide.title.replace(/\n/g, " ")}</h3>
        {slide.notes.map(note => <p key={note}>{note}</p>)}
        <p className="briefing-note-limit">{slide.limit}</p>
        {slide.id === "detection" && <figure className="briefing-detail-image"><img src={detectionError} alt="2026년 10월 22일 발표자료의 중복 오탐 원본 결과" loading="lazy" /><figcaption>당시 중복 오탐 사례 · 원본 탐지 결과</figcaption></figure>}
        <button onClick={showRelatedSection}>관련 상세 자료로 이동</button>
      </section>
      {evidence(scenarioRequest, openScenarioReferences)}
    </div>
    {view !== "slides" && referencePanel}
  </section>;
}

function ModelFigure({ exteriorView = false }: { exteriorView?: boolean }) {
  return <figure className="briefing-model"><div className={`briefing-crop ${exteriorView ? "briefing-crop-exterior" : "briefing-crop-model"}`}><img src={exteriorView ? exterior : researchLayout} width="1280" height="720" alt={exteriorView ? "Constructa 사육장 외관 배치 모델. 실물 사진이 아님." : "Constructa 사육장 절개 배치 모델. 상단 사육 공간과 하부 물통·펌프 위치. 실물 사진이 아님."} /></div><figcaption>가상 배치 모델 / 2026.11.05</figcaption></figure>;
}

function SlideVisual({ slide, onSelect }: { slide: BriefingSlide; onSelect: (id: string) => void }) {
  if (slide.visual === "progress-narrative") return <ProgressVisual key={slide.id} slide={slide} />;
  if (slide.visual === "rationale") return <RationaleVisual key={slide.id} slide={slide} />;
  if (slide.visual.startsWith("need-")) return <UsecaseVisual key={slide.id} slide={slide} />;
  if (slide.visual === "progress-delta") return <dl className="briefing-delta">{slide.points.map(([label, text], i) => <div key={label}><dt><span>{i === 0 ? "조회 수정" : "2026.11.06 운영 확인"}</span>{label}</dt><dd>{text}</dd></div>)}</dl>;
  if (slide.visual === "scenario-environment" || slide.visual === "scenario-care") return <div className="briefing-use-case">
    <figure className={`briefing-interface-crop ${slide.visual === "scenario-care" ? "briefing-care-crop" : ""}`}><picture><source media="(max-width:560px)" srcSet={slide.visual === "scenario-care" ? careHistoryMobile : environmentReadingMobile} /><img src={slide.visual === "scenario-care" ? careHistory : environmentReading} alt={slide.visual === "scenario-care" ? "로컬 시연 관리 기록. 급여 종류, 직접 입력한 예시 내용과 발생 시각이 표시됩니다." : "로컬 합성 환경 화면. 마지막 측정 시각, 합성 온도 24°C와 습도·조도 미수신 상태가 표시됩니다."} /></picture></figure>
    <ScenarioSteps points={slide.points} />
  </div>;
  if (slide.visual === "history-boundary") return <div className="briefing-boundary">
    <div className="briefing-boundary-evidence"><p>동일 시각의 합성 기록 <strong>2,002건</strong></p><dl><div><dt>수정 전 · 첫 조회 → 다음 조회</dt><dd>2,000 <span>→</span> 0<small>건</small></dd></div><div><dt>수정 후 · 첫 조회 → 다음 조회</dt><dd>2,000 <span>→</span> 2<small>건</small></dd></div></dl></div>
    <ScenarioSteps points={slide.points} />
  </div>;
  if (slide.visual === "cover") return <ModelFigure exteriorView />;
  if (slide.visual === "assembly") return <><ModelFigure /><dl className="briefing-annotations">{slide.points.map(([label,text])=><div key={label}><dt>{label}</dt><dd>{text}</dd></div>)}</dl></>;
  if (slide.visual === "spatial") return <figure className="briefing-screen"><div className="briefing-history-crop"><img src={spatialHistory} width="1004" height="560" alt="로컬 합성 데이터로 촬영한 공간 이력 화면의 상단 부분. 과거 시점, 조회 기간, 개별 측정 시각, 이전 기록 보기와 센서 위치의 보간 화면을 표시합니다." /></div></figure>;
  if (slide.visual === "timeline") return <ol className="briefing-slide-timeline">{archivedMilestones.map(m=><li key={m.id}><time dateTime={m.date}>{m.label.slice(5)}</time>{milestoneTargets[m.id]?.map(target=><button key={target.slideId} onClick={()=>onSelect(target.slideId)}>{m.title}</button>)}<p>{m.result}</p><small>{m.kind}</small></li>)}</ol>;
  if (slide.visual === "prediction") return <div className="briefing-results"><div className="briefing-bars"><h3>습도 이탈 시간 <span>분</span></h3><div className="briefing-legend"><span>임계값 제어</span><span>예측 제어</span></div>{[["A · 45–55%",14,3.3],["B · 60–70%",62.5,13.2],["C · 75–85%",156.8,82]].map(([label,before,after])=><div className="briefing-bar-group" key={label}><strong>{label}</strong><div><div className="briefing-bar before" style={{width:`${Number(before)/160*100}%`}}><span>{before}</span></div><div className="briefing-bar after" style={{width:`${Number(after)/160*100}%`}}><span>{after}</span></div></div></div>)}</div><div className="briefing-cost"><h3>펌프 작동 시간 증가</h3><table><caption>같은 시험의 작동 시간 · 초</caption><thead><tr><th scope="col">조건</th><th scope="col">임계값</th><th scope="col">예측</th></tr></thead><tbody>{[["A",52,81.3],["B",163,202.5],["C",274,331.5]].map(([c,b,a])=><tr key={c}><th scope="row">{c}</th><td>{b}</td><td>{a}</td></tr>)}</tbody></table><p>온도 이탈 시간도 증가</p></div></div>;
  if (slide.visual === "detection") return <><figure className="briefing-detection"><img src={detection} width="1024" height="576" alt="공개 영상에서 도마뱀을 탐지한 당시 모델 출력. 개체 주위에 T6 0.93 박스가 표시되어 있습니다." /></figure><dl className="briefing-detection-counts">{slide.points.map(([value,label])=><div key={label}><dt>{label}</dt><dd>{value}<small>건</small></dd></div>)}</dl></>;
  if (slide.visual === "tracking") return <div className="briefing-track-result"><div className="briefing-track-before"><span>수정 전</span><strong>0<small> / 86</small></strong><p>연속 연결</p></div><span className="briefing-track-arrow" aria-hidden="true">→</span><div className="briefing-track-after"><span>수정 후</span><strong>66<small> / 86</small></strong><p>연속 연결</p><div className="briefing-track-bar"><span /></div><small>미연결 20쌍</small></div></div>;
  if (slide.visual === "temperature" || slide.visual === "camera") return <><div className="briefing-media-fact"><span>{slide.visual === "temperature" ? "실제 기록 재생" : "합성 영상 처리"}</span><strong>{slide.visual === "temperature" ? "713" : "87"}<small>{slide.visual === "temperature" ? "시점" : "/ 270"}</small></strong><p>{slide.visual === "temperature" ? <>센서 3곳만 실측<br />사이 공간은 추정</> : <>3D 좌표 생성<br />나머지 183프레임 미결정</>}</p></div><PresentationVideo key={slide.id} src={slide.visual === "temperature" ? temperatureVideo : cameraVideo} label={slide.visual === "temperature" ? "원본 발표자료의 실제 센서 기록 재생 영상" : "원본 발표자료의 합성 천장·전면 영상 처리 시험"} /></>;
  if (slide.visual === "misting") return <><div className="briefing-pump-output">{[[pumpOn,"ON · 요청 1"],[pumpOff,"OFF · 요청 0"]].map(([src,label])=><figure key={label}><figcaption>{label}</figcaption><div className="briefing-crop briefing-crop-pump"><img src={src} width="1280" height="720" alt={`가상 제어 원본 화면: ${label}`} /></div></figure>)}</div><div className="briefing-pump-facts"><div><strong>2<small>초</small></strong><p>정상 요청 후 정지</p></div><div><strong>300<small>초</small></strong><p>다음 요청까지 대기</p></div></div></>;
  if (slide.visual === "comparison") return <div className="briefing-comparison"><section><h3>기존 제품의 제공 기능</h3><dl>{briefingProductComparison.map(product => <div key={product.name}><dt>{product.name}</dt><dd>{product.features}</dd></div>)}</dl></section><section><h3>EasyRep의 작업 흐름</h3><dl>{slide.points.map(([title,text]) => <div key={title}><dt>{title}</dt><dd>{text}</dd></div>)}</dl></section></div>;
  if (slide.visual === "status") return <div className="briefing-scope-bands">{slide.points.map(([title,text], i) => <section key={title}><h3>{title}</h3><p>{text}</p><span>{["환경 조회 · 관리 기록 · 공간 화면", "예측 결과 · 영상 처리 · 가상 분무", "조립·센서·영상·분사 검증 계획"][i]}</span></section>)}</div>;
  return <ol className={`briefing-flow briefing-flow-${slide.visual}`}>{slide.points.map(([label,text],i)=><li key={label}><span className="briefing-step">{String(i+1).padStart(2,"0")}</span><strong>{label}</strong><p>{text}</p></li>)}</ol>;
}

function ScenarioSteps({ points }: { points: BriefingSlide["points"] }) {
  return <ol className="briefing-scenario-steps">{points.map(([title, description], i) => <li key={title}><span>{String(i + 1).padStart(2, "0")}</span><strong>{title}</strong><p>{description}</p></li>)}</ol>;
}
