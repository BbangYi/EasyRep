# Pi GPU 클라이언트 운영 (프로그램 0.3.0 / GPU 계약 1.0.0)

로컬 사진 폴더를 GPU 서버로 보내고 복원 작업을 요청·조회한 뒤 결과를 검증하는 **Pi 클라이언트**다. GPU 서버·COLMAP·학습 프로그램은 데스크톱에 별도로 구현한다. 카메라 촬영, 라이브 스트리밍, SaaS 모델 등록, 열화상 투영은 이 worker의 구현 범위가 아니다.

## 현재 확인한 범위

별도 프로세스, 별도 SQLite/파일 저장소를 사용한다. GPU 응답 시간 초과 중에도 기존 gateway 프로세스의 가상 팬 명령 ACK와 SaaS 모의 수신 서버로의 전송이 계속되는 통합 테스트가 있다. 실제 GPU·카메라·ESP32에 대한 시험은 아니다.

기존 `habitat_gateway` 실행 명령과 설정은 그대로 사용한다. 새 worker는 `python -m apps.worker` 또는 설치된 `habitat-compute`로 실행한다. 같은 릴리스에 모든 매장 코드를 담고, `--gateway-config`의 site/gateway/cage/revision과 별도 Compute 설정만 바꾼다.

## 개발 환경에서 설정

프로젝트 루트에서 실행한다. `.venv` 의존성에 Pillow가 추가되었다.

```bash
.venv/bin/python -m pip install -c requirements.lock -e '.[test]'
mkdir -p configs/local
cp configs/examples/compute.toml configs/local/compute.toml
.venv/bin/python -m apps.worker --config configs/local/compute.toml --gateway-config config/simulation.toml check-config
```

기본은 `enabled=false`이고 `work`/`health`는 네트워크나 DB를 열지 않는다. `enqueue`는 비활성 상태에서도 실제 사진을 로컬 대기열에 보관할 수 있다.

GPU 준비 후 실제 설정에 아래 두 항목을 반영한다. 예제 호스트는 사용할 주소가 아니다. `/v1/gpu`를 base URL 뒤에 붙이지 않는다. `cloud.endpoint`는 SaaS 전용이며 바꾸지 않는다.

```toml
enabled = true
base_url = "https://데스크톱이-반환한-실제-HTTPS-호스트"
```

토큰은 데스크톱에 등록된 것과 같은 값을 셸의 `HABITAT_GPU_TOKEN` 환경변수로 설정한다. 코드·TOML·명령 인자·결과 보고서에 넣지 않는다. Bash에서는 아래처럼 화면/명령 기록에 값이 남지 않게 입력할 수 있다.

```bash
read -rsp 'GPU token: ' HABITAT_GPU_TOKEN
export HABITAT_GPU_TOKEN
.venv/bin/python -m apps.worker --config configs/local/compute.toml --gateway-config config/simulation.toml health
```

모든 API는 인증이 필요하다. TLS 인증서 검증을 끄는 옵션은 없다. HTTP는 loopback 시험 서버에만 허용한다. `health`가 응답해도 `backend=splatfacto`, `gpu.cuda_available=true`, `gpu.reconstruction_ready=true` 확인 전에는 복원을 요청하지 않는다.

## 촬영 묶음 → 작업 → 결과

`--folder`에는 바로 아래에 3~500개의 JPEG/PNG가 있는 실제 다시점 사진 폴더를 지정한다. 20 MiB/장, 2 GiB/묶음, 20 megapixel/장 이하를 수용한다. 이는 복원 성공에 필요한 촬영 장수/품질을 보장하지 않는다. 고정 카메라에서 같은 구도로 찍은 연속 사진을 다시점 자료로 취급하지 않는다.

`--captured-at`은 실제 촬영 시각으로 바꾼다. timezone이 필요하며 v1 CLI는 묶음의 모든 사진에 이 시각을 기록한다. EXIF 개별 시각 추출은 하지 않는다.

```bash
.venv/bin/python -m apps.worker --config configs/local/compute.toml --gateway-config config/simulation.toml enqueue --cage-id CAGE-001 --folder /절대경로/실제사진폴더 --captured-at 2026-09-19T12:00:00+09:00
.venv/bin/python -m apps.worker --config configs/local/compute.toml --gateway-config config/simulation.toml work
```

첫 명령은 원본을 worker 저장소로 복사·검증하고 capture_id/file_id/job_id를 SQLite에 영속 저장한다. **enqueue를 다시 실행하면 새 촬영/새 작업을 만든다.** 같은 작업의 재전송은 기존 대기열 worker 또는 `retry`로 처리한다. 업로드한 사진은 원본 폴더의 후속 변경에 영향받지 않는다.

`work`는 계속 실행되며 Ctrl+C로 종료한다. `work --once`는 현재 처리 시각이 된 작업을 한 번씩만 진행한다. 복원이 끝날 때까지 기다리는 명령이 아니므로 첫 실행의 `waiting`은 정상이다.

```bash
.venv/bin/python -m apps.worker --config configs/local/compute.toml --gateway-config config/simulation.toml list
.venv/bin/python -m apps.worker --config configs/local/compute.toml --gateway-config config/simulation.toml show JOB_UUID
.venv/bin/python -m apps.worker --config configs/local/compute.toml --gateway-config config/simulation.toml retry JOB_UUID
```

`JOB_UUID`를 enqueue 응답의 값으로 바꾼다. 상태 확인에는 토큰이 필요 없다. 동일 storage_dir에 network worker는 하나만 실행할 수 있고, 조회·사진 등록 CLI는 함께 사용할 수 있다.

| 로컬 상태 | 의미/대응 |
|---|---|
| queued / uploading | 로컬 보존됨 / GPU가 누락으로 반환한 파일 업로드 |
| waiting | GPU queued/running. 다음 조회 시각까지 대기 |
| downloading / complete | 결과 수신 중 / 크기·해시·Gaussian PLY 구조 검증 및 원자적 저장 완료 |
| retry | 시간 초과, 연결 실패, 408/425/429/5xx 또는 GPU 미준비. 간격을 늘려 같은 ID로 자동 재시도 |
| blocked | 인증·scope·revision·파일·저장 공간·계약 오류. 원인 수정 후 같은 ID로 `retry` |
| failed / interrupted | GPU가 반환한 종료 상태. 자동 재학습하지 않음; GPU 로그 확인 후 재실행을 원하면 새 enqueue |

401/403/404/409/413/422는 보수적으로 blocked에 보존한다. 특히 원격 DB가 사라진 404는 자동으로 새 job을 만들지 않는다. 서버 scope/저장 상태를 먼저 복구한다. `retry`도 사진·scope·revision·backend origin 검사를 다시 적용한다. 기존 task를 다른 GPU origin이나 변경된 revision으로 옮기려면 새 capture/job을 생성한다.

결과는 기본 `var/data/compute/artifacts/JOB_UUID/ARTIFACT_UUID.ply`, 원본 복사본은 `captures/CAPTURE_UUID/FILE_UUID`, 대기열은 `compute.sqlite3`에 있다. 성공은 파일 전송/구조 검증이며 형상 품질·실측 스케일·도마뱀 행동 판단의 검증이 아니다. v1의 `metric_scale_verified=false`를 유지한다. Gaussian 속성이 없는 일반 점군은 거절한다. ASCII와 little/big-endian binary PLY의 단일 vertex scalar 속성 형식을 지원한다.

## 저장 공간과 중단 복구

- 기본 저장 한도 8 GiB, 결과 1개 최대 1 GiB. `max_storage_bytes`, `max_artifact_bytes`로 조정한다. 다운로드/사진 복사 전 용량과 디스크 여유를 확인한다. 저용량 차단은 원본을 삭제하지 않는다.
- 파일을 메모리에 통째로 올리지 않고 나눠 보낸다. 일반 요청 timeout과 전송 deadline이 있으며 재시도 간격은 설정값까지 늘어난다.
- SIGTERM 중 긴 전송이 남으면 systemd가 20초 후 종료할 수 있다. 다음 실행은 SQLite와 GPU의 수신 목록을 기준으로 이어간다. 파일 단위 재시도이고 byte-range 재개는 아니다.
- 현재 자동 보존기간/삭제 기능은 없다. 오래 실행할 때 저장 용량을 감시하고 백업·정리 정책을 정한다. 정리 전 worker와 enqueue를 중지하고 SQLite와 captures/artifacts를 함께 백업한다. DB의 유효 작업이 참조하는 파일을 임의로 지우지 않는다.
- 비정상 전원 차단으로 `.staging-*`, DB에 없는 capture 디렉터리, `.part`가 남을 수 있다. 정상 실행 중의 임시 파일과 구분하여 worker/등록 중지 상태에서 DB 참조를 확인한 후 정리한다. 다음 다운로드는 `.part`를 처음부터 다시 받는다.
- storage_dir은 하나의 site/gateway 소유다. 다른 매장의 설정으로 열면 거절한다. 기존 control DB는 열지 않으며 storage schema도 별개다.

## 운영 릴리스와 선택적 systemd 서비스

0.3.0 릴리스에는 같은 wheel의 두 CLI, compute 설정 예시, JSON Schema, 이 문서와 `habitat-compute.service` 템플릿이 들어간다. 기존 `deploy/install.py`는 gateway를 설치하며 **Compute 서비스를 자동 활성화하지 않는다**. 기존 0.2.0 배포 파일에는 새 코드가 없다. 설치·업그레이드/롤백은 [기존 배포 안내](../deployment.md)를 사용한다.

운영 Pi에서 0.3.0 릴리스를 설치한 후 관리자 터미널에서 다음 준비를 한다. 계정/파일이 이미 있으면 재사용하고 실제 설정을 덮어쓰지 않는다.

```bash
sudo useradd --system --user-group --home-dir /var/lib/habitat-compute --shell /usr/sbin/nologin habitat-compute
sudo install -d -o habitat-compute -g habitat-compute -m 0700 /var/lib/habitat-compute
sudo install -m 0644 /opt/habitat-gateway/current/compute.toml /etc/habitat-gateway/compute.toml
sudo install -m 0644 /opt/habitat-gateway/current/habitat-compute.service /etc/systemd/system/habitat-compute.service
sudo install -m 0600 /dev/null /etc/habitat-gateway/compute.env
sudoedit /etc/habitat-gateway/compute.toml /etc/habitat-gateway/compute.env
```

`compute.toml`의 storage_dir은 `/var/lib/habitat-compute`, base_url은 실제 HTTPS origin으로 설정한다. `compute.env`에 `HABITAT_GPU_TOKEN=실제값` 한 줄을 기록하고 공개하지 않는다. 기존 `/etc/habitat-gateway/gateway.toml`이 올바른 매장/cage를 담는지도 확인한다. 파일 설치 명령은 초기 설치용이며 기존 파일에 반복 실행하지 않는다.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now habitat-compute.service
sudo journalctl -u habitat-compute.service -n 50 --no-pager
```

systemd는 root 소유 0600 환경 파일을 읽어 worker에 전달한다. worker 계정으로 실제 사진에 대한 읽기 권한을 마련한 뒤 enqueue/list/show/retry도 같은 `habitat-compute` 사용자로 실행한다. 예:

```bash
sudo -u habitat-compute /opt/habitat-gateway/current/venv/bin/python -m apps.worker --config /etc/habitat-gateway/compute.toml --gateway-config /etc/habitat-gateway/gateway.toml list
```

서비스에 CPU/메모리 제한과 낮은 우선순위를 적용한다. 대규모 업로드와 SD카드 I/O 경쟁은 실장치에서 추가 측정해야 한다. gateway와 Compute 간 systemd 의존 관계는 없다. **gateway 릴리스 교체·롤백 전 Compute를 정지**하고, 새 릴리스가 이 worker/storage schema를 지원하는지 확인한 뒤 다시 시작한다. 0.2.0으로 롤백하면 Compute는 정지 상태로 둔다. 자동 설치기가 Compute의 업그레이드/롤백을 관리하지는 않는다.

2026-09-19 기록에서는 관리자 권한과 네트워크 등록이 확보되지 않아 Compute 서비스 설치/활성화를 수행하지 않았다. 아래 Tailscale 설치와 Compute 서비스 배포는 별도 단계다.

## 이 Pi의 Tailscale 연결 단계

2026-09-19 확인 시 Tailscale이 없고 비대화식 sudo도 사용할 수 없었다. 이후 관측은 아래에 별도로 기록한다. `docs/gpu/pi-profile.json`은 2026-09-18의 스냅샷이며 최신 네트워크 상태를 나타내지 않는다.

**2026-09-21 01:28 KST 확인:** 이 Pi에 Tailscale **1.102.4**를 설치했고 `tailscaled.service`의 `active/running`, 부팅 자동 시작 `enabled`를 확인했다. 이 시점의 `BackendState`는 `NeedsLogin`이며 Pi Tailscale IP는 아직 할당되지 않았다. 당시에는 계정 소유자의 Pi 등록이 필요한 상태였다. 로그인 링크·인증 토큰은 인계 자료에 저장하지 않는다.

**2026-09-21 01:55~01:56 KST 확인:** 사용자 등록 후 `BackendState=Running`, `Online=true`, health 경고 없음과 서비스 `active/running`, `enabled`를 확인했다. Pi IPv4는 `100.102.106.40`, Tailscale DNS 이름은 `gateway.example.ts.net`이다. GPU peer `100.100.211.20`은 `<gateway-user>` / `gateway.example.ts.net`으로 online이었다. 첫 `tailscale ping --c=3 --timeout=5s 100.100.211.20`은 도쿄 중계 서버 `DERP(tok)`로 3회 응답(72~75 ms)을 받았지만 direct 연결 대기 조건을 충족하지 못해 종료 코드 1이었다. 이어 `tailscale ping --until-direct=false --c=3 --timeout=5s 100.100.211.20`은 **direct 경로로 3회 응답(7/7/6 ms), 종료 코드 0**이었다. Pi→GPU Tailscale 통신은 확인됐으며 GPU HTTPS API·SSH·CUDA·실제 복원은 이번 시험에서 확인하지 않았다. DNS 관측값만으로 GPU HTTPS 서비스가 구성됐다고 판단하지 않는다.

설치 중 발생한 APT `MergeList` 오류는 기존 Debian trixie 패키지 목록 3개가 중간에 잘린 상태여서 발생했다. 손상된 ARM64/ARMHF Packages 및 영문 Translation 파일을 `/var/lib/apt/habitat-index-backup-20260920T162551Z/`에 보존하고 다시 받았다. 복구 후 3개 파일의 크기·SHA-256이 InRelease와 일치했고 `apt-get update`와 `apt-get check`가 정상 종료했다. Tailscale 및 필요한 패키지 5개를 설치했으며 기존 패키지 업그레이드/삭제는 없었다.

이미 설치·등록된 이 Pi에서는 상태와 연결을 확인한다. 이후 `NeedsLogin`이면 `sudo tailscale up`으로 표시되는 링크를 연다. 명령의 로그인 대기 시간이 끝나도 daemon 설치가 취소된 것은 아니므로 설치 명령을 반복하지 않고 현재 상태를 확인한다.

```bash
tailscale status
tailscale ip -4
tailscale ping --until-direct=false --c=3 --timeout=5s 100.100.211.20
```

아래는 **아직 설치하지 않은 다른 Pi용** 절차다. [Tailscale Linux 공식 설치 안내](https://tailscale.com/docs/install/linux)를 따른다.

```bash
curl -fsSL https://tailscale.com/install.sh -o /tmp/habitat-tailscale-install.sh
sudo sh /tmp/habitat-tailscale-install.sh
sudo tailscale up
tailscale ip -4
tailscale status
tailscale ping 100.100.211.20
```

설치 후 표시되는 로그인 절차를 완료하고 데스크톱과 통신할 수 있는 tailnet/접근 권한을 설정한다. `tailscale ping` 성공과 HTTPS API 성공은 별개다. 데스크톱이 반환한 `desktop-result.json`의 HTTPS origin·계약 버전·등록된 매장/Pi/cage를 확인하고 위 `health`를 실행한다. 토큰을 채팅에 보내지 않는다.

실제 완료 판정은 **실제 사진 → Tailscale HTTPS 업로드 → RTX 4060 COLMAP/학습 → 결과 파일 다운로드 → 시각적 품질 확인**이다. 합성 테스트 결과로 이 단계가 완료됐다고 표시하지 않는다.

## 계약과 검증

- 원본 Python 모델: `habitat/compute/contracts.py`; 설정: `habitat/compute/config.py`.
- [v1 계약](../gpu/gpu-api-contract.md), [JSON Schema](../../configs/schemas/compute-v1/), [점진적 이전 계획](../architecture/compute-client-plan.md).
- JSON Schema는 자료형·필드 제약을 공유하며 scope 일치/파일 목록 분할/상태 전이 같은 모델 간 검증은 계약과 Python 검증을 함께 따른다.
- 스키마 재생성: `.venv/bin/python -m scripts.export_compute_contract`.
- 전체 회귀 검증: `.venv/bin/python -m pytest -q`.
