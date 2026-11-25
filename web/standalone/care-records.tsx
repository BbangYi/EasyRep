import { useId, useState } from "react";
import { ChevronRight, NotebookPen, Plus } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../components/ui/sheet";
import type { AuthSession } from "../lib/habitat/session";
import { dateTime, type Cage } from "./live-data";
import { useLiveQuery } from "./use-live-query";
import { Panel, Empty, QueryNotice } from "./live-panels";
import { HistoryOverview } from "./history-overview";
import { Records } from "./live-records";
import type { RecordSection } from "./live-route";

type CareRecord = {
  id: string; kind: string; kindLabel: string; at: string; note: string;
  weightG: string | null; author: string; createdAt: string;
  voidedAt: string | null; voidedBy: string | null; voidReason: string;
};
const kinds = [["all", "전체 종류"], ["feeding", "급여"], ["cleaning", "청소"], ["shedding", "탈피"], ["weight", "체중"], ["note", "특이사항"]];

export function RecordWorkspace({ cage, session, section, onSectionChange }: { cage: Cage; session: AuthSession; section: RecordSection; onSectionChange: (section: RecordSection) => void }) {
  return <>
    <div className="live-segment" role="group" aria-label="기록 구분">
      <button aria-pressed={section === "overview"} onClick={() => onSectionChange("overview")}>종합 이력</button>
      <button aria-pressed={section === "care"} onClick={() => onSectionChange("care")}>사육 관리</button>
      <button aria-pressed={section === "device"} onClick={() => onSectionChange("device")}>센서·장치 기록</button>
    </div>
    {section === "overview" ? <HistoryOverview cage={cage} /> : section === "care" ? <CareRecords cage={cage} session={session} /> : <Records cage={cage} />}
  </>;
}

export function CareRecords({ cage, session, compact = false, onOpen }: { cage: Cage; session: AuthSession; compact?: boolean; onOpen?: () => void }) {
  const [filters, setFilters] = useState({ kind: "all", status: "active", from: "", to: "", q: "" });
  const [applied, setApplied] = useState(filters);
  const [cursors, setCursors] = useState<string[]>([""]);
  const before = cursors[cursors.length - 1];
  const [filtersOpen, setFiltersOpen] = useState(false);
  const filtersId = useId();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const params = new URLSearchParams({ ...applied, before });
  // Human entries do not need sensor-frequency polling. Manual refresh still works.
  const query = useLiveQuery<{ items: CareRecord[]; next: string | null }>(`/api/enclosures/${encodeURIComponent(cage.id)}/care/?${params}`, 60000);
  const records = query.data?.items.slice(0, compact ? 3 : 20) || [];
  const selected = query.data?.items.find((item) => item.id === selectedId);
  const canWrite = session.user.role !== "user";
  const createUrl = `/manage/enclosures/${encodeURIComponent(cage.id)}/care/new/`;
  function reset() {
    const empty = { kind: "all", status: "active", from: "", to: "", q: "" };
    setFilters(empty); setApplied(empty); setCursors([""]);
  }
  return <Panel title={compact ? "최근 사육 관리" : "사육 관리 기록"} icon={NotebookPen} className="live-care-panel" action={compact ? <button onClick={onOpen}>전체 보기</button> : canWrite ? <a className="live-button" href={createUrl}><Plus size={16} aria-hidden="true" />기록 작성</a> : <span className="live-note">조회 권한</span>}>
    {!compact && <>
    <div className="live-care-filter-heading">
      <button type="button" aria-expanded={filtersOpen} aria-controls={filtersId} onClick={() => setFiltersOpen(!filtersOpen)}>필터 {filtersOpen ? "접기" : "펼치기"}</button>
      <p className="live-note" aria-live="polite">{[
        kinds.find(([value]) => value === applied.kind)?.[1],
        applied.status === "active" ? "유효 기록" : applied.status === "voided" ? "취소 기록" : "취소 포함",
        (applied.from || applied.to) && `${applied.from || "시작일 제한 없음"} ~ ${applied.to || "오늘"}`,
        applied.q && `“${applied.q}”`,
      ].filter(Boolean).join(" · ")}</p>
    </div>
    <div id={filtersId} hidden={!filtersOpen}>
    <form className="live-care-filters" onSubmit={(event) => { event.preventDefault(); setApplied({ ...filters, q: filters.q.trim() }); setCursors([""]); }}>
      <label>종류<select value={filters.kind} onChange={(event) => setFilters({ ...filters, kind: event.target.value })}>{kinds.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>상태<select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}><option value="active">유효 기록</option><option value="all">취소 포함</option><option value="voided">취소 기록</option></select></label>
      <label>시작일<input type="date" value={filters.from} max={filters.to || undefined} onChange={(event) => setFilters({ ...filters, from: event.target.value })} /></label>
      <label>종료일<input type="date" value={filters.to} min={filters.from || undefined} onChange={(event) => setFilters({ ...filters, to: event.target.value })} /></label>
      <label className="live-care-search">내용 검색<input type="search" maxLength={80} placeholder="먹이, 청소 내용 등" value={filters.q} onChange={(event) => setFilters({ ...filters, q: event.target.value })} /></label>
      <div className="live-care-actions"><button type="submit">조회</button><button type="button" onClick={reset}>초기화</button></div>
    </form></div></>}
    <QueryNotice query={query} />
    {!records.length ? <Empty>{query.error && !query.data ? "기록을 확인할 수 없습니다." : query.data ? "조건에 맞는 관리 기록이 없습니다." : "관리 기록을 불러오는 중입니다."}</Empty> : <ul className="live-records">
      {records.map((record) => <li key={record.id}><button onClick={() => setSelectedId(record.id)}>
        <span className="live-record-kind">{record.kindLabel}</span>
        <span className="live-record-copy"><strong>{record.weightG !== null ? `${record.weightG} g` : record.note.slice(0, 90)}</strong><small>{record.voidedAt ? "취소됨 · " : ""}{record.author} · 직접 입력</small></span>
        <time dateTime={record.at}>{dateTime(record.at)}</time><ChevronRight className="live-record-arrow" size={18} aria-hidden="true" />
      </button></li>)}
    </ul>}
    <div className="live-care-actions">
      {compact && canWrite && <a className="live-button" href={createUrl}>기록 작성</a>}
      {!compact && before && <><button onClick={() => setCursors([""])}>최신 기록</button><button onClick={() => setCursors((previous) => previous.slice(0, -1))}>앞 페이지</button></>}
      {!compact && <span className="live-note" aria-live="polite">{cursors.length}페이지</span>}
      {!compact && query.data?.next && <button onClick={() => { const next = query.data?.next; if (next && !cursors.includes(next)) setCursors((previous) => [...previous, next]); }}>이전 기록</button>}
    </div>
    {!compact && <p className="live-note">발생 시각 최신순 · 한국 시간 · 직접 입력한 관리 기록입니다.</p>}
    <Sheet open={Boolean(selected)} onOpenChange={(open) => { if (!open) setSelectedId(null); }}>
      <SheetContent className="live-record-detail">
        <SheetHeader><SheetTitle>{selected?.kindLabel} 기록{selected?.voidedAt ? " · 취소됨" : ""}</SheetTitle><SheetDescription>{cage.name} · 직접 입력</SheetDescription></SheetHeader>
        {selected && <div className="live-detail-body">
          <dl className="live-description"><dt>발생 시각</dt><dd>{dateTime(selected.at)} KST</dd><dt>작성자</dt><dd>{selected.author}</dd><dt>등록 시각</dt><dd>{dateTime(selected.createdAt)} KST</dd>{selected.weightG !== null && <><dt>체중</dt><dd>{selected.weightG} g</dd></>}</dl>
          <p className="live-care-note">{selected.note || "추가 내용 없음"}</p>
          {selected.voidedAt ? <dl className="live-description"><dt>취소 시각</dt><dd>{dateTime(selected.voidedAt)} KST</dd><dt>취소자</dt><dd>{selected.voidedBy}</dd><dt>취소 사유</dt><dd>{selected.voidReason}</dd></dl> : canWrite && <a className="live-button" href={`/manage/enclosures/${encodeURIComponent(cage.id)}/care/${selected.id}/void/`}>잘못 입력한 기록 취소</a>}
        </div>}
      </SheetContent>
    </Sheet>
  </Panel>;
}
