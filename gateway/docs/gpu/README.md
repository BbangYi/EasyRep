# 데스크톱 GPU 구현 인계 자료

이 묶음은 **데스크톱 Codex가 GPU 서버를 구현할 때 읽을 작업 지시서와 공통 계약**이다. GPU 서버 프로그램이나 설치 완료 파일이 아니다. Pi 세션은 인계 자료와 Pi 클라이언트 0.3.0을 구현했다. 2026-09-21 Pi Tailscale 등록과 GPU 데스크톱까지의 direct ping을 확인했다. GPU 서비스 설치·API 연동·실제 복원은 이 Pi 세션에서 아직 확인하지 않았다.

## 데스크톱에서 시작하는 방법

1. 전달받은 `HabitatOS_GPU_Desktop_Handoff_v1.zip`을 데스크톱의 작업 폴더에 푼다. 기존 프로젝트가 있으면 해당 작업 위치를 Codex에 알려준다.
2. 그 폴더를 열고 Codex를 실행한다. Pi의 `/home/<gateway-user>/Desktop/habitat`는 **Pi 내부 경로**이므로 데스크톱에서 같은 위치가 있다고 가정하지 않는다.
3. [desktop-codex-prompt.md](desktop-codex-prompt.md)의 **데스크톱에서 바로 시작하기**에 있는 `/goal` 명령을 입력한다. `/goal`을 사용할 수 없다면 같은 문서의 **전체 작업 지시** 코드 블록을 일반 요청으로 붙여 넣는다.
4. 데스크톱이 실제로 파악한 환경과 완성한 API 정보를 `GPU_API_RESULT.md`, `desktop-result.json`, OpenAPI로 돌려받는다. 결과 파일을 Pi 프로젝트에 전달하고 Pi 세션에서 후속 연결을 진행한다.

데스크톱이 Windows이고 Linux 3DGS 도구를 사용한다면 WSL2 실행 환경을 검토한다. NVIDIA는 WSL2 CUDA 실행을 지원하며 Windows 드라이버를 사용하므로 WSL 내부에 Linux 디스플레이 드라이버를 별도 설치하지 않도록 안내한다. 실제 설치 조합은 데스크톱에서 확인한다. [NVIDIA WSL 공식 안내](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)

## 제공하는 파일

| 파일 | 용도 |
|---|---|
| [desktop-codex-prompt.md](desktop-codex-prompt.md) | Goal 시작 명령, 전체 작업 지시, 단계별 완료·검증 기준 |
| [gpu-api-contract.md](gpu-api-contract.md) | Pi와 GPU가 함께 따를 경로·필드·상태·오류·재시도 규칙 |
| [pi-profile.json](pi-profile.json) | 2026-09-18에 관측한 Pi 환경과 당시 기본 설정. 비밀값 없음; 최신 네트워크 상태는 운영 기록 참조 |
| [desktop-result.template.json](desktop-result.template.json) | 데스크톱이 확인·구현 결과를 채워서 Pi 세션에 돌려줄 형식 |
| [pi-work-plan.md](pi-work-plan.md) | Pi 클라이언트 구현 상태와 실제 연결 순서 |
| [compute JSON Schema](../../configs/schemas/compute-v1/) | Pi 모델에서 생성한 요청·응답·설정 형식; ZIP에서는 schemas/compute-v1/ |
| [examples](examples/) | 촬영 등록·작업 요청·상태·health의 문서용 JSON 예시 |

압축파일 안의 `api/edge-sync.openapi.json`은 기존 Pi→SaaS 센서 수신 규격이다. GPU API 명세로 재사용하지 않는다. 데스크톱 구현은 GPU 계약에 맞는 별도 OpenAPI를 생성해야 한다.

## 데스크톱에 전달할 Pi 정보

아래 정보는 `pi-profile.json`의 `observed_at` 시점에 수집한 관측값이며, Tailscale·GPU 네트워크 항목에는 2026-09-21 확인 결과를 반영했다. 설정 확인 대상은 `config/simulation.toml` 기본 설정이며 현재 실행 중인 프로세스 설정을 추정한 것이 아니다. 실제 연결 시 현재 설정과 네트워크를 다시 확인한다.

| 항목 | 확인 결과 |
|---|---|
| 하드웨어 | Raspberry Pi 5 Model B Rev 1.1 |
| 호스트명 | habitat-pi |
| 환경 | Linux / aarch64 / Python 3.13.5 |
| 프로젝트 경로 | /home/<gateway-user>/Desktop/habitat |
| 매장·Pi ID | STORE-001 / PI-001 |
| 현재 기본 사육장 | CAGE-001 / ESP32-001, simulated |
| 시제품 목표 | 20×20×30 cm 새 사육장 3개 |
| Tailscale | 2026-09-21 01:55 KST 등록 완료, Running/online. Pi IPv4 `100.102.106.40`, DNS `gateway.example.ts.net`. 상세 [운영 기록](../operations/compute-client.md) |
| 사용자 제공 GPU 주소 | <gpu-user>@100.100.211.20; peer online, direct ping 3회 성공(6~7 ms). DNS `gateway.example.ts.net`; SSH·OS·HTTPS API는 미확인 |
| 카메라·촬영 자료 | 실제 연결/다시점 입력/교정 자료 아직 확보되지 않음 |

Pi는 GPU 서버에 **업로드와 작업 요청을 보내는 클라이언트**다. 처음 GPU 서버를 구현할 때 필요한 것은 매장·Pi·사육장 식별자와 공통 계약이다. Pi의 관측된 IPv4와 Tailscale DNS는 위 표에 있으며 다른 매장에 고정 설정으로 복사하지 않는다. Pi→GPU ping 성공은 GPU HTTPS API 제공이나 GPU→Pi 서비스 접근 성공을 의미하지 않는다.

두 Codex 세션의 대화·파일 변경은 자동 동기화되지 않는다. GPU 계약을 바꾸면 변경된 문서·버전·OpenAPI도 Pi 세션에 함께 전달한다. 서로 다른 버전으로 작업하지 않도록 첫 단계는 계약 v1.0.0을 따른다.

## 돌아와야 할 결과

실제 GPU 이름·VRAM·CUDA 준비 여부, 데스크톱 프로젝트 경로, 실행 명령, Tailscale HTTPS base URL, 계약 버전, 등록한 Pi/cage 목록, 로컬 테스트/실복원/실제 Pi 연결의 각각의 검증 상태가 필요하다.

토큰은 GPU 서버에 등록한 같은 값을 `HABITAT_GPU_TOKEN`으로 양쪽 환경에 설정한다. SaaS용 `HABITAT_CLOUD_TOKEN`과 별개의 자격증명이다. 결과 JSON에는 **환경 변수 이름과 설정 여부만** 넣으며 토큰 값을 포함하지 않는다. Pi 클라이언트 실행은 [운영 안내](../operations/compute-client.md)를 따른다. Pi가 사용할 HTTPS 주소와 토큰 등록이 준비되면 [Pi 작업 순서](pi-work-plan.md)에 따라 실제 연결을 진행한다.

이번 Goal의 완료 기준 A~D는 API 계약 검증, 실제 GPU 복원, Tailscale HTTPS 서비스, Pi 인계 자료다. 실제 Pi 통신은 E로 따로 기록한다. 센서가 연결되지 않아도 이미지 폴더로 GPU 작업을 시험할 수 있다. SaaS 3D 표시·행동 분석·열화상 정합은 후속 범위다.

## 기술 근거

- [Nerfstudio 설치 안내](https://docs.nerf.studio/quickstart/installation.html): 데스크톱의 GPU/Python/CUDA 조합에 맞춰 환경 구성.
- [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve): 데스크톱 내부 API를 같은 Tailscale 네트워크에 HTTPS로 제공.
- [Tailscale 연결 유형](https://tailscale.com/docs/reference/connection-types): 실제 업로드 속도를 확인할 때 direct/relay 연결을 구분.
