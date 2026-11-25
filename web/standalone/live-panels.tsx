import type { ReactNode } from "react";
import { Box, Wifi, WifiOff, Thermometer, Droplets, Sun, Fan, Lightbulb, Flame, type LucideIcon } from "lucide-react";
import {
  dateTime,
  deviceLabel,
  gatewayLabels,
  metrics,
  summary,
  type Cage,
} from "./live-data";

export function Panel({
  title,
  children,
  action,
  className = "",
  icon: Icon,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
  icon?: LucideIcon;
}) {
  return (
    <section className={`live-panel ${className}`}>
      <div className="live-panel-title">
        <h2>{Icon && <Icon size={19} aria-hidden="true" />}{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
export function Empty({
  children = "아직 수신한 데이터가 없습니다.",
}: {
  children?: ReactNode;
}) {
  return (
    <div className="live-empty">
      <Box size={24} aria-hidden="true" />
      <p>{children}</p>
    </div>
  );
}
export function Notice({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <p className={`live-notice ${className}`} role="status">
      {children}
    </p>
  );
}
export function Badge({ cage }: { cage: Cage }) {
  const Icon = cage.gateway.status === "connected" ? Wifi : WifiOff;
  return (
    <span
      className={`live-badge ${cage.gateway.status === "offline" ? "warning" : ""}`}
    >
      <Icon size={15} aria-hidden="true" />
      {gatewayLabels[cage.gateway.status]}
    </span>
  );
}
export function EnvironmentSummary({ cage }: { cage: Cage }) {
  const displayedMetrics = metrics.filter(
    (metric) => metric.unit !== "lux" || summary(cage, metric.unit).valid > 0,
  );
  return (
    <div className="live-metrics">
      {displayedMetrics.map((metric) => {
        const value = summary(cage, metric.unit);
        const Icon = { degC: Thermometer, percent_rh: Droplets, lux: Sun }[metric.unit];
        return (
          <div key={metric.unit}>
            <span><Icon size={16} aria-hidden="true" />{metric.name}</span>
            <strong className={value.text.includes("–") ? "live-range-value" : ""}>
              <span>{value.text}</span>
              <small>{metric.symbol}</small>
            </strong>
            <p>
              {value.count === 0
                ? "센서 정보 미수신"
                : `${value.valid}개 유효${value.excluded ? ` · ${value.excluded}개 제외` : ""}`}
            </p>
          </div>
        );
      })}
    </div>
  );
}
export function DeviceRows({ cage }: { cage: Cage }) {
  const entries = Object.entries(cage.actuators);
  return entries.length ? (
    <ul className="live-rows">
      {entries.map(([id, actuator]) => {
        const Icon = { mister: Droplets, fan: Fan, light: Lightbulb, heater: Flame }[id.toLowerCase()] || Box;
        return <li key={id}>
          <span className="live-device-name"><span className="live-device-icon"><Icon size={18} aria-hidden="true" /></span><span>
            <strong>{deviceLabel(id)}</strong>
            <small>{id}</small>
          </span></span>
          <span className="live-device-reading">
            <strong className={`live-device-state ${actuator.observed?.state ? "is-on" : ""}`}>
              {actuator.observed
                ? actuator.observed.state
                  ? "켜짐"
                  : "꺼짐"
                : "상태 미확인"}
            </strong>
            <small>{dateTime(actuator.observed?.occurred_at)}</small>
          </span>
        </li>;
      })}
    </ul>
  ) : (
    <Empty>장치 상태를 수신하지 않았습니다.</Empty>
  );
}

export function QueryNotice({ query }: { query: {
  error?: string; data?: unknown; updatedAt?: string; refreshing: boolean; offline: boolean; refresh(): void;
} }) {
  // A single workspace notice covers browser-wide offline state.
  if (!query.error || query.offline) return null;
  return <Notice className="live-query-notice">
    <span>{query.error}{query.data !== undefined && " 마지막 조회 결과를 표시합니다."}
      {query.updatedAt && <small>조회 성공 {dateTime(query.updatedAt)} KST</small>}
    </span>
    <button onClick={query.refresh} disabled={query.refreshing}>
      {query.refreshing ? "조회 중…" : "다시 조회"}
    </button>
  </Notice>;
}
