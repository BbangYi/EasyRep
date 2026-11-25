import { sensors, type Sensor, type DemoState } from "./demo";

export type CameraState = "demo" | "offline" | "not-installed";
export type Enclosure = {
  id: string;
  number: string;
  name: string;
  species: string;
  location: string;
  gateway: string;
  date: string;
  defaultState: DemoState;
  sensors: Sensor[];
  photo?: {
    src: string;
    alt: string;
    credit: string;
    source: string;
    license: string;
    licenseUrl: string;
    position?: string;
  };
  camera: { state: CameraState; name?: string; lastFrameAt?: string };
};

function sensorSet(
  temperature: number,
  humidity: number,
  light: number,
): Sensor[] {
  return sensors.map((sensor) => ({
    ...sensor,
    value:
      sensor.metric === "temperature"
        ? Number((sensor.value + temperature).toFixed(1))
        : sensor.metric === "humidity"
          ? humidity
          : light,
  }));
}

/** Enclosure fixtures, independent of UI. Values are examples, never husbandry targets. */
export const enclosures: Enclosure[] = [
  {
    id: "crested-01",
    number: "01",
    name: "크레스티드 게코 사육장 01",
    species: "크레스티드 게코",
    location: "사육실 A · 상단",
    gateway: "GW-001",
    date: "2026.09.15",
    defaultState: "normal",
    sensors,
    photo: {
      src: "/enclosures/crested-gecko.jpg",
      alt: "녹색 잎 위의 크레스티드 게코 예시 사진",
      credit: "Lennart Hudel",
      source: "https://commons.wikimedia.org/wiki/File:Crested_gecko_-_1.jpg",
      license: "CC BY 4.0",
      licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
      position: "50% 75%",
    },
    camera: {
      state: "demo",
      name: "CAM-001 · 정면",
      lastFrameAt: "2026.09.15 14:32:00",
    },
  },
  {
    id: "leopard-02",
    number: "02",
    name: "레오파드 게코 사육장 02",
    species: "레오파드 게코",
    location: "사육실 A · 하단",
    gateway: "GW-002",
    date: "2026.09.15",
    defaultState: "sensor-error",
    sensors: sensorSet(3.1, 45, 210),
    photo: {
      src: "/enclosures/leopard-gecko.jpg",
      alt: "사육장 은신처 위의 레오파드 게코 예시 사진",
      credit: "Asklēpiós",
      source:
        "https://commons.wikimedia.org/wiki/File:Leopard_gecko_basking.jpg",
      license: "CC BY-SA 4.0",
      licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0/",
      position: "50% 0%",
    },
    camera: { state: "not-installed" },
  },
  {
    id: "python-03",
    number: "03",
    name: "볼파이톤 사육장 03",
    species: "볼파이톤",
    location: "사육실 B · 상단",
    gateway: "GW-003",
    date: "2026.09.15",
    defaultState: "offline",
    sensors: sensorSet(4.7, 61, 180),
    photo: {
      src: "/enclosures/ball-python.jpg",
      alt: "은신처 입구의 볼파이톤 예시 사진",
      credit: "Lisaw123",
      source:
        "https://commons.wikimedia.org/wiki/File:Ball_python_and_rock.jpg",
      license: "Public domain",
      licenseUrl:
        "https://commons.wikimedia.org/wiki/File:Ball_python_and_rock.jpg",
      position: "50% 65%",
    },
    camera: {
      state: "offline",
      name: "CAM-003 · 정면",
      lastFrameAt: "2026.09.15 14:02:00",
    },
  },
  {
    id: "new-04",
    number: "04",
    name: "새 사육장 04",
    species: "개체 미등록",
    location: "사육실 B · 하단",
    gateway: "GW-004",
    date: "2026.09.15",
    defaultState: "unregistered",
    sensors: sensorSet(0, 68, 320),
    camera: { state: "not-installed" },
  },
];
export const cameraLabels: Record<CameraState, string> = {
  demo: "카메라 데모",
  offline: "카메라 연결 끊김",
  "not-installed": "카메라 미설치",
};
export const stateLabels: Record<DemoState, string> = {
  normal: "정상 수신",
  offline: "통신 끊김",
  "sensor-error": "센서 오류",
  unregistered: "센서 미등록",
};
export function needsAttention(state: DemoState) {
  return state === "offline" || state === "sensor-error";
}
export function getEnclosure(id: string) {
  return enclosures.find((item) => item.id === id);
}
