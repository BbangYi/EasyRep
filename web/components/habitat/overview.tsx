"use client";

import {
  ArrowUpRight,
  CircleCheck,
  CircleAlert,
  Clock3,
  Droplets,
  Fan,
  Sun,
  Thermometer,
  WifiOff,
  MapPin,
  ChevronRight,
} from "lucide-react";
import {
  metricInfo,
  type DemoState,
  type Metric,
  type Sensor,
  sensors,
} from "@/lib/habitat/demo";
import {
  devices,
  formatValue,
  getReadings,
  getRecords,
  receivedAt,
  summarize,
  timeLabel,
  type RecordEntry,
  type SensorReading,
} from "@/lib/habitat/model";
import { Unregistered } from "./unregistered";

export function ActiveAlert({
  state,
  gateway,
  onDetail,
}: {
  state: DemoState;
  gateway?: string;
  onDetail: (record: RecordEntry) => void;
}) {
  if (state !== "offline" && state !== "sensor-error") return null;
  const record = getRecords(state, gateway).find((record) =>
    record.id.startsWith("active-"),
  )!;
  return (
    <section className="active-alert" aria-label="활성 알림" role="status">
      {state === "offline" ? <WifiOff size={19} /> : <CircleAlert size={19} />}
      <div>
        <strong>{record.title}</strong>
        <p>
          {state === "offline"
            ? "오래된 데이터입니다. 게이트웨이 연결을 확인하세요."
            : "T3 · 중앙 센서 확인 필요. 요약에서 제외했습니다."}
        </p>
        <span>
          {record.target} · {timeLabel(record.time)} 발생
        </span>
      </div>
      <button onClick={() => onDetail(record)}>
        상세 보기 <ChevronRight size={14} />
      </button>
    </section>
  );
}

export function EnvironmentSummary({
  state,
  sensorSet = sensors,
  onMetric,
  onManage,
  selectedMetric,
}: {
  state: DemoState;
  sensorSet?: Sensor[];
  selectedMetric?: Metric;
  onMetric: (metric: Metric) => void;
  onManage: () => void;
}) {
  const readings = getReadings(state, sensorSet);
  const offline = state === "offline";
  return (
    <section aria-label="현재 환경">
      <div className="section-heading">
        <h2>현재 환경</h2>
        <span className="small muted">기준 미설정</span>
      </div>
      {state === "unregistered" ? (
        <div className="panel summary-empty">
          <Unregistered onManage={onManage} />
        </div>
      ) : (
        <div className="metrics-grid">
          {(
            [
              { metric: "temperature", icon: Thermometer },
              { metric: "humidity", icon: Droplets },
              { metric: "light", icon: Sun },
            ] as const
          ).map(({ metric, icon: Icon }) => {
            const summary = summarize(readings, metric);
            const isTemp = metric === "temperature";
            const unit = isTemp ? "°C" : metric === "humidity" ? "%" : "lx";
            const text = isTemp
              ? "온도"
              : metric === "humidity"
                ? "습도"
                : "조도";
            return (
              <button
                key={metric}
                className={`metric-card ${offline ? "stale-card" : ""}`}
                onClick={() => onMetric(metric)}
                aria-label={`${text} 상세 보기`}
                aria-pressed={
                  selectedMetric === undefined
                    ? undefined
                    : selectedMetric === metric
                }
              >
                <div className="metric-label">
                  <span>
                    <Icon size={17} />
                    {text}
                  </span>
                  <ArrowUpRight size={16} />
                </div>
                <div className="metric-value">
                  {isTemp
                    ? `${formatValue(summary.min, metric)} — ${formatValue(summary.max, metric)}`
                    : formatValue(summary.min, metric)}
                  <span>{unit}</span>
                </div>
                <div
                  className={`metric-note ${summary.excluded ? "warning-text" : ""}`}
                >
                  {isTemp
                    ? `최저–최고 · 센서 ${summary.count}개${summary.excluded ? ` · ${summary.excluded}개 제외` : ""}`
                    : metric === "humidity"
                      ? "H1 · 중앙"
                      : "L1 · 상단"}
                </div>
                <div
                  className={`metric-footer ${offline ? "warning-text" : ""}`}
                >
                  <span>
                    {offline ? <Clock3 size={12} /> : <CircleCheck size={12} />}{" "}
                    {offline ? "오래된 데이터" : "실측"}
                  </span>
                  <span>
                    측정{" "}
                    {timeLabel(
                      readings.find(
                        (sensor) =>
                          sensor.metric === metric &&
                          sensor.measuredAt !== null,
                      )?.measuredAt ?? receivedAt(state) - 10_000,
                    )}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function SensorMap({
  state,
  sensorSet = sensors,
  selected,
  onSelect,
  detailed = false,
  onDetail,
  metric = "temperature",
}: {
  state: DemoState;
  sensorSet?: Sensor[];
  metric?: Metric;
  selected: string;
  onSelect: (sensor: string) => void;
  detailed?: boolean;
  onDetail?: () => void;
}) {
  const readings = getReadings(state, sensorSet).filter(
    (sensor) => sensor.metric === metric,
  );
  const active = readings.find((sensor) => sensor.id === selected);
  return (
    <section
      className={`panel sensor-map-panel ${detailed ? "detailed-map" : ""}`}
    >
      <div className="panel-heading">
        <div>
          <h2>센서 위치</h2>
          {state === "offline" && (
            <p className="warning-text">오래된 데이터 · 수신 {timeLabel(receivedAt(state))}</p>
          )}
        </div>
        <span className="neutral-badge">예시 배치</span>
      </div>
      {readings.length ? (
        <>
          <div className="enclosure-diagram">
            <div className="diagram-top">
              <span>정면</span>
              <span>상단</span>
            </div>
            <div className="enclosure-frame">
              <div className="diagram-shelf upper" />
              <div className="diagram-shelf lower" />
              <div className="diagram-midline" />
              {readings.map((sensor) => (
                <button
                  key={sensor.id}
                  className={`sensor-pin ${selected === sensor.id ? "selected" : ""} ${sensor.status === "error" ? "sensor-error" : ""}`}
                  style={{ left: `${sensor.x}%`, top: `${sensor.y}%` }}
                  onClick={() =>
                    onSelect(selected === sensor.id ? "all" : sensor.id)
                  }
                  aria-label={`${sensor.id} ${sensor.name}, ${sensor.reading === null ? "센서 오류" : `${formatValue(sensor.reading, metric)} ${metricInfo[metric].unit}`}`}
                  aria-pressed={selected === sensor.id}
                >
                  <span className="pin-dot" />
                  <span className="pin-id">{sensor.id}</span>
                  <strong>
                    {sensor.reading === null
                      ? "오류"
                      : `${formatValue(sensor.reading, metric)}${metricInfo[metric].unit}`}
                  </strong>
                </button>
              ))}
            </div>
            <div className="diagram-bottom">
              <span>하단</span>
            </div>
          </div>
          {active && (
            <div className="map-selection">
              <MapPin size={14} />
              <span>{active.id} · {active.name}</span>
              <button onClick={() => onSelect("all")}>선택 해제</button>
            </div>
          )}
          {detailed && (
            <div className="sensor-details">
              {readings.map((sensor) => (
                <SensorRow
                  key={sensor.id}
                  sensor={sensor}
                  selected={selected === sensor.id}
                  onClick={() =>
                    onSelect(selected === sensor.id ? "all" : sensor.id)
                  }
                />
              ))}
            </div>
          )}
          {onDetail && (
            <div className="panel-bottom-link">
              <button className="text-button" onClick={onDetail}>
                센서 상세 확인 <ArrowUpRight size={13} />
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="map-no-sensors">
          등록된 {metricInfo[metric].label} 센서가 없습니다.
        </div>
      )}
    </section>
  );
}
function SensorRow({
  sensor,
  selected,
  onClick,
}: {
  sensor: SensorReading;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={`sensor-detail-row ${selected ? "selected" : ""}`}
      onClick={onClick}
      aria-pressed={selected}
    >
      <span className="sensor-id">{sensor.id}</span>
      <span>
        {sensor.name}
        <small>
          {sensor.measuredAt
            ? `측정 ${timeLabel(sensor.measuredAt)} · ${sensor.status === "stale" ? "오래된 데이터" : "실측"}`
            : "측정 실패 · 값 제외"}
        </small>
      </span>
      <strong className={sensor.status === "error" ? "warning-text" : ""}>
        {sensor.reading === null
          ? "오류"
          : `${formatValue(sensor.reading, sensor.metric)} ${metricInfo[sensor.metric].unit}`}
      </strong>
    </button>
  );
}
export function DevicePanel({
  state,
  onControl,
}: {
  state: DemoState;
  onControl: () => void;
}) {
  const offline = state === "offline";
  return (
    <section className="panel device-panel">
      <div className="panel-heading">
        <div>
          <h2>
            장치 상태 <span className="count-badge">3</span>
          </h2>
          <p>
            {offline
              ? "마지막 보고 · 오래된 데이터"
              : "장치 보고값"}
          </p>
        </div>
        <button className="text-button" onClick={onControl}>
          제어 <ArrowUpRight size={14} />
        </button>
      </div>
      <div className="device-list">
        {devices.map((device) => {
          const Icon =
            device.id === "mist" ? Droplets : device.id === "fan" ? Fan : Sun;
          return (
            <div className="device-row" key={device.id}>
              <span className="device-icon">
                <Icon size={19} />
              </span>
              <div>
                <h3>
                  {device.name}
                </h3>
                <p>
                  마지막 작동{" "}
                  {offline
                    ? device.id === "mist"
                      ? "10:05:10"
                      : device.id === "fan"
                        ? "12:00:00"
                        : "08:00:00"
                    : device.last}
                </p>
              </div>
              <span className={`device-state ${offline ? "warning-text" : ""}`}>
                {offline ? (
                  <Clock3 size={12} />
                ) : (
                  <span
                    className={`state-dot ${device.state === "켜짐" ? "on" : ""}`}
                  />
                )}{" "}
                {device.state}
                {offline && <small>현재 미확인</small>}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
export function RecentRecords({
  state,
  gateway,
  onAll,
  onDetail,
}: {
  state: DemoState;
  gateway?: string;
  onAll: () => void;
  onDetail: (record: RecordEntry) => void;
}) {
  const records = getRecords(state, gateway).slice(0, 3);
  return (
    <section className="panel records-panel">
      <div className="panel-heading">
        <div>
          <h2>최근 기록</h2>
        </div>
        <button className="text-button" onClick={onAll}>
          전체 기록 <ArrowUpRight size={14} />
        </button>
      </div>
      <div className="recent-records">
        {records.map((record) => (
          <button
            className="record-row"
            key={record.id}
            onClick={() => onDetail(record)}
          >
            <span
              className={`record-icon ${record.status === "조치 필요" ? "warning-text" : ""}`}
            >
              {record.kind === "이상 이벤트" ? (
                <CircleAlert size={16} />
              ) : (
                <CircleCheck size={16} />
              )}
            </span>
            <div>
              <h3>{record.title}</h3>
              <p>
                {record.target}
                <span>·</span>
                {timeLabel(record.time)}
              </p>
            </div>
            <ChevronRight size={14} />
          </button>
        ))}
      </div>
    </section>
  );
}
