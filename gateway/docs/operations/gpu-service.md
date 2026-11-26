# GPU 서버 운영

Pi와 GPU는 같은 프로젝트를 사용합니다. Pi 클라이언트는 `habitat/compute/`, GPU 서버는
`habitat/gpu/`이며 설치 대상에 맞는 진입점과 설정을 선택합니다.

**2026-10-07 GPU 운영 소스는 0.4.14이며 Pi도 `0.4.14-5a9bc13f4f2f`를 사용합니다.**
GPU 확인 시각은 `2026-10-07T05:18:01.690764+00:00`입니다. 서비스는 14:16:26 KST에
시작한 PID 4040·`active`이고, 관련 소스 9개 해시를 대조했습니다. 설정·인증정보·기존
환경 모델 해시는 보존했습니다. API 계약 버전은 `1.0.0`을 유지하며 이 문자열만으로
소스 버전 일치를 판단하지 않습니다.
[GPU 적용 기록](../../var/reports/commissioning/software-r15-20261007-gpu-014.json),
[Pi 설치 기록](../../var/reports/commissioning/software-r15-20261007-pi-014.json).

GPU health는 `ok`·`splatfacto`, RTX 4060·`cuda_available=true`·
`reconstruction_ready=true`입니다. 환경 health는 `simulation_configured`,
`field_validated=false`, `hardware_execution_allowed=false`를 유지합니다.
환경 health의 `cuda_probed=false`는 해당 health 경로가 CUDA를 검사하지 않는다는 뜻입니다.
이번 실제 추론 확인은 아래 Pi 요청 결과를 근거로 합니다.

### 0.4.14 실제 Pi → GPU 요청 검사

실제 Pi에서 가상 사육장 3개를 120분 가상 진행하며 **schema 2 CUDA 응답 360회**를
받았습니다. 응답은 기존 모델 `synthetic-mlp-7d56293563ff`·RTX 4060과
5·10·30·60분 예측, 길이 60의 REQ/예상 RUN 계획을 반환했습니다. 360개 계획의 계약
검증을 통과했습니다. 실제 경과 시간은 97.068661초, HTTPS 왕복 중앙값은 0.068625초,
최대는 1.925126초였습니다. 가상 펌프는 75회 실행됐고 종료 상태는 펌프 OFF·밸브 없음·
`idle`입니다. [실제 통합 결과](../../var/reports/commissioning/software-r15-20261007-integration.json).

센서·환경 반응·펌프·밸브는 가상이며 운영 DB·MQTT 출력·SaaS 데이터 전송을 사용하지
않았습니다. 이는 새 계약의 실제 CUDA 왕복 확인입니다. 선택한 조건부 계획을 보존했지만
이후 재계획으로 미래 동작이 바뀌므로 예측 정확도는 채점하지 않았습니다. 실물 토출량·
온습도 예측 성능·3D 복원 품질·종별 적합성·실제 분무 성공을 입증하지 않습니다.

Pi Linux 선택검사는 208개·하위 검사 141개가 33.46초에 통과했습니다. 환경 API 관련
동일 구현의 fixture 검사는 3개·하위 검사 38개가 2.99초에 통과했으며 버전 변경 전후
해당 구현이 같음을 확인했습니다. 실제 CUDA 요청 횟수와 이 fixture 검사를 합산하지
않습니다. [선택 검사 범위](../../var/reports/commissioning/software-r15-20261007-checks.json),
[검사 로그](../../var/reports/commissioning/software-r15-20261007-checks.log).

### 환경 요청/RUN 계약 — 0.4.14 적용

`schema_version=1`은 기존 `desired_run_ideal` 비교를 유지합니다. `pulse_seconds`는
직접 적용할 가상 RUN이며 이 계약의 기존 결과·가중치를 schema 2 검증으로 재분류하지 않습니다.
새 `schema_version=2`는 `timing_mode=r15_request_fixture`와 정확한
`timing_profile=r15_esp20_pico_window1ms_phase0_v1`을 요구합니다.

GPU는 REQ 후보 `[2000,3000,4000,4500,5000]`ms를 순방향 fixture에 넣고 나온 RUN 계획으로
기존 환경 신경망과 비용을 평가합니다. 원본 Pico RUN 한도는 3000ms입니다. 응답의
`selected_plan`은 60개 `request_hold_ms`(정수 0..5000)와 60개 `expected_virtual_run_s`
(0..3초)를 보존합니다. 0은 요청 없음입니다. 첫 제안의 `request_hold_ms`는 첫 REQ이고,
`expected_virtual_run_s`와 `pulse_seconds`는 첫 예상 RUN입니다. API는 요청의 schema·모드·
프로파일 조합을 확인하고, worker 응답도 Pi와 같은 `EnvironmentResult`·`validate_result`로
검사합니다. 전체 계획의 순방향 대응, 첫 제안 일치, RUN 한도, 요청/매장/사육장 ID,
시각·만료·예측 시점과 출력 금지 필드를 확인한 뒤에만 원본 JSON을 반환합니다. 잘못된 응답은
`503 prediction_unavailable`로 거절하고 resident worker를 닫습니다. worker가 명시한
잘못된 입력은 기존 `422 invalid_prediction_input`을 유지합니다. 검증 모델의 기본 필드를
추가해 직렬화하지 않으므로 schema 1의 기존 응답 모양은 보존합니다. Pi도 수신 후 재검사합니다.
모드 혼용·불일치·알 수 없는 프로파일은 거절하며 schema 1로 자동 대체하지 않습니다.

계획의 예상 RUN은 위상 0·20ms ESP task·이상적인 WINDOW 1ms 응답 조건입니다.
가상 제어가 접수한 위상과 실제 실행 구간은 별도로 기록합니다. 다음 입력 이력은 실행한
RUN 구간만 사용하며 REQ나 예상 RUN을 실행 이력으로 넣지 않습니다. 선택한 미래 계획을
보존해도 이후 재계획 때문에 바뀐 동작은 원래 조건부 예측의 정확도 평가에 사용할 수 없습니다.
`SYNTHETIC_ONLY`, `field_validated=false`, `hardware_execution_allowed=false`를 유지합니다.

0.4.14의 Pi는 ESP hello의 엄격한 정수
`max_request_hold_ms`를 확인하고, 필드가 없는 기존 ESP는 3000ms로 취급합니다. 상한 초과는
MQTT 발행 전에 `r15_request_hold_unsupported_by_node`로 거절합니다. 같은 소스의
GPU API·CUDA worker·`habitat/control/r15_timing.py`를 적용했고 위 schema 2 왕복을
확인했습니다. 신판 ESP32 스케치는 센서형·N1 중앙형 두 역할 모두 대상 빌드를
통과했지만 업로드하지 않았습니다. 두 빌드의 요청 출력은 0이고 임시 toolchain을
삭제했습니다. [신판 대상 빌드](../../var/reports/commissioning/esp32-target-build-20261007.json).
운영 출력 잠금·실물 시험 0건을 유지하며 대상 빌드를 실제 GPIO 실행으로 해석하지 않습니다.

향후 같은 버전 갱신에서도 출력 잠금을 유지하고 Pi 계약을 먼저 확인합니다. GPU 배포에는
API 패키지뿐 아니라
`experiments/environment_sim/gpu_predict.py`, `predictive_misting.py`, `simulation_config.json`이
필요합니다. 기존 설정·인증정보·모델 경로와 가중치 해시를 보존하고 resident worker를 재시작해
새 소스를 적용합니다. health 200만으로 새 계약의 추론 성공을 판단하지 않습니다.
[R15 계약](../protocols/r15-bridge.md), [Pi 모의실험 명령](hardware-arrival.md#prediction-and-commissioning).

SaaS 하트비트의 실제 ACK `2026-10-07T05:42:44.867608Z`와 오류 없음을 확인했지만,
보존 이벤트 1건은 아직 동기화되지 않았습니다. 이벤트 성공 시각은 `null`, 연속성은
`blocked`·`cloud_continuity_unverified`, ACK 최고 순번은 0이고 서버 최고 순번은
미확인입니다. GPU 요청·하트비트와 이벤트 전달은 별개이며 서버 순번을 추정하거나 보존
이벤트를 삭제하지 않습니다. [실제 Pi cloud 상태](../../var/reports/commissioning/software-r15-20261007-cloud.json).

### 0.4.12 R15 정상 요청 유지 수정과 공통 소스 배포 (과거)

Pi의 정상 R15 ON이 만든 예약을 주기적인 안전 검사에서 busy 오류로 해석해 스스로 OFF를
발행하던 문제를 수정했습니다. 수정 전 0.4.11에서 두 회귀검사가 실패했고, 추가 ON의
진입 검사와 진행 중 요청의 안전 검사를 분리한 뒤 관련 검사 **46개 통과·1.29초**, 전체
검사 **396개 통과·7개 건너뜀·subtest 231개 통과·108.99초**를 확인했습니다.
정상 예약은 자기 취소 사유가 아니며 실제 센서 오류·핀 LOW·세션/lease·통신 상실·STOP은
계속 정지 조건입니다. OFF 수신도 물리 OFF 확인으로 승격하지 않습니다.
[수정 전 재현](../../var/reports/commissioning/software-r15-20261005-active-reservation-baseline.log),
[관련 검사](../../var/reports/commissioning/software-r15-20261005-active-reservation-tests.log),
[Pi 배포·전체 검사 결과](../../var/reports/commissioning/software-r15-20261005-active-reservation-deployment.json).

GPU는 같은 프로젝트의 0.4.12 소스를 적용했고, 22:07:56 KST에 시작한 PID 2854로
`active/running`, 종료 상태 0을 확인했습니다. 당시 배포의 실제 응답은 다음과 같습니다.

| API | 0.4.12 실제 확인 |
|---|---|
| `/v1/gpu/health` | HTTP 200, `ok`·`splatfacto`·CUDA·`reconstruction_ready=true` |
| `/v1/environment/health` | HTTP 200, `simulation_configured`·`field_validated=false`·`hardware_execution_allowed=false` |
| `/v1/livescene/health` | HTTP 200, `configured`·참조 모델 1개·`rgb_training_configured=false` |

이번 수정에서 새 학습·렌더나 실물 출력 시험을 수행하지 않았습니다. GPU 설정·인증정보·
기존 모델/원본은 변경하지 않았고 Pi 비공개 설정·인증정보·보존 이벤트도 유지했습니다.
SaaS sequence 1의 충돌 이벤트는 아직 복구하지 못했습니다. 아래 0.4.11 메타데이터 및
0.4.10 활성화·전체 검사 기록은 당시 이력이며 이번 버전의 검증 횟수로 합산하지 않습니다.

## 실행

Linux/WSL의 API 가상환경과 검증된 CUDA 모델 환경을 구분합니다.

```bash
python -m apps.api --config /path/to/gpu.toml --env-file /path/to/gpu.env --check-config
python -m apps.api --config /path/to/gpu.toml --env-file /path/to/gpu.env
```

설정 예제는 `configs/examples/gpu.toml`, API 스키마는 `configs/schemas/compute-v1/`,
요청·응답 예제는 `docs/gpu/examples/`에 있습니다.
`backend.python`은 모델을 실행할 기존 CUDA 환경의 Python입니다.
서비스는 loopback에서 수신하며 외부 접속은 기존 Tailscale HTTPS 경로를 사용합니다.
인증키를 소스나 명령행 인수에 기록하지 않습니다.

### Windows에서 WSL API 유지 (2026-10-05 복구)

GPU PC에서 마지막 WSL 명령이 끝난 뒤 Ubuntu가 `Stopped`가 되어,
`https://gateway.example.ts.net:8443`의 기존 Tailscale 프록시가 502를 반환했다.
WSL을 시작하면 `habitat-gpu.service`가 자동 실행되고 Windows의 `127.0.0.1:8100`도
응답했다. 즉 프록시 주소나 인증키 문제가 아니었다. Microsoft도
[systemd 서비스만으로 WSL 인스턴스가 유지되지 않음](https://learn.microsoft.com/en-us/windows/wsl/systemd)을 명시한다.

GPU Windows에 `HabitatOS-GPU-WSL` 예약 작업을 등록했다. `<gpu-user>` 로그인 때 제한된
사용자 권한의 숨김 PowerShell이 `wsl.exe -d Ubuntu --exec /usr/bin/sleep infinity`를
종료까지 기다리며 실행하고 종료코드를 반환한다. `Interactive` 로그인 유형으로
암호를 저장하지 않는다. 중복 실행은 `IgnoreNew`, 실행시간 제한은 `PT0S`, 실패 시
재시도는 1분 간격 최대 999회다. API 자체 재시작은 기존 systemd 서비스가 담당한다.
Tailscale의 `8443 → http://127.0.0.1:8100`, 방화벽, 전원 정책, 모델 가중치는 변경하지 않았다.

작업은 아래의 인라인 명령을 저장하므로 임시 파일이나 별도 실행 스크립트에 의존하지 않는다.
다른 GPU PC에서 같은 구성을 등록할 때는 해당 Windows 사용자로 로그인한 상태에서 실행한다.
이미 같은 이름의 작업이 있으면 먼저 내용을 대조하며, 이 명령은 강제로 덮어쓰지 않는다.

```powershell
$taskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskAction = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument '-NoProfile -NonInteractive -WindowStyle Hidden -Command "wsl.exe -d Ubuntu --exec /usr/bin/sleep infinity; exit $LASTEXITCODE"'
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$taskSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'HabitatOS-GPU-WSL' -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Principal $taskPrincipal
```

재부팅 후에는 **GPU PC의 `<gpu-user>` Windows 로그인이 필요하다.** 로그인 전이나 로그아웃,
절전·전원 종료 상태의 API 가용성을 보장하지 않는다. 화면 잠금은 로그아웃과 다르다.
로그인 후 작업을 수동으로 다시 시작하거나 확인하려면 GPU PC의 PowerShell에서 실행한다.

```powershell
Start-ScheduledTask -TaskName 'HabitatOS-GPU-WSL'
Get-ScheduledTask -TaskName 'HabitatOS-GPU-WSL' | Select-Object TaskName,State
wsl -d Ubuntu -- systemctl is-active habitat-gpu.service
```

17:58:40 KST 작업 시작 후 SSH를 닫고 수분 뒤 재접속하여, WSL 확인 명령을 실행하기
**전에** Windows loopback과 Tailscale HTTPS가 각각 정상적인 무인증 응답 401을
계속 반환함을 확인했다. 작업은 `Running`, API는 17:58:43 이후 같은 PID 227·재시작
0회였다. 실제 Pi의 기존 인증정보로 GPU `/v1/environment/health`와
`/v1/livescene/models`, Pi `/v1/livescene/models` 중계가 모두 HTTP 200을 반환했다.
환경 모델 상태는 `simulation_configured`, 등록 장면은 1개이고
`hardware_execution_allowed=false`를 유지했다. 이번 검증에서 Windows 재부팅·로그아웃을
강제로 수행하지 않았으며, 연결 복구를 실측 모델 검증이나 실제 분무 완료로 취급하지 않는다.

WSL systemd 서비스 설치 도구는 `scripts/provision_service.py`입니다.

```bash
sudo python3 scripts/provision_service.py --user <service-user> \
  --api-python /path/to/api-venv/bin/python \
  --gpu-python /path/to/gpu-venv/bin/python
```

기존 설정·인증키는 보존합니다. 서비스 파일 변경이 필요할 때만 내용을 검토한 후
`--replace-service`를 사용합니다. 설치 도구는 서비스를 즉시 시작하지 않습니다.

## 모델 및 출력 위치

- 환경 예측의 `HABITAT_ENV_MODEL_DIR`에는 `model_3sensors.npz`와 `training_report.json`이 필요합니다.
- 기본 위치는 프로젝트의 `var/models/environment_sim/`입니다. 기존 모델은 복사하지 않고 이 변수로 기존 GPU 모델 경로를 지정할 수 있습니다.
- `gpu.env`에 같은 변수를 추가하면 API가 자식 추론 프로세스에도 전달합니다.
- 환경 실험 소스는 `experiments/environment_sim/`에 있으며 학습·평가 출력도 위 모델 디렉터리에 기록합니다.
- LiveScene은 `[backend.livescene]`에 지정한 기존 manifest·모델·실행 환경을 사용합니다. 자세한 검증 범위는 [LiveScene 안내](livescene-sample.md)에 있습니다.
- 원본 데이터·가중치·렌더를 Windows 소스 폴더에 중복 다운로드하지 않습니다.

## API별 준비 상태

`/v1/gpu/health`는 3DGS 복원, `/v1/environment/health`는 환경 예측,
`/v1/livescene/health`는 등록 LiveScene 모델의 상태를 나타냅니다.
한 경로의 성공으로 다른 경로까지 준비되었다고 판단하지 않습니다.
환경 예측은 합성 데이터 모델이며 실제 장치 제어를 허용하지 않습니다.

### 신규 RGB 복원 준비 검사와 GPU 작업 잠금 — 2026-10-05

운영 설정의 `backend.name`은 검사 당시 `not_configured`였습니다. API Python 3.12에
Torch를 설치하지 않은 것은 오류가 아닙니다. 기존 `backend.python`은 CUDA 모델용
`/home/<gpu-user>/.venvs/habitat-gpu/bin/python`을 가리킵니다. `name=splatfacto`인 설정에서만
기존 `Backend.probe()`가 실행되므로, 비활성 설정의 `cuda_available=false`는 이 복원
backend에서 CUDA 준비를 확인하지 않았다는 뜻입니다. 환경 모델과 LiveScene의 별도
실행 결과를 부정하는 전역 GPU 판정이 아닙니다.

운영 파일을 바꾸지 않고 메모리의 설정 복사본으로 기존 probe를 실행했습니다.
RTX 4060에서 CUDA 행렬 계산과 gsplat 순전파·역전파가 **5.409초에 통과**했습니다.
Torch 2.1.2+cu118, Nerfstudio 1.1.5, gsplat 1.4.0, COLMAP 3.9.1과 기존 실행 도구를
확인했습니다. 새 의존성·학습·모델은 만들지 않았고 운영 설정의 해시는 보존했습니다.
이 검사는 모델 학습, 실제 카메라 입력, 사육장 복원 품질·형상 정확도의 합격 기록이 아닙니다.
[실제 준비 검사 결과](../../var/reports/commissioning/gpu-probe.json).

신규 RGB 작업 Worker도 LiveScene의 `backend.livescene.lock_file`을 공유합니다.
기존 운영 경로는 `/home/<gpu-user>/.local/share/habitat-gpu/livescene/reconstruction.lock`입니다.
LiveScene 공유 설정이 없는 서버에서만 `<storage_dir>/reconstruction.lock`을 사용합니다.
동일 GPU를 쓰는 네이티브 뷰어도 같은 잠금을 사용해야 하며, 실행 중인 잠금 파일을
삭제해 우회하지 않습니다. 파일 자체의 존재가 작업 실행 중이라는 뜻은 아닙니다.

- Worker는 잠금을 얻기 전에 작업을 `running`으로 바꾸지 않습니다. 다른 렌더/뷰어가
  점유하면 작업은 `queued`에 남고 짧은 취소 가능한 대기를 반복합니다.
- 현재는 COLMAP·학습·내보내기·검증을 포함한 작업 전체를 직렬화합니다. COLMAP도
  설정에 따라 CUDA를 사용할 수 있어 단계별 자원 스케줄러를 추가하지 않았습니다.
  작업 중 LiveScene 요청은 기존 `429 reconstruction_busy`로 응답합니다.
- 성공·오류·취소 시 파일 잠금을 해제합니다. 대기 중 종료는 작업을 선점하지 않고,
  선점 후 종료는 기존 `interrupted` 처리와 자식 프로세스 그룹 정리를 따릅니다.
- 환경 예측은 이 무거운 복원 작업 잠금을 사용하지 않습니다. 동시에 실행할 때의
  예측 지연과 GPU 메모리 여유를 보장하는 수치로 준비 검사 결과를 사용하지 않습니다.

실제 Pi의 기존 가상환경에서 선택 회귀검사 **3개를 6.719초에 통과**했습니다.
별도 프로세스의 잠금 보유 중 `queued`·선점 0회, 해제 후 실행, 대기 중 취소,
Worker 작업 중 LiveScene `429`, 성공·오류·취소 후 렌더 재개와 입력 해시 보존을
확인했습니다. 이 검사는 합성 HTTP/작업 결과를 사용하며 실제 GPU 학습 검증과 구분합니다.
[잠금 회귀검사 로그](../../var/reports/commissioning/worker-lock-tests.log).

### 0.4.10 운영 활성화 — 2026-10-05 20:06 KST (과거 기록)

선택 회귀검사와 독립 코드 검토 후 GPU 소스 0.4.10에서 운영 설정 12행의
`backend.name`만 `not_configured`에서 `splatfacto`로 변경했습니다. 나머지 TOML 값,
권한 `0600`, 소유자 UID/GID `1000:1000`은 그대로입니다. 공유 잠금이 비어 있고
`queued/running=0`임을 확인한 뒤, 잠금을 직접 보유한 상태에서 서비스를 정지하고
설정을 변경·재시작했습니다. 작은 원본 설정 백업은 성공 검증 후 제거했습니다.

- `habitat-gpu.service`: `active/running`, PID 2526, 종료 상태 0.
- `/v1/gpu/health`: HTTP 200, `status=ok`, `backend=splatfacto`, RTX 4060,
  `cuda_available=true`, `reconstruction_ready=true`.
- `/v1/livescene/health`: HTTP 200, 등록된 참조 장면 1개. 등록 모델을 렌더하는
  LiveScene의 `rgb_training_configured`는 계속 `false`입니다. 이번에 활성화한
  신규 정적 RGB 복원은 별도 Splatfacto 작업 경로입니다.
- `/v1/environment/health`: HTTP 200, `simulation_configured`,
  `hardware_execution_allowed=false` 유지.

활성화 전후 기존 `failed` 작업 5개의 전체 행 해시가 같았고, 대기·실행 중 작업은
0개였습니다. 등록 manifest·장면 설정·30,000스텝 체크포인트 및 환경 모델/기록
9개 파일의 해시도 모두 보존했습니다. 활성화 절차에서 새 작업을 제출하거나
학습을 시작하지 않았습니다. [운영 활성화 검증 기록](../../var/reports/commissioning/software-r15-20261005-gpu-activation.json).

RGB 등록·업로드·COLMAP·학습·PLY 검증과 Pi 수신은 기존 파이프라인을 사용합니다.
보존된 RGB 입력으로 수행하는 소프트웨어 통합 시험과 별개로, 실제 사육장 입력의
복원 품질·형상 정확도와 실제 센서·분무 동작은 별도로 평가해야 합니다.

### 0.4.11 카메라 메타데이터 갱신과 서비스 확인 (과거 기록)

카메라 설정의 `expected_model`은 기본 `None`인 선택 메타데이터이며, USB VID/PID나
실제 장치 자동 식별 결과가 아닙니다. 실제 Pi 릴리스 `0.4.11-7967566bb2ea`의 카메라
설정 3개에 `SMG-A USB-OV5628-A (OV5693, Auto Focus/120deg)`를 적용했고 모두
`waiting_usb_port_binding`을 유지합니다. 관련 카메라/API 선택검사 11개가 0.74초에
통과했고 예제 설정 검사도 통과했습니다. [Pi 적용 확인](../../var/reports/commissioning/software-r15-20261005-camera-model.json).
이는 0.4.10 전체 회귀검사 386개 통과·7개 건너뜀·subtest 231개 통과와 별도 기록입니다.

GPU 서비스는 21:22:11 KST에 시작한 PID 2723으로 `active/running`, 종료 상태 0을
확인했습니다. 21:28:34 KST에 소스 버전 0.4.11·관련 5개 파일의 해시와 다음 실제 응답을
검증했습니다. 위의 PID 2526·0.4.10 활성화 기록을 새 버전 실행 증거로 대신하지 않습니다.

| API | 0.4.11 실제 확인 |
|---|---|
| `/v1/gpu/health` | HTTP 200, `ok`·`splatfacto`·CUDA·`reconstruction_ready=true` |
| `/v1/environment/health` | HTTP 200, `simulation_configured`·`field_validated=false`·`hardware_execution_allowed=false` |
| `/v1/livescene/health` | HTTP 200, `configured`·참조 모델 1개·`rgb_training_configured=false` |

이번 배포 확인에서 실제 카메라 촬영·FPS 측정·새 학습·렌더를 수행하지 않았고, GPU 설정·
인증정보·모델도 변경하지 않았습니다. [GPU 0.4.11 확인 기록](../../var/reports/commissioning/software-r15-20261005-gpu-camera-model.json).

## 0.4.4 운영 통합 (과거)

GPU의 이전 `habitat.compute.*` 실행 경로는 `habitat.gpu.*`로 바뀌었습니다.
`python -m apps.api` 진입점과 HTTP 계약은 유지합니다. Pi의 `habitat.compute.*`는 유지합니다.
GPU 운영 소스는 `C:/Users/<user>/Desktop/HabitatOS`, WSL 경로는
`/mnt/c/Users/<user>/Desktop/HabitatOS`입니다. 이전 학과 폴더의 중복 소스는 제거했습니다.
API 환경은 `/home/<gpu-user>/.venvs/habitat-api`, 모델 환경은 기존 `habitat-gpu`와
`habitat-livescene`을 사용합니다. 모델별 Python/CUDA 의존성이 달라 임의로 합치지 않습니다.
환경 모델은 `/home/<gpu-user>/.local/share/habitat-gpu/models/environment`에서 읽습니다.
Pi에서 세 사육장의 CUDA 예측, 다른 매장 ID 거절(403), 등록 모델의 PNG 수신·해시 검사를 확인했습니다.
0.4.4 당시 `/v1/gpu` Splatfacto 신규 학습은 비활성으로 유지했습니다. 현재 준비 검사와
활성화 조건은 위 2026-10-05 절을 따릅니다. 환경 예측과 등록 LiveScene 렌더의 준비 상태는
별도 경로에서 확인합니다.
