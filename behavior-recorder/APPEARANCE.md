# 카메라 없는 시작 경로 — 2026-11-04

2026-11-07 최신 실행 기준: PC 연결 없이 현재 Mac의 `.venv-vision`을 사용한다. 터미널에서 `source .venv-vision/bin/activate` 후 실행하며 `execution_host`/`--execution-host`는 실제 `platform.node()`와 같아야 한다. 합성 검사 통과는 실제 탈피 예측 검증이 아니다. [로컬 검증 기록](data/appearance-local-validation-20261107-07/completion-review.json).

전용 사육장 카메라 없이 **직접 본 상태와 탈피 시작·완료·불확실 구간**을 기록할 수 있습니다. 사진은 선택 사항입니다. 사용자의 최신 요청인 “우리 카메라가 없어도 가능하게 해줘”를 반영했으며, 이전의 카메라 모델/시청 앱 확인은 이 경로의 선행 조건이 아닙니다.

```sh
zsh "/Users/giminu0930/Documents/ChatGPT/HabitatOS/behavior-recorder/Start Appearance Journal.command"
```

Python 표준 라이브러리로 로컬 화면을 엽니다. 기본 주소는 `http://127.0.0.1:8768/`이며 카메라, FFmpeg, 학습 모델을 불러오지 않습니다. 터미널에서 `Ctrl+C`로 종료합니다. 기존 Vision Lab을 켠 경우에는 `/appearance`에서도 같은 기록 화면을 사용할 수 있습니다. 실행기의 파일 권한은 변경하지 않았으므로 위 `zsh` 명령으로 실행하세요.

1. `crested-01`을 기록할 실제 개체와 연결해 사용하고, 직접 본 사람의 기록자 ID를 입력합니다. 다른 개체는 다른 ID를 사용합니다.
2. 직접 본 상태와 시각을 기록합니다. 시각이 불확실하면 시작/끝 구간을 남깁니다. ‘옅어 보임’이나 ‘평소와 비슷함’을 미래 탈피 정답/음성으로 자동 변환하지 않습니다.
3. 사진·카메라 모델·사육장 ID 없이 저장할 수 있습니다. 사육장 ID를 모르면 null로 유지합니다. 사진이 있으면 JPEG/PNG 8MiB 이하 원본을 선택 첨부합니다.
4. ‘전체 기록 내보내기’로 관찰 이력을 JSON으로 받습니다. 저장소는 기본 `data/appearance-journal-local/appearance-journal/`이며, 일반 Vision Lab 경로는 해당 저장소의 `appearance-journal/`입니다. 두 저장소는 자동 병합하지 않습니다.

일지는 사람의 선언을 보존하는 입력 단계입니다. 개체 식별의 독립 검증, 이미지 디코딩/색상 측정/피부 마스크 검수, 학습 적격성 판단은 수행하지 않습니다. 첨부 원본은 해시와 바이트를 보존하며 `unreviewed_attachment`로 표시합니다. 기존 `appearance`/`appearance_series` 형식의 검수 산출물과 다르므로 일지 JSON을 그 입력으로 바로 사용하지 마세요. 아래 검수 연결에서 실제 개체·사육장 연결과 이벤트 근거를 확인한 뒤 변환합니다.

현재 `prediction=null`, `training_readiness=not_assessed`, `actuation_allowed=false`입니다. **사진이 없어도 탈피 이력 수집은 가능하지만, 색상 기반 예측에는 비교 가능한 실제 컬러 사진이 필요합니다.** 일지 시작/완료 기록만으로 탈피 주기를 자동 연결하거나 다음 날짜를 추정하지 않습니다. 실제 예측 학습·주기/시간/개체 분리 평가·분무 반응 보정은 후속 단계입니다.

소프트웨어 검증용 `--appearance-only --test-journal --storage <별도 경로>`는 합성 검사 저장소를 만들며 실제 기록과 혼합하면 거절합니다. 이 기능의 합성 검사 및 UI 저장/내보내기 확인은 생물학적 예측 성능이 아닙니다. 기록 한도 512개, 첨부 총량 256MiB를 넘기면 삭제·덮어쓰기 없이 거절합니다.

## 수동 일지의 명시적 검수와 수집기 연결

`behavior_recorder.appearance_intake`는 기존 일지를 **읽기 전용**으로 열고, 선택한 기록의 바이트 해시를 고정한 검수 계획을 만듭니다. 일지나 첨부 파일을 수정하지 않습니다. 전용 카메라가 없어도 확인된 탈피 사건은 변환할 수 있습니다. 색 특징에는 실제 컬러 사진과 검토한 마스크가 별도로 필요합니다.

```sh
# 원래 일지를 포함하는 data 디렉터리에 계획을 둡니다. RECORD_ID는 실제 32자리 기록 ID로 바꿉니다.
.venv-vision/bin/python -m behavior_recorder.appearance_intake prepare --journal data/appearance-journal-local/appearance-journal --records RECORD_ID --output data/appearance-review-v1.json
# 계획을 사람이 검토·수정한 뒤, 새 출력 폴더에 수집합니다.
.venv-vision/bin/python -m behavior_recorder.appearance_intake collect --plan data/appearance-review-v1.json --output data/appearance-reviewed-v1 --execution-host MacBook-Pro.local
```

계획의 `reviewer`, `reviewed_at`을 실제 검토에 맞게 입력합니다. 수집할 기록에는 동일 개체·사육장 연결을 확인한 `identity_confirmed=true`와 비어 있지 않은 `enclosure_id`가 필요합니다. 일지에서 null로 남긴 사육장 ID를 임의 예제로 채우지 않습니다. 검토 시각은 원래 기록·사진이 접수된 시각 이후여야 합니다. 과거 관측을 나중에 검토해도 새 산출물의 생성 시각을 과거로 소급하지 않습니다.

- 탈피 사건: 선택 항목의 `event_stage`를 원래 기록과 같은 `started`, `completed`, `uncertain`으로 직접 지정하고 `hold_reason`을 null로 둡니다. 원래 시작·끝 구간과 관찰자를 보존하며, 별도 검토자와 출처 해시도 남깁니다. `uncertain`을 시작/완료로 바꾸거나 `paler`/`usual`을 정답·음성으로 바꾸면 거절합니다. 사실을 정정하려면 새 일지 기록과 근거를 보존해야 합니다.
- 색 관측: 항목의 `color_review`에 [검토 템플릿](examples/appearance.intake-color-review.template.json)을 채웁니다. 촬영 시각은 원래 관찰 구간 안이고 첨부 접수보다 늦지 않아야 합니다. 원래 첨부 사진만 사용하며 마스크 경로와 SHA256, 몸 부위, 촬영 조건, 피부·젖음·선명도 검토가 필요합니다. `media_rights`에는 이미지·마스크에 대한 `own`, `permission`, `licensed` 중 근거가 있는 선언과 설명을 남깁니다. 이는 독립적인 권리 인증이 아닙니다. 경로는 검수 계획 파일 기준이며 `..`와 심볼릭 링크 우회는 허용하지 않습니다.
- 보류: 두 검토 항목을 null로 유지하고 `hold_reason`을 남깁니다. 사육장 미연결 상태도 그대로 보존할 수 있으며 학습용 기록은 생성하지 않습니다. 같은 원본에서 사건과 색 관측을 함께 수집할 수 있지만 서로 다른 고정 ID로 저장하고 주기는 자동 연결하지 않습니다.

색 관측은 기존 `appearance.collect`를 사용합니다. RGB·크기·방향·이진 피부 마스크 조건을 실제로 검사하고 특징을 계산합니다. 젖음·IR·불명 촬영 조건 등은 기존 기준에 따라 제외되며 특징은 null입니다. 일지 업로드에서 PNG/JPEG 시그니처를 확인했다는 사실만으로 디코딩이나 색 검수를 통과한 것으로 세지 않습니다. 마스크 생성이나 촬영 조건 추정은 하지 않습니다.

완료 폴더에는 검토 계획의 원문 사본, 선택 원본 기록, 색 관측에 사용한 사진·마스크의 동일 바이트 사본, 수집기 입력·산출물, `series.json`, `series-report.json`, `intake-report.json`이 남습니다. 보류만 있으면 series를 만들지 않습니다. `intake-report.json`의 완료·개수·파일/코드 해시를 확인한 뒤 다음 단계로 넘깁니다. 실패하면 부분 파일과 `failure.json`을 보존하며 같은 출력 폴더의 자동 재시도·덮어쓰기를 거절합니다. 복사된 `review-plan.source.json`은 출처 보존용이며 새 실행 계획으로 재사용하지 않습니다.

`series.json`은 **이번 수집 묶음**입니다. 여러 묶음을 개체 전체 시계열로 연결할 때는 기존 `appearance_series` manifest에 공통 상위 폴더 기준의 산출물 경로를 명시할 수 있습니다. 아래 `history` 명령은 이 기존 형식을 만들면서 각 intake의 완료 보고서와 산출물 해시도 확인합니다. 고정 기록 ID와 이미지/몸 부위 중복 검사가 같은 관측의 중복 계산을 막습니다. 주기 연결·역할 분리·학습은 기존 후속 단계에서 별도로 고정합니다. 수집 완료만으로 `training_readiness=not_assessed`, `prediction=null`, `actuation_allowed=false`를 바꾸지 않습니다.

한 번에 명시적 기록24개, 계획1MiB, 사진8MiB·마스크16MiB, 선택 미디어 합계128MiB로 제한합니다. 필수 원본 SHA256을 비워 검수 고정을 우회할 수 없으며, 외부 입력 해시 읽기에도 바이트 상한을 적용합니다. 미디어 합계는 반복 읽기를 포함한 전체 I/O 측정값이 아닙니다. 새 합성 연결 검사27개를 Mac CPU에서 확인했으며 실제 개체 관측·학습·예측 성능은 아닙니다. [10 검증 기록](data/appearance-reviewed-intake-20261107-10/completion-review.json)을 따릅니다.

### 여러 날짜의 검수 묶음 연결

[history 계획 예시](examples/appearance.history.template.json)를 두 intake 폴더의 공통 상위 폴더에 복사합니다. `intakes`에 실제 완료된 `intake-report.json` 경로와 해당 파일의 바이트 SHA256을 명시합니다. null 해시는 거절됩니다. 목록은 자동 탐색하지 않으며 한 개체의 완료 묶음만 선택합니다.

```sh
.venv-vision/bin/python -m behavior_recorder.appearance_intake history --plan data/appearance-history-plan.json --output data/appearance-history-v1.json --execution-host MacBook-Pro.local
```

출력 manifest의 부모는 원본 intake 폴더들의 공통 상위 폴더여야 합니다. 출력은 기존 시계열 계획의 `series`에 그대로 지정할 수 있습니다. 원본 사진·마스크·수집기 산출물을 복사하거나 고치지 않고 기존 산출물 경로를 참조합니다. 관측 시각과 산출물 가용 시각도 유지합니다. 보류 내역은 receipt에 남고, 불확실 사건과 젖음 등으로 제외된 색 관측은 기존 상태를 유지합니다.

완료 시 `<출력명>.receipt.json`과 최종 manifest를 함께 확인합니다. 최종 manifest는 검사가 끝난 뒤 마지막에 게시됩니다. 중간에 실패하면 `.started.json`, `.candidate.json`, `.failure.json` 등 부분 근거를 보존하고 같은 출력명의 재시도를 거절합니다. 원본이 바뀌거나 부분 실패한 intake, 서로 다른 개체·사육장·실제/시험 자료, 중복 기록·동일 이미지/몸 부위는 합치지 않습니다.

완료 보고서 최대32개, 합친 기록 최대512개, 보고서/계획 각1MiB·기록/manifest 각64KiB, 메타데이터 읽기 상한32MiB를 적용합니다. 기존 series 검증의 최대 재읽기 용량도 상한에 포함하므로 실제 허용 개수는 입력 크기에 따라 줄어듭니다. 이 단계는 저장된 해시·형식의 연결 검사이며 원본 픽셀·색 특징·권리·개체·시계의 독립 재검증이 아닙니다. 주기 연결·역할 할당·학습을 자동 수행하지 않습니다.

# 개체별 색 변화와 탈피 예측

2026-10-29 사용자 추가 요청. 목표는 개체별 색 변화와 실제 탈피 이력을 학습하고, 검증 후 환경 기록과 함께 분무 조절에 활용하는 것이다.

## 2026-11-07 과거 관측 특징과 탈피 구간 연결

`behavior_recorder.appearance_timeline`을 추가했다. 기존 검수 산출물을 `appearance_series`의 동일 개체·종·사육장·시험/실제 구분과 중복 검사로 읽은 뒤, 같은 촬영 조건의 과거 RGB·채도·명도와 현재 값을 비교한다. 과거 관측 중앙값 대비 변화, 직전 관측 대비 시간당 RGB 변화, 이력 길이를 만든다. 비교 조건이 다르거나 `max_gap_hours`보다 관측 간격이 길면 이력을 연결하지 않는다. RGB IQR은 색 분포 폭이며 피부 질감 측정으로 부르지 않는다.

```sh
# 현재 Mac의 CPU 경로에서도 실행할 수 있다.
python -m behavior_recorder.appearance_timeline --plan temporal-plan.json --output temporal-dataset-v1.json
```

[계획 템플릿](examples/appearance.temporal.template.json)의 `series`는 기존 `appearance_series` manifest 경로다. `max_gap_hours=24`는 편집할 예시 처리 설정이며, 생물학적으로 검증된 관측 간격이 아니다. 계획과 산출물 해시를 남기며 이미 있는 출력은 덮어쓰지 않는다. 계획 JSON은 64KiB, 기존 산출물은 최대 512개, 명시적 주기는 최대 128개다. 빈 주기 목록에서도 특징을 준비할 수 있지만 정답과 역할은 null이다.

주기는 사람이 확인하여 `cycles`에 직접 연결한다. 다음의 ID는 실제 관측 ID로 바꿔야 하며, 예제 자체가 관측이나 주기를 뜻하지 않는다.

```json
{
  "cycle_id": "confirmed-cycle-id",
  "previous_completed": "previous-completion-record-id",
  "started": "start-record-id",
  "completed": "completion-record-id",
  "role": "train",
  "observer": "reviewer-id",
  "evidence_reference": "확인한 동일 개체의 주기 연결 근거"
}
```

이전 완료·시작·완료의 확인 구간이 순서대로 놓여야 하며, 시작/완료를 여러 주기에 재사용할 수 없다. 주기 전체에 `train`, `validation`, `test` 역할을 부여하고 시간순 역할 역전을 거절한다. 연결 구간에 다른 미연결 탈피 기록이나 불확실 기록이 있으면 정답을 보류한다. 확인된 시작 이전 관측만 '시작까지 남은 시간의 하한·상한'을 갖는다. 미연결·시작 구간 안·젖음 등 제외 관측은 음성 정답이 아니다.

과거 시점의 예측을 가장하지 않도록 `as_of`는 촬영 시각과 검수 산출물 생성 시각 중 늦은 시각이다. 그때 생성되지 않은 과거 사진이나 아직 기록되지 않은 이전 탈피 완료는 해당 시점의 특징에 넣지 않는다. 정답의 `available_at`은 시작/완료 기록 생성 시각과 완료 구간 끝보다 빠를 수 없다. 오래된 사진을 나중에 검수하면 당시 실시간 예측 표본으로 자동 인정되지 않는다.

이 단계는 픽셀·색 특징의 진위나 시계 정확도를 다시 검증하지 않고, 주기 연결은 사람 선언이다. 시계열 산출물 자체는 `training_readiness=not_assessed`, `shedding_prediction=null`, `actuation_allowed=false`를 유지한다. 학습 cutoff·개체 분리는 아래 별도 평가 모듈에서 검사한다. 생물학적으로 충분한 표본 확보와 실제 예측 모델 학습은 미완료다. 피부 질감·행동·환경은 아래의 별도 검수 산출물을 선택적으로 연결한다.

새 PC 합성 검사 12개가 통과했다. 미래 값·입력 순서·지연 검수·촬영 조건·관측 공백·불확실 구간·역전된 평가 역할·라벨 사용 시각·출력 보존을 검사했다. 기존 완료된 수집 검사와 모델 추론은 반복하지 않았다. 실제 개체 자료 학습·생물학적 성능 검증은 0이다.

## 2026-11-07 고정 평가 자료와 간격 기준선

`behavior_recorder.appearance_evaluation`은 사후 시계열 평가 준비·채점 모듈이다. [평가 계획 템플릿](examples/appearance.evaluation.template.json)의 null, 경로, SHA256, 표본 수·오차 기준을 실제 설계에 맞게 채워야 한다. 예시 수치를 생물학적 승인 기준으로 제공하지 않는다.

```sh
# PC의 격리 Python에서 실행. 실제 자료 검수·자원 확인은 별도 선행한다.
python -m behavior_recorder.appearance_evaluation --plan evaluation-plan.json --output frozen-cohort-v1.json
python -m behavior_recorder.appearance_evaluation --plan evaluation-plan.json --cohort frozen-cohort-v1.json --predictions predictions-v1.json --output scores-v1.json
```

계획은 시계열 파일의 바이트 해시를 고정한다. 평가 시 원래 계획·검수 산출물로 시계열을 재생성하여 내용까지 대조한다. 한 개체의 전체 시계열을 한 번만 넣으며 실제/합성·종 혼합과 개체를 바꿔 붙인 동일 원본 이미지 해시를 거절한다. 계획은 64KiB, 시계열은 각 4MiB, 최대 16개 시계열의 명시적 메타데이터는 32MiB로 제한한다. 공통 기준선 주기 근거는 한 번만 저장하며, 고정 cohort 출력은 16MiB를 넘으면 저장 전에 거절한다. 원본 픽셀·정체성·촬영 시계의 진위를 다시 판정하는 기능은 아니다.

- `fit_cutoff` 이전에 학습 주기의 모든 시작/완료 구간과 기록이 끝나고 특징·정답이 사용 가능해야 한다. 주기를 잘라 일부 행만 학습에 넣지 않는다.
- `future_cycle`은 학습 이력이 있는 같은 개체의 미래 주기를 평가한다. `held_out_animal`은 학습 개체와 평가 개체를 분리하고 validation/test 개체도 서로 분리한다. 두 방식은 별도 계획·결과다.
- `anchors`에 평가 관측을 명시하고 주기당 한 번만 평가한다. 선택 시점과 근거는 작업자가 고정해야 한다. 이 사후 계획만으로 결과를 보기 전 선택했음을 증명하지 않는다.
- `training_rows`에는 학습 정답, `forecast_rows`에는 평가 정답을 뺀 특징만 내보낸다. 채점 때만 원래 라벨을 읽는다. 촬영 조건과 과거 특징의 한계는 시계열 모듈을 따른다.
- 개인화 기준선은 마지막 적격 학습 주기의 ‘이전 완료→다음 시작’ 간격을 쓴다. 새 개체 기준선은 학습 주기별 간격 중앙값을 쓴다. 구간 중간값을 사용하는 계산 규칙이며 신뢰 구간이나 생물학적 주기 법칙이 아니다.
- 확인된 test 주기·개체만 평가 최소 표본 수에 센다. validation, 미확인 라벨, 색상 프레임 수로 test 주기 수를 부풀리지 않는다. `model_fitting_allowed`는 선언한 실제 자료·구조·최소 수 충족 여부만 뜻하며 실제 학습 실행이나 생물학적 충분성 인증이 아니다. 합성 자료에서는 항상 false다.

예측 파일은 `schema_version=1`, `kind=appearance_point_predictions`, `dataset_kind`, `feature_version`, `model_id`, `cohort_sha256`, `rows`를 갖는다. 각 행은 `animal_id`, `record_id`, `hours_until_start`이며 null은 보류다. 없는 예측과 명시적 보류를 구분한다. 고정 cohort 바이트 해시와 일치해야 하며 알 수 없는/중복 행, 비유한 수치, 음수 시간은 거절한다. model ID 선언만으로 실제 학습 이력·미래 라벨 비사용이 입증되지는 않는다.

점 예측에서 실제 확인 구간까지의 거리, 확인 구간 내 포함 비율, 채점 가능 비율, 보류·누락을 보고한다. 기준선과 같은 관측끼리만 오차 감소를 비교하며 validation/test 승인 판단을 섞지 않는다. 라벨 미확인/미연결 행은 채점하지 않고 음성이나 통계적 중도절단 정답으로 가정하지 않는다. 구간 포함 비율은 확률 보정 성능이 아니다. 주기당 한 번의 채점으로 일별 오경보·놓친 전체 주기·실시간 선행 시간·확률 보정을 평가했다고 할 수 없으므로 `biological_validation_complete=false`, `actuation_allowed=false`를 유지한다.

새 PC 합성 검사 19개가 통과했다(2.782초). 기존 완료된 12개 시계열 검사는 다시 실행하지 않았다. 실제 관측·모델 학습·생물학적 예측 성능은 이 검사로 생기지 않는다. 고정 학습 자료용 실행기는 아래 단계에서 추가했다. 피부 질감·행동·환경 결합과 전체 알람 평가는 남아 있다.

## 2026-11-07 고정 색상 특징 모델 실행기

`behavior_recorder.appearance_predictor`는 신경망 없이 고정된 ridge 선형 모델을 학습·저장하고 위 평가기로 연결한다. 학습 입력은 고정 cohort의 `training_rows`, 예측 입력은 라벨을 제외한 `forecast_rows`다. 예측·기준선 값으로 학습 통계나 모델을 선택하지 않는다. 아직 실제 개체 자료로 학습한 모델은 없다.

```sh
# 현재 Mac에서도 실행할 수 있다. 기존 .venv-vision을 활성화하고 fit-plan의 execution_host를 실제 platform.node()와 맞춘다.
# 템플릿은 실제 설계 값과 cohort 해시를 채우기 전에는 거절된다.
python -m behavior_recorder.appearance_predictor fit --plan fit-plan.json --output fit-run-v1
python -m behavior_recorder.appearance_predictor score --plan fit-plan.json --run fit-run-v1 --evaluation-plan evaluation-plan.json --output scores-v1.json
```

[학습 계획 템플릿](examples/appearance.fit.template.json)은 특징 목록, 정규화 계수, 넓은 라벨 구간 제외 기준, 최소 학습 행 수, 예측 범위·지원 범위를 사전에 고정한다. `regularization=1`은 최초 공학적 기준 모델 설정이며 검증된 생물학적 최적값이 아니다. 다른 null 값은 실제 관측과 평가 설계에 맞게 정해야 한다. 실제 자료의 명시된 주기·개체 최소 수와 기존 cohort 검증도 통과해야 한다. 합성 자료를 실제 자료로 바꿔 표기해 이 경계를 넘기면 안 된다.

사용 가능한 입력은 이전 완료 이후 경과 시간, 같은 촬영 조건에서의 RGB·채도·명도 변화, 시간당 RGB 변화, 과거 이력 길이다. 경과 시간과 색 특징 하나 이상을 선택한다. 현재 평균·표준편차는 **학습 행만**으로 계산하고, 각 주기의 총 가중치는 같다. 원래 정답 구간의 중간값을 학습 목표로 쓰는 명시적 근사이며 정확한 탈피 시작 시각으로 간주하지 않는다. 무작위 선택이나 하이퍼파라미터 탐색은 없고 `seed=null`이다.

특징이 없는 행은 0이나 추정값으로 채우지 않는다. 라벨 구간이 선언한 폭보다 넓으면 제외하고, 제외 후 적격 학습 행·주기·개체 수를 다시 확인한다. 예측 특징이 학습 통계에서 선언한 `max_abs_z`보다 멀거나 학습 중 상수였던 값이 바뀌면 보류한다. 지원 범위 검사는 분포 변화 탐지의 완전한 증명이 아니다. 음수 예측은 0으로 제한한 사실을 기록하고, 선언한 예측 시간 상한을 넘으면 보류한다.

출력 폴더에는 시작 자원 상태, `model.json`, 평가기와 호환되는 `predictions.json`, 관측별 보류 사유와 `run.json`이 저장된다. 모델 ID는 학습 입력·설정·정규화 통계·계수·코드 해시에 연결되고 미래 예측 값에는 의존하지 않는다. run은 정확한 cohort/계획 바이트 해시와 예측 입력을 별도로 고정한다. `score`는 코드·파일·입력·모델 ID가 일치해야 진행한다. 이는 로컬 기록의 무결성 확인이며 악의적으로 다시 작성된 기록의 진위를 보증하는 실행 인증은 아니다.

기존 출력 폴더를 덮어쓰거나 자동 재시작하지 않는다. 학습 직후 모수를 먼저 저장하므로 이후 예측이 실패해도 모델은 보존된다. 실패 기록은 `fit_completed`, `forecast_completed`, 실제 자료 학습 여부를 구분한다. 실제 자료 시도에서 학습 완료가 확인되지 않으면 완료 여부를 null로 남기며 실패를 학습 0회나 성공으로 바꾸지 않는다.

CLI는 선언한 실제 호스트, 실행 PID/생성 시각, 작업 목록, 여유 RAM을 확인한다. Windows는 기존 CPU affinity 1개·BelowNormal·GPU 현황 조회를 유지한다. Mac은 CPU 라이브러리 1스레드 환경과 nice≥10을 적용하며 affinity와 GPU/온도 측정값을 추정하지 않는다. 두 경로 모두 GPU를 할당하지 않는다. 처리 중 여유 RAM 3GiB·RSS 512MiB·60초 경계를 단계별로 검사한다. 이는 협조적 중단 검사이며 OS가 보장하는 강제 시간 제한이나 연속 최대 RSS 측정이 아니다. 최대 8192개 학습 행·22개 특징(색/경과 10개, 선택 문맥 4개, 선택 질감 8개)·2048개 예측 행으로 계산을 제한하고 기존 작업이나 설정을 건드리지 않는다.

합성 자료의 CLI 검사는 `fit ... --software-test`로만 허용하며 `status=software_test_only`, `actual_biological_fit=false`다. 실제 자료에 이 옵션을 붙이면 거절한다. 새 PC 합성·수치 검사 15개가 통과했다(3.124초). 손계산과의 일치, 주기 가중치, 미래 정보 분리, 결측/범위 보류, 실제/합성 구분, 저장·채점·변조 거절, 예산 거절과 부분 실행 보존을 확인했다. 기존 완료된 시계열·평가 검사 전체는 재실행하지 않았다. 실제 관측 학습·탈피 예측 성능·물리 제어는 0이며 생물학적 검증 완료로 표시하지 않는다.

## 2026-11-07 행동·온습도 연결 — Mac CPU 검증 완료

`behavior_recorder.appearance_context`는 검수된 행동 구간과 센서 기록을 각 색 관측의 `as_of`에 연결한다. 선택 기능이며 기존 색상 전용 계획·자료의 형식은 유지한다. 초기 연결·통합 검사 14개는 PC에서 통과했다. 이후 추가한 입력 크기·시각 모순 검사 중 SSH 연결이 끊겨 18개 검사의 종료 여부는 미확정이다. 그 뒤 작성한 경계 처리 수정은 사용자 승인 후 Mac에서 18개 합성 검사를 통과했다. PC의 이전 실행 결과는 여전히 미확정이며 Mac 검증과 구분한다. 최신 검증은 `data/appearance-context-features-20261107-04/completion-review.json`을 따른다.

계획은 `examples/appearance.context.plan.template.json`을 복사해 작성한다. 템플릿의 null은 실제 값으로 채워야 하며 허용 시계 오차·센서 최대 나이·행동 관측 창·최소 관측 비율은 실험 전에 정한다. 개체·사육장·관측 ID, 촬영/가용 시각은 원래 temporal 자료와 정확히 일치해야 한다. `sources`는 상대 경로와 파일 SHA256으로 고정한 센서/행동 JSON을 가리킨다. 합성/실제 자료를 섞지 않는다.

센서 파일은 `kind=appearance_context_sensors`, 행동 파일은 `kind=appearance_context_behaviour`이며 모두 `schema_version=1`, `dataset_kind`, `records`를 갖는다. 빈 records는 실제 측정 0건을 뜻한다. 템플릿에는 예제 측정값을 넣지 않았다.

- 센서 행은 기존 `records.py` 센서 형식(`record_id`, `enclosure_id`, `observed_at/observed_clock`, `received_at/received_clock`, `source`, `geometry_revision`, `placement_revision`, `readings`)에 `recorded_at/recorded_clock`을 더한다. `recorded_at`은 이 정보가 검수·기록되어 이용 가능해진 시각이다. 각 reading은 `sensor_id/unit/value/quality`를 갖는다. 온도 단위는 `Cel`, 습도는 `%RH`이며 자동 환산하지 않는다. 실제 source는 `sensor`, 합성은 `simulation`이다.
- 행동 행은 `record_id`, `animal_id`, `enclosure_id`, `start_at/end_at/observed_clock`, `received_at/received_clock`, `recorded_at/recorded_clock`, `quality`, `identity_method`, `active_seconds`, `observer`, `evidence_reference`를 갖는다. `quality=valid`와 `identity_method=human_confirmed`인 같은 개체의 검토 구간만 사용한다. 추적기 임시 ID를 개체 ID로 간주하지 않는다. 확인되지 않은 값은 null이며 확인되지 않은 구간을 비활동 시간으로 채우지 않는다.

모든 clock은 기존 `{source, accuracy_ms}` 형식이다. 이는 신고한 오차 범위이며 독립 시계 검증의 증거가 아니다. 오차 불명, 미래를 걸치는 구간, 늦은 수신·검수, 다른 개체/사육장, quality·단위·배치 불일치는 제외 사유를 남긴다. 센서는 가용 시점까지 알려진 최신 기록을 사용하되 그 기록이 무효하면 오래된 정상 값으로 대체하지 않는다. 시간 순서를 오차 범위로 구분할 수 없으면 보류한다. 수신이 사건보다 앞서거나 검수가 수신보다 앞선 모순도 수정안에서 거절한다.

추가 특징은 `temperature_c`, `humidity_percent`, `activity_fraction`, `behaviour_coverage`다. 행동 비율은 겹치지 않는 확인 구간의 활동 초 합 / 관측 초 합이다. 창 전체의 활동 비율로 해석하면 안 된다. coverage는 시계 오차를 뺀 보수적 관측 길이 / 선언 창 길이이며 최소 coverage 미달이면 활동 특징을 보류한다. 자료가 전혀 없으면 coverage도 null이다. 0은 실제 확인된 0과 구분한다. 혈색·건강·탈피 정답으로 자동 변환하지 않는다.

```bash
# 현재 호스트의 Python에서 실행한다. 실제 자료 검수·파일 해시 고정이 선행한다.
python -m behavior_recorder.appearance_context --plan context-plan.json --output context-v1.json --execution-host MacBook-Pro.local
```

그 다음 temporal 계획에 `context: {"plan": "context-plan.json", "artifact": "context-v1.json", "sha256": "산출물의 실제 SHA256"}`을 추가한다. 경로는 temporal 계획 기준이며 context 계획 내부 source 경로는 그 계획 기준이다. 결합 시 산출물의 바이트 해시와 원본 메타데이터에서 재생성한 값을 모두 대조한다. 평가 계획의 `feature_version`은 `past-only-reviewed-srgb-context-v1`로 고정하고 새 timeline/cohort를 만든다. 기존 `past-only-reviewed-srgb-v1`은 그대로 허용한다. 색상 전용 cohort에 문맥 특징 이름만 추가해 학습하는 경로는 거절한다. 기존 모델 실행의 해시 검증에는 해당 실행 당시 코드가 필요하다.

Mac에서도 위 CPU 전용 자원 검사를 거쳐 실행한다. GPU 할당 0과 협조적 60초 검사를 유지한다. 최대 512개 anchor·8개 source·전체 4096개 context 행·source 총 8MiB·산출물 8MiB를 제한한다. 경계 수정안은 행마다 누적 출력 크기를 확인하며, 전체 cohort 입력은 기존 32MiB 제한에 context 파일까지 포함한다. 값·시각·개체 확인은 선언 및 검수 근거이며 생물학적 진실이나 독립 계측 인증은 아니다. 실제 학습·예측 성능·물리 제어는 아직 검증되지 않았다.

## 2026-11-07 피부 질감 후보 특징 — Mac CPU 추출기 검증 완료

`behavior_recorder.appearance_texture`는 기존 색 관측에 연결되는 별도 질감 산출물이다. 기존 수집기의 입력 형식을 변경하지 않는다. 사용자 승인 후 Mac CPU에서 합성 검사 16개와 CLI 실행 검사가 통과했다. 아래의 선택형 시계열·모델 입력 연결도 소프트웨어 검증을 마쳤다. 실제 피부 관측·탈피 예측 성능의 증거가 아니다.

RGB 사분위 범위는 공간 배치를 무시하므로 질감으로 부르지 않는다. 이 구현은 같은 피부 영역 안에서 선언한 픽셀 거리만큼 떨어진 두 점의 명암 차이를 측정한다. 명암 값은 **인코딩된 sRGB 세 채널의 산술평균 / 255**이며 물리적 휘도나 보정된 색 공간이 아니다. 가로·세로 방향별 절대 차이 평균과 제곱 차이 평균을 계산하고, 두 방향에 같은 가중치를 주어 평균 절대 차이와 RMS 차이를 만든다. 방향별 유효 쌍 수도 보존한다. 픽셀 쌍 개수는 독립 개체나 탈피 주기 수가 아니다.

두 끝점 사이의 **모든 픽셀**이 검수한 피부 마스크 안에 있어야 한다. 마스크의 구멍이나 배경을 가로지르는 쌍은 제외한다. 어느 방향이든 선언한 최소 쌍 수에 못 미치면 특징은 null이다. 조명·노이즈·초점·자세·배율에 민감한 단순 공간 대비 지표이며 피부 생리나 탈피를 식별한다는 검증은 없다.

`examples/appearance.texture.template.json`은 실제 측정값과 검수 정보를 채우기 전에는 실행되지 않는 템플릿이다.

- `observation_input`은 원래 색 관측 JSON, `observation_artifact`는 그 수집 결과, `observation_sha256`은 수집 결과의 실제 바이트 SHA256이다. 입력과 산출물 메타데이터가 같고 원본 사진·마스크 바이트 해시가 일치해야 한다.
- `extraction`에는 `pixel_offset`(1~64 정수), 방향별 `minimum_pairs`(16~4,194,304 정수), `max_clipped_fraction`, `max_scale_relative_error`를 고정한다. 이 범위는 계산·입력 경계이며 생물학적 최적값이 아니다. 실제 표본을 보고 무단으로 설정을 탐색하지 않는다.
- `geometry`에는 `pixels_per_mm`, 그 상대 오차 범위 `scale_relative_error`, `reference_revision`, `pose_revision`, `planar_region_confirmed`를 선언한다. 배율·기준·자세가 불명확하거나 평면 근사가 확인되지 않으면 보류한다. 피부 곡률을 자동 보정하지 않는다. 명목 거리 `pixel_offset / pixels_per_mm`와 선언한 배율 오차로 계산한 거리 구간을 함께 기록한다.
- `review`에는 검수자, 평탄한 조명·같은 자세 확인, 원본 소유자와 media 자체 권리 근거를 넣는다. 기존 RGB 수집기의 개체·피부·건조·선명도·노출/화이트밸런스 고정 조건도 그대로 적용한다. 권리 또는 촬영/기하 조건이 미확인인 입력은 원본 픽셀을 읽기 전에 제외한다. 선언은 독립 검증을 의미하지 않는다.

```bash
# PC 연결 없이 현재 Mac에서 실행할 수 있다. 선언한 호스트가 실제 호스트와 같아야 한다.
python -m behavior_recorder.appearance_texture --plan texture-plan.json --output texture-v1.json --execution-host MacBook-Pro.local
```

측정 전에 기존 RGB PNG/JPEG·마스크·방향·프로파일 검사를 재사용하고, 원본에서 다시 계산한 색 특징이 저장된 값과 같은지 확인한다. 기존 수집기 코드를 바꾸지 않기 위해 같은 검증된 바이트를 질감 계산 시 한 번 더 디코딩하는 절충을 택했다. 파일은 각각 16MiB, 영상은 4메가픽셀 이내로 제한한다. 원본을 수정·재인코딩·리사이즈하지 않는다. 작은 합성 입력의 CPU 실행만 검증했으며 4메가픽셀 최대 입력의 성능은 아직 측정하지 않았다.

산출물은 원본/마스크·관측·계획·측정 코드 해시, 사용한 Python/NumPy/Pillow 버전, 방향별 측정값, 제외 사유, 비교 그룹과 `available_at`을 가진다. 코드·런타임 버전도 비교 그룹에 묶어 서로 다른 구현의 값을 자동 혼합하지 않는다. 비교 그룹에는 기존 색 관측 조건과 배율·자세·추출 설정이 포함되므로 조건을 바꾼 값을 같은 시계열로 자동 합치지 않는다. `available_at`은 촬영, 원래 색 특징 생성, 이번 처리 시각 중 가장 늦은 값이다. 나중에 계산한 질감을 이전 예측에 소급 사용할 수 없다. 제외된 자료의 `media_reverified=false`는 기존 파일 명세만 참조했다는 뜻이며 픽셀 재검증 성공으로 세지 않는다. `actual_model_fit=false`, `shedding_prediction=null`, `actuation_allowed=false`를 유지한다.

## 질감 시간 변화와 모델 입력 연결

`appearance_texture_timeline`은 [질감 포함 시계열 계획](examples/appearance.temporal-texture.template.json)의 `textures` 목록을 읽는다. 각 항목은 실제 추출 계획 `plan`, 추출 산출물 `artifact`, 그 파일 바이트의 `sha256`이다. null 해시·빈 주기 예시는 학습 준비가 아니다. 기존 색상 전용 계획은 이 필드 없이 그대로 사용한다.

같은 개체·몸 부위·촬영 조건에 대해 배율·자세·추출 설정·기록된 Python/NumPy/Pillow·추출기 코드까지 같은 비교 그룹만 연결한다. 직전 확인 탈피 완료 이후의 과거 관측만 사용하고, `max_gap_hours`를 넘는 관측 공백에서 이력을 끊는다. 산출물 해시, 원래 색 관측/입력/파일 명세, 검수 조건, 방향별 측정과 요약값의 일관성을 검사한다. 이 단계는 원본 픽셀을 다시 측정하지 않으며 해시는 기록의 독립적인 실행 인증이 아니다.

질감 처리 시각이 색 관측보다 늦으면 행의 `as_of`를 실제 가용 시각으로 늦춘다. 같은 시각을 기준으로 이전 탈피 이후 경과 시간과 탈피 시작까지의 정답 구간을 다시 계산한다. 이미 탈피가 시작된 뒤 생성된 특징에는 탈피 전 정답을 붙이지 않는다. 선택형 행동·온습도 산출물도 늦춰진 `as_of`와 정확히 일치해야 하므로 예전 anchor를 그대로 재사용하면 거절된다. 과거 질감도 해당 시점까지 실제로 가용했던 것만 사용한다.

모델에서 선택할 수 있는 질감 특징은 다음과 같다. 이 값들은 공학적 후보이며 검증된 탈피 지표가 아니다.

- `texture_mean_absolute_difference`, `texture_rms_difference`: 현재 피부 공간 대비.
- `texture_absolute_delta`, `texture_rms_delta`: 적격 과거 관측 중앙값 대비 변화.
- `texture_absolute_rate`, `texture_rms_rate`: 직전 적격 관측 대비 촬영 시간당 변화.
- `texture_history_hours`, `texture_observation_age_hours`: 비교 이력 길이와 촬영부터 특징 가용 시각까지 경과 시간.

결측·제외·비교 이력 없음은 null로 보존하며 선택한 특징이 없으면 학습 행 제외 또는 예측 보류로 처리한다. 질감 없는 cohort에 질감 특징을 넣거나 문맥 없는 cohort에 온습도·행동 특징을 넣으면 거절한다. 질감 버전은 `past-only-reviewed-srgb-texture-v1`, 문맥까지 결합한 버전은 `past-only-reviewed-srgb-context-texture-v1`이다. 평가 계획에도 같은 버전을 지정하고 기존 `appearance_predictor fit/score`를 사용한다. 소스·코드 변경 전의 고정 cohort/모델을 덮어쓰거나 새 revision으로 검증했다고 간주하지 않는다.

목록은 최대512개, 추가 메타데이터는 참조 색 관측 재읽기를 포함해8MiB, 시계열 출력4MiB, 전체 cohort 메타데이터32MiB로 제한한다. 새 합성 검사27개와 변경된 공유 경로의 기존 통합 검사3개가 Mac CPU에서 통과했다. 입력 픽셀·처리 시각·주기 정답은 모두 명시적 합성 fixture다. 실제 관측 학습·생물학적 성능·물리 제어는0이며, [08 검증 기록](data/appearance-texture-temporal-20261107-08/completion-review.json)을 따른다.

## 고정 간격 알림 평가 — Mac CPU 소프트웨어 검증 완료

`behavior_recorder.appearance_alarm_evaluation`은 주기당 한 시점 평가와 별도로, 사전 지정한 개체·평가 기간·간격의 **모든 예정 예측**을 평가한다. Mac CPU에서 합성 검사 25개가 통과했다. 아래 실행기가 만든 로그도 같은 평가기로 연결할 수 있다. 실제 개체 자료와 생물학적 승인 기준 검증은 남아 있으며 소프트웨어 검사를 실제 성능으로 세지 않는다.

[계획 템플릿](examples/appearance.alarm-evaluation.template.json)에 같은 고정 모델, 학습 종료/fit cutoff, 한 가지 평가 역할, 개체 분리 방식, 알림 범위와 최소 선행 시간을 고정한다. 템플릿의 24시간 간격·48시간 범위·6시간 선행은 형식 예시이며 생물학적 권고가 아니다. null과 빈 입력은 실제 근거로 채우기 전 거절된다. 타임라인은 기존 검수 산출물에서 재생성해 해시·내용을 대조한다. 계획·원자료·코드가 달라지면 기존 고정 설계를 재사용할 수 없다.

```bash
# PC 미확정 작업과 독립적으로, 현재 Mac에서 CPU 검증 경로를 사용한다.
python -m behavior_recorder.appearance_alarm_evaluation freeze --plan alarm-plan.json --output alarm-design-v1.json --execution-host MacBook-Pro.local
python -m behavior_recorder.appearance_alarm_evaluation evaluate --plan alarm-plan.json --design alarm-design-v1.json --predictions alarm-predictions.json --output alarm-report-v1.json --execution-host MacBook-Pro.local
```

- 설계는 `animal_id:index`인 `decision_id`와 `scheduled_at` 전체 목록을 생성한다. 예측 파일은 `schema_version=1`, `kind=appearance_alarm_predictions`, `dataset_kind`, 같은 `model_id`, 설계 파일 바이트의 `design_sha256`, `rows`를 가진다. 각 행은 `decision_id`, `issued_at`, `features_available_at`, `hours_until_start`, `probability_onset_within_horizon`을 가진다. 시간 예측은 **발행 시각부터**의 시간이다. 원래 관측 시각 기준 출력과 혼동하지 않는다.
- 특징은 예정 시각까지 가용해야 하며 예측 발행은 예정 시각 이전일 수 없다. 미제출·명시적 null·허용 지연 초과를 구분한다. 실제 발행 시각으로 정답 범위와 선행 시간을 계산한다. 늦은 예측에는 실시간 성공 점수를 주지 않는다. 모델 ID와 기록 시각의 일치만으로 실제 실행·시계 정확성을 증명하지 않는다.
- 미관측 구간은 음성이 아니다. 음성에는 `negative_windows`의 `record_id`, `animal_id`, `kind=confirmed_no_onset`, `start_at`, `end_at`, `available_at`, `observer`, `evidence_reference`가 필요하다. 이 기록은 사람이 연속 확인했다고 선언한 범위이며 자동 관찰 증명이 아니다. 전체 예측 범위를 끊김 없이 덮어야 하고, 시작·불확실 이벤트와 충돌하면 거절한다. 확인 시각이 label cutoff 이후이면 사용하지 않는다.
- 다음 탈피 시작 구간 전체가 예측 범위 안에 있고 완료까지 확인됐을 때 양성으로 평가한다. 경계에 걸친 시작, 진행 중 탈피, 미연결·미확정 이벤트는 보류한다. 한 알림은 가장 가까운 다음 주기 하나에만 대응한다.
- 예정 시점에서 허용 지연과 최소 선행 시간을 확보할 수 있었던 주기를 분모로 삼는다. 예측을 모두 누락해도 그 주기를 성공 분모에서 빼지 않고 놓친 주기로 센다. 촘촘하지 않은 일정·넓은 정답 구간 때문에 기회 자체가 없었던 주기는 `uncovered_cycles`로 별도 보고한다. 개체별 예정 UTC 날짜의 오경보 수와 확인된 음성 예측 수·누락도 함께 낸다. 누락·보류·지연·정답 미확인 비율을 오류율과 함께 읽어야 한다.
- 간격 기준선의 기간은 학습 주기만 사용한다. 개인화는 마지막 학습 간격, 새 개체는 학습 개체들의 중앙값이다. 이후 알려진 완료 이벤트는 경과 시간만 재설정한다. 같은 유효 예측 시각의 공통 평가 행도 별도로 비교한다. 실제 확률이 제공된 행만 Brier 점수·구간별 관측 빈도를 계산하며 시간 예측을 확률로 바꾸지 않는다.

입력은 최대 16개 타임라인, 8,192개 예정 시점, 1,024개 명시적 음성 검토 구간으로 제한한다. 같은 주기의 반복 예측은 독립 표본이 아니므로 신뢰구간·보정 완료·승격을 주장하지 않는다. `biological_validation_complete=false`, `comparison_criteria_passed=false`, `model_identity_verified=false`, `actuation_allowed=false`를 유지한다. 평가기만으로 공급된 로그의 실제 실행을 인증하지 않으며 아래 로컬 실행 근거도 독립 인증이나 충분한 실제 주기를 대체하지 않는다.

## 고정 모델의 예정 시점별 실행과 평가 연결

`behavior_recorder.appearance_alarm_runner`는 완성된 `appearance_predictor` 실행의 모델·입력·코드 해시를 검증하고 **정답 없는 미래 일정**을 별도로 고정한다. [실행 계획 템플릿](examples/appearance.alarm-runner.template.json)의 시간·간격·유효기간은 형식 예시다. null 시각과 실제 연결이 확인되지 않은 개체 ID는 준비 상태이며 실제 평가 전에 근거와 함께 정해야 한다. 시각 순서는 자료의 `fit_cutoff` ≤ 실제 학습 실행 완료 ≤ 일정 고정 < 첫 예정 시점이다. 평가기에도 같은 학습 완료 시각을 사용한다.

```bash
# 현재 Mac의 기존 가상환경. 미래 일정 고정은 한 번만 수행한다.
.venv-vision/bin/python -m behavior_recorder.appearance_alarm_runner freeze --plan runner-plan.json --schedule schedule-v1.json --execution-host MacBook-Pro.local
# 해당 슬롯이 도래했을 때 한 번 호출한다. 실행 시각을 지정하거나 소급하는 옵션은 없다.
.venv-vision/bin/python -m behavior_recorder.appearance_alarm_runner issue --plan runner-plan.json --schedule schedule-v1.json --inputs live-inputs.json --decision crested-01:0 --execution-host MacBook-Pro.local
# 이후 정답 검토를 고정한 평가 설계로 내보낸다. 일정·모델·평가 정책이 같아야 한다.
.venv-vision/bin/python -m behavior_recorder.appearance_alarm_runner export --plan runner-plan.json --schedule schedule-v1.json --evaluation-plan alarm-plan.json --design alarm-design-v1.json --output alarm-export-v1 --execution-host MacBook-Pro.local
.venv-vision/bin/python -m behavior_recorder.appearance_alarm_evaluation evaluate --plan alarm-plan.json --design alarm-design-v1.json --predictions alarm-export-v1/predictions.json --output alarm-report-v1.json --execution-host MacBook-Pro.local
```

`live-inputs.json`은 `{"timelines":[{"plan":"temporal-plan.json","timeline":"timeline.json","sha256":"실제 파일 바이트 SHA256"}]}` 형식이다. 경로는 이 파일 기준의 상대 경로다. 입력을 바꿀 때는 원본을 보존한 새 버전을 사용한다. 기존 검수·시계열 재생성과 일치해야 하며 해당 시점까지 가용한 최신 관측 하나만 선택한다. 같은 촬영 시각의 여러 관측은 모호함으로 보류한다. 최신 관측이 제외됐다고 더 오래된 정상 관측으로 바꾸지 않는다. 학습에 선언된 이미지의 재사용, 다른 역할, 학습 마감 이전 관측, 오래된 관측, 확인된 진행 중·불확실 탈피, 관측 이후 확인된 탈피 완료는 보류한다. 늦게 알려진 사건은 과거 슬롯에 넣지 않는다.

모델 출력은 특징의 `as_of` 기준 시간이다. 실행 완료 시각까지 경과한 시간을 빼서 발행 시각 기준으로 바꾼다. 이미 지난 예측은 0시간의 임박 알림으로 만들지 않는다. 관측 유효기간은 실제 완료 시각에도 검사한다. 예정 시점보다 늦게 완료되면 `late`로 남기고 예측값은 null이다. 확률은 생성하지 않는다.

슬롯마다 SHA256 이름의 디렉터리를 원자적으로 만들고 `started.json`, 선택 특징과 입력 해시, `prediction.json`, `receipt.json`을 보존한다. 일부 실패도 `failure.json`과 함께 남겨 자동 재실행을 막는다. 호출하지 않은 슬롯은 내보내기·평가에서 `missing`이며 실패한 부분 실행은 별도 목록으로 남는다. `execution-evidence.json`은 모델 연결·영수증 해시를 확인한 로컬 근거다. 호스트 시계·사람의 검수·파일 자체를 독립적으로 인증하지 않는다. 과거 실행을 재현해 실시간 성공으로 표시하는 경로는 없다.

이는 수동 또는 별도 승인된 호출자가 슬롯 하나를 실행하는 CLI다. 상주 스케줄러, 사용자 알림 발송, 예측 UI, 분무 제어는 포함하지 않는다. 새 합성 검사 27개와 시각 조건이 바뀐 기존 평가 검사 25개를 Mac CPU에서 확인했다. [09 검증 기록](data/appearance-alarm-runner-20261107-09/completion-review.json)을 따른다. 실제 개체 학습·예측 성능·물리 제어는 여전히 검증되지 않았다.

## 현재 구현

`behavior_recorder.appearance`는 **로컬 관측 수집기**다. 검토한 RGB 원본과 피부 마스크에서 RGB 중앙값·사분위 범위, 채도·명도 중앙값, 선택 픽셀 수, 채널 끝값에 닿은 픽셀 비율을 저장한다. 신경망·카메라·서버·분무기에 접속하지 않는다. 수집 산출물의 `shedding_prediction`은 null, `actuation_allowed`는 false다. 별도 예측 실행기는 구현했지만 실제 자료 학습·생물학적 검증과 운영 예측 UI는 미완료다.

- 개체 ID, 종, 사육장, 촬영 시각, 몸 부위, 카메라·조명·설정·기준판 revision, 검토자를 함께 저장한다. T1 같은 임시 추적 번호를 생물학적 개체 ID로 자동 변환하지 않는다.
- `visible_rgb`와 명시한 sRGB만 색 분석한다. IR/불명 촬영, 미확인 설정·기준판, 자동 노출·화이트밸런스, 개체/피부 영역 불확실, 젖음, 흐림은 `excluded`로 남기고 색 특징을 만들지 않는다.
- 검토자는 마스크가 같은 개체의 같은 몸 부위 피부만 포함하고 배경·물방울·반사·가림 경계를 제외했는지 확인해야 한다. 이 확인과 촬영 조건은 **작업자 선언**이며 소프트웨어가 독립적으로 검증한 사실이 아니다.
- 입력은 단일 프레임 RGB PNG/JPEG와 같은 크기의 8-bit grayscale PNG 마스크다. 마스크의 255만 포함하고 0은 제외한다. 이미지별 16 MiB, 4×1024²픽셀, 최소 피부 64픽셀 제한은 처리 경계이며 생물학적 유효성 기준이 아니다.
- 프로파일이 포함된 이미지, 다중 프레임, 회전 메타데이터를 자동 변환하지 않는다. 기존 NZ MPO 자료의 거절을 완화하는 경로가 아니다.
- 원본/마스크 바이트의 SHA256, 입력 메타데이터 지문과 `dataset_kind`를 보존한다. 출력은 한 번만 생성하며 기존 출력은 덮어쓰지 않는다. 원본은 복사하거나 삭제하지 않으므로 별도로 보존해야 한다.
- 같은 개체·몸 부위·촬영 조건에만 동일한 `comparison_group`이 부여된다. 이것은 비교 대상 구분 키이며 색 보정이나 피부 반사율 측정의 증명이 아니다. 실제 기준판 확인과 카메라 보정은 별도로 필요하다.

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv-vision/bin/python -m behavior_recorder.appearance \
  --input /absolute/path/to/new-observation.json \
  --output /absolute/path/to/new-observation-result.json
```

[색 관측 입력 템플릿](examples/appearance.observation.template.json)을 새 관측 폴더에 복사한 뒤 실제 값을 입력한다. `image`, `mask`는 입력 JSON 폴더 아래 상대 경로다. null/false를 형식상 통과시키기 위해 임의로 채우지 않는다. `observed_at`은 파일 수정 시각이 아닌 확인된 촬영 시각이다. 시계가 동기화되지 않았으면 이후 센서 결합·시간 예측 학습에서 제외하고, 시계 오차를 기록할 수 있는 기존 수집 세션을 함께 보존한다.

[탈피 기록 입력 템플릿](examples/appearance.shedding.template.json)도 같은 명령으로 저장한다. 사람이 본 `started`, `completed`, `uncertain`을 구분한다. 발생 시각을 정확히 모르면 `earliest_at`–`latest_at` 구간으로 기록한다. 잔여 탈피가 있으면 완료로 라벨링하지 않는다. 기존 관리 기록을 참조할 때에는 원래 기록 ID를 `evidence_reference`에 넣되, 기존 `kind=shedding`만 보고 시작·완료를 임의로 정하지 않는다. 이 명령은 운영 DB에 쓰거나 기존 관리 기록을 자동 가져오지 않는다.

## 학습과 평가 순서

1. 개체별 RGB 관측과 사람이 확인한 탈피 시작·완료 구간을 누적한다. 평소 밝아짐·어두워짐, 탈피 전후, 분무 직후 제외 사례를 함께 확보한다. 색 수집을 위해 밤에 조명을 켜는 동작은 추가하지 않는다.
2. 동일 촬영 조건 안에서 개체별 평소 색 분포와 지속적인 색 변화, 변화 지속 시간, 마지막 확인 탈피 이후 경과를 특징으로 만든다. 기존 행동·온습도 기록은 개체/사육장/시각/센서 quality/시계 오차가 맞는 관측만 연결한다. 색상 시계열·간격 기준선은 구현됐고 행동·환경 결합의 Mac CPU 합성 검증은 완료됐고 실제 개체 자료 검증은 남아 있다.
3. 단순한 마지막 탈피 간격 기준선과 색 시계열을 포함한 모델을 비교한다. 실제 반복 주기 수가 확보되기 전에는 다음 탈피 날짜나 확률을 산출하지 않는다. 미확인 기간을 자동으로 '탈피 없음' 정답으로 만들지 않는다.
4. 인접 프레임 무작위 분할 대신 탈피 주기 전체를 시간순으로 분리한다. 개인화 성능은 과거 주기로 학습하고 미래 주기로 평가하며, 새 개체 일반화는 개체까지 분리해 별도로 측정한다. 라벨 확인 구간이 경계에 걸치면 양쪽 학습/평가에 중복시키지 않는다.
5. 개체당 하루 오경보, 놓친 탈피 주기, 실제 선행 시간, 확률 보정, 예측 보류율을 기록한다. 충분한 표본 수와 승인 기준을 평가 전에 정한다. 프레임 수를 독립 탈피 횟수로 세지 않는다. 색 변화가 탈피를 예측하는지는 이 검증으로 판단한다.

## 분무 연동 설계 — 구현·실행 전

예측은 먼저 관리자에게 근거와 불확실성을 보여 주는 권고로 사용한다. 제어기는 색 분류 결과만으로 분무를 늘리지 않는다. 종별로 확인한 사육 프로필, 최신 실측 습도, 마지막 분무 이후의 실제 습도 반응, 환기/건조 구간을 함께 고려한다.

- 분무기의 실제 유량을 측정하고 보정 revision을 기록한다. 작동 초를 검증 없이 mL로 바꾸지 않는다.
- 허용 습도 상한, 최소 분무 간격, 1회·하루 최대량, 건조 구간, 수동 정지와 센서 이상 시 추가 조절 금지를 독립적으로 적용한다. 프로필 미설정·센서 오래됨·예측 보류이면 AI 추가 조절을 하지 않는다. 기존 사육 제어 정책을 임의로 끄지 않는다.
- 권고, 명령 큐 등록, 장치 수신, 실제 분무 수행, 습도 응답을 각각 기록한다. 명령 중복 방지와 재접속 시 지난 권고 재실행 방지를 검증한다.
- 실제 장치 연동은 운영 코드 위치와 프로토콜을 확인한 뒤 별도 구현한다. 이번 작업은 물리 분무나 운영 배포를 하지 않았다.

## 기존 코드와 연결 위치

- `core.py`의 개체·카메라 설정, `records.py`의 센서 원본/quality, `analysis_features.py`의 시계 오차·센서 신선도 검사를 후속 결합에 재사용한다. 기존 manifest와 라벨 스키마는 바꾸지 않았다.
- 로컬 `work/easyrep-overview-20261025/server/habitat/models.py`에는 사육장 단위 `CareRecord.Kind.SHEDDING`이 있다. 개체 ID와 시작/완료 구간이 없는 이 기록을 곧바로 개인별 학습 정답으로 사용할 수 없다. 이는 로컬 사본에서 확인한 구조이며 운영 서버 최신 상태 검증은 아니다.
- 작은 야간 IR 탐지 개선 작업, 봉인된 평가 자료와 새 출처 검색 큐는 유지한다. 색 수집 테스트를 탐지 성능 개선 또는 새 실제 학습으로 집계하지 않는다.

## 근거와 한계

[RSPCA 크레스티드 게코 안내](https://www.rspca.org.uk/adviceandwelfare/pets/other/crestedgecko)는 평소 체색 변화(firing up), 탈피와 적정 습도의 관련성, 과습한 바닥재 문제, 일정하지 않은 탈피 간격을 설명한다. 따라서 색 변화 하나를 확정 탈피 신호로 해석하거나 보편적인 날짜·분무량을 고정하지 않는다. 이 안내 자체가 컴퓨터 비전 탈피 예측의 성능 근거는 아니다.

검증은 합성 피부/배경 픽셀로 입력 처리와 제외·보존 경로를 확인한 단위 테스트다. 실제 개체 색 정확도, 탈피 예측력, 습도 제어 성능은 아직 측정하지 않았다.

## 2026-11-04 연결 대상 확인

사용자는 기존 **분무기**를 탈피 예측 이후의 조절 대상으로 지정했다. 현재 단계는 실제 개체별 자료를 확보해 예측을 검증하는 단계이며, 물리 분무 실행이나 제어 잠금 해제는 수행하지 않았다.

[이번 자료 확인 기록](data/appearance-misting-intake-20261104-01/intake-review.json)에 확인 범위를 남겼다. 제한한 로컬 JSON 검사에서는 실제 색 관측/탈피 이벤트 입력을 찾지 못했다. 이는 전체 디스크에 기록이 없다는 뜻은 아니다. 같은 날 저장된 운영 응답 사본의 1/7/30일 care 집계는 모두 0이고, 개체별 RGB 시계열을 제공하지 않는다. 사육장 단위 센서 기록을 확인된 개체별 탈피 정답으로 대체하지 않는다.

운영 응답 사본에 있는 분무기 항목 3개는 `hardware_not_commissioned`, `observed=null`이었다. 실제 분무기가 있다는 사용자 확인과 소프트웨어의 연결 검증 상태는 별개다. 사본의 작동 상한/간격을 새로운 분무 권고나 유량 보정값으로 사용하지 않는다. 이 확인은 최신 장치의 실시간 점검이 아니다.

첫 대상 개체의 종·개체 ID, 날짜별 RGB 원본 위치, 사람이 확인한 탈피 구간을 연결한 뒤 기존 학습·평가 순서를 적용한다. 기록 위치를 묻는 질문은 야간 IR 탐색 큐를 정지시키지 않는다. 새 모델 학습·생물학적 성능 검증·물리 제어는 아직 0이다.

## 2026-11-04 신규 수집 확정

후속 답변에서 사용자는 **기존 자료가 없으며 새로 수집해야 한다**, 첫 대상은 **크레스티드 게코**라고 확인했다. 위 기록 위치 질문은 해소됐다. [첫 수집 폴더와 절차](data/appearance-collection-series-20261104-01/crested-01/START.md)를 준비했고, 로컬 기록 ID `crested-01`을 예약했다. 이름·실제 개체/사육장/카메라 연결은 아직 미확인이며, 실제 촬영·관측은 0건이다. 템플릿의 null/false를 확인 없이 채우지 않는다.

`behavior_recorder.appearance_series`는 기존 수집기 출력만 명시적으로 읽는 새 기록 점검 명령이다. [범용 manifest 템플릿](examples/appearance.series.template.json)에 한 개체의 결과 파일을 지정하면 시간순 정렬, 촬영 조건별 묶음, 색 제외 사유, 탈피 시작/완료 관측의 누락을 기록한다. 실제/시험 자료, 개체·종·사육장 혼합과 중복 경로/ID/동일 이미지·몸 부위를 거절한다. 입력은 최대 512개, JSON별 64 KiB다. 출력은 덮어쓰지 않는다.

이 점검은 메타데이터/산출물 구조 검사다. 원본/특징 값을 재검증하거나 실제 개체 식별을 증명하지 않는다. 탈피 이벤트를 자동으로 주기끼리 연결하지 않으며, 미관측 구간을 음성으로 만들지 않는다. 촬영 조건이 다른 색을 하나의 기준선으로 합치지 않는다. `training_readiness=not_assessed`, `shedding_prediction=null`, `actuation_allowed=false`를 유지한다. 센서 결합·실제 예측 학습·제어 코드는 추가하지 않았다.

새 기록 기능의 합성 JSON 검사 9개가 통과했다. 기존 수집기의 완료된 7개 픽셀 fixture 검사는 반복하지 않았다. 9개는 생물학적 성능이나 실제 수집 개체 수가 아니다. 당시 배터리 59% 및 thermal 상태 미확인으로 영상 처리·모델 실행·전체 회귀 검사는 수행하지 않았고, 표준 라이브러리의 짧은 CPU 검사만 실행했다.
