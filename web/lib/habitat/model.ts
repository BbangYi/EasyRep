import { sensors, type DemoState, type Metric, type Sensor } from "./demo";

export const DEMO_NOW = Date.parse("2026-09-15T14:32:00+09:00");
export const STEP = 5 * 60_000;
export type Period = 1 | 6 | 24;
export type Sample = { time: number; [sensorId: string]: number | null };
export type SensorReading = (typeof sensors)[number] & {
  reading: number | null;
  measuredAt: number | null;
  status: "received" | "stale" | "error";
};
export const lineStyles = [
  { color: "var(--chart-1)", dash: "" },
  { color: "var(--chart-2)", dash: "7 3" },
  { color: "var(--chart-3)", dash: "2 3" },
  { color: "var(--chart-4)", dash: "9 3 2 3" },
  { color: "var(--chart-5)", dash: "5 4" },
];
export function sensorLineStyle(
  sensorId: string,
  sensorSet: Sensor[] = sensors,
) {
  const index = sensorSet.findIndex((sensor) => sensor.id === sensorId);
  return lineStyles[Math.max(0, index) % lineStyles.length];
}
export const timeLabel = (time: number, seconds = false) =>
  new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
    hour12: false,
  }).format(time);
export const fullTime = (time: number) =>
  `2026.09.${new Intl.DateTimeFormat("en", { timeZone: "Asia/Seoul", day: "2-digit" }).format(time)} ${timeLabel(time)} KST`;
export const receivedAt = (state: DemoState) =>
  DEMO_NOW - (state === "offline" ? 30 * 60_000 : 0) + 10_000;
export const formatValue = (value: number | null, metric: Metric) =>
  value === null
    ? "—"
    : metric === "temperature"
      ? value.toFixed(1)
      : String(Math.round(value));

/** Fixed fixture: each series ends at the value declared in demo.ts. Never uses the wall clock or random data. */
function createHistory(sensorSet: Sensor[]): Sample[] {
  return Array.from({ length: 289 }, (_, index) => {
    const stepsAgo = 288 - index;
    const time = DEMO_NOW - stepsAgo * STEP;
    const row: Sample = { time };
    sensorSet.forEach((sensor, sensorIndex) => {
      const missing =
        (stepsAgo >= 8 && stepsAgo <= 9) || (stepsAgo >= 17 && stepsAgo <= 20);
      const wave =
        Math.sin(stepsAgo / 4 + sensorIndex * 0.65) -
        Math.sin(sensorIndex * 0.65);
      const slowWave = Math.sin(stepsAgo / 19) * 0.4;
      const amplitude =
        sensor.metric === "temperature"
          ? 0.38
          : sensor.metric === "humidity"
            ? 4.5
            : 28;
      row[sensor.id] = missing
        ? null
        : Number(
            (sensor.value + (wave + slowWave) * amplitude).toFixed(
              sensor.metric === "temperature" ? 1 : 0,
            ),
          );
    });
    return row;
  });
}

export const history = createHistory(sensors);
const histories = new WeakMap<Sensor[], Sample[]>([[sensors, history]]);
function historyFor(sensorSet: Sensor[]) {
  let rows = histories.get(sensorSet);
  if (!rows) {
    rows = createHistory(sensorSet);
    histories.set(sensorSet, rows);
  }
  return rows;
}

export function getSamples(
  state: DemoState,
  period: Period,
  sensorSet: Sensor[] = sensors,
): Sample[] {
  if (state === "unregistered") return [];
  const cutoff = receivedAt(state) - 10_000;
  return historyFor(sensorSet)
    .filter((row) => row.time >= DEMO_NOW - period * 3_600_000)
    .map((row) => {
      const sample = { ...row };
      for (const sensor of sensorSet) {
        if (
          row.time > cutoff ||
          (state === "sensor-error" &&
            sensor.id === "T3" &&
            row.time >= DEMO_NOW - 10 * 60_000)
        )
          sample[sensor.id] = null;
      }
      return sample;
    });
}

export function getReadings(
  state: DemoState,
  sensorSet: Sensor[] = sensors,
): SensorReading[] {
  if (state === "unregistered") return [];
  const rows = getSamples(state, 24, sensorSet);
  const cutoff = receivedAt(state) - 10_000;
  const row = rows.find((sample) => sample.time === cutoff)!;
  return sensorSet.map((sensor) => ({
    ...sensor,
    reading: row[sensor.id],
    measuredAt: row[sensor.id] === null ? null : row.time,
    status:
      state === "sensor-error" && sensor.id === "T3"
        ? "error"
        : state === "offline"
          ? "stale"
          : "received",
  }));
}

export function summarize(readings: SensorReading[], metric: Metric) {
  const matching = readings.filter((sensor) => sensor.metric === metric);
  const values = matching
    .map((sensor) => sensor.reading)
    .filter(
      (value): value is number => value !== null && Number.isFinite(value),
    );
  return {
    count: values.length,
    excluded: matching.length - values.length,
    min: values.length ? Math.min(...values) : null,
    max: values.length ? Math.max(...values) : null,
  };
}

/** Statistics describe received samples only, never an environmental suitability score. */
export function inspectSamples(rows: Sample[], sensorIds: string[]) {
  let minimum = Infinity;
  let maximum = -Infinity;
  let received = 0;
  let latestIndex = -1;
  rows.forEach((row, index) => {
    for (const id of sensorIds) {
      const value = row[id];
      if (typeof value !== "number" || !Number.isFinite(value)) continue;
      minimum = Math.min(minimum, value);
      maximum = Math.max(maximum, value);
      received++;
      latestIndex = index;
    }
  });
  return {
    min: received ? minimum : null,
    max: received ? maximum : null,
    received,
    expected: rows.length * sensorIds.length,
    latestIndex,
  };
}

export function closestSampleIndex(rows: Sample[], time: number) {
  if (!rows.length || !Number.isFinite(time)) return -1;
  return rows.reduce(
    (best, row, index) =>
      Math.abs(row.time - time) < Math.abs(rows[best].time - time)
        ? index
        : best,
    0,
  );
}

export type DeviceEvent = {
  id: string;
  time: number;
  device: "mist" | "fan" | "light";
  label: string;
  detail: string;
};
export const deviceEvents: DeviceEvent[] = [
  {
    id: "light-on",
    time: DEMO_NOW - 392 * 60_000,
    device: "light",
    label: "조명 켜짐",
    detail: "08:00 · 조명 켜짐",
  },
  {
    id: "mist-1",
    time: DEMO_NOW - 267 * 60_000,
    device: "mist",
    label: "분무",
    detail: "10:05 · 분무 10초",
  },
  {
    id: "fan-1",
    time: DEMO_NOW - 157 * 60_000,
    device: "fan",
    label: "환기",
    detail: "11:55 · 환기 5분",
  },
  {
    id: "mist-2",
    time: DEMO_NOW - 27 * 60_000,
    device: "mist",
    label: "분무",
    detail: "14:05 · 분무 10초",
  },
  {
    id: "fan-2",
    time: DEMO_NOW - 7 * 60_000,
    device: "fan",
    label: "환기",
    detail: "14:25 · 환기 5분",
  },
];
export function getEvents(state: DemoState, period: Period) {
  return deviceEvents.filter(
    (event) =>
      event.time >= DEMO_NOW - period * 3_600_000 &&
      event.time <= receivedAt(state),
  );
}
export const devices = [
  {
    id: "mist",
    name: "분무기",
    model: "MIST-01",
    state: "대기",
    request: "10초 분무",
    applied: "10초 분무 완료",
    last: "14:05:10",
  },
  {
    id: "fan",
    name: "환기 팬",
    model: "FAN-01",
    state: "꺼짐",
    request: "5분 작동",
    applied: "5분 작동 완료",
    last: "14:30:00",
  },
  {
    id: "light",
    name: "조명",
    model: "LIGHT-01",
    state: "켜짐",
    request: "켜짐",
    applied: "켜짐",
    last: "08:00:00",
  },
] as const;
export type CommandStatus =
  | "발행 대기"
  | "장치 수락"
  | "실행 완료"
  | "거절"
  | "실행 실패"
  | "결과 미확인";
export const commandStatuses: CommandStatus[] = [
  "발행 대기",
  "장치 수락",
  "실행 완료",
  "거절",
  "실행 실패",
  "결과 미확인",
];
export type RecordEntry = {
  id: string;
  time: number;
  kind: "이상 이벤트" | "명령" | "설정 변경";
  target: string;
  title: string;
  summary: string;
  status: string;
  acknowledged?: boolean;
  recovered?: boolean;
  detail: string;
};
const at = (minutes: number) => DEMO_NOW - minutes * 60_000;
export const records: RecordEntry[] = [
  {
    id: "cmd-fan",
    time: at(2),
    kind: "명령",
    target: "환기 팬",
    title: "환기 5분 작동 완료",
    summary: "5분 환기",
    status: "실행 완료",
    detail:
      "요청: 5분 작동 · 장치 적용: 5분 작동 완료. 장치가 보고한 명령 결과의 데모입니다.",
  },
  {
    id: "sensor-restored",
    time: at(35),
    kind: "이상 이벤트",
    target: "T3 · 중앙",
    title: "온도 센서 수신 복구",
    summary: "수신 복구",
    status: "복구됨",
    acknowledged: false,
    recovered: true,
    detail:
      "13:47 측정 오류 발생 후 13:57 정상 측정이 수신되었습니다. 문제 복구와 사용자 확인은 별도 상태입니다.",
  },
  {
    id: "cmd-mist",
    time: at(27),
    kind: "명령",
    target: "분무기",
    title: "분무 10초 작동 완료",
    summary: "10초 분무",
    status: "실행 완료",
    detail: "요청: 10초 분무 · 장치 적용: 10초 분무 완료.",
  },
  {
    id: "sensor-old",
    time: at(45),
    kind: "이상 이벤트",
    target: "T3 · 중앙",
    title: "온도 센서 측정 오류 발생",
    summary: "측정 오류",
    status: "복구됨",
    acknowledged: true,
    recovered: true,
    detail:
      "사용자 확인: 13:50 · 수신 복구: 13:57. 확인했다고 문제가 복구되는 것은 아닙니다.",
  },
  {
    id: "settings",
    time: at(62),
    kind: "설정 변경",
    target: "사육장",
    title: "센서 설치 위치 이름 변경",
    summary: "위치 이름 변경",
    status: "변경됨",
    detail: "T3 설치 위치 표시를 중앙으로 변경한 데모 기록입니다.",
  },
];
export function getRecords(state: DemoState, gateway = "GW-001") {
  const visible = records.filter((r) => r.time <= receivedAt(state));
  if (state === "sensor-error")
    visible.unshift({
      id: "active-sensor",
      time: at(10),
      kind: "이상 이벤트",
      target: "T3 · 중앙",
      title: "온도 센서 응답 없음",
      summary: "응답 없음",
      status: "조치 필요",
      acknowledged: false,
      recovered: false,
      detail:
        "14:22부터 T3 측정값이 수신되지 않습니다. 온도 요약은 유효한 센서 4개만 사용합니다. 센서 연결과 전원을 확인하세요.",
    });
  if (state === "offline")
    visible.unshift({
      id: "active-gateway",
      time: at(29),
      kind: "이상 이벤트",
      target: gateway,
      title: "게이트웨이 통신 끊김",
      summary: "통신 끊김",
      status: "조치 필요",
      acknowledged: false,
      recovered: false,
      detail:
        "마지막 데이터 수신: 2026.09.15 14:02:10 KST. 이후 센서값과 장치의 현재 상태를 확인할 수 없습니다. 게이트웨이 전원과 네트워크를 확인하세요.",
    });
  return visible.sort((a, b) => b.time - a.time);
}


export type RecordFilters = {
  query?: string;
  minutes?: number;
  kind?: RecordEntry["kind"] | "전체";
  status?: string;
};

/** Recent periods use the same fixed clock as the demo readings. */
export function filterRecords(entries: RecordEntry[], filters: RecordFilters = {}) {
  const terms = (filters.query ?? "").trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const cutoff = filters.minutes ? DEMO_NOW - filters.minutes * 60_000 : -Infinity;
  return entries.filter((entry) => {
    const searchable = `${entry.target} ${entry.summary} ${entry.title} ${entry.detail}`.toLocaleLowerCase();
    return entry.time >= cutoff && entry.time <= DEMO_NOW
      && (!filters.kind || filters.kind === "전체" || entry.kind === filters.kind)
      && (!filters.status || filters.status === "전체" || entry.status === filters.status)
      && terms.every((term) => searchable.includes(term));
  }).sort((a, b) => b.time - a.time);
}

export function makeCsv(
  state: DemoState,
  period: Period,
  metric: Metric,
  selected: string,
  sensorSet: Sensor[] = sensors,
  enclosureName?: string,
): string {
  const selectedSensors = sensorSet.filter(
    (sensor) =>
      sensor.metric === metric &&
      (selected === "all" || sensor.id === selected),
  );
  const lines = [
    [
      ...(enclosureName ? ["사육장"] : []),
      "데이터 종류",
      "데모 상태",
      "측정시각(KST)",
      "센서",
      "위치",
      "값",
      "단위",
      "측정 상태",
    ],
  ];
  const rows = getSamples(state, period, sensorSet);
  for (const row of rows)
    for (const sensor of selectedSensors) {
      const value = row[sensor.id];
      const status =
        state === "offline" && row.time > receivedAt(state)
          ? "미수신"
          : state === "sensor-error" && sensor.id === "T3" && row.time >= at(10)
            ? "센서 오류"
            : value === null
              ? "데이터 없음"
              : state === "offline"
                ? "과거 실측(오래된 데이터)"
                : "실측";
      lines.push([
        ...(enclosureName ? [enclosureName] : []),
        "데모 실측",
        state,
        fullTime(row.time),
        sensor.id,
        sensor.name,
        value === null ? "" : String(value),
        sensor.metric === "temperature"
          ? "°C"
          : sensor.metric === "humidity"
            ? "%"
            : "lx",
        status,
      ]);
    }
  return (
    "\uFEFF" +
    lines
      .map((line) =>
        line.map((cell) => '"' + cell.replaceAll('"', '""') + '"').join(","),
      )
      .join("\r\n")
  );
}
