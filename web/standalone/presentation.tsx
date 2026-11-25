/// <reference types="vite/client" />
import { useEffect, useState, type ReactNode } from "react";
import { presentationCategories, presentationScenarios } from "./presentation-content";
import researchLayout from "../public/presentation/research-layout-20261105.jpg?url";
import "./presentation.css";
import PresentationBriefing from "./presentation-briefing";

const chapters = [
  ["problem", "문제"], ["comparison", "기존 방식"], ["approach", "제안 방안"],
  ["scenarios", "사용자 시나리오"], ["evidence", "구현·검증 범위"], ["next", "다음 검증"],
] as const;
const evidence = [
  ["센서 없이 시작·사육 기록", "등록·작성·취소 및 역할 제한", "로컬 서버 회귀 검사", "실제 운영자의 사용성"],
  ["환경 조회·기록", "기간·출처·누락 구분", "로컬 코드·합성 데이터 검증", "장기간 실제 센서 연속 수신"],
  ["공간 추정", "위치 기반 보간과 조건 표시", "로컬 화면·계산 검증", "독립 측정으로 공간 오차 평가"],
  ["발표용 예시", "가상 운영 시나리오", "기능 설명용 구성", "실제 고객·성과 통계가 아님"],
  ["AI 미래 예측", "미연동", "생성된 예측 결과 없음", "데이터 품질·예측 정확도 검증"],
  ["원격 제어", "장치 보고·명령 기록 조회, 원격 명령 미연동", "화면 상태 확인", "물리 동작과 안전 검증은 별도 범위"],
];
function moveTo(id: string) {
  const target = document.getElementById(`presentation-${id}`);
  target?.focus({ preventScroll: true });
  target?.scrollIntoView({ block: "start", behavior: "instant" });
}
function Chapter({ id, number, label, title, children }: { id: string; number: number; label: string; title: string; children: ReactNode }) {
  return <section className="presentation-chapter" aria-labelledby={`presentation-${id}`}>
    <p className="presentation-chapter-label">{number}. {label}</p>
    <h2 id={`presentation-${id}`} tabIndex={-1}>{title}</h2>
    {children}
  </section>;
}

export default function Presentation({ onReturn }: { onReturn: () => void }) {
  return <PresentationBriefing onReturn={onReturn} evidence={(scenarioRequest, onScenarioReferences) => <PresentationEvidence onReturn={onReturn} scenarioRequest={scenarioRequest} onScenarioReferences={onScenarioReferences} />} />;
}

function PresentationEvidence({ onReturn, scenarioRequest, onScenarioReferences }: {
  onReturn: () => void;
  scenarioRequest: { id: string } | null;
  onScenarioReferences: (id: string) => void;
}) {
  const [mode, setMode] = useState<"purpose" | "feature">("purpose");
  const [category, setCategory] = useState("all");
  const [selectedId, setSelectedId] = useState("D2");
  useEffect(() => {
    if (!scenarioRequest || !presentationScenarios.some(s => s.id === scenarioRequest.id)) return;
    setMode("purpose"); setCategory("all"); setSelectedId(scenarioRequest.id);
  }, [scenarioRequest]);
  const visible = mode === "feature" && category !== "all" ? presentationScenarios.filter(s => s.categories.includes(category)) : presentationScenarios;
  const selected = visible.find(s => s.id === selectedId) ?? visible.find(s => s.group === "primary") ?? visible[0];
  function filter(nextMode: typeof mode, nextCategory: string) {
    const candidates = nextMode === "feature" && nextCategory !== "all" ? presentationScenarios.filter(s => s.categories.includes(nextCategory)) : presentationScenarios;
    setMode(nextMode);
    setCategory(nextCategory);
    if (!candidates.some(s => s.id === selectedId)) setSelectedId((candidates.find(s => s.group === "primary") ?? candidates[0]).id);
  }
  function openRelated(id: string) {
    setMode("purpose"); setCategory("all"); setSelectedId(id);
    requestAnimationFrame(() => {
      const target = document.getElementById("presentation-scenario-title");
      target?.focus({ preventScroll: true });
      target?.scrollIntoView({ block: "start", behavior: "instant" });
    });
  }
  return <article className="presentation-page" aria-label="EasyRep 발표 자료">
    <div className="presentation-intro">
      <div className="presentation-intro-top"><span>서비스 소개</span><button onClick={onReturn}>운영 화면으로</button></div>
      <h2 id="presentation-top" tabIndex={-1}>EasyRep 서비스 개요</h2>
      <p className="presentation-thesis">사육장 환경과 관리 기록을 확인하고,<br className="presentation-wide-break" /> 영상 관찰과 분무 제어를 연구합니다.</p>
      <p>첫 사용자는 크레스티드 게코를 키우는 개인 사육자입니다. 환경·관리 이력은 현재 웹 기능이며 영상·분무는 별도 연구 단계입니다.</p>
      <p className="presentation-scope">개인 사육자와 ‘사육장 A’는 가상 사례입니다.<br />연구 자료는 2026-11-05까지의 보고 기준입니다. 현재 웹의 조회·기록 기능과 연구 시험을 구분합니다.</p>
    </div>
    <nav className="presentation-contents" aria-label="발표 목차">
      {chapters.map(([id, label], index) => <button key={id} onClick={() => moveTo(id)}><span>{index + 1}</span>{label}</button>)}
    </nav>
    <Chapter id="problem" number={1} label="문제" title="외출 중 확인할 정보">
      <blockquote>측정 위치·시각·출처와 관측하지 못한 구간의 구분</blockquote>
      <p>크레스티드 게코를 키우는 개인 사육자가 외출 중 사육장 A를 확인합니다. 환경 수치와 관리 기록은 사이트에서 살피되, 영상 관찰과 분무 요청의 판단은 별도 연구 단계라는 구분이 필요합니다.</p>
      <p className="presentation-note">설명을 위한 가상 상황입니다. 사용자 인터뷰나 발생 통계가 아닙니다.</p>
      <ul className="presentation-problems"><li><strong>환경<small>현재 사이트</small></strong><span>측정 위치·시각·출처 확인</span></li><li><strong>관찰<small>별도 연구</small></strong><span>개체 위치와 관측 불가 구간 구분</span></li><li><strong>분무<small>별도 연구</small></strong><span>분무 요청의 허용·보류·정지 조건 확인</span></li></ul>

    </Chapter>
    <Chapter id="comparison" number={2} label="기존 방식" title="기존 제품의 기능과 EasyRep의 개발 방향">
      <p>기존 제품도 측정 이력과 제어 기능을 제공합니다. 비교 범위는 제품별 기능 구성입니다. 시장 전체의 유일성이나 성능 우위는 검증하지 않았습니다.</p>
      <table className="presentation-table"><caption>기존 방식과 EasyRep의 접근 · 공식 자료 확인 2026-11-06</caption>
        <thead><tr><th scope="col">방식</th><th scope="col">제공 기능</th><th scope="col">사용 요구</th><th scope="col">EasyRep의 접근</th></tr></thead>
        <tbody>
          <tr><th scope="row">Exo Terra Monsoon Multi II<div className="presentation-sources"><a href="https://exo-terra.com/products/hydration/humidity/monsoon-multi-ii/" target="_blank" rel="noreferrer">공식 소개 (새 창)</a></div></th><td><span className="presentation-cell-label">제공 기능</span>설정한 간격과 지속시간에 따른 정기 분무</td><td><span className="presentation-cell-label">사용 요구</span>후보 분무 결과와 허용·보류·정지 조건 확인</td><td><span className="presentation-cell-label">EasyRep의 접근</span>별도 연구에서 후보 동작 비교와 상태 조건 확인을 탐색. 현재 사이트의 분무 명령은 미연동</td></tr>
          <tr><th scope="row">Zoo Med Environmental Control Center<div className="presentation-sources"><a href="https://zoomed.com/environmental-control-center/" target="_blank" rel="noreferrer">공식 소개 (새 창)</a><a href="https://zoomed.com/wp-content/uploads/RT-1000_Instructions_9-17-21.pdf" target="_blank" rel="noreferrer">공식 설명서 (새 창)</a></div></th><td><span className="presentation-cell-label">제공 기능</span>온습도·조명 제어, 시간 설정과 온도 경보</td><td><span className="presentation-cell-label">사용 요구</span>측정값과 장치 보고 상태 구분</td><td><span className="presentation-cell-label">EasyRep의 접근</span>측정 출처·시각, 장치 보고와 명령 기록을 구분. 원격 명령은 현재 미연동</td></tr>
          <tr><th scope="row">Zoo Med SlitherSense<div className="presentation-sources"><a href="https://zoomed.com/slither-sense/" target="_blank" rel="noreferrer">공식 소개 (새 창)</a></div></th><td><span className="presentation-cell-label">제공 기능</span>원격 온습도 확인·이력·범위 알림, 복수 센서로 여러 위치 확인</td><td><span className="presentation-cell-label">사용 요구</span>환경 기록·개체 관찰과 관측하지 못한 구간 구분</td><td><span className="presentation-cell-label">EasyRep의 접근</span>현재는 환경·사육 기록을 연결. 두 방향 영상의 관찰 맥락은 별도 연구이며 사이트에 미연동</td></tr>
        </tbody>
      </table>
      <p className="presentation-note">공식 자료의 기능을 짧게 재서술했습니다. 확인하지 않은 경쟁 제품의 기능을 ‘없음’으로 판단하지 않습니다.</p>
    </Chapter>
    <Chapter id="approach" number={3} label="제안 방안" title="사육장별 기록 구성">
      <div className="presentation-flow" aria-label="센서 측정, 관리 기록, 장치 보고를 사육장별 맥락으로 모아 사람이 다음 점검을 판단">
        <ul><li>센서 측정</li><li>사람이 남긴 관리 기록</li><li>장치 보고</li></ul><span aria-hidden="true">→</span><strong>사육장별<br />시간·공간 맥락</strong><span aria-hidden="true">→</span><p>근거를 확인하고<br /><b>다음 점검은 사람이 판단</b></p>
      </div>
      <dl className="presentation-choices"><div><dt>센서 없이 시작</dt><dd>장비가 없어도 사육장과 관리 기록을 먼저 남깁니다.</dd></div><div><dt>기간 이력·공간 추정</dt><dd>기간 추세로 언제 달랐는지, 위치 기반 보간으로 어디를 더 확인할지 살핍니다.</dd></div><div><dt>해석의 근거 표시</dt><dd>실측·가상 데이터·공간 추정을 구분하고 오래된 값과 누락을 드러냅니다.</dd></div><div><dt>변경 이력 보존</dt><dd>직접 입력한 기록과 취소 사유를 남겨 내가 언제 무엇을 고쳤는지 확인합니다.</dd></div></dl>
      <p className="presentation-note">구현된 설계의 특징입니다. 자동 진단·처방·안전 제어를 뜻하지 않으며, 시간 절감이나 생물 건강 개선 효과는 아직 실험 결과가 아닙니다.</p>
      <div className="presentation-research-intent"><h3>연구 목표</h3><p>개인 사육장의 <strong>관찰 맥락</strong>, <strong>위치별 환경 이해</strong>, <strong>후보 분무 결과 비교와 재확인</strong>을 함께 다루면 관리 판단에 도움이 되는지 검증합니다.</p><p>모델 오차·관측 불가·통신 문제와 장치 검증 부담도 추가됩니다. 기능을 묶는 것만으로 더 낫다고 단정하지 않고 같은 조건의 비교 실험으로 이득과 비용을 확인해야 합니다.</p></div>
    </Chapter>
    <Chapter id="scenarios" number={4} label="사용자 시나리오" title="개인 사육자의 세 가지 확인 상황">
      <p>외출 중 환경 확인, 지난 시점의 공간 조회, 마지막 급여·청소 기록을 각각 필요한 상황에서 시작합니다.</p>
      <p className="presentation-note">개인 사육자와 사육장 A는 설명을 위한 가상 사례입니다. 실제 사용자 인터뷰나 수행 결과가 아닙니다.</p>
      <div className="presentation-filters">
        <div role="group" aria-label="시나리오 탐색 방식"><button aria-pressed={mode === "purpose"} onClick={() => filter("purpose", category)}>사용 목적별</button><button aria-pressed={mode === "feature"} onClick={() => filter("feature", category)}>기능별</button></div>
        {mode === "feature" && <label>기능 분류<select value={category} onChange={e => filter(mode, e.target.value)}><option value="all">전체 기능</option>{presentationCategories.map(value => <option key={value}>{value}</option>)}</select></label>}
      </div>
      {([['primary', '주요 사용 상황'], ['supporting', '관련·예외 상황']] as const).map(([group, label]) => {
        const scenarios = visible.filter(s => s.group === group);
        return scenarios.length > 0 && <div className={`presentation-scenario-group presentation-scenario-group-${group}`} key={group}>
          <h3>{label}</h3>
          <div className="presentation-scenario-options" role="group" aria-label={label}>
            {scenarios.map(s => <button key={s.id} aria-pressed={s.id === selected.id} aria-controls="presentation-scenario-detail" onClick={() => setSelectedId(s.id)}><strong>{s.title}</strong></button>)}
          </div>
        </div>;
      })}
      <p className="presentation-selection" role="status">선택한 상황: {selected.title}</p>
      <section id="presentation-scenario-detail" className="presentation-scenario" aria-labelledby="presentation-scenario-title" data-scenario-id={selected.id}>
        <p className="presentation-scenario-actor">{selected.actor}</p>
        <h3 id="presentation-scenario-title" tabIndex={-1}>{selected.title}</h3>
        <p className="presentation-situation">{selected.situation}</p>
        <dl className="presentation-scenario-context"><div><dt>사용 목적</dt><dd>{selected.need}</dd></div><div><dt>시작 조건</dt><dd>{selected.prerequisites}</dd></div></dl>
        <ol className="presentation-storyboard" aria-label="사용자 행동과 화면 응답">{selected.flow.map((step, index) => <li key={step.action}>
          <div className="presentation-storyboard-action"><span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span><h4>{step.action}</h4></div>
          <dl><div><dt>화면 응답</dt><dd>{step.response}</dd></div><div><dt>다음 판단</dt><dd>{step.decision}</dd></div></dl>
        </li>)}</ol>
        <div className="presentation-scenario-outcome"><h4>확인 결과</h4><p>{selected.value}</p></div>
        <details className="presentation-scenario-exceptions" key={selected.id}><summary>관련 예외</summary><ul>{selected.exceptions.map(item => <li key={item}>{item}</li>)}</ul></details>
        <div className="presentation-scenario-links"><h4>이어 볼 상황</h4><div>{selected.related.map(id => { const related = presentationScenarios.find(s => s.id === id)!; return <button key={id} onClick={() => openRelated(id)}>{related.title}</button>; })}</div></div>
        <button className="presentation-scenario-reference" onClick={() => onScenarioReferences(selected.id)}>구현 상태와 관련 근거</button>
      </section>
    </Chapter>
    <Chapter id="evidence" number={5} label="구현·검증 범위" title="구현 현황과 실험 결과">
      <p>사육장별 조회·관리 기록과 연구 산출물을 정리했습니다. 장기간 센서 수신, 사용자 효과와 공간 전체의 오차는 각각 별도 검증 대상입니다.</p>
      <h3>현재 사이트</h3>
      <table className="presentation-table"><caption>구현 상태와 남은 검증</caption><thead><tr>{["항목", "구현한 내용", "확인한 범위", "남은 검증"].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{evidence.map(([item, ...values]) => <tr key={item}><th scope="row">{item}</th>{values.map((value, i) => <td key={i}><span className="presentation-cell-label">{["구현한 내용", "확인한 범위", "남은 검증"][i]}</span>{value}</td>)}</tr>)}</tbody></table>

      <h3 className="presentation-research-heading">선행 연구</h3>
      <p>합성 환경의 예측 비교, 공개 영상의 탐지·추적, 실제 기록 재생과 가상 제어 결과를 날짜와 입력별로 구분합니다.</p>
      <ol className="presentation-research-timeline">
        <li><time dateTime="2026-10-06">2026.10.06</time><div><h4>예측 분무와 3D 복원의 가능성 탐색</h4><p>합성 환경의 후보 분무 비교와 Pi–GPU 요청 시험, 사진 복원 방향을 보고했습니다.</p></div></li>
        <li><time dateTime="2026-10-22">2026.10.22</time><div><h4>탐지·추적 개발 집계와 제작 진행</h4><p>센서 조립, 공개 영상 기반 탐지·추적 평가와 물리 분무·정지의 미검증 범위를 정리했습니다.</p></div></li>
        <li><time dateTime="2026-11-05">2026.11.05</time><div><h4>개인 사육자 중심의 연구 구성</h4><p>실측 기록 재생, 합성 두 영상, Constructa 가상 제어를 구분해 보고했습니다. 카메라와 분무가 현재 사이트에서 동작한다는 뜻은 아닙니다.</p></div></li>
      </ol>
      <p className="presentation-note">발표 날짜가 모든 코드·모델의 업그레이드 순서는 아닙니다. 서로 다른 실험과 평가집합을 하나의 성능 성장 그래프로 합치지 않습니다.</p>
      <aside className="presentation-tradeoff" aria-label="예측 분무 연구의 이점과 비용"><h4>습도 이탈 감소·펌프 작동 증가</h4><p>10월 6일 자료의 합성 비교에서는 예측 제어의 습도 이탈 시간이 줄어든 반면 <strong>펌프 사용 시간과 온도 이탈은 증가</strong>했습니다. 전체 성능 향상이나 물 절약을 입증한 결과로 해석할 수 없습니다.</p></aside>
      <figure className="presentation-research-figure"><img src={researchLayout} width={1280} height={720} loading="lazy" decoding="async" alt="Constructa 가상 배치 모델: 사육장 프레임과 내부 가지, 하부 장치 공간을 배치한 화면. 실물 조립 사진이 아님." /><figcaption>11월 5일 발표자료의 Constructa 배치 모델. 실물 조립·누수·전기 동작 검증 결과와 구분합니다.</figcaption></figure>
      <div className="presentation-questions presentation-research-details" aria-label="선행 연구 상세 근거">
        <details><summary>환경 예측 실험 결과</summary><p>최근 30분의 온습도 4값·펌프 이력과 향후 60분 후보 계획을 입력한 MLP 실험입니다. 학습에 쓰지 않은 <strong>합성 2,352구간</strong>에서 60분 습도 MAE 1.024%p를 보고했습니다. 물 사용량이나 전력의 실측 결과가 아닙니다.</p><p>당시 Pi–GPU 요청 180회의 중앙값 66.3ms는 별도 요청 시험입니다. 센서·분무는 가상이고 60분도 가속한 가상 시간입니다. 현재 웹 지연이나 물리 제어 성능으로 사용할 수 없습니다.</p></details>
        <details><summary>사진 복원·기록 재생·공간 보간 비교</summary><p>10월 자료의 사진 38장 파일 생성 시험과 현재 사이트의 센서 위치 기반 보간은 서로 다른 작업입니다. R3는 <strong>실제 기록 713시점의 재생</strong>을 보고했지만, 색이 있는 공간 전체를 직접 측정한 것은 아닙니다.</p><p>현재 사이트가 R3의 공기 흐름 모델을 그대로 실행하는 것은 아닙니다. 10월 DS18B20 표면 온도 설명과 11월 R3 공기 온도 배치 설명을 동일 설치 실험으로 합치지 않습니다.</p></details>
        <details><summary>탐지·추적 개발 집계와 실물 검증 범위</summary><p>사전학습 검출기·인코더, 학습한 검증기·결합 점수, ByteTrack 기반 추적 수정의 역할을 구분합니다. 10월 22일 자료는 공개 영상 5개에서 AI 검수한 266프레임의 TP 160 / FP 5 / FN 3, F1 약 97.6%를 보고했습니다.</p><p>개발용 집계이며 독립 최종평가·실물 카메라·건강 이상 정확도가 아닙니다. 이전 223 / 0 / 37 집계와 평가집합이 달라 성능 향상률로 비교할 수 없고, 현재 최신 모델 성능도 뜻하지 않습니다.</p></details>
        <details><summary>두 방향 영상의 좌표 생성·미결정 결과</summary><p>R3는 <strong>합성 270프레임 중 87프레임</strong>에서 3D 좌표를 만들고 나머지는 미결정으로 보고했습니다. 87/270을 실제 촬영 정확도로 환산하지 않습니다.</p><p>천장·전면 카메라는 목표 구성입니다. 자료 작성 시점에는 카메라가 미도착 상태였으며, 실시간 사이트 관찰 기능을 검증한 결과가 아닙니다. 미결정 상태를 정지 행동이나 질병·허기·갈증으로 판정하지 않습니다.</p></details>
        <details><summary>조건부 분무의 가상 제어·실물 검증 범위</summary><p>합성 입력에서 약 2초 작동, 300초 대기, 누적 10초 제한과 일부 오류 차단을 보고했습니다. 시험 설정이며 종별 권장값이 아닙니다.</p><p>물 부족·읽기 실패·높은 습도는 ON 중 정지를 관찰했다고 보고했습니다. 오래된 값은 이미 OFF인 상태에서 요청을 차단한 확인에 한정됩니다.</p><p>누적량은 RAM·고정창 방식이며 3초 조건도 같은 loop에 포함됩니다. 독립 하드웨어 안전장치나 재부팅 후 제한 유지를 뜻하지 않습니다. 모델 화면의 물방울·질량·속도는 실제 분무량·물압·전력·기계 검증 결과가 아닙니다.</p></details>
      </div>
    </Chapter>
    <Chapter id="next" number={6} label="후속 검증" title="후속 실험">
      <h3>실물 검증 계획</h3><p>미수행 시험 계획입니다.</p>
      <ol className="presentation-validation"><li><strong>현재 사이트의 사용성</strong><p>분리 도구 방식과 EasyRep으로 마지막 측정 시각·관리 내용을 찾는 성공률과 시간을 비교합니다. 오류·통신 단절·가상 데이터도 올바르게 구분하는지 확인합니다.</p></li><li><strong>공간 표현과 추정</strong><p>표·2D·3D에서 위치를 찾는 시간과 오류를 비교하고, 독립 측정 지점으로 공간 추정 오차와 적용할 수 없는 조건을 확인합니다.</p></li><li><strong>실제 두 카메라의 관찰 범위</strong><p>주야간·가림·시간차에서 관측 가능한 범위를 확인합니다. 질병·허기·갈증 판단은 제외합니다.</p></li><li><strong>빈 사육장에서 분무 동작 확인</strong><p>토출량·누수·전원·정지 후 동작을 먼저 확인한 뒤, 같은 조건에서 정기·임계값·예측 방식을 비교합니다. </p></li></ol>
      <p className="presentation-note">대상자 수·개선율·정확도 목표는 근거 없이 확정하지 않습니다. 실제 수집 실험과 장치 조작은 이 발표 자료의 기능이 아닙니다.</p>
      <div className="presentation-questions"><details><summary>기존 서비스와의 비교</summary><p>측정·그래프 자체를 새로 발명한 것이 아닙니다. 사육장 단위로 관리 기록·환경 맥락·출처와 한계를 함께 다루는 사용 흐름에 초점을 둡니다. 경쟁 제품 전체에 대한 독점 기능 주장은 아닙니다.</p></details><details><summary>공간 보간과 미래 예측</summary><p>현재 3D는 등록된 위치와 센서 값으로 계산하는 보간입니다. 실제 3D 촬영·3DGS·기류 시뮬레이션이나 검증된 온도장이 아니며, 미래 예측은 미연동입니다.</p></details><details><summary>비교 검증 현황</summary><p>기능의 로컬 동작은 확인했으나 사용자 효율·장기 데이터 신뢰성·공간 정확도의 비교 효과는 제안한 검증으로 확인해야 합니다.</p></details></div>
      <div className="presentation-end"><button onClick={() => moveTo("top")}>발표 처음으로</button><button onClick={onReturn}>운영 화면으로</button></div>
    </Chapter>
  </article>;
}
