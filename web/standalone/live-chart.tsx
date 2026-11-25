import { useEffect, useRef, useState } from "react";
import {
  dateTime,
  deviceLabel,
  commandLabels,
  metrics,
  segments,
  type Cage,
  type HistoryData,
  type Sensor,
} from "./live-data";

const colors = [
  "#274b36",
  "#50778a",
  "#927140",
  "#765b83",
  "#707c43",
  "#955e5c",
];
function historySourceLabel(source: string | undefined) {
  if (source === "sensor") return "센서 실측";
  if (source === "simulation") return "가상 데이터";
  return "출처 미확인";
}
export function LiveChart({
  data,
  sensors,
  selected,
  cage,
  compact = false,
}: {
  compact?: boolean;
  data: HistoryData;
  sensors: Sensor[];
  selected: string;
  cage: Cage;
}) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const chart = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ width: 880, height: 248 });
  const color = (id: string) => colors[Math.max(0, sensors.findIndex((sensor) => sensor.id === id)) % colors.length];
  const visible = sensors.filter(
    (s) => selected === "all" || s.id === selected,
  );
  const series = visible.map((s) => ({
    sensor: s,
    parts: segments(data.points, s.id, cage.staleAfterSeconds),
  }));
  const values = series.flatMap((s) =>
    s.parts.flatMap((p) => p.map((v) => v.value)),
  );
  const hasValues = values.length > 0;
  useEffect(() => {
    if (!hasValues || !chart.current) return;
    const observer = new ResizeObserver(([entry]) => {
      const next = { width: Math.max(240, Math.round(entry.contentRect.width)), height: Math.max(160, Math.round(entry.contentRect.height)) };
      setSize((previous) => previous.width === next.width && previous.height === next.height ? previous : next);
    });
    observer.observe(chart.current);
    return () => observer.disconnect();
  }, [hasValues]);
  if (!hasValues)
    return (
      <div className="live-empty">선택한 기간에 유효한 측정값이 없습니다.</div>
    );
  const lower = values.reduce((a, b) => Math.min(a, b), Infinity),
    upper = values.reduce((a, b) => Math.max(a, b), -Infinity),
    padding = Math.max((upper - lower) * 0.15, 1);
  const min = lower - padding,
    max = upper + padding;
  const left = Math.max(52, Math.max(min.toFixed(1).length, max.toFixed(1).length) * 9 + 12),
    top = 18,
    width = size.width - left - 24,
    height = size.height - top - 32;
  const start = Date.parse(data.start),
    end = Date.parse(data.end);
  const x = (at: string) =>
    left + ((Date.parse(at) - start) / (end - start)) * width;
  const y = (value: number) => top + ((max - value) / (max - min)) * height;
  const point =
    data.points.find((p) => p.eventId === activeId) || data.points.at(-1);
  const sources = [...new Set(data.points.map((p) => p.data_source))];
  const sourceLabels = [...new Set(sources.map(historySourceLabel))];
  const ticks = Array.from({ length: 5 }, (_, i) => i / 4);
  return (
    <>
      <p className="live-note">
        이력 출처: {sourceLabels.join(" · ")}
        {sources.length > 1 && " · 여러 출처가 섞인 이력"}
      </p>
      <svg
        ref={chart}
        className="live-chart"
        viewBox={`0 0 ${size.width} ${size.height}`}
        role="img"
        aria-label={`${metrics.find((m) => m.unit === sensors[0]?.unit)?.name || "환경"} 측정 이력. 선은 미수신·센서 오류 또는 출처 변경 지점에서 끊깁니다. 아래 시각 선택과 수치 표에서 값과 출처를 확인할 수 있습니다.`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={left}
              x2={left + width}
              y1={top + t * height}
              y2={top + t * height}
              stroke="#dce3d7"
            />
            <text x={left - 10} y={top + t * height + 4} textAnchor="end">
              {(max - t * (max - min)).toFixed(1)}
            </text>
            {(size.width >= 480 || t === 0 || t === 0.5 || t === 1) && <text x={left + t * width} y={size.height - 8} textAnchor={t === 1 ? "end" : t === 0 ? "start" : "middle"}>
              {dateTime(
                new Date(start + t * (end - start)).toISOString(),
                true,
              ).slice(0, 5)}
            </text>}
          </g>
        ))}
        {data.commands.map((command) => (
          <line
            key={command.id}
            x1={x(command.at)}
            x2={x(command.at)}
            y1={top}
            y2={top + height}
            stroke="#a2ada0"
            strokeDasharray="3 4"
          >
            <title>
              {deviceLabel(command.actuator)} · {commandLabels[command.status]}{" "}
              · {dateTime(command.at)}
            </title>
          </line>
        ))}
        {series.map(({ sensor, parts }) => (
          <g
            key={sensor.id}
            stroke={color(sensor.id)}
            fill="none"
            strokeWidth="2"
          >
            {parts.map((part, n) =>
              part.length === 1 ? (
                <circle
                  key={n}
                  cx={x(part[0].at)}
                  cy={y(part[0].value)}
                  r="3"
                  fill={color(sensor.id)}
                />
              ) : (
                <path
                  key={n}
                  d={part
                    .map((p, j) => `${j ? "L" : "M"}${x(p.at)},${y(p.value)}`)
                    .join(" ")}
                />
              ),
            )}
          </g>
        ))}
        {point && (
          <line
            x1={x(point.at)}
            x2={x(point.at)}
            y1={top}
            y2={top + height}
            stroke="#284232"
            strokeDasharray="5 4"
          />
        )}
      </svg>
      <div className="live-chart-readout">
        <label>
          측정 시각
          <select
            value={point?.eventId || ""}
            onChange={(e) => setActiveId(e.target.value)}
          >
            {data.points.map((p) => (
              <option key={p.eventId} value={p.eventId}>
                {dateTime(p.at)} · {historySourceLabel(p.data_source)} · {p.eventId.slice(0, 6)}
              </option>
            ))}
          </select>
        </label>
        <p className="live-note">선택 출처: {historySourceLabel(point?.data_source)}</p>
        <div className="live-legend">
          {visible.map((sensor) => {
            const reading = point?.readings[sensor.id];
            return (
              <span key={sensor.id}>
                <i style={{ background: color(sensor.id) }} />
                <strong>{sensor.id}</strong>{" "}
                {reading?.quality === "valid" && reading.value !== null
                  ? reading.value.toFixed(1)
                  : "—"}{" "}
                {metrics.find((m) => m.unit === sensor.unit)?.symbol}
              </span>
            );
          })}
        </div>
      </div>
      <p className="live-note">
        선은 미수신·센서 오류 또는 출처 변경 지점에서 끊깁니다.
        {!compact && " 점선은 장치 명령 기록이며, 처리 결과는 기록에서 확인하세요."}
      </p>
      {!compact && data.commands.length > 0 && (
        <details>
          <summary>이 기간의 장치 기록 {data.commands.length}건</summary>
          <ul className="live-rows">
            {data.commands.map((command) => (
              <li key={command.id}>
                <span>
                  {deviceLabel(command.actuator)} ·{" "}
                  {commandLabels[command.status]}
                </span>
                <time>{dateTime(command.at)}</time>
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
