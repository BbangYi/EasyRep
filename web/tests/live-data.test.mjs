import assert from "node:assert/strict";
import { build } from "esbuild";
const result = await build({
  stdin: {
    contents: 'export * from "./standalone/live-data.ts"',
    resolveDir: process.cwd(),
    loader: "ts",
  },
  bundle: true,
  write: false,
  platform: "node",
  format: "esm",
});
const {
  summary,
  segments,
  csvForHistory,
  commandLabels,
  historyForConfiguration,
  measurementStatus,
  operationalStatus,
  orderOperationalCages,
} = await import(
  "data:text/javascript;base64," +
    Buffer.from(result.outputFiles[0].text).toString("base64")
);
const sensors = [
  { id: "T1", unit: "degC", quality: "valid", value: 23.2 },
  { id: "T2", unit: "degC", quality: "crc_error", value: null },
  { id: "T3", unit: "degC", quality: "valid", value: 25.1 },
];
assert.deepEqual(summary({ sensors }, "degC"), {
  text: "23.2–25.1",
  count: 3,
  valid: 2,
  excluded: 1,
});
assert.equal(summary({ sensors: [] }, "degC").text, "—");
const point = (second, value, quality = "valid") => ({
  eventId: `event-${second}`,
  at: new Date(Date.UTC(2026, 8, 19, 0, 0, second)).toISOString(),
  received_at: "2026-09-19T00:00:10Z",
  serverReceivedAt: "2026-09-19T00:00:11Z",
  data_source: "simulation",
  geometry_revision: 1,
  placement_revision: 1,
  readings: { T1: { value, quality } },
});
const points = [
  point(0, 22),
  point(5, 23),
  point(10, null, "crc_error"),
  point(15, 24),
  point(60, 25),
];
assert.deepEqual(
  segments(points, "T1", 15).map((p) => p.length),
  [2, 1, 1],
);
assert.deepEqual(segments(points, "unknown", 15), []);
// Close measurements from different origins must not imply one continuous trend.
const mixedPoints = [
  { ...point(0, 24), data_source: "sensor" },
  point(5, 38),
  { ...point(10, 25), data_source: "sensor" },
];
const mixedBefore = structuredClone(mixedPoints);
assert.deepEqual(segments(mixedPoints, "T1", 15), [
  [{ at: mixedPoints[0].at, value: 24 }],
  [{ at: mixedPoints[1].at, value: 38 }],
  [{ at: mixedPoints[2].at, value: 25 }],
]);
for (const source of ["sensor", "simulation", "unrecognized", undefined]) {
  const sameSource = mixedPoints.map((p) => ({ ...p, data_source: source }));
  assert.deepEqual(segments(sameSource, "T1", 15).map((s) => s.length), [3]);
}
const unknownSources = mixedPoints.map((p, i) => ({ ...p, data_source: ["sensor", undefined, "unrecognized"][i] }));
assert.deepEqual(segments(unknownSources, "T1", 15).map((s) => s.length), [1, 1, 1]);
const invalidAndGap = [
  { ...point(0, 24), data_source: "sensor" },
  { ...point(5, 25), data_source: "sensor" },
  point(10, null, "crc_error"),
  point(15, 38),
  point(60, 39),
  { ...point(65, 26), data_source: "sensor" },
  { ...point(70, NaN), data_source: "sensor" },
  { ...point(75, 27), data_source: "sensor" },
];
assert.deepEqual(segments(invalidAndGap, "T1", 15).map((s) => s.length), [2, 1, 1, 1, 1]);
assert.deepEqual(segments([], "T1", 15), []);
assert.deepEqual(segments([mixedPoints[0]], "T1", 15), [[{ at: mixedPoints[0].at, value: 24 }]]);
assert.deepEqual(mixedPoints, mixedBefore, "Segmentation must preserve source rows and order");
const mixedCsv = csvForHistory({ points: mixedPoints }, sensors, "T1");
assert.equal(mixedCsv.split("\r\n").length, 4);
assert.equal((mixedCsv.match(/"sensor"/g) || []).length, 2);
assert.equal((mixedCsv.match(/"simulation"/g) || []).length, 1);
const csv = csvForHistory({ points }, sensors, "T1");
assert.equal(csv.split("\r\n").length, 6);
assert.ok(csv.includes('"","crc_error"'));
assert.ok(csv.includes('"simulation"'));
assert.ok(!csv.includes('"T2"'));
assert.equal(commandLabels.published, "전송됨 · 결과 대기");
assert.equal(
  historyForConfiguration(
    { points },
    { geometryRevision: 1, placementRevision: 2 },
  ).points.length,
  0,
);
const reportingCage = {
  configurationChanged: false, sampledAt: "2026-09-21T05:40:33Z",
  stale: true, gateway: { status: "connected" }, sensors,
};
// A heartbeat must never turn old measurements into a current reading.
assert.equal(measurementStatus(reportingCage).label, "측정 갱신 지연");
assert.match(measurementStatus(reportingCage).message, /Pi 통신은 연결/);
assert.equal(measurementStatus({ ...reportingCage, sampledAt: null }).label, "측정 미수신");
assert.equal(measurementStatus({ ...reportingCage, configurationChanged: true }).label, "새 측정 대기");
assert.equal(measurementStatus({ ...reportingCage, stale: false }).label, "일부 센서 확인");
assert.equal(measurementStatus({ ...reportingCage, stale: false, sensors: [sensors[1]] }).label, "유효 측정 없음");
assert.equal(measurementStatus({ ...reportingCage, stale: false, sensors: [sensors[0]] }).label, "측정 갱신 중");

// Store names are administrative labels. They must never turn sensor data into
// a simulated record or hide it behind a "virtual" name.
const sensorNow = {
  ...reportingCage,
  id: "sensor-now",
  name: "연결 검증 사육장 02",
  store: "개발 검증 매장 (가상)",
  source: "sensor",
  stale: false,
  gateway: { status: "connected" },
};
const sensorDelayed = { ...sensorNow, id: "sensor-delayed", stale: true };
const piWaiting = {
  ...sensorNow,
  id: "pi-waiting",
  source: null,
  sampledAt: null,
  gateway: { status: "connected" },
};
const unregistered = {
  ...sensorNow,
  id: "unregistered",
  source: null,
  sampledAt: null,
  gateway: { status: "unregistered" },
};
const simulation = { ...sensorNow, id: "simulation", store: "실제 매장", source: "simulation" };
assert.equal(operationalStatus(sensorNow).kind, "sensor-current");
assert.equal(operationalStatus(sensorNow).label, "실제 센서 수신 중");
assert.equal(operationalStatus(sensorDelayed).kind, "sensor-delayed");
assert.equal(operationalStatus(piWaiting).label, "Pi 연결 · 측정 대기");
assert.equal(operationalStatus(unregistered).label, "장치 미등록");
assert.equal(operationalStatus(simulation).kind, "simulation");
assert.deepEqual(
  orderOperationalCages([unregistered, simulation, sensorDelayed, piWaiting, sensorNow]).map((cage) => cage.id),
  ["sensor-now", "sensor-delayed", "pi-waiting", "unregistered", "simulation"],
);


// A snapshot has a measurement ID, but must not claim a Pi event that never arrived.
const snapshotCsv = csvForHistory({ points: [{ ...point(0, 22), id: 'stored-measurement',
  eventId: 'legacy-chart-key', piEventId: null, receiptSource: 'snapshot', message_id: 'sensor-message' }] }, sensors, 'T1');
assert.ok(snapshotCsv.includes('"measurement_id","event_id","receipt_source","sensor_message_id"'));
assert.ok(snapshotCsv.includes('"stored-measurement","","snapshot","sensor-message"'));
const eventCsv = csvForHistory({ points: [{ ...point(0, 22), id: 'stored-measurement',
  piEventId: 'pi-event', receiptSource: 'event', message_id: 'sensor-message' }] }, sensors, 'T1');
assert.ok(eventCsv.includes('"stored-measurement","pi-event","event","sensor-message"'));

console.log("Live-data checks including snapshot/event CSV provenance passed");
