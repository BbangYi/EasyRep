# EasyRep

SaaS, 매장 Pi Gateway, 센서·IR·카메라 펌웨어, 열역학·환경 예측과 행동 분석을
함께 관리하는 저장소입니다. 각 구성요소는 별도 실행 환경과 배포 단위를 사용합니다.

- [`web/`](web/): 웹 화면과 `server/`의 Django API
- [`gateway/`](gateway/): Pi 수집·제어·영상 송출, GPU 연동·추론 API, 보드 펌웨어와 배포 도구
- [`behavior-recorder/`](behavior-recorder/): 카메라·감지·추적·행동 분석 코드와 테스트
- [`models/`](models/): 기존 행동 분석 모델, 열역학 모델 명세, 환경 MLP 원본 확보 상태

[저장소 구조와 배포 경계](docs/repository-layout.md)를 먼저 참고하세요.
`gateway/`와 `web/server/`는 서로 다른 `habitat` Python 패키지를 가지므로
각각 별도 가상환경에서 실행합니다. 저장소에 함께 있다는 이유로 같은 프로세스에
설치하거나 SaaS·GPU를 매장 Pi에서 모두 실행하지 않습니다.

각 구성요소의 설치·실행 방법은 해당 폴더의 README를 참고하세요.
웹의 소스 검사는 `cd web && npm ci && npm run test:source`,
AI 프로그램 검사는 필요한 의존성을 설치한 환경에서
`cd behavior-recorder && python -m unittest discover -s tests`로 실행합니다.

## 포함 범위

2026-11-25 웹·행동 분석 소스 모음에 2026-11-26 HabitatOS 0.4.29의 공개
소스·테스트·예제 설정을 `gateway/`로 통합했습니다. 기존 프로젝트 내부의
상대 경로와 패키지명은 보존했습니다. `SOURCE_SNAPSHOT.json`에 출처와 범위를 기록합니다.
기존 코드의 HabitatOS 내부 패키지명·환경변수·프로토콜 이름은 호환성을 위해 유지합니다.
저장소의 서비스 이름은 EasyRep입니다.

비밀정보, 운영 DB, 가상환경, 빌드 결과물, 원본 영상·학습 데이터,
대형 모델 바이너리는 제외했습니다. 포함한 소형 학습 계수와 필요한 추가 파일은 `models/`에서 확인할 수 있습니다.
환경 MLP의 학습·추론 코드는 포함되어 있지만 최종 `.npz` 가중치와 학습 보고서는
GPU 데스크탑 원본 확인 대기입니다. `models/environment-mlp/manifest.json`의
`complete_inference_bundle=false`를 모델 설치 완료로 해석하지 않습니다.
문서의 `data/` 링크 중 로컬 연구 산출물을 가리키는 링크는 이 저장소만으로 열리지 않습니다.

[우리 파트 설계 초안](docs/EasyRep_민우파트_설계초안.drawio)은 2026-10-22 작성한 편집 가능한 도식이며, 현재 운영 구성의 검증 자료는 아닙니다.

## 검증 범위

이 저장소는 소스 통합본이며 운영 배포나 실제 장치 성능을 보증하지 않습니다.
라즈베리파이 연결 후 인증된 API 수신, DB 저장, 화면 반영을 새 센서 샘플로 확인해야 합니다.
하트비트와 실제 센서 입력의 최신성은 별도로 확인합니다.
