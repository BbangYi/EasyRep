import { useEffect, useRef, type KeyboardEvent } from "react";
import { reportSources, type ReportGap } from "./presentation-report-content";
import { briefingSlides, currentBriefingSlides, archivedBriefingSlides, milestones } from "./presentation-briefing-content";
import "./presentation-references.css";

export type ReferenceContext = {
  title: string;
  sourceIds: string[];
  gaps?: (ReportGap & { chapterId?: string; chapterTitle?: string })[];
  slides?: string[];
  scenarios?: string[];
  detail?: string;
  notes?: string[];
  notesTitle?: string;
  sourceNote?: string;
  initialSource?: string;
};

export default function PresentationReferences({ context, onClose, onSlide, onDetail, onTimeline, onReport }: {
  context: ReferenceContext;
  onClose: () => void;
  onSlide: (id: string) => void;
  onDetail: (id: string, scenario?: string) => void;
  onTimeline: () => void;
  onReport: (id: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const navigateAfterClose = useRef<(() => void) | null>(null);
  const sources = [...new Set(context.sourceIds)].filter(id => reportSources[id]);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    element.showModal();
    if (context.initialSource) {
      const source = element.querySelector<HTMLElement>(`#reference-source-${context.initialSource}`);
      source?.focus({ preventScroll: true });
      source?.scrollIntoView({ block: "start" });
    }
    return () => {
      document.body.style.overflow = previousOverflow;
      if (element.open) element.close();
    };
  }, [context.initialSource]);

  function close() { dialog.current?.close(); }
  function closed() {
    const navigate = navigateAfterClose.current;
    if (!navigate && opener.current?.isConnected) opener.current.focus({ preventScroll: true });
    onClose();
    if (navigate) requestAnimationFrame(navigate);
  }
  function follow(action: () => void) {
    navigateAfterClose.current = action;
    close();
  }

  function keydown(event: KeyboardEvent<HTMLDialogElement>) {
    event.stopPropagation();
    if (event.key !== "Tab") return;
    const controls = [...event.currentTarget.querySelectorAll<HTMLElement>("button:not([disabled]),a[href]")].filter(element => element.getClientRects().length > 0);
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first?.focus();
    }
  }

  return <dialog ref={dialog} className="presentation-references" aria-labelledby="reference-title" onClose={closed} onKeyDown={keydown}>
    <header className="reference-header"><div><h2 id="reference-title">참고 자료</h2><p>{context.title}</p></div><button autoFocus onClick={close} aria-label="참고 자료 닫기">닫기</button></header>
    <div className="reference-body">
      {context.notes && <section aria-labelledby="reference-notes-title"><h3 id="reference-notes-title">{context.notesTitle ?? "발표 노트"}</h3>{context.notes.map(note => <p key={note}>{note}</p>)}</section>}
      <section aria-labelledby="reference-sources-title"><h3 id="reference-sources-title">출처</h3>
        {context.sourceNote && <p className="reference-source-note">{context.sourceNote}</p>}
        <nav className="reference-index" aria-label="출처 바로가기">{sources.map(id => <button key={id} onClick={() => { const target = document.getElementById(`reference-source-${id}`); target?.focus({ preventScroll: true }); target?.scrollIntoView({ block: "start" }); }}>{reportSources[id].title}</button>)}</nav>
        {sources.map(id => { const source = reportSources[id]; return <section className="reference-source" key={id} id={`reference-source-${id}`} tabIndex={-1} aria-labelledby={`reference-heading-${id}`}>
          <h4 id={`reference-heading-${id}`}>{source.title}</h4><p className="reference-meta">{source.date} / {source.status}</p>
          <dl><div><dt>해당 위치</dt><dd>{source.location}</dd></div><div><dt>확인 범위</dt><dd>{source.scope}</dd></div></dl>
          {source.url && <a href={source.url} target="_blank" rel="noreferrer">{source.urlLabel ?? "공식 자료 열기"} (새 창)</a>}
        </section>; })}
      </section>
      {!!context.gaps?.length && <section aria-labelledby="reference-review-title"><h3 id="reference-review-title">검토 메모</h3>{context.gaps.map(gap => <section className="reference-gap" key={gap.id} id={`report-gap-${gap.id}`}><h4>{gap.title}</h4><p><strong>필요한 자료</strong> {gap.missing}</p><p><strong>확인 방법</strong> {gap.check}</p>{gap.chapterId && <button onClick={() => follow(() => onReport(gap.chapterId!))}>{gap.chapterTitle} 보기</button>}</section>)}</section>}
      <nav className="reference-related" aria-label="관련 자료"><h3>관련 자료</h3>
        {context.slides?.map(id => {
          const slide = briefingSlides.find(item => item.id === id);
          if (!slide) return null;
          const current = currentBriefingSlides.findIndex(item => item.id === id);
          const location = current >= 0 ? `이번 발표 ${current + 1}장` : `${["post-r3", "technical-rationale"].includes(slide.group) ? "이전 로컬 검토" : "지난 자료"} · ${milestones.find(item => item.id === slide.group)?.label ?? (slide.group === "post-r3" ? "웹 사용 흐름" : slide.group === "technical-rationale" ? "관찰과 관리 설계" : "서비스 개요")} · ${archivedBriefingSlides.findIndex(item => item.id === id) + 1}장`;
          return <button key={id} onClick={() => follow(() => onSlide(id))}>{location} · {slide.title.replace(/\n/g, " ")}</button>;
        })}
        {context.detail && <button onClick={() => follow(() => onDetail(context.detail!))}>관련 상세 설명</button>}
        {context.scenarios?.map(id => <button key={id} onClick={() => follow(() => onDetail("scenarios", id))}>{id} 사용자 시나리오</button>)}
        <button onClick={() => follow(onTimeline)}>전체 타임라인</button>
      </nav>
    </div>
  </dialog>;
}
