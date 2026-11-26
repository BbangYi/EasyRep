# 매장 Pi와 보드 프로그램 안내 — HabitatOS 0.4.29

이 폴더에는 **매장의 Raspberry Pi가 센서와 카메라 데이터를 모으고, IR 조명을 제어하는 프로그램**이 있습니다. 센서·카메라 보드의 펌웨어와 별도 GPU PC에 계산을 요청하는 코드도 함께 관리합니다.

처음 읽을 때는 세 가지를 구분하면 됩니다.

- **Pi 프로그램:** 장치의 데이터를 받아 저장하고 SaaS 서버에 전달합니다.
- **보드 펌웨어:** ESP32 보드 안에서 실행되며 센서를 읽거나 카메라 영상을 만듭니다.
- **설정 파일:** 매장·장치 ID, 연결 주소, 사용할 핀 등 설치 장소에 따라 달라지는 값을 담습니다.

모든 매장은 같은 버전의 소스를 사용하고 설정으로 차이를 구분합니다. SaaS 웹 프로그램은 [../web/](../web/)에 있으며, Pi와 별도로 설치·실행합니다. GPU 계산도 별도 GPU PC에서 실행합니다.

[구조](#1-데이터가-흐르는-순서) · [코드 위치](#2-코드-위치-찾기) · [장치 없이 시작](#3-장치-없이-코드부터-확인하기) · [펌웨어](#4-보드에-넣을-프로그램-준비하기) · [매장 설치](#5-실제-매장에-설치하기) · [설정·모델](#6-설정모델실행-결과-보관하기)

## 1. 데이터가 흐르는 순서

```text
온습도 센서 → BB6 센서 보드 ─┐
                            ├→ Pi → SaaS → 브라우저
RGB 카메라 → DFR1172 보드 ───┘

IR 켜기·끄기: 브라우저 → SaaS → Pi → BB6 → IR 조명
```

BB6와 Pi는 **MQTT**라는 메시지 통신 방식을 사용합니다. Pi는 어떤 매장과 사육장의 장치가 보냈는지 확인한 뒤 데이터를 처리합니다. 카메라 영상은 등록된 주소에서 받아 전달합니다. TOP·FRONT 역할은 등록 정보로 구분하며 USB 연결 순서로 정하지 않습니다.

## 2. 코드 위치 찾기

| 폴더·파일 | 여기서 찾을 수 있는 내용 |
|---|---|
| `habitat_gateway/` | Pi 프로그램 시작, MQTT 수신, 데이터 저장, API와 카메라 화면 |
| `habitat/vision/` | 장치 ID로 카메라 찾기, 영상 받기, 연결 복구 |
| `habitat/saas/` | Pi와 SaaS 사이의 영상·데이터 전송 규격 |
| `habitat/control/`, `apps/worker/ir_*.py` | IR 명령 처리와 제어 프로그램 |
| `firmware/cage_node/` | BB6 센서·IR 공통 펌웨어 |
| `firmware/camera_node/main.py` | MicroPython으로 동작하는 기존 카메라 프로그램 |
| `firmware/camera_node/h264_node/` | ESP32-P4에서 H.264 영상을 만드는 펌웨어와 빌드 도구 |
| `habitat/digital_twin/air/` | 온도센서 값으로 사육장 내부의 온도 분포 추정 |
| `habitat/compute/` | Pi가 GPU PC에 계산을 요청하고 결과를 확인하는 코드 |
| `habitat/gpu/`, `apps/api/` | GPU PC에서 실행할 API와 작업 처리 코드 |
| `experiments/environment_sim/` | 합성 환경 데이터 생성, MLP 학습·추론·평가 |
| `config/`, `configs/` | 설정 예제, 기본값, 설정 형식 정의 |
| `deploy/` | 설치 파일 만들기, 장치 설정, 업데이트와 복구 |
| `tests/`, `docs/` | 자동 시험, 연결 규격, 설치·운영 설명 |

API는 프로그램끼리 요청과 결과를 주고받는 창구를 뜻합니다. 사용할 주소와 데이터 형식은 관련 문서에 정의되어 있습니다.

## 3. 장치 없이 코드부터 확인하기

아래 명령은 **Linux 또는 Raspberry Pi OS의 터미널** 기준입니다. Python 3.11 이상이 필요합니다. 저장소의 최상위 폴더에서 시작합니다.

```bash
cd gateway
```

이후 명령은 모두 `gateway/` 안에서 실행합니다. 먼저 이 프로젝트 전용 Python 가상환경을 만들고 필요한 라이브러리를 설치합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e '.[test,simulation]' --no-deps
.venv/bin/python -m pip install 'pytest>=8,<10' 'jsonschema>=4.23,<5' 'numpy>=2,<3'
```

`.venv/`는 이 프로젝트의 Python과 라이브러리를 보관하는 폴더입니다. `requirements.lock`에는 Pi에서 사용할 라이브러리 버전이 적혀 있습니다. API·GPU용 잠금 파일은 각각의 실행 환경에 맞춰 별도로 사용합니다.

**`gateway/`와 `web/server/`는 별도 가상환경을 사용하세요.** 두 프로젝트에는 이름이 같은 서로 다른 `habitat` 패키지가 있어 한 환경에 설치하면 충돌할 수 있습니다.

### 설정 파일 검사

```bash
.venv/bin/python -m habitat_gateway --config config/simulation.toml --check-config
```

시뮬레이션 예제 설정을 읽고 형식이 올바른지 검사합니다. 성공하면 출력 JSON에 `"valid": true`가 표시됩니다. 서버를 시작하거나 실제 센서·조명을 작동시키지 않으므로 첫 확인 단계로 사용할 수 있습니다.

### 자동 시험

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider
python3 -B tests/hardware/check_cage_node.py
```

첫 명령은 Python 코드의 시험을 실행합니다. 두 번째 명령은 C++ 컴파일러로 보드 코드의 일부 동작을 가상 입력에 대해 검사합니다. 실제 보드에 연결해 센서값이나 조명 출력을 확인하는 시험은 별도입니다.

시험 종류에 따라 FFmpeg(영상 처리), C++ 컴파일러, cJSON 헤더·라이브러리, Chromium(브라우저)이 필요합니다. 해당 도구가 없는 시험은 제외될 수 있으므로 결과의 통과·실패뿐 아니라 제외 사유도 확인하세요.

## 4. 보드에 넣을 프로그램 준비하기

**빌드**는 소스 코드로 보드용 실행 파일을 만드는 작업입니다. **업로드**는 만든 파일을 실제 보드에 기록하는 작업입니다. 두 단계는 따로 진행합니다.

| 대상 | 안내 | 확인할 내용 |
|---|---|---|
| BB6 센서·IR 보드 | [BB6 빌드 안내](firmware/cage_node/README.md) | 공개 예제 설정으로 컴파일하며 실제 출력은 잠긴 상태입니다. |
| ESP32-P4 카메라 | [H.264 펌웨어 안내](firmware/camera_node/h264_node/README.md) | 지정한 개발 도구와 라이브러리로 빌드합니다. |
| 기존 MicroPython 카메라 | [새 매장 설치 안내](docs/operations/new-store-setup.md) | `deploy/camera_node.py`로 제조사 이미지와 Microdot 파일의 해시를 확인합니다. |

해시는 파일 내용으로 계산하는 식별값으로, 준비한 파일이 예상한 파일과 같은지 확인할 때 사용합니다. 제조사 MicroPython 이미지와 Microdot 파일은 외부에서 준비하는 자료이며 이 저장소에는 포함하지 않았습니다.

2026년 11월 26일 소스 통합 당시 확인한 구성은 다음과 같습니다.

- FRONT는 카메라에서 H.264로 압축한 영상을 보내고 Pi가 재압축 없이 전달했습니다.
- TOP(`RGB-001`)은 H.264 전환 시험 중 영상 수집 시간 초과가 발생해 기존 MicroPython 프로그램으로 복원했습니다.

따라서 두 카메라가 현재 같은 펌웨어를 사용하는 것으로 가정하면 안 됩니다. Pi는 등록된 두 입력 방식을 처리할 수 있습니다. 새 보드에는 해당 보드의 실제 영상 수신까지 확인해야 합니다.

## 5. 실제 매장에 설치하기

처음 설치하는 경우에는 [새 매장 설치 안내](docs/operations/new-store-setup.md)를 따릅니다. 이미 운영 중인 Pi를 갱신할 때는 [Pi 업데이트 기록과 절차](docs/operations/pi-update.md)를 먼저 확인합니다. IR 연결은 [IR 통신 규격](docs/protocols/ir-control.md), SaaS 연결은 [카메라·IR API 안내](docs/api/camera-ir-integration.md)에 설명되어 있습니다.

배포 파일이 필요할 때 다음 명령을 사용합니다. 첫 명령은 전달용 소스 묶음을 만들고, 두 번째 명령은 설치에 사용할 라이브러리까지 포함한 Pi용 묶음을 만듭니다. Pi용 묶음은 설치 대상과 CPU 종류 및 Python 주·부 버전이 같은 환경에서 만듭니다.

```bash
.venv/bin/python deploy/build_release.py --source-handoff --output /tmp/habitatos-source-release
.venv/bin/python deploy/build_release.py
```

파일을 만드는 명령만으로 운영 서비스가 설치되거나 재시작되지는 않습니다. 설치할 때 실제 매장 설정과 장치 연결 상태를 확인하는 단계가 이어집니다. IR은 설정·권한·BB6 배선이 갖춰져야 동작하며, 펌프와 R15 확장은 설치·검증 완료로 가정하지 않습니다.

## 6. 설정·모델·실행 결과 보관하기

실제 매장 설정은 `/etc/habitat-gateway/`와 사용자별 `.config/habitatos/` 등 소스 밖의 경로에 보관합니다. Wi-Fi·MQTT 암호, API·IR 키, TLS 개인 키, 장치별 `config.h`·`config.json`과 전체 플래시 백업은 Git에 올리지 않습니다. 저장소의 설정 파일에는 실제 값 대신 예제가 들어 있습니다.

열역학 모델은 가정한 물리 조건과 센서값으로 공간 온도를 추정합니다. MLP는 합성 데이터로 학습한 환경 예측 모델이며, 현재 최종 가중치와 학습 보고서는 원본 확인 대기입니다. [열역학 모델 안내](../models/thermal-air/README.md)와 [MLP 안내](../models/environment-mlp/README.md)에서 입력·출력과 현재 준비 상태를 확인할 수 있습니다.

영상, 데이터베이스, 모델 평가 결과, 캐시, 배포 파일은 실행용 경로에 보관합니다. 기존 `First_Connection_R1`의 8092 수신기, 날짜별 전달본, `/opt/habitat-gateway/current`의 설치 결과를 별도 개발 소스로 관리하지 않습니다.

과거 운영 문서는 그 시점의 기록입니다. 일부 `var/reports/` 자료, 외부 도구, 문서 첨부 파일과 Fritzing 원본은 이 공개본에 포함되지 않았습니다. 현재 소스를 확인하려면 이 README에 적힌 빌드·시험 명령부터 사용하세요.
