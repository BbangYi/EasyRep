export type Unit = "degC" | "percent_rh" | "lux";
export type SpatialLayout = {
  id: string;
  geometryRevision: number;
  placementRevision: number;
  dimensionsCm: [number, number, number];
  positionsVerified: boolean;
  source: string;
  sensors: { id: string; label: string; positionCm: [number, number, number] }[];
};
export type Sensor = {
  id: string;
  unit: Unit;
  value: number | null;
  quality: string;
};
export type Observation = {
  state: boolean;
  occurred_at: string;
  source: string;
};
export type Cage = {
  id: string;
  name: string;
  species?: string;
  location?: string;
  store: string;
  photo?: { url: string; thumbnailUrl: string; updatedAt: string } | null;
  siteId: string | null;
  cageId: string | null;
  gateway: { id: string | null; status: string; lastReceivedAt: string | null };
  historyReceipt?: { sampledAt: string | null; receivedAt: string | null; behindCurrent: boolean };
  configurationChanged: boolean;
  sampledAt: string | null;
  piReceivedAt: string | null;
  stale: boolean;
  source: string | null;
  sensors: Sensor[];
  actuators: Record<
    string,
    { observed: Observation | null; on_blocked_reason: string | null }
  >;
  mode: string;
  staleAfterSeconds: number;
  geometryRevision: number | null;
  placementRevision: number | null;
  spatialLayout?: SpatialLayout | null;
};
export type Point = {
  id?: string;
  eventId: string; // Legacy chart identifier; piEventId carries the Pi event identity.
  piEventId?: string | null;
  receiptSource?: "snapshot" | "event";
  message_id?: string;
  at: string;
  serverReceivedAt: string;
  received_at: string;
  data_source: string;
  geometry_revision: number;
  placement_revision: number;
  readings: Record<string, { value: number | null; quality: string }>;
};
export type HistoryData = {
  start: string;
  end: string;
  points: Point[];
  commands: {
    id: string;
    at: string;
    actuator: string;
    action: string;
    status: string;
  }[];
  truncated: boolean;
  commandsTruncated: boolean;
  olderThan: string | null;
  next?: string | null;
  limit: number;
};
export type Command = {
  command_id: string;
  actuator_id: string;
  action: string;
  status: string;
  duration_s: number;
  created_at: string;
  reason: string | null;
  applied_at?: string;
  acknowledged_at?: string;
  source: string;
};
export type RecordItem = {
  id: string;
  kind: "telemetry.recorded" | "command.updated";
  at: string;
  serverReceivedAt: string;
  sequence: number;
  payload: Command | (Point & { sampled_at: string });
};
export const metrics: { unit: Unit; name: string; symbol: string }[] = [
  { unit: "degC", name: "온도", symbol: "°C" },
  { unit: "percent_rh", name: "습도", symbol: "%" },
  { unit: "lux", name: "조도", symbol: "lx" },
];
export const gatewayLabels: Record<string, string> = {
  unregistered: "Pi 미등록",
  disabled: "수신 중지",
  waiting: "수신 대기",
  offline: "통신 끊김",
  connected: "Pi 연결됨",
};

export type OperationalStatus = {
  kind: "sensor-current" | "sensor-delayed" | "pi-waiting" | "unregistered" | "simulation";
  label: string;
  detail: string;
};

// The administrative store name is not a telemetry provenance field.  Keep the
// user-facing classification tied only to the origin and freshness returned by
// the server.
export function operationalStatus(cage: Cage): OperationalStatus {
  const gateway = cage.gateway || { id: null, status: "unregistered", lastReceivedAt: null };
  if (cage.source === "simulation") {
    return {
      kind: "simulation",
      label: "가상 데이터",
      detail: "시뮬레이션 원본으로 구분된 측정입니다.",
    };
  }
  if (cage.source === "sensor") {
    if (!cage.stale && gateway.status === "connected") {
      return {
        kind: "sensor-current",
        label: "실제 센서 수신 중",
        detail: "최근 센서 원본을 받고 있습니다.",
      };
    }
    return {
      kind: "sensor-delayed",
      label: "실제 센서 기록 · 수신 지연",
      detail: "실제 센서 원본은 있으나 최신성 기준을 넘겼습니다.",
    };
  }
  if (gateway.status === "connected" || gateway.id || cage.cageId) {
    return {
      kind: "pi-waiting",
      label: gateway.status === "connected" ? "Pi 연결 · 측정 대기" : "Pi 측정 대기",
      detail: "Pi 바인딩은 있으나 센서 원본을 아직 받지 않았습니다.",
    };
  }
  return {
    kind: "unregistered",
    label: "장치 미등록",
    detail: "사육장 정보만 등록되어 있습니다.",
  };
}

const operationalRank: Record<OperationalStatus["kind"], number> = {
  "sensor-current": 0,
  "sensor-delayed": 1,
  "pi-waiting": 2,
  unregistered: 3,
  simulation: 4,
};

export function orderOperationalCages(items: Cage[]) {
  return items
    .map((cage, index) => ({ cage, index, rank: operationalRank[operationalStatus(cage).kind] }))
    .sort((left, right) => {
      if (left.rank !== right.rank) return left.rank - right.rank;
      const leftSampledAt = Date.parse(left.cage.sampledAt || "");
      const rightSampledAt = Date.parse(right.cage.sampledAt || "");
      const leftHasSample = Number.isFinite(leftSampledAt);
      const rightHasSample = Number.isFinite(rightSampledAt);
      if (leftHasSample !== rightHasSample) return rightHasSample ? 1 : -1;
      if (leftHasSample && rightHasSample && leftSampledAt !== rightSampledAt) return rightSampledAt - leftSampledAt;
      return left.index - right.index;
    })
    .map(({ cage }) => cage);
}
export const qualityLabels: Record<string, string> = {
  valid: "유효",
  invalid: "측정 오류",
  crc_error: "검증 오류",
  disconnected: "센서 연결 끊김",
  missing: "미수신",
};
// published means dispatched by Pi; it is not device acceptance or completion.
export const commandLabels: Record<string, string> = {
  publishing: "발행 대기",
  published: "전송됨 · 결과 대기",
  applied: "장치 적용 확인",
  rejected: "거절",
  expired: "기한 만료",
  interrupted: "실행 중단",
};
export const deviceLabel = (id: string) =>
  ({ mister: "분무", fan: "환기", light: "조명", heater: "히터" })[
    id.toLowerCase() as "mister"
  ] || id;
export function dateTime(value: string | null | undefined, short = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    ...(short ? {} : { month: "2-digit", day: "2-digit" }),
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}
export function summary(cage: Cage, unit: Unit) {
  const all = cage.sensors.filter((s) => s.unit === unit);
  const valid = all.filter(
    (s) =>
      s.quality === "valid" && s.value !== null && Number.isFinite(s.value),
  );
  const values = valid.map((s) => s.value!);
  const format = (value: number) =>
    unit === "lux"
      ? value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })
      : value.toFixed(1);
  return {
    text: values.length
      ? values.length > 1 && Math.min(...values) !== Math.max(...values)
        ? `${format(Math.min(...values))}–${format(Math.max(...values))}`
        : format(values[0])
      : "—",
    valid: valid.length,
    excluded: all.length - valid.length,
    count: all.length,
  };
}
export function segments(
  points: Point[],
  sensorId: string,
  maxGapSeconds: number,
): { at: string; value: number }[][] {
  const result: { at: string; value: number }[][] = [];
  let segment: { at: string; value: number }[] = [];
  let previousSource: string | undefined;
  for (const point of points) {
    const reading = point.readings[sensorId];
    const valid =
      reading?.quality === "valid" &&
      reading.value !== null &&
      Number.isFinite(reading.value);
    if (
      !valid ||
      (segment.length > 0 &&
        (point.data_source !== previousSource ||
          Date.parse(point.at) - Date.parse(segment[segment.length - 1].at) >
            maxGapSeconds * 1000))
    ) {
      if (segment.length) result.push(segment);
      segment = [];
    }
    if (valid) segment.push({ at: point.at, value: reading.value! });
    previousSource = point.data_source;
  }
  if (segment.length) result.push(segment);
  return result;
}
export function csvForHistory(
  data: HistoryData,
  sensors: Sensor[],
  selected: string,
) {
  const cell = (value: unknown) =>
    `"${String(value ?? "").replace(/"/g, '""')}"`;
  const rows: unknown[][] = [
    [
      "measurement_id",
      "event_id",
      "receipt_source",
      "sensor_message_id",
      "sampled_at",
      "pi_received_at",
      "server_received_at",
      "data_source",
      "sensor_id",
      "unit",
      "value",
      "quality",
      "geometry_revision",
      "placement_revision",
    ],
  ];
  for (const point of data.points)
    for (const sensor of sensors.filter(
      (s) => selected === "all" || selected === s.id,
    )) {
      const reading = point.readings[sensor.id];
      rows.push([
        point.id ?? point.eventId,
        point.piEventId === undefined ? point.eventId : point.piEventId,
        point.receiptSource ?? "event",
        point.message_id,
        point.at,
        point.received_at,
        point.serverReceivedAt,
        point.data_source,
        sensor.id,
        sensor.unit,
        reading?.value,
        reading?.quality || "missing",
        point.geometry_revision,
        point.placement_revision,
      ]);
    }
  return "\uFEFF" + rows.map((row) => row.map(cell).join(",")).join("\r\n");
}

export function historyForConfiguration(
  data: HistoryData,
  cage: Cage,
): HistoryData {
  return {
    ...data,
    points: data.points.filter(
      (point) =>
        point.geometry_revision === cage.geometryRevision &&
        point.placement_revision === cage.placementRevision,
    ),
  };
}

// Transport receipt and sensor freshness are independent, including for simulation.
export function measurementStatus(cage: Cage) {
  if (cage.configurationChanged)
    return {
      label: "새 측정 대기",
      warning: true,
      message: "센서 구성이 변경되어 새 구성의 측정값을 기다리고 있습니다.",
    };
  if (!cage.sampledAt)
    return {
      label: "측정 미수신",
      warning: false,
      message: "아직 수신한 측정값이 없습니다.",
    };
  if (cage.stale)
    return {
      label: "측정 갱신 지연",
      warning: true,
      message: cage.gateway.status === "connected"
        ? "Pi 통신은 연결되어 있지만 측정값은 오래된 데이터입니다."
        : "오래된 데이터입니다. 현재 환경과 다를 수 있습니다.",
    };
  const valid = cage.sensors.filter(
    (sensor) => sensor.quality === "valid" && sensor.value !== null && Number.isFinite(sensor.value),
  ).length;
  if (!valid)
    return {
      label: "유효 측정 없음",
      warning: true,
      message: "수신값에서 유효한 센서 측정을 확인할 수 없습니다.",
    };
  if (valid < cage.sensors.length)
    return {
      label: "일부 센서 확인",
      warning: true,
      message: "일부 센서값에 오류가 있거나 아직 수신되지 않았습니다.",
    };
  return {
    label: "측정 갱신 중",
    warning: false,
    message: "최근 측정값을 수신하고 있습니다.",
  };
}
