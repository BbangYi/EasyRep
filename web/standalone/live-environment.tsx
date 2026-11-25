import { useState } from "react";
import { HistoryOverview } from "./history-overview";
import { SpatialEnvironment } from "./live-spatial";
import { EnvironmentInsights } from "./environment-insights";
import type { EnvironmentMode } from "./live-route";
import { ChartNoAxesCombined, Thermometer, Radio, Download } from "lucide-react";
import {
  csvForHistory,
  historyForConfiguration,
  dateTime,
  metrics,
  qualityLabels,
  summary,
  type Cage,
  type HistoryData,
  type Unit,
} from "./live-data";
import { useLiveQuery } from "./use-live-query";
import { LiveChart } from "./live-chart";
import { Panel, Empty, Notice, QueryNotice, EnvironmentSummary } from "./live-panels";

export function EnvironmentWorkspace({ cage, mode, onModeChange, onManagement }: {
  cage: Cage; mode: EnvironmentMode; onModeChange: (mode: EnvironmentMode) => void; onManagement: () => void;
}) {
  return <div className="live-environment-workspace">
    <div className="live-segment live-analysis-modes" role="group" aria-label="환경 분석 구분">
      {([["measured", "현재·기간 추세"], ...(cage.spatialLayout ? [["spatial", "공간 온도"]] as const : [])] as const).map(([value, label]) =>
        <button key={value} aria-pressed={mode === value} onClick={() => onModeChange(value)}>{label}</button>)}
    </div>
    {mode === "measured" ? <Environment cage={cage} /> : mode === "spatial" ? <SpatialEnvironment cage={cage} /> : <EnvironmentInsights cage={cage} mode={mode} onMeasured={() => onModeChange("measured")} onManagement={onManagement} />}
  </div>;
}

export function Environment({
  cage,
  compact = false,
  onOpen,
}: {
  cage: Cage;
  compact?: boolean;
  onOpen?: () => void;
}) {
  const [rawOpen, setRawOpen] = useState(false);
  const [unit, setUnit] = useState<Unit>("degC");
  const [hours, setHours] = useState(6);
  const [selected, setSelected] = useState("all");
  const [{ anchor, before }, setPage] = useState({ anchor: "", before: "" });
  const query = useLiveQuery<HistoryData>(
    compact || rawOpen ? `/api/enclosures/${encodeURIComponent(cage.id)}/history/?hours=${hours}${anchor ? `&end=${encodeURIComponent(anchor)}` : ""}${before ? `&before=${encodeURIComponent(before)}` : ""}` : null,
  );
  const displayedMetrics = metrics.filter(
    (metric) => metric.unit !== "lux" || summary(cage, metric.unit).valid > 0,
  );
  const activeUnit = displayedMetrics.some((metric) => metric.unit === unit) ? unit : "degC";
  const sensors = cage.sensors.filter((s) => s.unit === activeUnit);
  if (selected !== "all" && !sensors.some((sensor) => sensor.id === selected)) {
    // Reconcile before rendering children; removed IDs must not revive on later polls.
    setSelected("all");
  }
  const data = query.data
    ? historyForConfiguration(query.data, cage)
    : undefined;
  function download() {
    if (!data) return;
    const url = URL.createObjectURL(
      new Blob([csvForHistory(data, sensors, selected)], {
        type: "text/csv;charset=utf-8",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `EasyRep-${cage.cageId || cage.id}-${activeUnit}.csv`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div className={compact ? "live-chart-panel-wrap" : "live-environment-layout"}>
      {!compact && (
        <>
          <Panel
            title="현재 환경"
            icon={Thermometer}
            className="live-current-panel"
            action={<span className="live-note">기준 미설정</span>}
          >
            <EnvironmentSummary cage={cage} />
            <p className="live-note">
              측정 {dateTime(cage.sampledAt)} KST ·{" "}
              {cage.stale && cage.sampledAt
                ? "오래된 데이터"
                : "수신 상태 기준"}
            </p>
          </Panel>
        </>
      )}
      {!compact && <HistoryOverview cage={cage} environmentOnly />}
      <details className="live-raw-history" open={compact || rawOpen} onToggle={e => setRawOpen(e.currentTarget.open)}>
      {!compact && <summary>개별 측정 상세·CSV</summary>}
      <Panel
        title={compact ? "최근 환경 변화" : "환경 이력"}
        icon={ChartNoAxesCombined}
        className="live-environment-panel"
        action={
          compact ? (
            <button onClick={onOpen}>환경 상세</button>
          ) : (
            <button
              aria-label="현재 표시된 환경 이력 CSV 내려받기"
              onClick={download}
              disabled={!data?.points.length || !sensors.length}
            >
              <Download size={16} aria-hidden="true" />CSV
            </button>
          )
        }
      >
        <div className="live-filters live-environment-filters">
          <div className="live-segment" aria-label="환경 항목">
            {displayedMetrics.map((metric) => (
              <button
                key={metric.unit}
                aria-pressed={activeUnit === metric.unit}
                onClick={() => {
                  setUnit(metric.unit);
                  setSelected("all");
                }}
              >
                {metric.name}
              </button>
            ))}
          </div>
          <label>
            기간
            <select
              value={hours}
              onChange={(e) => {
                setHours(Number(e.target.value));
                setPage({ anchor: "", before: "" });
              }}
            >
              <option value={1}>최근 1시간</option>
              <option value={6}>최근 6시간</option>
              <option value={24}>최근 24시간</option>
            </select>
          </label>
          <label>
            센서
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="all">전체 센서</option>
              {sensors.map((s) => (
                <option key={s.id}>{s.id}</option>
              ))}
            </select>
          </label>
        </div>
        {!compact && !anchor && !data?.points.length && cage.stale && cage.sampledAt && (
          <p className="live-note">
            <button onClick={() => setPage({ anchor: cage.sampledAt!, before: "" })}>
              마지막 측정 시점 보기
            </button>
          </p>
        )}
        {anchor && (
          <Notice>
            {dateTime(anchor)}까지의 기록을 보고 있습니다.{" "}
            <button onClick={() => setPage({ anchor: "", before: "" })}>현재 시점</button>
          </Notice>
        )}
        {query.data &&
          data &&
          query.data.points.length !== data.points.length && (
            <Notice>
              현재 센서 구성과 다른 이력{" "}
              {query.data.points.length - data.points.length}건을 그래프·CSV에서
              제외했습니다. 원래 기록은 기록 메뉴에서 확인하세요.
            </Notice>
          )}
        <QueryNotice query={query} />
        {!data ? (
          <Empty>{query.error ? "환경 이력을 확인할 수 없습니다." : "환경 이력을 불러오는 중입니다."}</Empty>
        ) : (
          <>
            {compact && !data.points.length && cage.stale && cage.sampledAt && !anchor ? (
              <div className="live-empty">
                <p>선택한 기간에 새로운 측정값이 없습니다.</p>
                <button onClick={() => setPage({ anchor: cage.sampledAt!, before: "" })}>마지막 측정 보기</button>
              </div>
            ) : (
              <LiveChart data={data} sensors={sensors} selected={selected} cage={cage} compact={compact} />
            )}
            {data.truncated && (
              <Notice>
                표시 범위를 최근 {data.limit.toLocaleString()}개 측정으로
                제한했습니다. CSV도 현재 표시 범위만 포함합니다.
              </Notice>
            )}
            {data.commandsTruncated && (
              <Notice>
                장치 기록이 많아 500건까지 표시합니다. 기록 메뉴에서 이어서
                확인하세요.
              </Notice>
            )}
            {(data.next || data.olderThan) && (
              <button
                onClick={() =>
                  setPage({
                    anchor: data.next ? (data.olderThan ?? data.end) : new Date(Date.parse(data.olderThan!) - 1).toISOString(),
                    before: data.next || "",
                  })
                }
              >
                이전 측정 보기
              </button>
            )}
          </>
        )}
      </Panel>
      </details>
      {!compact && (
        <Panel
          title="센서별 측정값"
          icon={Radio}
          className="live-sensor-panel"
          action={<span className="live-note">설치 위치 미등록</span>}
        >
          {cage.sensors.length ? (
            <div className="live-sensors">
              {cage.sensors.map((sensor) => (
                <button
                  key={sensor.id}
                  aria-pressed={selected === sensor.id && activeUnit === sensor.unit}
                  onClick={() => {
                    setUnit(sensor.unit);
                    setSelected(sensor.id);
                    setRawOpen(true);
                  }}
                >
                  <strong>{sensor.id}</strong>
                  <span>
                    {sensor.quality === "valid" && sensor.value !== null
                      ? sensor.value.toFixed(1)
                      : "—"}{" "}
                    {metrics.find((m) => m.unit === sensor.unit)?.symbol}
                  </span>
                  <small>
                    {qualityLabels[sensor.quality] || sensor.quality}
                  </small>
                </button>
              ))}
            </div>
          ) : (
            <Empty>Pi에서 센서 구성을 수신하면 표시됩니다.</Empty>
          )}
        </Panel>
      )}
    </div>
  );
}
