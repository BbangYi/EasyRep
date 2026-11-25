import assert from "node:assert/strict";
import { build } from "esbuild";
import { createRequire } from "node:module";

const result = await build({
  stdin: { contents: 'export {default as Presentation} from "./standalone/presentation.tsx"; export {default as PresentationVideo} from "./standalone/presentation-video.tsx"; export {default as PresentationReferences} from "./standalone/presentation-references.tsx"; export {default as PresentationReport} from "./standalone/presentation-report.tsx"; export * from "./standalone/presentation-briefing-content.ts"; export {slideSources} from "./standalone/presentation-briefing.tsx"; export {progressNarrative} from "./standalone/presentation-progress-content.ts"; export * from "./standalone/presentation-report-content.ts"; export {presentationScenarios} from "./standalone/presentation-content.ts"; export {createElement} from "react"; export {renderToStaticMarkup} from "react-dom/server";', resolveDir: process.cwd(), loader: "ts" },
  bundle: true, write: false, platform: "node", format: "cjs", jsx: "automatic", loader: { ".css": "empty", ".jpg": "dataurl", ".png": "dataurl", ".mp4": "dataurl" },
});
const module = { exports: {} };
new Function("module", "exports", "require", result.outputFiles[0].text)(module, module.exports, createRequire(import.meta.url));
const { PresentationVideo, slideSources, progressNarrative, Presentation, PresentationReferences, PresentationReport, createElement, renderToStaticMarkup, milestones, milestoneTargets, archivedMilestones, resolveBriefingSlide, briefingOutline, briefingSlides, currentBriefingSlides, archivedBriefingSlides, briefingGroups, presentationScenarios, reportChapters, reportSources, reportReviewItems } = module.exports;
const html = renderToStaticMarkup(createElement(Presentation, { onReturn() {} }));
// Catch stale outline ranges and date links resolving to the wrong deck/index.
assert.match(html, /발표 05–07/);
assert.match(html, /발표 08–11/);
assert.doesNotMatch(html, /발표 05–06|발표 07–09/);
assert.deepEqual(briefingOutline.map(item => [item.slideId, item.range]), [
  ["progress-need-observation", "발표 01–04"],
  ["progress-spatial-method", "발표 05–07"],
  ["progress-appearance-input", "발표 08–11"],
]);
const datedDestinations = [
  ["oct06", ["prediction"], "archive", [5]],
  ["oct22", ["detection"], "archive", [6]],
  ["nov05", ["system"], "archive", [2]],
  ["nov06", ["current"], "archive", [3]],
  ["nov07", ["progress-appearance-input", "progress-detection-result"], "current", [7, 6]],
];
for (const [date, ids, deck, indices] of datedDestinations) {
  assert.deepEqual(milestoneTargets[date].map(target => target.slideId), ids);
  for (const [index, id] of ids.entries()) assert.deepEqual(resolveBriefingSlide(id), { deck, index: indices[index] });
}
assert.equal(resolveBriefingSlide("missing-slide"), null);
assert.equal(resolveBriefingSlide(""), null);
assert.deepEqual(archivedMilestones.map(item => item.id), ["oct06", "oct22", "nov05", "nov06"]);
assert.deepEqual(milestones.map(item => item.id), ["oct06", "oct22", "nov05", "nov06", "nov07", "nov08", "nov09", "nov10", "nov16", "nov17"]);
assert.match(html, />2026\.11\.07 탈피 연구 보기<\/button>/);
assert.match(html, />2026\.11\.07 탐지 평가 보기<\/button>/);
assert.match(html, />전체 타임라인<\/button>/);
assert.match(html, /id="briefing-slide-title"/);
assert.match(html, />상세 설명<\/button>/);
assert.match(html, />결과보고서 개요<\/button>/);
assert.doesNotMatch(html, /교수님/);
assert.equal(briefingSlides.length, 46);
assert.equal(currentBriefingSlides.length, 11);
assert.equal(archivedBriefingSlides.length, 35);
assert.equal(currentBriefingSlides.at(-1).id, "progress-conclusion");
assert.equal(currentBriefingSlides.at(-1).detailSection, "next");
assert.equal(archivedBriefingSlides.at(-1).id, "progress-appearance-result");
assert.deepEqual(currentBriefingSlides.map(s => s.id), ["progress-need-observation", "progress-need-evidence", "progress-need-prediction", "progress-after-r3", "progress-spatial-method", "progress-detection-method", "progress-detection-result", "progress-appearance-input", "progress-appearance-prediction", "progress-humidity-method", "progress-conclusion"]);
const currentNarrative = currentBriefingSlides.map((slide) => [slide.title, slide.lead, slide.caption, ...slide.points, ...slide.notes].join(" ")).join(" ");
assert.doesNotMatch(currentNarrative, /서비스 필요성의 근거와 범위|EasyRep의 보완 범위와 구현 결과|해석 범위/);
const necessitySlide = currentBriefingSlides.find((slide) => slide.id === "progress-need-observation");
assert.equal(necessitySlide.title, "서비스의 필요성");
assert.match(necessitySlide.caption, /사육 조건 조사.*레오파드 게코 임상 기록.*반복 탈피 관찰/);
assert.ok(slideSources["progress-need-observation"].includes("keeper-germany-2014"));
assert.ok(slideSources["progress-need-observation"].includes("keeper-portugal-2021"));
assert.ok(slideSources["progress-need-observation"].includes("keeper-gecko-clinical-2026"));
assert.ok(slideSources["progress-need-observation"].includes("clinical-reptile-behavior-2021"));
assert.ok(slideSources["progress-need-observation"].includes("gecko-ecdysis-repeat-2023"));
assert.match(html, /45\.6% · 57\.0%/);
assert.match(html, /온도 45.6%\(유효 250건\).*습도 57.0%\(유효 149건\)/);
assert.match(html, /220명 중 186명은 기본 조건 하나 이상 미충족/);
assert.match(html, /214마리/);
assert.match(html, /건강 문제·사육 조건을 점검할 임상 신호/);
assert.match(html, /임상기록 214마리: 원인이 바로 특정되지 않은 증상\s*137건 · 식욕 저하·부재 80\s*무기력 34 · 체중 감소 34/);
assert.match(html, /가장 많이 기록된 최종 진단: 탈피 이상/);
assert.match(html, /진단 272건 중 탈피 이상 47건.*별도 반복관찰: 게코 3종 27마리·284일/);
assert.doesNotMatch(html, /자기보고 응답/);
const spatialNeedSlide = currentBriefingSlides.find((slide) => slide.id === "progress-need-evidence");
assert.equal(spatialNeedSlide.title, "서비스의 필요성 - 공간 온도 모델");
assert.match(spatialNeedSlide.conclusion, /열환경의 공간 배치 연구.*센서 실측 기반 모델/);
assert.deepEqual(slideSources["progress-need-evidence"], ["thermal-landscape-2016", "spatial"]);
const spatialNeedNarrative = progressNarrative.find((slide) => slide.id === "progress-need-evidence");
assert.match(JSON.stringify(spatialNeedNarrative.content.stages), /기존 확인 방식/);
assert.match(JSON.stringify(spatialNeedNarrative.content.stages), /Sears 등\(2016\).*체온조절 정확도·이동 비용/);
assert.match(JSON.stringify(spatialNeedNarrative.content.stages), /3DGS 기반 사육장 재구성/);
assert.match(JSON.stringify(spatialNeedNarrative.content.stages), /센서 위치 \+ 동일 시각 실측값/);
assert.match(JSON.stringify(spatialNeedNarrative.content.stages), /3DGS만으로 시간별 온도장을 만들 수 없어 실측값을 연결/);
const projectTimeline = currentBriefingSlides.find((slide) => slide.id === "progress-need-prediction");
assert.equal(projectTimeline.title, "프로젝트 진행 경과");
assert.equal(projectTimeline.conclusion, "");
const projectTimelineNarrative = progressNarrative.find((slide) => slide.id === "progress-need-prediction");
assert.match(JSON.stringify(projectTimelineNarrative), /11\.08.*카메라 연결/);
assert.match(JSON.stringify(projectTimelineNarrative), /11\.09.*현장 장치 배선.*11\.10.*영상 수신 확인/);
assert.match(JSON.stringify(projectTimelineNarrative), /반복 학습·후보 비교/);
assert.match(JSON.stringify(projectTimelineNarrative), /자료 연결·기준선 평가/);
const postR3Results = currentBriefingSlides.find((slide) => slide.id === "progress-after-r3");
assert.equal(postR3Results.title, "R3 이후 검증 결과");
assert.equal(postR3Results.conclusion, "");
assert.match(postR3Results.caption, /운영 이력 수정.*일반 사진 개발평가.*탈피 날짜 예측 비교/);
const postR3Narrative = progressNarrative.find((slide) => slide.id === "progress-after-r3");
assert.match(JSON.stringify(postR3Narrative.content.decisions), /조회 누락 2건 → 0건.*2,002건.*수정 반영/);
assert.match(JSON.stringify(postR3Narrative.content.decisions), /F1 93\.31% → 96\.74%.*305장.*293개.*야간 4\/11 기준 미달/);
assert.match(JSON.stringify(postR3Narrative.content.decisions), /특징 추가로 오차 감소 미확인.*게코 3종 25개체.*개체 분리 5-fold.*예측 기능 미채택/);
assert.match(html, /R3 이후 검증 결과/);
const historyStatus = currentBriefingSlides.find((slide) => slide.id === "progress-spatial-method");
assert.equal(historyStatus.title, "공간 이력 현황");
assert.equal(historyStatus.conclusion, "");
assert.match(historyStatus.caption, /운영 DB 집계.*온도·습도 센서 출처 이력만 포함/);
const historyStatusNarrative = progressNarrative.find((slide) => slide.id === "progress-spatial-method");
assert.match(JSON.stringify(historyStatusNarrative.content), /397,697건.*현재 활용.*과거 시점·위치별 온·습도 조회.*환경 변화·회복 시간 예측.*최근값·규칙 기준선/);
assert.doesNotMatch(JSON.stringify(historyStatusNarrative.content), /관리 결과·개체 상태|관리 기록 0건|사진 0건|아직 연결 불가/);
assert.doesNotMatch(JSON.stringify(historyStatusNarrative.content), /2,002건 경계|시각만으로 다음 페이지/);
assert.ok(slideSources["progress-spatial-method"].includes("liveHistoryAggregate20261118"));
assert.ok(slideSources["progress-spatial-method"].includes("prediction"));
const sheddingResearch = currentBriefingSlides.find((slide) => slide.id === "progress-appearance-input");
assert.equal(sheddingResearch.title, "탈피 상태 판별");
assert.match(sheddingResearch.caption, /외관 상태 분류 학습 감사.*사용 미채택/);
const sheddingResearchNarrative = progressNarrative.find((slide) => slide.id === "progress-appearance-input");
assert.match(JSON.stringify(sheddingResearchNarrative.content.runs), /DINOv2 마지막 block.*사진 19장.*TP 0.*탈피 전 사진 1장.*balanced accuracy 50%/);
assert.match(JSON.stringify(sheddingResearchNarrative.content), /미채택.*정상 · 탈피 전 · 진행 상태/);
const detectionTraining = currentBriefingSlides.find((slide) => slide.id === "progress-detection-method");
assert.equal(detectionTraining.title, "도마뱀 탐지 학습·결합");
assert.equal(detectionTraining.conclusion, "개체 출현 후보 · 검증 경로");
assert.match(JSON.stringify(progressNarrative.find((slide) => slide.id === "progress-detection-method").content), /일반 사진 개발 평가 경로.*YOLO-World 503.*1,474장.*883 update.*고정 DINO 검증기.*Grounding 561 → 562.*64 update.*추가 수락 후보 없음/);
assert.ok(slideSources["progress-detection-method"].includes("modelLearningAudit20261117"));
const sheddingPrediction = currentBriefingSlides.find((slide) => slide.id === "progress-appearance-prediction");
assert.equal(sheddingPrediction.title, "탈피 날짜 예측");
assert.equal(sheddingPrediction.conclusion, "개체 분리 5-fold · 기준선 비교");
assert.match(JSON.stringify(progressNarrative.find((slide) => slide.id === "progress-appearance-prediction").content), /평가 5개체.*집단 중앙값.*MAE 6\.72일.*MAE 7\.03일.*오차 \+0\.31일.*사진·날짜 연결 자료 없음/);
const currentDetection = currentBriefingSlides.find((slide) => slide.id === "progress-detection-result");
assert.equal(currentDetection.title, "도마뱀 탐지 평가");
assert.match(currentDetection.caption, /305장.*11개/);
assert.equal(currentDetection.conclusion, "일반 사진 개발 평가 · 야간 정답 점검");
assert.match(JSON.stringify(progressNarrative.find((slide) => slide.id === "progress-detection-result").content), /FP.*10.*8.*야간 정답 11개 중 탐지.*후보 생성 부족.*후단 검증 실패.*새 사육장.*시간당 오탐/);
assert.doesNotMatch([currentDetection.title, currentDetection.lead, currentDetection.caption, ...currentDetection.notes].join(" "), /67\/736|1,293\/1,423/);
assert.equal(currentBriefingSlides.find((slide) => slide.id === "progress-humidity-method").title, "현장 영상 연동");
assert.match(currentBriefingSlides.find((slide) => slide.id === "progress-humidity-method").caption, /2026\.11\.10.*EasyRep 영상 수신 화면/);
assert.match(JSON.stringify(progressNarrative.find((slide) => slide.id === "progress-humidity-method").content), /카메라 연결.*현장 장치 배선.*사이트 영상 수신.*실제 영상 평가/);
const reportDraft = currentBriefingSlides.find((slide) => slide.id === "progress-conclusion");
assert.equal(reportDraft.title, "결과보고서 초안");
assert.match(JSON.stringify(progressNarrative.find((slide) => slide.id === "progress-conclusion").content.rows), /센서 위치 기반 추정.*야간 정답 4\/11.*날짜 예측 미채택.*수중 펌프 조립/);
assert.doesNotMatch(currentNarrative, /펌프 구동 배선|펌프 구동부|제어 모듈 배선/);
assert.doesNotMatch(currentNarrative, /단일 모델 교체가 아니라|현재 수치는 새 본체 하나의 단독 성능|확인 범위와 아직 부족한 근거|원시 로그와 실패 사례 보존/);
assert.ok(slideSources["progress-detection-result"].includes("modelLearningAudit20261117"));
assert.deepEqual(archivedBriefingSlides.slice(0, 14).map(s => s.id), ["intro", "service", "system", "current", "timeline", "prediction", "detection", "tracking", "temperature", "camera", "misting", "comparison", "status", "next"]);
assert.match(html, /data-deck="current"/);
assert.match(html, /data-slide-id="progress-need-observation"/);
assert.doesNotMatch(html, /briefing-caption|briefing-key-help|← → 넘기기/);
assert.doesNotMatch(currentBriefingSlides.map(s => [s.title, s.conclusion, s.caption, ...s.points.flat()].join(" ")).join(" "), /713|270|66.*86/);
assert.deepEqual(presentationScenarios.filter(s => s.group === "primary").map(s => s.id), ["D2", "D3", "D4"]);
assert.deepEqual(presentationScenarios.filter(s => s.group === "supporting").map(s => s.id), ["D1", "D5", "D6"]);
for (const scenario of presentationScenarios) {
  assert.ok(scenario.actor && scenario.prerequisites && scenario.flow.length && scenario.exceptions.length);
  assert.deepEqual(scenario.steps, scenario.flow.map(step => step.action));
  for (const step of scenario.flow) assert.ok(step.action && step.response && step.decision);
  for (const id of scenario.related) assert.ok(presentationScenarios.some(s => s.id === id));
}
assert.match(html, /id="presentation-scenario-title"[^>]*>[^<]*외출 중/);
assert.equal(new Set(briefingSlides.map(s => s.id)).size, briefingSlides.length);
for (const milestone of milestones) {
  assert.ok(milestoneTargets[milestone.id]?.length, milestone.id);
  for (const target of milestoneTargets[milestone.id]) assert.ok(resolveBriefingSlide(target.slideId), target.slideId);
  assert.ok(milestone.date && milestone.source);
}
for (const slide of briefingSlides) {
  assert.ok(briefingGroups.some(g => g.id === slide.group), slide.id);
  assert.match(html, new RegExp(`id="presentation-${slide.detailSection}"`), slide.id);
  assert.ok(slide.notes.length > 0 && slide.limit && slide.source && slide.caption, slide.id);
  assert.ok(slide.points.length <= 3 && slide.title.length <= 42, slide.id);
}
// Keep the six detailed scenarios reachable while shortening the main talk.
assert.deepEqual(presentationScenarios.map(s => s.id), ["D1", "D2", "D3", "D4", "D5", "D6"]);
assert.equal(milestones.find(m => m.id === "nov06").kind, "사이트 확인");
assert.match(briefingSlides.find(s => s.id === "prediction").caption, /합성/);
assert.match(briefingSlides.find(s => s.id === "current").caption, /합성.*실제 센서 측정이 아닙니다/);
assert.match(briefingSlides.find(s => s.id === "system").caption, /가상.*실물 조립 완료 사진이 아닙니다/);
assert.ok(!milestones.some(m => m.id === "next"));
for (const id of ["detection", "tracking", "temperature", "camera", "misting"]) {
  const slide = briefingSlides.find(s => s.id === id);
  assert.ok(slide.source && slide.limit && slide.notes.length >= 3, id);
}
assert.match(briefingSlides.find(s => s.id === "camera").notes.join(" "), /270.*87/);
assert.match(briefingSlides.find(s => s.id === "detection").notes.join(" "), /같은 동물.*프레임/);
assert.match(briefingSlides.find(s => s.id === "prediction").notes.join(" "), /45–55%RH.*60–70%RH.*75–85%RH/);
// The menu must follow the same order as Next/Previous, not date groups.
const contentsMenu = html.match(/<select[^>]*aria-label="발표 목차"[^>]*>([\s\S]*?)<\/select>/)?.[1];
assert.ok(contentsMenu);
assert.deepEqual([...contentsMenu.matchAll(/<option[^>]*value="(\d+)"/g)].map(match => Number(match[1])), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
console.log("Brief main flow, dated jumps, contextual detail targets and preserved evidence/scenarios passed.");

// Report links must resolve to existing evidence and retain the curated slide deck.
assert.equal(reportChapters.length, 9);
assert.equal(new Set(reportChapters.map(chapter => chapter.id)).size, 9);
assert.deepEqual(reportChapters.map(chapter => chapter.id), ["introduction", "background", "comparison", "system", "screens", "results", "management", "deliverables", "appendix"]);
for (const chapter of reportChapters) {
  assert.ok(chapter.sections.length >= 3 && chapter.gaps.length > 0, chapter.id);
  assert.match(html, new RegExp(`id="presentation-${chapter.detail}"`), chapter.id);
  for (const id of chapter.slides) assert.ok(briefingSlides.some(slide => slide.id === id), id);
  for (const id of chapter.scenarios) assert.ok(presentationScenarios.some(scenario => scenario.id === id), id);
  for (const section of chapter.sections) {
    assert.ok(section.paragraphs.length > 0 && section.paragraphs.every(Boolean));
    for (const id of section.sources) assert.ok(reportSources[id]?.date && reportSources[id]?.location && reportSources[id]?.scope, id);
    for (const row of section.table?.rows ?? []) assert.equal(row.length, section.table.headings.length);
  }
}
assert.equal(new Set(reportReviewItems.map(item => item.id)).size, reportReviewItems.length);
for (const item of reportReviewItems) {
  assert.ok(item.missing && item.check);
  assert.ok(reportChapters.find(chapter => chapter.id === item.chapterId)?.gaps.some(gap => gap.id === item.id));
}
assert.deepEqual(reportChapters.find(c => c.id === "screens").scenarios, presentationScenarios.map(s => s.id));
const prediction = reportChapters.find(c => c.id === "results").sections.find(s => s.title === "예측 분무 비교");
assert.match(prediction.table.caption, /합성.*360분.*6회.*평균/);
assert.deepEqual(prediction.table.rows, [["A · 45–55%RH", "14 → 3.3", "52 → 81.3", "13.5 → 17"], ["B · 60–70%RH", "62.5 → 13.2", "163 → 202.5", "21.8 → 25"], ["C · 75–85%RH", "156.8 → 82", "274 → 331.5", "35.7 → 40.5"]]);
assert.equal(reportSources.prediction.status, "합성 시험 · 발표자료 보고치");
assert.equal(reportSources.release.status, "운영 확인 · 당시 버전");
assert.equal(reportSources.briefing.status, "로컬 검증");
assert.match(reportSources["crested-thermal-gradient-2021"].scope, /체온.*공기온도/);
assert.match(reportSources["gecko-ecdysis-repeat-2023"].scope, /탈피 예측/);
assert.match(reportSources["reptile-smart-environment-2019"].scope, /공개 초록/);
assert.match(reportSources["thermal-landscape-2016"].scope, /공간 배치.*체온조절/);
const background = reportChapters.find(chapter => chapter.id === "background");
assert.ok(background.sections.find(section => section.title === "은신처 조건과 개체의 이용").sources.includes("crested-thermal-gradient-2021"));
assert.ok(background.sections.find(section => section.title === "사진 일지에서 예측 비교까지").sources.includes("gecko-ecdysis-repeat-2023"));
const comparison = reportChapters.find(chapter => chapter.id === "comparison");
assert.ok(comparison.sections.find(section => section.title === "기능 구성 비교").sources.includes("reptile-smart-environment-2019"));
assert.match(comparison.sections.find(section => section.title === "기능 구성 비교").table.rows.flat().join(" "), /스마트 환경제어시스템/);
console.log("Nine report chapters, evidence references, review targets and scenario/slide links passed.");

// References are scoped to the selected chapter and deduplicated without losing provenance.
const noop = () => {};
for (const selected of [null, "system", "introduction"]) {
  const markup = renderToStaticMarkup(createElement(PresentationReport, { selected, onSelect: noop, onReferences: noop }));
  const date = markup.match(/자료 기준: ([0-9.]+)/)?.[1];
  assert.equal(date, selected === "introduction" ? "2026.11.06" : "2026.11.07");
}

const referenceHtml = renderToStaticMarkup(createElement(PresentationReferences, {
  context: { title: "비교 자료", sourceIds: ["web", "monsoon", "web"], gaps: reportReviewItems.filter(item => item.chapterId === "introduction"), slides: ["service"], scenarios: ["D1"], detail: "scenarios" },
  onClose: noop, onSlide: noop, onDetail: noop, onTimeline: noop, onReport: noop,
}));
assert.equal((referenceHtml.match(/id="reference-source-web"/g) ?? []).length, 1);
assert.equal((referenceHtml.match(/id="reference-source-monsoon"/g) ?? []).length, 1);
assert.doesNotMatch(referenceHtml, /id="reference-source-prediction"/);
assert.match(referenceHtml, /<dialog[^>]*aria-labelledby="reference-title"/);
assert.match(referenceHtml, /참고 자료 닫기/);
assert.match(referenceHtml, /https:\/\/exo-terra.com/);
assert.match(referenceHtml, /D1 사용자 시나리오/);
assert.match(referenceHtml, /지난 자료 · 서비스 개요 · 2장/);
assert.match(referenceHtml, /report-gap-submission-info/);
assert.match(referenceHtml, /프로젝트 및 작품 소개 보기/);
for (const chapter of reportChapters) {
  const chapterHtml = renderToStaticMarkup(createElement(PresentationReport, { selected: chapter.id, onSelect: noop, onReferences: noop }));
  assert.doesNotMatch(chapterHtml, /근거 보기|report-gaps|report-review-list|report-related/);
  assert.match(chapterHtml, /참고 자료/);
  for (const section of chapter.sections) for (const figure of section.figures ?? []) assert.ok(figure.src && figure.alt && figure.caption);
}
console.log("Scoped reference content, duplicate removal, source links and clean report body passed.");

for (const slide of briefingSlides) {
  assert.ok(slideSources[slide.id]?.length, slide.id);
  for (const id of slideSources[slide.id]) assert.ok(reportSources[id], `Missing reference ${id} for ${slide.id}`);
}

// A recovery change must not start playback or remove native media controls.
const videoHtml = renderToStaticMarkup(createElement(PresentationVideo, {
  src: "/original-video.mp4", label: "원본 기록 재생 영상",
}));
assert.match(videoHtml, /<video[^>]*controls=""/);
assert.match(videoHtml, /<video[^>]*playsInline=""/);
assert.match(videoHtml, /<video[^>]*preload="metadata"/);
assert.match(videoHtml, /<video[^>]*src="\/original-video.mp4"/);
assert.match(videoHtml, /<video[^>]*aria-label="원본 기록 재생 영상"/);
assert.doesNotMatch(videoHtml, /autoPlay=|loop=|<button/);
console.log("Healthy media keeps native controls, provenance and explicit manual playback.");

assert.deepEqual(archivedBriefingSlides.slice(14, 21).map(s => s.id), ["post-r3-overview", "outdoor-environment", "spatial-context", "care-history", "post-r3-changes", "spatial-history", "post-r3-next"]);

// Moving the detailed material must retain its links and local-review provenance.
const detailIds = ["rationale-goal", "rationale-spatial", "rationale-interpolation", "rationale-detection", "rationale-association", "rationale-shedding", "rationale-misting"];
assert.deepEqual(archivedBriefingSlides.slice(21, 28).map(slide => slide.id), detailIds);
const detailReferences = renderToStaticMarkup(createElement(PresentationReferences, {
  context: {title: "기술별 상세", sourceIds: [], slides: detailIds},
  onClose: noop, onSlide: noop, onDetail: noop, onTimeline: noop, onReport: noop,
}));
for (const [index, id] of detailIds.entries()) {
  assert.match(detailReferences, new RegExp("이전 로컬 검토 · 관찰과 관리 설계 · " + (index + 22) + "장"));
  assert.ok(archivedBriefingSlides.find(slide => slide.id === id));
}

assert.deepEqual(archivedBriefingSlides.slice(28, 32).map(slide => slide.id), ["necessity-overview", "necessity-approach", "rationale-state", "rationale-evaluation"]);
