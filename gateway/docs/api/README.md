# 민우님 전달용: HabitatOS Pi 수신 엔드포인트 v1.0.0

**2026-11-10 카메라·IR 추가 전달:** [RGB 카메라 2대 + IR 조명 제어 SaaS 연결 안내](camera-ir-integration.md)를 먼저 확인하세요. 현재 Pi의 조회·제어 API, OpenAPI, Postman과 서버용 클라이언트를 제공합니다. 기존 `/manage/`에 연결할 내용이며, 아래 Pi → SaaS 센서 수신 계약과는 별개입니다. SaaS 화면 구현·배포 완료를 뜻하지 않습니다.

**이 문서는 초기 SaaS 구현 인계 자료이자 Pi 수신 API 계약입니다.** 팀원이 운영 연결을 구성했으며, 2026-09-20 기존 샘플의 서버 조회·웹 표시·CSV를 확인했습니다. 현재 구현 범위와 남은 검증은 [운영 사이트 전수 조사](../operations/saas-site-review-2026-09-20.md)를 기준으로 합니다. 아래 구현·배포 절차를 이미 연결된 서버에 다시 수행해야 한다는 뜻은 아닙니다.

수신 주소는 `https://easyrep.kro.kr/v1/edge/sync`입니다. 이 규격 자체가 새 송신·저장 완료 ACK의 검증 증거를 대신하지는 않습니다. 별도의 수신 서버를 사용해도 Pi의 endpoint 설정만 바꾸면 됩니다. 수신 서버의 언어나 프레임워크는 제한하지 않습니다.

**SaaS 저장소에서 바로 작업하려면 [작업 지시서](saas-codex-prompt.md)를 사용합니다.** 센서 수신 API뿐 아니라 기존 웹 화면의 조회·상태·이력 연결, 아직 합의 전인 GPU 결과 수신의 후속 요구사항을 담았습니다. 2026-09-19 기준 Pi 프로그램은 0.3.0이며 **이 센서 API 계약은 v1.0.0 그대로**입니다.

## 1. 계약 경로

2026-10-25: [공기 온도 추정 v1](../saas-integration.md#air-estimate-v1)을 추가했다.
`POST /v1/edge/air`, `GET /v1/enclosures/{uuid}/air`와 정확한 ACK가 OpenAPI에 포함된다.
Pi 전송기는 기본 비활성이며 운영 SaaS의 수신·조회·환경 페이지 배포는 남아 있다.
[현재 적용 지시](saas-codex-prompt.md#air-saas-work)는 기존 센서 이벤트 순번을 변경하지 않는다.

2026-10-20: [실시간 영상 v1 계약](../saas-integration.md#실시간-영상-전송-v1-2026-10-20-미배포-소스)을
추가했다. `POST /v1/edge/video`와 인증된 HLS 조회가 같은 OpenAPI에 포함된다.
기존 센서 sync 계약은 유지한다. 영상은 아직 운영 SaaS에 배포되지 않았으며,
[최신 작업 지시](saas-codex-prompt.md#2026-10-20-추가-요청-cage-001-실시간-카메라)를 사용한다.

| 메서드·경로 | 호출자 → 수신자 | 역할 | 응답 |
|---|---|---|---|
| `POST /v1/edge/sync` | 매장 Pi → SaaS | 온습도·출력 상태·명령 처리 이력·현재 사육장 설정 수신 | 저장 후 `200` + 수신한 이벤트 ID |
| `GET /v1/edge/health` | 운영자 → SaaS | 수신 서비스 응답 확인; 참고 구현에 포함 | `200 {"status":"ok"}` |

**온도·습도·조명·급수마다 별도 POST 경로를 만들 필요는 없습니다.** 매장/Pi/사육장 ID로 묶어 한 경로로 받습니다. 이벤트가 없으면 `events: []`로 현재 상태만 보냅니다. 기본 전송 간격은 5초이며, 밀린 데이터가 있으면 여러 묶음을 이어서 보냅니다.

이 요청은 데이터를 수신하는 동작입니다. 명령 이벤트 안의 `action: "on"`을 보고 서버가 장치를 새로 켜면 안 됩니다. 이는 **Pi에서 이미 처리한 명령의 이력**입니다.

영상·객체 탐지 결과·3DGS 모델·열화상 배열의 업로드는 이번 v1 수신 데이터에 들어가지 않습니다. 해당 파일을 이 JSON의 임의 필드로 추가하지 않습니다. 먼저 실제 온습도/장치 상태 연결을 완료한 다음 별도 영상·GPU 규격으로 확장합니다.

## 2. 전달 파일

| 파일 | 사용 방법 |
|---|---|
| [edge-sync.openapi.json](edge-sync.openapi.json) | OpenAPI 3.1 명세. Swagger/Postman 등에 열어 모든 필드·타입·필수 여부 확인 |
| [sync-request.json](sync-request.json) | **현재 Pi 송신 코드가 생성한 전체 요청 예시**. 가상 센서 및 조명 명령 처리 결과 포함 |
| [sync-response.json](sync-response.json) | 위 요청에 대한 정상 ACK 예시 |
| [heartbeat-request.json](heartbeat-request.json) | 이벤트 없이 현재 상태만 보내는 예시 |
| [HabitatOS.postman_collection.json](HabitatOS.postman_collection.json) | Postman에 가져온 뒤 `base_url`, `pi_token` 설정 |
| [saas_reference.py](../../habitat_gateway/saas_reference.py) | FastAPI + SQLite 수신 참고 구현. Pi 제어 서버와 별개 프로세스 |
| [sync_contract.py](../../habitat_gateway/sync_contract.py) | 전체 데이터 모델과 필드 간 검증 규칙 |
| [saas-codex-prompt.md](saas-codex-prompt.md) | SaaS 저장소용 작업 지시서, 웹 표시 요구사항, GPU 결과 연동의 후속 조건 |

예시 데이터는 **시뮬레이션**이며 2026-09-18 고정 시각입니다. 현재 실측값으로 표시하지 않습니다. OpenAPI에 표현되지 않는 필드 간 ID 일치·시간대 필수·순서 검사는 데이터 모델과 아래 규칙도 함께 적용합니다.

## 3. 요청과 인증

```http
POST /v1/edge/sync
Authorization: Bearer <해당 Pi 전용 토큰>
Content-Type: application/json
```

| 최상위 필드 | 의미 |
|---|---|
| `schema_version` | 정수 `1` |
| `site_id` | 예: `STORE-001` |
| `gateway_id` | 예: `PI-001`. 한 매장에 Pi 여러 대 가능 |
| `sent_at` | 이번 묶음을 준비한 시각; UTC 오프셋 포함 |
| `gateway` | 프로그램 버전, 연결 상태, 사육장별 설정과 최신 관측 상태 |
| `events` | 최대 1,000개, Pi의 event_sequence 오름차순. 기본 묶음 크기 100 |

센서값의 예: `readings.T1.value=24.0`, `readings.RH1.value=65.0`. 단위는 사육장 configuration의 센서 목록에서 `degC`, `percent_rh`, `lux`로 확인합니다. 센서 오류는 `value=null`과 quality 값으로 표시합니다.

이벤트 종류는 `telemetry.recorded`와 `command.updated`입니다. 각 이벤트에는 `event_id`, `event_sequence`, `site_id`, `gateway_id`, `cage_id`, `created_at`, `payload`가 있습니다. command payload는 요청·발행·적용·거절·만료 등의 상태 이력입니다. 자세한 payload는 OpenAPI와 전체 JSON 예시를 기준으로 구현합니다.

토큰은 SaaS에서 발급하고 `(tenant, site_id, gateway_id, 허용 cage_ids)`에 연결합니다. Pi는 발급받은 토큰을 `HABITAT_CLOUD_TOKEN` 환경 변수로 사용합니다. **토큰은 32자 이상의 공백 없는 ASCII 문자열**입니다. 서로 다른 Pi는 다른 토큰을 사용하며, 같은 매장의 같은 사육장을 두 Pi에 동시에 배정하지 않습니다. 웹 사용자의 로그인 토큰과도 구분합니다.

서버는 본문에 적힌 site_id만 믿지 않고 등록된 토큰 권한과 대조해야 합니다. 참고 구현은 토큰별 매장/Pi/사육장 목록을 설정 파일에서 읽으며, 실제 SaaS에서는 기존 사용자·매장 DB와 연결하면 됩니다. Pi 요청으로 임의 장치 등록/이관을 수행하지 않습니다.

개발 등록에는 `simulation` 데이터를 명시적으로 허용합니다. 실제 센서 등록에는 이를 기본 차단하도록 참고 구현을 구성했습니다. 시뮬레이션과 실측 데이터를 화면에서도 구분합니다.

## 4. 서버 저장과 응답

1. 인증키와 매장·Pi·사육장 권한을 검사합니다. 요청 크기 한도는 8 MiB입니다.
2. 필수 필드·종류·센서 품질·시간대·이벤트 순서를 검사합니다. 본문과 이벤트, command payload의 ID가 일치해야 합니다.
3. 이벤트와 현재 상태를 DB 트랜잭션으로 저장합니다.
4. **DB 커밋이 성공한 뒤** `200`과 저장 완료한 event_id 목록을 반환합니다.

응답 형식:

```json
{
  "schema_version": 1,
  "site_id": "STORE-001",
  "gateway_id": "PI-001",
  "accepted_event_ids": ["요청에서 받은 실제 event_id"]
}
```

위 마지막 값은 설명용 자리표시자입니다. 복사해서 테스트할 때는 [실제 UUID 응답 예시](sync-response.json)를 사용합니다. `events: []`를 받으면 `accepted_event_ids: []`로 응답합니다. `204`, `202`, `{"success":true}`, HTML 화면으로 응답하면 현재 Pi는 수신 완료로 인정하지 않습니다.

중복 제거 키는 **`(site_id, gateway_id, event_id)`**입니다. 같은 이벤트가 다시 오면 저장을 반복하지 않고 해당 ID를 다시 ACK합니다. `(site_id, gateway_id, event_sequence)`도 고유하게 관리하고, 이미 사용한 ID/순서에 다른 내용이 오면 `409`로 처리합니다. 참고 구현은 묶음 전체를 저장하거나 전체를 취소합니다. 중간에 실패했는데 앞부분만 ACK하지 않습니다. Pi 클라이언트는 부분 ACK도 지원하지만 첫 서버 구현에는 전체 트랜잭션을 권장합니다.

| 코드 | 처리 |
|---|---|
| `200` | 저장 성공/동일 이벤트 재수신; ACK 반환 |
| `401` | 토큰 누락 또는 불일치 |
| `403` | 매장·Pi·사육장 권한 불일치 또는 시뮬레이션 허용 안 됨 |
| `409` | 기존 event_id/event_sequence와 내용 충돌 |
| `413` | 8 MiB 초과; Pi batch_size를 낮추거나 설정 목록 크기 점검 |
| `422` | 요청 형식/참조/시간대/순서 오류 |
| `503` | DB 저장 실패; ACK 없이 재시도 유도 |

`401/403/409/413/503` 참고 응답은 `{"detail":{"code":"...","message":"..."}}`입니다. `422`는 OpenAPI의 검증 오류 형식입니다. Pi는 오류 응답에 들어 있는 명령을 실행하지 않으며, 미확인 이벤트를 보관하고 재시도합니다.

서버에 늦게 도착한 이벤트도 이력에는 저장합니다. 현재 센서 값은 `sampled_at`을, 명령 상태는 해당 Pi의 event_sequence를 비교해 과거 값으로 덮어쓰지 않습니다. **event_sequence는 Pi끼리 비교하지 않습니다.** gateway 최신 상태는 sent_at으로 순서를 비교하고 접속 시각은 서버가 별도로 기록합니다. DB 초기화/장치 이관 시 등록 세대를 별도로 처리하거나 새 gateway_id를 발급해야 합니다.

참고 구현은 원본 이벤트와 Pi별 최신 상태를 저장합니다. 사용자 로그인·웹 조회 API·차트용 집계·사육장별 현재 값 테이블은 민우님 SaaS 구조에 맞춰 연결해야 합니다. 펌프 출력이 켜졌다는 정보만으로 실제 물 토출까지 확인됐다고 표시하지 않습니다.

## 5. 로컬 실행 및 확인

프로젝트 루트에서 실행합니다. 기존 `.venv` 의존성을 사용합니다.

```bash
# 이 셸에서만 쓸 로컬 시험 토큰 생성. 값을 문서나 저장소에 넣지 않습니다.
export HABITAT_CLOUD_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
.venv/bin/python -m habitat_gateway.saas_reference --config config/saas-reference.toml
```

수신 예제는 `127.0.0.1:9000`에서만 열립니다. Swagger 화면은 `http://127.0.0.1:9000/docs`입니다. 같은 토큰을 설정한 다른 셸에서 다음을 실행합니다.

```bash
curl --fail-with-body http://127.0.0.1:9000/v1/edge/sync \
  -H "Authorization: Bearer ${HABITAT_CLOUD_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary @docs/api/sync-request.json
```

같은 요청을 두 번 보내도 같은 이벤트 ID 목록을 응답해야 합니다. 두 번째 요청이 새 장치 동작을 유발해서는 안 됩니다. 예제 DB는 `data/saas-reference.sqlite3`입니다. 실제 SaaS에서 참고 구현을 재사용한다면 기존 HTTPS 역방향 프록시 뒤에 배치하고 기존 DB·권한 체계에 맞게 통합합니다. 이 로컬 프로그램을 실행했다고 공개 도메인에 자동 배포되지는 않습니다.

참고 수신기 CLI의 설정 오류는 입력 원문·traceback 대신 고정 오류 코드와 종료 코드 2로 표시합니다. `invalid_reference_configuration`이면 TOML·gateway 등록 필드·포트를, `reference_configuration_unreadable`이면 설정 경로와 읽기 권한을, `invalid_reference_credentials`이면 등록된 토큰 환경변수와 중복 등록을 확인합니다. 실제 토큰을 TOML의 `token` 필드에 넣지 않고 `token_env`가 지정한 환경변수로 전달합니다. HTTP API의 오류 형식과 저장 후 ACK 규칙은 바뀌지 않았습니다.

## 6. 운영 연결 순서

아래 순서는 신규 서버 구성 또는 누락 항목 확인용입니다. 2026-09-20 조사에서는 운영 사이트와 기존 샘플 조회, 수신 경로의 인증 응답까지 확인했습니다. 현재 연결 시험은 기존 PI-001 등록과 송신 인증 설정을 먼저 확인하며, endpoint 재구현이나 새 키 발급이 반드시 필요하다고 판단한 것은 아닙니다.

1. 민우님: 목표 도메인의 HTTPS와 `POST /v1/edge/sync`를 구성합니다. 이 경로가 프런트엔드 HTML을 반환하지 않도록 API로 라우팅합니다.
2. 민우님: 매장/Pi/사육장 등록과 전용 토큰을 발급합니다. 첫 검증용 등록은 시뮬레이션 허용 여부를 명시합니다.
3. Pi 담당: 실제 URL·발급 토큰을 설정하고 `--check-config`를 실행한 뒤 전송을 켭니다.
4. 함께 확인: 실제 데이터 수신, 동일 이벤트 재전송, 잘못된 토큰 차단, 통신 복구, 화면의 시뮬레이션/측정 시각 표시.

Pi 설정의 최상위 `[cloud]`:

```toml
[cloud]
enabled = true
endpoint = "https://habitatos.kro.kr/v1/edge/sync"
token_env = "HABITAT_CLOUD_TOKEN"
interval_s = 5
timeout_s = 10
batch_size = 100
retry_max_s = 60
```

현재 기본 Pi 설정은 전송을 꺼 둡니다. **운영 수신 URL과 기존 Pi에 등록된 인증값의 설정 위치를 확인한 뒤 위 설정을 적용합니다.** Pi의 로컬 API 주소 `127.0.0.1:8000`을 SaaS 수신 주소로 전달하는 구성이 아닙니다.

## 민우님에게 보낼 문장

> Pi에서 보낼 수신 규격 만들었어. SaaS에 `POST https://habitatos.kro.kr/v1/edge/sync` 경로를 만들어주면 돼. Bearer 토큰으로 Pi를 구분하고, 매장/Pi/사육장 ID와 온습도·조명·급수 출력·명령 결과를 JSON으로 보낼게. 기본 주기는 5초야. DB에 저장한 다음 `schema_version`, `site_id`, `gateway_id`, `accepted_event_ids`를 담아 HTTP 200으로 응답해줘. 같은 event_id가 다시 와도 한 번만 저장하고 같은 ID로 응답하면 돼. OpenAPI랑 요청·응답 JSON, Postman 파일, Python 수신 예제를 같이 준비했어. HTTPS 경로랑 Pi 전용 토큰 만들어주면 연결할게. 영상과 3DGS는 별도 연결로 이어서 붙일 예정이야.

이 문장은 최초 수신기 구현 요청 당시의 전달용 초안이며 자동 발송하지 않았습니다. 이미 연결한 운영 SaaS에는 위 운영 연결 상태를 기준으로 남은 설정·검증 항목만 전달합니다.

명세·예시 및 최신 소스를 포함한 전달 ZIP 재생성:

```bash
.venv/bin/python -m scripts.export_edge_contract --handoff dist/HabitatOS_SaaS_API_v1.zip
```

ZIP은 실행 가능한 수신 **참고 구현**과 공통 계약의 소스 묶음입니다. Pi 공통 패키지를 유지하기 위해 gateway/compute 소스도 포함하며, SaaS에서 실행할 프로그램은 위 `habitat_gateway.saas_reference`입니다. SaaS 운영 저장소를 대체하거나 GPU 서버를 자동 설치하지 않습니다. 토큰·실제 매장 설정·DB·ARM 전용 wheel은 포함하지 않습니다.

구현 참고: [FastAPI 요청 모델과 자동 API 문서](https://fastapi.tiangolo.com/tutorial/body/).
