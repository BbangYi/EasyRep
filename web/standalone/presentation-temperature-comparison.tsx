import { temperatureComparisonExample as example } from "./presentation-briefing-content";
import { interpolateTemperature, type Position, type SpatialReading } from "./spatial-data";
import "./presentation-temperature-comparison.css";

type ExamplePoint = typeof example.points[number];
type View = "front" | "top" | "space";
const sensors: SpatialReading[] = example.points.flatMap(point => point.temperature === null ? [] : [{
  id: point.id, label: point.label, positionCm: [...point.position] as Position, value: point.temperature,
}]);
const refuge = example.points.find(point => point.id === "U")!;

function color(value: number) {
  const ratio = Math.max(0, Math.min(1, (value - example.range[0]) / (example.range[1] - example.range[0])));
  const low = [110, 151, 139], high = [212, 179, 114];
  return `rgb(${low.map((channel, i) => Math.round(channel + (high[i] - channel) * ratio)).join(" ")})`;
}

function project([x, y, z]: readonly number[], view: View): [number, number] {
  return view === "space" ? [25 + 210 * x + 75 * y, 215 - 155 * z - 50 * y]
    : [25 + 130 * x, 180 - 150 * (view === "front" ? z : y)];
}

// The same normalized inputs and 16 IDW samples feed both plan and oblique views.
const field = Array.from({ length: 16 }, (_, index) => {
  const x = (index % 4) / 4, y = Math.floor(index / 4) / 4, z = refuge.position[2];
  const corners: Position[] = [[x, y, z], [x + .25, y, z], [x + .25, y + .25, z], [x, y + .25, z]];
  const value = interpolateTemperature([x + .125, y + .125, z], sensors)!;
  return { corners, value };
});

function Field({ view }: { view: "top" | "space" }) {
  return <g className="er24-field" aria-label="가상 입력의 U 높이 IDW 추정 단면">
    {field.map((cell, index) => <polygon key={index} points={cell.corners.map(point => project(point, view).join(",")).join(" ")}
      fill={color(cell.value)} fillOpacity=".72" stroke="#f5f7f1" strokeWidth=".7" data-estimate={cell.value.toFixed(4)} />)}
  </g>;
}

const labelOffsets: Record<View, Record<ExamplePoint["id"], [number, number]>> = {
  front: { T1: [8, -9], T2: [-24, 24], T3: [7, 24], U: [-29, -5] },
  top: { T1: [-27, 26], T2: [-24, 24], T3: [7, -9], U: [-29, 8] },
  space: { T1: [9, -10], T2: [-27, 25], T3: [15, 25], U: [-29, -9] },
};

function Markers({ view }: { view: View }) {
  return example.points.map(point => {
    const [x, y] = project(point.position, view), [dx, dy] = labelOffsets[view][point.id];
    return <g key={point.id} data-point-id={point.id} data-position={point.position.join(",")} data-input={point.temperature ?? "unknown"}>
      <title>{point.id} {point.label}: {point.temperature === null ? "미측정" : `${point.temperature.toFixed(1)}°C, 가상 입력`}</title>
      {point.temperature === null
        ? <path d={`M${x} ${y - 9}l9 9-9 9-9-9Z`} fill="#f5f7f1" stroke="#183429" strokeWidth="2.4" strokeDasharray="4 2" />
        : <circle cx={x} cy={y} r="7" fill={color(point.temperature)} stroke="#183429" strokeWidth="2" />}
      <text x={x + dx} y={y + dy} className="er24-point-label">{point.id}</text>
    </g>;
  });
}

function PlanView({ view }: { view: "front" | "top" }) {
  return <figure className="er24-plan"><figcaption>{view === "front" ? "정면" : "평면 · U 높이"}</figcaption>
    <svg viewBox="0 0 180 215" role="img" aria-label={view === "front" ? "같은 가상 사례의 정면도. T1은 위, T2와 T3는 아래, 미측정 U는 T3보다 위쪽." : "같은 가상 사례의 평면도. T2는 앞왼쪽, T3는 뒤오른쪽, U는 T3보다 앞쪽. 색은 U 높이의 IDW 추정."}>
      <rect x="25" y="30" width="130" height="150" fill="none" stroke="#7e8d52" strokeWidth="1.5" />
      {view === "top" && <Field view="top" />}
      {view === "front" && <path d={`M25 ${project(refuge.position, "front")[1]}H155`} stroke="#899873" strokeDasharray="4 4" />}
      <text x="25" y="23" className="er24-axis-label">{view === "front" ? "위" : "뒤"}</text>
      <text x="25" y="210" className="er24-axis-label">{view === "front" ? "아래" : "앞"}</text>
      <Markers view={view} />
    </svg>
  </figure>;
}

function SpaceView() {
  return <svg className="er24-space" viewBox="0 0 340 240" role="img" aria-label="같은 가상 사례의 사선 3D도. T1 상단 가지, T2 앞쪽 하단, T3 뒤쪽 하단, U는 옮긴 은신처 입구의 미측정점. 색 단면은 2D 평면도와 같은 U 높이의 IDW 추정.">
    <path d="M100 10V165H310M25 215 100 165" fill="none" stroke="#9aaa91" strokeWidth="1.5" strokeDasharray="4 5" />
    <Field view="space" />
    <path d="M25 60H235V215H25ZM25 60 100 10H310V165L235 215M235 60 310 10" fill="none" stroke="#526556" strokeWidth="1.8" />
    <Markers view="space" />
    <text x="26" y="239" className="er24-axis-label">앞</text><text x="306" y="190" className="er24-axis-label">뒤</text>
  </svg>;
}

export default function TemperatureComparison() {
  return <div className="er24-comparison">
    <p className="er24-case">표현 비교용 가상 사례 · 동일 시점·동일 입력</p>
    <table className="er24-matrix" aria-label="같은 가상 온도 입력의 표·2D·3D 비교">
      <colgroup><col className="er24-row-label"/><col/><col/><col/></colgroup>
      <thead><tr><th scope="col">표현</th><th scope="col">표</th><th scope="col">2D 배치도</th><th scope="col">3D 공간 보기</th></tr></thead>
      <tbody>
        <tr className="er24-visual-row"><th scope="row">같은 입력</th>
          <td data-label="표"><table className="er24-inputs" aria-label="공유 가상 입력 3점과 미측정 은신처 U">
            <thead><tr><th scope="col">지점</th><th scope="col">위치</th><th scope="col">온도</th></tr></thead>
            <tbody>{example.points.map(point => <tr key={point.id} data-point-id={point.id} data-position={point.position.join(",")} data-input={point.temperature ?? "unknown"}>
              <th scope="row">{point.id}</th><td>{point.label}</td><td>{point.temperature === null ? <strong>미측정</strong> : `${point.temperature.toFixed(1)}°C`}</td>
            </tr>)}</tbody>
          </table></td>
          <td data-label="2D 배치도"><div className="er24-plans"><PlanView view="front"/><PlanView view="top"/></div></td>
          <td data-label="3D 공간 보기"><SpaceView/></td>
        </tr>
        <tr><th scope="row">바로 읽는 정보</th><td data-label="표">지점별 숫자·미측정 여부</td><td data-label="2D 배치도">정면 높이·평면 위치</td><td data-label="3D 공간 보기">높이·깊이의 동시 배치</td></tr>
        <tr><th scope="row">이 사례의 쓰임</th><td data-label="표">센서값 차이 확인</td><td data-label="2D 배치도">새 은신처와 센서 위치 대조</td><td data-label="3D 공간 보기">입체 배치에서<br/>같은 위치 관계 확인</td></tr>
      </tbody>
    </table>
    <div className="er24-legend"><span>● 센서점 = 입력값</span><span>▦ 색 영역 = IDW 추정</span><span>◇ U = 미측정</span><span className="er24-scale">{example.range[0]}°C <i style={{background:color(example.range[0])}}/><i style={{background:color(24)}}/><i style={{background:color(25)}}/><i style={{background:color(example.range[1])}}/> {example.range[1]}°C</span></div>
    <div className="er24-action"><strong>새 은신처 입구 추가 측정</strong><span>기존 센서값과 비교 후 위치 조정 검토</span></div>
  </div>;
}
