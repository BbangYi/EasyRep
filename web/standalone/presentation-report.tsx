import { useState } from "react";
import { reportChapters, reportSources, type ReportSection } from "./presentation-report-content";
import { milestones } from "./presentation-briefing-content";
import type { ReferenceContext } from "./presentation-references";
import overviewLayout from "../public/presentation/research-layout-20261105.jpg?url";
import "./presentation-report.css";

export default function PresentationReport({ selected, onSelect, onReferences }: {
  selected: string | null;
  onSelect: (id: string | null) => void;
  onReferences: (context: ReferenceContext) => void;
}) {
  const [contentsOpen, setContentsOpen] = useState(false);
  const chapter = reportChapters.find(item => item.id === selected);
  const chapterIndex = reportChapters.findIndex(item => item.id === selected);
  function selectChapter(id: string | null) {
    onSelect(id);
    setContentsOpen(false);
    requestAnimationFrame(() => {
      const target = document.getElementById("report-reading-title");
      target?.focus({ preventScroll: true });
      target?.scrollIntoView({ block: "start", behavior: "instant" });
    });
  }

  return <section className="report-page" aria-labelledby="report-title">
    <header className="report-header"><h2 id="report-title" tabIndex={-1}>결과보고서 개요</h2><p className="report-document-state">문서 상태: 초안 <span>자료 기준: {selected === null || ["background", "system", "results", "deliverables"].includes(selected ?? "") ? "2026.11.07" : "2026.11.06"}</span></p></header>
    <div className="report-layout">
      <aside className="report-contents">
        <button className="report-contents-toggle" aria-expanded={contentsOpen} aria-controls="report-contents-list" onClick={() => setContentsOpen(!contentsOpen)}>보고서 목차 {contentsOpen ? "접기" : "펼치기"}</button>
        <nav id="report-contents-list" className={contentsOpen ? "is-open" : ""} aria-label="결과보고서 목차">
          <button aria-current={!chapter ? "page" : undefined} onClick={() => selectChapter(null)}>보고서 개요</button>
          <ol>{reportChapters.map((item, i) => <li key={item.id}><button aria-current={selected === item.id ? "page" : undefined} onClick={() => selectChapter(item.id)}><span>{i + 1}.</span> {item.title}</button></li>)}</ol>
        </nav>
      </aside>
      <article className="report-reading" aria-labelledby="report-reading-title" data-report-chapter={chapter?.id ?? "overview"}>
        {!chapter ? <>
          <h3 id="report-reading-title" tabIndex={-1}>사육장 하나의 환경과 관리 이력</h3>
          <p className="report-summary">EasyRep은 센서가 보낸 환경 정보와 사람이 남긴 관리 기록을 같은 사육장에 연결합니다.</p>
          <ol className="report-service-flow" aria-label="개인 사육자의 사용 흐름">{[["환경 확인", "최근 측정 시각과 위치별 환경"],["과거 기록 조회", "기간·측정 시점을 골라 이전 기록 확인"],["급여·관리 내역", "마지막으로 직접 남긴 기록 조회"]].map(([title,text]) => <li key={title}><strong>{title}</strong><p>{text}</p></li>)}</ol>
          <p className="report-figure-caption">현재 웹 기능을 이용한 설계 시나리오. 사용자 효과를 측정한 결과는 아닙니다.</p>
          <p>센서 설치 전에는 급여·청소 기록부터 남깁니다. 설치 후에는 측정 시각과 기간 이력을 확인하고, 공간 화면에서 센서가 읽은 지점과 그 사이를 계산한 영역을 구분합니다.</p>
          <section className="report-overview-system"><div><h4>센서와 공간 표시, 영상·분무 연구</h4><p>HabitatOS 연구는 환경 예측, 개체 탐지·추적, 외관 관찰·탈피 예측, 두 영상의 좌표 계산과 조건부 분무를 다룹니다. 현재 웹의 조회 기능과 별도 연구 실행 경로의 입력·결과를 구분해 정리했습니다.</p><button onClick={() => selectChapter("system")}>시스템 구성</button><button onClick={() => selectChapter("results")}>실험 결과</button></div><figure><img src={overviewLayout} width="1280" height="720" alt="상단 사육 공간과 하부 물통·펌프를 배치한 Constructa 모델" /><figcaption>2026.11.05 개인 사육장 가상 배치. 실물 통합 완료 사진이 아닙니다.</figcaption></figure></section>
          <section className="report-overview-progress"><h4>제작·개발 경과</h4><ol>{milestones.map(item => <li key={item.id}><time dateTime={item.date}>{item.label}</time><div><strong>{item.title}</strong><p>{item.result}</p></div></li>)}</ol><button onClick={() => selectChapter("deliverables")}>결과물 구성</button></section>
        </> : <>
          <p className="report-chapter-number">{chapterIndex + 1}장</p><h3 id="report-reading-title" tabIndex={-1}>{chapter.title}</h3><p className="report-summary">{chapter.summary}</p>
          {chapter.sections.map((section, i) => <section className="report-section" key={section.title} aria-labelledby={`report-section-${chapter.id}-${i}`}>
            <h4 id={`report-section-${chapter.id}-${i}`}>{chapterIndex + 1}.{i + 1} {section.title}</h4>
            {section.paragraphs.map(text => <p key={text}>{text}</p>)}
            {section.flow && <ol className="report-flow">{section.flow.map(step => <li key={step.title}><strong>{step.title}</strong><p>{step.text}</p></li>)}</ol>}
            {section.table && <ReportTable table={section.table} />}
            {section.figures && <div className="report-figures">{section.figures.map(figure => <figure key={figure.src}><img src={figure.src} alt={figure.alt} width={figure.width} height={figure.height} loading="lazy" /><figcaption>{figure.caption}</figcaption></figure>)}</div>}
            {section.sources.length > 0 && <button className="report-citation" aria-label={`${section.title} 참고 자료`} onClick={() => onReferences({title: `${chapterIndex + 1}장 · ${section.title}`, sourceIds: section.sources, initialSource: section.sources[0], gaps: chapter.gaps, slides: chapter.slides, scenarios: chapter.scenarios, detail: chapter.detail})}>[{section.sources.map(id => Object.keys(reportSources).indexOf(id) + 1).join(", ")}]</button>}
          </section>)}
          <nav className="report-chapter-paging" aria-label="보고서 장 이동"><button disabled={chapterIndex === 0} onClick={() => selectChapter(reportChapters[chapterIndex - 1].id)}>이전 장</button><button onClick={() => selectChapter(null)}>보고서 개요</button><button disabled={chapterIndex === reportChapters.length - 1} onClick={() => selectChapter(reportChapters[chapterIndex + 1].id)}>다음 장</button></nav>
        </>}
      </article>
    </div>
  </section>;
}

function ReportTable({ table }: { table: NonNullable<ReportSection["table"]> }) {
  return <table className="report-table"><caption>{table.caption}</caption><thead><tr>{table.headings.map(heading => <th key={heading} scope="col">{heading}</th>)}</tr></thead><tbody>{table.rows.map(row => <tr key={row[0]}>{row.map((cell, i) => i === 0 ? <th key={i} scope="row">{cell}</th> : <td key={i} data-label={table.headings[i]}>{cell}</td>)}</tr>)}</tbody></table>;
}
