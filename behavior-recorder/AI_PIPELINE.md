# 행동·환경 이상탐지 모델 구성

> 이 문서는 기존 화면 변화량 통계 기준선입니다. 2026-10-14 추가된 크레스티드 게코 검출기 학습·추적 CLI는 [README의 실제 영상 모델](README.md#실제-영상-모델)을 사용합니다. 아래 합성 결과는 실제 동물 모델의 학습 성과가 아닙니다.

수집기 위에 **특징 추출, 정상 기준 모델 학습, 이상 점수 추론, 독립 세션 평가**를 추가했습니다. 새 Python 패키지나 GPU가 필요하지 않습니다. 실제 행동 데이터는 아직 0건이며, 제공된 모델은 합성 영상으로 학습한 실행 검증용 모델입니다.

최종 목표는 개체·시간대·환경에 맞는 행동 이상탐지입니다. 이번 기준 모델은 그 목표를 위한 **화면 움직임·환경의 통계 학습 기준 모델**입니다. 화면 변화량을 개체의 실제 이동거리나 특정 행동으로 해석하지 않습니다. 별도로 2026-11-25 `tracked_behavior_centroid_classifier`를 추가했습니다. 이는 사람 라벨이 전체를 덮는 관측 가능 시간창의 이동 특징만으로 상태를 분류하는 보수적 v1이며, 실제 개체 행동 라벨로 아직 학습·평가하지 않았습니다. 탐지기와 별도이며 질병·스트레스·수면 진단 모델은 아닙니다.

행동 분류기는 `moving`·`resting`처럼 사람이 명시한 상태만 학습합니다. 검출 누락, 가림, 부분 가시성, 미라벨 창은 `resting`으로 채우지 않고 `unobserved`로 보류합니다. 학습과 평가는 반드시 서로 다른 기록 그룹으로 분리합니다. 자세·이미지 기반 행동 모델은 권리와 라벨이 확인된 시간 순서 원본이 확보된 뒤 이 v1과 별도로 비교합니다.

Vision Lab의 행동 상태 기록 v1은 이 계약을 그대로 적용합니다. `moving`·`resting`은 사람이 전 구간을 보고 확실히 판단한, 추적 품질 `usable` 창에만 저장됩니다. 가림·추적 단절은 `unobservable`로 감사 이력에 남고 학습 예제가 되지 않습니다. 현재 라벨은 `/api/behavior-labels`에서 recorder 호환 형식으로 확인할 수 있으며, 라벨 입력 자체는 실제 행동 모델 학습이나 생물학적 검증이 아닙니다.

## 지금 실행되는 구조

```text
종료된 recorder 세션 + 사람이 검토한 구간 라벨
    |
    | ai features: 원본 해시 검사, ROI, 64x48 회색조, 1~4 fps 표본
    v
특징 JSON: 화면 변화량 + 선택 센서값 + 품질 + 원본/세션/개체 ID
    |
    | ai train: 정상 확인 구간만 사용, 학습과 보정 세션 분리
    v
model.json: 중앙값/MAD/허용 변동폭/임계점 + 학습 이력
    |
    | ai infer: 동일 개체/카메라/설치/context/전처리인지 확인
    v
점수, 판단 보류 사유, 주요 변화 특징, 지속 이상 후보, 근거 영상 구간
    |
    | 사람이 원본을 재생하고 assessment 라벨을 추가/수정
    v
새 버전 특징·모델 생성 + 미래 시점의 별도 세션으로 ai evaluate
```

추론 명령은 모델이나 정답을 수정하지 않습니다. 경고를 그대로 정상/이상의 학습 정답으로 재사용하지 않습니다.

## 1. 합성 데이터로 전체 실행

프로젝트 디렉터리에서 실행합니다. 기존 환경의 Python과 FFmpeg만 필요합니다.

```sh
python3 examples/make_anomaly_demo.py data/ai-example-01
```

12초, 64×48, 4 fps 합성 영상 6개를 만들고 수집·라벨·특징 추출·학습·추론·평가를 실행합니다. 출력 경로가 이미 있으면 새 경로를 사용하세요. 카메라·네트워크를 사용하지 않으며 실시간 72초 동안 녹화하는 작업이 아닙니다.

```text
data/ai-example-01/
  sessions/synthetic-0 ... synthetic-5/  # 기존 수집기 형식, 원본 영상과 라벨 포함
  features.config.json
  training.features.json               # 앞선 두 세션, 24개 1초 구간
  calibration.features.json            # 다음 두 세션, 24개 정상 구간
  test.features.json                   # 마지막 두 세션, 24개 구간
  model.json                           # 학습된 매개변수, 실행 가능한 JSON 모델
  predictions.json                     # 점수, 원본 위치, 판단 보류/이상 후보
  evaluation.json                      # 독립 평가와 고정 임계값 기준선 비교
  summary.json
```

데모의 움직이는 사각형은 실제 개체가 아닙니다. 정상·이상 라벨은 합성 fixture의 동작을 나타냅니다. 현재 보관된 실행 결과는 [data/ai-demo-v2/](data/ai-demo-v2/), 근거는 [AI_VERIFICATION.md](AI_VERIFICATION.md)입니다.

명령을 개별 실행할 수도 있습니다.

```sh
python3 -m behavior_recorder.ai features \
  data/ai-example-01/sessions/synthetic-0 data/ai-example-01/sessions/synthetic-1 \
  --config data/ai-example-01/features.config.json \
  --output data/ai-example-01/training-v2.features.json

python3 -m behavior_recorder.ai train \
  --training data/ai-example-01/training-v2.features.json \
  --calibration data/ai-example-01/calibration.features.json \
  --output data/ai-example-01/model-v2.json

python3 -m behavior_recorder.ai infer \
  --model data/ai-example-01/model-v2.json \
  --data data/ai-example-01/test.features.json \
  --output data/ai-example-01/predictions-v2.json

python3 -m behavior_recorder.ai evaluate \
  --model data/ai-example-01/model-v2.json \
  --data data/ai-example-01/test.features.json \
  --baseline-motion-threshold 0.05 \
  --output data/ai-example-01/evaluation-v2.json
```

## 2. 실제 데이터 준비

카메라가 준비되면 기존 파일 수집 계약으로 짧은 구간을 저장합니다. real 세션의 `animals`에는 실제 개체 하나를 등록하고 종을 확인 전이면 `unknown`으로 둡니다. 예시 ID를 실제 개체 식별자로 오해하지 마세요.

첫 버전은 한 사육장의 단일 개체를 전제로 합니다. 여러 개체가 있는 경우 개체별 추적이 없으므로 특징 추출을 거절합니다. 영상에서 개체 ID를 판독하는 방식이 아니라 설정된 소속을 보존하는 방식입니다.

정상 기준으로 쓸 구간은 사람이 영상을 확인한 뒤 명시적으로 표시합니다. **미라벨, 가림, 불확실한 구간은 정상으로 채우지 않습니다.**

```sh
python3 -m behavior_recorder label data/session-01 CLIP_ID \
  --animal animal-01 --start 0 --end 60 \
  --visibility visible --certainty certain --assessment normal \
  --annotator operator-01 --note '해당 맥락에서 기준으로 사용 가능한 관측 구간 확인'

# 실제로 확인한 변화가 있을 때만 anomaly로 표시합니다.
python3 -m behavior_recorder label data/session-01 CLIP_ID \
  --animal animal-01 --start 60 --end 90 \
  --visibility visible --certainty certain --assessment anomaly \
  --annotator operator-01 --note '관측 근거와 환경 변화 기록'

# 판단할 수 없으면 uncertain. 행동명과 이상 여부는 별개입니다.
python3 -m behavior_recorder label data/session-01 CLIP_ID \
  --animal animal-01 --start 90 --end 120 \
  --visibility partial --certainty uncertain --assessment uncertain \
  --annotator operator-01 --note '가림으로 판단 보류'

python3 -m behavior_recorder stop data/session-01
```

`normal`은 운영자가 이 모델의 기준 관측으로 검토했다는 뜻입니다. 의학적 건강 판정이 아닙니다. `moving` 같은 행동 라벨만 붙어 있으면 이상 여부는 미판정입니다. `--assessment`는 별도 필드이며 기존 라벨 파일도 계속 읽을 수 있습니다.

한 특징 구간 전체가 동일 개체의 `visible/certain` 평가로 덮여 있어야 학습 정답이 됩니다. 라벨 사이 공백, 서로 다른 평가의 겹침, 가림·불확실성은 제외됩니다. 기존 라벨을 수정할 때는 `--supersedes LABEL_ID`로 이력을 남기세요. **서로 반대인 라벨을 겹쳐 추가하는 것은 수정이 아닙니다.**

## 3. 특징 설정

[features.example.json](examples/features.example.json)을 복사해 실제 개체·카메라 ID와 맞춥니다. 기본값은 **30초 구간 / 2 fps / 전체 화면**입니다.

```sh
cp examples/features.example.json local.features.json
```

- `context`: 운영자가 구분한 주간/야간/조명 조건 등의 식별자입니다. 자동 시간대 분류는 없습니다. `day`와 `night`는 별도 모델로 학습합니다. 한 세션에 서로 다른 조건을 임의로 같은 context로 넣지 마세요.
- `roi`: `[x, y, width, height]`를 화면 크기의 0~1 비율로 지정하거나 `null`로 전체 화면을 사용합니다. 설치와 ROI가 바뀌면 새 기준을 학습합니다.
- `window_seconds`: 1~120초. 데모만 1초를 쓰며 실제 기본값은 30초입니다. 짧은 구간 수만 늘려 충분한 날짜·상황을 관측한 것처럼 판단하지 않습니다.
- `sample_fps`: 1~4. 원본 PTS는 수집기에 보존되고, AI 입력은 첫 PTS 기준으로 재표본한 파생 영상입니다. 각 파생 프레임이 원본 촬영 프레임 하나와 정확히 대응한다고 주장하지 않습니다.
- `pixel_delta`: 움직임으로 셀 픽셀 밝기 차이. 기본 20/255이며 개체 검출 신뢰도나 실제 이동거리 단위가 아닙니다.

기본 특징은 연속 표본 사이의 평균 화면 변화량(`motion_mean`), 구간 내 최대 변화량(`motion_peak`), 변화 픽셀 비율(`changed_fraction`), 평균 밝기(`brightness_mean`)입니다. 광량, 분무, 사람이 화면을 가린 경우도 값을 바꿀 수 있으므로 경고는 검토 후보입니다.

극단적인 노출, 큰 화면 밝기 급변, 원본 PTS 이상, 표본 부족, 구간 끝의 불완전한 창, 사람이 기록한 가림은 별도 품질 사유로 남기고 점수 계산을 보류합니다. 정지 영상은 동물의 정지와 카메라 프리즈를 구분할 수 없으므로 자동으로 수면·정상·장애로 라벨링하지 않습니다.

센서가 필요하면 [features.with-sensors.json](examples/features.with-sensors.json)을 참조합니다. 원본 센서 로그를 먼저 기존 `sensors` 명령으로 가져옵니다. 설정의 센서 ID·단위·revision을 실제 구성에 맞춰야 합니다.

센서 결합은 구간 종료시각 이전의 가장 최근 관측만 사용합니다. 미래 관측, 오래된 값, 잘못된 단위/revision, invalid 값, 같은 시각의 중복 관측, 알 수 없는 시계 정확도는 값을 채우지 않습니다. 마지막 invalid 관측을 건너뛰고 오래된 valid 값으로 대신하지 않습니다. 카메라와 센서의 보고된 오차 합이 `max_clock_error_ms` 이내여야 결합합니다. 이는 보고값 검사이며 실제 시계 정확도 측정을 대신하지 않습니다.

센서 `scale_floor`는 단위에 맞는 최소 변동폭입니다. 예시 0.2°C/1%RH는 초기 설정값으로, 장비 해상도·노이즈를 측정한 뒤 정해야 합니다. 센서가 없으면 `sensors: []`로 동작합니다. 수치 열화상 배열은 수집·보존만 하고 이 모델의 특징에는 아직 사용하지 않습니다.

## 4. 분할·학습 규칙

이번 평가 목적은 **동일 개체의 이후 시점, 처음 보는 세션에서의 성능**입니다. 따라서 개체는 동일하게 유지하면서 세션·연속 녹화·원본은 나눕니다. 다른 개체에도 적용 가능한 모델을 평가하려면 별도의 개체 분리 프로토콜과 모델이 필요합니다.

1. 시간순으로 앞선 여러 세션을 학습용으로 선택합니다.
2. 그 이후의 별도 정상 세션을 임계값 보정용으로 선택합니다.
3. 마지막 별도 세션을 평가용으로 보관합니다. 평가 결과를 보고 모델을 바꿨다면 그 평가 세트는 개발용으로 사용한 것이므로 최종 평가는 새로운 세션이 필요합니다.

`session_id`, `recording_id`, `original_video_id`가 분할 사이 하나라도 겹치면 학습/평가를 거절합니다. 복사·이동으로 ID가 보존된 동일 자료도 차단합니다. 같은 원본 창을 다시 넣거나 창을 겹쳐 표본을 늘리는 것도 막습니다. 영상 재인코딩 시에는 원본 바이트 해시가 달라지므로 기존 `recording_id`를 유지해야 합니다.

real 데이터는 실제 촬영시각이 있어야 앞선 학습·보정과 뒤의 평가를 확인할 수 있습니다. 파일 수신시각으로 대체하지 않습니다. 시각을 아직 얻지 못하는 카메라라면 원본 수집은 가능하지만 real 모델 학습은 보류합니다.

```sh
python3 -m behavior_recorder.ai features data/session-01 data/session-02 \
  --config local.features.json --output data/training.features.json
python3 -m behavior_recorder.ai features data/session-03 data/session-04 \
  --config local.features.json --output data/calibration.features.json
python3 -m behavior_recorder.ai features data/session-05 data/session-06 \
  --config local.features.json --output data/test.features.json

python3 -m behavior_recorder.ai train \
  --training data/training.features.json --calibration data/calibration.features.json \
  --false-alarm-rate 0.05 --consecutive-windows 2 --output data/model-v1.json
```

학습에는 정상으로 검토된 사용 가능 구간 **20개 이상, 세션 2개 이상**이 필요합니다. 보정에도 별도 정상 구간 20개 이상이 필요하며 더 낮은 quantile 목표를 설정하면 더 많은 구간을 요구합니다. 이는 계산을 시작하는 하한이며 실제 일반화 성능에 충분한 데이터량이라는 뜻이 아닙니다. 종·개체·주야·환경 변화의 범위를 실제로 관측해야 합니다.

## 5. 무엇을 학습하는가

각 특징에 대해 학습 정상 구간의 중앙값과 MAD를 구합니다. MAD는 중앙값에서 얼마나 흩어져 있는지 나타내는 값입니다. 최소 허용 변동폭을 적용해 정상 표본이 모두 같은 값이어도 0으로 나누거나 미세한 차이만으로 점수가 폭증하지 않게 합니다.

```text
center = median(training_normal_feature)
scale = max(1.4826 × median(abs(value - center)), scale_floor)
score = max(abs(new_feature - center) / scale)  # 모든 선택 특징 중 최대
```

중앙값·scale은 학습 데이터에서만 결정합니다. 임계값은 별도 정상 보정 데이터의 상위 점수와 최소값 3을 사용합니다. `--false-alarm-rate`는 보정 quantile을 고르는 목표값이며 **실제 오탐률 보장이 아닙니다.** 시간적으로 상관된 창, 환경 변화, 적은 세션으로 인해 실제 오탐률은 달라집니다.

이 모델은 단순 규칙에 고정 숫자만 넣은 파일이 아니라 데이터로 학습한 기준을 저장합니다. 다만 특징 간 복잡한 상호작용·다봉 분포·장기 행동 순서는 학습하지 않는 작은 통계 모델입니다. 딥러닝 행동 인식 모델로 표현하지 않습니다.

## 6. 추론·검토·재학습

```sh
python3 -m behavior_recorder.ai infer --model data/model-v1.json \
  --data data/new-session.features.json --output data/predictions-v1.json
```

결과 상태:

- `within_reference`: 현재 특징이 학습 기준 안에 있음. 건강/정상 행동 확정이 아닙니다.
- `elevated`: 임계값을 넘었으나 설정한 지속 조건에 아직 도달하지 않음.
- `alert`: 같은 clip에서 연속 구간이 임계값을 넘음. 기본 2개 창이며 30초 설정에서는 최소 약 60초의 관측이 필요합니다.
- `insufficient_data`: 품질/결측 때문에 판단 보류. score는 null입니다.

점수는 이상일 **확률이 아닙니다.** 결과에는 가장 크게 변한 특징 3개, 그 값과 학습 중앙값, 원본 ID/clip ID/구간이 포함됩니다. 끊긴 창·품질 보류·clip 경계에서 지속 카운트가 초기화됩니다. 첫 버전은 clip 사이의 지속 상태를 연결하지 않습니다. clip 길이가 지속 조건보다 짧으면 경고가 나올 수 없으므로 설정을 확인하세요.

```sh
# predictions.json의 session_id를 가진 로컬 세션과 clip_id/start를 선택합니다.
python3 -m behavior_recorder replay data/new-session CLIP_ID --start 30 --seconds 30 --window

# 확인 후 label --assessment 명령으로 정답/불확실성을 기록합니다.
# 수정 라벨이 있는 세션은 features를 새 파일로 다시 추출합니다.
# train을 새 모델 파일 이름으로 실행하고, 보지 않았던 후속 세션으로 평가합니다.
```

평가 명령은 학습/보정 데이터와 원본이 겹치면 실행되지 않습니다. 추론 명령은 과거 자료 진단에도 사용할 수 있으나 그 출력만으로 일반화 성능을 계산하면 안 됩니다.

평가 결과에는 window precision/recall, 정상 창 오탐률, 검토 구간 대비 계산 가능 비율, 판단 보류 건수, 이상 episode 탐지율과 지연, 정상 관측 시간당 오탐 이벤트가 포함됩니다. 분모가 없으면 null입니다. 판단 보류된 이상 구간도 event recall 분모에는 남습니다. 미검토 경고 수는 별도로 표시합니다.

`--baseline-motion-threshold`는 같은 지속 조건을 적용한 고정 화면 변화량 기준선입니다. 기본 0.05는 비교 실행을 위한 임의의 시작값이며 생물학적 안전 기준이 아닙니다. 현장 비교에서는 평가 세트를 보기 전에 기준을 정하세요. 짧은 합성 구간에서 계산된 시간당 수치를 실제 운영 시간당 오탐 예측으로 사용하지 마세요.

## 7. 저장·이동·한계

특징·모델·결과는 JSON이며 pickle이나 실행 코드를 로드하지 않습니다. 내용 fingerprint를 검사하고 새 결과 파일을 원자적으로 게시하며 기존 파일을 덮어쓰지 않습니다. fingerprint는 우발적인 수정 검사이며 서명/출처 인증이 아닙니다.

원본 데이터와 모델을 다른 폴더로 옮겨도 session/clip/recording/original ID가 유지됩니다. `media_path`는 원본 세션에 대한 상대경로입니다. 결과 파일만으로 임의의 PC에서 세션 폴더 위치를 찾아내지는 않으므로 재생 시 로컬 세션 경로를 지정하세요. 원본 recorder ZIP과 특징/모델/보고서 JSON을 함께 복사하면 됩니다. 새 데이터 수집에는 해당 장치의 카메라/inbox 설정이 별도로 필요합니다.

`test` 모델은 `real` 특징에 적용되지 않습니다. real 모델도 처음에는 `unvalidated_research_baseline`, `production_validated=false`로 남습니다. 이 버전에는 검증 없이 운영 적합 상태로 바꾸는 명령이 없습니다.

Mac에서 합성 영상으로 검증했습니다. Pi/Linux 실행, 실제 동물·센서·카메라 조건, 장기 운전, 개체/행동 인식, 열화상 특징, 실시간 알림·제어·온라인 재학습은 아직 검증하거나 구현하지 않았습니다. 로컬 수집·파일·수동 라벨 계약은 유지했습니다.

다음 현장 작업은 **카메라 10초 구간으로 시야·PTS·촬영시각·ROI·부하를 확인하는 것**입니다. 그 뒤 같은 개체의 여러 날짜 정상·검토 대상 구간을 모아 이 기준 모델의 실제 오탐을 측정합니다. 객체/행동 모델을 추가할지는 그때 화면 변화 특징이 놓치는 사례를 근거로 결정합니다.

## 참고

- [FFmpeg fps/scale/crop 필터](https://ffmpeg.org/ffmpeg-filters.html): 영상 표본 추출에 사용합니다.
- [NIST의 강건한 산포 측정](https://itl.nist.gov/div898/handbook/eda/section3/eda356.htm), [GSL의 scaled MAD 정의](https://www.gnu.org/software/gsl/doc/html/statistics.html): 중앙값/MAD 기준을 참고했습니다.
- [scikit-learn의 그룹·시간순 평가 설명](https://scikit-learn.org/stable/modules/cross_validation): 누수 방지 원칙을 참고했습니다. scikit-learn은 설치하거나 런타임 의존성으로 추가하지 않았습니다.
