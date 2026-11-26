# 저장소 구조와 배포 경계

2026-11-26 통합 기준. 기존 `web/`, `behavior-recorder/`, `models/`의 소유 책임을
유지하고 HabitatOS 공개 소스를 `gateway/`에 추가한다. 매장별 소스 복사본은 만들지 않는다.

| 위치 | 책임 | 실행 대상 |
|---|---|---|
| `web/standalone/`, `web/server/` | 계정·매장·사육장, 센서 이력, 카메라/IR 인증 중계 | SaaS 서버·브라우저 |
| `web/server/edge/` | Pi 데이터의 SaaS 수신·저장·조회 | SaaS 서버 |
| `gateway/habitat_gateway/` | MQTT 수집, 로컬 저장, API, 카메라 화면·송출 | 매장 Pi |
| `gateway/habitat/control/` | IR 등 장치 제어·응답·유효 시간 관리 | 매장 Pi |
| `gateway/habitat/vision/` | 카메라 ID 발견, 입력 수신, 재연결 | 매장 Pi |
| `gateway/habitat/digital_twin/air/` | 센서로 보정하는 물리 기반 공간 온도 추정 | 매장 Pi |
| `gateway/habitat/compute/`, `habitat/gpu/` | Pi의 GPU 요청, 별도 GPU API·추론 작업 | 각각 Pi / GPU PC |
| `gateway/experiments/environment_sim/` | 합성 환경, MLP 학습·추론·평가 | 모델 학습·평가 환경 |
| `gateway/firmware/cage_node/` | ESP32 센서 입력·IR·로컬 안전 처리 | BB6 등 Cage Node |
| `gateway/firmware/camera_node/` | 공통 MicroPython 프로그램과 P4 H.264 펌웨어 | DFR1172 |
| `behavior-recorder/` | 완성된 영상 파일의 기록·행동 분석 | 분석 실행 환경 |
| `models/` | 모델 출처·가정·검증 범위와 확정된 배포 자산 | 모델 관리 |

## 소스와 설정

`gateway/`는 현재 Pi·GPU 공통 Python 프로젝트의 경계다. 배포 도구와 GPU API가
기존 상대 경로로 펌웨어·환경 모델 코드를 찾으므로 첫 통합에서 내부 경로를 옮기지 않는다.
IR은 BB6 센서 펌웨어와 Pi의 기존 제어 모듈에 포함한다. TOP·FRONT는 카메라 공통
프로그램에 ID·역할 설정을 적용한다. 보드별 GPIO와 매장·사육장 매핑은 설정으로 관리한다.

`gateway/config/`, `gateway/configs/`에는 공개 기본값·예제·스키마만 포함한다.
실제 인증정보와 매장 설정은 설치 대상의 외부 경로에 둔다. 기존 MQTT·HTTP 계약과
장치 ID를 소스 통합만으로 바꾸지 않는다. Pi와 SaaS의 계약 구현은 기존 모듈을 사용하고
양쪽 계약 시험으로 호환성을 확인한다.

`gateway/`와 `web/server/`의 `habitat`는 서로 다른 Python 패키지다.
가상환경과 작업 디렉터리를 분리한다. 기존 Pi 운영 설치 경로
`/opt/habitat-gateway/current`는 Git 저장소 배치와 별개이며 이 통합으로 변경하지 않는다.

## 실행·검증·배포

- Gateway: `cd gateway`, 별도 Python 환경에서 `pip install -c requirements.lock -e '.[test,simulation]'`,
  `python -B -m pytest -q -p no:cacheprovider`. 설치·업데이트·복구는 기존 `deploy/`를 사용한다.
- SaaS: `web/README.md`와 `web/server/docs/web-api.md`를 따른다. Gateway를 SaaS의 Python 환경에 설치하지 않는다.
- BB6: `gateway/firmware/cage_node/README.md`의 공개 예제 빌드를 사용한다.
  이 검증 도구는 실사용 설정을 읽거나 장치에 업로드하지 않는다.
- P4 H.264: `gateway/firmware/camera_node/h264_node/README.md`의 잠긴 의존성과 빌드 도구를 사용한다.
- MicroPython: 제조사 이미지와 Microdot은 기존 프로비저닝 도구가 검증하는 외부 의존이다.
  저장소에는 애플리케이션 소스·설정 예제·검증 절차를 포함한다.

각 구성요소에서 버전이 있는 배포물을 만들고 대상 장치의 설정과 결합한다.
Git push와 PR 병합은 실물 펌웨어 업로드·서비스 적용을 자동으로 뜻하지 않는다.
웹 운영 번들과 이 저장소의 소스가 일치하는지 배포 담당자가 대조한 뒤 적용한다.

## 열역학·MLP 모델

공간 온도 추정과 열부하 설계 계산은 학습 가중치가 없는 모델이다.
`models/thermal-air/`는 정본 코드·설정·가정을 연결한다. 현재 공간 추정 모델은
20×20×30cm 조건을 갖고 있으며 임의 크기의 사육장 정확도가 검증된 모델은 아니다.

`models/environment-mlp/`는 합성 데이터 기반 MLP의 코드와 예상 최종 파일을 명시한다.
GPU 데스크탑의 `model_1sensors.npz`, `model_2sensors.npz`, `model_3sensors.npz`,
`training_report.json`을 확보한 후 보고서의 가중치 해시·학습 소스·설정 출처를 대조한다.
검증 전 가중치 해시나 모델 버전을 추정하지 않는다. 현재 이 네 파일은 미포함이다.
검증한 최종 자산만 버전 디렉터리 또는 GitHub Release로 게시하고 manifest를 갱신한다.
GPU 실행은 `HABITAT_ENV_MODEL_DIR`로 설치된 모델 위치를 선택한다.

## 통합에서 제외한 항목

실제 `config.h`·카메라 설정·Wi-Fi/MQTT/API/IR 키, 개인 키, 전체 플래시 백업,
운영 DB, `var/`, 가상환경, 의존성 캐시, 영상, 중간 학습 체크포인트, 임시 빌드 결과는
포함하지 않는다. 과거 전달 ZIP과 8092 수신기를 별도 정본으로 추가하지 않는다.
개발·시험 출력은 Git에서 제외된 실행 경로를 사용한다.

`SOURCE_SNAPSHOT.json`의 Gateway 파일 수와 해시는 선별한 소스 범위를 기록한다.
과거 운영 문서의 검사 결과는 해당 시점의 기록이며 현재 운영 검증 결과로 합산하지 않는다.
