import { BrainCircuit, Layers3, Clock3, Radio, ChartNoAxesCombined } from "lucide-react";
import type { Cage } from "./live-data";
import { dateTime } from "./live-data";
import { Panel } from "./live-panels";
import type { EnvironmentMode } from "./live-route";

export function EnvironmentInsights({ cage, mode, onMeasured, onManagement }: {
  cage: Cage; mode: Exclude<EnvironmentMode, "measured">;
  onMeasured: () => void; onManagement: () => void;
}) {
  const forecast = mode === "forecast";
  const observed = cage.source === "sensor";
  const source = cage.source === "simulation" ? "가상 데이터 · 학습 대상 제외" : cage.sampledAt ? observed ? "실측 수신 · 이력 검토 필요" : "수신 이력 · 출처 검토 필요" : "실측 이력 없음";
  return <div className="live-insights-layout">
    <Panel title={forecast ? "AI 미래 예측" : "공간 추정"} icon={forecast ? BrainCircuit : Layers3}
      className="live-insights-intro" action={<span className="live-source">연동 예정</span>}>
      <h3>{forecast ? "온도·습도 변화 예측" : "센서 사이의 환경 추정"}</h3>
      <p>{forecast ? "온도·습도의 예상 변화와 불확실성을 확인할 영역입니다." : "센서 위치와 실측값을 바탕으로 내부 환경을 추정할 영역입니다."}</p>
      <div className="live-insights-status"><Clock3 size={20} aria-hidden="true" /><div><strong>아직 생성된 {forecast ? "예측" : "추정"} 결과가 없습니다.</strong><span>{forecast ? "예측 모델과 실측 이력 검증이 필요합니다." : "설치 위치와 공간 추정 모델의 연결이 필요합니다."}</span></div></div>
      <div className="live-care-actions"><button onClick={onMeasured}>실측·수신 이력 보기</button><button onClick={onManagement}>사육장 정보 보기</button></div>
    </Panel>
    <Panel title="현재 데이터 상태" icon={Radio}>
      <dl className="live-description"><dt>수신 센서 구성</dt><dd>{cage.sensors.length ? `${cage.sensors.length}개` : "미수신"}</dd>
        <dt>마지막 측정</dt><dd>{cage.sampledAt ? <>{dateTime(cage.sampledAt)} KST{cage.stale && <small className="live-insights-stale">오래된 데이터</small>}</> : "미수신"}</dd>
        <dt>데이터 출처</dt><dd>{source}</dd><dt>{forecast ? "예측 모델" : "공간 모델"}</dt><dd>미연동</dd>
      </dl>
      <p className="live-note">현재 수신 정보입니다. 분석에 충분한 기간·품질의 데이터인지는 별도 검증이 필요합니다.</p>
    </Panel>
    <Panel title="연동 후 제공할 정보" icon={ChartNoAxesCombined} className="live-insights-planned">
      <div className="live-insights-features">
        <div><strong>{forecast ? "온도·습도 변화" : "사육장 내부 분포"}</strong><p>{forecast ? "실측과 구분된 예상 추이와 예측 대상 기간" : "센서 위치와 추정 구역의 구분"}</p></div>
        <div><strong>불확실성 표시</strong><p>{forecast ? "예측 범위와 데이터 부족·측정 누락 안내" : "추정 가능한 범위와 데이터가 부족한 구역"}</p></div>
        <div><strong>분석 근거</strong><p>사용한 측정 기간·생성 시각·모델 정보</p></div>
      </div>
      <p className="live-note">예상 제공 항목입니다. 분석 결과로 장치를 자동 제어하지 않습니다.</p>
    </Panel>
  </div>;
}
