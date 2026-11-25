import { useState } from "react";
import { ChevronRight, History, Search } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "../components/ui/sheet";
import {
  commandLabels,
  dateTime,
  deviceLabel,
  qualityLabels,
  type Cage,
  type Command,
  type Point,
  type RecordItem,
} from "./live-data";
import { useLiveQuery } from "./use-live-query";
import { Panel, Empty, Notice, QueryNotice } from "./live-panels";

function recordTitle(record: RecordItem) {
  if (record.kind === "command.updated") {
    const command = record.payload as Command;
    return {
      title: deviceLabel(command.actuator_id),
      detail: commandLabels[command.status] || command.status,
      kind: "명령",
    };
  }
  const point = record.payload as Point;
  const invalid = Object.values(point.readings).filter(
    (r) => r.quality !== "valid",
  ).length;
  return {
    title: invalid ? `센서 오류 ${invalid}개` : "환경 측정",
    detail: point.data_source === "simulation" ? "가상 데이터" : "센서 데이터",
    kind: "측정",
  };
}

export function Records({
  cage,
  compact = false,
  onOpen,
}: {
  cage: Cage;
  compact?: boolean;
  onOpen?: () => void;
}) {
  const [kind, setKind] = useState("all"),
    [search, setSearch] = useState(""),
    [keyword, setKeyword] = useState(""),
    [before, setBefore] = useState("");
  const [selected, setSelected] = useState<RecordItem | null>(null);
  const query = useLiveQuery<{ items: RecordItem[]; next: string | null }>(
    `/api/enclosures/${encodeURIComponent(cage.id)}/records/?kind=${kind}&q=${encodeURIComponent(keyword)}&before=${encodeURIComponent(before)}`,
  );
  const rows = query.data?.items.slice(0, compact ? 3 : 50) || [];
  return (
    <Panel
      title={compact ? "최근 기록" : "기록 조회"}
      icon={History}
      className={compact ? "live-recent-panel" : "live-history-panel"}
      action={compact ? <button onClick={onOpen}>전체 보기</button> : <span className="live-note">최신순</span>}
    >
      {!compact && (
        <form
          className="live-filters live-record-filters"
          onSubmit={(e) => {
            e.preventDefault();
            setKeyword(search);
            setBefore("");
          }}
        >
          <div className="live-segment" role="group" aria-label="기록 종류">
            {[["all", "전체"], ["telemetry.recorded", "환경 측정"], ["command.updated", "명령 처리"]].map(([value, label]) => (
              <button type="button" key={value} aria-pressed={kind === value} onClick={() => { setKind(value); setBefore(""); }}>{label}</button>
            ))}
          </div>
          <label className="live-search">
            키워드
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="조명, 장치 적용 확인, T1 등"
              maxLength={80}
            />
          </label>
          <button type="submit"><Search size={16} aria-hidden="true" />검색</button>
          {before && (
            <button type="button" onClick={() => setBefore("")}>
              최신 기록
            </button>
          )}
        </form>
      )}
      <QueryNotice query={query} />
      {!rows.length ? (
        <Empty>
          {query.error && !query.data ? "기록을 확인할 수 없습니다." : query.data
            ? "조건에 맞는 수신 기록이 없습니다."
            : "기록을 불러오는 중입니다."}
        </Empty>
      ) : (
        <ul className="live-records">
          {rows.map((record) => {
            const label = recordTitle(record);
            return (
              <li key={record.id}>
                <button onClick={() => setSelected(record)}>
                  <span className="live-record-kind">{label.kind}</span>
                  <span className="live-record-copy">
                    <strong>{label.title}</strong>
                    <small>{label.detail}</small>
                  </span>
                  <time dateTime={record.at}>{dateTime(record.at)}</time>
                  <ChevronRight size={18} className="live-record-arrow" aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {!compact && query.data?.next && (
        <button onClick={() => setBefore(query.data!.next!)}>이전 기록</button>
      )}
      {!compact && (
        <p className="live-note">
          이상 알림의 확인·복구 기록은 연동 예정입니다.
        </p>
      )}
      <Sheet
        open={!!selected && !!query.data}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <SheetContent className="live-record-detail">
          <SheetHeader>
            <SheetTitle>
              {selected ? recordTitle(selected).title : "기록 상세"}
            </SheetTitle>
            <SheetDescription>
              {selected
                ? `${recordTitle(selected).detail} · ${dateTime(selected.at)} KST`
                : ""}
            </SheetDescription>
          </SheetHeader>
          {selected && (
            <div className="live-detail-body">
              <dl className="live-description">
                <dt>대상</dt>
                <dd>{cage.name}</dd>
                <dt>서버 수신</dt>
                <dd>{dateTime(selected.serverReceivedAt)}</dd>
                <dt>기록 ID</dt>
                <dd>{selected.id}</dd>
              </dl>
              {selected.kind === "command.updated" ? (
                <CommandDetail command={selected.payload as Command} />
              ) : (
                <>
                  <p>
                    측정 시각{" "}
                    {dateTime(
                      (selected.payload as Point & { sampled_at: string })
                        .sampled_at,
                    )}
                  </p>
                  <ul className="live-rows">
                    {Object.entries((selected.payload as Point).readings).map(
                      ([id, reading]) => (
                        <li key={id}>
                          <strong>{id}</strong>
                          <span>
                            {reading.value ?? "—"} ·{" "}
                            {qualityLabels[reading.quality]}
                          </span>
                        </li>
                      ),
                    )}
                  </ul>
                </>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </Panel>
  );
}
function CommandDetail({ command }: { command: Command }) {
  return (
    <dl className="live-description">
      <dt>요청</dt>
      <dd>
        {command.action === "on" ? `${command.duration_s}초 켜기` : "끄기"}
      </dd>
      <dt>처리 상태</dt>
      <dd>{commandLabels[command.status] || command.status}</dd>
      <dt>장치 응답 시각</dt>
      <dd>{dateTime(command.acknowledged_at)}</dd>
      <dt>적용 시각</dt>
      <dd>{dateTime(command.applied_at)}</dd>
      <dt>사유</dt>
      <dd>{command.reason || "—"}</dd>
    </dl>
  );
}
