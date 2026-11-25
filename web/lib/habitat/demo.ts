export type DemoState = "normal" | "offline" | "sensor-error" | "unregistered";
export type View =
  | "home"
  | "enclosure"
  | "environment"
  | "control"
  | "history"
  | "management";
export type Metric = "temperature" | "humidity" | "light";
export const enclosure = {
  name: "크레스티드 게코 사육장 01",
  species: "크레스티드 게코",
  gateway: "GW-001",
  date: "2026.09.15",
  receivedAt: "14:32:10",
};
export const demoStates: { value: DemoState; label: string }[] = [
  { value: "normal", label: "정상 수신" },
  { value: "offline", label: "게이트웨이 통신 끊김" },
  { value: "sensor-error", label: "온도 센서 1개 오류" },
  { value: "unregistered", label: "센서 미등록" },
];
export const sensors = [
  {
    id: "T1",
    name: "상단 왼쪽",
    metric: "temperature" as Metric,
    value: 25.6,
    x: 23,
    y: 25,
  },
  {
    id: "T2",
    name: "상단 오른쪽",
    metric: "temperature" as Metric,
    value: 26.2,
    x: 77,
    y: 25,
  },
  {
    id: "T3",
    name: "중앙",
    metric: "temperature" as Metric,
    value: 24.8,
    x: 50,
    y: 51,
  },
  {
    id: "T4",
    name: "하단 왼쪽",
    metric: "temperature" as Metric,
    value: 24.1,
    x: 23,
    y: 77,
  },
  {
    id: "T5",
    name: "하단 오른쪽",
    metric: "temperature" as Metric,
    value: 24.5,
    x: 77,
    y: 77,
  },
  {
    id: "H1",
    name: "중앙 습도",
    metric: "humidity" as Metric,
    value: 68,
    x: 50,
    y: 51,
  },
  {
    id: "L1",
    name: "상단 조도",
    metric: "light" as Metric,
    value: 320,
    x: 50,
    y: 25,
  },
];
export const metricInfo = {
  temperature: { label: "온도", unit: "°C" },
  humidity: { label: "습도", unit: "%" },
  light: { label: "조도", unit: "lx" },
};

export type Sensor = (typeof sensors)[number];
