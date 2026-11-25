import assert from "node:assert/strict";
import { build } from "esbuild";

// Bundle only the pure model in memory. No browser, network, or project output needed.
const result = await build({
  stdin: {
    contents:
      'export * from "./lib/habitat/model"; export * from "./lib/habitat/enclosures";',
    resolveDir: process.cwd(),
    loader: "ts",
  },
  bundle: true,
  write: false,
  platform: "node",
  format: "esm",
});
const model = await import(
  "data:text/javascript;base64," +
    Buffer.from(result.outputFiles[0].text).toString("base64")
);
const {
  DEMO_NOW,
  getReadings,
  getSamples,
  summarize,
  getEvents,
  getRecords,
  filterRecords,
  makeCsv,
  receivedAt,
  inspectSamples,
  closestSampleIndex,
} = model;
let assertions = 0;
function check(condition, message) {
  assert.ok(condition, message);
  assertions++;
}

const normal = getReadings("normal");
check(normal.length === 7, "Seven registered sensors");
const temperature = summarize(normal, "temperature");
check(
  temperature.min === 24.1 &&
    temperature.max === 26.2 &&
    temperature.count === 5,
  "Temperature range is calculated from five readings",
);
check(
  summarize(normal, "humidity").min === 68 &&
    summarize(normal, "light").min === 320,
  "Humidity and light match fixtures",
);
for (const state of ["normal", "offline", "sensor-error"]) {
  const readings = getReadings(state);
  const samples = getSamples(state, 24);
  for (const sensor of readings) {
    if (sensor.reading !== null)
      check(
        samples.find((row) => row.time === sensor.measuredAt)?.[sensor.id] ===
          sensor.reading,
        `${state} ${sensor.id}: summary matches plotted measurement`,
      );
  }
  for (const period of [1, 6, 24]) {
    const rows = getSamples(state, period);
    check(
      rows.length === period * 12 + 1,
      `${period}h range retains five-minute points`,
    );
    check(
      rows[0].time === DEMO_NOW - period * 3_600_000,
      "Range starts at requested time",
    );
    check(
      rows.some((row) => row.T1 === null),
      "Missing intervals remain null",
    );
    check(
      getEvents(state, period).every(
        (event) => event.time <= receivedAt(state),
      ),
      "No device events after last receipt",
    );
  }
}
const error = getReadings("sensor-error");
check(
  error.find((sensor) => sensor.id === "T3").reading === null,
  "Faulty T3 is null, never zero",
);
check(
  summarize(error, "temperature").count === 4 &&
    summarize(error, "temperature").excluded === 1,
  "Faulty T3 is excluded from summary",
);
check(
  getSamples("sensor-error", 1)
    .slice(-3)
    .every((row) => row.T3 === null),
  "Faulty interval ends with null samples",
);
const stale = getReadings("offline");
check(
  stale.every(
    (sensor) =>
      sensor.status === "stale" && sensor.measuredAt <= receivedAt("offline"),
  ),
  "Offline retains timestamped stale readings",
);
check(
  getSamples("offline", 1)
    .filter((row) => row.time > receivedAt("offline"))
    .every((row) =>
      Object.entries(row).every(
        ([key, value]) => key === "time" || value === null,
      ),
    ),
  "Offline never draws future received values",
);
check(
  getReadings("unregistered").length === 0 &&
    getSamples("unregistered", 24).length === 0,
  "Unregistered yields neither sensor values nor graphs",
);
const csv = makeCsv("sensor-error", 1, "temperature", "T3");
const lines = csv.split("\r\n");
check(
  lines.length === 14,
  "Selected one-hour sensor CSV has one header and thirteen samples",
);
check(
  lines.at(-1).includes('"","°C","센서 오류"'),
  "CSV leaves faulty value empty and labels error",
);
check(
  lines.every((line, index) => index === 0 || line.includes('"T3"')),
  "CSV respects sensor selection",
);
check(
  makeCsv("unregistered", 1, "light", "all").split("\r\n").length === 1,
  "Unregistered CSV contains no fabricated rows",
);
const restored = getRecords("normal").find(
  (record) => record.id === "sensor-restored",
);
check(
  restored.recovered === true && restored.acknowledged === false,
  "Problem recovery is independent from user acknowledgement",
);


const historyRecords = getRecords("normal");
const historySnapshot = JSON.stringify(historyRecords);
check(filterRecords(historyRecords, { minutes: 30 }).map((r) => r.id).join() === "cmd-fan,cmd-mist", "Recent period uses the fixed demo clock, newest first");
check(filterRecords(historyRecords, { minutes: 60 }).length === 4, "Hour filter excludes older settings");
check(filterRecords(historyRecords, { query: "  t3   복구  ", kind: "이상 이벤트", status: "복구됨" }).length === 2, "Keyword tokens, target, category and state combine");
check(filterRecords(historyRecords, { query: "5분 환기", kind: "명령", minutes: 30, status: "실행 완료" })[0]?.id === "cmd-fan", "Short summary is searchable across combined filters");
check(filterRecords(historyRecords, { query: "존재하지않는기록" }).length === 0, "Search can return an honest empty result");
check(filterRecords(historyRecords, { kind: "명령", status: "복구됨" }).length === 0, "Conflicting filters do not leak other records");
check(filterRecords(getRecords("sensor-error"), { status: "조치 필요", minutes: 30 })[0]?.id === "active-sensor", "Active sensor error participates in filtering");
check(filterRecords(getRecords("offline", "GW-002"), { query: "gw-002", status: "조치 필요" })[0]?.id === "active-gateway", "Gateway identity is searchable during communication loss");
check(filterRecords(getRecords("offline"), { kind: "명령" }).length === 0, "Offline filtering does not restore unavailable command results");
check(filterRecords(historyRecords, { status: "복구됨" }).some((r) => r.acknowledged === false), "Recovery filtering does not imply acknowledgement");
const boundaryRecords = [-30, -30.001, 1].map((minutes, index) => ({ ...historyRecords[0], id: `boundary-${index}`, time: DEMO_NOW + minutes * 60_000 }));
check(filterRecords(boundaryRecords, { minutes: 30 }).map((r) => r.id).join() === "boundary-0", "Period includes exact boundary and excludes older or future records");
check(JSON.stringify(historyRecords) === historySnapshot, "Filtering leaves source data unchanged");
check(filterRecords([...historyRecords].reverse()).map((r) => r.id).join() === historyRecords.map((r) => r.id).join(), "Unordered input always returns newest first");

const fixture = [
  { time: 10, A: 3, B: 7 },
  { time: 20, A: null, B: 4 },
  { time: 30, A: null, B: Number.NaN },
];
const allStats = inspectSamples(fixture, ["A", "B"]);
check(
  allStats.min === 3 && allStats.max === 7,
  "Period range excludes null and non-finite values",
);
check(
  allStats.received === 3 && allStats.expected === 6,
  "Received count describes individual sensor samples",
);
check(
  allStats.latestIndex === 1,
  "Initial readout finds last received data before a gap",
);
check(
  inspectSamples(fixture, ["B"]).min === 4,
  "Period summary respects sensor selection",
);
check(
  inspectSamples(fixture, ["unknown"]).min === null,
  "Missing sensor never invents zero",
);
check(
  inspectSamples([], ["A"]).expected === 0,
  "Empty history has zero expected samples",
);
check(
  inspectSamples([], ["A"]).latestIndex === -1,
  "Empty history has no last measurement",
);
check(
  inspectSamples([{ time: 0, A: 0 }], ["A"]).received === 1,
  "Real zero remains a valid sample",
);
check(
  closestSampleIndex(fixture, 25) === 1,
  "Nearest-time ties select the earlier sample",
);
check(
  closestSampleIndex(fixture, 29) === 2,
  "Device event selects nearest real timestamp",
);
check(
  closestSampleIndex(fixture, -1) === 0,
  "Out-of-range earlier time clamps to first sample",
);
check(
  closestSampleIndex(fixture, 99) === 2,
  "Out-of-range later time clamps to last sample",
);
check(
  closestSampleIndex([], 20) === -1,
  "No timestamp selection without samples",
);
check(
  closestSampleIndex(fixture, Number.NaN) === -1,
  "Invalid chart input cannot select a false timestamp",
);
const offlineRows = getSamples("offline", 6);
check(
  offlineRows[inspectSamples(offlineRows, ["T1"]).latestIndex].time ===
    receivedAt("offline") - 10_000,
  "Offline initial readout uses the last real measurement",
);
const faultyRows = getSamples("sensor-error", 1);
check(
  faultyRows[inspectSamples(faultyRows, ["T3"]).latestIndex].time ===
    DEMO_NOW - 15 * 60_000,
  "Faulty sensor history ends at its own last valid measurement",
);

// Each enclosure must keep its own values when sensor IDs (T1..L1) are reused.
const { enclosures, sensorLineStyle, needsAttention, getEnclosure } = model;
check(
  new Set(enclosures.map((item) => item.id)).size === enclosures.length,
  "Enclosure identities are unique",
);
for (const enclosure of enclosures) {
  for (const state of ["normal", "sensor-error", "offline", "unregistered"]) {
    const readings = getReadings(state, enclosure.sensors);
    const rows = getSamples(state, 6, enclosure.sensors);
    check(
      readings.every(
        (sensor) =>
          sensor.reading === null ||
          rows.some(
            (row) =>
              row.time === sensor.measuredAt &&
              row[sensor.id] === sensor.reading,
          ),
      ),
      `${enclosure.id}: card, detail and chart share the same values in ${state}`,
    );
    check(
      state !== "unregistered" || (!readings.length && !rows.length),
      "Unregistered enclosure never draws fake history",
    );
  }
  const normalReadings = getReadings("normal", enclosure.sensors);
  check(
    normalReadings.every((sensor) => sensor.reading === sensor.value),
    `${enclosure.id}: history ends at its own fixture values`,
  );
  check(
    enclosure.sensors.every(
      (sensor) => sensorLineStyle(sensor.id, enclosure.sensors)?.color,
    ),
    "Chart styles resolve for cloned per-enclosure sensors",
  );
  check(
    getRecords("offline", enclosure.gateway).find(
      (record) => record.id === "active-gateway",
    ).target === enclosure.gateway,
    "Gateway alert belongs to the selected enclosure",
  );
  const exportCsv = makeCsv(
    "normal",
    1,
    "humidity",
    "all",
    enclosure.sensors,
    enclosure.name,
  );
  check(
    exportCsv.split("\r\n").at(-1).includes(`"${enclosure.name}"`) &&
      exportCsv
        .split("\r\n")
        .at(-1)
        .includes(
          `"${normalReadings.find((sensor) => sensor.id === "H1").reading}"`,
        ),
    "CSV includes selected enclosure identity and its measurements",
  );
}
check(
  getReadings("normal", enclosures[0].sensors)[0].reading !==
    getReadings("normal", enclosures[1].sensors)[0].reading,
  "Enclosure selection does not reuse another enclosure's series",
);
check(
  getReadings("normal", enclosures[0].sensors)[0].reading === 25.6,
  "Reading another enclosure leaves original fixture unchanged",
);
check(
  needsAttention("offline") &&
    needsAttention("sensor-error") &&
    !needsAttention("normal") &&
    !needsAttention("unregistered"),
  "Attention means actionable reception issues, not a suitability score",
);
check(
  getEnclosure("unknown") === undefined,
  "Unknown enclosure is not silently represented as a real registry entry",
);

console.log(
  `${assertions} checks passed: shared values, gaps, scenarios, time ranges, events, CSV, acknowledgement.`,
);
