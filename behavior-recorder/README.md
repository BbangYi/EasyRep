# EasyRep 행동 데이터 수집기

영상·센서·사람의 관찰 기록을 보존하고, 도마뱀 감지·추적 및 행동·탈피 관련 모델을 실험하는 프로그램입니다. 웹·서버 API는 [상위 프로젝트](../README.md)의 `web/`에서 관리합니다.

## 현재 범위

- **수집:** 저장이 끝난 영상 구간의 체크섬·프레임 시각을 검사하고, 센서·열화상·수동 라벨과 함께 보관·내보냅니다.
- **감지·추적:** 여러 탐지 모델과 추적 백엔드를 비교할 수 있습니다. 사진 개발 평가와 일부 영상 실험을 수행했으며, 실제 사육장·야간·Pi 실시간 성능은 별도 검증이 필요합니다.
- **행동 분류:** 사람이 검토한 추적 시간창으로 이동·휴식을 학습·평가하는 v1과 로컬 라벨 UI가 있습니다. 실제 행동 성능은 아직 측정하지 않았습니다.
- **탈피:** 관찰 일지·색 특징 수집·검수·예측 실행기와 관련 학습 실험이 있습니다. 크레스티드 게코의 반복 촬영·확인된 탈피 날짜를 결합한 예측 성능과 실제 분무 제어는 검증하지 않았습니다.

미검출·가림·불확실한 구간을 휴식이나 정상으로 바꾸지 않습니다. 합성 테스트, 반복 사용한 개발 자료, 다른 종의 실험 결과를 현장 성능으로 해석하지 않습니다.

## 주요 진행

날짜는 작업 묶음의 기록 시점이며, 각 항목이 운영 배포를 뜻하지는 않습니다.

- **2026-10월 — 수집·탐지·추적 기반:** 파일 수집·복구·이동, 수동 라벨, 공개 사진 학습과 영상 추적을 연결했습니다. 꼬리 누락·번호 단절과 새 영상 비교 등 세부 실험은 참고 문서로 묶었습니다.
- **2026-10월 말~11월 초 — 관찰·탈피 파이프라인:** 사진 없이도 관찰 이력을 기록하는 일지, 검수·시계열 연결, 예측 실행·예정 시점 평가 경로를 추가했습니다. 소프트웨어 검증과 실제 생물학적 예측 검증은 별개입니다.
- **2026-11월 — 모델 학습 확대:** 탐지 본체의 실제 학습·회귀 비교와 탈피 관련 외부 자료의 학습·평가를 수행했습니다. 탈피 실험에는 다른 종·작성자 보고값·이미지가 아닌 측정값을 쓴 경우가 있어 사용자 개체에 적용할 성능 근거는 아닙니다. 전체 목표와 운영 적용은 미완료입니다.
- **통합 시점의 추가 구현 — 행동 분류 v1:** 이동·휴식 라벨과 추적 특징을 연결하고, 학습·평가 간 같은 녹화 기록의 중복을 차단합니다. 실제 라벨 데이터로 성능을 확인하는 단계는 남아 있습니다.

## 시작하기

아래 명령은 이 폴더에서 실행합니다. 기본 파일 수집기는 Python 3.10 이상과 `ffmpeg`·`ffprobe`를 사용합니다. 화면 재생에는 `ffplay`도 필요합니다. AI 분석은 별도 의존성과 모델 파일이 필요합니다.

```sh
python3 -m behavior_recorder --help

# 2초 합성 영상으로 파일 수집을 확인합니다. 실제 동물 관측이 아닙니다.
# 같은 출력 경로를 재사용하지 마세요.
python3 examples/make_test_input.py data/inbox
python3 -m behavior_recorder start data/demo --config examples/config.test.json
python3 -m behavior_recorder record data/demo --config examples/config.test.json --once
python3 -m behavior_recorder verify data/demo
python3 -m behavior_recorder stop data/demo
```

영상 AI의 기본 환경 점검:

```sh
python3 -m venv .venv-vision
.venv-vision/bin/python -m pip install -r requirements-vision.txt
.venv-vision/bin/python -m behavior_recorder.vision doctor
```

위 설치만으로 모든 실험 백엔드가 준비되지는 않습니다. 결합 모델의 추가 의존성은 `requirements-hybrid.txt`와 모델별 설정을 확인하세요. **일부 소형 학습 계수만 포함하며, 대형 가중치·학습 데이터·로컬 평가 영상은 제외합니다.** [모델 목록과 보관 안내](../models/README.md)를 참고하세요.

기존 Mac 실행 환경에서는 `zsh "Start Vision Lab.command"`로 관찰 실험실, `zsh "Start Appearance Journal.command"`로 관찰 일지를 엽니다. 수집기의 POSIX 파일 잠금 때문에 Windows 직접 수집은 지원하지 않습니다. 모델 학습용 Windows 환경과 수집기 실행 환경은 구분합니다.

## 행동 분류 v1

사람이 전 구간을 명시적으로 라벨한 창만 사용합니다. `training.examples.json`과 `heldout.examples.json`은 서로 다른 `recording_id`의 실제 기록으로 준비해야 합니다.

```sh
python3 -m behavior_recorder behavior-fit training.examples.json behavior-model.json
python3 -m behavior_recorder behavior-evaluate \
  behavior-model.json heldout.examples.json behavior-evaluation.json
```

창·라벨에서 예제를 만드는 `behavior-examples` 명령과 입력 형식은 아래 참고 문서에 있습니다. 이 분류기는 자세·수면·스트레스·질병 진단기가 아닙니다.

## Pi와 서버 연결 전

현재 수집 입력은 `finalized_file`입니다. 수집 시작이 카메라 촬영 시작을 의미하지 않으며, USB/CSI/RTSP 생산자는 별도로 연결해야 합니다.

먼저 실제 카메라의 짧은 영상 한 구간으로 시각·프레임 누락·개체 식별·저장·복구를 확인합니다. 이어 서버 API 수신·DB 저장·화면 반영을 확인해야 합니다. Pi 하트비트만으로 영상이나 센서가 최신이라고 판단하지 않습니다.

## 검증과 상세 문서

```sh
# 선택한 테스트에 필요한 의존성이 갖춰진 환경에서 실행합니다.
python3 -m unittest discover -s tests -v
```

전체 테스트에는 AI 의존성과 호스트 자원 조회 권한이 필요한 항목이 있습니다. 일부 테스트 통과만으로 전체 모델·장치 검증 완료를 뜻하지 않습니다.

- [상세 사용법·입력 계약·이전 실험 기록](REFERENCE.md)
- [모델·학습 파이프라인](AI_PIPELINE.md) · [AI 검증 기록](AI_VERIFICATION.md)
- [관찰 일지·색 특징·탈피 관련 구현](APPEARANCE.md)
- [수집기 검증 기록](VERIFICATION.md) · [대표 모델 결과](../models/RESULTS.md)

상세 문서의 `data/` 링크는 원래 로컬 연구 산출물을 가리키며, 공개 저장소만으로 열리지 않습니다. 과거 실험의 수치·미구현 표시는 해당 기록 시점에 한정됩니다.
