# Pi ↔ GPU API 구현 계약 v1.0.0

2026-10-03: 이 문서의 Gaussian PLY 작업 계약은 유지한다. LiveScene은 별도 `GET /v1/livescene/health`, `POST /v1/livescene/render`를 추가했다. Pi의 `habitat.compute.livescene`에서 요청 식별자·scope·모델·카메라·상태·PNG 크기·SHA-256을 검증한다. 실제 Pi→GPU CUDA 렌더→Pi PNG 수신을 확인했으며, 공개 문 예제는 `source_kind=reference_dataset`, `field_validated=false`로 표시한다. 기존 `/v1/gpu/health`의 backend 상태로 새 LiveScene 렌더 준비 여부를 판단하지 않는다.

`apps.worker`의 `livescene-health`, `livescene-render --cage-id ... --model-id ... --camera-index 0 --state 0.0 --max-width 320 --output 새파일.png`를 별도 Compute 설정으로 실행한다. `--state`를 생략하면 해당 평가 프레임의 추정 상태를 사용한다. 출력 파일이 이미 있으면 덮어쓰지 않는다. 렌더 요청 시간 제한을 위해 이 클라이언트의 `timeout_s=60`을 사용한다. 429는 GPU 복원 작업 사용 중이며 재시도 가능한 응답이다. 등록 모델 렌더와 신규 RGB 학습, SaaS 표시 배포는 별도 기능이다.

이 문서는 **두 개발 환경이 함께 구현할 첫 GPU 인터페이스**다. Pi 송신 클라이언트는 프로그램 0.3.0에 구현되었다. 데스크톱 서버 실행과 실제 Pi 연결은 별도 확인 대상이다. Pi의 기존 `/v1/edge/sync` 센서 규격과 별개다. API payload의 `schema_version`은 정수 1이다.

## 환경 예측 실행 최적화 (2026-10-03)

기존 `GET /v1/environment/health`, `POST /v1/environment/predict` 주소와 응답 형식을 사용한다. GPU 작업자는 첫 요청에서 모델을 불러온 뒤 재사용한다. Pi의 요청 방식이나 설정 변경은 필요 없다. `history`는 정확히 30행×5열(네 센서 채널과 실행된 분무 시간), `sample_times`는 30개의 분 단위 시각이다. 이력의 유효성/범위/시각 검사를 유지하며 잘못된 입력은 422, 동시 요청은 429, 작업자 오류/기한 초과는 503으로 처리한다. 프로세스 장애 후 다음 요청에서는 새 작업자를 시작한다.

실제 Pi 5의 합성 입력 9회 전후 비교에서 중앙 응답 시간이 1.415475초→0.057560초였고 예측·분무 제안이 모두 같았다. 첫 요청은 2.092213초였다. 공개 예제 복원 렌더와 함께 실행한 9회는 중앙값 0.067904초였다. 측정은 실제 센서/동물 검증이 아니며 `SYNTHETIC_ONLY`, `field_validated=false`, `hardware_execution_allowed=false`를 유지한다. 모델 정확도나 촬영·학습 스텝 추천·행동 분류가 새로 학습됐다는 의미는 아니다.

## 연결과 권한

- GPU 서버 기본 바인딩: `127.0.0.1:8100`.
- 운영 시 Pi가 사용할 base URL: 데스크톱에서 설정 후 반환할 Tailscale HTTPS 주소. `100.100.211.20` IP 자체를 TLS 호스트명으로 가정하지 않는다.
- 모든 API에 `Authorization: Bearer <HABITAT_GPU_TOKEN>`을 사용한다. 기존 SaaS 토큰과 구분하고 32자 이상의 공백 없는 ASCII 토큰을 사용한다.
- 토큰은 허용 `(site_id, gateway_id, cage_ids)`에 묶는다. 조회·파일 다운로드에도 같은 권한을 검사한다. GPU가 Pi에 접속하는 역방향 제어는 없다.
- UUID는 RFC 형식 문자열, SHA-256은 소문자 16진수 64자리, 시각은 UTC 오프셋이 있는 ISO 8601이다. ID 이름은 기존 Pi와 같은 `[A-Za-z0-9_-]{1,64}`를 사용한다.
- JSON은 `application/json`, 파일은 `application/octet-stream`이다. URL에 인증키를 넣거나 리다이렉트로 다른 서버에 토큰을 전달하지 않는다.

## 요청과 응답

| 메서드·경로 | 요청 | 정상 응답 |
|---|---|---|
| `GET /v1/gpu/health` | 본문 없음 | `200`: API 상태, 실행 backend, GPU/CUDA·3DGS 준비 여부 |
| `POST /v1/gpu/captures` | CaptureManifest | `200`: CaptureStatus. 신규와 동일 요청 재시도 모두 200 |
| `GET /v1/gpu/captures/{capture_id}` | 본문 없음 | `200`: CaptureStatus, 누락된 file_id 목록 |
| `PUT /v1/gpu/captures/{capture_id}/files/{file_id}` | 원본 이미지 바이트 | `200`: FileReceipt. 동일 파일 재업로드도 200 |
| `POST /v1/gpu/jobs` | JobRequest | `202`: JobStatus. 신규·같은 요청 재전송 모두 202, 실제 처리 결과는 status 필드로 판단 |
| `GET /v1/gpu/jobs/{job_id}` | 본문 없음 | `200`: JobStatus |
| `GET /v1/gpu/jobs/{job_id}/artifacts/{artifact_id}` | 본문 없음 | `200`: 인증된 결과 파일 바이트. `Content-Length`, `X-Content-SHA256` 제공 |

각 예시의 JSON 키·자료형은 [examples](examples/)에 있고, Pi 모델에서 생성한 [JSON Schema](../../configs/schemas/compute-v1/)를 함께 제공한다. 예시의 이미지 이름과 해시는 문서용이며 실제 파일은 포함하지 않는다.

### CaptureManifest

필수 필드: `schema_version`, `capture_id`, `site_id`, `gateway_id`, `cage_id`, `geometry_revision`, `placement_revision`, `captured_at`, `capture_method`, `files`.

- `capture_id`는 Pi가 로컬에 먼저 저장한 UUID. 같은 등록 범위에서 같은 ID·같은 manifest는 같은 촬영 묶음을 반환한다. 같은 ID·다른 내용은 409.
- 두 revision은 1 이상 정수다. `capture_method`는 v1에서 `multiview_rgb`다.
- `files`는 3~500개. 이는 입력 경계일 뿐 복원 성공에 충분한 촬영 장수를 보장하지 않는다. file_id는 UUID이고 같은 manifest 안에서 고유하다.
- 각 file 필수값: `file_id`, `name`, `size_bytes`, `sha256`, `captured_at`. 이름은 경로가 없는 `.jpg`, `.jpeg`, `.png` 파일명이다. 이미지 하나는 최대 20 MiB, 묶음 총합은 최대 2 GiB로 시작한다. 이 한도는 구현 설정에서 줄일 수 있으며 health에 실제 한도를 반환한다.
- 등록 후 manifest는 불변이다. 이미지 변경이나 재촬영에는 새 capture_id를 사용한다.
- v1에는 실측 스케일/외부 보정 업로드를 포함하지 않는다. 따라서 v1 생성 결과의 `metric_scale_verified`는 false다. 시각적 3DGS 결과를 계측용 좌표로 취급하지 않는다.

### CaptureStatus와 FileReceipt

CaptureStatus 필수값: `schema_version`, `capture_id`, `site_id`, `gateway_id`, `cage_id`, `status`, `verified_file_ids`, `missing_file_ids`.

- status는 `uploading` 또는 `ready`. 모든 manifest 파일의 실제 크기·해시·이미지 형식 검사와 영속 저장이 끝나야 ready다. 알려지지 않은 file_id를 추가하지 않는다.
- FileReceipt 필수값: `schema_version`, `capture_id`, `file_id`, `size_bytes`, `sha256`, `status`. status는 `verified`다.
- 서버는 임시 파일에 스트리밍 수신하고 크기·해시·이미지 형식을 검사한 뒤 원자적으로 저장을 확정한다. 업로드 중 연결이 끊기면 해당 파일을 verified로 표시하지 않는다.
- Pi는 GET으로 미수신 파일을 확인하고 **파일 단위로 다시 업로드**한다. v1은 바이트 범위 재개를 지원한다고 가정하지 않는다.
- 저장 경로는 서버가 등록된 scope와 UUID를 기준으로 결정한다. Pi의 로컬 경로나 파일명을 서버 경로로 실행/해석하지 않는다.

### JobRequest와 JobStatus

JobRequest 필수값: `schema_version`, `job_id`, `capture_id`, `site_id`, `gateway_id`, `cage_id`, `kind`, `preset`.

- job_id는 Pi가 먼저 저장한 UUID. kind는 `3dgs`, preset은 첫 버전에서 `preview` 한 개다. preview의 이미지 축소·학습 반복 수·도구 버전은 GPU 서버 설정으로 관리하고 결과 metadata에 기록한다.
- 명령 문자열이나 임의의 CLI 인자를 요청으로 받지 않는다. 구현된 preset만 허용한다.
- capture 소유권과 ready 상태를 확인한 뒤 작업을 DB에 저장하고 202를 반환한다. 파일이 덜 왔으면 `409 capture_not_ready`, GPU/backend가 준비되지 않았으면 `503 backend_not_ready`다.
- 같은 job_id·같은 요청에는 기존 JobStatus를 반환한다. 중복 요청으로 학습을 새로 실행하지 않는다. 동일 ID·다른 요청은 `409 id_conflict`다.

JobStatus 필수값:

`schema_version`, `job_id`, `capture_id`, `site_id`, `gateway_id`, `cage_id`, `kind`, `preset`, `status`, `stage`, `created_at`, `updated_at`, `geometry_revision`, `placement_revision`, `artifacts`, `error`.

- status: `queued`, `running`, `succeeded`, `failed`, `interrupted`.
- stage: `queued`, `colmap`, `training`, `exporting`, `complete`, `failed`, `interrupted`.
- 초기 응답은 status/stage=queued, artifacts=[], error=null이다.
- 실패 시 error는 `{ "code": "...", "message": "..." }`. 내부 경로나 자격증명을 오류에 싣지 않는다.
- 서버 재시작 당시 running 작업은 interrupted로 기록한다. 체크포인트 복구가 구현·검증되기 전에는 자동으로 다시 학습하지 않는다. queued 작업은 영속 큐에서 이어서 처리할 수 있다.
- 실제 COLMAP/학습/내보내기 성공과 결과 파일 검사를 통과해야 succeeded다. mock과 실제 backend를 health·보고서에서 구분하며 모의 결과로 실복원 성공을 표시하지 않는다.

성공 artifact 필수값: `artifact_id`(UUID), `format`(`gaussian_splat_ply`), `size_bytes`, `sha256`, `download_path`, `metric_scale_verified`(v1은 false), `metadata`.

- download_path는 이 API의 `/v1/gpu/jobs/{job_id}/artifacts/{artifact_id}` 상대 경로다. 내부 파일 경로나 임의 외부 URL을 반환하지 않는다.
- metadata는 backend 이름/버전, 실제 적용 preset 값, 학습 입력 수, 좌표계 설명을 포함한다. revision은 JobStatus에서 해당 촬영 묶음의 값을 유지한다.
- Pi는 단일 vertex element와 scalar 속성의 ASCII/little-endian/big-endian Gaussian PLY를 검증한다. x/y/z, f_dc_0~2, opacity, scale_0~2, rot_0~3 부동소수 속성과 선언된 vertex 수에 맞는 payload가 필요하다. 일반 점군을 Gaussian 결과로 보내지 않는다.
- artifact 파일은 SaaS 모델 저장소에 올리기 전까지 GPU에 보존한다. 이 private download_path를 일반 웹 사용자의 모델 URL로 쓰지 않는다.

### Health

필수값: `schema_version`, `service`(`habitat-gpu`), `api_version`(`1.0.0`), `status`(`ok`/`degraded`), `backend`(`splatfacto`/`mock`/`not_configured`), `gpu`와 `limits`.

gpu에는 `name`(문자열 또는 null), `cuda_available`(bool), `vram_total_bytes`(정수 또는 null), `reconstruction_ready`(bool)를 제공한다. API가 응답하는 것과 실제 GPU 복원이 가능한 것은 구분한다. mock 상태에서는 reconstruction_ready=false다.

limits는 `max_files_per_capture`, `max_file_bytes`, `max_capture_bytes`, `max_concurrent_jobs`를 포함한다. 처음에는 동시 복원 작업 1개로 제한한다. 준비가 안 된 경우 health 자체는 200/degraded로 응답하고 실제 작업 생성은 503으로 거절한다.

## 오류·실패 처리

오류 응답은 `{"detail":{"code":"...","message":"..."}}`를 사용한다. 검증 오류도 같은 바깥 형식을 쓰고 상세 입력 검사 정보는 필요하면 별도 `errors` 키로 추가한다. 권한 밖의 다른 작업/파일의 존재를 노출하지 않도록 조회는 404로 처리할 수 있다.

| 코드 | 의미 | Pi 처리 |
|---|---|---|
| 401 | 토큰 누락/불일치 | 작업을 보존하고 인증 설정 필요 표시 |
| 403 | 요청의 매장/Pi/사육장 범위 위반 | 작업 보존, 설정 오류 표시 |
| 404 | 해당 scope의 촬영/작업/파일 없음 | 등록 단계부터 상태 확인; 자동 삭제하지 않음 |
| 409 | ID 충돌 또는 파일 미완료 | 오류 code에 따라 설정 확인/미수신 파일 재전송 |
| 413 | 업로드 한도 초과 | 입력 축소 또는 설정 조정 필요 표시 |
| 422 | 잘못된 manifest·파일 크기/해시/이미지·요청 형식 | 원본/요청 검사; 잘못된 데이터를 무한히 빠르게 재송신하지 않음 |
| 429 / 503 | 부하/백엔드 미준비/저장 불가 | 기한·간격을 둔 재시도, 원본과 UUID 보존 |

Pi에서 GPU와 통신하는 작업은 별도 프로세스 또는 worker로 실행하며 로컬 제어 잠금을 잡은 채 네트워크를 기다리지 않는다. GPU 중단이 ESP32 제어·SaaS 센서 전송을 중단시키면 안 된다.

## SaaS와의 다음 계약

GPU→SaaS 결과 수신 API는 아직 합의되지 않았다. 데스크톱에서 결과 등록·재시도 모듈과 규격 제안 문서를 만들되, 수신 URL이 정해지기 전에는 비활성화한다. 기존 `/v1/edge/sync`는 센서/명령 이벤트 두 종류만 받으므로 GPU 결과를 보내지 않는다. 모델 파일 업로드와 JSON 결과 등록은 별도로 설계하고 민우님에게 전달한다.

## 단계별 완료 판단

1. 로컬 API 계약/해시·중복·권한·재시작 테스트 통과.
2. 실제 GPU 인식과 GPU 연산 확인.
3. 실제 다시점 데이터로 COLMAP→학습→Gaussian Splat 파일 검증.
4. Pi에서 Tailscale HTTPS로 등록→업로드→작업→결과 파일 확인.
5. 별도로 합의한 SaaS 결과 API에 등록하고 웹에서 모델 표시.

앞 단계가 성공해도 뒷 단계가 자동 완료된 것으로 보고하지 않는다. 실제 사진이 아직 없으면 파일 업로드 시험과 실제 3DGS 시험을 구분한다.
