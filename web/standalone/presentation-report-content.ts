/// <reference types="vite/client" />
import assemblyEnclosure from "../public/presentation/assembly-enclosure-20261022.jpg?url";
import assemblySensors from "../public/presentation/assembly-sensors-20261022.jpg?url";
import detectionResult from "../public/presentation/detection-result-20261022.png?url";
import detectionError from "../public/presentation/detection-false-positive-20261022.png?url";

export type ReportSource = { title: string; date: string; location: string; status: string; scope: string; url?: string; urlLabel?: string };
export type ReportSection = { title: string; paragraphs: string[]; sources: string[]; table?: { caption: string; headings: string[]; rows: string[][] }; figures?: { src: string; alt: string; caption: string; width: number; height: number }[]; flow?: { title: string; text: string }[] };
export type ReportGap = { id: string; title: string; missing: string; check: string };
export type ReportChapter = { id: string; title: string; summary: string; sections: ReportSection[]; gaps: ReportGap[]; slides: string[]; scenarios: string[]; detail: string };

export const reportSources: Record<string, ReportSource> = {
  "keeper-hk-husbandry-2024": {
    "title": "파충류 온도 관리 조사 · Chan 등",
    "date": "2022.03.10–04.11 조사 · 2024.06.12 발표",
    "location": "Animals 14(12), 1767 · Table 7 및 보충 Table S1·S2 · DOI 10.3390/ani14121767",
    "status": "홍콩 자발적 온라인 조사 · 유효 응답 206명",
    "scope": "온도 관리 미충족 36/206명(17.5%)은 응답을 연구 기준으로 분류한 결과입니다. S1은 온도 관찰 방식을, S2는 정기·계절 관리 유무를 기준으로 설명합니다. 실제 온도 이탈·질병 발생률과 구분하며 국내 게코 전체로 일반화하지 않습니다.",
    "url": "https://doi.org/10.3390/ani14121767",
    "urlLabel": "원문 열기"
  },
  "keeper-rrk-2025": {
    "title": "Worldwide Reptile Super Survey 2025 · 국제 사육 현황",
    "date": "2025년 조사 · 2026-05-31 공개",
    "location": "RRK 공개 요약 · 공개일은 발행 단체의 2026-05-31 공지에서 확인",
    "status": "자발적 국제 조사 7,650응답 · 74개국",
    "scope": "2025년 국제 파충류·양서류 사육 현황 조사: 7,650응답, 74개국. 자발적 참여를 바탕으로 사육 단체가 발행한 공개 요약입니다. 보유 종·사육자·입수 경로 등 현황을 다루며 온습도 관리 문제의 발생률이나 제품 효과를 나타내지 않습니다. 모집단 대표성이나 독립 동료심사는 확인하지 않았습니다. 전체 보고서 본문은 확인하지 못했습니다. 공개일 공지: https://responsiblereptilekeeping.substack.com/p/the-results-are-in",
    "url": "https://responsiblereptilekeeping.org/worldwide-reptile-super-survey-report-2025",
    "urlLabel": "원문 열기"
  },
  "keeper-case-position-2025": {
    "title": "Humidity question! · 사육 경험",
    "date": "2025-02-24",
    "location": "Reddit 원 게시물 본문과 작성자 후속 답변 · 날짜는 검색 결과로 확인",
    "status": "크레스티드 게코 사육자 개인 게시물",
    "scope": "작성자는 사육장에 건조한 구역과 습한 구역이 보인다고 문의했습니다. 센서는 은신처 아래 앞쪽과 반대 유리의 상단 부근에 각각 두었다고 답했습니다. 센서 교정·시각 동기화·실제 공간 분포는 미확인입니다. 위치 차이와 센서 오차를 구분할 수 없으며, 3D나 공간 보간의 정확도를 확인한 사례는 아닙니다. 댓글의 관리 권고는 사용하지 않았습니다.",
    "url": "https://www.reddit.com/r/CrestedGecko/comments/1iwp2nn/humidity_question/",
    "urlLabel": "원문 열기"
  },
  "keeper-case-misting-2025": {
    "title": "My wife has concerns · 사육 경험",
    "date": "2025-06-03",
    "location": "Reddit 원 게시물 본문과 작성자 후속 답변 · 날짜는 검색 결과로 확인",
    "status": "크레스티드 게코 사육 가정의 개인 게시물",
    "scope": "수동 분무 뒤 습도 유지의 어려움으로 자동 분무기를 사용한 개인 경험입니다. 작성자는 4시간 간격 45초 작동 후 습도는 유지됐지만 바닥재 과습과 고인 물이 생겼다고 보고했습니다. 디지털 습도계 보유, 설정 조정, 배수층 부재를 밝혔습니다. 작동 시간은 권장 설정이 아닙니다. 배수·바닥재는 현장 점검 대상이며 공기 습도나 예측만으로 해결할 수 있다고 판단하지 않습니다. 분무량·온습도 반응을 함께 평가할 설계의 참고 사례입니다. 댓글 처치법은 사용하지 않았습니다.",
    "url": "https://www.reddit.com/r/CrestedGecko/comments/1l221nt/my_wife_has_concerns/",
    "urlLabel": "원문 열기"
  },
  "keeper-case-appearance-2025": {
    "title": "Is he about to shed · 사육 경험",
    "date": "2025-06-28",
    "location": "검색에 표시된 원 게시물의 본문 일부·날짜 · 원문 전체와 사진은 접근 제한으로 미확인",
    "status": "크레스티드 게코 사육자 개인 게시물",
    "scope": "사육 약 2개월인 작성자가 2–3주 전 사진과 전날 외관을 비교하며 탈피 전조인지 문의했습니다. 체색 변화의 원인과 실제 탈피 여부는 확인되지 않았습니다. 관찰을 해석하는 어려움을 보여주는 개인 경험이며, 탈피 시점 예측의 효용을 검증한 자료는 아닙니다. 댓글의 체색 판정은 사용하지 않았습니다.",
    "url": "https://www.reddit.com/r/CrestedGecko/comments/1lmwgf0/",
    "urlLabel": "원문 열기"
  },
  "keeper-survey-2022": {
    "urlLabel": "원문 열기",
    "title": "뱀 사육 환경·관리 설문 — Cargill 등",
    "date": "2019.08.13–09.08 조사 · 2022 발표",
    "location": "A survey exploring the impact of housing and husbandry on pet snake welfare · Table 5, p.200 · DOI 10.7120/09627286.31.2.004",
    "status": "온라인 뱀 사육자 744명의 자기보고",
    "scope": "습도 미측정 48.1%·온도 미측정 7.7%: 각 분모 744명. 자발적 온라인 응답이며 국내 게코 전체로 일반화할 수 없습니다. 반올림 비율을 정수 응답 수로 역산하지 않았습니다. 측정 여부와 임상징후 점수의 유의한 연관은 확인되지 않았습니다. 미측정의 건강 피해나 AI·3D 효과를 입증하지 않습니다.",
    "url": "https://www.cambridge.org/core/journals/animal-welfare/article/survey-exploring-the-impact-of-housing-and-husbandry-on-pet-snake-welfare/7BED1DBAF7E7736788E3DEDAAC2A352D"
  },
  "keeper-case-morphmarket-2021": {
    "urlLabel": "원문 열기",
    "title": "Crested gecko stuck shed — 사육 경험",
    "date": "2021-10-13",
    "location": "MorphMarket 게시물 본문·작성자 답글",
    "status": "크레스티드 게코 사육자 한 명의 경험",
    "scope": "사육장 교체 뒤 잔여 탈피를 문의하고 난방 시작 후 습도 유지의 어려움을 보고했습니다. 분무 후 상대습도 90% → 12시간 뒤 58%는 작성자의 두 시점 보고입니다. 센서 교정·측정 위치·연속 원자료와 문제 원인은 미확인입니다. 발생률·처치 효과·다음 탈피 예측 효과의 근거가 아닙니다.",
    "url": "https://community.morphmarket.com/t/crested-gecko-stuck-shed/22967"
  },
  "keeper-case-reddit-ventilation": {
    "urlLabel": "원문 열기",
    "title": "How do I keep humidity lower? — 사육 경험",
    "date": "2026-11-07 확인 · 게시일 미확정",
    "location": "Reddit r/CrestedGecko 게시물 본문",
    "status": "개별 사육자의 자기보고",
    "scope": "문을 열거나 팬을 켜 습도를 낮추면 온도도 내려간다는 경험입니다. 장비 정확도·시간별 원자료는 확인되지 않았습니다. 온도와 습도의 동반 변화를 확인할 사례이며, 일반적인 발생 빈도·자동 제어·예측의 효과를 입증하지 않습니다.",
    "url": "https://www.reddit.com/r/CrestedGecko/comments/1jcysm0/how_do_i_keep_humidity_lower/"
  },
  "postR3Delta029": {
    "title": "R3 이후 변경 대조",
    "date": "2026-11-07",
    "location": "post-r3-briefing/delta-audit.json · er-029-persuasive-progress-narrative/worker-delta-audit.json",
    "status": "2026.11.05 R3 이후 운영·개발 결과 대조",
    "scope": "탐지 비교는 2026.11.07 18차 완료 기록까지"
  },
  "historyBoundary029": {
    "title": "공간 이력 경계 수정·운영 조회",
    "date": "2026-11-06",
    "location": "results/er-011-spatial-history-cursor.json · easyrep-release-20261106/REVIEW.txt · easyrep-release-20261106/browser-verification.json",
    "status": "로컬 합성 경계 시험·운영 조회 확인",
    "scope": "동일 시각 합성 2,002건과 별도의 운영 브라우저·API 확인"
  },
  "liveHistoryAggregate20261118": {
    "title": "EasyRep 운영 환경 이력 집계",
    "date": "2026-11-18 14:39 KST",
    "location": "/srv/habitatos/state/habitatos.sqlite3 · edge_event · habitat_carerecord · habitat_enclosurephoto",
    "status": "운영 DB 읽기 전용 집계",
    "scope": "data_source=sensor 환경 이벤트 397,697건(2026.10.19–11.18, 사육장 2곳)입니다. 관리 기록과 사진은 각각 0건입니다. 이벤트 수는 센서 정확도·동물 상태·관리 효과를 입증하지 않습니다."
  },
  "detectorDevelopment029": {
    "title": "배경 후보 추가 학습 비교",
    "date": "2026-11-07",
    "location": "detector-proposal-training-decision-20261107-18/completion-review.json · detector-proposal-training-decision-20261107-18/training-protocol.json · detector-proposal-training-decision-20261107-18/artifact-audit.json",
    "status": "실영상 특징의 개발 학습 비교",
    "scope": "캐시된 실영상 특징·검증기 head·개발 3분할·후보 미채택"
  },
  "modelLearningAudit20261117": {
    "title": "게코 탐지 모델 비교 감사",
    "date": "2026-11-17 19:10 KST",
    "location": "behavior-recorder/data/model-learning-comparison-audit-20261117-564/REPORT.md",
    "status": "개발 사진 305장·야간 정답 11개 재비교",
    "scope": "기준 hybrid/SAM+CLAHE와 현재 결합 파이프라인을 같은 개발 사진에서 대조했습니다. 일반 사진 F1은 93.31%에서 96.74%로 상승했지만, 야간은 4/11 탐지로 현장 적용 판단을 보류했습니다. 새로운 사육장·실제 야간 영상 평가는 다음 단계입니다."
  },
  "appearancePipeline029": {
    "title": "외관 입력·예측·평가 연구 구현",
    "date": "2026-11-07",
    "location": "appearance-prediction-pipeline-20261107-01/completion-review.json · appearance-prediction-evaluation-20261107-02/completion-review.json · appearance-prediction-runner-20261107-03/completion-review.json · appearance-texture-temporal-20261107-08/completion-review.json · appearance-alarm-runner-20261107-09/completion-review.json · appearance-reviewed-intake-20261107-10/completion-review.json · appearance-reviewed-history-20261107-13/completion-review.json",
    "status": "연구 소프트웨어 구현·합성 입력 검증",
    "scope": "합성 자료로 실행 경로 확인·실개체 성능 평가 준비"
  },
  "remoteHistory": {
    "title": "SensorPush 공식 기능 안내",
    "date": "2026-11-06 확인",
    "location": "공식 홈페이지 · 그래프·이력·G1 WiFi Gateway",
    "status": "제조사 기능 설명",
    "scope": "그래프·이력과 G1 게이트웨이를 추가한 인터넷 원격 조회·알림을 안내합니다. 직접 제품을 시험하지 않았으며 EasyRep만의 기능이라는 근거로 쓰지 않습니다.",
    "url": "https://www.sensorpush.com/"
  },
  "careAlternatives": {
    "title": "Reptile Buddy 개발자 앱 설명",
    "date": "2026-11-06 확인",
    "location": "Google Play · 개발자 제공 소개",
    "status": "개발자 기능 설명",
    "scope": "성장·먹이·외형 변화의 기록을 소개합니다. 사육 기록이 기존 도구에서도 가능한 범주임을 확인한 자료이며 세부 기능 부재나 사용 효과를 비교하지 않았습니다.",
    "url": "https://play.google.com/store/apps/details?id=com.reptilebuddy.app"
  },
  "positionContext": {
    "title": "Exo Terra · Crested Gecko 관리 안내",
    "date": "2026-11-06 확인",
    "location": "Heating · 수직 온도 구배와 위치별 확인",
    "status": "제조사 안내 · 위치 고려의 배경",
    "scope": "서로 다른 위치의 환경을 고려하는 배경 자료입니다. 3D 화면의 사용성 우위, 현재 센서 설치 위치 또는 보간 정확도의 검증 근거는 아닙니다. 사육 처방 수치는 재사용하지 않습니다.",
    "url": "https://exo-terra.com/explore/care-guides/lizards/correlophus-ciliatus/"
  },
  "spatialMeaning": {
    "title": "센서 등록 위치와 공간 표시 구현",
    "date": "2026-11-06",
    "location": "standalone/live-spatial.tsx · spatial-data.ts",
    "status": "현재 코드 확인",
    "scope": "등록된 센서 위치와 유효 온도값을 연결합니다. 위치 미확인은 가정 배치로 표시하며 과거 기록은 geometry/placement 버전이 맞아야 합니다. 센서 사이 값은 거리 기반 온도 추정이고, 시각 선택은 공간 화면에서 별도로 수행합니다."
  },
  "necessityPlan": {
    "title": "표시 방식과 기록 탐색 비교 계획",
    "date": "2026-11-06",
    "location": "R3 이후 발표 · 사용 과제와 비교 조건",
    "status": "평가 제안 · 수행 전",
    "scope": "동일한 값·시각·센서 ID·위치 정보를 표·2D·3D로 비교하고, 메모와 현재 웹에서 관리 발생 시각과 환경 기록을 찾는 과제를 제안했습니다. 참여자·일정·결과는 미확정입니다. 새 제품 기능이나 사용자 효과 검증 완료를 뜻하지 않습니다."
  },
  "prediction": {
    "title": "HabitatOS 프로젝트 진행발표",
    "date": "2026-10-06",
    "location": "16·19–26·36장 · 모델 입력, 제어 비교와 예측 시점별 MAE",
    "status": "합성 시험 · 발표자료 보고치",
    "scope": "최근 30분의 온습도·펌프 이력과 향후 60분 후보 계획을 입력하는 합성 모델입니다. 제어 비교는 조건별 360분 × 6회 평균, MAE는 학습에 쓰지 않은 합성 2,352구간입니다. 10월 자료의 두 프로브는 표면 온도 입력으로 설명되어 11월 공기 온도·공간 보간 오차와 구분합니다."
  },
  "detection": {
    "title": "EasryRep AI 진행보고",
    "date": "2026-10-22",
    "location": "5–9장 · 탐지 집계와 추적 연결",
    "status": "연구 자료 · 개발용 집계",
    "scope": "공개 영상 5개, AI 검수 266프레임의 개체 출현 집계. 추적은 같은 44프레임의 연결 가능한 86쌍을 비교했습니다. 독립 최종평가가 아닙니다."
  },
  "r3": {
    "title": "HabitatOS Personal Gecko Research R3",
    "date": "2026-11-05",
    "location": "3–7·9–11·13–19장 · 구성과 시연 결과",
    "status": "연구 자료 · 입력별 구분",
    "scope": "3지점 실측 기록 713시점 재생, 합성 두 영상 270프레임, 가상 분무 제어를 따로 보고했습니다. 원시 로그를 새로 검증하거나 실물 장치를 시험하지 않았습니다. 가상 분무의 누적 10초는 시뮬레이션 시작 기준 고정 86,400초 창의 RAM 예산이며 재시작 시 소실됩니다. 오래된 측정값은 이미 OFF인 상태의 차단만 확인했고 실제 고장 반응시간은 측정하지 않았습니다."
  },
  "counsel": {
    "title": "HabitatOS Personal Gecko Research R3",
    "date": "2026-11-05",
    "location": "3장 · 자문 후 범위와 배치 정리",
    "status": "자문 요약 있음 · 원문 미확보",
    "scope": "음성을 정리한 발표자료의 요약입니다. 개인 사육자 중심과 일체형 배치 방향은 읽을 수 있지만 자문 일시·참여자·원문은 직접 확인하지 못했습니다."
  },
  "web": {
    "title": "EasyRep 웹 구현과 로컬 회귀 검사",
    "date": "2026-11-06",
    "location": "server/config/urls.py, habitat/husbandry.py·models.py, standalone/use-live-query.ts 및 기존 회귀 기록",
    "status": "로컬 검증",
    "scope": "계정과 사육장 범위 조회, 관리 기록의 종류·시각·내용 검증, 중복 제출 방지, 원본·취소 사유 보존을 코드에서 확인했습니다. GET /api/enclosures/{id}/history/·care/·records/는 조회 경로이며, 작성·취소는 POST /manage/enclosures/{id}/care/new/ 및 /care/{record_id}/void/ 폼입니다. 요청 전환·오류 표시·CSV 범위는 기존 회귀 기록과 연결합니다. 실제 사용자 효과나 장기 센서 수신 검증이 아닙니다."
  },
  "search": {
    "title": "센서·장치 기록 출처 검색 검토",
    "date": "2026-11-05",
    "location": "출처 검색 8건 회귀 검사",
    "status": "로컬 합성 시험",
    "scope": "메모리 데이터베이스에서 센서 데이터·가상 데이터 검색을 검토했습니다. 운영 배포 또는 실제 사용자 데이터의 검색을 확인한 기록이 아닙니다."
  },
  "spatial": {
    "title": "공간 이력 커서 검토",
    "date": "2026-11-06",
    "location": "기간·측정 시점·이전 기록 왕복",
    "status": "로컬 검증 · 합성 입력",
    "scope": "같은 시각의 기록과 과거 커서 이동을 검토했습니다. 화면에 보이는 보간 영역은 실측점 사이의 추정이며 공간 전체의 측정 정확도를 검증하지 않았습니다."
  },
  "release": {
    "title": "발표·공간 이력 운영 확인 기록",
    "date": "2026-11-06",
    "location": "당시 운영 16장 발표와 공간 이력 화면",
    "status": "운영 확인 · 당시 버전",
    "scope": "이 기록은 당시 16장 발표 릴리스에 한정됩니다. 이후 발표 수정본, 키보드 수정 및 결과보고서 개요의 운영 배포 증거가 아닙니다."
  },
  "briefing": {
    "title": "누적 14장 발표와 키보드 검토",
    "date": "2026-11-06",
    "location": "목차 01–14, 방향키·전체화면·입력 예외",
    "status": "로컬 검증",
    "scope": "버튼 클릭 후 전환, 첫·끝 포커스, 전체화면 왕복과 표준 소스 테스트 8개를 확인했습니다. 사용자 디자인 승인이나 연구 효과 평가가 아닙니다."
  },
  "monsoon": {
    "title": "Exo Terra Monsoon Multi II 공식 소개",
    "date": "2026-11-06 확인",
    "location": "제품 기능 설명",
    "status": "공식 자료 확인",
    "scope": "설정 간격과 지속시간에 따른 정기 분무. 여기서의 비교는 기능 구성에 한정합니다.",
    "url": "https://exo-terra.com/products/hydration/humidity/monsoon-multi-ii/"
  },
  "ecc": {
    "title": "Zoo Med Environmental Control Center 공식 소개",
    "date": "2026-11-06 확인",
    "location": "제품 기능 설명 및 연결된 RT-1000 설명서",
    "status": "공식 자료 확인",
    "scope": "온습도·조명 등 환경·시간 제어와 온도 경보. 유선 LCD 조작부를 원격 인터넷 제어로 표현하지 않으며 자료에서 확인하지 않은 기능을 없다고 단정하지 않습니다.",
    "url": "https://zoomed.com/environmental-control-center/"
  },
  "slither": {
    "title": "Zoo Med SlitherSense 공식 소개",
    "date": "2026-11-06 확인",
    "location": "원격 측정·이력 설명",
    "status": "공식 자료 확인",
    "scope": "원격 온습도 확인·이력·범위 알림과 복수 센서. 성능이나 사용성의 우위를 비교한 시험이 아닙니다.",
    "url": "https://zoomed.com/slither-sense/"
  },
  "assembly": {
    "title": "EasryRep AI 진행보고",
    "date": "2026-10-22",
    "location": "2장 · 사육장·센서 노드 조립 사진 / 3장 · 10월 20일 수신 화면",
    "status": "과거 실물 조립 사진 · 제공 화면",
    "scope": "아크릴 외함과 ESP32·브레드보드·센서 배선의 조립 사진입니다. 당시 부품 설명은 SEN0331 온습도 센서 1개와 DS18B20 2개로, R3의 SHT31 설명과 동일 부품이라고 단정하지 않습니다. 10월 20일 화면에는 온도 3개·습도 1개의 유효값이 보이지만 가상·개발 검증 표기도 있어 채널 대응, 측정 정확도와 장기 안정성의 근거로 쓰지 않습니다. 이번 편집에서 실물 수신을 재시험하지 않았습니다."
  },
  "planning": {
    "title": "EasryRep AI 진행보고",
    "date": "2026-10-22",
    "location": "12·22·23장 · 구매 검토, 작업 단계와 미확정 역할",
    "status": "당시 후보·제안 계획",
    "scope": "전체 분무 조합의 발주는 당시 미확정이었습니다. 규격 검토→보유품 차감·견적→입고·배선 확인→물·고장 시험의 제안 순서이며, 개인별 담당·일정·합격 수치·지출 금액은 확정 자료가 아닙니다. 현재 재고나 구매 상태를 확인한 결과가 아닙니다."
  },
  "roles": {
    "title": "HabitatOS 프로젝트 진행발표",
    "date": "2026-10-06",
    "location": "31장 · 역할 구성안과 인계 산출물",
    "status": "역할 구성안 · 개인 배정 미정",
    "scope": "하드웨어·현장 수집, AI·실험, 3D·서비스·통합의 책임과 산출물을 나눈 제안입니다. 확정된 개인별 배정이나 완료 실적으로 표시하지 않습니다."
  },
  "geckoVideo": {
    "title": "Pristurus · Tarentola mauritanica - San Vincenzo",
    "date": "2026-11-06 출처 확인",
    "location": "Wikimedia Commons 원본 영상 · CC BY-SA 3.0",
    "status": "탐지 시연 그림의 원본 영상",
    "scope": "게코류 Tarentola mauritanica의 공개 영상이며 크레스티드 게코가 아닙니다. 보고서의 두 그림은 원본 영상에 실제 모델 박스·점수·임시 ID 또는 검수 판정을 덧붙인 기존 발표자료의 편집물입니다. 성공 구간은 결과 확인 후 선택했고 빨간 오탐 표시는 검수 판정입니다.",
    "url": "https://commons.wikimedia.org/wiki/File:Tarentola_mauritanica_-_San_Vincenzo.ogv"
  },
  "geckoLicense": {
    "title": "CC BY-SA 3.0 이용 조건",
    "date": "2026-11-06 원본 출처 확인",
    "location": "탐지 시연에 사용한 Pristurus 영상의 라이선스",
    "status": "원본·편집물 출처 표시",
    "scope": "원저작자 Pristurus와 원본 영상, 변경 사실을 표시합니다. 이 영상에서 만든 탐지 시연 편집물에도 동일한 CC BY-SA 3.0 조건을 적용합니다.",
    "url": "https://creativecommons.org/licenses/by-sa/3.0/"
  },
  "rspca-crested": {
    "title": "RSPCA · Crested Gecko 관리 안내",
    "date": "2026-11-07 확인",
    "location": "온도 구배·위치별 확인·평소 체색과 탈피",
    "status": "사육 맥락의 배경 자료",
    "scope": "생활 구역의 조건과 평소 체색·탈피 이력을 관찰하는 배경입니다. EasyRep의 공간 보간 정확도, 미래 탈피 예측력이나 분무 효과를 검증한 자료가 아닙니다. 사육 처방 수치는 이번 발표에 적용하지 않습니다.",
    "url": "https://www.rspca.org.uk/adviceandwelfare/pets/other/crestedgecko"
  },
  "reptilearn-2024": {
    "title": "Eisenberg·Shein-Idelson, ReptiLearn",
    "date": "2024-02-29",
    "location": "PLOS Biology · 영상 위치 추적과 환경 관찰",
    "status": "별도 종의 선행 연구",
    "scope": "비어디드 드래곤에서 영상 위치와 환경·열영상을 함께 관찰한 연구 사례입니다. 탐지와 별도 영역/열영상 정합의 역할을 참고했습니다. 크레스티드게코의 탈피 예측, EasyRep 성능, 공기온도에서 체온으로의 변환 근거가 아닙니다.",
    "url": "https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.3002411"
  },
  "esri-idw": {
    "title": "Esri · IDW 보간 원리",
    "date": "2026-11-07 확인",
    "location": "ArcGIS Pro · How inverse distance weighted interpolation works",
    "status": "방법 문서",
    "scope": "가까운 관측의 영향이 크다는 가정과 거리 가중치를 설명합니다. 현재 코드의 양수 가중 평균이 입력 최솟값과 최댓값 사이에 머문다는 설명은 코드에 대한 수학적 해석입니다. 현 사육장의 오차나 센서 3개의 충분성을 입증하지 않습니다.",
    "url": "https://doc.esri.com/en/arcgis-pro/latest/help/analysis/geostatistical-analyst/how-inverse-distance-weighted-interpolation-works.html"
  },
  "technicalAudit": {
    "title": "관찰·예측·제어 기술의 구현 근거 점검",
    "date": "2026-11-07",
    "location": "spatial-data.ts14–28 / vision_video.py323–361 / behavior_windows.py14–99·131–206 / appearance.py·appearance_series.py·appearance_journal.py / environment-insights.tsx11–35",
    "status": "읽기 전용 코드·이전 검증 대조",
    "scope": "웹의 온도IDW, 로컬 저장영상 탐지·이동/체류·변화후보, 외관/탈피 수집 도구를 확인했습니다. 예측은 null, 웹 환경예측은 미연동입니다. 11월7일 탈피 파이프라인은 실행 전 계획입니다. 현재 추적기는2.9이고 과거66/86쌍은2.2 결과입니다. 기존 그림의 T6은 임시ID,0.93은 모델점수이며 정확도93%가 아닙니다. 새 실험·현장 성능·생물학적 효과 검증은 하지 않았습니다."
  },
  "technicalResearch": {
    "title": "단순 대안과 비교할 후속 검증 설계",
    "date": "2026-11-07",
    "location": "독립 공간 실측 / 주야간 영상 / 미래 탈피 주기 / 빈 사육장 반응",
    "status": "연구 계획 · 실행 전",
    "scope": "적절한 환경 관리와 정기 관찰은 예측과 관계없이 유지한다. 탈피 예측의 추가 가치는 확인 시점을 더 유용하게 알려 주는지에 있으며, 정기 관찰만으로 충분하면 복잡한 예측을 추가할 이유는 약하다. 비교에는 선행시간·누락·오경보뿐 아니라 추가 촬영·기록 시간과 불필요한 확인 부담도 포함한다. 같은 정보의 표·2D·3D, 수동/움직임 검출과 객체 관찰, 직전 탈피 간격과 외관 특징, 동일 보호조건의 규칙과 예측 제어를 비교할 계획입니다. 조사·자료 수집·장치 시험이나 효과 수치는 이번 발표 작업에서 생성하지 않았습니다."
  },
  "appearanceResearchCurrent": {
    "title": "개체별 외관·탈피 연구 코드",
    "date": "2026-11-07 확인",
    "location": "APPEARANCE.md / appearance_journal.py / appearance_series.py / appearance_timeline.py / appearance_predictor.py / appearance_evaluation.py",
    "status": "읽기 전용 코드 대조 · 합성 검사 기록",
    "scope": "일지는 사람의 관찰·선택 사진을 보존하며 prediction=null입니다. 별도로 검수한 색 특징의 묶음·시계열, 고정 ridge 모델 실행기와 평가 경로가 존재합니다. 일지 첨부가 자동으로 특징 추출·학습·예측으로 이어지는 경로는 아닙니다. 기존 기술 점검의 예측 null은 일지 경로의 상태이며, 현재 별도 연구 실행기의 부재를 뜻하지 않습니다. 실제 개체 학습·운영 알림·생물학적 예측 효과는 미완료입니다. 합성 소프트웨어 검사 기록을 확인했으며 이번 발표 작업에서는 연구 모듈을 import하거나 실행·학습·수집·장치 조작하지 않았습니다."
  },
  "keeper-germany-2014": {
    "title": "Pees 등 · 독일 파충류 사육 조건 평가",
    "date": "2014 발표 / 수집 연도 미기재, 6개월 모집",
    "location": "내원 사육자 자기보고를 기준과 대조",
    "status": "7개 전문 진료기관 설문 304건; 항목별 유효 온도250·습도149",
    "scope": "본문 Table 5·6에서 권장 기준과 큰 차이를 보인 응답은 온도45.6%(유효250건), 습도57.0%(149건)였다. 조명43.3%(240건), 사육장36.6%(227건), 먹이16.9%(213건), 보충제37.1%(186건), 동면46.2%(225건)도 항목별 분모로 제시했다. 초록의 온도43%와 본문45.6%가 달라 그래프에는 본문 표를 사용했다. 현장 실측이나 대표표본이 아닌 내원 사육자의 응답 평가다. 일부 무응답은 제외됐으며 필수정보 미상은 기준 차이로 평가될 수 있다.",
    "url": "https://doi.org/10.2377/0023-2076-59-477",
    "urlLabel": "원문 열기"
  },
  "keeper-portugal-2021": {
    "title": "Azevedo 등 · Pet Reptiles—Are We Meeting Their Needs?",
    "date": "2017.11–2018.02 모집, 설문2020.07까지 공개 / 2021.10.14 발표",
    "location": "병원·온라인 모집 자기보고",
    "status": "포르투갈 파충류 사육자220명; 거북144·뱀41·도마뱀35",
    "scope": "온도·조명·먹이·은신처 네 항목을 모두 충족한 응답은34/220명(논문15%), 하나 이상 미충족은186/220명(논문85%), 두 항목 이하 충족은94/220명(논문43%)이다(Table 1). 비율은 논문의 반올림 값을 따랐다. 습도는 이 네 항목에 포함되지 않는다. 적절한 온도 범위 보고는 뱀69%·도마뱀41%·거북19%로 제시됐으나 각 집단의 유효응답 수를 확인하지 못해 인원으로 환산하지 않았다. 85%는 EasyRep으로 해결할 수 있는 문제의 비율을 뜻하지 않는다.",
    "url": "https://doi.org/10.3390/ani11102964",
    "urlLabel": "원문 열기"
  },
  "keeper-brazil-2023": {
    "title": "De la Fuente 등 · 브라질 파충류 사육 동기·관리",
    "date": "2015 조사 / 2023.10.21 발표",
    "location": "온라인 반구조화 자기보고",
    "status": "브라질 Facebook 사육자719명",
    "scope": "2015년 조사에서719명 중88명(12.2%)이 질환·부상 경험을 보고했다. 경험자88명 중49명(55.6%)은 병원을 방문했고26명(29.5%)은 수의사 지시 없이 투약하거나 환경을 조절했다. 26/88의 분모는 전체 사육자가 아닌 질환·부상 경험자다. 2023년 발표 자료이며 조사 시점은2015년이다. 환경 기록은 진료나 처치를 대신하지 않는다.",
    "url": "https://doi.org/10.1186/s13002-023-00618-z",
    "urlLabel": "원문 열기"
  },
  "keeper-lizard-australia-2017": {
    "title": "Howell·Bennett · 호주 도마뱀 관리",
    "date": "2017 발표",
    "location": "자기보고, 공개 초록 확인",
    "status": "Victoria 도마뱀 사육자316명",
    "scope": "Victoria의 도마뱀 사육자316명을 대상으로 주거·환경·행동·사회·먹이·건강 요구와 관리지침 준수를 검토했다. 공개 초록까지 확인했으며 원문 세부 표는 확보하지 못했다. 같은 Victoria 프로젝트의 다른 종별 보고와 응답자가 겹칠 수 있다.",
    "url": "https://doi.org/10.1016/j.jveb.2017.07.005",
    "urlLabel": "원문 열기"
  },
  "keeper-snake-australia-2020": {
    "title": "Howell 등 · 호주 뱀 관리",
    "date": "2014 모집 계열 / 2020 발표",
    "location": "자기보고; 공개 초록 확인",
    "status": "Victoria 뱀 사육자251명",
    "scope": "공개 초록에서 자신의 뱀 활동양식을 문헌 기준과 맞게 답한 비율은60%였다. 몸을 가로로 완전히 펼 수 있는 공간을 제공한 응답은 절반 미만이었다. 같은 Victoria 프로젝트의 종별 논문이므로 표본을 독립된 인원으로 합산하지 않았다. 행동에 관한 지식과 실제 질환·탐지 효과는 별도의 지표다.",
    "url": "https://doi.org/10.1136/vr.105409",
    "urlLabel": "원문 열기"
  },
  "keeper-gecko-clinical-2026": {
    "title": "Henley·Dutton·Hedley · 레오파드 게코 진료기록",
    "date": "2019.01–2023.01 진료 / 2026.07.31 발표",
    "location": "후향적 진료기록, 일반 건강검진 제외",
    "status": "영국3개병원, 임상문제가 있는 레오파드게코214마리",
    "scope": "새 임상문제로 내원한 레오파드 게코214마리의 후향 기록이다. 원인이 바로 특정되지 않은 증상은137건이며 식욕 저하·부재80건, 잔여 탈피47건, 무기력34건, 체중 감소34건, 눈을 감은 상태27건이 기록됐다. 최종 진단은184마리에서 총272건이 기록됐고 탈피 이상47건이 가장 많았다. 같은 개체에 여러 증상·진단이 함께 기록될 수 있다. 초록의 탈피장애29.96%는 본문 표의 총 진단 수와 분모가 직접 연결되지 않아 발표 그래프에서 제외한다. 일반 사육 게코의 발생률이나 원인·예방 효과를 나타내지 않으며 미래 탈피일 예측의 효용은 별도 평가 대상이다.",
    "url": "https://doi.org/10.1002/vetr.70971",
    "urlLabel": "원문 열기"
  },
  "clinical-reptile-behavior-2021": {
    "title": "Schilliger·Vergneau-Grosset·Desmarchelier · Clinical Reptile Behavior",
    "date": "2021.01 발표",
    "location": "Veterinary Clinics of North America: Exotic Animal Practice 24(1), 175–195 · DOI 10.1016/j.cvex.2020.09.008",
    "status": "파충류 임상 행동 문헌 고찰",
    "scope": "과잉활동·자해·물기·반복 행동·비정상 자세를 임상적으로 검토할 행동 문제로 다루며, 건강 문제와 부적절한 사육 조건을 함께 배제·평가해야 한다고 설명한다. 행동 변화가 실질적인 임상 신호가 될 수 있다는 배경 근거다. 단일 행동으로 특정 질환을 확진할 수 있다는 근거도, EasyRep 객체 탐지의 이상행동 판별 정확도 근거도 아니다.",
    "url": "https://doi.org/10.1016/j.cvex.2020.09.008",
    "urlLabel": "원문 열기"
  },
  "reptile-welfare-delphi-2021": {
    "title": "Whittaker 등 · 파충류 복지지표 Delphi",
    "date": "2020 조사 / 2021 발표",
    "location": "전문가 합의 연구",
    "status": "두 차례 설문을 완료한 전문가23명",
    "scope": "두 차례 설문을 완료한 전문가23명의 합의 연구다. 환경 자원과 개체의 건강·행동 관찰지표를 구분하는 데 참고했다. 사육자의 문제 발생률을 조사한 자료와는 구분된다.",
    "url": "https://doi.org/10.3390/ani11072010",
    "urlLabel": "원문 열기"
  },
  "reptile-welfare-review-2025": {
    "title": "Hanson 등 · 근거 기반 사육 연구 범위검토",
    "date": "2025.11 발표",
    "location": "Scopus/PubMed/Web of Science/Zoological Record 범위검토",
    "status": "72편·75개 사육변경 실험",
    "scope": "사육조건 변경 뒤 복지를 평가한72편·75개 실험을 검토했다. 실험실 연구에 편중돼 있으며 중립·불명확 결과도 포함한다. 이 숫자는 설문 응답자나 사육장 수가 아닌 논문·실험 수다. 기술 적용의 효과를 실제로 비교 평가할 필요성을 뒷받침한다.",
    "url": "https://doi.org/10.1016/j.applanim.2025.106831",
    "urlLabel": "원문 열기"
  },
  "keeper-sweden-thesis-2026": {
    "title": "Wertsén·Matani · 구매 시 사육정보",
    "date": "2026.03.03–16 조사 / 2026.06 학부논문",
    "location": "학부 설문논문",
    "status": "스웨덴29유효응답(55접수);뱀11·도마뱀14·거북4",
    "scope": "구매 시 제공된 정보와 사육기준을 비교한2026년 학부 설문논문이다. 접수55건 중 유효응답29건으로, 뱀11·도마뱀14·거북4건이다. 최근 자료지만 표본이 작고 동료심사 학술논문과 성격이 달라 핵심 그래프와 구분했다.",
    "url": "https://stud.epsilon.slu.se/22407/",
    "urlLabel": "원문 열기"
  },
  "keeper-fbh-2023": {
    "title": "FBH UK Keeper Survey",
    "date": "2023.09–2024.01 조사 / 2025.04 수정",
    "location": "사육단체 현황보고서",
    "status": "영국1788유효응답(1968접수)",
    "scope": "영국의 종·사육 규모·입수경로·사육자 분포를 다룬 단체 현황보고서다. 접수1,968건 중 유효응답은1,788건이다. 전년도 조사 참여23%, 미참여55%, 기억하지 못함22%로 연도 간 응답자가 겹칠 수 있다. 이 표본을 온습도 문제 연구의 분모에 더하지 않았다.",
    "url": "https://www.thefbh.org/_files/ugd/4ca8cc_28543c09af184bc3bce15c0002278cbe.pdf",
    "urlLabel": "원문 열기"
  },
  "keeper-exopet-primary": {
    "title": "EXOPET · 독일 파충류 사육 응답과 조건 평가",
    "date": "2016–2017 조사·보고기간 / 2017·2018 EXOPET 결과",
    "scope": "p205/216/219–220/227–228. 정제 설문3947건, 종별 상세3276참여자, 조건 평가911자료, 기후 평가733자료. 단위와 하위표본을 구분한다. 자발적 응답을 기준과 대조한 평가이며 현장 실측·대표표본으로 해석하지 않는다. 기후는 온도구배·온습도 조절·위치 등을 포함한다. 그림51에 없는 정확한 비율을 역산하지 않았다. 2025년 업로드는 조사연도가 아니다.",
    "url": "https://tierschutz.hessen.de/sites/tierschutz.hessen.de/files/2025-08/zb_teil_3_ergebnis_halter_ohne_technischen_bericht_final_jan2018.pdf",
    "location": "EXOPET 공개 원문 · p205/216/219–220/227–228",
    "status": "정제 설문3,947건 · 조건 평가911자료 · 기후 평가733자료",
    "urlLabel": "원문 열기"
  },
  "keeper-exopet-pogona": {
    "title": "EXOPET 후속 연구 · 비어디드드래곤 사육 평가",
    "date": "2017·2018 EXOPET 결과의 재분석",
    "scope": "p41–43. 기후 평가66건: 부합51.5%, 작은 편차34.8%, 큰 편차13.6%. 별도 유효응답의 주간 측정81/86(94.2%), 야간74/86(86.0%). 온도범위·야간하강 문제를 기술했다. 다른 분모의 측정률과 평가율을 교차분석하거나 전후효과로 계산하지 않는다. 본 EXOPET의 부분표본이라 독립조사로 합산하지 않는다. 보고서의2022자료는 새 사육 설문의 증거로 쓰지 않는다.",
    "url": "https://mlr.baden-wuerttemberg.de/fileadmin/redaktion/m-mlr/intern/dateien/PDFs/SLT/Machbarkeitsstudie_folgend_EXOPET_Bartagame.pdf",
    "location": "EXOPET 후속 공개 보고서 · p41–43",
    "status": "기후66건 · 별도 측정응답86건 · 기존 표본의 재분석",
    "urlLabel": "원문 열기"
  },
  "gehyra-spatial-experiment-2025": {
    "title": "Skelton 등 · Gehyra 게코의 온도·습도 미소환경 선택",
    "date": "2024.12 온라인 / 2025.03 권호",
    "scope": "9종의 세 온도처리별20시간 실험. 두 은신처 각각의 온습도와10초 간격 영상의 출입을 연결했다. 습한 은신처가 더 서늘한27·22도 처리에서는 따뜻하고 건조한 쪽 이용이 많았다. Table1 개체합계95는 모집표 합계이며 제외 규칙이 있는 최종 분석 실험수와 다르다. 구역별 온습도와 이용을 함께 보는 방법 근거이며 크레스티드게코 사육 권장값,3D 편의 또는 EasyRep 예측효과의 검증으로 확장하지 않는다.",
    "url": "https://onlinelibrary.wiley.com/doi/full/10.1002/jez.2890",
    "location": "DOI 10.1002/jez.2890 · 방법·결과",
    "status": "9종 · 처리별20시간 통제실험",
    "urlLabel": "원문 열기"
  },
  "crested-thermal-gradient-2021": {
    "title": "Aparicio Ramirez·Perez·Telemeco · 크레스티드 게코의 체온조절",
    "date": "2020.06.01 온라인 공개 · 2021.01 권호",
    "location": "Journal of Experimental Zoology Part A 335(1), 86–95 · DOI 10.1002/jez.2388",
    "status": "사육 번식 크레스티드 게코 35마리 · 실험실 온도 구배 관찰",
    "scope": "성체 18마리와 어린 개체 17마리의 활동기 체온을 실험실 온도 구배에서 10초 간격으로 기록했습니다. 논문은 선택 체온 범위(TSET)를 약 24–28°C로 보고했습니다. 크레스티드 게코가 미소환경에서 체온을 선택한다는 배경 근거이며, EasyRep의 위치별 공기온도가 체온을 대체하거나 그 범위가 사육장 권장 설정값임을 뜻하지 않습니다. 센서 수·공간 보간·서비스 효과를 평가한 연구도 아닙니다.",
    "url": "https://doi.org/10.1002/jez.2388",
    "urlLabel": "원문 열기"
  },
  "gecko-ecdysis-repeat-2023": {
    "title": "Pillai·Riedel·Schwarzkopf · 게코의 반복 탈피 관찰",
    "date": "2023.05.12 발표",
    "location": "Journal of Experimental Biology 226(10), jeb245286 · DOI 10.1242/jeb.245286",
    "status": "3종 diplodactylid 게코 · 실험 1은 27마리(10·11·6) · 탈피·부착력 실험",
    "scope": "세 게코 종을 2020.03.23–12.31 동안 매일 관찰해 탈피 날짜와 사육장 온도·습도를 기록했고, 탈피 간격은 개체와 종 사이에서 달랐습니다. 부착력 실험의 개체 수는 O. castelnaui10·O. monilis11·S. krisalys6으로 27마리이며, 두 번째 실험에서 O. castelnaui는9마리였습니다. 반복 관찰과 실제 사건 기록의 배경 근거입니다. 크레스티드 게코 자료가 아니며, 직전 간격이 다음 탈피일을 예측한다거나 외관 기반 탈피 예측의 정확도를 입증하지 않습니다. 논문의 주된 결과는 탈피 뒤 부착력 변화입니다.",
    "url": "https://doi.org/10.1242/jeb.245286",
    "urlLabel": "원문 열기"
  },
  "thermal-landscape-2016": {
    "title": "Sears 등 · 열환경의 공간 배치와 체온조절",
    "date": "2016.09.06 발표",
    "location": "PNAS 113(38), 10595–10600 · DOI 10.1073/pnas.1604824113",
    "status": "외온동물 모의·야외 통제실험",
    "scope": "평균과 분산이 같은 온도 분포라도, 적정 온도의 공간 배치가 체온조절 정확도와 이동 비용을 바꿀 수 있음을 모의와 야외 도마뱀 실험으로 보였다. 사육장 센서 보간의 정확도, 3D 화면의 사용성, 크레스티드 게코 사육 효과를 검증한 연구는 아니다.",
    "url": "https://doi.org/10.1073/pnas.1604824113",
    "urlLabel": "원문 열기"
  },
  "reptile-smart-environment-2019": {
    "title": "윤석준·구동주·안교민 · 파충류 사육을 위한 스마트 환경제어시스템",
    "date": "2019.11",
    "location": "한국정보처리학회 학술대회논문집 26(2), 249–252 · KISS key 3861276",
    "status": "국내 학술대회 논문 · 공개 초록 확인",
    "scope": "공개 초록은 미스팅·팬 습도 제어, 조광기 기반 온도 제어, 급이·급수 자동화, 적외선 센서 데이터로 활동량·탈피·질병 가능성을 예상하는 시스템을 제안합니다. 기능 제안 범위의 선행기술 비교에 사용합니다. 공개 초록만 확인했으므로 구현 완성도·정확도·사용 효과·기록 기능 부재를 판단하지 않으며, EasyRep의 현재 기능 우위를 뜻하지 않습니다.",
    "url": "https://kiss.kstudy.com/Detail/Ar?key=3861276",
    "urlLabel": "공개 초록 열기"
  },
  "pogona-enclosure-outcomes-2025": {
    "title": "사육장 구성과 실제 개체 반응 · Denommé·Bakker·Tattersall",
    "date": "2022–2024 관찰 · 2025.06.05 발표",
    "location": "PLOS ONE 20(6), e0322682 · Abstract, Methods, Results · DOI 10.1371/journal.pone.0322682",
    "status": "비어디드드래곤 24마리 · 실험실 사육장 구성 비교",
    "scope": "자연형 사육장은 더 다양한 온도 환경을 제공했으나 행동·복지 개선의 전체 근거는 불명확했습니다. 혈액 지표 차이는 암컷에서만 관찰됐습니다. 환경 조건과 개체 반응을 각각 관찰할 연구 맥락이며 EasyRep·3D·예측의 효과를 평가한 연구가 아닙니다. 모집 24마리를 모든 개별 분석의 유효분모로 사용하지 않습니다. 원자료 재분석은 수행하지 않았습니다.",
    "url": "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0322682",
    "urlLabel": "원문 열기"
  }
};

export const reportChapters: ReportChapter[] = [
  {
    "id": "introduction",
    "title": "프로젝트 및 작품 소개",
    "summary": "환경·관리 기록 서비스와 센서 노드 조립 기록, 영상·분무 실험이 주요 산출물입니다.",
    "sections": [
      {
        "title": "개인 사육자의 환경 확인과 관리 기록",
        "paragraphs": [
          "EasyRep은 사육장별 환경 정보와 사람이 직접 남긴 관리 기록을 조회하는 웹 서비스다. 사육장을 선택해 최근 온도·습도를 확인하고, 급여·청소를 기록한 뒤 이전 날짜의 환경과 관리 내역을 다시 찾는다. 각 기록의 측정·실행 시각과 출처를 유지해 센서값과 사람의 입력을 구별한다.",
          "사육장 등록과 관리 기록은 센서 연결 없이 시작할 수 있다. 관리 종류는 급여·청소·탈피·체중·특이사항이며, 잘못 쓴 기록은 원본과 취소 사유를 남긴 뒤 다시 작성한다. 센서가 없는 사육장은 관리 기록과 별도로 측정 없음 상태를 표시한다."
        ],
        "sources": [
          "web",
          "counsel"
        ],
        "table": {
          "caption": "사육장에 연결되는 정보",
          "headings": [
            "입력 주체",
            "저장·조회 정보",
            "사용하는 화면"
          ],
          "rows": [
            [
              "센서",
              "환경값·측정 시각·출처",
              "환경 이력 / 공간 조회"
            ],
            [
              "사람",
              "관리 종류·실행 시각·내용·작성자·취소 이력",
              "사육 관리"
            ],
            [
              "장치 보고",
              "보고 상태와 기록 시각",
              "장치 기록"
            ]
          ]
        }
      },
      {
        "title": "실물 조립 기록과 개인 사육장 구성",
        "paragraphs": [
          "10월 22일 발표자료에는 아크릴 사육장과 상단 ESP32·브레드보드, 내부로 내려가는 센서 배선의 조립 사진이 담겨 있다. 10월 20일 수신 화면에는 온도 3개와 습도 1개의 유효값이 표시되지만, 이 화면만으로 실물 센서와 채널의 대응이나 장시간 안정성을 확인한 것은 아니다.",
          "11월 5일 자료는 제어부를 뒤쪽에, 물통과 펌프를 아래쪽에 정리한 개인 사육장 배치 모델이다. 천장·전면 카메라와 분무 장치까지 포함한 이후의 구성이므로 기존 조립 사진과 나누어 제시한다."
        ],
        "sources": [
          "assembly",
          "r3"
        ],
        "figures": [
          {
            "src": assemblyEnclosure,
            "width": 1350,
            "height": 1800,
            "alt": "아크릴 사육장과 상단 센서 배선의 기존 조립 사진",
            "caption": "2026.10.22 자료의 사육장 조립 사진 · 이후 카메라·분무 통합 완료를 뜻하지 않음"
          },
          {
            "src": assemblySensors,
            "width": 1350,
            "height": 1800,
            "alt": "사육장 상단 ESP32와 브레드보드·센서 배선의 근접 사진",
            "caption": "2026.10.22 자료의 기존 센서 노드 조립 사진"
          }
        ]
      },
      {
        "title": "웹과 연구의 산출물",
        "paragraphs": [
          "현재 웹에서는 환경·관리·공간 이력을 조회한다. HabitatOS 연구에서는 후보 분무 계획에 따른 환경 변화, 영상 속 개체 탐지와 추적 연결, 조건에 따른 분무 정지를 시험했다. 웹 기능, 실물 조립 기록, 실험·시연 자료를 각각의 결과물로 관리한다."
        ],
        "sources": [
          "prediction",
          "assembly",
          "detection",
          "r3",
          "release"
        ],
        "table": {
          "caption": "자료 기준일별 주요 산출물",
          "headings": [
            "기준일",
            "산출물",
            "자료의 범위"
          ],
          "rows": [
            [
              "2026.10.06",
              "분무 계획별 환경 예측·제어 비교",
              "합성 환경 시험"
            ],
            [
              "2026.10.22",
              "센서 노드 조립 사진·영상 탐지·추적",
              "기존 조립 기록 / 공개 영상 개발 평가"
            ],
            [
              "2026.11.05",
              "개인 사육장 배치·공간 재생·두 영상·분무",
              "가상 배치 / 실측 기록 재생 / 합성·가상 시험"
            ],
            [
              "2026.11.06",
              "웹의 환경·공간 이력 조회",
              "당시 운영 화면 확인"
            ]
          ]
        }
      }
    ],
    "gaps": [
      {
        "id": "submission-info",
        "title": "제출 정보 확인 필요",
        "missing": "역할군과 인계 산출물 구성안은 있지만 개인별 담당과 확정 수행기간의 최신 증빙은 확보하지 못했습니다.",
        "check": "7장의 역할 구성안을 기준으로 담당자와 기간을 확정한 뒤 실제 산출물과 대조합니다. 다른 프로젝트의 인적 사항을 가져오지 않습니다."
      }
    ],
    "slides": [
      "intro",
      "service",
      "system"
    ],
    "scenarios": [
      "D1"
    ],
    "detail": "approach"
  },
  {
  "id": "background",
  "title": "과제의 배경 및 필요성",
  "summary": "설문·통제 실험·진료기록·사육 사례를 네 가지 관리 문제로 종합하고, 기존 대응과 EasyRep의 구현·결과 및 비교평가를 연결합니다.",
  "sections": [
    {
      "title": "관리 문제와 구현 목적의 종합",
      "paragraphs": [
        "지금까지 조사한 자료의 공통 질문은 센서를 보유했는지가 아니라, 실제 사육 조건을 유지하고 관리 변경의 결과를 확인할 수 있는가다. 이를 환경 조건의 유지, 구역별 환경과 이용, 탈피·관리 이력, 자동 분무 후 경과의 네 문제로 정리했다. 설문은 관리 현황, 통제 실험은 조건과 반응의 관계, 진료기록은 관찰·정보의 맥락, 개인 사례는 실제 작업의 흐름을 설명한다. 서로 다른 결과를 하나의 발생률로 계산하지 않았다.",
        "온습도계와 온도 조절기는 현재 상태를 확인하고 설정을 유지하는 기본 수단이다. 데이터로거·이력 앱은 시간 경과, 위치명 표는 구역 비교, 직접 영상과 사진 일지는 개체 관찰을 지원한다. 따라서 EasyRep의 필요성은 기존 도구로 불가능한 문제를 발견했다는 주장에 있지 않다. 같은 관찰 자료를 사육장·위치·시점에 맞춰 조회하고, 반복 영상·외관 분석과 다음 시점 평가를 수행할 구현 경로를 마련하는 데 있다.",
        "환경 조건 평가에서는 EXOPET 비어디드드래곤66건의 권고 부합51.5%·작은 편차34.8%·큰 편차13.6%와 독일 내원 사육자 조사의 온도·습도 기준 차이, 홍콩 조사의 관찰·관리 방식 부족이 확인됐다. 질문과 모집 방식은 다르지만 측정 여부와 관리 조건 충족을 별도로 확인해야 할 맥락을 제공한다. EXOPET의 주간 온도 측정81/86과 야간74/86을 기후 평가66건과 교차 계산하지 않았다. 부족한 설치·지식은 기본 기기와 관리 기준으로 먼저 보완하고, 기록·분석은 주야 경과와 변경 전후를 비교하는 역할을 맡는다.",
        "위치에 관한 근거는 단순히 센서를 늘리자는 주장보다 구체적이다. Gehyra 실험에서 건조 은신처32°C를 고정했을 때 습한 은신처32·27·22°C의 이용시간 비중은46·2·3%였다. 같은 습한 장소라도 온도 조건에 따라 이용이 달랐다. 2025년 비어디드드래곤 사육장 실험에서도 환경의 온도 다양성과 실제 행동·복지 결과를 분리해서 평가했다. 두 센서의 설치 위치를 문의한 사육 사례와 함께 보면, 값의 위치를 확인하고 실제 이용 장면을 관찰하는 작업이 중요하다. 표·단면도·직접 영상으로도 가능한 작업이며, 3D 표현과 분석 자동화의 추가 가치는 별도 비교 대상이다.",
        "대상종 근거도 별도로 둔다. Aparicio Ramirez 등의 크레스티드 게코 실험실 온도 구배 연구에서는 활동기에 개체가 체온을 약24–28°C 범위로 선택했다. 이 결과는 사육장 안의 미소환경을 구분해 기록할 이유를 보강한다. 다만 논문은 체온을 측정한 실험이며 EasyRep이 조회하는 위치별 공기온도와 같지 않다. 이 범위를 사육장 설정값으로 쓰거나 위치별 센서·공간 보간의 효과로 확대하지 않는다.",
        "레오파드게코 임상기록에서는 잔존 탈피 징후47/214와 보조습도 정보 미상92/214가 각각 확인됐다. 증상과 정보 공백을 인과관계로 묶기보다 실제 탈피일·관찰 사진·관리 조건을 시간순으로 정리할 이유로 사용했다. 날짜 있는 사진 일지는 이 목적에 충분한 기본 수단이다. EasyRep의 별도 외관 연구는 검수 사진의 특징을 반복적으로 정리하고, 현재 주기 정보가 직전 간격보다 유용한 확인 시점을 제시할지 비교할 실행 경로를 갖췄다.",
        "자동 분무 사례에서는 타이머를 설치한 뒤 공기습도 유지와 바닥재 물 고임이 동시에 보고됐다. 분무량·배수·바닥재 점검이 먼저이며 환경 이력은 설정 전후의 건조·회복을 확인하는 자료다. 예측 연구는 이 물 고임을 해결했다는 주장이 아니라, 충분한 상하한·대기·보호 규칙에 반응 경과를 더할 가치가 있는지 비교하는 과제다. 같은 현재습도에서도 건조가 계속되는 때와 직전 분무 후 회복하는 때의 작동·대기 시점을 비교하며 온도 영향과 펌프 사용까지 함께 평가한다."
      ],
      "table": {
        "caption": "서로 다른 근거를 관리 문제별로 연결한 종합 · 대표 수치의 분모·연구 범위는 각 상세 절에 유지",
        "headings": [
          "문제와 근거",
          "기존 대응",
          "남는 비교 작업",
          "EasyRep의 역할"
        ],
        "rows": [
          [
            "관리 조건의 충족 / EXOPET·독일·홍콩 조사",
            "온습도계·조절기·관리 기준·이력 앱",
            "밤사이 범위와 관리 변경 전후 확인",
            "측정시각·수신상태·이력·관리기록 조회"
          ],
          [
            "구역 조건과 실제 이용 / Gehyra·Pogona 실험·센서 위치 사례",
            "위치별 센서·위치명 표·직접 영상",
            "그 장소의 온도 경과와 이용 장면 확인",
            "등록 위치·시점의 공기온도 조회 / 별도 저장 영상 분석"
          ],
          [
            "탈피와 관리 이력 / 레오파드게코 진료기록·사진 문의 맥락",
            "날짜 있는 사진·실제 탈피일·직접 관찰",
            "같은 개체의 반복 주기와 현재 변화 대조",
            "사진 검수·특징 시계열·예측·평가 연구 경로"
          ],
          [
            "설정 이후의 분무 반응 / 타이머 과습 사례·기존 합성 연구",
            "분무량·배수 점검 / 상하한·대기·보호 규칙",
            "건조·회복 경과를 고려한 작동 시점 비교",
            "환경 이력과 별도 예측 연구 / 습도·온도·펌프 비용 평가"
          ]
        ]
      },
      "sources": [
        "keeper-exopet-pogona",
        "gehyra-spatial-experiment-2025",
        "crested-thermal-gradient-2021",
        "keeper-gecko-clinical-2026",
        "keeper-case-misting-2025",
        "pogona-enclosure-outcomes-2025",
        "keeper-germany-2014",
        "keeper-hk-husbandry-2024",
        "remoteHistory",
        "spatial",
        "technicalResearch",
        "appearancePipeline029",
        "prediction"
      ]
    },
    {
      "title": "탈피 관찰과 관리 정보의 기록",
      "paragraphs": [
        "영국3개병원의 레오파드게코 진료기록에서는 임상문제가 있는214마리 중47마리에 잔존 탈피 징후가 기록됐고, 보조습도 제공 여부는92마리의 기록에서 미상이었다. 탈피 관찰과 관리 조건을 함께 남길 맥락으로 사용한다. 진료기록의 미상은 실제 미제공을 뜻하지 않으며, 두 항목의 원인 관계를 계산하지 않는다.",
        "날짜 있는 사진, 촬영 조건, 직접 관찰한 탈피일과 관리 내용을 남기면 이미 일어난 경과를 확인할 수 있다. 이 기록의 공백과 미래 탈피 예측의 가치는 다른 문제다. EasyRep 연구는 기록을 검수·특징 시계열·별도 ridge 예측·발행·평가로 연결해 비교 가능한 입력과 결과를 준비했다.11월7일 합성 입력의 정상 실행·보류를 확인했으며, 실제 이후 주기에서 직전 탈피 간격·개체 주기보다 유용한지 확인하는 것이 다음 단계다."
      ],
      "sources": [
        "keeper-gecko-clinical-2026",
        "appearancePipeline029"
      ],
      "table": {
        "caption": "2019.01–2023.01 진료 / 2026.07 발표 · 영국3개병원 · 일반 건강검진 제외 · 두 항목은 합산하지 않음",
        "headings": [
          "진료기록에서 확인한 항목",
          "결과·의미",
          "기록·연구의 연결"
        ],
        "rows": [
          [
            "잔존 탈피 징후",
            "47/214마리 · 내원 기록의 증상",
            "사진·관찰 시각·실제 탈피 사건의 경과 보존"
          ],
          [
            "보조습도 제공 여부 미상",
            "92/214마리 · 관리 정보의 기록 공백",
            "환경·관리 이력을 관찰 기록과 시각으로 대조"
          ],
          [
            "연구 실행 경로",
            "검수 → 특징 이력 → 예측·발행·평가",
            "11.07 합성 입력 정상 실행·보류 → 발표8–10장"
          ]
        ]
      }
    },
    {
      "title": "문헌별 대상과 활용 범위",
      "paragraphs": [
        "문헌은 관리 문제, 환경 조건과 개체 이용, 관찰 기록, 예측 평가라는 질문에 맞춰 구분했다. EXOPET는 관리 조건 평가, Gehyra와 사육장 구성 비교는 환경과 개체 반응, 임상기록은 관찰·관리 정보의 맥락으로 사용한다. 표본 규모를 합쳐 제품 필요성이나 효과를 계산하지 않는다.",
        "질환·부상 경험, 관리기준 충족, 관찰정보 누락은 서로 다른 결과다. 사육 규모나 문헌 수를 문제 빈도로 바꾸지 않는다. 같은 조사에서 나온 후속 보고서와 종별 분석은 중복 표본으로 관리한다."
      ],
      "table": {
        "caption": "원자료 유형·표본·연도·선정 이유",
        "headings": [
          "문헌",
          "확인한 범위",
          "확인 내용과 해석 범위"
        ],
        "rows": [
          [
            "Cargill 등 · 뱀 사육 환경·관리",
            "2019.08.13–09.08 조사 / 2022 발표 / 국제 온라인 뱀 사육자 744명 / 자발적 자기보고 설문",
            "미측정: 습도48.1%·온도7.7%\n현재 또는 과거 탈피 문제 경험28.2%\n국제 온라인 뱀 사육자의 자기보고"
          ],
          [
            "Pees 등 · 독일 파충류 사육 조건 평가",
            "2014 발표 / 수집 연도 미기재, 6개월 모집 / 7개 전문 진료기관 설문 304건; 항목별 유효 온도250·습도149 / 내원 사육자 자기보고를 기준과 대조",
            "항목별 큰 기준 차이: 습도57.0%·온도45.6%\n전문병원 모집·연구 기준에 따른 응답 평가"
          ],
          [
            "Azevedo 등 · Pet Reptiles—Are We Meeting Their Needs?",
            "2017.11–2018.02 모집, 설문2020.07까지 공개 / 2021.10.14 발표 / 포르투갈 파충류 사육자220명; 거북144·뱀41·도마뱀35 / 병원·온라인 모집 자기보고",
            "온도·조명·먹이·은신처 중 1개 이상 미충족186/220(논문85%)\n네 항목을 합친 지표"
          ],
          [
            "Chan 등 · 홍콩 파충류 관리 조사",
            "2022.03.10–04.11 조사 / 2024.06.12 발표 / 홍콩 자발 온라인206명 / 온도관찰/관리방식 등의 연구 분류",
            "온도17.5%·조명27.0%·은신처10.7%·정기검진48.2% 미충족\n항목별 분모와 관리방식 분류"
          ],
          [
            "De la Fuente 등 · 브라질 파충류 사육 동기·관리",
            "2015 조사 / 2023.10.21 발표 / 브라질 Facebook 사육자719명 / 온라인 반구조화 자기보고",
            "질환·부상 경험88/719(12.2%)\n경험자 중 병원 방문49/88(55.6%)\n수의사 지시 없는 투약·환경조절26/88(29.5%)"
          ],
          [
            "Howell·Bennett · 호주 도마뱀 관리",
            "2017 발표 / Victoria 도마뱀 사육자316명 / 자기보고, 공개 초록 확인",
            "주거·환경·행동·먹이·건강 요구와 관리지침 준수 조사\n공개 초록 확인; 세부 비율은 원문 표 확보 후 사용"
          ],
          [
            "Howell 등 · 호주 뱀 관리",
            "2014 모집 계열 / 2020 발표 / Victoria 뱀 사육자251명 / 자기보고; 공개 초록 확인",
            "활동양식을 문헌 기준과 맞게 답한 비율60%\n몸을 완전히 펼 공간 제공은 절반 미만\n공개 초록 결과; 행동 지식과 실제 질환은 별도"
          ],
          [
            "Henley·Hedley · 레오파드 게코 진료기록",
            "2019.01–2023.01 진료 / 2026.07.31 발표 / 영국3개병원, 임상문제가 있는 레오파드게코214마리 / 후향적 진료기록, 일반 건강검진 제외",
            "잔존 탈피 징후47/214 · 보조습도 제공 여부 미상92/214\n임상문제로 내원한 기록 · 별도 항목, 합산·인과 추론 제외"
          ],
          [
            "Whittaker 등 · 파충류 복지지표 Delphi",
            "2020 조사 / 2021 발표 / 두 차례 설문을 완료한 전문가23명 / 전문가 합의 연구",
            "환경 자원과 개체의 건강·행동 관찰지표를 구분\n문제 발생률 대신 관찰 항목 설계의 근거"
          ],
          [
            "Hanson 등 · 근거 기반 사육 연구 범위검토",
            "2025.11 발표 / 72편·75개 사육변경 실험 / Scopus/PubMed/Web of Science/Zoological Record 범위검토",
            "사육조건 변경 뒤 복지를 평가한72편·75실험\n중립·불명확 결과도 포함; 실제 비교평가의 필요성"
          ],
          [
            "Wertsén·Matani · 구매 시 사육정보",
            "2026.03.03–16 조사 / 2026.06 학부논문 / 스웨덴29유효응답(55접수);뱀11·도마뱀14·거북4 / 학부 설문논문",
            "구매 시 제공 정보와 사육기준 비교\n최근 자료지만 유효29명인 학부 연구"
          ],
          [
            "FBH UK Keeper Survey",
            "2023.09–2024.01 조사 / 2025.04 수정 / 영국1788유효응답(1968접수) / 사육단체 현황보고서",
            "보유종·입수경로·사육 규모 중심\n전년도 참여23%로 연도 간 중복 가능"
          ],
          [
            "RRK Worldwide Reptile Super Survey",
            "2025 조사 / 2026 공개 / 7650응답·74개국 / 단체 공개 요약 확인 · 전체 보고서 미확인",
            "보유종·입수경로 등 공개 현황\n문제별 빈도는 확인한 공개 요약에서 미확보"
          ],
          [
            "EXOPET 본보고서",
            "독일 자발적온라인 / 2016–2017보고기간 / 정제3947설문·조건평가911자료·기후733자료",
            "종별조건을 기준과 대조한 연구평가\n원문p205/216/219–220/227–228·Figure51 확인"
          ],
          [
            "EXOPET 비어디드드래곤 재분석",
            "기존2017·2018결과의 부분표본 / 기후66건·측정응답86건",
            "부합51.5%·작은편차34.8%·큰편차13.6%\n원문p41–43 확인 · 본조사와 표본중복"
          ],
          [
            "Skelton 등 · Gehyra 구역선택 실험",
            "2024.12온라인/2025권호 · 9종 · 처리별20시간",
            "두 은신처의 온습도와 이용을 함께 관찰\n원문방법/결과 확인 · 인과실험의 범위는 해당 종·조건"
          ],
          [
            "Denommé 등 · 비어디드드래곤 사육장 구성",
            "2022–2024 관찰 /2025.06.05 발표 / 실험실 사육 비어디드드래곤24마리; 분석별 유효수 상이",
            "온도 다양성 증가와 행동·복지 결과를 분리 / 환경과 실제 개체 반응의 별도 평가"
          ]
        ]
      },
      "sources": [
        "keeper-survey-2022",
        "keeper-germany-2014",
        "keeper-portugal-2021",
        "keeper-hk-husbandry-2024",
        "keeper-brazil-2023",
        "keeper-lizard-australia-2017",
        "keeper-snake-australia-2020",
        "keeper-gecko-clinical-2026",
        "reptile-welfare-delphi-2021",
        "reptile-welfare-review-2025",
        "keeper-sweden-thesis-2026",
        "keeper-fbh-2023",
        "keeper-rrk-2025",
        "keeper-exopet-primary",
        "keeper-exopet-pogona",
        "gehyra-spatial-experiment-2025",
        "pogona-enclosure-outcomes-2025"
      ]
    },
    {
      "title": "질문과 관찰 단위에 따른 근거 선정",
      "paragraphs": [
        "환경 관리, 구역 이용, 외관 기록, 예측 효과를 서로 다른 질문으로 나눴다. EXOPET는 동일 기준의 관리 조건 평가, Gehyra는 같은 실험의 온도 조건 비교, 레오파드게코 진료기록은 관찰·기록 공백의 맥락으로 사용한다. 이 자료와 EasyRep 기능의 연결은 문헌과 구현을 대조한 설계 해석이다.",
        "연구 간 비율을 합쳐 파충류 전체의 실패율을 만들지 않았다. EXOPET 본보고서와 후속분석의 중복, 임상 기록의 내원 편향, 반복 실험의 동일 개체를 유지한다. 질환율·관리 조건 평가·기록 미상은 같은 결과가 아니다. 전체 응답 수나 임상 표본 합계 대신 질문·단위·직접성을 기준으로 아래처럼 채택 범위를 구분했다."
      ],
      "sources": [
        "keeper-exopet-primary",
        "keeper-exopet-pogona",
        "gehyra-spatial-experiment-2025",
        "keeper-gecko-clinical-2026",
        "technicalResearch"
      ],
      "table": {
        "caption": "문제의 근거 / 구현의 검증 / 추가 효과의 평가를 구분",
        "headings": [
          "질문",
          "종합에 적합한 단위",
          "사용 범위"
        ],
        "rows": [
          [
            "환경 관리",
            "동일한66건의 기후 평가3범주",
            "한100%막대 · 측정86명과 교차 계산 제외"
          ],
          [
            "위치별 조건",
            "같은 실험의32/27/22°C 처리",
            "은신처 체류시간 비중 비교 · 원자료 재분석 없이 논문값 사용"
          ],
          [
            "외관·관리 기록",
            "임상214마리의 서로 다른 기록 항목",
            "증상47건과 미상92건 각각 설명"
          ],
          [
            "예측 효과",
            "같은 기준선·보호조건의 비교",
            "외부 문제율로 효과 추론 대신 자체 비교평가"
          ],
          [
            "그 밖의 설문·임상 자료",
            "모집·종·분모·평가기준별 유지",
            "문헌 목록의 보조 맥락 · 통합 발생률 산출 제외"
          ]
        ]
      }
    },
    {
      "title": "두 센서의 위치 차이와 비교 기록",
      "paragraphs": [
        "2025년2월24일 게코 사육 게시물의 작성자는 은신처 아래 앞쪽과 반대편 상단에 센서를 두고, 몇 시간 뒤 생기는 습한 구역과 건조한 구역을 문의했다. 이미 두 지점을 측정하고 있었지만 각 위치의 값과 변화 경과를 함께 해석하는 문제가 남았다.",
        "기본 대응은 센서를 같은 곳에 두어 차이를 점검하고, 설치 위치·측정시각을 기록하는 것이다. 위치명 표·2D 배치도와 기존 이력 앱으로도 비교할 수 있다. EasyRep은 등록 위치와 과거 시점의 공기온도를 함께 조회하며, 센서 사이 온도는IDW 추정으로 표현한다. 습도 사례에서 제기된 위치 비교 요구를 현재 온도 기능에 연결한 것이고, 습도 공간화는 확장 과제다.",
        "R3 이후 작업은 이 비교에 필요한 이력의 누락을 고친 것이다. 서버가 제공하는 시각·ID 커서를 클라이언트가 함께 보내도록 수정했다. 동일시각 합성2002건 시험에서2000+0이2000+2로 조회되고 중복0건을 확인했다. 11월6일 운영조회 확인은 별도 증거다. 사용자 편의와 공간 추정 정확도는 기능평가에서 따로 다룬다."
      ],
      "table": {
        "caption": "기본 측정 → 비교 정보 → 구현 결과",
        "headings": [
          "대응",
          "확인 가능한 정보",
          "EasyRep의 현재 결과"
        ],
        "rows": [
          [
            "온습도계·센서 점검",
            "지점의 현재값·센서차이",
            "측정값·시각·수신상태 표시"
          ],
          [
            "위치명 표·이력 앱",
            "같은 시각의 위치차이·밤사이 변화",
            "등록 위치의 공기온도·과거 시점 조회"
          ],
          [
            "IDW·공간 표현",
            "센서 사이 추정과 높이·배치 설명",
            "측정점과 추정영역 구분 · 표·2D·3D 비교평가 예정"
          ]
        ]
      },
      "sources": [
        "keeper-case-position-2025",
        "remoteHistory",
        "historyBoundary029",
        "esri-idw"
      ]
    },
    {
      "title": "은신처 조건과 개체의 이용",
      "paragraphs": [
        "Skelton 등의 Gehyra 게코9종 실험에서는 건조 은신처를32°C로 고정하고 습한 은신처의 온도를32·27·22°C로 바꿨다. 논문이 보고한 습한 은신처의 이용 비중은 각각46·2·3%였다. 습도가 높은 구역도 온도 조건이 달라지면 이용 양상이 달라졌다는 실험 근거다.",
        "관찰 단위는 전체 은신처 체류시간 중 습한 쪽의 비중이다. 개체 비율이나 사육 실패율로 읽지 않는다. 같은 개체의 세 처리, 처리별20시간, 종과 주야 조건을 포함한 분석이며 원자료를 새로 계산한 값이 아니다. 2019–2021년에 채집했고2024.12 온라인 공개·2025권호에 발표됐다.",
        "Aparicio Ramirez 등의 크레스티드 게코 실험실 온도 구배 연구에서는 활동기에 개체가 체온을 약24–28°C 범위로 선택했다. 이는 사육장 안의 미소환경을 구분해 기록할 이유를 보강한다. 다만 논문은 체온을 측정한 실험이며 EasyRep이 조회하는 위치별 공기온도와 같지 않다. 이 범위를 사육장 설정값으로 쓰거나 위치별 센서·공간 보간의 효과로 확대하지 않는다.",
        "위치별 센서와 이력 앱은 각 구역의 조건을 기록하고, 영상·직접 관찰은 그 구역의 이용을 보여준다. 두 기록을 함께 비교하면 환경을 제공한 것과 실제로 이용된 것을 구분할 수 있다. 현재 EasyRep은 등록 위치의 공기온도 조회와 별도 저장 영상 분석을 제공한다. 개체 이용과 환경의 자동 정합은 후속 과제이며,3D와 IDW는 공간 관찰 정보를 표현·추정하는 선택이다.",
        "Denommé 등의2025년 비어디드드래곤 사육장 비교에서는 자연형 구성이 온도 다양성을 늘렸지만 행동·복지 개선의 전체 결과는 불명확했다. 따라서 환경 구성과 개체 반응을 각각 평가할 필요가 있다. 특정 구성의 우열이나 EasyRep 효과로 일반화하지 않는다."
      ],
      "sources": [
        "gehyra-spatial-experiment-2025",
        "crested-thermal-gradient-2021",
        "spatial",
        "esri-idw",
        "pogona-enclosure-outcomes-2025"
      ],
      "table": {
        "caption": "같은 실험의 조건 비교 · 전체 은신처 체류시간 기준 · 논문 보고값 · 종·조건을 제한한 실험값",
        "headings": [
          "건조 은신처",
          "습한 은신처",
          "습한 쪽 이용시간 비중"
        ],
        "rows": [
          [
            "32°C 고정",
            "32°C",
            "46%"
          ],
          [
            "32°C 고정",
            "27°C",
            "2%"
          ],
          [
            "32°C 고정",
            "22°C",
            "3%"
          ]
        ]
      }
    },
    {
      "title": "타이머 분무 이후의 과습",
      "paragraphs": [
        "2025년6월3일 게코 사육 사례에서 작성자는 디지털 습도계를 보며 하루 두 번 손으로 분무했지만 목표습도가 몇 시간만 유지됐다고 설명했다. 이후4시간마다45초 분무하는 타이머를 사용하자 공기습도는 유지됐으나 바닥재가 젖고 물이 고였다. 배수층이 없었고 작성자는 설정을 줄였다.60%와45초/4시간은 작성자의 설정 기록이다.",
        "이 사례의 첫 대응은 분무량·간격 조정과 배수·바닥재 점검이다. 공기습도만 맞추는 제어와 물 고임을 관리하는 일은 구분해야 한다. EasyRep의 현재 이력에서 분무 전후 공기온습도의 회복·건조 구간을 사람이 찾아볼 수 있다. 관리와 환경의 자동 인과 연결은 제공하지 않는다.",
        "이 물 고임 사례 자체로 예측 제어의 필요성을 결론낼 수는 없다. 예측 연구는 별도로, 충분한 상하한·최소대기·최대작동·센서보호 규칙에 건조·회복 경과를 더했을 때 분무 시점의 결과가 달라지는지 비교한다. 같은 현재습도에서 건조 중인지 직전 분무 후 회복 중인지 구분하는 것이 시험할 상황이다. 기존10월 합성시험은 습도 이탈 감소와 온도 이탈·펌프 사용 증가를 함께 보였다. 실제 조건의 이득과 비용은 별도 검증할 단계다."
      ],
      "table": {
        "caption": "수치 없는 설계 상황 · 실제 장치 제어와 분리",
        "headings": [
          "경과",
          "충분한 기본 대응",
          "예측 연구의 비교 질문"
        ],
        "rows": [
          [
            "계속 건조하며 하한에 접근",
            "상하한·대기 규칙으로 작동",
            "반응 지연을 고려한 시작시점이 이탈시간을 줄이는가"
          ],
          [
            "직전 분무 뒤 습도 회복 중",
            "재작동 대기·최대작동 제한",
            "예상 회복을 기다려 중복 분무를 줄이는가"
          ],
          [
            "공기습도 유지·바닥재 물 고임",
            "분무량·배수·바닥재 현장점검",
            "현재 모델의 평가에 온도·작동비용을 포함 · 물고임은 현장관리"
          ]
        ]
      },
      "sources": [
        "keeper-case-misting-2025",
        "monsoon",
        "ecc",
        "technicalResearch",
        "prediction"
      ]
    },
    {
      "title": "사진 일지에서 예측 비교까지",
      "paragraphs": [
        "기존 사진 일지는 같은 개체의 변화 경과와 실제 탈피일을 확인하는 기본 수단이다. 관찰 시각·촬영 조건·사건 기록을 맞추면 단발 사진만으로 남는 시간적 공백을 줄일 수 있다.2025년 사진 문의 게시물은 이러한 질문의 예시로 참고하되, 원문 전체·사진·탈피 정답을 확인하지 못해 정량 근거에서 제외했다.",
        "사진 일지와 실제 탈피일은 과거 경과를 확인하는 기본 방법이다. 별도 예측 연구의 목적은 현재 주기의 관찰 정보를 더했을 때 직전 탈피 간격이나 과거 주기 중앙값보다 확인 시점을 유용하게 좁힐 수 있는지 평가하는 것이다. 유용성에는 예측 오차뿐 아니라 놓친 관찰과 추가 촬영·기록 부담이 포함된다.",
        "Pillai 등의 세 게코 종 연구는 매일 탈피를 확인하면서 실제 탈피 날짜·사육장 온도·습도를 남겼고, 탈피 간격이 개체와 종에 따라 달랐다고 보고했다. 따라서 반복 관찰과 실제 사건 기록은 사진 한 장보다 먼저 갖춰야 할 기준선이다. 그러나 크레스티드 게코 연구가 아니며, 이 결과만으로 직전 탈피 간격이나 외관 특징이 다음 탈피일을 예측한다고 말할 수 없다. EasyRep은 그 기준선과 별도 예측을 같은 이후 주기에서 비교하는 연구 경로로 한정한다.",
        "현재 연구 경로는 검수 사진·마스크에서 특징을 만들고 예측 시점까지의 이력만 ridge 실행기에 전달한다. 이후 관찰한 탈피 사건은 별도 평가 정답으로 둔다. 합성 입력에서 처리·발행·평가·보류를 확인했으며 실제 개체의 이후 주기와 다른 개체에 대한 비교를 준비한 상태다."
      ],
      "sources": [
        "keeper-case-appearance-2025",
        "gecko-ecdysis-repeat-2023",
        "appearancePipeline029",
        "technicalResearch"
      ],
      "table": {
        "caption": "현재: 별도 연구 실행기 · 실개체 반복 주기의 비교평가 준비",
        "headings": [
          "기존 대응",
          "연구에서 추가한 과정",
          "현재 확인과 다음 비교"
        ],
        "rows": [
          [
            "날짜 있는 사진·탈피 일지",
            "입력 검수·촬영 조건별 특징 이력",
            "합성 사진·마스크 처리 경로 확인"
          ],
          [
            "직전 탈피일·과거 주기",
            "동일한 예측 시점의ridge 점추정",
            "정상 입력 발행·부족 입력 보류 확인"
          ],
          [
            "직접 관찰한 탈피 사건",
            "예측과 관찰 정답 구간의 대조",
            "이후 주기·다른 개체의 오차·보류·기록 부담 비교"
          ]
        ]
      }
    },
    {
      "title": "네 가지 관리 문제와 R3 이후 결과",
      "paragraphs": [
        "필요성 두 장의 네 문제를 뒤의 구현·결과 장과 같은 순서로 연결했다. 환경 기록과 공간 조회는 현재 웹, 저장 영상·외관·예측은 별도 연구 경로를 포함한다. 환경과 개체 자료를 자동으로 합쳐 관리 효과를 판정하는 단계가 아니라, 기록을 보존하고 반복 비교를 수행할 기반을 구현한 단계다.",
        "R3 이후 가장 직접적인 웹 변경은 같은 시각의 환경 기록을 빠짐없이 조회하도록 전체 커서를 전달한 수정이다. 동일시각 합성2,002건 검증과11월6일 운영 조회를 분리해 확인했다. 기록 비교의 전제인 조회 신뢰성을 개선한 결과이며3D의 편의 효과를 측정한 결과로 사용하지 않는다.",
        "영상 검증기 후보는 배경 수락 감소와 함께 대상 손실이 발생해 채택하지 않았다. 외관 연구는 입력 검수에서 특징·ridge 예측·발행·평가·보류까지 합성 입력으로 확인했다. 이는 실제 개체의 관찰 시점 예측을 평가할 코드 경로의 결과다. 분무는10월의 합성 비교를 바탕으로 충분한 규칙과 작동 시점·비용을 비교하는 후속 과제다.",
        "효과 평가는 구현 상태와 분리한다. 공간은 같은 정보의 표·2D·3D, 영상은 직접 재생·배속, 외관은 사진 일지와 직전 간격·주기 중앙값, 분무는 같은 보호조건의 규칙 제어를 기준으로 삼는다. 정확도뿐 아니라 누락·보류·확인 시간·촬영 부담·온도 영향·작동 비용을 함께 읽어 추가 복잡성이 필요한지 판단한다."
      ],
      "table": {
        "caption": "기본 발표12장과의 연결 · 2026.11.05 R3 이후 결과와 기존 연구를 구분",
        "headings": [
          "필요성에서 제시한 문제",
          "구현·결과",
          "평가할 추가 가치",
          "발표"
        ],
        "rows": [
          [
            "환경 조건의 유지",
            "전체 커서 전달 수정 / 동일시각 합성2,002건·중복0 /11.06 운영 조회",
            "기록 누락 없이 과거 경과·설정 전후 확인",
            "3·5·6장"
          ],
          [
            "구역별 환경과 이용",
            "등록 위치·시점의 온도 조회 / 검증기 head 후보 미채택",
            "표·2D·3D 및 직접 영상 대비 정확한 비교·검토 부담",
            "4–7장"
          ],
          [
            "탈피·관리 이력",
            "검수·특징·ridge·발행·평가·보류의11.07 합성 검증",
            "실제 이후 주기에서 직전 간격 대비 오차·보류·기록 부담",
            "8–10장"
          ],
          [
            "자동 분무 후 경과",
            "10월 합성 비교: 습도 이탈 감소·온도 이탈/펌프 사용 증가",
            "동일 보호조건에서 건조·회복에 따른 분무·대기와 비용",
            "11장"
          ],
          [
            "전체 흐름",
            "관찰·비교 기반의 구현과 개발 결과",
            "실개체·실환경 비교평가의 남은 항목",
            "12장"
          ]
        ]
      },
      "sources": [
        "remoteHistory",
        "spatial",
        "historyBoundary029",
        "technicalResearch",
        "appearancePipeline029",
        "postR3Delta029",
        "prediction"
      ]
    },
    {
      "title": "기록·공간 표현의 평가 설계",
      "paragraphs": [
        "아래는 추가 효과를 확인하기 위한 평가 계획이다. 기존 조회 경계 시험은 기록 신뢰성의 검증으로 유지하고, 공간 추정 정확도와 화면 비교의 효용을 별개의 시험으로 구성한다. 참여자 수와 합격 기준은 예비 측정으로 변동성을 확인한 뒤 본시험 전에 고정한다. 실제 결과가 없는 단계에 성공률을 부여하지 않는다."
      ],
      "table": {
        "caption": "계획 · 같은 정보와 독립 검증값을 사용한 비교",
        "headings": [
          "평가 대상·기준선",
          "동일 조건과 절차",
          "측정 지표·채택 기준"
        ],
        "rows": [
          [
            "이력 조회 신뢰성\n원자료의 시각·ID 목록",
            "같은 시각·페이지 경계·재조회·취소를 포함해 원자료와 대조",
            "누락·중복·시각 불일치 건수\n정확한 일치가 기능 사용의 선행 조건"
          ],
          [
            "IDW 추정 정확도\n가까운 센서값·단순 평균",
            "센서를 같은 곳에서 교정 비교한 뒤 위치 고정\n추정에 쓰지 않은 검증 지점으로 시간·구역을 나눠 평가",
            "구역·시간별 MAE/최대오차·센서오프셋\n검증 위치에만 오차 주장, 센서3점의 충분성 단정 금지"
          ],
          [
            "표·2D·3D 편의\n위치명 표와 기존 이력 앱",
            "동일값·위치·시각·상태 표시\n순서를 바꿔 같은 비교 과제 수행",
            "위치/시각 오독·완료시간·추정영역 이해\n오류 증가 없이 확인 부담 감소 시 표현 채택"
          ],
          [
            "기록 묶음의 효용\n기존 이력 앱+사진/관리일지",
            "같은 자료에서 야간 구간·관리 전후·관찰 경과 찾기",
            "잘못 연결한 기록·찾는 시간·입력 시간\n추가 입력 부담을 포함한 비교"
          ]
        ]
      },
      "sources": [
        "technicalResearch",
        "historyBoundary029",
        "remoteHistory",
        "esri-idw"
      ]
    },
    {
      "title": "분무·탈피 예측의 평가 설계",
      "paragraphs": [
        "예측은 충분한 규칙과 기록 기반 기준선을 통과할 때만 추가 가치가 있다. 학습·튜닝·평가 자료를 시간과 개체로 분리하고, 동일한 평가 구간을 모든 방법에 적용한다. 아래 항목은 수행할 비교 계획이며 현재 확보된 합성 실행 결과와 구분한다."
      ],
      "table": {
        "caption": "계획 · 단순 방식과 같은 조건의 비교",
        "headings": [
          "대상·충분한 기준선",
          "검증 절차",
          "지표와 판단 기준"
        ],
        "rows": [
          [
            "분무 시점\n타이머 / 상하한+대기+보호 규칙",
            "센서·목표범위·최대작동·보호조건 동일\n시간을 분리한 건조·회복 구간과 센서오류에서 비교\n합성 검증 뒤 물·장치 시험은 별도 승인 범위",
            "습도 이탈시간·온도 이탈시간·펌프초/횟수·사용수량\n보호조건 유지, 목표 개선과 비용을 함께 판단"
          ],
          [
            "탈피 시점\n직전 간격 / 과거 주기 중앙값",
            "같은 개체의 이후 주기, 별도 개체 평가를 구분\n예측시점 뒤 사진·정답 유입 차단\n실제 관찰사건의 정답구간 보존",
            "시점오차 분포·구간까지 거리·구간포함·발행/보류 비율\n기준선보다 유용한 시점과 관찰부담인지 비교"
          ],
          [
            "실제 관찰 부담\n사진일지·정기 관찰",
            "같은 관찰기록과 시간대에서 확인 과제 비교\n필요 이상의 촬영·확인을 비용으로 기록",
            "추가 기록분/주·놓친 관찰·불필요한 확인\n예측정확도 개선만으로 사용가치 판정 금지"
          ]
        ]
      },
      "sources": [
        "technicalResearch",
        "appearancePipeline029",
        "reptile-welfare-review-2025"
      ]
    },
    {
      "title": "개인 사육자의 주요 사용 목적",
      "paragraphs": [
        "센서 설치 전에는 급여와 청소 기록부터 남긴다. 설치 후에는 마지막 측정 시각을 확인하고, 필요할 때 위치별 온도와 이전 기록을 찾아본다. 다음 흐름은 실제 사용자 관찰 통계가 아닌 설계 시나리오다."
      ],
      "sources": [
        "web",
        "search"
      ],
      "flow": [
        {
          "title": "준비 · D1",
          "text": "센서 없이 사육장을 등록하고 관리 기록을 시작한다."
        },
        {
          "title": "환경·과거 기록 확인 · D2·D3",
          "text": "측정 시각·수신 상태를 확인하고, 센서 점과 보간 영역을 구분해 살핀다."
        },
        {
          "title": "급여·관리 내역 확인 · D4",
          "text": "직접 한 급여·청소를 기록한다. 오기는 취소 사유를 남기고 다시 작성한다."
        },
        {
          "title": "기록 시각 대조 · D6",
          "text": "같은 사육장의 환경·관리·장치 기록을 오가며 시각을 대조한다."
        }
      ]
    },
    {
      "title": "관찰·예측 기술의 적용 목적",
      "paragraphs": [
        "사육장 배치를 바꾼 뒤에는 개체가 이용하는 구역과 측정 지점의 대응을 다시 살핀다. 외출·야간 영상에서는 개체를 관찰할 수 있었던 시간과 구역을 찾고, 관리 동작 뒤에는 환경의 변화를 확인한다.",
        "현재 웹은 이력 조회와 공간 표현을 제공하고, 저장 영상 분석과 외관·탈피 관찰 도구는 별도 연구 코드에 있다. 환경·행동의 자동 대조와 실물 분무 효과는 후속 검증 대상이다. 외관 연구에는 별도 ridge 예측·발행·평가 경로가 구현됐으며 실개체 효용은 평가 준비 단계다."
      ],
      "sources": [
        "rspca-crested",
        "esri-idw",
        "reptilearn-2024",
        "technicalAudit",
        "technicalResearch"
      ],
      "table": {
        "caption": "관찰 목적과 기술 선택 · 구현 기능과 후속 연구를 구분",
        "headings": [
          "확인 목적",
          "기술의 역할과 현재 범위",
          "단순 대안과 추가 가치의 판정"
        ],
        "rows": [
          [
            "생활 구역별 온도 조건",
            "웹에서 센서 실측값과 IDW 추정을 구분해 표시. 색 분포·3D는 위치 관계를 설명하는 선택적 표현.",
            "위치명 표·단면도로 충분한지 비교. 보간 정확도는 입력에 쓰지 않은 지점의 실측으로 별도 평가."
          ],
          [
            "외출·야간의 개체 관찰",
            "저장 영상의 탐지·추적으로 관찰 구간, 이동·구역 체류와 변화 후보를 계산. 가림은 미관찰로 남김.",
            "직접 재생·움직임 검출과 비교. 주야·가림 조건별 누락·오경보와 원본 검토 부담을 확인."
          ],
          [
            "탈피 상태를 확인할 시점",
            "외관·탈피 관찰 수집과 별도 ridge 예측·발행·평가 경로 구현. 합성 입력 검증 완료, 실개체 기준선 비교 준비.",
            "직전 탈피 날짜·정기 관찰이 기준. 선행 정보뿐 아니라 추가 촬영·기록 부담까지 비교."
          ],
          [
            "분무 뒤 추가 작동 또는 대기",
            "과거 합성 환경 예측과 가상 명령 시험. 현재 웹 모델 미연동, 실물 효과 미검증.",
            "타이머·임계값·대기 규칙과 같은 조건으로 비교. 습도 이득과 온도·펌프 비용을 함께 평가."
          ]
        ]
      }
    },
    {
      "title": "확인 목적별 기존 대안과 현재 구성",
      "paragraphs": [
        "환경 기록은 센서가 측정한 값과 시각을, 관리 기록은 사람이 입력한 행동과 발생 시각을 제공한다. 원격 이력 앱·위치명 표·메모도 각각의 목적을 충족할 수 있다.",
        "EasyRep은 이 정보를 사육장별 화면에서 제공한다. 현재는 사용자가 화면을 오가며 대조하며, 추세에서 고른 시각을 공간 보기로 자동 전달하지 않는다. 같은 웹에 모았을 때 기록을 찾는 부담이 줄어드는지는 실제 비교가 필요하다."
      ],
      "sources": [
        "web",
        "spatial",
        "remoteHistory",
        "careAlternatives",
        "spatialMeaning",
        "necessityPlan"
      ],
      "table": {
        "caption": "같은 확인 목적의 대안과 현재 구성 · 기능 우열이나 사용 효과의 비교 결과가 아님",
        "headings": [
          "확인 목적",
          "기존 도구로 가능한 일",
          "EasyRep 현재 구성"
        ],
        "rows": [
          [
            "센서 없이 관리 기록 시작",
            "메모나 사육 기록 앱에 종류·발생 시각·내용 기록",
            "센서 연결 전에도 사육장별 관리 내역 저장"
          ],
          [
            "부재 중 환경 확인",
            "이력을 지원하는 원격 센서 앱에서 측정 시각·기간 기록 조회",
            "사육장별 측정 시각·수신 상태·기간 이력 조회"
          ],
          [
            "측정값과 위치 대응",
            "위치명 표·배치도로 센서와 지점 대응",
            "등록 위치와 센서값 표시 · 3D는 선택 표현, 미확인 위치는 가정 배치"
          ],
          [
            "관리 기록 정정",
            "메모에 정정 이유와 수정 내용을 덧붙임",
            "원본과 취소 사유를 보존한 뒤 재작성"
          ]
        ]
      }
    },
    {
      "title": "조회 상태와 기록 이력의 요구사항",
      "paragraphs": [
        "화면을 새로 열어도 마지막 측정값의 시각은 바뀌지 않는다. 값의 크기와 함께 언제 측정됐는지, 조회에 성공했는지, 기록이 없는지를 확인할 수 있어야 한다. 갱신 지연이나 오류가 보이면 D5에서 마지막 측정 시각과 조회 상태를 확인하고 다시 조회한다. 출처가 궁금하면 센서 데이터와 가상 데이터를 구분해 찾아본다."
      ],
      "sources": [
        "web",
        "search"
      ],
      "table": {
        "caption": "사용 요구와 구현 화면의 연결",
        "headings": [
          "요구",
          "화면·동작",
          "확인할 정보"
        ],
        "rows": [
          [
            "장비 없이 기록 시작",
            "사육장 등록 / 사육 관리",
            "등록 대상과 직접 작성한 내용"
          ],
          [
            "선택 범위 유지",
            "환경 이력 / 공간 시점 선택",
            "사육장·기간·센서·시각"
          ],
          [
            "정정 이력 유지",
            "기록 취소 / 새 기록 작성",
            "원본·취소 사유·재작성 내용"
          ],
          [
            "누락과 오류 구분",
            "수신 상태 / 오류 / 출처 검색",
            "마지막 측정·빈 결과·조회 실패"
          ]
        ]
      }
    }
  ],
  "gaps": [
    {
      "id": "user-research",
      "title": "사용자 불편과 개선 효과는 미측정",
      "missing": "외부 설문·개별 사육 사례는 확보했습니다. EasyRep 사용자 인터뷰·관찰에 따른 문제 빈도와 기존 방식 대비 개선 효과는 미측정입니다.",
      "check": "동일한 기록·시각·센서 위치 정보를 제공하고 위치명 표·2D·3D 및 메모·현재 웹에서 필요한 기록을 찾게 한다. 대상·시각·위치의 오독, 기록 유무 구분과 탐색 완료를 비교한다. 참가자 수·효과 수치·일정은 아직 정하지 않았다."
    }
  ],
  "slides": [
    "service",
    "rationale-spatial",
    "rationale-interpolation",
    "rationale-detection",
    "rationale-association",
    "rationale-shedding",
    "rationale-misting",
    "progress-spatial-method",
    "progress-history-result",
    "progress-history-production",
    "progress-appearance-input",
    "progress-appearance-prediction",
    "progress-appearance-result",
    "progress-humidity-method",
    "progress-need-observation",
    "progress-need-prediction"
  ],
  "scenarios": [
    "D1",
    "D2",
    "D5"
  ],
  "detail": "problem"
},

  {
    "id": "comparison",
    "title": "유사 서비스 및 관련 기술 조사",
    "summary": "기존 제품도 분무·환경제어·원격 이력을 제공하며, EasyRep은 관리·공간 맥락을 연결합니다.",
    "sections": [
      {
        "title": "기능 구성 비교",
        "paragraphs": [
          "기존 제품도 정기 분무, 환경·시간 제어, 원격 온습도와 이력 확인을 제공한다. 2019년 국내 학술대회 논문도 환경제어와 적외선 기반 상태 추정을 제안했다. EasyRep은 사육장별 환경 기록에 사람이 작성한 관리 이력과 센서 위치를 연결하는 흐름을 중심으로 구성했다. 아래 비교는 확인한 공식 설명·공개 초록·현재 웹 구현에 한정한다."
        ],
        "sources": [
          "monsoon",
          "ecc",
          "slither",
          "reptile-smart-environment-2019",
          "web"
        ],
        "table": {
          "caption": "공식 제품 기능과 이번 프로젝트의 관계 · 성능 비교 아님",
          "headings": [
            "대상",
            "주요 제공 기능",
            "확인·조작 대상",
            "이번 프로젝트와의 관계"
          ],
          "rows": [
            [
              "Monsoon Multi II",
              "설정 주기·지속시간에 따른 분무",
              "분무 장치의 작동 설정",
              "후보 분무 계획의 비교는 별도 연구 주제"
            ],
            [
              "Environmental Control Center",
              "환경·시간 제어와 온도 경보",
              "연결한 환경 장치",
              "EasyRep 웹은 조회·기록 중심이며 원격 분무 미연동"
            ],
            [
              "SlitherSense",
              "원격 온습도·이력·범위 알림·복수 센서",
              "여러 구역·사육장의 환경",
              "원격 조회·다중 센서 자체는 공통 기능"
            ],
            [
              "스마트 환경제어시스템 (2019)",
              "미스팅·팬·조광기 제어, 급이·급수 자동화, 적외선 기반 상태 가능성 추정",
              "사육장 환경과 센서 데이터",
              "공개 초록에서 확인한 제안 범위 · 구현·성능은 판단하지 않음"
            ],
            [
              "EasyRep",
              "환경·수동 관리 기록·공간 추정 조회",
              "사육장별 시각·출처·정정 이력",
              "영상 관찰·분무 계획은 별도 연구 단계"
            ]
          ]
        }
      },
      {
        "title": "기술별 입력과 출력",
        "paragraphs": [
          "공간 보간은 센서 위치와 값을 이용해 지점 사이를 표시한다. 미래 예측은 최근 기록과 분무 계획으로 이후 환경값을 계산한다. 탐지·추적은 영상에서 개체 후보를 찾고 시간 순서로 연결하며, 두 영상의 좌표 계산은 천장·전면 입력으로 위치를 추정하는 별도 단계다."
        ],
        "sources": [
          "web",
          "prediction",
          "detection",
          "r3"
        ],
        "table": {
          "caption": "입력·처리·결과의 구분",
          "headings": [
            "기술",
            "입력",
            "처리와 출력",
            "현재 범위"
          ],
          "rows": [
            [
              "공간 온도 보간",
              "센서 위치·선택 시점의 온도",
              "지점 사이 값을 계산해 표시",
              "현재 웹 조회 / 공간 전체 오차 미검증"
            ],
            [
              "환경 예측",
              "최근 환경·펌프 이력·후보 계획",
              "향후 온습도 계산",
              "합성 데이터 학습·평가"
            ],
            [
              "탐지·추적",
              "영상 프레임",
              "후보 검증 후 임시 ID 연결",
              "공개 영상 개발 집계"
            ],
            [
              "두 영상 좌표",
              "천장·전면 시험 영상",
              "좌표 생성 또는 미결정",
              "합성 입력 처리 시험"
            ]
          ]
        }
      },
      {
        "title": "관리·관찰 맥락의 연결",
        "paragraphs": [
          "웹에서는 환경값의 측정 시각과 위치, 사람이 기록한 관리 종류와 실행 시각, 정정 이유를 같은 사육장에서 찾아볼 수 있게 했다. 위치가 정해지지 않은 센서는 가정 배치임을 표시하고, 보간된 영역은 실측점과 구분한다.",
          "연구에서는 위치를 정하지 못한 영상 구간을 미결정으로 남기고, 분무 계획의 습도 이탈과 펌프 작동 시간을 함께 비교한다. 이 방향을 현재 웹의 자동 관찰·분무 기능이나 다른 제품보다 높은 성능으로 표현하지 않는다."
        ],
        "sources": [
          "web",
          "spatial",
          "prediction",
          "r3"
        ]
      }
    ],
    "gaps": [
      {
        "id": "comparison-effect",
        "title": "기능 비교가 성능 우위를 뜻하지 않음",
        "missing": "동일 조건의 사용성·성능 비교를 수행하지 않았습니다.",
        "check": "같은 사용자 과제에서 성공 여부와 소요시간을 비교합니다. 공식 자료가 설명하지 않은 기능은 ‘해당 자료에서 확인하지 않음’으로 남깁니다."
      }
    ],
    "slides": [
      "comparison"
    ],
    "scenarios": [
      "D2",
      "D3",
      "D5"
    ],
    "detail": "comparison"
  },
  {
    "id": "system",
    "title": "제안 시스템 및 구현 내용",
    "summary": "웹은 환경·관리·공간 이력을 제공하며, 외관 관찰·탈피 예측·평가와 영상·분무는 별도 연구 경로로 구현했습니다.",
    "sections": [
      {
        "title": "현재 웹의 정보 흐름",
        "paragraphs": [
          "로그인한 계정이 접근할 수 있는 사육장을 선택하면 환경 현재값·기간 이력·관리 기록을 그 사육장 범위에서 조회한다. 센서·장치 기록과 사람이 작성한 기록은 각각의 유형으로 저장되고 화면에서도 출처를 구별한다."
        ],
        "sources": [
          "web"
        ],
        "flow": [
          {
            "title": "센서·장치 기록",
            "text": "저장된 측정값·보고 상태를 선택 사육장 범위로 조회해 환경·공간·장치 기록에 표시한다."
          },
          {
            "title": "사용자 관리 입력",
            "text": "종류·시각·내용을 검증하고 중복 제출을 막은 뒤 저장해 같은 사육장의 관리 탭으로 돌아간다."
          },
          {
            "title": "기록 정정",
            "text": "원본에 취소 시각·사유를 남기고 새 기록을 작성한다. 조회 시 유효·취소 기록을 구분한다."
          }
        ]
      },
      {
        "title": "개인 사육장 배치",
        "paragraphs": [
          "11월 5일 R3의 20 × 20 × 30 cm 배치 모델은 천장 온습도 센서와 마주 보는 두 모서리의 온도 센서를 둔다. BB6는 측정값을 전송하고 Pi는 기록·영상·화면을 처리하는 구성이다. 물통·펌프는 아래쪽, 제어부는 뒤쪽에 정리했다.",
          "이 구성은 가상 배치 모델이다. 10월의 기존 실물 조립 사진과 구분하며, 카메라·펌프까지 한 사육장에서 함께 동작한 실물 시험을 뜻하지 않는다."
        ],
        "sources": [
          "r3",
          "assembly"
        ],
        "table": {
          "caption": "R3 가상 배치의 위치별 역할",
          "headings": [
            "위치",
            "구성",
            "역할"
          ],
          "rows": [
            [
              "천장",
              "온습도 센서·카메라·노즐",
              "환경 측정 / 바닥 이동 관찰 / 물 공급"
            ],
            [
              "마주 보는 두 모서리",
              "온도 센서 2개",
              "세 지점의 공기 온도 기록"
            ],
            [
              "전면",
              "카메라",
              "벽 이동 관찰 보완"
            ],
            [
              "후면·하부",
              "제어부·물통·펌프",
              "배선과 물 공급 장치 정리"
            ]
          ]
        }
      },
      {
        "title": "예측·영상·분무의 처리 단계",
        "paragraphs": [
          "예측 시험은 최근 30분의 온습도 4값과 펌프 이력, 향후 60분의 후보 분무 계획을 입력한다. MLP가 후보별 환경 변화를 계산하면 별도 선택 로직이 목표 범위 이탈과 펌프 작동 시간을 비교한다. RGB·3D·행동 정보는 이 모델의 입력에 포함되지 않았다.",
          "영상은 사전학습 모델의 후보 생성, 검증기·결합 점수에 의한 후보 검토, 시간 순서의 임시 ID 연결로 처리한다. 두 방향 영상의 좌표 계산과 분무의 허용·대기·차단은 각각 별도 시험으로 다뤘다."
        ],
        "sources": [
          "prediction",
          "detection",
          "r3"
        ],
        "flow": [
          {
            "title": "최근 기록과 계획",
            "text": "과거 30분의 환경·펌프 이력에 다음 60분의 후보 계획을 붙인다."
          },
          {
            "title": "후보별 미래 계산",
            "text": "MLP가 각 계획의 이후 온습도를 출력한다."
          },
          {
            "title": "계획 선택",
            "text": "목표 범위 이탈과 펌프 작동 시간을 비교해 첫 동작을 정한다."
          },
          {
            "title": "재측정·재평가",
            "text": "첫 동작 후 새 기록으로 다음 계획을 다시 계산한다."
          }
        ]
      },
      {
        "title": "서로 다른 세 가지 3D",
        "paragraphs": [
          "사진 기반 복원, 센서 사이 온도 추정, 두 영상의 좌표 계산은 입력과 결과가 다르다. 현재 공간 화면은 형상·센서 위치와 선택 시점의 값으로 보간하며 사진을 촬영해 형태를 복원하는 기능과 구분한다."
        ],
        "sources": [
          "prediction",
          "r3",
          "spatial"
        ],
        "table": {
          "caption": "자료에서 쓰는 3D의 범위",
          "headings": [
            "작업",
            "입력과 결과",
            "확인 범위"
          ],
          "rows": [
            [
              "사진 기반 복원 · 10/06 19장",
              "사진으로 형태 파일 생성",
              "공기 온도나 행동의 측정 결과가 아님"
            ],
            [
              "센서 사이 온도 추정 · R3 6장",
              "3지점 온도 기록을 공간에 표시",
              "실측점 사이의 추정. 전체 공간 오차 미검증"
            ],
            [
              "두 영상 좌표 계산 · R3 7장",
              "합성 천장·전면 영상에서 좌표 생성",
              "실물 카메라 정확도와 구분"
            ]
          ]
        }
      },
      {
        "title": "외관 관찰·탈피 예측의 연구 구조",
        "paragraphs": [
          "보고서 2장의 사진 문의 사례는 과거 사진과 현재 외관을 비교한 뒤에도 실제 탈피 경과와 다음 시점에 관한 정보가 남는 상황을 보여준다. 사진 일지와 직전 탈피 간격을 기준으로 삼고, 같은 개체의 촬영 조건과 시간에 따른 색·질감 변화를 추가 입력으로 구성했다.",
          "2026년 11월 7일 연구 경로는 사람이 검수한 사진·마스크와 관찰 기록을 받아 특징 이력, 기준 시점의 ridge 예측, 단발 발행과 사건 평가로 연결된다. 현재 웹 일지와 구분된 연구 실행기이며, 합성 입력의 정상 처리와 자료 부족·시점 충돌에 따른 보류를 확인했다. 실제 개체의 반복 주기 자료에서는 직전 탈피 간격과 같은 기준선에 비해 예측이 유용한지 비교할 예정이다."
        ],
        "sources": [
          "keeper-case-appearance-2025",
          "appearancePipeline029",
          "postR3Delta029"
        ],
        "flow": [
          {
            "title": "관찰 입력 검수",
            "text": "개체·촬영 시각·조건 확인 → 검수 사진·마스크와 관찰 기록"
          },
          {
            "title": "특징 이력 구성",
            "text": "색·질감의 변화량·변화율, 마지막 관찰 이후 경과 → 같은 조건의 시계열"
          },
          {
            "title": "기준 시점 예측",
            "text": "그 시점까지의 기록 → ridge 점 추정 또는 자료 부족·시점 충돌에 따른 보류"
          },
          {
            "title": "발행·사건 평가",
            "text": "예측 결과·보류 사유 저장 → 이후 사람이 확인한 탈피 사건과 비교"
          }
        ],
        "table": {
          "caption": "2026.11.07 연구 코드 · 합성 입력의 실행 검증 · 실제 개체 효용은 반복 주기 평가 대상",
          "headings": [
            "남은 문제",
            "구현한 처리",
            "결과·연결"
          ],
          "rows": [
            [
              "사진마다 촬영 조건과 시점이 다름",
              "개체·조건 검수 후 색·질감·시간 특징 누적",
              "예측 입력 자료 생성 · 발표 8장"
            ],
            [
              "직전 탈피 간격만으로 현재 주기 변화 반영이 어려움",
              "같은 평가 자료에서 주기 기준선과 ridge 예측 비교 경로",
              "학습·예측·평가 실행기 구현 · 발표 9장"
            ],
            [
              "자료가 부족하거나 관찰 시점이 충돌",
              "기준 시점 입력 확인과 보류 사유 저장",
              "합성 정상 처리·보류 확인 · 발표 10장 / 보고서 6.6·8.4"
            ]
          ]
        }
      }
    ],
    "gaps": [
      {
        "id": "temperature-measurement-definition",
        "title": "표면 온도와 공기 온도의 측정 대상 확인",
        "missing": "두 자료의 센서 설명을 동일 설치 실험으로 연결할 근거가 없습니다.",
        "check": "최신 설치 사진·센서 위치·측정 대상과 기준 센서 기록을 대조한 뒤 공간 오차를 따로 평가합니다. 10월 SEN0331과 11월 SHT31 표기의 관계도 실제 부품과 대조합니다."
      },
      {
        "id": "three-distinct-3d-claims",
        "title": "세 종류 3D의 산출물 구분",
        "missing": "사진 복원·온도 보간·영상 좌표의 통합 성능은 검증하지 않았습니다.",
        "check": "각 작업의 입력·출력·검증 자료를 분리하고 가상 배치를 실물 설치 완료로 표시하지 않습니다."
      }
    ],
    "slides": [
      "system",
      "current",
      "temperature",
      "camera",
      "misting",
      "progress-need-observation",
      "progress-need-prediction",
      "progress-appearance-input",
      "progress-appearance-prediction",
      "progress-appearance-result",
      "progress-conclusion"
    ],
    "scenarios": [
      "D3"
    ],
    "detail": "evidence"
  },
  {
    "id": "screens",
    "title": "사용자 화면 및 데이터/API 흐름",
    "summary": "사육장을 등록하고 환경 이력을 조회하며, 관리 기록을 작성·취소·재작성할 수 있습니다.",
    "sections": [
      {
        "title": "입력·저장·정정의 사용자 흐름",
        "paragraphs": [
          "사육장을 선택한 뒤 관리 종류·실행 시각·내용을 입력한다. 체중 기록에는 체중값을 사용하며, 다른 관리 기록에는 내용을 남긴다. 저장하면 같은 사육장의 관리 탭에서 결과를 확인한다. 작성과 취소는 허용된 역할과 사육장 범위에서 수행한다."
        ],
        "sources": [
          "web"
        ],
        "flow": [
          {
            "title": "작성",
            "text": "관리 종류·시각·내용을 입력하고 저장한다."
          },
          {
            "title": "조회",
            "text": "사육 관리 탭에서 저장된 기록과 작성 정보를 확인한다."
          },
          {
            "title": "정정",
            "text": "잘못된 기록에 취소 사유를 남긴 뒤 올바른 내용을 새로 작성한다."
          }
        ]
      },
      {
        "title": "사용자 시나리오",
        "paragraphs": [
          "D2·D3·D4는 외출 중 환경 확인, 이전 공간 기록 조회, 마지막 급여·관리 내역 확인을 위한 주요 시나리오다. D1은 센서 없이 기록을 시작하는 흐름, D5는 조회 지연·실패 대응, D6는 관리 시각과 환경 기록을 대조하는 관련 흐름이다. 순서대로 수행해야 하는 하루 일과가 아니다."
        ],
        "sources": [
          "web",
          "search",
          "spatial"
        ],
        "table": {
          "caption": "상황별 행동과 화면 반응 · 사용성 실험 결과 아님",
          "headings": [
            "상황",
            "사용자 행동",
            "화면에서 확인할 내용"
          ],
          "rows": [
            [
              "D1 · 센서 설치 전",
              "사육장 등록 후 급여·청소 기록",
              "직접 작성한 관리 기록 / 센서 미등록"
            ],
            [
              "D2 · 외출 중 환경 확인",
              "마지막 측정 시각 확인 후 환경·공간 조회",
              "현재·기간 추세 / 센서 지점과 사이 추정"
            ],
            [
              "D3 · 이전 공간 기록 조회",
              "과거 시점·기간 선택 후 이전 기록 보기",
              "선택한 측정 시각 / 센서 값·가정 배치 표시"
            ],
            [
              "D4 · 급여·관리 내역 확인",
              "종류·발생 시각·내용 조회 후 직접 한 일 기록",
              "기존 내역 / 작성 후 같은 사육 관리 이력"
            ],
            [
              "D5 · 갱신 지연",
              "오래된 값·빈 결과·조회 오류를 구분하고 재조회",
              "기록 출처와 조회 오류·오래된 값"
            ],
            [
              "D6 · 관리 시각과 환경 대조",
              "관리 기록의 발생 시각과 환경 기록을 오가며 대조",
              "같은 사육장·같은 시간대 / 인과 판정 없음"
            ]
          ]
        }
      },
      {
        "title": "조회와 저장의 데이터 흐름",
        "paragraphs": [
          "환경 이력은 기간과 이전 시점 커서, 관리 기록은 종류·기간·상태, 장치·센서 기록은 검색어와 유형으로 범위를 좁힌다. 작성 요청은 입력과 중복 여부를 확인한 뒤 저장하고, 취소 요청은 원본을 지우지 않고 취소 사유를 남긴다."
        ],
        "sources": [
          "web",
          "search",
          "spatial"
        ],
        "table": {
          "caption": "선택 사육장 안에서 수행하는 조회·저장",
          "headings": [
            "요청",
            "입력·범위",
            "결과"
          ],
          "rows": [
            [
              "환경 이력 조회 · GET history",
              "선택 기간·이전 시점 커서",
              "측정 기록과 다음 탐색 범위"
            ],
            [
              "관리 기록 조회 · GET care",
              "종류·기간·상태·이전 기록",
              "관리 내용과 작성·취소 정보"
            ],
            [
              "기록 검색 · GET records",
              "검색어·유형·이전 기록",
              "센서·장치 기록의 출처와 내용"
            ],
            [
              "관리 작성 · POST 폼",
              "종류·시각·내용·제출 식별값",
              "유효성·중복 확인 후 저장, 관리 탭 복귀"
            ],
            [
              "관리 취소 · POST 폼",
              "대상 기록·취소 사유",
              "원본·취소 정보 보존, 관리 탭 복귀"
            ]
          ]
        }
      },
      {
        "title": "조회 전환·오류·내보내기 범위",
        "paragraphs": [
          "사육장이나 기간이 바뀌면 진행 중인 이전 요청을 중단하고, 늦게 도착한 응답을 새 화면에 반영하지 않는다. 같은 조회의 일시적 오류 때 이전 값을 유지하는 경우에는 갱신 시각과 오류를 함께 표시한다. 권한·대상이 바뀌거나 점검 중인 응답은 이전 데이터를 계속 보여주는 경우와 구분한다.",
          "CSV에는 화면에 불러온 범위가 담긴다. 현재 구간을 확인하는 용도와 전체 보관 이력이 필요한 경우를 구별해야 한다. 조회 결과가 비었다는 상태와 조회 자체에 실패한 상태도 따로 표시한다."
        ],
        "sources": [
          "web",
          "spatial"
        ]
      }
    ],
    "gaps": [
      {
        "id": "scenario-validation",
        "title": "시나리오 설명과 사용성 시험 구분",
        "missing": "실제 참가자가 D1~D6를 수행한 시간·실패·정정 결과가 없습니다.",
        "check": "사용자 과제평가에서 오래된 값·빈 결과·조회 실패와 취소 후 재작성의 이해 여부를 관찰합니다. 건강 진단·자동 인계 발송·원격 명령은 현재 기능으로 쓰지 않습니다."
      }
    ],
    "slides": [
      "service",
      "current"
    ],
    "scenarios": [
      "D1",
      "D2",
      "D3",
      "D4",
      "D5",
      "D6"
    ],
    "detail": "scenarios"
  },
  {
    "id": "results",
    "title": "실험 및 분석 결과",
    "summary": "기존 연구 시험과 R3 이후 조회 수정·운영 확인·외관 연구·최신 영상 탐지 비교를 입력별로 정리합니다.",
    "sections": [
      {
        "title": "예측 분무 비교",
        "paragraphs": [
          "후보 계획을 비교하는 방식과 현재 습도에 반응하는 임계값 제어를 합성 환경에서 비교했다. 목표 습도가 다른 A·B·C 조건을 각각 360분씩 6회 실행한 평균이다. 예측 제어에서 습도 이탈 시간은 줄었지만 펌프 ON 시간과 온도 이탈 시간은 늘었다.",
          "습도를 목표 안에 유지하는 것과 펌프 작동을 줄이는 것을 함께 평가해야 한다. 실제 물·전력 사용량은 측정하지 않았으며 생물 안전이나 사육 효과를 평가한 시험도 아니다."
        ],
        "sources": [
          "prediction"
        ],
        "table": {
          "caption": "합성 시험 · 360분 × 6회 평균 · 임계값 → 예측 제어 · 공통 온도 목표 23–29°C, 종별 권장값 아님",
          "headings": [
            "목표 습도",
            "습도 이탈 (분)",
            "펌프 ON (초)",
            "온도 이탈 (분)"
          ],
          "rows": [
            [
              "A · 45–55%RH",
              "14 → 3.3",
              "52 → 81.3",
              "13.5 → 17"
            ],
            [
              "B · 60–70%RH",
              "62.5 → 13.2",
              "163 → 202.5",
              "21.8 → 25"
            ],
            [
              "C · 75–85%RH",
              "156.8 → 82",
              "274 → 331.5",
              "35.7 → 40.5"
            ]
          ]
        }
      },
      {
        "title": "예측 시점별 오차",
        "paragraphs": [
          "학습에 사용하지 않은 합성 데이터 2,352구간에서 미래 분무 계획을 입력하고 예측값과 정답 차이의 절댓값을 평균했다. 먼 시점의 오차가 커지는 결과는 새 측정값으로 계획을 갱신할 필요성을 뒷받침한다. 아래 MAE는 실제 센서 정확도나 현재 공간 보간의 오차가 아니다."
        ],
        "sources": [
          "prediction"
        ],
        "table": {
          "caption": "합성 2,352구간 · MAE: 평균 절대 오차",
          "headings": [
            "미래 시점",
            "온도 MAE (°C)",
            "습도 MAE (%p)"
          ],
          "rows": [
            [
              "5분",
              "0.043",
              "0.296"
            ],
            [
              "10분",
              "0.050",
              "0.354"
            ],
            [
              "30분",
              "0.073",
              "0.583"
            ],
            [
              "60분",
              "0.105",
              "1.024"
            ]
          ]
        }
      },
      {
        "title": "영상 탐지·추적",
        "paragraphs": [
          "10월 22일 자료는 공개 영상 5개, AI 검수 266프레임에서 정검출 TP 160건·오탐 FP 5건·놓침 FN 3건을 보고했다. 같은 동물도 프레임마다 별도 객체 출현으로 세므로 세 수치의 합이 프레임 수와 같지는 않다. 개발 표본의 집계이며 독립 최종평가나 실제 카메라 성능을 뜻하지 않는다.",
          "정상 탐지 사례와 함께 부분 몸체를 별도 개체로 잡은 중복 오탐을 확인했다. 추적에서는 일부 겹친 두 개체의 정상 연결까지 모호한 경우로 처리하던 규칙을 수정해, 서로 구분되는 이전 추적 연결을 보존했다.",
          "같은 두 마리 구간 44프레임에서 연결 가능한 86쌍을 비교한 결과 연속 연결은 0쌍에서 66쌍으로 늘었고 20쌍은 미연결로 남았다. 이 값은 장기 개체 식별 정확도나 새 영상 전체의 성능이 아니다."
        ],
        "sources": [
          "detection",
          "geckoVideo",
          "geckoLicense"
        ],
        "figures": [
          {
            "src": detectionResult,
            "width": 1024,
            "height": 576,
            "alt": "공개 영상에서 도마뱀을 검출한 당시 모델 출력",
            "caption": "정상 탐지 사례 · 결과 확인 후 선택한 구간. Pristurus 영상에 모델 결과를 표시한 편집물 · CC BY-SA 3.0"
          },
          {
            "src": detectionError,
            "width": 1024,
            "height": 576,
            "alt": "두 마리 영상에서 부분 몸체를 별도 박스로 검출한 당시 오탐 결과",
            "caption": "중복 오탐 사례 · 빨간 박스는 검수 판정. Pristurus 영상에 결과를 표시한 편집물 · CC BY-SA 3.0"
          }
        ]
      },
      {
        "title": "공간·두 영상·가상 분무",
        "paragraphs": [
          "11월 5일 R3는 센서 기록 재생, 합성 두 영상 처리, 가상 분무 출력을 각각 시험했다. 입력과 결과의 단위가 다르므로 하나의 정확도나 통합 시스템 성능으로 합산하지 않는다."
        ],
        "sources": [
          "r3"
        ],
        "table": {
          "caption": "R3 발표자료의 입력과 결과",
          "headings": [
            "시험",
            "입력",
            "관찰 결과",
            "확인 범위"
          ],
          "rows": [
            [
              "공간 온도 재생",
              "실제 센서 3지점 기록",
              "713시점을 공간 화면으로 재생",
              "센서 사이 공간은 추정 / 공간 전체 오차 미검증"
            ],
            [
              "두 영상 좌표",
              "합성 영상 270프레임",
              "87프레임 좌표 생성 / 183프레임 미결정",
              "실제 카메라 정확도와 구분"
            ],
            [
              "분무 작동·정지",
              "가상 습도·상태 입력",
              "약 2초 뒤 정지 / 정지 후 300초 대기",
              "실제 물압·분사량 미측정"
            ],
            [
              "분무 차단",
              "물 부족·읽기 실패·높은 습도",
              "작동 중 가상 요청 OFF",
              "고장 발생 후 반응 지연은 미측정"
            ]
          ]
        }
      },
      {
        "title": "웹 동작 확인",
        "paragraphs": [
          "사육장·기간 전환, 이전 이력 탐색, 출처 검색, 관리 기록 정정에서 선택 범위와 기록이 유지되는지 확인했다. 조회 실패가 빈 정상 결과로 보이거나 오래된 응답이 다른 사육장 화면에 들어가는 경우를 회귀 검사에 포함했다.",
          "웹 동작 확인은 조회·저장·전환의 기능 검사다. 사용자가 기록을 더 빨리 찾는지, 장시간 실제 센서 수신이 이어지는지, 사육 결과가 개선되는지는 별도 평가가 필요하다."
        ],
        "sources": [
          "web",
          "search",
          "spatial",
          "briefing"
        ]
      },
      {
        "title": "R3 이후 구현·검증 결과",
        "paragraphs": [
          "11월 5일 R3 이후에는 위치별 과거 기록을 다시 읽는 조회 경로와 외관 관찰을 예측·평가 자료로 연결하는 연구 경로를 보강했다. 같은 시각의 기록이 페이지 경계에서 빠지는 문제를 수정하고, 운영 화면의 기간·시점 선택을 별도로 확인했다.",
          "외관 연구는 검수한 촬영 조건·관찰 입력에서 색·질감·시간 특징 이력을 구성하고 ridge 점 예측, 단발 발행과 평가로 이어진다. 정상 합성 입력의 자료 생성과 입력 부족·시점 충돌 시 예측 보류를 확인했다. 11월 17일 최신 탐지 비교에서는 일반 사진 개발 305장에서 F1이 93.31%에서 96.74%로 올랐지만, 야간 정답 11개 중 4개만 탐지해 현장 적용은 보류했다.",
          "11월 16일에는 수중 펌프를 사육장 모델에 조립했다. 실물 시험은 펌프 작동·누수·배수와 분무 뒤 습도 회복 시간을 기록하는 단계부터 시작하며, 자동 제어 성과는 아직 보고하지 않는다."
        ],
        "sources": [
          "historyBoundary029",
          "appearancePipeline029",
          "modelLearningAudit20261117",
          "postR3Delta029"
        ],
        "table": {
          "caption": "2026.11.06–17 확인 기록 · R3 이후 결과 · 입력별 비교",
          "headings": [
            "대상·입력",
            "변경 또는 비교",
            "확인 결과",
            "확인 범위"
          ],
          "rows": [
            [
              "공간 이력 경계 · 2026.11.06\n동일 시각 합성 2,002건",
              "클라이언트가 서버의 시각·ID 커서를 다음 조회에 전달",
              "2,000 + 0 → 2,000 + 2건\n누락 2 → 0건 · 중복 0건",
              "동일 시각 페이지 경계의 조회 완전성"
            ],
            [
              "운영 조회 · 2026.11.06",
              "과거 기록 탐색 · 기간 변경 · 시점 선택",
              "과거 2,000건 뒤 이전 2,000건 조회\n1시간 선택 시 369건 · 선택 시점 센서값 반영",
              "당시 가상 검증 사육장·측정 지연 표시를 유지한 운영 화면 확인"
            ],
            [
              "외관 연구 · 2026.11.07\n합성 사진·마스크·시계열",
              "관찰 입력 검수 · 특징 이력 · ridge 점 예측 · 단발 발행·평가",
              "정상 입력의 특징·예측·평가 자료 생성\n자료 부족·시점 충돌 시 예측 보류와 사유 기록",
              "로컬 소프트웨어 실행 경로 · 실제 개체 반복 주기 평가는 준비 단계"
            ],
            [
              "영상 탐지 비교 · 2026.11.17\n일반 사진 개발 305장 + 야간 정답 11개",
              "기준 hybrid/SAM+CLAHE와 현재 결합 파이프라인 비교",
              "TP 265 → 282 · FP 10 → 8 · FN 28 → 11\nF1 93.31% → 96.74% · 야간 4/11 탐지",
              "일반 사진 개선 확인\n야간 현장 적용 보류 · 새 사육장·야간 영상 재측정"
            ],
            [
              "실물 습도 시험 준비 · 2026.11.16",
              "수중 펌프 도착 후 사육장 모델 조립",
              "펌프 작동·누수·배수·습도 회복 시간 기록 준비",
              "실물 작동·자동 제어 결과는 아직 없음"
            ]
          ]
        }
      }
    ],
    "gaps": [
      {
        "id": "independent-evaluation",
        "title": "독립 평가와 실제 장치 시험 필요",
        "missing": "독립 영상 평가, 기준 센서의 공간 오차, 실제 누수·분사·전원 시험과 장기 수신 자료가 없습니다.",
        "check": "평가 입력과 개발 입력을 분리하고 각 단위의 원시 로그·실패 사례를 확보합니다. 장치 시험과 사용자 과제평가는 별도 검증으로 계획합니다."
      }
    ],
    "slides": [
      "prediction",
      "detection",
      "tracking",
      "temperature",
      "camera",
      "misting",
      "progress-spatial-method",
      "progress-history-result",
      "progress-history-production",
      "progress-detection-result",
      "progress-appearance-input",
      "progress-appearance-prediction",
      "progress-appearance-result"
    ],
    "scenarios": [
      "D3",
      "D5"
    ],
    "detail": "evidence"
  },
  {
    "id": "management",
    "title": "활용 가능성 및 프로젝트 관리",
    "summary": "개인 사육장 적용을 우선하며, 역할별 인계와 통합 시험은 제안 계획입니다.",
    "sections": [
      {
        "title": "개인 사육자 중심의 범위",
        "paragraphs": [
          "10월에는 매장별 Pi가 여러 사육장을 관리하는 구성을 설명했다. 11월 자문 요약에서는 첫 사용자를 크레스티드 게코 개인 사육자로 좁혔다. 소수 개체를 관찰하고 환경·관리 기록을 남기는 흐름을 우선하며 연구 장치를 한 사육장에 연결하는 방향으로 범위를 구체화했다."
        ],
        "sources": [
          "prediction",
          "counsel",
          "planning",
          "release"
        ],
        "table": {
          "caption": "보고일별 범위와 산출물",
          "headings": [
            "자료 기준일",
            "범위·산출물",
            "후속 조건"
          ],
          "rows": [
            [
              "2026.10.06",
              "매장별 Pi·복수 사육장 / 합성 예측",
              "실물 장치와 화면 연결"
            ],
            [
              "2026.10.22",
              "기존 센서 조립 / 탐지·추적 / 구매 검토",
              "부품 규격·담당·시험 기준 확정"
            ],
            [
              "2026.11.05",
              "개인 사육장 구성 / 기능별 시험",
              "실제 카메라·분무 통합"
            ],
            [
              "2026.11.06",
              "웹의 환경·공간 이력 조회",
              "장기 수신·사용자 과제평가"
            ]
          ]
        }
      },
      {
        "title": "역할별 인계 산출물",
        "paragraphs": [
          "10월 6일 자료는 역할을 기능뿐 아니라 다음 작업에 넘길 산출물까지 묶어 제안했다. 아래는 역할 구성안이며 확정된 개인별 배정이나 완료 실적이 아니다. 코드와 함께 설정, 시험 기록, 실패 사례를 인계하는 기준으로 활용한다."
        ],
        "sources": [
          "roles",
          "planning"
        ],
        "table": {
          "caption": "역할 구성안 · 개인별 담당 미정",
          "headings": [
            "역할군",
            "주요 작업",
            "인계 산출물"
          ],
          "rows": [
            [
              "하드웨어·현장 수집",
              "센서·분무 연결, 보호 기능 시험",
              "배선·배치도 / 장치·시간·토출량 기록"
            ],
            [
              "AI·실험",
              "입력·평가 자료 분리, 모델·제어 방식 비교",
              "데이터 명세 / 모델·설정 / 지표·실패 사례"
            ],
            [
              "3D·서비스·통합",
              "센서 위치 연결, 화면·이력 동기화",
              "3D / 화면·API 명세 / 통합 시험·시연"
            ]
          ]
        }
      },
      {
        "title": "다음 시험의 선행 조건",
        "paragraphs": [
          "아래는 후속 시험 계획이다. 장치 규격과 배선을 확인하고, 동물 없는 사육장에서 전원·누수·분사량을 먼저 측정한다. 센서 기록과 실제 영상이 이어지는지 확인한 뒤 조건부 통합을 시험한다. 사용자 과제평가는 장치 시험과 별도로 진행한다."
        ],
        "sources": [
          "planning",
          "r3",
          "web"
        ],
        "table": {
          "caption": "시험 계획 · 담당과 일정은 미확정",
          "headings": [
            "대상",
            "입력·선행 조건",
            "관찰 항목",
            "필요 산출물"
          ],
          "rows": [
            [
              "빈 사육장 장치",
              "규격·배선·전원 확인",
              "누수·실제 분사량·정지·반복 작동",
              "조립 확인표 / 계측·실패 기록"
            ],
            [
              "센서·카메라",
              "실물 연결·시간 기준 확인",
              "장시간 수신, 주야간 시야·가림·지연",
              "시각이 맞는 센서·영상 기록"
            ],
            [
              "조건부 통합",
              "개별 장치 시험 후 연결",
              "요청·동작·정지와 이후 환경 변화",
              "실행 조건 / 연속 동작 기록"
            ],
            [
              "D1~D6 사용성",
              "같은 과제와 관찰 기준 준비",
              "탐색 시간·해석 오류·정정 성공",
              "과제별 결과 / 수정할 화면"
            ]
          ]
        }
      }
    ],
    "gaps": [
      {
        "id": "scope-evolution",
        "title": "매장 중심에서 개인 사육자로 바뀐 범위 확인",
        "missing": "개인 사육자 사용 흐름과 시험 계획은 정리했지만 최종 제출 범위·개인별 담당·일정을 확정한 자료는 부족합니다.",
        "check": "10/06 21장과 R3 3장의 범위 변화를 현재 D1~D6 및 시험 계획과 대조하고, 제출 범위와 남은 이슈의 담당·일정을 확인합니다."
      },
      {
        "id": "evaluation-plan",
        "title": "평가 계획의 담당·입력·수행 기록 확인",
        "missing": "사용성·장기 수신·물리 시험의 절차와 관찰 항목은 제안했지만 확정 담당·일정·평가 입력과 실제 수행 결과는 확보하지 못했습니다.",
        "check": "7·8장의 제안 계획을 기준으로 평가 입력과 실패 기준, 담당·일정을 확정하고 실제 실행 기록을 대조합니다. 제안된 절차를 완료 실적으로 추가하지 않습니다."
      }
    ],
    "slides": [
      "timeline",
      "next"
    ],
    "scenarios": [
      "D6"
    ],
    "detail": "next"
  },
  {
    "id": "deliverables",
    "title": "최종 결과물 및 기대효과",
    "summary": "웹·센서 조립·기존 연구 자료와 R3 이후 공간 조회 보강·외관 연구 실행 경로·개발 비교 기록이 누적 결과물입니다.",
    "sections": [
      {
        "title": "결과물 구성",
        "paragraphs": [
          "결과물은 EasyRep 웹, 기존 센서 노드 조립 기록, 기능별 연구 실험, 보고·시연 자료로 나뉜다. 운영 웹의 조회 기능과 연구 시연에서 사용한 실측 기록·합성 입력·가상 출력을 구분해 제시한다."
        ],
        "sources": [
          "web",
          "assembly",
          "prediction",
          "detection",
          "r3",
          "release",
          "briefing"
        ],
        "table": {
          "caption": "산출물과 확인 범위",
          "headings": [
            "산출물",
            "포함 내용",
            "연결되는 화면·자료"
          ],
          "rows": [
            [
              "EasyRep 웹",
              "환경·관리·공간 이력 조회",
              "환경 / 사육 관리 / 공간 화면"
            ],
            [
              "센서 노드 조립 기록",
              "아크릴 외함·ESP32·브레드보드·센서 배선",
              "10월 22일 발표자료의 기존 조립 사진"
            ],
            [
              "연구 실험",
              "합성 예측·탐지·추적·공간 재생·두 영상·가상 분무",
              "예측 분무·영상·공간·가상 분무의 발표와 상세 설명"
            ],
            [
              "보고·시연 자료",
              "날짜별 개발 경과와 입력별 결과 정리",
              "전체 타임라인 / 슬라이드 발표 / 상세 설명"
            ]
          ]
        }
      },
      {
        "title": "기록을 찾고 해석하는 작업",
        "paragraphs": [
          "센서가 없어도 사육장에 관리 기록을 남길 수 있고, 설치 후에는 측정 시각과 관리 시각을 같은 사육장 기준으로 찾아본다. 공간 화면에서는 센서 위치를 기억에만 의존하지 않고 값과 위치를 함께 확인한다.",
          "취소한 기록의 원본과 사유는 유지되므로 나중에 내용을 바꾼 이유를 다시 읽을 수 있다. 이 기능들이 제공하는 작업과 실제로 시간이 줄거나 오류가 감소하는 효과는 구분해 평가한다."
        ],
        "sources": [
          "web",
          "spatial"
        ]
      },
      {
        "title": "기대효과 평가 계획",
        "paragraphs": [
          "같은 과제를 수행하며 대상과 날짜를 올바르게 찾는지, 화면 상태를 구분하는지, 기록 정정을 마치는지를 관찰한다. 현재 참가자 수·수행시간·효과 점수는 산출하지 않았다."
        ],
        "sources": [
          "web"
        ],
        "table": {
          "caption": "향후 사용자 과제평가 항목",
          "headings": [
            "과제",
            "관찰할 행동",
            "기록할 결과"
          ],
          "rows": [
            [
              "이력 찾기",
              "지정 사육장·날짜의 기록 조회",
              "대상·기간 일치 / 탐색 시간"
            ],
            [
              "상태 해석",
              "오래된 값·빈 결과·조회 실패 구분",
              "해석 오류 / 추가 확인 경로"
            ],
            [
              "관리 기록 정정",
              "취소 사유 작성 후 새 기록 확인",
              "정정 성공 / 원본·새 기록 확인"
            ]
          ]
        }
      },
      {
        "title": "R3 이후 추가 산출물",
        "paragraphs": [
          "새로 보강된 산출물은 공간 이력 조회 수정과 운영 확인 기록, 외관 입력·특징·예측·평가의 별도 연구 실행 경로, 영상 검증기 후보의 개발 비교 기록이다. 사례에서 제기된 위치·시점 해석과 관찰 경과 확인을 실제 구현 결과에 연결했다.",
          "외관 실행기는 웹 일지와 구분된 연구 코드다. 실제 개체 자료에 대한 예측 효용, 상시 실행과 사용자 알림은 후속 평가·통합 범위다. 기존 10월 분무 합성시험은 누적 연구 결과로 유지하며 이번 신규 산출물에 합산하지 않는다."
        ],
        "sources": [
          "historyBoundary029",
          "appearancePipeline029",
          "detectorDevelopment029",
          "postR3Delta029"
        ],
        "table": {
          "caption": "2026.11.05 R3 이후 추가 결과물 · 상세 결과는 실험 및 분석 결과 장과 관련 발표에 연결",
          "headings": [
            "추가 산출물",
            "현재 확보한 내용",
            "관련 발표"
          ],
          "rows": [
            [
              "공간 이력 조회 보강",
              "전체 커서 전달 수정 · 동일 시각 경계 시험\n11월 6일 운영 기간·시점 조회 확인",
              "4–6장 · 공간 방법·누락 수정·운영 확인"
            ],
            [
              "외관 관찰·예측·평가 연구 경로",
              "입력 검수 · 색/질감/시간 특징 이력 · ridge 점 예측\n단발 발행·평가와 합성 정상/보류 결과",
              "8–10장 · 관찰 입력·예측 방법·실행 결과"
            ],
            [
              "영상 검증기 후보 비교 기록",
              "배경 수락 감소와 대상 손실을 함께 기록\n필수 대상 보존 기준에 따라 후보 미채택",
              "7장 · 배경 추가 학습의 결과"
            ]
          ]
        }
      }
    ],
    "gaps": [
      {
        "id": "deployment-version-scope",
        "title": "최신 자료의 배포 버전 확인",
        "missing": "이번 배포 확인 기준은 2026.11.07 release-20261107-materials-v3입니다. 발표 12장·결과보고서 9장·타임라인 5개 날짜를 해당 버전의 운영 확인 기록과 대조합니다.",
        "check": "배포 후 로그인한 운영 화면의 자료·자산과 확인 기록을 대조합니다. 11월 6일의 16장 운영 확인 출처는 당시 기록으로 보존합니다. 운영 접근과 제출용 공개 링크, 기술 검증과 사용자 내용 승인은 구분합니다."
      },
      {
        "id": "submission-links",
        "title": "제출용 공개 링크 확인 필요",
        "missing": "제출할 공개 저장소·시연 주소가 확정되지 않았습니다.",
        "check": "공개 범위와 실제 접근 가능한 제출 주소를 확인한 후 연결합니다. 임시 주소를 최종 결과물 링크로 만들지 않습니다."
      }
    ],
    "slides": [
      "current",
      "status",
      "progress-spatial-method",
      "progress-history-result",
      "progress-history-production",
      "progress-detection-result",
      "progress-appearance-input",
      "progress-appearance-prediction",
      "progress-appearance-result"
    ],
    "scenarios": [
      "D4",
      "D6"
    ],
    "detail": "evidence"
  },
  {
    "id": "appendix",
    "title": "자문·소요 비용 및 부록",
    "summary": "자문은 개인 사육자 중심의 배치에 반영됐으며, 구성품 상태는 과거 자료 기준입니다.",
    "sections": [
      {
        "title": "자문 요약과 반영 방향",
        "paragraphs": [
          "11월 5일 R3의 자문 요약은 첫 사용자를 개인 사육자로 정하고, 소수 개체와 사육장 조건에 맞춰 관찰·분무 설정을 조정하는 방향을 설명한다. 아래는 발표자료에 정리된 요약이며 축어 인용은 아니다."
        ],
        "sources": [
          "counsel",
          "r3",
          "web"
        ],
        "table": {
          "caption": "자문 요약과 서비스·구성의 연결",
          "headings": [
            "자문에서 정리한 방향",
            "반영·연결 내용",
            "현재 범위"
          ],
          "rows": [
            [
              "개인 사육자부터 시작",
              "사육장별 기록과 D1~D6 사용 흐름",
              "웹 조회·수동 기록 제공"
            ],
            [
              "소수 개체·개별 조건 고려",
              "관찰·분무 설정을 사육장에 맞게 조정",
              "개인 설정 통합은 목표 단계"
            ],
            [
              "장치 정리와 일체형 형태",
              "후면 제어부 / 하부 물통·펌프",
              "가상 배치 모델"
            ]
          ]
        }
      },
      {
        "title": "구성품과 구매 검토",
        "paragraphs": [
          "자료의 기준일에 따라 조립된 항목과 검토·대기 항목을 구분한다. 아래 표는 과거 자료의 상태이며 현재 재고나 발주·입고 상태를 새로 확인한 결과가 아니다.",
          "지출 정산은 기존 보유품과 추가 구매품을 나누고 품목·수량·단가·영수증을 대조해 작성한다. 확보된 자료에는 집행 금액과 구매 증빙이 없어 합계를 산출하지 않았다. 금액이 미확보라는 사실을 0원 또는 구매 없음으로 바꾸어 해석하지 않는다."
        ],
        "sources": [
          "assembly",
          "planning",
          "r3"
        ],
        "table": {
          "caption": "구성품의 자료 기준 상태 · 현재 구매 상태 확인 아님",
          "headings": [
            "품목군",
            "자료 기준일",
            "당시 자료의 상태"
          ],
          "rows": [
            [
              "사육장 외함·ESP32·브레드보드·센서 배선",
              "2026.10.22",
              "기존 조립 사진"
            ],
            [
              "분무 펌프·노즐·밸브·호스·연결구",
              "2026.10.22",
              "검토 후보 / 전체 조합 발주 미확정"
            ],
            [
              "전원·보호부품·배선",
              "2026.10.22",
              "규격·전류·정지 경로 검토 항목"
            ],
            [
              "천장·전면 카메라",
              "2026.11.05",
              "자료 작성 당시 미도착"
            ]
          ]
        }
      },
      {
        "title": "용어와 자료 범위",
        "paragraphs": [
          "연구 결과를 읽을 때 실제로 측정한 입력, 계산한 값, 시험을 위해 만든 입력을 나눈다. 발표자료는 보고일과 해당 장, 제품 자료는 공식 페이지와 확인일로 연결한다."
        ],
        "sources": [
          "prediction",
          "detection",
          "r3",
          "web",
          "monsoon",
          "ecc",
          "slither"
        ],
        "table": {
          "caption": "이 보고서에서 사용하는 용어",
          "headings": [
            "용어",
            "뜻",
            "구별할 내용"
          ],
          "rows": [
            [
              "실측",
              "센서가 놓인 지점의 측정 기록",
              "색이 표시된 공간 전체의 직접 측정과 구분"
            ],
            [
              "보간",
              "센서 사이 값을 입력에서 계산",
              "추가 센서의 측정값이 아님"
            ],
            [
              "예측",
              "기록과 계획으로 이후 값을 계산",
              "현재 측정값·과거 이력과 구분"
            ],
            [
              "합성",
              "시험을 위해 만든 영상·환경 입력",
              "실제 촬영·측정과 구분"
            ],
            [
              "가상 출력",
              "소프트웨어가 표시한 작동 요청",
              "실제 펌프 회전·물 분사와 구분"
            ]
          ]
        }
      }
    ],
    "gaps": [
      {
        "id": "missing-raw-documents",
        "title": "자문 원문과 비용 증빙 자료 미확보",
        "missing": "자문 일시·참여자·원문, 요청사항 반영 증빙, 실제 구매 내역이 필요합니다.",
        "check": "자문 요약과 원문을 대조하고 비용은 품목·수량·단가·영수증으로 확인합니다. 개인 연락처와 증빙 원본은 공개 화면에 게시하지 않습니다."
      }
    ],
    "slides": [
      "system",
      "status"
    ],
    "scenarios": [],
    "detail": "evidence"
  }
];

export const reportReviewItems = reportChapters.flatMap(chapter => chapter.gaps.map(gap => ({ ...gap, chapterId: chapter.id, chapterTitle: chapter.title })));
