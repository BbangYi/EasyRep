> 소스는 `Desktop/HabitatOS` 단일 프로젝트에서 관리합니다. 현재 실행·배포 시작점은 [README](../README.md)와 [Pi 운영 안내](operations/pi-update.md)입니다. 아래 날짜별 검증 기록은 과거 상태로 구분하며 배포 패키지는 새 배포 때만 생성합니다.

# 매장별 Raspberry Pi 배포

각 매장 Pi에는 같은 HabitatOS 게이트웨이 프로그램을 설치합니다. 매장별로 달라지는 것은 `site_id`, `gateway_id`, 사육장·장치 목록, 제어 설정, 인증정보입니다. 현재 실제 검증 대상은 `STORE-001 / PI-001`이며 다른 매장 Pi의 설치까지 검증한 결과는 아닙니다. `STORE-002 / PI-002`는 설정 생성·배포 목록 검증용 예제입니다.

이 배포 기능은 Pi 프로그램의 설치와 업데이트를 담당합니다. Pi의 SaaS 이벤트 송신은 [연동 규격](saas-integration.md), GPU 작업 클라이언트는 [운영 설정](operations/compute-client.md)을 따릅니다. 기본 시험 예제는 시뮬레이션을 사용할 수 있지만, 현재 설치된 Pi의 transport는 **MQTT**입니다. GPU 서버·ESP32 펌웨어의 소프트웨어 검증과 실제 장치 조립·시운전은 구분합니다.

## 현재 Pi 배포 — 2026-10-20

Pi 운영 릴리스는 `0.4.15-e724b3a0b4e4`, 복구용은 `0.4.14-5a9bc13f4f2f`다.
별도 인증 카메라 뷰어와 HLS를 배포했으며 GPU·ESP32는 변경하지 않았다.
[실제 배포 기록](operations/hardware-arrival.md#standalone-camera-20261020)을 따른다.
0.4.15 빌더는 개인 `config.h`와 firmware 빌드 산출물을 제외한다. 설치기는 공개
코드 준비에 umask 022를 쓰고 호출자의 umask를 복원하여, 비공개 백업의 077과
서비스가 읽어야 하는 릴리스 파일 권한을 구분한다.

## 이전 배포 확인 — 2026-10-07

실제 Pi 운영 릴리스는 **`0.4.14-5a9bc13f4f2f`**, 직전 복구용은 `0.4.13-a1337300e296`이며 GPU 운영 소스도 0.4.14입니다. Pi health `ok`·MQTT 연결, Pi 핵심 파일 7개·GPU 파일 9개의 해시 일치와 기존 설정·인증정보·모델 보존을 확인했습니다. [Pi 확인](../var/reports/commissioning/software-r15-20261007-pi-014.json), [GPU 확인](../var/reports/commissioning/software-r15-20261007-gpu-014.json), [current/previous 확인](../var/reports/commissioning/software-r15-20261007-integration.json)을 근거로 합니다.

관련 Linux 선택 검사 208개·하위 사례 141개와 환경 API 검사 3개·하위 사례 38개가 통과했습니다. 실제 Pi→GPU CUDA 통합 모의실험은 가상 120분·360응답·75가상 펌프 실행 후 OFF·밸브 없음·`idle`로 종료했습니다. [검사 범위](../var/reports/commissioning/software-r15-20261007-checks.json)와 [통합 결과](../var/reports/commissioning/software-r15-20261007-integration.json)는 전체 회귀검사·실물 분무·실측 예측 정확도의 합격 기록이 아닙니다. 신판 ESP32 두 역할의 대상 빌드는 통과했지만 펌웨어 업로드와 실물 ESP/Pico 출력 시험은 하지 않았습니다. 실물 출력 잠금은 유지합니다.

SaaS 하트비트 ACK는 정상이지만 이벤트 연속성은 `blocked`·`cloud_continuity_unverified`입니다. 대기 이벤트 1개와 원래 순번·UUID·본문 해시를 보존했고 이벤트 성공 시각은 `null`, 서버 최고 순번은 미확인입니다. [현재 SaaS 상태](../var/reports/commissioning/software-r15-20261007-cloud.json)를 따르며 배포 성공을 이벤트 전달 완료로 표시하지 않습니다. 이번 전달 파일과 일회성 도구는 [Pi](../var/reports/commissioning/software-r15-20261007-pi-cleanup.json)·[GPU 정리 기록](../var/reports/commissioning/software-r15-20261007-gpu-cleanup.json)에 따라 제거했습니다.

## 저장 위치

| 위치 | 내용 | 업데이트 시 |
|---|---|---|
| `/opt/habitat-gateway/releases/<release-id>/` | 프로그램 wheel, 의존성, 버전별 venv | 새 디렉터리에 설치 |
| `/opt/habitat-gateway/current` | 현재 실행 버전 symlink | 검증한 새 버전으로 전환 |
| `/opt/habitat-gateway/previous` | 직전 성공 버전 symlink | 기존 버전 보존 |
| `/etc/habitat-gateway/gateway.toml` | 해당 Pi의 매장·장치 설정 | 지정한 매장 설정 적용, ID 변경 거절 |
| `/etc/habitat-gateway/gateway.env` | 해당 Pi의 API/MQTT 인증정보 | 기존 값 보존; 최초 API 토큰 자동 생성 |
| `/var/lib/habitat-gateway/gateway.sqlite3` | 로컬 센서·명령·감사 DB | 그대로 유지 |
| `/opt/habitat-gateway/backups/` | 업데이트 직전 DB 백업 | 기존 DB가 있는 경우 생성 |
| `/etc/systemd/system/habitat-gateway.service` | 부팅 시 시작·프로세스 재시작 | 공통 서비스 정의 |

개발자 홈 경로와 사용자명에 의존하지 않습니다. 서비스는 systemd의 DynamicUser와 StateDirectory로 실행하며, 설정·프로그램은 읽고 상태 디렉터리에 기록합니다. DB는 systemd가 관리하는 `/var/lib/private/` 아래를 가리킬 수도 있습니다.

## 매장 설정 생성

```bash
python3 deploy/provision.py \
  --site-id STORE-003 --gateway-id PI-003 \
  --output config/stores/STORE-003.toml
```

새 파일만 생성하며 기존 설정을 덮어쓰지 않습니다. 이 예제는 동일한 가상 사육장 구성을 복사합니다. 실제 설치에는 해당 매장의 cage/node ID, 센서, 장치, 임계값을 반영합니다. 같은 프로그램을 사용해도 매장별 인증키와 DB는 복사·공유하지 않습니다.

API의 기본 주소는 `127.0.0.1:8000`입니다. 필요하면 TOML의 최상위 `[server]`에 `host`, `port`를 지정할 수 있습니다. 외부 인터페이스에서 수신하려면 API 토큰이 필수입니다. 처음에는 loopback과 SSH 터널로 접속합니다.

## 배포 묶음 만들기

```bash
.venv/bin/python deploy/build_release.py
```

`dist/habitat-gateway-<release-id>.tar.gz`와 SHA-256 파일만 생성합니다. 빌드 임시 폴더는 종료 시 삭제합니다. 설치기는 `--archive`로 이 패키지를 직접 받습니다. 프로그램과 고정 버전의 실행 의존성 wheel만 포함하고, 매장 설정·인증키·DB는 포함하지 않습니다. 빌드할 때는 패키지를 다운로드하지만, 대상 Pi에서의 설치는 `pip --no-index`로 수행합니다.

확인한 Pi 릴리스 묶음은 **ARM64(aarch64), Python 3.13**용입니다. 대상은 같은 CPU/Python과 호환되는 Raspberry Pi OS 64-bit 환경이어야 합니다. Python 버전 또는 CPU가 다르면 설치가 거절됩니다. 이 경우 대상 환경과 같은 환경에서 묶음을 다시 만듭니다. 각 Pi에는 Python과 `venv` 지원, systemd가 미리 있어야 합니다.

### 2026-09-18 초기 설치 검증 (과거)

당시 릴리스는 `0.2.0-5d529ac6e1dc`였습니다. 자동 테스트 39개와 임시 경로의 실제 오프라인 설치는 통과했지만, 당시 Pi의 시스템 설치는 `sudo: a password is required`로 실행되지 않았습니다. 이후 설치된 현재 Pi 상태는 위 2026-10-07 기록을 따릅니다. 관리자 비밀번호는 설정 파일이나 배포 패키지에 기록하지 않습니다.

## 신규 설치와 업그레이드 절차

현재 Pi에는 위 릴리스가 이미 설치되어 있습니다. 아래는 새 설치나 후속 업그레이드의 절차이며, 기존 DB·설정·인증정보를 초기화하거나 새 매장 연결을 다시 실행하는 안내가 아닙니다.

새 매장 담당자가 처음 연결할 때는 0.3.2 이상의 릴리스 폴더에서 **`bash connect.sh`**를 실행한다. [매장 담당자용 간단 안내](operations/new-store-setup.md)에 준비물과 입력 순서를 정리했다. 기존 Pi는 신규 연결 마법사 대신 아래 업그레이드 설치 경로를 사용한다.

센서 없이 웹 연결만 유지할 때는 아래의 [heartbeat 사용자 서비스](#센서-없는-pi의-heartbeat-서비스)를 사용한다. 이 절의 기존 시스템 서비스는 센서/시뮬레이터와 로컬 API를 실행하는 전체 Gateway용이다.

프로젝트 폴더에서 다음 명령을 실행합니다.

```bash
sudo python3 deploy/install.py \
  --archive dist/habitat-gateway-<release-id>.tar.gz \
  --config config/stores/STORE-001.toml
```

설치 순서:

1. 릴리스 checksum, CPU/Python, 매장 ID를 검사합니다.
2. 새 버전의 venv에 포함된 wheel을 오프라인 설치합니다.
3. 장치·DB를 시작하지 않는 `--check-config`로 실제 설치본의 설정을 검증합니다.
4. 기존 서비스가 있으면 정지하고 DB를 백업합니다.
5. 매장 설정·서비스와 `current`를 적용하고 새 버전을 시작합니다.
6. 로컬 `/health` 및 인증된 `/v1/gateway`에서 상태·매장·Pi·릴리스가 맞는지 확인합니다.
7. 정상 실행을 확인하면 부팅 시 시작하도록 등록합니다.

새 서비스가 정상 실행되지 않으면 이전 코드 링크·설정·서비스 파일을 복원하고, 이전에 실행 중이었던 서비스를 다시 시작합니다. 첫 설치 실패 시에는 실패한 새 서비스를 정지합니다. 전원 차단 중단까지 복구하는 트랜잭션 설치기는 아닙니다. 현재 DB schema 1만 지원하며, 향후 DB 구조 변경은 별도 migration 계획이 필요합니다.

`systemctl restart`나 업데이트 후에는 제어 모드가 `manual`로 시작합니다. 자동제어 재개는 상태를 확인한 후 명시적으로 수행합니다.

## 설정 검사 오류

2026-09-20 소스 수정부터 gateway CLI는 설정 검사 실패 시 입력 원문이나 traceback 대신 아래 오류 코드를 stderr에 표시하고 종료 코드 2로 끝납니다. 일반 시작과 `--check-config`에 모두 적용되며 이 단계에서는 장치·DB를 시작하지 않습니다. 기존 `dist/0.2.0-*` 및 `dist/0.3.0-011629817059` 묶음에는 이 수정이 포함되지 않습니다.

| 코드 | 확인할 항목 |
|---|---|
| `invalid_gateway_configuration` | TOML 문법, 지원 필드·값 범위, 서버 host/port. SaaS endpoint에는 사용자명·비밀번호·토큰 query를 넣지 않고, 인증값은 설정된 환경변수로 전달 |
| `gateway_configuration_unreadable` | `--config` 경로, 파일 존재 여부와 읽기 권한 |
| `invalid_gateway_credentials` | API·SaaS 토큰 조건과 설정된 환경변수, MQTT 비밀번호 환경변수. 오류에 원문 값을 추가해 출력하지 않음 |

정상 `--check-config`는 기존과 같이 매장/Pi ID·버전·transport·cloud 활성 여부 및 `valid=true`를 JSON으로 반환합니다. 설정 형식과 MQTT/SaaS/GPU API 계약은 바뀌지 않았습니다.

## 상태 확인과 운영

```bash
systemctl status habitat-gateway --no-pager
curl -sS http://127.0.0.1:8000/health
sudo journalctl -u habitat-gateway -n 50 --no-pager
```

`/health`에는 실행 버전과 release ID가 포함됩니다. `/v1/gateway`는 토큰 인증 후 매장 ID, gateway ID, 사육장 목록도 반환합니다. 토큰은 `/etc/habitat-gateway/gateway.env`에 권한 `0600`으로 보관합니다. 설치 과정에서는 토큰을 화면에 출력하지 않습니다.

```bash
sudo systemctl stop habitat-gateway
sudo systemctl start habitat-gateway
```

서비스가 실행 중이면 개발 서버를 같은 포트로 동시에 시작하지 않습니다. 개발 서버는 `--port 8001`과 별도 DB를 사용합니다. 아직 이력 자동 삭제 기능이 없으므로, 장기 운영 전 용량·보존 정책을 추가해야 합니다.

## 센서 없는 Pi의 heartbeat 서비스

0.3.1부터 `--heartbeat-only`를 지원한다. Pi의 전원과 인터넷 연결이 있으면 실제 센서 없이 SaaS와 인증된 주기 통신을 유지할 수 있다. 센서값을 만들어내지 않으며 외부에서 Pi로 들어오는 포트를 열지 않는다. 이 모드는 MQTT·ESP32 연결과 로컬 API를 실행하지 않는다. 현재 Pi는 위의 전체 Gateway 서비스로 운영하며, heartbeat 전용 서비스를 추가로 시작하지 않는다.

사용자 서비스 설치는 관리자 권한 없이 가능하다. 다만 부팅 시 시작하고 로그아웃 후에도 실행하려면 해당 사용자의 systemd **Linger=yes**가 필요하다. `loginctl show-user "$USER" --property=Linger`로 확인한다. 꺼져 있으면 Pi 운영자가 `loginctl enable-linger "$USER"`를 실행한다. 설치 도구는 lingering이 꺼져 있으면 서비스 변경 전에 중단한다.

사용자별 외부 파일·릴리스 경로는 다음과 같다. 모든 Pi에 동일한 프로그램을 설치하고 ID·사육장 정의·목적지만 설정으로 바꾼다.

| 경로 | 역할 |
|---|---|
| `~/.config/habitatos/gateway.env` | 기존 `HABITAT_CLOUD_TOKEN`, 파일 `0600`, 디렉터리 `0700` |
| `~/.config/habitatos/gateway.toml` | 검증 후 적용한 매장/Pi 설정, `0600` |
| `~/.local/share/habitatos/gateway/releases/<release_id>/` | checksum 검증한 릴리스와 전용 venv |
| `~/.local/share/habitatos/gateway/current` | 현재 릴리스; 갱신 시 기존 버전은 `previous`로 보존 |
| `~/.config/systemd/user/habitat-heartbeat.service` | 부팅·로그아웃 후 실행, 실패 시 5초 후 재시작 |

기존 Store TOML에 `[cloud]`를 최상위로 추가한다. 자격증명 파일은 새로 발급하지 않고 기존 토큰을 재사용한다. credential 파일에 쓰는 값은 비밀이며 명령행 인자로 전달하지 않는다.

```toml
[cloud]
enabled = true
endpoint = "https://habitatos.kro.kr/v1/edge/sync"
token_env = "HABITAT_CLOUD_TOKEN"
interval_s = 5
timeout_s = 10
retry_max_s = 60
```

`database` 필드는 기존 설정과 호환되도록 `/var/lib/habitat-gateway/gateway.sqlite3`를 유지한다. heartbeat 모드는 이 DB를 열지 않는다. 기존 사육장 구성은 연결 전의 등록 정보이며 실제 측정을 의미하지 않는다. 프로그램을 source checkout에서 상시 실행하지 않고 다음과 같이 릴리스 묶음을 사용한다.

```bash
.venv/bin/python deploy/build_release.py
python3 deploy/install.py --archive dist/habitat-gateway-<release_id>.tar.gz \
  --config /path/to/reviewed-store.toml --user-heartbeat
```

설치 도구는 저장된 비밀파일 권한, 기존 Pi ID, 묶음 checksum·CPU/Python을 확인한다. 묶음의 wheel만으로 venv를 설치한 후 해당 버전의 `--heartbeat-only --check-config`를 실행하고 서비스·설정을 적용한다. 서비스 시작 실패 시 기존 릴리스 링크·설정·서비스를 복원한다. 정상 시작 후 자동 시작을 활성화한다. 이 시작 검사는 프로세스 확인이므로 아래 ACK 로그로 SaaS 통신도 확인해야 한다.

```bash
systemctl --user status habitat-heartbeat --no-pager
journalctl --user-unit=habitat-heartbeat.service -n 20 --no-pager
systemctl --user is-enabled habitat-heartbeat
```

`Cloud heartbeat acknowledged: site=... gateway=...`는 해당 요청의 HTTP 200뿐 아니라 schema·Pi ID·빈 이벤트 목록 ACK 검증까지 성공했다는 뜻이다. 기본 5초마다 기록되며 로그 보관은 systemd journal 정책을 따른다. 실패에는 `http_401`, `timeout`, `network_error`, `invalid_ack` 등의 오류 코드만 기록하고 간격을 늘려 재시도한다. 토큰을 재발급·변경했다면 외부 credential 파일을 갱신하고 `systemctl --user restart habitat-heartbeat`를 실행한다.

사용자 서비스 로그가 시스템 journal에 기록되는 Pi에서는 `journalctl --user -u ...`가 비어 보일 수 있다. 위의 `--user-unit=habitat-heartbeat.service`로 조회한다.

```bash
systemctl --user stop habitat-heartbeat
systemctl --user start habitat-heartbeat
```

센서/ESP32를 연결해 전체 Gateway로 전환할 때는 먼저 `systemctl --user disable --now habitat-heartbeat`를 실행한다. **같은 Pi ID의 두 송신기를 동시에 실행하지 않는다.** 기존 영속 DB·이벤트 순서를 복구하거나 서버 등록 세대 변경을 합의한 다음 전체 Gateway를 설치한다. heartbeat는 이벤트 순서를 변경하지 않는다. 예제 데이터베이스나 시험용 DB를 확인 없이 새 운영 DB로 간주하지 않는다.

Pi 온라인과 센서 연결은 별도 상태다. 화면의 과거 가상 값이 오래됨으로 표시되는 것은 새 센서 데이터가 없기 때문이다. 네트워크나 전원이 끊기면 Pi도 오프라인이 되며 연결 복구 후 재시도한다. 재부팅 자동 시작 설정은 검증할 수 있지만 실제 재부팅 시험은 운영자가 별도로 수행한다.

### 2026-09-21 heartbeat 전용 적용 기록 (과거)

- 설치 릴리스: `0.3.1-a9fffa62b07d`, ARM64 / Python 3.13. 기존 `build_release.py`로 묶고 `install.py --user-heartbeat`로 저장소 외부에 오프라인 설치했다.
- 대상: `STORE-001 / PI-001 / CAGE-001`, heartbeat 전용. SaaS URL·ID·사육장 정의는 외부 TOML, 토큰은 기존 사용자 전용 `gateway.env`에서 읽는다. 예제의 센서 inventory는 실측을 의미하지 않는다.
- 15:25:19 KST 점검: `ActiveState=active`, `SubState=running`, `UnitFileState=enabled`, `Linger=yes`, 자동 장애 재시작 횟수 0. 직접 서비스 재시작 후 다른 invocation에서 통신 재개를 확인했다.
- 연속 수신: 15:20:19–15:25:18 KST 동안 ACK 60건, 총 298.66초, 간격 5.050–5.096초, sync 오류 0. 각 성공 로그는 HTTP 200과 기존 v1 ACK 검증을 모두 통과한 경우에만 남는다. 점검 종료 후에도 서비스는 계속 실행 중이다.
- 전체 `pytest`: **181 passed**. 로컬 HTTP 수신기를 이용한 503 실패→재시도→복구, 프로세스 재시작, 미접속 센서 상태, 기존 DB 불변성, v1 수신 계약, 설치 실패 시 rollback을 검증했다. 초기 샌드박스의 socket 제한을 벗어난 실행에서 통과했다.
- `systemd-analyze --user verify` 통과. credential 파일 `0600`, 상위 디렉터리 `0700`. 기존 샘플 DB의 측정 3건과 마지막 이벤트 순서 8은 변경되지 않았다.
- 증거: `var/data/heartbeat-service-2026-09-21/verification.json`, `acknowledgments.json`. runtime 산출물이므로 버전 관리 대상이 아니다. 임시 설치 설정은 적용본과 일치함을 확인하고 제거했다.

검증 한계: 실제 재부팅·물리적 인터넷 단절 시험은 수행하지 않았다. 웹 조회 API에는 별도 로그인이 필요하므로 현재 화면의 Pi 온라인 표시는 독립 조회하지 않았다. 앞선 시뮬레이션 데이터 표시 성공은 사용자가 확인했다. heartbeat는 새 센서값·원격 제어·안전 interlock을 제공하지 않으며, 다음 단계는 ESP32 센서 경로를 연결하고 로컬 안전 동작을 검증하는 일이다.

## 새 매장 연결 마법사 (0.3.2)

매장 담당자용 entrypoint는 `connect.sh`이며 Python 프로그램 `connect.py`를 호출한다. `provision.generate_heartbeat`가 입력된 site/gateway/cage ID와 공통 `cloud-defaults.toml`로 설정을 만들고, 기존 `prepare_release`·`install_user_heartbeat`가 릴리스 설치와 서비스를 담당한다. 매장별 코드 복사본이나 별도 송신 구현은 추가하지 않았다.

2026-09-21에 검증한 묶음은 `dist/habitat-gateway-0.3.2-4630f82d864d.tar.gz`와 같은 이름의 `.sha256` 파일이었다. 이 파일명을 현재 배포 명령에 그대로 쓰지 않는다. 새 배포 때는 현행 소스로 만든 `dist/habitat-gateway-<release-id>.tar.gz`와 checksum을 사용한다. 압축 내부에는 실행 스크립트, 설치기, 공통 기본 설정, wheel, `CONNECT.md`가 함께 들어 있다. 담당자는 웹에서 이 Pi에 발급한 ID와 token을 준비한 뒤 압축 폴더에서 `bash connect.sh`를 실행한다. 자동 SaaS 등록/토큰 발급 API는 현재 계약에 없으므로 먼저 웹에서 등록해야 한다. 현재 소스나 다른 매장 토큰을 복사해서 배포하지 않는다.

마법사는 숨김 토큰 입력을 위해 대화형 터미널을 요구하고, 전체 프로그램의 sudo 실행을 거절한다. 필요한 경우 운영체제의 로컬 인증으로 lingering을 활성화한다. 연결 전에는 디스크에 token을 보관하지 않으며, 새 `--check-connection`이 정상 ACK를 받은 뒤에만 사용자 전용 `gateway.env`를 배타적으로 생성한다. 토큰은 명령행 인자로 넘기지 않는다. 기존 사용자 설정·credential·heartbeat unit 또는 시스템 Gateway 설정이 있으면 신규 설치를 거절한다.

heartbeat 설정은 `transport=mqtt`를 선택하되 MQTT를 시작하지 않는다. 새 매장의 시뮬레이션 허용 옵션을 켤 필요가 없다. `UNASSIGNED-*` node ID와 기본 센서/출력 목록은 v1 스냅샷의 비활성 inventory이며 실제 설치를 뜻하지 않는다. 예제 자동제어 정책은 제외한다. 실제 센서 전환 시 inventory·연결·안전 기준을 반드시 별도로 구성한다.

서비스 적용 후 해당 실행 invocation의 `Cloud heartbeat acknowledged` 로그를 확인해야 `CONNECTED`를 출력한다. 별도 연결 확인은 성공했으나 background ACK가 확인되지 않으면 설정·retry 서비스는 보존하고 미확인 상태를 알린다. 토큰/설정 적용 전 실패는 새 credential을 남기지 않으며, 적용 도중 중단되어 설정이 남은 경우 credential을 무조건 삭제하지 않는다. 계정 변경·토큰 교체·업그레이드는 기존 설치 운영 절차를 따른다.

2026-09-21 검증:

- 전체 pytest **194 passed**. 여러 사육장 매핑, 토큰 거절 전후의 파일 상태, 기존 등록 보호, 설치 실패 정리, current invocation의 ACK 확인, 실제 one-shot HTTP 요청과 잘못된 Pi ACK 거절을 포함한다.
- 배포 archive SHA-256·manifest 검증, 공백이 있는 폴더에서 shell launcher 실행, 저장소 외부 임시 경로의 실제 오프라인 venv 설치, 설치된 0.3.2 코드의 실제 HTTP preflight 통과.
- 임시 `STORE-PACKAGE / PI-PACKAGE`, 사육장 2개와 합성 시험 토큰을 사용했다. `events=[]`, `telemetry=null`, device transport 미연결을 확인했다. 실제 SaaS에 새 매장을 등록하거나 현재 운영 credential을 사용한 시험은 아니다.
- 실제 신규 Pi에서의 OS 관리자 인증/부팅과 다른 SaaS 등록의 권한은 그 Pi에서 setup 실행 시 확인해야 한다. 기존 Pi의 0.3.1 heartbeat 서비스는 이번 package 검증에서 변경하지 않았다.
- 결과: `var/data/new-store-setup-2026-09-21/package-verification.json`. 임시 추출·설치 경로는 검증 후 제거했다. 외부 API/MQTT/schema 변화는 없고, `--check-connection` CLI만 추가되었다.

## 다른 매장 Pi 배포

`deploy/inventory.example.json`을 참고하여 `deploy/inventory.json`에 실제 SSH 주소와 설정 경로를 기록합니다. 경로는 inventory 파일 기준입니다. SSH 키 인증, 확인된 host key, 원격 `sudo -n python3` 실행 권한이 필요합니다. 현재 예제 주소에는 연결하지 않았습니다.

```json
[
  {
    "host": "operator@actual-store-pi.local",
    "site_id": "STORE-003",
    "gateway_id": "PI-003",
    "config": "../config/stores/STORE-003.toml",
    "port": 22
  }
]
```

`identity_file`을 추가하면 해당 SSH 키 파일을 지정할 수 있습니다. 비밀번호나 API 토큰은 inventory에 넣지 않습니다.

목록과 설정을 먼저 검증합니다. 이 명령은 네트워크에 접속하지 않습니다.

```bash
python3 deploy/fleet.py --inventory deploy/inventory.json \
  --archive dist/habitat-gateway-<release-id>.tar.gz
```

한 매장부터 적용합니다.

```bash
python3 deploy/fleet.py --inventory deploy/inventory.json \
  --archive dist/habitat-gateway-<release-id>.tar.gz \
  --site-id STORE-003 --apply
```

`--site-id`를 생략하면 목록의 Pi에 **순차 배포**합니다. 중간에 실패하면 다음 매장 배포를 중단합니다. 전송은 SSH/SCP이며, host key 검증을 비활성화하지 않습니다. 각 대상에서 archive checksum과 설치 후 identity/health를 확인합니다.

MQTT 모드는 브로커, ESP32와 해당 Pi의 `HABITAT_MQTT_PASSWORD`를 먼저 준비해야 합니다. 설치 도구가 MQTT 브로커나 GPIO 드라이버를 자동 설치하지는 않습니다.

구현 참고: [systemd 실행 환경](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html), [pip 오프라인 설치 옵션](https://pip.pypa.io/en/stable/cli/pip_install/), [Python tar 추출 필터](https://docs.python.org/3/library/tarfile.html#extraction-filters).

## Pi 공기 온도 화면 (0.4.17 이후)

모델 수식, 실행 코드 대응, 선행 논문·특허 비교와 독립 실측 검증 계획은
[공간 온도 추정 기술보고서](air-temperature-technical-report.md)에 정리했다.

`habitat-air-viewer.service`는 기존 MQTT telemetry/status를 구독하는 별도 로컬 화면이다.
`apps.air`는 설정과 lifecycle만 담당하고, 수신 adapter·온도 추정·HTTP 화면은
`habitat/digital_twin/air/`가 소유한다. 0.4.19부터 시작 시 기존 Gateway의 인증된
기록 조회 API로 최근 측정을 복원한다. Gateway·recorder DB를 직접 열거나 MQTT
명령을 발행하지 않는다. 과거 기록의 출처·측정 시각을 유지하여 표시한다.

사용자가 제공한 `HabitatOS_BB6_Air_Live_R13.zip`
(SHA-256 `dcefc2dbaacba9b555fba5e1d5739f62e944208138219d38ff613aeed711e981`)의
NumPy 모델과 웹 화면을 기존 package로 가져왔다. 원본 ZIP은 보존했다.
실험용 recorder·무제한 CSV 기록·카메라 실행기는 가져오지 않았다.

운영 설정은 `/etc/habitat-air-viewer/air.json`이다. `cage_id`는 기존 gateway TOML에
등록된 cage여야 하며 node ID·MQTT host/port·CA·credential 환경변수는 기존 설정을
그대로 읽는다. systemd가 기존 gateway.env를 읽어 전달하므로 토큰을 새 파일이나
명령행으로 복사하지 않는다. 화면은 자체 DynamicUser로 실행하고 gateway를 재시작하지 않는다.

수신기는 기존 `Telemetry`와 `node_topic`을 재사용한다. 명시적인 sensor source와
정수 schema 1, UUID, 해당 cage의 geometry/placement revision, 유효한 T1/T2/T3 및
gateway 센서 범위를 검사한다. retained·미래 메시지·중복·측정 시각 역순은 새 화면에
사용하지 않는다. 유효하지만 늦게 도착한 측정은 마지막 온도장을 갱신하고
`stale/fresh=false`로 표시한다. 숫자가 같아도 새 ID와 더 최신 측정 시각이면 반영한다.
중복 ID 캐시는 4,096건으로 제한한다. 모델 오류가 발생해도 MQTT
수신 스레드는 유지한다. 실제 수신 메시지 ID는 `/api/air`의 `message_id`에 노출한다.
MQTT wire contract와 기존 SaaS/DB schema는 변경하지 않았다.

화면에는 실측 T1/T2/T3와 3D 공간 추정을 구분해 표시한다. 기본 설정은 ZIP과 같은
20×20×30cm, T1=(10,10,28), T2=(2,2,8), T3=(18,18,8)cm이다. 이 좌표와
0.004m/s 순환은 가정이며 실제 설치 좌표·공간 정확도를 검증한 것으로 해석하면 안 된다.
현재 모델/화면은 이 크기에 한정된다. 온도 입력 범위 예제는 기존 CAGE-001과 같은
−20~60°C이며 사육 적정 온도 기준은 아니다. 갱신 지연 및 모델 재초기화는
`stale_after_s`(기본 30초)를 사용한다. 끊기면 마지막 화면을 흐리게 표시한다.

### 저장 기록 복원과 새 측정 반영 (0.4.19)

`history.py`는 `GET /v1/cages/{cage_id}/telemetry?limit=300`의 기존 계약을 재사용한다.
앱의 `--history-limit`으로 1~1000건을 지정할 수 있고 0이면 복원을 끈다.
기존 gateway TOML의 server host/port와 `HABITAT_API_TOKEN`을 사용하며,
이 기능은 loopback 주소에만 연결한다. API 인증값을 브라우저나 새 설정 파일에
복사하지 않는다. MQTT와 독립된 스레드에서 복원하며 실패한 사육장은 재시도한다.
API 장애나 인증정보 부재가 MQTT 수신을 중단시키지 않는다.

조회 결과는 기존 telemetry 검증을 거쳐 측정 시각 순으로 기존 AirModel에 입력한다.
사육장별 revision과 센서 품질·단위·범위·미래 시각 검사를 유지한다. 원래 메시지 ID와
측정 시각을 보존하고, 큰 측정 간격은 기존 모델의 gap reset으로 처리한다.
복원 도중 더 최신 MQTT 값이 도착하면 늦게 완료된 이력이 화면을 되돌리지 않는다.
기록과 MQTT 양쪽에서 같은 메시지가 도착하면 온도장을 두 번 계산하지 않고 출처와
실제 수신 시각만 전환한다. 기존 오프라인 통지를 기록 복원이 온라인으로 바꾸지 않는다.

로컬 `/api/air`는 기존 schema version 1에 다음 표시용 필드를 추가한다.

| 필드 | 의미 |
| --- | --- |
| `data_origin` | `history`, `mqtt`, `replay`, 또는 측정 전 `null` |
| `history_samples` | 이번 실행에서 복원한 측정 수 |
| `live_samples` | 이번 실행에서 반영한 MQTT 측정 수 |
| `loaded_at` | 마지막 기록을 복원한 시각 |

`accepted_samples`는 중복되지 않은 반영 총수다. 같은 기록이 복원 후 MQTT로도
수신되면 history/live 건수 양쪽에 포함될 수 있으므로 두 건수의 합과 같을 필요는 없다.
`generated_at`은 현재 온도장을 실제 계산한 시각이다. 기존 이력 API는 원래
`received_at`을 제공하지 않으므로 복원 시 `received_at_utc`와 `age_seconds`는
`null`로 둔다. 복원 시각을 센서 수신 시각으로 표시하지 않는다.

복원한 기록은 항상 `fresh=false`이며 `history` 또는 확인된 통신 상태로 표시한다.
현재보다 오래된 유효 MQTT 측정도 표시하지만, 30초 기준을 넘으면 실시간으로
간주하지 않는다. 기존 AirUploader의 live/fresh 조건을 유지하여 복원·지연 온도장이
실시간 추정으로 SaaS에 전송되지 않는다. 원시 센서 로그와 기존 `/v1/edge/sync`의
이벤트 전송에는 이 표시 기준을 적용하지 않는다. MQTT·SaaS 업로드 계약·DB schema는
변경하지 않는다. 이 기능은 최근 기록으로 마지막 화면을 복원하며 전체 이력 시간축
탐색 UI를 추가하는 기능은 아니다.

검증에는 `tests/contract/test_air_history.py`, 기존 AirState/MQTT/업로드/수신기/
통합·배포 검사, `tests/integration/air_viewer_browser.mjs`를 사용한다. 기록 복원·동일 값
신규 측정·지연 측정 표시·오프라인 보관·실시간 전환을 격리된 입력으로 검증한다.

배포는 공통 release builder를 사용한다. 명시적으로 배포할 때만 지정 출력 경로에
묶음을 만들고, 대상 Pi에서 압축을 검증·해제한 release 디렉터리를 설치기에 전달한다.

```bash
.venv/bin/python deploy/build_release.py --with-air --output /tmp/habitat-air-release
sudo python3 deploy/install_air.py /path/to/verified-release
```

오프라인 빌드에는 NumPy wheel까지 포함된 `--wheel-cache`를 지정한다. 설치기는
기존 `verify_release`/`prepare_release`를 재사용하며
`/opt/habitat-air-viewer/releases/<release-id>`와 별도 `current`를 관리한다.
따라서 gateway release 정리가 화면의 실행 파일을 삭제하지 않는다.
기존 air.json은 덮어쓰지 않고, 변경되는 기존 service unit은 백업한다.
HTTP 검증 실패 시 기존 화면 release/unit으로 복구한다. 최초 설치 실패 시 서비스는 중단한다.

Pi 브라우저 주소는 `http://127.0.0.1:8765/`이며 기본적으로 Pi 내부에서만 접속한다.
다른 PC에서 볼 때는 기존 SSH 접속으로 `ssh -L 8765:127.0.0.1:8765 user@pi`를
실행한 다음 그 PC의 같은 주소를 연다. 서비스는 부팅 시 시작하며 자동 장애 재시작한다.
중단은 `sudo systemctl stop habitat-air-viewer.service`로 하며 기존 gateway/recorder는 유지된다.

외부 브라우저에서 앱 설치 없이 보려면 별도 인증 프록시를 사용한다. 화면은 계속
loopback에서 실행하고, `HTTPS Funnel → Caddy 로그인 → 127.0.0.1:8765`로 연결한다.
기존 gateway용 HTTPS 443과 분리하여 공개 포트 8443을 사용한다. 이는 Pi 화면의
직접 조회이며 운영 SaaS에 3D 추정값을 저장하거나 SaaS 로그인을 연동하는 기능은 아니다.

Caddy가 없는 Pi에서는 기존 서비스 유무를 확인한 뒤 배포판 패키지를 설치한다.
새 설치라면 기본 Caddy 서비스를 먼저 mask하여 기본 웹 서버가 시작되지 않도록 한다.
이 절차는 기존 Caddy 서비스가 있는 장비에 그대로 적용하지 않는다.

```bash
sudo systemctl mask caddy.service caddy-api.service
sudo apt-get install --no-install-recommends caddy
sudo python3 deploy/install_air_remote.py --username habitat
```

`--with-air` 배포 묶음에도 설치기와 공개 템플릿이 포함된다. 해당 묶음에서는
`sudo python3 install_air_remote.py`를 사용하며 Caddy 패키지는 별도로 설치한다.

설치기는 `configs/examples/air-remote.Caddyfile`을 사용해 loopback 전용 8766 포트에
인증 프록시를 설정한다. 사용자명과 두 로컬 포트는 CLI 설정으로 변경할 수 있다.
화면·스크립트·사육장 목록·측정 API 전체에 브라우저의 ID/비밀번호 인증을 적용하며,
업스트림에 로그인 인증 헤더를 전달하지 않는다. Caddy 2.6 계열과의 호환을 위해
`basicauth` 지시어를 사용한다. [Caddy 인증 문서](https://caddyserver.com/docs/caddyfile/directives/basic_auth).

새 무작위 비밀번호는 `/etc/habitat-air-viewer/remote-login.json`에 root 전용 0600으로
저장한다. 관리자가 Pi에서만 이 파일을 확인해 로그인 정보를 사용하며 공유 로그에는
출력하지 않는다. 기존 로그인 파일과 `remote.Caddyfile`은 재설치 시 보존한다.
설정에는 bcrypt 해시만 저장하고 systemd `LoadCredential`로 서비스에 전달한다.
`habitat-air-remote.service`는 DynamicUser, 비공개 상태 디렉터리, CPU·메모리 제한을
사용한다. Caddy의 자동 저장 설정에도 해시만 포함되며 해당 비공개 디렉터리에 보관된다.

설치기는 로컬에서 무인증/잘못된 비밀번호 401 및 정상 로그인 200을 검사한다.
검사에 성공한 뒤에만 다음 단계로 외부 공개를 활성화한다. 기존 Funnel 설정을 먼저
보존하고 다른 포트나 경로는 변경하지 않는다.

```bash
sudo tailscale funnel --bg --https=8443 http://127.0.0.1:8766
```

접속 주소는 `https://<Pi의 Tailscale DNS 이름>:8443/?cage_id=<사육장 ID>`다.
공개 HTTPS의 TLS 인증서는 Tailscale이 관리한다. 원격 조회를 중단할 때는
`sudo tailscale funnel --bg --https=8443 off`로 이 포트만 해제한다.
Pi와 인터넷 연결이 유지되어야 하며 `--bg` 설정은 재부팅 후에도 유지된다.
[Funnel 운영 문서](https://tailscale.com/docs/reference/tailscale-cli/funnel).

인증 회귀 검사는 `tests/integration/test_air_remote.py`에서 실제 Caddy와 격리된
HTTP 서버를 사용한다. 실제 MQTT·센서·SaaS에 시험 데이터를 보내지 않는다.

검증: `tests/unit/test_air_viewer.py`, `tests/contract/test_air_mqtt.py`,
`tests/test_mqtt.py` 46개와 41 subtests 통과; `tests/test_deployment.py` 35개 통과.
실시간 입력 검증은 별도로 실제 메시지 ID·측정 시각·T1/T2/T3를 대조한다.

2026-10-24 Pi 적용 기록:

- 화면 release: `0.4.17-9bcf4fc7fbde` (manifest 49개 파일 검증, NumPy 2.5.3).
  실행 package의 air/entrypoint 파일 8개가 소스와 바이트 단위로 일치한다.
  gateway는 기존 `0.4.16-92e6792d58ff`를 계속 실행한다.
- 21:29:48 KST 실제 메시지 `f969aab4-03eb-477c-ac51-72fc98324ac6`의
  T1=21.19, T2=20.875, T3=21.25°C가 화면 API, gateway DB, recorder DB에서
  정확히 일치했다. recorder의 전체 센서 quality도 valid였다.
- gateway PID 84959, recorder PID 21687 유지; viewer PID 88362, enabled/active,
  자동 재시작 0회. 기존 gateway.toml, gateway.env, CA 및 기존 두 service unit의
  SHA-256이 설치 전후 일치했다. 센서 배선·핀·TLS·인증 파일은 변경하지 않았다.
- 21:45:11 KST 실제 입력에서 Chromium의 `live` 표시 및 173번째 온도장 렌더링,
  회전 후 canvas 변화, IDW 전환, 390px 모바일 너비에서 가로 넘침 없음과 JS 오류
  없음까지 확인했다. 화면은 표시용이며 제어 명령을 보내지 않는다.
- 이 Pi의 새 Chromium 프로필에서는 OS password-store 기본 설정일 때 URL이
  `about:blank`에서 진행되지 않았다. 임시 프로필에 `--password-store=basic`만
  추가하자 같은 검사가 통과했다. 키링 내부 대기 원인은 별도 확정하지 않았다.
  사용자 브라우저 설정을 변경하지 않고 로그인 없는 화면 전용 프로필
  `~/.cache/habitat-air-viewer`에만 이 옵션을 적용했다. Pi 배포 wrapper의 오래된
  V8 옵션 경고는 해당 실행의 `--js-flags=`로 제외했다.

Pi 화면을 다시 열 때(설치된 Chromium, 기존 데스크톱 사용자):

```bash
chromium --user-data-dir="$HOME/.cache/habitat-air-viewer" \
  --password-store=basic --js-flags= --no-proxy-server \
  --no-first-run --no-default-browser-check http://127.0.0.1:8765/
```

해당 프로필은 로컬 온도 화면 전용이며 웹 계정 로그인에 사용하지 않는다.
한글 문구가 네모로 표시되면 `fc-list :lang=ko`로 확인하고 OS의 `fonts-noto-cjk`
패키지를 설치한다. 화면 실측값 검증과 공간 추정 정확도 검증은 별개이며, 센서 좌표와
공기 흐름의 물리 보정은 남아 있다. 이번 로컬 화면 검증은 SaaS 웹 기록 조회의
독립적인 검증을 의미하지 않는다.

이 Pi에는 한글 글꼴이 없어 실제 캡처의 문구가 네모로 나타났다.
`fonts-noto-cjk`를 설치했고 `fc-match :lang=ko`의 Noto Sans CJK KR 선택 및
재실행한 Chromium의 실제 한글 렌더링을 확인했다.
최종 점검 시에는 209건을 수신한 뒤 BB6의 `online=false`를 받아
`status=offline`, `status_reason=bb6_status_offline`이었다. 마지막 메시지는
`99c9e801-e0f4-4b73-91f5-31bb4be929f5`, 측정 시각은 21:48:57 KST이며
recorder도 같은 시각 이후 신규 입력 없이 stale 상태였다. 기존 서비스와 viewer는
모두 active였고 재시작 횟수는 0이었다. 이 시점의 상위 센서 연결 중단을 화면도
정확히 표시했으며, 전원/Wi-Fi 등 중단의 물리 원인은 이번 화면 작업에서 확정하지 않았다.

## 사육장별 SaaS 공기 추정 준비 (0.4.18, 2026-10-25)

### CAGE-002 추가 준비 — 2026-11-04

사용자는 CAGE-002 조립 완료, 카메라 미설치, 기존 CAGE-001 설정과 같은
20×20×30cm 크기 및 T1=(10,10,28), T2=(2,2,8), T3=(18,18,8)cm 센서
위치를 확인했다. 공기 온도 추정에는 카메라가 필요하지 않으며 유효한
T1·T2·T3 측정값을 사용한다. 이 확인은 추정 정확도의 독립 검증을 뜻하지 않는다.

운영 viewer는 `0.4.19-01d4d3953ab6`이며 `/api/cages`에 CAGE-001만
등록돼 있었다. `/api/air?cage_id=CAGE-002`는 404였다. 기존 실행 명령은
`--air-config /etc/habitat-air-viewer/air.json` 하나만 지정한다.
`/etc/habitat-air-viewer/upload.json`의 SaaS 전송도 `enabled=false`다.

다음 두 파일을 소스 외부 `~/.config/habitatos/air-viewer/`에 준비했다.

- `cage-002.json`: 사용자 확인을 받은 크기·센서 좌표와 CAGE-002 ID.
- `20-cage-002.conf`: 기존 CAGE-001을 유지하고 CAGE-002 JSON을 추가하는
  `habitat-air-viewer.service`의 systemd drop-in.

설치된 release의 `load_config`, `load_settings`, `AirState`로 좌표 유효성,
CAGE-002/ESP32-002 매핑, 세 온도 센서 단위 및 모델 초기화를 검증했다.
실측값을 주입하거나 운영 MQTT에 시험 자료를 보내지 않았다. 현재 사용자의
`sudo -n -v`가 비밀번호를 요구하여 **운영 적용과 CAGE-002 실시간 수신 확인은
아직 완료하지 않았다.** CAGE-002의 과거 센서 장애 기록을 현재 상태로 단정하지 않는다.

Pi 터미널에서 적용할 명령:

```bash
sudo install -m 644 /home/<gateway-user>/.config/habitatos/air-viewer/cage-002.json /etc/habitat-air-viewer/cage-002.json &&
sudo install -d -m 755 /etc/systemd/system/habitat-air-viewer.service.d &&
sudo install -m 644 /home/<gateway-user>/.config/habitatos/air-viewer/20-cage-002.conf /etc/systemd/system/habitat-air-viewer.service.d/20-cage-002.conf &&
sudo systemctl daemon-reload &&
sudo systemctl restart habitat-air-viewer.service
```

적용 후 `http://127.0.0.1:8765/?cage_id=CAGE-002`에서 사육장 선택과
실제 새 메시지의 T1·T2·T3·message_id를 확인한다. 센서 입력이 invalid이거나
끊겨 있으면 정상 추정으로 표시하지 않는다. 변경 대상은 공간 추정 viewer이며,
MQTT broker·gateway·recorder·카메라 설정은 아니다. SaaS는 아래의 수신 API·
사육장 매핑·웹 연결을 별도로 완료한 뒤 전송을 활성화해야 한다.

19:05 KST 후속 확인: 사용자가 위 명령을 적용했고 서비스는 19:03:30에
재시작됐다. 두 설정 파일과 drop-in 적용을 확인했으며 viewer는 active,
재시작 횟수 0이었다. `/api/cages`는 CAGE-001·CAGE-002를 반환했고
CAGE-002 API와 HTML 모두 200이었다. 19:05:53 측정 메시지
`dd45b0a3-97fb-40b8-bf29-6e308096440a`의 T1=24.56, T2=24.312,
T3=24.375°C로 `live/fresh=true`, 추정 격자 12,000개, 실시간 수신 29건,
거절 0건을 확인했다. 이로써 위의 운영 적용·현재 센서 수신 확인은 완료했다.

사용자는 다른 PC·휴대폰에서 `127.0.0.1:8765`에 접속하고 있었다.
다른 기기에서는 기존 공개 주소
`https://gateway.example.ts.net:8443/?cage_id=CAGE-002`를 사용한다.
이 HTTPS 주소와 로컬 인증 프록시 모두 무인증 요청에 정상적으로 Basic
로그인 401을 반환했다. 인증 후 사용자 브라우저 렌더링과 easyrep 연동은
이 검사에 포함하지 않았다.

21:39 KST SaaS 전송 활성화: 사용자 요청으로 기존 `upload.json`의
`enabled`만 true로 변경한 설정을 준비·검증했다. 사용자가 파일을 복사했지만
서비스 이름 중간의 줄바꿈 때문에 재시작이 실패했다. 이후 정확한
`sudo -n systemctl restart habitat-air-viewer.service` 명령으로 적용했다.
21:39:19 로그의 `cloud_enabled=True`, CAGE-001·002의 MQTT 수신 및 실제
`POST https://easyrep.kro.kr/v1/edge/air` 실행을 확인했다. Viewer는 active,
자동 재시작 0회이며 gateway PID 84959는 유지됐다.

전송은 활성화됐지만 서버 저장 완료 ACK는 받지 못했다. 서비스 로그에는
HTTP 413이 반복되고 403도 한 차례 있었다. 같은 운영 인증정보로 21:40에
실제 추정값을 한 건씩 재확인했을 때 CAGE-001 요청은 37,415바이트,
CAGE-002 요청은 33,814바이트였으며 둘 다 HTML 413을 반환했다.
이는 계약의 JSON 본문 상한 98,304바이트(96 KiB) 이내다. SaaS 팀은
`/v1/edge/air`까지의 프록시·앱 요청 크기 제한과 장비별 권한·UUID 매핑을
확인해야 한다. Pi는 전송 활성 상태를 유지하며 기존 5초 간격과 실패 시 최대
60초 backoff를 사용한다. 서버 저장·SaaS 화면 표시 완료로 해석하지 않는다.

### 여러 사육장 지원과 SaaS 계약

화면 entrypoint는 여러 `--air-config`를 받아 사육장별 AirState와 수신기를 하나의
프로세스에서 관리한다. 중복 ID 또는 gateway에 없는 cage는 시작 시 거절한다.
`/api/cages`는 설정된 화면 대상만 반환하고 `/api/air?cage_id=...`는 해당 사육장을
조회한다. 없는·빈·중복 선택은 404다. 아직 연결하지 않은 사육장을 임의로 표시하지 않는다.

`habitat/saas/air.py`는 측정 이벤트 대기열과 독립적으로 최신 추정을 전송한다.
MQTT callback에서 HTTP를 호출하지 않고 사육장별 전송 루프를 분리한다.
성공 ACK까지 최신 결과 하나만 유지하고 새 결과로 교체하며 오래된 결과는 보내지 않는다.
파생 화면용 임시 대기 상태이며 원본 측정의 영속 대기열을 대체하지 않는다.

서비스는 `/etc/habitat-air-viewer/upload.json`을 읽는다. 최초 설치는
`configs/examples/air-upload.json`으로 생성하며 기존 파일은 보존한다.
기본값은 `enabled=false`, endpoint는 `https://easyrep.kro.kr/v1/edge/air`,
token_env는 기존 `HABITAT_CLOUD_TOKEN`이다. 전송 간격 5초, timeout 5초,
최대 재시도 간격 60초이며 실제 토큰 값은 새 파일에 기록하지 않는다.
여러 사육장은 `--air-config /etc/habitat-air-viewer/cage-002.json`처럼 인자를 추가한다.

운영 SaaS 코드·배포 접근은 사용자가 보유하지 않는다고 확인했다. 서버 적용 전에는
전송을 비활성으로 유지한다. [SaaS 적용 지시](api/saas-codex-prompt.md#air-saas-work)와
[공기 추정 v1 계약](saas-integration.md#air-estimate-v1)을 서버 담당자가 적용한 뒤,
실제 수신·조회 경로와 사육장 UUID 등록을 확인하고 전송을 활성화한다.
자연 발생한 실제 메시지 ID와 격자 해시로 저장 ACK·웹 조회를 대조해야 완료다.

웹은 실시간/CSV 출처, 연결 서버, 사육장, 측정 후/수신 후 경과 시간을 분리한다.
SaaS 응답에서 IDW baseline이 없어도 주 격자를 표시한다. SPA의
`window.HabitatAirView.setEndpoint()`는 이전 값을 지우고 요청을 취소하며 늦은
응답을 무시한다. 문서당 스크립트를 한 번 로드하고 뷰 DOM을 유지하는 계약이다.

검증: Python 검사 206개와 49 subtests, 추가 설치 권한 회귀 검사 1개 통과.
격리된 합성 데이터로 두 사육장의 `AirSubscriber → AirState → AirUploader →
참고 수신기 → 권한별 조회`, 원본 ID·센서값·색 범위 보존과 기존 Gateway DB 불변을
확인했다. 실제 Chromium에서 사육장 전환, 지연 응답 차단, 중복 polling 방지,
baseline 생략, 3D 회전 및 모바일 너비를 검증했다. 외부 SaaS나 센서에 합성 자료를 보내지 않았다.

```bash
.venv/bin/python -m pytest tests/unit/test_air_viewer.py tests/contract/test_air_mqtt.py \
  tests/contract/test_air_upload.py tests/contract/test_air_receiver.py \
  tests/integration/test_air_pipeline.py tests/test_saas_reference.py \
  tests/contract/test_video.py tests/test_deployment.py -q
node tests/integration/air_viewer_browser.mjs
```

브라우저 검사는 Node 22 이상과 Chromium을 사용하며 임시 서버·프로필을 제거한다.
최초 설치 시 caller umask 0077 때문에 별도 설치된 NumPy를 서비스 계정이 읽지
못해 이전 0.4.17로 자동 복구됐다. 공개 의존성 설치 구간만 umask 0022로 제한하고
원래 값을 복원하도록 설치기를 수정했으며 같은 조건의 권한 회귀 검사를 추가했다.

최종 적용 release는 `0.4.18-50f2018436e1`이다. manifest 50개 파일을 검증했고
실행 air/entrypoint/전송·계약·수신 모듈 11개가 소스와 일치했다. 기존 설정·인증·CA·
서비스 unit·공기 모델 설정 6개 파일의 SHA-256과 gateway PID 84959,
recorder PID 21687이 유지됐다. 새 업로드 설정은 비활성이고 `/api/cages`는
CAGE-001만 반환한다. 서비스 시작 직후 상태는 새 실제 측정을 기다리는 `waiting`이었다.

02:39 KST 최종 점검에서도 viewer는 MQTT에 연결된 채 새 측정을 기다렸으며,
recorder의 마지막 측정은 2026-10-25 01:31:39 KST, 상태는 stale이었다.
viewer PID 130247의 재시작 횟수는 0이고 세 서비스 모두 enabled/active였다.
따라서 새 전송 경로의 자연 발생 실측 ACK 및 운영 SaaS 화면 대조는 아직 미확인이다.
원본 R13 ZIP의 SHA-256도 보존됐다. 설치·검증 임시 파일은 정리했다.

### 기록 복원 화면 실제 적용 — 2026-10-25

화면 서비스만 `0.4.19-01d4d3953ab6`으로 갱신했다. 배포 manifest 53개 파일과
설치된 화면 모듈·entrypoint·웹 자산 8개의 소스 일치를 확인했다. 이전 release는
보존했다. Gateway는 계속 `0.4.16-92e6792d58ff`이며 실행 PID 84959,
recorder PID 21687, 로그인 프록시 PID 142129가 유지됐다. 새 viewer PID 160806은
enabled/active, 재시작 0회였다.

04:50 KST 확인에서 기록 300건을 복원했고 이후 실제 수신은 0건이었다.
마지막 ID `bfb4f6fb-fb28-4d4f-93fa-6ef580849f41`, 측정 시각
2026-10-25 03:56:36 KST, T1 22.63°C / T2 22.313°C / T3 22.375°C가
Gateway 이력 API와 recorder DB, viewer에서 정확히 일치했다. 모델은 15개의
큰 시각 간격에서 초기화했으며 최종 12,000개 격자값이 유한했다.
`data_origin=history`, `fresh=false`, `held=true`, `received_at_utc=null`로
과거 기록을 신규 수신으로 표시하지 않았다.

공용 DNS 경로 `203.0.113.10`에서 TLS 호스트 검증을 유지한 채 공개 8443 API를
조회했다. 무인증 401, 정상 로그인 200, 공개·로컬의 메시지 ID와 전체 온도장 일치,
공개 JS와 설치 자산 일치를 확인했다. 센서 펌웨어·핀 설정을 포함한 설정·인증·TLS·
기존 service 파일 12개의 해시도 유지됐다. 이전 상태 요약은 root 전용
`/etc/habitat-air-viewer/history-before-20261025.json`에 보존한다.

실제 Chromium에서 저장 기록 출처, "기록 복원 300건 · 이후 수신 0건", 한국 측정
시각과 온도 3개, WebGL 입체 부피·센서 라벨 표시를 확인했다. JavaScript 오류가
없었으며 원래 수신 시각은 "수신 시각 기록 없음"으로 표시했다.
격리된 브라우저 회귀에서는 같은 숫자의 신규 MQTT 표시 전환, 늦은 측정 갱신,
오프라인 화면 유지, 사육장 전환·회전·모바일 너비도 통과했다.

Python 관련 검사 221개와 48 subtests가 통과했다. FastAPI/Starlette의 기존 의존성
deprecation warning 2개가 있었으며 이번 기능 실패는 없었다. 실제 새 센서 메시지는
검증 중 수신되지 않아 새 펌웨어 통신이나 실제 live 전환이 복구됐다고 판단하지 않는다.
SaaS 3D 업로드는 비활성 상태를 유지했다. 전체 과거 이력을 선택하는 시간축 UI는
추가하지 않았으며, 이번 변경은 최근 기록으로 마지막 온도장을 복원하는 범위다.
