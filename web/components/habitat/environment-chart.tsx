"use client";

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowUpRight,
  Clock3,
  Droplets,
  Fan,
  Sun,
  Info,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Unregistered } from "./unregistered";
import { Slider } from "@/components/ui/slider";
import {
  sensors,
  type Sensor,
  metricInfo,
  type DemoState,
  type Metric,
} from "@/lib/habitat/demo";
import {
  DEMO_NOW,
  inspectSamples,
  closestSampleIndex,
  receivedAt,
  formatValue,
  fullTime,
  getEvents,
  getSamples,
  sensorLineStyle,
  timeLabel,
  type Period,
  type Sample,
} from "@/lib/habitat/model";

export type EnvironmentSelection = {
  metric: Metric;
  period: Period;
  sensor: string;
};

export function EnvironmentChart({
  state,
  sensorSet = sensors,
  selection,
  onChange,
  detailed = false,
  onDetail,
  onManage,
}: {
  state: DemoState;
  sensorSet?: Sensor[];
  selection: EnvironmentSelection;
  onChange: (selection: EnvironmentSelection) => void;
  detailed?: boolean;
  onDetail?: () => void;
  onManage: () => void;
}) {
  // Cursor movement reuses the same history and statistics.
  const rows = useMemo(
    () => getSamples(state, selection.period, sensorSet),
    [state, selection.period, sensorSet],
  );
  const available = useMemo(
    () => sensorSet.filter((sensor) => sensor.metric === selection.metric),
    [sensorSet, selection.metric],
  );
  const visible = useMemo(
    () => available.filter((sensor) => selection.sensor === "all" || sensor.id === selection.sensor),
    [available, selection.sensor],
  );
  const context = `${state}:${selection.metric}:${selection.period}:${selection.sensor}`;
  const [cursor, setCursor] = useState<{
    context: string;
    time: number;
  } | null>(null);
  const statistics = useMemo(
    () => inspectSamples(rows, visible.map((sensor) => sensor.id)),
    [rows, visible],
  );
  const selectedTime = cursor?.context === context ? cursor.time : null;
  const cursorIndex =
    selectedTime === null
      ? Math.max(
          0,
          statistics.latestIndex >= 0
            ? statistics.latestIndex
            : rows.length - 1,
        )
      : closestSampleIndex(rows, selectedTime);
  function selectTime(time: number) {
    const index = closestSampleIndex(rows, time);
    if (index >= 0) setCursor({ context, time: rows[index].time });
  }
  const row = rows[cursorIndex];
  const events = useMemo(
    () => getEvents(state, selection.period),
    [state, selection.period],
  );
  const unit = metricInfo[selection.metric].unit;
  function changeMetric(metric: Metric) {
    onChange({ ...selection, metric, sensor: "all" });
    setCursor(null);
  }
  function readout(sample: Sample | undefined, tooltip = false) {
    if (!sample) return null;
    return (
      <div className={tooltip ? "chart-tooltip" : "chart-readout"}>
        <div className="readout-time">
          <Clock3 size={12} />
          {timeLabel(sample.time)} <span>KST</span>
        </div>
        <div className="readout-values">
          {visible.map((sensor) => (
            <span key={sensor.id}>
              <b>{sensor.id}</b>{" "}
              {formatValue(sample[sensor.id], selection.metric)}{" "}
              {sample[sensor.id] !== null ? unit : <em>미수신</em>}
            </span>
          ))}
        </div>
      </div>
    );
  }
  return (
    <section
      className={`panel chart-panel ${detailed ? "detailed-chart" : ""}`}
      aria-label="환경 실측 이력"
    >
      <div className="panel-heading">
        <div>
          <h2>{detailed ? "기간별 환경 이력" : "최근 환경 변화"}</h2>
          <p>{fullTime(DEMO_NOW)}</p>
        </div>
        {onDetail && (
          <button className="text-button" onClick={onDetail}>
            환경 상세 <ArrowUpRight size={14} />
          </button>
        )}
      </div>
      {state === "unregistered" ? (
        <Unregistered onManage={onManage} />
      ) : (
        <Tabs
          value={selection.metric}
          onValueChange={(value) => changeMetric(value as Metric)}
        >
          <div className="chart-controls">
            <TabsList className="metric-tabs" aria-label="환경 항목">
              {(
                [
                  "temperature",
                  "humidity",
                  ...(detailed ? ["light"] : []),
                ] as Metric[]
              ).map((metric) => (
                <TabsTrigger key={metric} value={metric}>
                  {metricInfo[metric].label}
                </TabsTrigger>
              ))}
            </TabsList>
            {detailed && (
              <div className="sensor-select-row">
                <span>표시할 센서</span>
                <Select
                  value={selection.sensor}
                  onValueChange={(sensor) => onChange({ ...selection, sensor })}
                >
                  <SelectTrigger aria-label="표시할 센서">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">
                      전체 센서 ({available.length})
                    </SelectItem>
                    {available.map((sensor) => (
                      <SelectItem value={sensor.id} key={sensor.id}>
                        {sensor.id} · {sensor.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <RadioGroup
              value={String(selection.period)}
              onValueChange={(value) => {
                onChange({ ...selection, period: Number(value) as Period });
                setCursor(null);
              }}
              className="period-options"
              aria-label="조회 기간"
            >
              {[1, 6, 24].map((period) => (
                <label
                  className={selection.period === period ? "active" : ""}
                  key={period}
                >
                  <RadioGroupItem
                    value={String(period)}
                    aria-label={`최근 ${period}시간`}
                  />
                  {period}시간
                </label>
              ))}
            </RadioGroup>
          </div>
          <TabsContent value={selection.metric} className="chart-content">
            {detailed && (
              <details className="chart-statistics">
                <summary>기간 통계</summary>
                <dl
                  className="period-summary"
                  aria-label="선택한 센서의 기간 요약"
                >
                  <div>
                    <dt>기간 최저</dt>
                    <dd>
                      {formatValue(statistics.min, selection.metric)}{" "}
                      <small>{unit}</small>
                    </dd>
                  </div>
                  <div>
                    <dt>기간 최고</dt>
                    <dd>
                      {formatValue(statistics.max, selection.metric)}{" "}
                      <small>{unit}</small>
                    </dd>
                  </div>
                  <div>
                    <dt>수신 측정값</dt>
                    <dd className="sample-count">
                      {statistics.received}{" "}
                      <small>/ {statistics.expected}개</small>
                    </dd>
                  </div>
                </dl>
              </details>
            )}
            <div className="chart-analysis-layout">
              <div className="chart-plot-section">
                <div className="chart-axis-unit">
                  {metricInfo[selection.metric].label} ({unit})
                  {state === "offline" && (
                    <span className="warning-text">
                      오래된 데이터 · {timeLabel(receivedAt(state))} 이후 미수신
                    </span>
                  )}
                </div>
                <div
                  className="chart-canvas"
                  role="img"
                  aria-label={`${metricInfo[selection.metric].label} 최근 ${selection.period}시간 실측 그래프. 빈 구간은 미수신입니다. 아래 시간 탐색과 센서 수치로 같은 데이터를 확인할 수 있습니다.`}
                >
                  <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                    <LineChart
                      data={rows}
                      margin={{ top: 18, right: 15, left: -20, bottom: 0 }}
                      onClick={(event) => {
                        if (event.activeLabel !== undefined)
                          selectTime(Number(event.activeLabel));
                      }}
                    >
                      <CartesianGrid
                        vertical={false}
                        stroke="var(--border-subtle)"
                        strokeDasharray="3 3"
                      />
                      <XAxis
                        dataKey="time"
                        type="number"
                        domain={[DEMO_NOW - selection.period * 3_600_000, DEMO_NOW]}
                        tickFormatter={(time) => timeLabel(time)}
                        axisLine={false}
                        tickLine={false}
                        minTickGap={32}
                        tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
                        tickCount={5}
                        dy={9}
                      />
                      <YAxis
                        domain={
                          selection.metric === "temperature"
                            ? [22, 28]
                            : selection.metric === "humidity"
                              ? [45, 85]
                              : [200, 400]
                        }
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
                        tickCount={4}
                        width={53}
                      />
                      <Tooltip
                        content={({ active, payload }) =>
                          active && payload?.[0]
                            ? readout(payload[0].payload as Sample, true)
                            : null
                        }
                        cursor={{ stroke: "var(--ring)", strokeDasharray: "3 3" }}
                      />
                      {events.map((event, index) => (
                        <ReferenceLine
                          key={event.id}
                          x={event.time}
                          stroke="var(--input)"
                          strokeDasharray="3 4"
                          label={{
                            value: event.label,
                            position: "insideTopLeft",
                            dy: index % 2 === 0 ? 0 : 16,
                            fill: "var(--forest-bark)",
                            fontSize: 12,
                          }}
                        />
                      ))}
                      {selectedTime !== null && row && (
                        <ReferenceLine
                          x={row.time}
                          stroke="var(--primary)"
                          strokeWidth={1.5}
                        />
                      )}
                      {visible.map((sensor) => {
                        const style = sensorLineStyle(sensor.id, sensorSet);
                        return (
                          <Line
                            key={sensor.id}
                            name={`${sensor.id} ${sensor.name}`}
                            dataKey={sensor.id}
                            type="linear"
                            stroke={style.color}
                            strokeWidth={selection.sensor === "all" ? 1.8 : 2.5}
                            strokeDasharray={style.dash}
                            dot={false}
                            connectNulls={false}
                            isAnimationActive={false}
                            activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }}
                          />
                        );
                      })}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <div className="timeline-explorer">
                  <div className="timeline-heading">
                    <label id={detailed ? "detail-time-label" : "home-time-label"}>
                      {selectedTime === null ? "마지막 실측" : "선택 시각"}{" "}
                      <strong>{row ? timeLabel(row.time) : "—"}</strong>
                    </label>
                    <button
                      className="text-button"
                      onClick={() => setCursor(null)}
                      disabled={selectedTime === null}
                    >
                      최근 측정으로
                    </button>
                  </div>
                  <Slider
                    ref={(root) => {
                      const thumb = root?.querySelector('[role="slider"]');
                      thumb?.setAttribute("aria-label", "측정시각 탐색");
                      thumb?.setAttribute(
                        "aria-valuetext",
                        row ? timeLabel(row.time) : "측정 없음",
                      );
                    }}
                    aria-labelledby={
                      detailed ? "detail-time-label" : "home-time-label"
                    }
                    min={0}
                    max={Math.max(1, rows.length - 1)}
                    step={1}
                    value={[cursorIndex]}
                    onValueChange={(values) => {
                      const sample = rows[values[0]];
                      if (sample) selectTime(sample.time);
                    }}
                    aria-valuetext={row ? timeLabel(row.time) : undefined}
                  />
                  <div className="chart-legends" aria-label="센서별 측정값과 범례">
                    {available.map((sensor) => {
                      const style = sensorLineStyle(sensor.id, sensorSet);
                      return (
                        <button
                          key={sensor.id}
                          aria-pressed={selection.sensor === sensor.id}
                          aria-label={`${sensor.id} ${sensor.name}, ${row?.[sensor.id] == null ? "미수신" : `${formatValue(row[sensor.id], selection.metric)} ${unit}`}`}
                          onClick={() =>
                            onChange({
                              ...selection,
                              sensor:
                                selection.sensor === sensor.id ? "all" : sensor.id,
                            })
                          }
                          className={
                            selection.sensor !== "all" &&
                            selection.sensor !== sensor.id
                              ? "legend-dim"
                              : ""
                          }
                        >
                          <svg width="18" height="6" aria-hidden="true">
                            <line
                              x1="0"
                              x2="18"
                              y1="3"
                              y2="3"
                              stroke={style.color}
                              strokeWidth="2"
                              strokeDasharray={style.dash}
                            />
                          </svg>
                          <b>{sensor.id}</b>
                          <span className="legend-name">{sensor.name}</span>
                          <strong className="legend-value">
                            {row?.[sensor.id] == null
                              ? "미수신"
                              : `${formatValue(row[sensor.id], selection.metric)} ${unit}`}
                          </strong>
                        </button>
                      );
                    })}
                    {selection.sensor !== "all" && (
                      <button
                        className="all-sensors"
                        onClick={() => onChange({ ...selection, sensor: "all" })}
                      >
                        전체 보기
                      </button>
                    )}
                  </div>
                </div>
                <div className="chart-footer">
                  <span>
                    <Info size={12} /> 빈 구간은 미수신 데이터
                  </span>
                  <span>
                    <Droplets size={12} /> 분무 <Fan size={12} /> 환기
                  </span>
                </div>
              </div>
              {detailed && (
                <div className="event-timeline">
                  <h3>장치 작동</h3>
                  {events.length ? (
                    events.map((event) => (
                      <button
                        key={event.id}
                        onClick={() => selectTime(event.time)}
                        aria-label={`${timeLabel(event.time)} ${event.label}, 가까운 측정시각 보기`}
                      >
                        {event.device === "mist" ? (
                          <Droplets size={14} />
                        ) : event.device === "fan" ? (
                          <Fan size={14} />
                        ) : (
                          <Sun size={14} />
                        )}
                        <time>{timeLabel(event.time)}</time>
                        <span>{event.detail.split(" · ")[1]}</span>
                        <ArrowUpRight size={12} aria-hidden="true" />
                      </button>
                    ))
                  ) : (
                    <p className="muted">
                      이 기간에 수신된 작동 기록이 없습니다.
                    </p>
                  )}
                </div>
              )}
            </div>
          </TabsContent>
        </Tabs>
      )}
    </section>
  );
}
