# Pi 세션에서 맡을 작업

2026-09-19: **Pi GPU 클라이언트 0.3.0 구현 완료, 실제 GPU 연결 검증 전**이다. 실행 방법과 복구 절차는 [Pi 운영 안내](../operations/compute-client.md)에 있다. GPU 복원 코드는 데스크톱 Codex가 담당한다.

2026-09-21 01:55~01:56 KST: **Pi Tailscale 등록과 GPU 데스크톱까지 direct ping 확인 완료**. Pi IPv4는 `100.102.106.40`이며 `100.100.211.20`에서 3회 응답(6~7 ms)을 받았다. 실제 GPU API 연동과 복원은 별도 미확인이다.

## Pi에서 구현·검증한 부분

- `apps/worker` 실행부, `habitat/compute` 계약·HTTP adapter·작업 흐름, `habitat/persistence/compute.py` 영속 큐를 추가했다.
- 별도 TOML과 `HABITAT_GPU_TOKEN`을 사용한다. 매장/Pi/cage/revision은 기존 gateway 설정에서 읽는다. 소스에 실제 IP나 토큰을 고정하지 않는다.
- 사진 폴더를 worker 저장소에 복사·검증하고 capture/file/job ID와 해시를 전송 전에 보존한다.
- GPU가 누락으로 반환한 파일만 업로드한다. 같은 job ID로 재시도하고 상태를 조회한다.
- 응답 scope/revision/ID, 상대 다운로드 경로, 파일 크기·SHA-256·Gaussian PLY 구조를 검증한다. 비정상 파일과 외부 리다이렉트를 거절한다.
- worker와 DB는 제어/SaaS 프로세스와 분리된다. 기본 비활성화이며 별도 서비스 템플릿을 제공한다.
- 계약/내구성 테스트 및 실제 CLI+loopback HTTP 왕복을 통과했다. GPU 응답 시간 초과 중 가상 팬 ACK와 SaaS 모의 수신 서버의 계속된 수신도 검증했다.

모의 서버와 합성 사진/PLY를 사용한 시험이다. 실제 4060 연산·다시점 복원·Tailscale 접속·실물 ESP32 제어는 이 결과로 입증하지 않는다. 새 프로그램은 기존 0.2.0 tar.gz에 포함되지 않는다.

## 실제 GPU 연결을 위해 필요한 부분

1. **완료(2026-09-21):** 이 Pi에 Tailscale을 설치하고 사용자 로그인·등록 후 GPU 데스크톱까지 Tailscale 통신을 확인했다.
2. Pi의 Tailscale IP는 `100.102.106.40`으로 확인했다. 다음은 데스크톱의 API 노출 위치를 확인한다. 데스크톱이 Windows+WSL이면 Tailscale에서 WSL의 API까지 실제 도달하는지 확인한다.
3. 데스크톱의 `desktop-result.json`과 OpenAPI를 받아 계약 버전·HTTPS base URL·등록된 cage 범위를 확인한다.
4. 양쪽 환경에 같은 GPU용 토큰을 설정하고 Pi에서 `GET /v1/gpu/health`를 호출한다. API 접근, CUDA 인식, 실제 복원 준비를 각각 확인한다.
5. 작은 파일 묶음으로 등록·전송·중복 재요청을 확인한 다음, 실제 다시점 이미지로 복원·결과 다운로드를 시험한다.

최초 목표는 **사진 폴더 하나가 Pi에서 GPU까지 전달되고 실제 3DGS 결과가 생성되는 것**이다. 처음부터 카메라 3대·영상 스트리밍·추론·열화상을 한 번에 결합하지 않는다.

## 카메라와 열화상은 다음 입력 단계

- 카메라 모델·개수·연결 방식을 결정하면 촬영 프로세스와 영상 전달 프로세스를 연결한다. 사육장 3개 계획을 Pi의 설정과 장치 등록에 반영한다.
- 고정 카메라 영상에서 사진만 여러 장 뽑아 다시점 입력이라고 부르지 않는다. 초기 3DGS용으로 실제로 다른 위치에서 본 영상이 필요하다.
- 실시간 스트림 주소와 카메라 ID를 GPU 영상 분석 모듈에 등록하는 계약은 따로 확정한다.
- 열화상 배열과 교정 데이터가 준비되면 시각/좌표계/revision을 붙여 전달한다. 일반 NoIR 영상은 온도 배열 입력을 대신하지 못한다.

## 데스크톱 결과가 준비되면

`desktop-result.json`, 생성한 OpenAPI, 실제 HTTPS origin과 계약 버전 1.0.0을 Pi에 전달한다. 인증 토큰 값은 채팅 대신 각 장비 환경변수에 설정한다. Pi에서는 `check-config → health → 실제 사진 enqueue → work → show` 순서로 확인한다. 현재 기본 설정은 CAGE-001 한 개이며 세 사육장을 실제 운영하려면 검증한 cage/device mapping을 설정 파일에 추가한다.
