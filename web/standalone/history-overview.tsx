import { useState } from "react";
import { ChartNoAxesCombined } from "lucide-react";
import { dateTime, metrics, type Cage, type Unit } from "./live-data";
import { Empty, Panel, QueryNotice } from "./live-panels";
import { useLiveQuery } from "./use-live-query";

type Stats = { count: number; avg: number | null; min: number | null; max: number | null };
type Bucket = { at: string; sensorCount: number; commandUpdates: number; careCount: number; readings: Record<string, Stats> };
type Overview = {
  lifetime: { sensorCount: number; firstAt: string | null; lastAt: string | null };
  period: { start: string; end: string; days: number; bucketHours: number; sensorCount: number; otherSourceCount: number; otherConfigurationCount: number };
  sensors: (Stats & { id: string; unit: Unit; invalidCount: number })[];
  buckets: Bucket[];
  commands: { count: number; updates: number };
  care: { count: number; kinds: Record<string, number> };
};
const number = (value: number | null | undefined, digits = 1) => value == null ? "—" : value.toLocaleString("ko-KR", { maximumFractionDigits: digits });
const careLabels: Record<string, string> = { feeding: "급여", cleaning: "청소", shedding: "탈피", weight: "체중", note: "특이사항" };
const stamp = (at: string, hourly: boolean) => new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric", ...(hourly ? { hour: "numeric", hourCycle: "h23" as const } : {}) }).format(new Date(at));
const sensorOrder = (left: { id: string; unit: Unit }, right: { id: string; unit: Unit }) => {
  const rank = (sensor: { id: string; unit: Unit }) => sensor.unit === "degC" ? 0 : sensor.unit === "percent_rh" ? 1 : 2;
  return rank(left) - rank(right) || left.id.localeCompare(right.id, "en");
};

export function HistoryOverview({ cage, compact = false, environmentOnly = false, onOpen }: { cage: Cage; compact?: boolean; environmentOnly?: boolean; onOpen?: () => void }) {
  const [days, setDays] = useState(compact ? 1 : 7);
  const [sensorId, setSensorId] = useState("");
  // Revision parameters separate client caches; the API summarizes its current configuration.
  const query = useLiveQuery<Overview>(`/api/enclosures/${encodeURIComponent(cage.id)}/overview/?days=${days}&geometry_revision=${cage.geometryRevision ?? ""}&placement_revision=${cage.placementRevision ?? ""}`, 60000);
  const data = query.data;
  const sensors = [...(data?.sensors ?? [])].sort(sensorOrder);
  const sensor = sensors.find(s => s.id === sensorId) ?? sensors[0];
  const symbol = metrics.find(m => m.unit === sensor?.unit)?.symbol ?? "";
  return <Panel title={compact ? "최근 24시간 요약" : environmentOnly ? "환경 추세" : "종합 누적 이력"} icon={ChartNoAxesCombined} className="live-overview-panel" action={compact ? <button onClick={onOpen}>종합 이력</button> : undefined}>
    {!compact && <div className="live-overview-filters">
      <div className="live-segment" role="group" aria-label="요약 기간">{[[1, "24시간"], [7, "7일"], [30, "30일"]].map(([value, label]) => <button key={value} aria-pressed={days === value} onClick={() => setDays(Number(value))}>{label}</button>)}</div>
      <span className="live-note">{days === 1 ? "시간별" : "날짜별"} 요약 · 한국 시간</span>
    </div>}
    <QueryNotice query={query} />
    {!data ? <Empty>{query.error ? "요약을 확인할 수 없습니다. 새로고침으로 다시 조회하세요." : "누적 이력을 집계하고 있습니다…"}</Empty> : <>
      <div className="live-overview-coverage">
        <p><strong>기간 내 실측 {number(data.period.sensorCount, 0)}건</strong><span>전체 누적 {number(data.lifetime.sensorCount, 0)}건</span></p>
        {!compact && <p className="live-note">조회 {stamp(data.period.start, days === 1)} ~ {stamp(data.period.end, days === 1)} KST</p>}
      </div>
      <div className={!compact && !environmentOnly ? "live-overview-layout" : ""}>
        <section className="live-overview-trend" aria-label="환경 추세 요약">
          <div className="live-overview-heading"><h3>환경 변화</h3></div>
          {sensors.length ? <div className="live-sensor-tabs" role="group" aria-label="표시 센서">{sensors.map(s => <button key={s.id} type="button" aria-pressed={sensor?.id === s.id} onClick={() => setSensorId(s.id)}>{s.id} · {metrics.find(m => m.unit === s.unit)?.name ?? s.unit}</button>)}</div> : <p className="live-note">센서 미등록</p>}
          <dl className="live-overview-values"><div><dt>평균</dt><dd>{number(sensor?.avg)} <small>{symbol}</small></dd></div><div><dt>최저</dt><dd>{number(sensor?.min)} <small>{symbol}</small></dd></div><div><dt>최고</dt><dd>{number(sensor?.max)} <small>{symbol}</small></dd></div></dl>
          {sensor?.count ? <RangeChart data={data} sensorId={sensor.id} symbol={symbol} /> : <Empty>선택 기간에 이 센서의 유효한 실측이 없습니다.</Empty>}
          <p className="live-note">막대는 최저~최고, 점은 평균입니다. 빈 구간은 측정값 없음이며, 구간 사이를 연결하지 않습니다.</p>
          {sensor && <p className="live-note">{sensor.id} 유효 {number(sensor.count, 0)}건 · 누락·오류 {number(sensor.invalidCount, 0)}건</p>}
        </section>
        {!compact && !environmentOnly && <aside className="live-overview-operations" aria-label="운영 기록 요약">
          <section><h3>장치 명령 기록</h3><p><strong>{number(data.commands.count, 0)}건</strong><span>상태 변경 {number(data.commands.updates, 0)}건</span></p><p className="live-note">기간 내 상태가 보고된 명령입니다. 실제 작동 횟수와는 다릅니다.</p><a href={`#history/${cage.id}?section=device`}>장치 수신 기록 보기</a></section>
          <section><h3>사육 관리</h3><p><strong>{number(data.care.count, 0)}건</strong><span>취소한 기록 제외</span></p>{data.care.count ? <ul>{Object.entries(data.care.kinds).map(([kind, count]) => <li key={kind}>{careLabels[kind] ?? kind}<span>{number(count, 0)}건</span></li>)}</ul> : <p className="live-note">이 기간에 발생한 관리 기록이 없습니다.</p>}<a href={`#history/${cage.id}?section=care`}>사육 관리 기록 보기</a></section>
        </aside>}
      </div>
      {(data.period.otherSourceCount > 0 || data.period.otherConfigurationCount > 0) && <p className="live-note">추세 제외: 가상·기타 출처 {number(data.period.otherSourceCount, 0)}건, 현재와 다른 센서 구성 {number(data.period.otherConfigurationCount, 0)}건. 원본은 유지됩니다.</p>}
      {!compact && <details className="live-overview-details"><summary>{days === 1 ? "시간별" : "날짜별"} 수치와 수집 내역</summary><div className="live-overview-table-wrap"><table><caption>{data.lifetime.firstAt ? `실측 저장 시작 ${dateTime(data.lifetime.firstAt)} KST. ` : "아직 저장된 실측이 없습니다. "}조회 기간에 포함된 기록만 집계합니다. 첫·마지막 구간은 일부 시간만 포함할 수 있습니다. 평균은 측정 건수 기준입니다.</caption><thead><tr><th scope="col">구간 시작</th><th scope="col">실측</th><th scope="col">{sensor?.id ?? "센서"} 평균</th><th scope="col">최저~최고 {symbol}</th><th scope="col">명령 상태 변경</th><th scope="col">사육 관리</th></tr></thead><tbody>{[...data.buckets].reverse().map(b => <tr key={b.at}><th scope="row">{stamp(b.at, days === 1)}</th><td>{number(b.sensorCount, 0)}</td><td>{number(b.readings[sensor?.id ?? ""]?.avg)}</td><td>{number(b.readings[sensor?.id ?? ""]?.min)} ~ {number(b.readings[sensor?.id ?? ""]?.max)}</td><td>{b.commandUpdates}</td><td>{b.careCount}</td></tr>)}</tbody></table></div></details>}
    </>}
  </Panel>;
}

function RangeChart({ data, sensorId, symbol }: { data: Overview; sensorId: string; symbol: string }) {
  const values = data.buckets.flatMap(b => b.readings[sensorId]?.count ? [b.readings[sensorId].min!, b.readings[sensorId].max!] : []);
  const low = Math.min(...values), high = Math.max(...values), pad = Math.max((high - low) * .15, .5);
  const min = low - pad, max = high + pad;
  const y = (v: number) => 18 + (max - v) / (max - min) * 148;
  const x = (i: number) => 62 + (i + .5) * 714 / data.buckets.length;
  const labelIndices = new Set([0, Math.floor((data.buckets.length - 1) / 2), data.buckets.length - 1]);
  return <svg className="live-overview-chart" viewBox="0 0 800 208" role="img" aria-label={`${sensorId} ${data.period.bucketHours === 1 ? "시간별" : "날짜별"} 최저·최고·평균 ${symbol}. 상세 수치는 아래 펼침 영역에서 확인할 수 있습니다.`}>
    {[0, .5, 1].map(t => <g key={t}><line x1={62} x2={776} y1={18 + t * 148} y2={18 + t * 148} stroke="#d9e3dc" /><text x={50} y={22 + t * 148} textAnchor="end">{number(max - t * (max - min))}</text></g>)}
    {data.buckets.map((b, i) => { const s = b.readings[sensorId]; return <g key={b.at}>{s?.count ? <g><title>{stamp(b.at, data.period.days === 1)} · 최저 {number(s.min)} · 평균 {number(s.avg)} · 최고 {number(s.max)} {symbol} · {number(s.count, 0)}건</title><line x1={x(i)} x2={x(i)} y1={y(s.max!)} y2={y(s.min!)} stroke="#91ad9c" strokeWidth={10} strokeLinecap="round" /><circle cx={x(i)} cy={y(s.avg!)} r={3.5} fill="#254d3c" /></g> : <line x1={x(i)-3} x2={x(i)+3} y1={170} y2={170} stroke="#adb9b1" />}{labelIndices.has(i) && <text x={x(i)} y={198} textAnchor={i === 0 ? "start" : i === data.buckets.length - 1 ? "end" : "middle"}>{stamp(b.at, data.period.days === 1)}</text>}</g>; })}
  </svg>;
}
