# GPU 데스크톱 Codex Goal 프롬프트

이 문서는 데스크톱에서 수행할 목표와 검증 기준이다. GPU 서버가 이미 구현됐다는 뜻은 아니다. Pi 클라이언트 0.3.0 / GPU API 계약 1.0.0을 기준으로 작성했다.

## 데스크톱에서 바로 시작하기

`HabitatOS_GPU_Desktop_Handoff_v1.zip`을 데스크톱 작업 폴더에 풀고 그 폴더를 VS Code와 Codex에서 연다. 기존 GPU 프로젝트가 있으면 해당 폴더에서 인계 자료 위치를 알려준다. 아래 시작 명령을 복사한다.

```text
/goal 이 폴더의 desktop-codex-prompt.md를 읽고 전체 작업 지시와 완료 기준 A~D에 따라 HabitatOS GPU 서버를 구현하고 검증해줘. 전체 HabitatOS 저장소라면 docs/gpu/desktop-codex-prompt.md를 읽어줘. 기존 코드와 AGENTS.md부터 확인하고, Pi GPU API 계약 1.0.0을 유지하면서 실제 CUDA 연산, 실제 다시점 사진의 COLMAP→Splatfacto→Gaussian PLY 복원, Tailscale HTTPS 서비스와 Pi 인계 자료까지 완성해줘. GPU_API_RESULT.md에 검증 결과와 다음 작업을 갱신하며 진행해줘. 실제 Pi 통신은 별도로 검증하고 mock 통과를 실제 복원이나 연결 성공으로 보고하지 마.
```

`/goal`을 사용할 수 없다면 아래 **전체 작업 지시** 코드 블록을 일반 요청으로 붙여 넣는다. Goal 사용 방법은 [OpenAI 장기 작업 안내](https://learn.chatgpt.com/docs/long-running-work)를 참고한다.

## 전체 작업 지시

```text
HabitatOS의 GPU Compute Node를 이 데스크톱에 구현하고 검증해줘. Pi가 업로드한 다시점 사진을 실제 GPU에서 COLMAP→Splatfacto 3DGS로 복원하고 검증된 Gaussian PLY를 반환할 수 있게 만들어줘. 아래 완료 기준 A~D가 이 Goal의 완료 조건이다. 계획·mock 서버·설치 안내만으로 완료하지 마.

먼저 작업 위치의 AGENTS.md, 기존 소스·entrypoint·설정·테스트를 확인해줘. 첨부 묶음의 README.md, gpu-api-contract.md, pi-profile.json, examples/, schemas/compute-v1/, desktop-result.template.json, pi-operations.md를 읽어줘. 전체 Pi 저장소에서는 대응 경로가 docs/gpu/, configs/schemas/compute-v1/, docs/operations/compute-client.md이다. ZIP에 Pi 소스가 있다고 가정하지 마. api/edge-sync.openapi.json은 Pi→SaaS 센서 API 참고 자료이며 GPU API와 구분해줘.

[프로젝트와 역할]
- 매장마다 Raspberry Pi가 여러 사육장의 ESP32·센서·장치·카메라를 관리한다.
- Pi가 온습도·조명·급수 출력 및 명령 이력을 SaaS로 직접 보낸다.
- SaaS는 민우가 운영하는 https://habitatos.kro.kr이며 센서 수신 경로는 POST /v1/edge/sync다. 2026-09-20 기준 운영 사이트와 기존 샘플 조회는 확인됐으나 신규 Pi 송신의 정상 접수 ACK는 아직 미확인이다. SaaS 인증 문제 때문에 독립적인 GPU 서버 개발을 중단하지 마.
- 이 데스크톱은 RTX 4060을 사용하는 분석 서버다. 사용자 제공 SSH 정보는 <gpu-user>@100.100.211.20이다. 현재 OS, Tailscale 소속, GPU/VRAM, CUDA, 사용 가능한 프로젝트 폴더는 먼저 직접 확인해줘.
- Pi 쪽 개발은 별도 Codex 세션에서 진행한다. 이번 Goal은 GPU 서버와 Pi 연결 인계까지다. GPU→SaaS 결과 전송은 수신 계약 합의 이후의 후속 작업이다. 양쪽 세션은 자동으로 파일이나 결정을 공유하지 않는다.
- Pi GPU 클라이언트 0.3.0은 별도 worker로 구현되었다. 계약 v1.0.0에 맞춘 촬영 등록·업로드·작업 조회·결과 검증과 합성 HTTP 통합 테스트가 있고 실제 GPU API 연동은 아직 미확인이다. schemas/compute-v1/ JSON Schema도 함께 검토해줘.

[Pi 정보: pi-profile.json의 observed_at 시점 관측값과 아래 날짜를 명시한 후속 네트워크 관측; 현재 상태는 연결 시 재확인]
- Raspberry Pi 5 Model B Rev 1.1 / Linux aarch64 / Python 3.13.5
- 호스트명 habitat-pi
- Pi 프로젝트 경로 /home/<gateway-user>/Desktop/habitat (데스크톱 로컬 경로가 아님)
- site_id STORE-001, gateway_id PI-001
- 기본 예시 설정은 CAGE-001 / ESP32-001의 시뮬레이션 1개다. 현재 실행 프로세스 설정을 확인했다는 뜻은 아니다.
- 계획은 새 20×20×30 cm 사육장 3개이며 CAGE-002/003과 대응 노드 ID는 아직 Pi의 기본 설정에 등록하지 않았다.
- pi-profile.json의 기존 관측에서는 Tailscale이 없었다. 이후 2026-09-21에 Pi Tailscale 1.102.4를 설치했고 01:55~01:56 KST에는 등록 완료(Running/online), Pi IPv4 100.102.106.40, DNS habitat-pi.tail292da2.ts.net과 GPU까지 direct ping 3회 성공(6~7 ms)을 확인했다. GPU peer DNS는 <gateway-user>.tail292da2.ts.net이다. 최신 네트워크 상태는 pi-operations.md(전체 저장소에서는 docs/operations/compute-client.md)의 날짜별 기록을 확인해줘. GPU HTTPS 서비스·API·SSH는 아직 미확인이다. 관측 DNS를 배포 완료 HTTPS 주소로 간주하지 마. <gpu-user>@100.100.211.20은 GPU 데스크톱 정보이며 Pi 주소가 아니다.
- 실제 카메라 영상, 다시점 촬영 데이터, 열화상 장비, 교정 데이터는 아직 확보되지 않았다.
- 사용자는 Pi에 실제 센서·제어 장치를 아직 연결하지 않았다고 확인했다. 웹 샘플을 실측으로 취급하지 마. 센서가 없어도 이미지 폴더 업로드와 GPU API 시험은 가능하다.

[작업 위치와 환경]
- 사용자가 지정한 작업 폴더를 사용하고 기존 프로젝트가 있으면 확장해줘. 기존 구현이 없을 때만 필요한 구조를 만들어줘. 매장별 소스 복사본, 불필요한 중첩 폴더, 빈 추상화 계층을 만들지 마.
- OS, NVIDIA 드라이버, nvidia-smi, 실제 GPU와 VRAM, Python/WSL 상태를 읽기 작업으로 점검해줘.
- Windows이면 WSL2에서 GPU 연산을 사용할 수 있는지 확인하고, 가능한 경우 Linux 도구를 사용하는 3DGS 실행 환경으로 검토해줘. WSL 안에 Linux 디스플레이 드라이버를 설치하지 말고 NVIDIA의 공식 WSL 안내를 따라줘.
- PyTorch/CUDA/Nerfstudio가 함께 지원하는 환경을 공식 문서로 확인해서 별도 환경을 구성하고 버전을 기록해줘. Pi의 Python 3.13.5를 데스크톱에 억지로 맞추거나 Pi의 .venv/ARM 휠을 복사하지 마.
- 계정 로그인, 관리자 권한, 재부팅이 필요한 작업은 필요 조건을 정확히 알려줘. 해당 조건과 무관하게 가능한 코드·로컬 API·테스트 작업은 계속해줘.
- 실제 GPU/VRAM과 디스크 여유 공간을 확인하고 VRAM 용량이나 OS를 추측하지 마. 설정과 비밀값은 소스 밖에서 주입하고 입력 사진·학습 출력·로그·cache는 runtime 저장소로 분리해줘.
- 기존 구조 조사 → 재사용/변경 경계와 검증 명령 결정 → 구현 → 테스트/수정 → 문서 갱신 순서로 진행해줘. 진행 가능할 때는 계획 제시 후 매 단계 승인을 요청하지 말고 실행해줘.
- GPU_API_RESULT.md를 진행 기록과 최종 인계 문서로 재사용해줘. 단계별 상태, 실행 명령, 관측 결과, 결정 이유, 다음 작업을 갱신하고 같은 목적의 임시 보고서를 계속 만들지 마.

[첫 구현 범위: 첨부 GPU API 계약 v1.0.0 준수]
- GET /v1/gpu/health
- POST /v1/gpu/captures (새 요청·동일 재요청 모두 200)
- GET /v1/gpu/captures/{capture_id}
- PUT /v1/gpu/captures/{capture_id}/files/{file_id}
- POST /v1/gpu/jobs (새 요청·동일 재요청 모두 202)
- GET /v1/gpu/jobs/{job_id}
- GET /v1/gpu/jobs/{job_id}/artifacts/{artifact_id}
- 정확한 필드, HTTP 상태, 멱등성, 업로드 완료 판정, 오류 규칙은 gpu-api-contract.md와 examples/를 기준으로 구현해줘.
- JSON Schema만으로 표현되지 않는 제약도 계약 문서에서 확인해줘. 응답에 계약 밖 필드를 추가하지 마. Pi는 ID·scope·요청 필드·geometry/placement revision을 엄격하게 비교한다.
- Pi가 파일과 메타데이터를 올리고 GPU가 작업을 수행하는 방식이다. GPU가 Pi의 내부 API에 들어가 장치를 제어하는 구현은 하지 마.
- 모든 API에 Bearer 인증을 적용하고 토큰에 등록된 site_id/gateway_id/cage_ids 권한을 조회·다운로드까지 검사해줘. ID·권한은 설정으로 관리하고 business logic에 고정하지 마.
- GPU 인증은 HABITAT_GPU_TOKEN이며 SaaS의 HABITAT_CLOUD_TOKEN 및 웹 로그인 비밀번호와 별개다. 기존 GPU 토큰이 없으면 충분히 무작위인 32자 이상 공백 없는 ASCII 값을 한 번 생성해 소스 밖 비밀 설정에 보관하고 scope를 등록해줘. 재기동마다 재발급하지 마. 다른 Pi도 동일 코드와 개별 자격증명/scope 설정으로 추가할 수 있게 해줘.
- Pi는 서버에 등록한 같은 값을 HABITAT_GPU_TOKEN으로 설정해야 한다. 토큰 값은 채팅·소스·명령 인자·로그·테스트 결과·공유 문서에 적지 마. 인계에는 보관 위치/전달 절차·환경변수명·설정 여부·scope만 남겨줘.
- 기본 API 바인딩은 127.0.0.1:8100, 외부 접근은 Tailscale 내부 HTTPS로 구성해줘. Tailscale이 Windows 호스트에 있고 API가 WSL에 있다면 포워딩 경로를 실제로 확인해줘.
- Pi에 반환할 base_url은 /v1/gpu를 붙이지 않은 실제 HTTPS origin이다. 100.100.211.20을 인증서 호스트명으로 가정하지 말고 실제 Tailscale DNS/인증서를 확인해줘. TLS 검증 해제나 리다이렉트 토큰 전달, 공개 인터넷 노출을 추가하지 마.
- capture_id/job_id는 Pi가 생성한 UUID를 유지한다. DB에 메타데이터/작업을 저장하고, 같은 요청은 중복 실행하지 않으며 같은 ID에 다른 내용이면 충돌을 반환해줘.
- 파일 크기·해시·이미지 형식을 검사하고 임시 저장 후 원자적으로 확정해줘. 파일 경로는 서버가 정하고 파일명으로 디렉터리 탈출을 허용하지 마.
- JPEG/PNG 3~500개, 장당 20 MiB, 묶음 2 GiB 제한을 지켜줘. Pi는 장당 20 megapixel도 제한한다. 업로드를 제한된 크기로 스트리밍하고 실제 적용 limits를 health에 표시해줘.
- verified/missing 목록은 manifest 전체 file_id의 중복 없는 서로소 분할이어야 한다. 재전송은 파일 단위이며 byte-range resume을 구현했다고 표현하지 마.
- 모든 이미지의 수신·검증이 끝나야 복원 작업을 받도록 해줘.
- 작업 큐와 실제 GPU 실행을 분리하고 처음에는 3DGS 작업을 한 번에 1개만 실행해줘. API 응답 중에 학습 완료를 기다리지 마.
- 작업 중 프로세스가 재시작되면 실행 중 작업을 interrupted로 기록해줘. 실제 체크포인트 복구를 검증하기 전에는 자동 성공/자동 재개로 처리하지 마.
- 대기 중 queued 작업은 영속 보존하고 상태/stage 조합을 계약대로 유지해줘. 시간 초과, 디스크 부족, subprocess 실패, GPU 없음/VRAM 부족을 명시적인 실패로 처리해줘. 사용자 입력으로 임의 shell 명령을 실행하게 하지 마.
- health.backend는 splatfacto/mock/not_configured만 허용한다. 실제 backend와 CUDA 준비가 확인된 경우에만 reconstruction_ready=true다. mock은 false이며 현 Pi worker는 이 상태에서 job을 제출하지 않는다. backend 미준비 시 health는 200/degraded, job은 503/backend_not_ready로 응답해줘.

[실제 3DGS 실행]
- 계약의 kind=3dgs, preset=preview에 맞춰 COLMAP 카메라 자세 복원 → Splatfacto 학습 → Gaussian Splat PLY 내보내기 경로를 구현해줘. 실제 VRAM에 맞춘 해상도·학습 설정·실행 제한은 서버 설정으로 관리하고 기록해줘.
- GPU를 실제 사용할 수 있는지 작은 연산으로 확인한 뒤 복원 의존성과 실행 어댑터를 연결해줘.
- 사육장 다시점 데이터가 없으면 사용 조건이 명확한 공식 공개 다중 시점 데이터나 이미 있는 적절한 데이터로 실제 복원을 검증해줘. 출처·라이선스·사용 범위·전처리를 기록하고 공개 샘플 검증과 실제 사육장 검증을 구분해줘. 데이터를 확보할 수 없으면 실복원은 미완료로 남겨줘.
- 고정 카메라의 같은 구도 연속 사진이나 합성 테스트 이미지를 실제 다시점 검증으로 취급하지 마. 모의 작업을 실제 학습 성공으로 보고하지 마.
- 단순 점군 PLY나 샘플 파일을 복사한 것을 3DGS 결과로 표시하지 마. 종료 코드·출력 파일·내용을 확인해야 succeeded로 처리해줘.
- 성공 결과에는 artifact_id, 형식, 파일 크기, SHA-256, 모델/도구 버전, geometry/placement revision, metric_scale_verified를 포함해줘.
- 각 정보는 계약에서 정한 필드 위치에 넣고, Gaussian PLY 필수 속성·vertex payload와 정확한 상대 download_path를 검증해줘. 다운로드에 Content-Length와 X-Content-SHA256을 제공하고 identity encoding으로 전달해줘. 프록시 자동 압축으로 bytes 검증을 깨뜨리지 마.
- v1에서는 metric_scale_verified=false로 반환해줘. 20×20×30 cm라는 계획만으로 복원 좌표의 실제 축척/보정이 검증되지 않는다. 온도 투영용 실측 좌표가 확보됐다고 말하지 마.
- 렌더/뷰어로 복원 품질도 확인하고 결손·시점 한계를 기록해줘. API 성공만으로 사육장 디지털 트윈 품질을 보장하지 마.

[후속 기능과 SaaS 연동]
- SaaS 모델 등록/웹 3D 표시, 실시간 카메라 스트리밍, 도마뱀 탐지·추적·행동 분석, 열화상 정합은 후속 범위다. 이번 Goal에 필요 없는 빈 모듈이나 임시 endpoint를 만들지 마.
- 일반 NoIR 카메라로 섭씨 온도를 만들지 마. 열화상과 3DGS 결합은 온도 배열·시각·내외부 보정값이 준비된 다음 단계다.
- GPU 결과용 SaaS 수신 계약은 아직 합의되지 않았다. /v1/edge/sync에 GPU 이벤트를 임의 추가하거나 private GPU download_path를 공개 모델 URL로 전달하지 마. 필요한 결과 metadata와 저장/표시 연동 항목은 인계 문서에 정리하고 saas_delivery는 실제 시험 전까지 not_run으로 남겨줘.
- SaaS·실카메라·센서가 없다는 이유로 독립적으로 가능한 서버 구현을 남겨두지 마.

[Goal 완료 기준]
A. API 호환성: 실제 HTTP 서버로 촬영 등록→파일 PUT→job→polling→artifact 다운로드와 아래 실패 사례를 정식 테스트로 검증한다. mock/API 시험과 실제 backend 시험을 구분한다.
B. 실제 GPU 복원: 실제 CUDA 연산, 실제 다시점 사진의 COLMAP/Splatfacto 실행, 다운로드한 Gaussian PLY의 크기·해시·내용 및 품질 확인 증거가 있다. 데이터 출처·실행 시간·관측 VRAM 사용량·도구 버전·artifact 정보를 기록한다.
C. 데스크톱 서비스: 재현 가능한 설치·기동·중지·재시작 안내, 영속 DB/파일, 인증된 Tailscale HTTPS 주소와 실제 GPU health를 확인한다. 데스크톱 내부 HTTPS 시험은 Pi 접근 성공과 구분한다.
D. 인계: GPU_API_RESULT.md, desktop-result.json, GPU OpenAPI를 준비하고 실제 환경·주소·scope·단계별 검증 상태·남은 조건을 기록한다. 비밀값은 포함하지 않는다.
E. 실제 Pi 연결은 접근 준비 시 추가 수행한다. 기존 Pi worker로 health→enqueue→work→상태 조회→artifact 검증 완료까지 확인한다. Pi 접근이 없으면 필요한 설정·실행 명령·예상 확인 지점을 인계하고 pi_to_gpu=not_run으로 둔다. 이때 A~D를 충족한 데스크톱 완료와 E의 미완료를 명확히 구분한다.
A~D 중 필수 항목이 미완료면 Goal을 완료 처리하지 말고 독립적으로 가능한 작업을 마친 뒤 실제 장애 원인과 필요한 외부 조치를 기록한다.

[검증과 인계]
- 실제 API로 capture 등록 → 파일 PUT → job 요청 → 상태 조회 → artifact 다운로드를 시험해줘.
- 잘못된 토큰, 다른 매장/Pi/사육장, 중복 요청, ID 충돌, 잘못된 해시, 누락 파일, 저장 실패, 재시작, GPU 없음/VRAM 부족을 검사해줘.
- OpenAPI 명세와 실행 명령, 설치한 버전, 검증한 데이터와 관측 결과를 남겨줘.
- 실제 Pi가 아직 연결되지 않았으면 localhost 테스트와 Pi↔GPU 실통신 시험을 구분해줘.
- Pi 명령은 pi-operations.md(전체 저장소에서는 docs/operations/compute-client.md)를 따라줘. work --once는 한 번 진행할 뿐 완료까지 기다리지 않는다. 재시도하려고 enqueue를 반복하면 새 job이 생기므로 기존 job의 worker/retry를 사용해줘.
- GPU_API_RESULT.md와 desktop-result.json을 만들어 Pi 세션에 전달할 주소·계약 버전·상태·남은 조건을 정리해줘. desktop-result.template.json을 사용하고 비밀값은 빼줘.
- 공통 계약 변경이 불가피하면 기존 문서를 조용히 바꾸지 말고 변경 항목과 버전, Pi가 바꿔야 할 부분을 명시해줘.
- 마지막에는 변경 파일·검증 결과·실제 GPU/샘플/Pi 각각의 검증 범위·서비스 상태·인계 파일 경로·Pi의 다음 작업을 한국어로 간결히 보고해줘.
```
