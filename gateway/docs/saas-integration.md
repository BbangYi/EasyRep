# Pi → SaaS 이벤트 전송 규격 v1

이 문서는 현재 구현된 `habitat_gateway/cloud.py`의 송신 규격이다. 수신 경로는 **`POST /v1/edge/sync`**, 현재 주소는 `https://easyrep.kro.kr/v1/edge/sync`다. 2026-10-24 사용자가 동일 서버의 도메인 변경임을 확인했고 Pi 운영 설정에 반영했다. 팀원이 SaaS 연결을 구성했으며, 2026-09-20 운영 사이트에서 기존 샘플의 수신 이력·API 조회·웹 표시를 확인했다. [운영 사이트 점검 기록](operations/saas-site-review-2026-09-20.md)에 확인 범위와 남은 검증을 정리했다. [민우님 전달용 API 자료](api/README.md)에 OpenAPI·전체 JSON·Postman·로컬 수신 구현을 준비했다. 실제 URL은 설정으로 지정한다. 영상, GPU 작업 제출, 원격 제어 수신은 이 API에 포함하지 않는다.

## 0.4.16 이벤트 전송 차단 수정

0.4.15까지는 `verified_at`이 없으면 Pi가 `cloud_continuity_unverified`로
모든 이벤트를 전송하지 않았다. 2026-10-24 실제 운영 API에 원본 이벤트를
그대로 전송한 결과 순번 1은 409 `event_conflict`, 순번 1941은 HTTP 200과
정확한 이벤트 UUID ACK를 반환했다. 순번 1941의 동일 내용 재전송도 같은 ACK를 받았다.
충돌이 없는 측정까지 일괄 차단하는 동작을 0.4.16에서 수정했다.

서버의 실제 오류 설명은 `An event ID or sequence has different stored content`다.
과거 운영 서버 점검에서 같은 `STORE-001 / PI-001`의 순번 1은
`ca21c579-c662-53cc-b73a-a55a12ae3b71`이라는 9월 시험 측정이었다.
운영 Pi의 순번 1은 `c2b2587a-dfa9-4c9e-b704-8587327fc92e`라는
10월 5일의 출력 잠금으로 거절된 분무 요청 이력이다. 동일 등록 아래 서로 다른
이벤트 번호 생성 이력이 연결되지 않아 순번 1이 재사용된 근거다.
현재 서버 행을 직접 읽거나, DB를 초기화·교체한 명령과 작업자를 확인한 것은 아니다.
[당시 서버 확인](operations/saas-site-review-2026-09-20.md)과 아래 과거 기록을 구분한다.

현재 동작은 다음과 같다.

- 서버 전체 이력 확인 근거가 없으면 `continuity.status=unverified`로 표시하지만
  그 이유만으로 전송을 차단하지 않는다. `verified_at`과 서버 최고 순번을 추정해 쓰지 않는다.
- 서버가 배치를 409 `detail.code=event_conflict`로 거절하면 다음 시도에서
  앞부분을 절반으로 줄인다. 단일 원본 이벤트가 같은 오류로 거절됐을 때만
  `cloud_conflicts`에 ID와 확인 시각을 기록해 이후 배치에서 제외한다.
  원래 `cloud_outbox`의 순번·UUID·본문은 그대로 보존한다.
- 한 시도는 HTTP 요청 한 번으로 제한한다. 단일 충돌 이후에는 다음 이벤트도
  한 건씩 확인하고, 정상 ACK 후 원래 배치 크기로 돌아간다.
- 일반 409, 인증 오류, 422, 네트워크 오류, 잘못된 ACK로는 이벤트를 격리하거나
  삭제하지 않는다. 기존 ACK 검증에 통과한 이벤트 ID만 대기열에서 삭제한다.
- `pending_events`는 격리된 행까지 포함한 전체 보존 수다. `eligible_events`는
  전송 가능 수, `conflicted_events`는 보존 중인 충돌 수다. 충돌이 남으면
  `last_error=cloud_event_conflicts`로 알리되 정상 이벤트는 계속 전송한다.
- 실제 로컬 순번 할당값이 이미 확인한 ACK/서버 순번보다 작아진
  `cloud_sequence_regressed`는 계속 차단한다. 높은 순번의 ACK를 받았다고
  낮은 충돌 이벤트까지 처리됐다고 표시하지 않는다.

Pi→SaaS v1 요청·ACK 계약은 변경하지 않았다. 로컬 DB에 충돌 메타데이터 테이블만
추가하며 기존 이벤트·순번·등록·센서 설정을 재작성하지 않는다. 과거의 전체 배치
충돌 원인은 `recorded_blocked_reason`으로 보존하면서 개별 이벤트를 다시 확인한다.
이전 바이너리로 복구하면 기존의 전체 차단 정책도 다시 적용될 수 있다.
충돌 기록 자체의 서버 이관·해결은 별도 작업이며 자동 재번호하거나 삭제하지 않는다.

최종 전송·ACK·충돌·참고 서버와 GPU 잠금 재검사 87개(하위 검사 6개)를 통과했다.
검사에는 같은 순번의
다른 이벤트가 이미 저장된 수신기에서 정상 이벤트만 원래 ID로 ACK받는 경우,
충돌 행의 재시작 후 보존, 잘못된 오류/ACK, 네트워크 실패, 실제 순번 회귀가 포함된다.

전체 회귀검사는 547개 통과·7개 제외·하위 검사 399개 통과와 별도 실패 2건이었다.
GPU 렌더링 검사의 일시적 flock 경합(429)은 단독 재검사에서 통과했다.
나머지는 기존 소스 및 0.4.15 릴리스에도 없는 `firmware/cage_node/config.example.h`를
소스 전달용 `.pyz` 빌더가 요구하는 검사다. 해당 파일이나 센서 설정은 수정하지 않았다.
실제 배포에 쓰는 오프라인 archive 경로는 별도로 빌드하고 manifest 45개 파일의
해시 및 wheel 내부 수정 소스 일치를 검증했다. 전체 검사 전부 통과로 보고하지 않는다.

### 운영 적용과 원본 메시지 재검증

2026-10-24 20:07 KST에 `0.4.16-92e6792d58ff`를 적용했다. 기존 설치기의
검증·오프라인 venv 설치·링크 전환·health 확인 기능을 재사용했고, 운영 설정·인증 파일·
MQTT CA·서비스 unit·recorder·센서 핀 설정은 바이트 비교로 보존했다.
이전 릴리스는 모두 남겼으며 기존 current는 previous로 보존했다.
적용 직전 DB 전체를
`/opt/habitat-gateway/backups/before-cloud-0.4.16-20261024T110716Z.sqlite3`에
권한 0600으로 백업했다. 기존 DB를 초기화하거나 순번을 바꾸지 않았다.

적용 전 대기열 38,798건 중 정상 38,790건이 실제 서비스에서 ACK 처리됐다.
20:10:56 KST 확인 결과는 `pending_events=8`, `eligible_events=0`,
`conflicted_events=8`, `acknowledged_high_watermark=38798`, `blocked_reason=null`이다.
마지막 이벤트 성공 시각은 `2026-10-24T11:10:55.576758+00:00`이고 health `ok`,
MQTT 연결, 연속 네트워크 실패 0이다. `continuity.status=unverified`는 전체 서버
이력을 확인했다고 주장하지 않는 정보 상태이며 전송 차단 상태가 아니다.

단일 원본 요청으로 서버가 `event_conflict`를 반환한 순번 1–8만 격리했다.
순번 1은 기존 명령 이력, 2–8은 측정 이력이다. 모든 보존 행의 순번·UUID·본문
SHA-256이 적용 전 백업과 같음을 확인했다. 이 8건의 충돌 상대 서버 행을 직접
조회하거나 서버의 기존 기록을 덮어쓰지는 않았다.

원래 추적한 메시지 세 건은 로컬 telemetry에 그대로 있고 전송 대기열에서는
ACK 후 제거됐다. 백업의 원래 이벤트를 설치된 0.4.16 송신 코드로 다시 전송해
아래 이벤트 ID 각각에 대해 HTTP 200 및 정확히 일치하는 `accepted_event_ids`를
독립적으로 확인했다. 이는 수신 계약의 저장 ACK이며 서버 DB 직접 조회나 웹
로그인 후 표시까지 확인한 결과는 아니다.

| message_id | 원본 event_sequence | 검증된 ACK event_id |
|---|---:|---|
| `92b67bb3-e418-4712-a117-8768b02ab922` | 1941 | `eb44499a-1620-44f9-b54a-bb8d8352c6ae` |
| `22784783-c061-45cf-bdb8-314c3f3522fb` | 1942 | `1e7cf334-6fe5-4506-850a-73ec9e89e942` |
| `340031d3-9ee2-4006-96bf-6727a8bb2297` | 1943 | `697df55d-4007-4219-8ed5-98f47a070912` |

적용·대기열 처리 관측 중 새 자연 메시지는 없었으므로 새 측정의 끝단 검증으로
표현하지 않는다. 검증 대상은 실제 Pi에 이미 저장돼 있던 원본 실측이다.
새 운영 릴리스와 복구용 DB 백업은 보존하고, 빌드/진단 임시파일은 제거했다.

2026-10-24 20:35:52 KST 후속 읽기 전용 확인에서는 할당·ACK 최고 순번이 모두
38807로 증가했다. 적용 직후 관측 이후 새 이벤트 9건도 ACK됐으며
`eligible_events=0`, `conflicted_events=8`, `blocked_reason=null`, 네트워크 실패 0이다.
보존된 8건은 10월 5일 18:09:30 KST의 거절된 분무 명령 이력 1건과
10월 20일 03:10:17–03:10:48 KST의 측정 메시지 7건이다. 측정마다 T1·RH1·T2·T3가
들어 있어 센서값 기준으로는 28개(온도 21개, 습도 7개)다.

하트비트는 20:35:49 KST까지 정상 ACK됐지만, gateway와 별도 recorder 모두
마지막 새 측정은 20:15:53 KST였고 recorder는 약 20분간 새 수신이 없는 `stale`였다.
이 시점의 최신 측정 공백은 전송 가능 이벤트가 쌓이는 현상이 아니므로 과거 순번
충돌만으로 설명하지 않는다. ESP32→Pi 입력 공백의 구체적인 원인은 이 조회에서
확인하지 않았고, 센서 배선·핀·인증·서비스 설정은 변경하지 않았다.

## 2026-10-24 도메인 변경 및 0.4.15 Pi 검증 이력

운영 `/etc/habitat-gateway/gateway.toml`의 `cloud.endpoint`만
`https://habitatos.kro.kr/v1/edge/sync`에서 `https://easyrep.kro.kr/v1/edge/sync`로
변경했다. 원본은 같은 디렉터리의 `gateway.toml.before-easyrep-20261024T102037Z`에
기존 소유권·권한으로 보존했다. 공통 설치 기본값도 새 도메인으로 갱신했다.
등록 ID는 `STORE-001 / PI-001 / CAGE-001`을 유지하며 wire schema 변경은 없다.

변경 전 실행 서비스는 연속 네트워크 실패 556회, 마지막 하트비트 성공
`2026-10-24T05:14:59.572015+00:00`이었다. 이전 도메인은 DNS 조회에 실패했고
새 도메인의 health는 HTTP 200이었다. 설치된 `cloud.py`, `config.py`, `store.py`,
`api.py`, `sync_contract.py`는 개발 소스와 SHA-256이 일치했다.

기존 Pi 토큰과 실제 로컬 API 스냅샷으로 설치된 `CloudSync.send_once()`를 실행했다.
운영 DB는 읽기 전용으로 열었으며, 신규 Gateway/Store 생성이나 센서 없는 가상
스냅샷으로 대체하지 않았다. 실제 요청 시각은 `2026-10-24T10:20:36.796868+00:00`,
CAGE-001 스냅샷은 같은 날 19:20:36 KST의 실제 메시지
`e7ba2930-3912-43c6-bba8-1d847646bfd5`였다. 기존 연속성 차단에 따라 `events=[]`였고,
새 서버에서 HTTP 200 및 아래 ACK를 받아 schema·등록 ID·이벤트 ID 검증을 통과했다.

```json
{"schema_version":1,"site_id":"STORE-001","gateway_id":"PI-001","accepted_event_ids":[]}
```

설정 적용 후 gateway만 재시작했다. 운영 서비스의 하트비트 ACK를
`2026-10-24T10:20:38.399773+00:00`과 `2026-10-24T10:20:43.509226+00:00`에
확인했고, health `ok`, MQTT 연결, 하트비트 오류 `null`, 연속 실패 0이었다.
검증 중 자연 수신된 메시지 `86e56268-a0c5-43a5-a11c-5e662b11c218`는
19:20:41 KST 측정값이며 gateway 수신 시각은 `2026-10-24T10:20:41.166085+00:00`다.

변경 전 대기 이벤트 38,603건의 순번·UUID·본문을 해시로 대조해 모두 보존됐음을
확인했다. 이후 대기 건수는 새 메시지가 추가돼 38,604건이었다.
`cloud_delivery_state`, 인증 파일, MQTT CA, 서비스 unit, recorder 코드는 그대로다.
센서 배선·핀·펌웨어·등록 ID·출력 잠금은 변경하지 않았다.

**도메인 연결은 복구됐지만 영속 이벤트 전송은 미복구다.** `cloud_continuity_unverified`,
`last_event_success_at=null`, ACK 최고 순번 0, 서버 확인 순번 `null`이 유지됐다.
아래 원래 추적 메시지도 대기열에 그대로 남았다.

| message_id | event_sequence |
|---|---:|
| `92b67bb3-e418-4712-a117-8768b02ab922` | 1941 |
| `22784783-c061-45cf-bdb8-314c3f3522fb` | 1942 |
| `340031d3-9ee2-4006-96bf-6727a8bb2297` | 1943 |

이 연결 검증은 새 도메인의 기존 인증 수용과 실제 서비스의 하트비트 재개를 확인한 것이다.
당시 서버 DB의 저장 행, 웹 로그인 후 현재값·기록 표시, 서버 최고 순번은 확인하지 못했다.
후속 CSV 대조로 확인한 스냅샷 측정 이력은 아래에 별도로 기록한다.
아래 연속성 복구 조건은 영속 이벤트에 계속 적용된다.

공통 기본값 변경 후 기존 새 매장 설정·등록 검사
`pytest tests/test_deployment.py -q -k 'store_wizard or new_store' -p no:cacheprovider`는
11개 통과·24개 제외였다. 임시 진단 스크립트는 검증 후 제거했다.

### 사용자 제공 SaaS CSV와 Pi DB 대조

사용자가 제공한 [EasyRep-CAGE-001-degC.csv](EasyRep-CAGE-001-degC.csv)를
운영 Pi DB와 읽기 전용으로 대조했다. 파일은 2,139행, 서로 다른 센서 메시지
713건이며, 메시지마다 T1·T2·T3가 한 번씩 있다. 측정 범위는 2026-10-24
13:13:19–14:14:57 KST, 서버 수신 범위는 13:13:21.455507–14:14:59.557084 KST다.
모든 행이 `receipt_source=snapshot`, 빈 `event_id`, `data_source=sensor`,
`quality=valid`, `unit=degC`다.

713개 `sensor_message_id` 전부가 Pi의 `CAGE-001` telemetry와 일치했고,
2,139개 센서 행의 값·quality·sampled_at·pi_received_at·data_source·geometry_revision·
placement_revision이 모두 일치했다. 누락된 Pi 메시지와 불일치는 0건이다.
같은 713건의 이벤트는 여전히 Pi 대기열에 남아 있었고, 이들의 순번 범위는
34376–35107이다. ACK 최고 순번은 0, 연속성 확인 시각은 `null`이다.

따라서 **영속 이벤트가 차단돼도 이 SaaS는 하트비트의 스냅샷을 측정 이력으로
저장하고 있다.** 앞서 이벤트 차단을 근거로 SaaS 측정 기록 전체가 저장되지
않는다고 해석한 설명은 정정한다. CSV는 스냅샷 이력의 증거이며,
`accepted_event_ids` ACK나 전체 이벤트 순번 연속성을 확인하는 근거는 아니다.
서버 DB 직접 접속이나 서버 코드 검사는 수행하지 않았다.

10월 20일 원래 추적 메시지 3건과 10월 24일 19:20 도메인 변경 검증 메시지는
CSV 기간 밖이며 파일에 없다. 이 파일만으로 그 메시지들의 서버 부재나
변경 후 저장 성공을 판정하지 않는다. RH1도 온도 전용 CSV의 검사 범위 밖이다.
내보내기 원본은 변경하지 않았고 SHA-256은
`fc5557bcc732a34b52e4bb0f5d93aaa071ba16a8338c5fef6f66c2ebc64bdb1c`다.
대조용 임시 스크립트는 제거했다.

## 2026-10-07 연결 확인 이력과 복구 조건

현재 Pi 운영 릴리스는 **`0.4.15-e724b3a0b4e4`**다. 2026-10-20 설치 후 health `ok`·MQTT 연결과 기존 데이터·인증정보 보존을 확인했다. [설치 확인](operations/hardware-arrival.md#standalone-camera-20261020)을 따른다. 이는 SaaS 이벤트 수신 완료의 근거가 아니다.

실제 Pi `/v1/cloud` 확인 시각은 `2026-10-07T05:42:47.199081+00:00`이다. 최근 하트비트 ACK는 `2026-10-07T05:42:44.867608+00:00`, 하트비트 오류는 `null`이다. 반면 `last_event_success_at=null`, `pending_events=1`, `continuity.status=blocked`, `blocked_reason=cloud_continuity_unverified`이며 서버 최고 순번은 `null`로 미확인이다. 로컬 할당 최고 순번은 1, ACK 최고 순번은 0이다. [현재 SaaS 상태](../var/reports/commissioning/software-r15-20261007-cloud.json)를 근거로 하며, 하트비트 ACK나 GPU 모의실험 성공을 이벤트 전달 성공으로 취급하지 않는다.

대기 이벤트의 원래 sequence·UUID·본문 SHA-256을 보존했다. 정확한 서버 기록 또는 원래 Pi DB와 감사 가능한 이관이 필요하며, 순번을 추정하거나 큐를 삭제·자동 재번호하지 않는다. 아래의 공통 복구 조건은 여전히 적용된다.

### 0.4.12 운영 충돌 기록 — 2026-10-05 (과거)

당시 Pi 릴리스는 **`0.4.12-76a2b5356b9c`**였다. 설치 후
`2026-10-05T13:13:25.834393+00:00`에 서비스 건강 상태 `ok`·MQTT 연결과
하트비트 ACK `2026-10-05T13:13:24.986376+00:00`를 확인했다.
운영 설정·인증 파일은 바이트 단위로 유지됐으며, 아래 대기 이벤트의
순번·UUID·본문 SHA-256도 그대로다. `pending_events=1`,
`continuity.status=blocked`, `last_event_success_at=null`이므로 기존 순번 충돌은
복구되지 않았다. 0.4.12는 R15의 정상 예약이 제어 주기에서 자기 취소되는
문제를 수정했으며 서버 순번을 변경하거나 이벤트를 삭제하지 않았다.
[당시 배포 확인](../var/reports/commissioning/software-r15-20261005-active-reservation-deployment.json),
[0.4.12 전체 검사](../var/reports/commissioning/software-r15-20261005-0.4.12-tests.log)에
396개·하위 검사 231개 통과, 7개 제외·108.99초의 결과를 기록했다.

### 0.4.10 검증 이력과 공통 복구 조건

Pi 운영 릴리스 `0.4.10-fe170e802fba`의 설치 후 `last_heartbeat_success_at=2026-10-05T11:25:45.343678+00:00`의 실제 ACK와 하트비트 오류 없음을 확인했다. 대기 이벤트 1건은 `cloud_continuity_unverified`로 차단되며 `last_event_success_at=null`, 로컬 할당 최고 순번 1, ACK 최고 순번 0, 서버 확인 최고 순번 `null`이다. [배포 상태](../var/reports/commissioning/software-r15-20261005-deployment.json)와 [업그레이드 전후 대조](../var/reports/commissioning/software-r15-20261005-upgrade.json)에 실제 확인 결과를 보존했다. 대기 이벤트 한 건의 본문 SHA-256은 배포 전후 `981b7dbc43a83c65a59cc6b6f90659f2ea28a6aa461edbaf6e4d7d31ec1e2357`로 같다. 대기 건수·순번·UUID도 그대로다. 하트비트 성공은 이벤트 전달 완료를 뜻하지 않으며 `last_event_success_at`, 대기 수와 연속성 상태를 함께 확인한다.

0.4.10의 [최종 Pi 전체 검사](../var/reports/commissioning/software-r15-20261005-final-tests.log)는 386개 및 하위 검사 231개 통과, 의존성에 따른 7개 제외, 110.07초다. 설치 후 서비스 건강 상태와 MQTT 연결은 정상이지만 실제 센서 수신·물리 출력 검증은 수행하지 않았다.

현재 Pi의 운영 DB는 `/var/lib/habitat-gateway/gateway.sqlite3`이며, `STORE-001 / PI-001`의 대기 이벤트 한 건이 `event_sequence=1`이다. 실제 수신 서버는 이 이벤트에 HTTP 409 `event_conflict`를 반환했다. 같은 등록의 과거 순번 1–8 수신 기록은 아래에 보존되어 있으나, **8은 현재 서버 최고 순번으로 확인된 값이 아니다.** 새 R15 필드의 422 문제로 해석하지 않는다.

대기 이벤트 `c2b2587a-dfa9-4c9e-b704-8587327fc92e`는 출력 잠금으로 거절된 분무 요청의 이력이다. 원래 순번·UUID·본문을 보존한다. 번호를 임의로 올리거나 큐를 삭제하거나 매장 등록을 바꿔 성공으로 처리하지 않는다. 조사한 DB 파일 9개는 할당 최고 순번이 모두 없거나 1이어서 서버가 과거 ACK한 1–8의 연속성을 복구할 수 없었다. 2026-10-05 사용자는 현재 서버 기록이나 원래 DB를 확인할 수 없다고 답했다. 현재 필요한 것은 추가적인 순번 추정이 아니라 외부 서버의 정확한 기록 확인과 감사 가능한 이관이다.

0.4.9에서 적용했고 0.4.10에도 유지한 보호 기능은 `cloud_delivery_state`에 ACK 최고 순번과 연속성 확인 근거를 영속 저장한다. ACK 기록과 대기열 삭제는 같은 SQLite 트랜잭션으로 처리한다. 새 DB 또는 확인 근거가 없는 기존 DB는 이벤트 전송을 차단한다. 서버의 409 충돌 이후에도 조정 전까지 이벤트를 다시 보내지 않는다. 이 차단은 Pi의 센서 수집·GPU 요청·로컬 안전 제어를 중단하지 않는다. 동일한 Pi 서비스에서 이벤트를 제외한 실제 상태 하트비트를 전송하고, 이벤트 차단과 하트비트 ACK는 별도 상태로 표시한다. 이 보호 기능 구현은 완료했으며 기존 충돌 이벤트의 외부 조정은 완료하지 않았다.

`GET /v1/cloud`의 `continuity`는 로컬 할당 최고 순번, ACK 최고 순번, 서버 확인 순번, 확인 시각과 차단 이유를 보여준다. `confirmed`는 운영자가 제시한 근거를 로컬에서 대조했다는 뜻이며, `confirmation_provenance=operator_declared`로 표시한다. Pi가 서버 DB를 직접 확인한 상태로 표현하지 않는다.

### SaaS 담당자에게 필요한 정확한 확인

등록 `STORE-001 / PI-001`에 대해 모든 사육장·이벤트 종류·페이지를 포함한 서버의 실제 최고 `event_sequence`, 확인 UTC 시각, 그 값을 얻은 근거가 필요하다. 최신 측정 한 건이나 최신 명령 한 건은 전체 최고 순번의 근거가 아니다. 확인과 복구 동안 같은 등록을 쓰는 다른 송신자가 없어야 한다. 현재 v1의 ACK는 수신 이벤트 ID만 반환하며 순번 조회·등록 세대 복구 API가 없다. 이 요구사항은 운영 SaaS에 구현했다고 주장하지 않는다.

서버 최고 순번이 현재 로컬 할당 순번보다 높거나, 대기 이벤트가 이미 서버가 사용한 순번과 겹치면 별도의 감사 가능한 이관이 필요하다. **현재 로컬 순번 1과 서버 과거 순번 ≥8은 확인 명령만으로 승인할 수 없다.** 원래 DB의 복구 또는 서버 담당자와 합의한 이관 후에 다음 확인 절차를 사용한다. 현재 충돌 이벤트는 자동 재번호하지 않는다.

### 일치하는 DB에 대한 운영자 확인 절차

서비스를 중지하고 실제 확인 근거를 담은 JSON을 준비한다. 필수 키는 `site_id`, `gateway_id`, `server_high_watermark`, 시간대가 있는 ISO 형식 `verified_at`, `method`, `evidence_ref`, `exclusive_writer=true`다. 최고 순번은 서버에서 확인한 정수여야 한다. 비밀번호나 토큰을 근거 파일에 넣지 않는다.

```bash
sudo systemctl stop habitat-gateway.service
sudo /opt/habitat-gateway/current/venv/bin/python -m habitat_gateway \
  --config /etc/habitat-gateway/gateway.toml \
  --confirm-cloud-continuity /path/to/verified-evidence.json
sudo systemctl start habitat-gateway.service
```

이 명령은 네트워크나 장치를 시작하지 않는다. 실행 중인 DB의 잠금, 등록 불일치, 서버 순번이 더 높은 상태, 겹치는 대기 순번, 오래된 충돌 전 근거를 거절한다. 통과해도 순번 변경·이벤트 삭제는 0건이다. 확인 정보까지 포함한 과거 DB 전체를 오래된 시점으로 되돌린 경우는 로컬만으로 서버의 더 높은 순번을 알아낼 수 없다. 서버 순번 조회 또는 등록 세대 계약이 있어야 그 복구까지 검증할 수 있다.

## 실행 설정

2026-09-21 14:24 KST에는 제공받은 Pi 토큰으로 운영 주소에 연결 확인 요청을 보내 **HTTP 200과 기존 `CloudSync.send_once`의 ACK 검증 성공**을 확인했다. 대상은 `STORE-001 / PI-001`이며, `events=[]`, `telemetry=null`, `healthy=false`, `transport_connected=false`로 센서값이나 장치 연결을 만들어내지 않았다. 토큰은 해당 검사 프로세스 메모리에서만 사용했다. 새 센서 이벤트의 저장·ACK, 상시 송신 서비스와 재부팅 자동 시작을 검증한 결과는 아니다. 새 송신 DB를 기존 Pi ID로 시작하기 전에 기존 DB와 이벤트 순서 또는 서버 등록 세대를 확인해야 한다. 비밀값을 제외한 결과는 `var/data/pi-saas-check-2026-09-21/heartbeat-result.json`에 있다.

같은 날 14:40 KST에는 사용자가 요청한 **CAGE-001 시뮬레이션 측정 3건**을 기존 Gateway의 입력 검증·SQLite 대기열·`CloudSync.send_once` 경로로 전송했다. 저장소 외부의 `~/.config/habitatos/gateway.env`에서 토큰을 읽었으며 파일 권한은 `0600`, 상위 디렉터리는 `0700`이다. 세 요청 모두 HTTP 200과 전송한 이벤트 ID의 ACK를 받았다. 마지막 요청을 그대로 재전송해 같은 ACK도 확인했다. 로컬 대기열은 0건이며 실제 센서·출력 장치를 사용하거나 제어 명령을 발행하지 않았다.

| KST 측정 시각 | event_sequence | T1–T5 각각 | RH1 | LUX1 |
|---|---|---|---|---|
| 2026-09-21 14:40:27 | 6 | 24.8 °C | 64.5% | 150 lux |
| 2026-09-21 14:40:30 | 7 | 25.0 °C | 64.0% | 175 lux |
| 2026-09-21 14:40:33 | 8 | 25.2 °C | 63.5% | 200 lux |

모든 측정은 `data_source=simulation`이고 가상 출력은 모두 꺼짐이다. 마지막 이벤트 ID는 `a77367ad-213c-4975-a259-997a67592d52`이다. 2026-09-20 조회 기록의 순서 1–5와 기존 요청 예시의 ID·순서 일치를 확인하고, 별도 검증 DB의 다음 순서를 6으로 명시적으로 설정했다. 서버가 충돌을 반환하면 중단하도록 했으며 실제 응답에는 충돌이 없었다. 현재 서버의 전체 최대 순서를 조회한 것은 아니며, 이 검증 DB는 운영 DB 전체를 복원한 결과가 아니다. 후속 송신에서 순서를 1로 초기화하면 안 된다.

요청 4개(새 측정 3개와 마지막 측정 재전송), ACK, 검증 결과, 순서 기준과 로컬 DB는 `var/data/pi-saas-check-2026-09-21/cage001-sample-4tb9xht9/`에 보존했다. Pi 토큰으로 `/api/enclosures/`와 해당 사육장의 `/records/`를 읽으면 401이므로 이번 측정의 웹 표시·서버 조회 결과·실제 중복 행 개수는 독립적으로 확인하지 못했다. ACK는 계약상 저장 완료 응답이나 서버 DB를 직접 조사한 것은 아니다. 시험 후 송신 프로세스는 종료했으며 상시 실행·재부팅 자동 시작은 구성하지 않았다. 기본 센서 만료 15초·Pi 오프라인 60초가 지나면 화면에 오래됨/오프라인이 표시될 수 있다.

아래는 새 Pi를 설치할 때의 설정 안내다. 이미 연결된 Pi는 기존 실행 설정을 먼저 확인하며, 인증키 재발급이나 설정 재적용을 전제로 하지 않는다.

후속 사용자 확인으로 위 14:40:33 KST의 시뮬레이션 값이 로그인한 대시보드에 표시됨을 확인했다. 이는 사용자의 화면 확인이며 Pi 토큰으로 웹 조회 권한을 얻었다는 뜻은 아니다.

기존 Pi TOML의 최상위에 다음 섹션을 추가한다. `[[cages]]` 안에 넣지 않는다. 예제 도메인을 실제 서버 주소로 바꾼다.

```toml
[cloud]
enabled = true
endpoint = "https://easyrep.kro.kr/v1/edge/sync"
token_env = "HABITAT_CLOUD_TOKEN"
interval_s = 5
timeout_s = 10
batch_size = 100
retry_max_s = 60
```

프로세스 환경에 SaaS에서 발급한 `HABITAT_CLOUD_TOKEN`을 설정한다. 32자 이상의 공백 없는 ASCII 토큰을 사용하며 로컬 API의 `HABITAT_API_TOKEN`과 분리한다. systemd에서는 기존 `/etc/habitat-gateway/gateway.env`에 추가한다. 브라우저에 이 Pi 인증키를 전달하지 않는다.

```bash
.venv/bin/python -m habitat_gateway --config config/local.toml --check-config
.venv/bin/python -m habitat_gateway --config config/local.toml
```

기본은 `cloud.enabled=false`다. 활성화하지 않으면 전송·대기열 기록을 하지 않는다. `--check-config`는 필요한 토큰과 URL 형식을 검사하며 외부 연결·DB 쓰기·장치 구동을 하지 않는다. 활성화 후 발생한 이벤트부터 기록하며 예전 로컬 이력을 자동 소급 전송하지 않는다. 다시 비활성화하면 기존 대기열은 보존하고 새 이벤트 기록만 중단한다.

### 센서 없는 연결 유지 (0.3.1)

0.3.2에는 새 Pi 설정용 `--check-connection`을 추가했다. 저장된 설정과 환경변수의 토큰으로 센서 없는 heartbeat 한 번을 보내고 `connected`, `site_id`, `gateway_id`, `checked_at`, `error` JSON을 반환한다. ACK 검증 성공은 종료 코드 0, 실패는 1이며 DB·장치·로컬 API를 시작하지 않는다. `connect.sh`는 이 검사가 성공한 다음에만 토큰을 저장하고 서비스를 설치한다. 서버 등록/토큰 발급은 기존 SaaS에서 수행하며, 자동 등록 API나 토큰에서 ID를 추출하는 기능은 추가하지 않았다. wire schema와 ACK는 그대로다.

`--heartbeat-only`는 같은 설정과 Pi 토큰으로 연결 확인만 지속한다. `[cloud] enabled=true`가 필요하며 기본 간격은 5초다. Gateway는 실행 중인 Pi 프로세스의 `healthy=true`를 보고하되 각 사육장의 `transport_connected=false`, `telemetry=null`, 출력 `observed=null`, `events=[]`를 보낸다. 설정의 `transport`는 기존 v1 열거형(`simulated` 또는 `mqtt`)을 유지하며, 어느 쪽도 실제로 시작하지 않는다. 따라서 MQTT 비밀번호·로컬 API 토큰은 이 모드에 필요하지 않다. 기존의 가상 데이터 허용 등록은 계속 사용할 수 있다.

연결 상태 생성에는 메모리 DB만 사용한다. 설정된 운영 DB를 열거나 변경하지 않고, 이벤트 순서를 소비·초기화하지 않으며 대기 중인 이벤트를 전송하지 않는다. 센서 시뮬레이터·MQTT·자동제어·로컬 HTTP API도 시작하지 않는다. ACK의 버전·Pi ID·이벤트 ID 검증, HTTPS 요구, 리다이렉트 차단, 타임아웃·재시도는 기존 `CloudSync`를 재사용한다. 성공은 `Cloud heartbeat acknowledged`로, 실패는 기존 오류 코드로 기록한다. 요청 헤더나 토큰은 로그에 기록하지 않는다.

Pi 온라인 여부는 최근 heartbeat 수신 시각으로, 센서 상태는 장치 연결·측정 시각으로 각각 판단해야 한다. 과거 시뮬레이션 이력은 삭제하거나 새 측정으로 바꾸지 않는다. 인터넷 장애나 전원 차단 때는 실제로 오프라인 상태가 되며 이 서비스가 연결을 보장하거나 원격 안전 제어를 수행하지 않는다. 장치 안전 제어는 향후 ESP32의 로컬 interlock/fallback에 둔다.

wire schema, `/v1/edge/sync`, ACK와 MQTT 규격은 바뀌지 않는다. heartbeat 전용 프로세스와 일반 Gateway를 **같은 site/gateway ID로 동시에 실행하지 않는다.** 실센서 전환 시 heartbeat 서비스를 정지하고 기존 영속 DB·등록 세대·이벤트 순서를 명시적으로 연결한다. [서비스 설치·상태·전환 안내](deployment.md#센서-없는-pi의-heartbeat-서비스)를 참고한다.

외부 목적지는 HTTPS를 요구한다. 로컬 수신기 개발에만 `http://127.0.0.1:9000/...`, `http://[::1]:9000/...`, `http://localhost:9000/...`를 허용한다. HTTP habitatos 홈페이지를 토큰을 실어 보내는 수신 URL로 쓰지 않는다. 리다이렉트를 따라가지 않으며 OS 프록시 환경을 자동 사용하지 않는다.

## 요청

`POST <cloud.endpoint>`, `Content-Type: application/json`, `Authorization: Bearer <Pi 전용 키>`

| 필드 | 의미 |
|---|---|
| schema_version | 정수 1 |
| site_id / gateway_id | 등록한 매장과 Pi; 인증키에 묶인 값과 일치해야 함 |
| sent_at | 이번 전송을 준비한 UTC 시각 |
| gateway | 버전·transport·healthy, 각 사육장의 설정과 현재 상태 |
| events | 오래된 순서의 영속 이벤트, 최대 batch_size개 |

`gateway.cages[]`는 `configuration`과 `state`를 포함한다. configuration은 현재 CageConfig(센서 ID/단위/범위, node_id, revision, 정책)이며 state는 로컬 `/v1/cages/{cage_id}` 응답 형식이다. 전체 설정이나 환경 변수를 보내지 않으며 MQTT 비밀번호·SaaS 토큰·로컬 API 토큰은 payload에 넣지 않는다.

각 이벤트:

```json
{
  "schema_version": 1,
  "event_id": "e90d6b6f-956f-4bc8-a83e-e5d062b283bc",
  "event_sequence": 42,
  "kind": "telemetry.recorded",
  "site_id": "STORE-001",
  "gateway_id": "PI-001",
  "cage_id": "CAGE-001",
  "created_at": "2026-09-18T06:00:00+00:00",
  "payload": {
    "schema_version": 1,
    "data_source": "sensor",
    "message_id": "24989d0c-7a44-473d-bf85-682b57e2334c",
    "sampled_at": "2026-09-18T06:00:00+00:00",
    "received_at": "2026-09-18T06:00:00+00:00",
    "geometry_revision": 1,
    "placement_revision": 1,
    "readings": {"T1": {"value": 25.2, "quality": "valid"}},
    "actuators": {"light": true, "mister": false}
  }
}
```

`node_id`는 gateway.cages의 configuration에 포함된다. 이벤트와 등록 정보를 `(site_id, cage_id)`로 연결한다.

| kind | payload | 갱신 규칙 |
|---|---|---|
| telemetry.recorded | Telemetry + received_at | message_id와 sampled_at을 저장하고, 늦게 도착한 과거 값으로 현재 값을 덮어쓰지 않음 |
| command.updated | 로컬 `/v1/commands/{command_id}`와 동일한 command 객체 | 같은 command_id의 상태 이력. event_sequence를 비교해 오래된 상태로 돌아가지 않도록 함 |

이벤트 ID와 순서는 Pi DB에 저장되며 재전송해도 바뀌지 않는다. `command.updated`는 상태가 바뀔 때마다 새 이벤트 UUID를 받는다. `event_sequence`는 같은 Pi의 같은 DB 내 순서이며 모든 Pi의 공통 시계가 아니다. DB 초기화 후 재등록할 때는 새 gateway_id를 사용하거나 SaaS에서 등록 세대를 명시적으로 구분해야 한다. 같은 등록을 유지한 채 순서를 조용히 초기화하지 않는다.

gateway 부분은 매번 만드는 최신 상태이며 영속 이벤트가 아니다. 이벤트가 0개일 때도 연결 확인용으로 보낸다. 센서 데이터의 최신 여부는 **sampled_at과 received_at**으로 판단한다. sent_at을 측정 시각으로 쓰지 않는다. Pi가 온라인이어도 센서 값은 오래됐을 수 있다. `simulation`은 화면에서 명시하고 실측과 구분한다.

<a id="standalone-camera"></a>
## 별도 실시간 카메라 접속 (2026-10-20, Pi 배포)

사용자 요청에 따라 SaaS와 별도로 Pi의 `/camera` 페이지를 배포했다.
현재 주소는 `https://gateway.example.ts.net/camera`다. 기존 Tailscale
Funnel HTTPS 경로를 재사용했으며 터널·라우팅 설정은 변경하지 않았다.
이 주소는 인터넷에서 접근 가능하지만 영상 목록·재생목록·영상 조각에는 인증이 필요하다.

Pi에서 `/home/<gateway-user>/.config/habitatos/camera-viewer.html`을 열면 접속 버튼과
휴대폰용 QR을 볼 수 있다. `camera-viewer-qr.png`도 같은 폴더에 있다.
두 파일은 소유자만 읽는 0600이며 폴더는 0700이다. QR/링크 자체가 영상 접근
권한이므로 공개 문서·로그에 복사하지 않는다. 기존 웹 계정이나 Pi 관리자 비밀번호를
영상 페이지에 입력하지 않는다.

영상 전용 키는 외부 환경 파일 `/etc/habitat-gateway/gateway.env`의
`HABITAT_CAMERA_VIEWER_TOKEN`에 저장한다. 키가 없으면 영상 API는 503으로
닫히며, 키는 32자 이상이어야 한다. 링크 fragment의 키는 페이지를 열 때 지워지고
서버 URL 로그로 전송하지 않는다. `POST /camera/session`에서 키를 확인한 뒤
12시간 유효한 HttpOnly·SameSite=Strict 쿠키를 발급한다. HTTPS에서는 Secure도
설정한다. 영상 쿠키와 키는 기존 제어 API의 권한을 제공하지 않는다.
키를 변경하고 게이트웨이를 재시작하면 기존 영상 세션도 무효화된다.

카메라는 기존 `[[cameras]]` 설정의 `live_stream=true`로 선택한다. 기본값은
false다. 현재 RGB-001은 640×480, 설정 FPS 10으로 HLS를 생성하며 실제 카메라
입력 하나를 기존 녹화·미리보기와 공유한다. HLS 캐시와 영구 녹화 정책은 분리한다.
일시적 영상 단절은 브라우저에서 재연결하며, 실제 Pi 재부팅 복구 시험은 별도다.

플레이어는 로컬 번들의 hls.js 1.7.3 light 또는 브라우저 내장 HLS를 사용한다.
공식 npm tarball의 SHA-512 integrity를 확인했고 Apache-2.0 라이선스를 함께
포함했다. `hls-1.7.3.min.js` SHA-256은
`0251332c00a216a35d7d6919044d60da82b78beb3bd50ac6c662ae74a2f5474b`다.
외부 CDN 호출은 없다. 새 매장에서는 동일 프로그램과 매장별 카메라 설정·전용 키·
HTTPS 주소를 사용한다. 이번 소스에 현재 매장 호스트명을 하드코딩하지 않았다.

## SaaS 실시간 영상 전송 v1 (수신 서버 배포 대기)

사용자는 몇 초 지연을 허용하는 실시간 영상을 선택했다. 현재 운영 사이트
환경 화면 `/#environment/507a8d53-a6b1-49d7-aab3-1becba7a0451`은
STORE-001 / PI-001 / CAGE-001에 연결되어 있지만, 카메라 탭은 고정된
미연동 안내다. 웹 로그인으로 실제 프런트엔드와 사육장 조회를 확인했다.
웹 계정은 서버 코드 배포 권한이 아니며, 아래 수신 API의 운영 배포는 남아 있다.

### 데이터 경로와 활성화

`USB 카메라 → 기존 FFmpeg 입력 하나 → H.264 HLS → Pi HTTPS 송신기 → SaaS → 로그인한 브라우저`

기존 MKV 녹화와 30초 JPEG 미리보기에 HLS 출력을 추가한다. 조각은 2초,
재생목록은 최근 6개이며, 카메라 영상은 목표 비트레이트 1 Mbps로 재인코딩한다.
Base64 JSON 전송은 미디어 크기를 약 1/3 늘린다. 실제 지연·FPS·Pi 부하는
운영 촬영 조건에서 측정해야 한다. HLS 옵션은 [FFmpeg 공식 문서](https://ffmpeg.org/ffmpeg-formats.html#hls-2),
브라우저 재생은 [hls.js 공식 안내](https://github.com/video-dev/hls.js#embedding-hlsjs)를 참고한다.

Pi 설정의 기본값은 비활성이다. 수신기를 배포하고 해당 카메라를 등록한 다음
실제 외부 설정 파일에 다음 설정을 적용한다. 기존 `[[cameras]]` 항목에
`live_stream = true`를 추가하며 같은 카메라를 중복 선언하지 않는다.
Pi 0.4.15에는 이 기능이 포함되어 있다. 현재 RGB-001의 `live_stream`만 활성화했고,
SaaS `video_upload.enabled`는 false를 유지한다. 아래 설정은 수신 서버를 배포한
뒤 적용하는 예시다. 현재 운영 `/v1/edge/video` 조회는 404다.

```toml
[video_upload]
enabled = true
endpoint = "https://habitatos.kro.kr/v1/edge/video"
token_env = "HABITAT_CLOUD_TOKEN"
timeout_s = 5
retry_max_s = 30
```

`live_stream`은 카메라별 설정이며 `record_video`와 독립이다. 녹화 용량이
가득 차면 기존 클립을 보존하며 녹화 출력을 중지하고, HLS·미리보기는 유지한다.
실시간 임시 파일은 DB와 같은 runtime 디렉터리의 `cameras/live/<camera_id>/`에
놓는다. FFmpeg가 오래된 조각을 삭제하고 재시작 시 해당 캐시를 비운다.
최대 8개 완료 조각과 현재 작성 중인 조각을 유지한다. 영구 MKV 녹화는
기존 `cameras/recordings/` 정책을 따른다.

### 업로드와 ACK

`POST /v1/edge/video`, `Authorization: Bearer <등록된 Pi 토큰>`, JSON 본문.
영상은 `/v1/edge/sync`나 센서 outbox에 넣지 않는다. 센서 계약은 변경하지 않는다.
모델은 `habitat/saas/video_contract.py`, 명세는 `docs/api/edge-sync.openapi.json`에 있다.

| 필드 | 의미 |
|---|---|
| schema_version | 정수 1, 영상 계약의 버전 |
| site_id / gateway_id / cage_id / camera_id | 토큰에 등록된 매장·Pi·사육장·카메라 매핑 |
| session_id / session_started_at | 캡처 프로세스마다 새 UUID와 UTC 시작 시각 |
| sequence | HLS 조각 순서, 0..9007199254740991. FFmpeg epoch_us 시작 번호로 재시작 후 증가 |
| captured_at / duration_s | 조각의 program date time / 최대 4초. 센서 동기화 정밀도를 보장하는 시각은 아님 |
| content_type | `video/mp2t` |
| sha256 / data_base64 | TS 원본의 SHA-256 / Base64 바이트 |

JSON 전체는 3 MiB, 디코딩한 TS는 2 MiB 이하다. 참고 수신기는 MPEG-TS 패킷
길이·동기 바이트·해시를 검사한다. 이는 임의 업로드의 H.264 디코딩 검증을
대신하지 않는다. 운영 배포는 허용된 Pi만 업로드하도록 제한한다.
수신 측은 촬영 시각이 15초보다 오래되거나 서버보다 5초 넘게 미래이면 거절한다.
Pi와 SaaS의 시계를 동기화한다.

커밋 후 HTTP 200과 `schema_version, site_id, gateway_id, cage_id, camera_id,
session_id, sequence, sha256`를 반환한다. Pi는 모든 필드가 요청과 정확히
일치해야 성공으로 인정한다. 동일 재시도는 같은 ACK, 다른 내용·이전 세션은 409,
인증 401/403, 크기 413, 형식 422, 저장 실패 503이다. 리다이렉트는 따라가지 않고
응답 본문은 로그에 기록하지 않는다.

Pi 송신기는 카메라마다 별도 작업으로 실행한다. 0.5초마다 완료된 최근 조각을
확인하고, 실패하면 임의 지연을 섞어 최대 30초까지 재시도 간격을 늘린다.
오래된 영상은 쌓지 않고 최신 조각으로 따라잡는다. 느린 카메라 전송이 다른
카메라나 MQTT·센서 동기화를 기다리게 하지 않는다. 상태는 인증된
`GET /v1/cameras`의 `video_upload`에서 최근 성공·오류·연속 실패를 확인한다.

### SaaS 저장과 브라우저 조회

참고 구현은 별도 `video_streams`, `video_segments` 테이블을 사용한다.
카메라마다 최신 세션만 유지하며 최대 12개 조각을 저장한다. 새 세션이 오면
이전 세션 조각을 삭제하고, 뒤늦은 이전 세션이 최신 상태를 덮어쓰지 못하게 한다.
재생목록은 최신 연속 6개 이하만 포함하므로 통신 장애 중 빠진 순서를 위조하지 않는다.

- `GET /v1/video/{site_id}/{gateway_id}/{camera_id}/index.m3u8`
- `GET /v1/video/{site_id}/{gateway_id}/{camera_id}/{session_id}/{sequence}.ts`

두 조회 모두 인증과 카메라 접근 권한 검사가 필요하다. 최신 영상이 15초 넘게
오래되면 재생목록은 503을 반환하고 화면은 연결 끊김 상태를 표시한다.
운영 SaaS는 기존 웹 세션·사육장 권한을 그대로 사용한다. Pi 토큰은 브라우저로
보내지 않는다. 로컬 참고 수신기의 선택적 `[[viewers]]`와 별도 bearer token은
개발용 조회 인증이며 운영 웹 로그인 구현을 대체하지 않는다.

기존 카메라 탭의 플레이어는 동일 출처 URL과 세션을 사용하고, 네이티브 HLS
또는 프로젝트에서 관리하는 고정 버전 hls.js로 재생한다. `liveSyncDurationCount: 2`
등으로 지연을 조정하되 네트워크 장애 처리·재연결·컴포넌트 종료 시 정리를 구현한다.
관련 SaaS 작업 지시는 [실제 저장소용 지시서](api/saas-codex-prompt.md)에 있다.

기존 설정은 `live_stream=false`, `video_upload.enabled=false`로 호환된다.
센서 DB·이벤트 순서는 변경하지 않는다. 소스를 구현한 것과 운영 SaaS에서 재생한
것은 별도 검증이다. 별도 Pi 영상 페이지의 배포·실행 증거는 위 안내와
[운영 기록](operations/hardware-arrival.md#standalone-camera-20261020)을 따른다.
운영 SaaS로의 영상 업로드·해당 사이트 카메라 탭 재생은 미검증이다.

### 구현 검증 기록

2026-10-20 검사: 영상 계약·기존 센서/API·실제 FFmpeg 통합 묶음 **101 passed**,
엄격한 ACK·느린 전송 격리·인증·CLI 재연결 추가 묶음 **67 passed**,
기존 시작/설정 검사 CLI **35 passed**. 묶음 사이 중복이 있으며 합산 횟수가
고유 테스트 수는 아니다. Starlette/AnyIO의 기존 deprecation 경고만 남았다.
샌드박스에서 TestClient가 멈춘 실행은 중단하고 샌드박스 밖에서 재검증했다.

FFmpeg 통합 검사는 합성 MJPEG 입력 하나에서 MKV·JPEG·HLS를 동시에 만들고,
완료 조각을 실제 송신기로 참고 수신기에 전달한 뒤 조회한 TS를 FFprobe로
H.264/해상도 확인했다. 녹화 한도 도달 시 클립을 보존하면서 실시간 출력만
이어가는 세션 전환도 검사했다. 실제 카메라 영상의 운영 SaaS 업로드 증거로
해석하지 않는다. 테스트 임시 파일과 웹 코드 확인용 임시 파일은 제거했다.

## 서버 응답과 재전송

**DB에 영속 저장한 이벤트만** HTTP 200으로 수신 확인한다.

```json
{
  "schema_version": 1,
  "site_id": "STORE-001",
  "gateway_id": "PI-001",
  "accepted_event_ids": ["e90d6b6f-956f-4bc8-a83e-e5d062b283bc"]
}
```

수신 키 `(site_id, gateway_id, event_id)`에 유일성 제약을 둔다. 같은 이벤트의 중복 수신도 저장 완료로 처리해 같은 ID를 반환한다. 서버 저장 후 연결이 끊겨도 이 방식으로 재전송을 처리한다. HTTP 200만 보내거나, 빈 JSON·데모 HTML·다른 Pi의 응답·보내지 않은 ID·중복 ID를 반환하면 Pi는 성공으로 처리해 삭제하지 않는다.

부분 수신이면 저장한 ID만 반환할 수 있다. Pi는 그 항목만 삭제하고 나머지는 재전송한다. 보통은 묶음 전체를 한 트랜잭션으로 저장하고 모든 ID를 반환한다. 인증 오류·서버 오류·시간 초과에도 이벤트를 보존한다. 응답 크기는 최대 64 KiB, 요청 전체 제한 시간은 timeout_s다. 실패 시 간격을 늘려 최대 retry_max_s까지 임의 지연을 섞어 재시도한다. 연속성이 확인된 이벤트 전송에 성공하고 대기열이 남았으면 50 ms 후 다음 묶음을 보낸다. 대기열이 비었거나 연속성 차단 중인 하트비트에 성공하면 interval_s를 유지한다. 차단된 이벤트가 남았다는 이유로 하트비트를 50 ms 간격으로 보내지 않는다.

클라우드에 등록한 DB를 다른 site_id/gateway_id로 보내려 하면 시작할 때 거절한다. Pi마다 별도 DB를 쓴다. 기존 로컬 DB를 처음 클라우드에 등록할 때도 과거 담당 ID가 일치하는지 확인해야 한다.

## SaaS 담당 구현 항목

1. Pi 인증키를 발급하고 키에서 tenant/site/gateway/허용 cage를 찾는 등록 정보를 만든다.
2. 외부 필드와 각 이벤트의 ID 일치, 종류, 자료형, 크기, revision, 담당 사육장을 검사한다.
3. 중복 제거·이벤트 저장·현재 값 갱신을 수행하고 DB 커밋 후 수신한 ID를 반환한다.
4. 기기 현재 상태와 이벤트 이력을 따로 저장한다. 과거 이벤트가 재전송되어도 최신 화면을 되돌리지 않는다.
5. 로그인한 브라우저용 조회 API나 SSE 등을 구현해 기존 데모 화면과 연결한다. 서버에서도 매장별 접근 권한을 검사한다.

이 Pi용 API에서 미등록 Pi가 다른 매장이나 다른 Pi 담당의 사육장을 임의로 등록하게 해서는 안 된다. 등록과 담당 이관은 별도 관리 작업으로 처리한다.

## 운영과 검증 범위

로컬의 인증된 `GET /v1/cloud`에서 enabled, 미전송 개수, 가장 오래된 미전송 시각, 최근 성공 시각, 오류 코드를 확인한다. `/health`는 로컬 제어 상태를 반환한다. SaaS 장애만으로 로컬 제어를 멈추지 않으며 SaaS 연결 상태는 따로 표시한다.

전송 대기 이벤트는 원래 센서 기록/명령 저장과 같은 SQLite 트랜잭션에 쓴다. 네트워크를 기다리는 동안 제어 잠금을 유지하지 않는다. 전송은 제어 루프와 별도 async 작업으로 실행하고 종료 시 취소해 미확인 항목을 남긴다. 같은 저장 매체가 고장 나거나 가득 찼을 때까지 제어 지속을 보장하는 기능은 아니다.

기존 DB 스키마 1에 테이블만 추가하며 과거 데이터를 다시 쓰지 않는다. 구버전 프로그램 실행 중에는 클라우드 이벤트가 추가되지 않는다. 로컬 이력과 미전송 이벤트에는 아직 자동 삭제/용량 제한이 없다. 양산 전 수집량에 맞는 용량 감시와 보존 기간 설계가 필요하다. 계속 실패하는 이벤트를 자동으로 버리지도 않으므로 pending_events/last_error를 운영에서 확인해야 한다.

테스트는 수신 확인, 중복, 재전송, 부분 수신, 잘못된 ID, 인증 실패, 시간 초과, 재시작, 취소, 여러 묶음 전송, 동시 로컬 명령과 연속성 차단 중 하트비트를 검사한다. 별도 실행한 CLI와 로컬 HTTP 수신기로 가상 사육장 3개의 장애 후 재전송도 검증했다. **운영 SaaS에서는 과거 가상 측정의 ACK와 화면 표시, 현재 Pi의 하트비트 ACK를 확인했다. 현재 충돌 이벤트 1건의 전달·정상 ACK와 실제 센서·카메라 연동은 미완료다.**

HTTP 클라이언트 구현 참고: [HTTPX async](https://www.python-httpx.org/async/), [시간 제한](https://www.python-httpx.org/advanced/timeouts/).

<a id="air-estimate-v1"></a>
## 2026-10-25 공기 온도 추정 전송 v1

Pi에서 계산한 사육장별 R13 격자를 SaaS 환경 화면에 전달하는 별도 계약이다.
SaaS가 최신 센서 세 값만으로 R13을 다시 계산하지 않는다. R13은 이전 격자와
시각을 유지하므로 동일한 현재 측정값만으로 Pi의 결과를 재현할 수 없다.
현재 모델은 **20 × 20 × 30 cm 사육장만 지원**한다. 센서 좌표·순환 흐름·벽
열교환은 설정과 가정이며, 이 화면의 구현이 물리적 정확도 검증을 뜻하지 않는다.

계약은 [air_contract.py](../habitat/saas/air_contract.py)의 `AirEstimate`,
`AirAck`, `AirSensor`, `AirGrid`, `AirRegistrationBinding`과
[OpenAPI](api/edge-sync.openapi.json)를 따른다. `MODEL_ID=bb6-air-r13`,
`MODEL_VERSION=1`, `schema_version=1`이며 다른 모델·격자는 현재 거절한다.
전송기는 [air.py](../habitat/saas/air.py), 참고 수신기는
[air_receiver.py](../habitat/saas/air_receiver.py)에 있다.

### 경로와 등록

- Pi 전송: `POST /v1/edge/air`, JSON, 기존 Pi bearer 인증과 등록 범위 검사.
- 웹 조회: `GET /v1/enclosures/{enclosure_id}/air`, 기존 로그인 세션과 사육장 권한 검사.
- 참고 ASGI 앱은 `mount_air_receiver(..., registrations=registrations)`로 등록한다.
  참고 구현의 별도 viewer bearer는 개발용이며 운영 웹 세션의 대체물이 아니다.

서버의 `Registration.air_cages`는 cage ID를 node·웹 사육장 UUID·revision으로
명시적으로 연결한다. 미등록 사육장을 전송 본문만으로 만들지 않으며, Pi 본문에는
`enclosure_id`를 넣지 않는다. 다음은 참고 수신기의 TOML 형식이다. UUID와 node,
두 revision을 **운영 SaaS의 기존 DB 및 현재 Pi 설정과 대조한 뒤** 적용한다.

```toml
[[gateways]]
site_id = "STORE-001"
gateway_id = "PI-001"
cage_ids = ["CAGE-001"]
token_env = "HABITAT_CLOUD_TOKEN"

[gateways.air_cages.CAGE-001]
node_id = "ESP32-001"
enclosure_id = "507a8d53-a6b1-49d7-aab3-1becba7a0451"
geometry_revision = 1
placement_revision = 1
```

다른 사육장은 같은 프로그램과 별도 등록·설정으로 구분한다. 조회 시 UUID를 서버
등록에서 해석하고 로그인 사용자의 site/gateway/cage 범위를 다시 확인한다.
revision이 변경되면 이전 격자는 숨기고 일치하는 새 결과를 기다린다.

### 본문과 검증

필수 출처 정보는 `estimate_id`, `site_id`, `gateway_id`, `cage_id`, `node_id`,
`source_message_id`, `sampled_at`, `generated_at`, 두 revision, `config_sha256`이다.
UUID·timezone이 있는 시각·정수 revision·SHA-256 형식과 추가 필드 금지를 검사한다.
`sensors`는 T1/T2/T3 각각의 `id,label,xyz_m,value_c`이며, 서로 다른 사육장 내부
좌표와 유한한 온도를 요구한다. 원본 측정은 센서 점, 격자 값은 공간 추정으로 표시한다.

`grid`는 `shape_zyx=[30,20,20]`, `spacing_m=0.01`,
`origin_m=[0.005,0.005,0.005]`, `order=zyx`로 고정한다. `dimensions_m`은
`[0.2,0.2,0.3]`이다. 주 추정 격자 하나만 전송하며 IDW baseline은 필수가 아니다.

`encoding=zlib-f32le-base64`이며 12,000개 값을 little-endian Float32로 만든다.
그 **48,000바이트 원문**의 SHA-256이 `field_sha256`이고, zlib 압축 후 base64로
표현한 문자열이 `field_base64`다. `encode_field`/`decode_field`를 재사용할 수 있다.
JSON 본문은 `MAX_AIR_BODY=96 KiB`로 제한한다. 압축 해제 중 48,001바이트까지만
확인하고 정확히 48,000바이트인지 검사하며, 잘린 스트림·후행 데이터·연결된 추가
압축 스트림을 거절한다. 해제된 모든 값은 유한하고 −55..125 °C 범위여야 한다.

Pi 화면에서 이미 소수 넷째 자리까지 표현한 격자를 Float32로 전송하므로 숫자 대조는
절대 오차 `1e-5 °C` 이내의 직렬화 차이를 허용한다. 이는 센서 정확도 보장이 아니다.
전송 무결성은 Float32 원문 해시의 **완전 일치**로 확인한다. `color_range_c`를
보내면 Pi의 누적 색 범위를 보존하며 모든 격자·실측값을 포함하는 유한한 범위인지
검사한다. `source_accepted_samples`·`source_gap_resets`는 Pi의 원본 횟수이며,
SaaS 수신 횟수로 대체하지 않는다. 없는 수신 횟수는 0으로 표시한다.

### ACK, 최신성, 보관 한도

새 최신 후보는 측정·생성 시각이 현재보다 30초 넘게 오래되거나 5초 넘게 미래면
거절한다. 처음 받는 과거 표본도 미래 생성 시각 검사를 우회하지 못한다.
HTTP 200만으로 성공을 판정하지 않는다. DB 커밋 후 반환하는 `AirAck`의 schema,
site/gateway/cage/node, `estimate_id`, `source_message_id`, `field_sha256`이
요청과 일치해야 하며 `outcome`은 `stored`, `duplicate`, `superseded` 중 하나다.
`stored`는 최신 결과 저장, `duplicate`는 보관 중인 같은 내용의 재수신,
`superseded`는 같거나 이전 측정이어서 최신 결과를 교체하지 않았다는 뜻이다.

같은 ID의 다른 내용은 receipt 또는 최신 결과가 남아 있는 동안 409로 거절한다.
사육장마다 최신 격자 1개와 최근 receipt 해시 256개만 보관한다. 퇴출된 receipt의
과거 중복·충돌 여부를 영구히 증명하지 않으며, 이 저장소는 역사 기록 원장이 아니다.
퇴출된 과거 표본이 다시 와도 최신 측정 이전이면 `superseded`로 처리한다.
저장 실패는 ACK 없이 503, 범위 위반은 403, revision 불일치는 409,
잘못된 본문·압축은 422, 요청 크기 초과는 413으로 처리한다.

조회 freshness는 매번 `sampled_at` 기준 30초와 미래 허용 5초로 판단한다.
중복 전송·웹 조회로 측정 시각이나 최초 서버 수신 시각을 갱신하지 않는다.
만료되면 `fresh=false, held=true, status=stale`과 이유를 반환한다. 등록된 UUID에
결과가 없으면 404다. `received_at_utc`는 이 API의 서버 수신 시각이며 Pi 측정
수신 시각을 대신하지 않는다. `source_message_id`는 인증된 Pi가 선언한 출처로,
원본 센서 기록이 SaaS의 기존 측정 DB에 이미 커밋됐다는 독립적인 증거는 아니다.

### 화면 통합과 적용 상태

공통 웹 자산은 [air/web](../habitat/digital_twin/air/web)에 있다. 반환 본문은 기존
AirState 화면 형식이며 `source_mode=live`, 주 `field`, `baseline=null`을 지원한다.
0.4.19 로컬 화면은 저장 기록 복원을 위해 선택 필드 `data_origin`, `history_samples`,
`live_samples`, `loaded_at`과 `history` 상태를 추가한다. 공통 웹 자산은 이 필드가 없는
기존 SaaS 응답도 계속 지원한다. 로컬 기록 복원·지연값 표시는 `fresh=false`로 유지하며
기존 `AirEstimate` 업로드 계약이나 서버 저장 정책은 바꾸지 않는다.
같은 출처의 조회 주소를 `#air-app`의 `data-air-endpoint`로 지정하거나 초기화 후
`window.HabitatAirView.setEndpoint('/v1/enclosures/<uuid>/air')`를 호출한다.
SPA는 유지되는 뷰 DOM에서 endpoint를 전환하며 이전 값을 지우고 늦은 응답을 버린다.
DOM을 교체하는 프레임워크는 컴포넌트 수명주기에 맞게 이식하거나 같은 출처의
뷰 문서를 사용한다. 운영 API가 다른 경로이면 같은 출처 alias를 연결한다.
브라우저에 Pi 토큰을 주거나 Pi의 `127.0.0.1:8765`를 SaaS 조회 주소로 쓰지 않는다.

기존 `/v1/edge/sync`, 측정 이벤트 대기열·sequence·ACK·MQTT·센서 설정은 바꾸지
않는다. 공기 추정 전송 장애가 기존 수집·로컬 제어를 막지 않도록 분리한다.
운영 SaaS 소스와 배포 접근이 제공되지 않아 **실제 SaaS 배포·조회는 미검증**이며,
Pi의 SaaS 공기 추정 업로드는 비활성 상태다. 서버 적용 후 자연 발생한 실제
`message_id`와 격자 해시를 Pi→커밋/ACK→해당 UUID 화면까지 대조해야 한다.
서버 작업 순서는 [SaaS 담당 지시서](api/saas-codex-prompt.md#air-saas-work)를 따른다.
