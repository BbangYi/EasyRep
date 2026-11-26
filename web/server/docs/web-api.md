# EasyRep 브라우저 조회 API · v1

Base URL: `https://habitatos.kro.kr`. 같은 출처의 Django 세션 쿠키로 인증한다. Pi bearer 키는 이 API의 로그인 수단이 아니다. 비로그인은 401, 다른 계정 범위의 사육장은 404. 모든 조회 응답은 `Cache-Control: no-store`.

| 경로 | 응답/조건 |
|---|---|
| `GET /api/session/` | `user`, 접근 가능한 `enclosures`, `site`, `csrfToken` |
| `GET /api/enclosures/` | `asOf`, `items`, `truncated`. 최대 200개 |
| `GET /api/enclosures/{id}/` | `asOf`, `item` |
| `GET /api/enclosures/{id}/history/?hours=6` | 측정 이력과 같은 시간축의 명령 기록 |
| `GET /api/enclosures/{id}/records/?kind=all` | 최신 발생순 원본 기록, 상세 payload |
| `GET /api/enclosures/{id}/commands/` | 명령별 가장 최근 처리 상태 30건 |

`{id}`는 등록 시 만든 내부 사육장 ID이다. Pi의 `cage_id`와 같다고 가정하지 않는다. URL에 site_id/role을 추가해 권한을 넓힐 수 없다.

## 현재값

사육장 item은 `id`, `name`, `store`, `siteId`, `cageId`, `gateway`, `sampledAt`, `piReceivedAt`, `stale`, `source`, `sensors`, `actuators`, `mode`, `staleAfterSeconds`, `geometryRevision`, `placementRevision`, `configurationChanged`를 포함한다.

- `gateway`: `id`, `status`, `lastReceivedAt`. 상태는 `unregistered`, `disabled`, `waiting`, `offline`, `connected`.
- `source`: `sensor`, `simulation`, 미수신 시 null. simulation을 실측처럼 표현하지 않는다.
- `sensors`: `{id, unit, value, quality}[]`. 단위는 `degC`, `percent_rh`, `lux`. 오류·미수신 값은 null.
- `actuators`: Pi snapshot의 관측 상태와 관측 시각. 명령 요청과 구분한다.
- `asOf`: SaaS 조회 기준 시각. 측정 시각이 아니다.
- `configurationChanged=true`: 최신 구성과 보관된 측정의 revision이 다르다. 기존 수치를 새 구성의 값처럼 표시하지 않는다.

## 이력

`hours=1|6|24`, 선택적 `end=<timezone을 포함한 ISO 8601>`. end 기본값은 서버 현재 시각이다. 임의로 마지막 측정 시각으로 이동하지 않는다.

응답: `start`, `end`, `points`, `commands`, `truncated`, `commandsTruncated`, `limit`, `olderThan`, `next`.

- point: `eventId`, `at`(sampled_at), `serverReceivedAt`, 원본 telemetry payload의 data_source/readings/received_at/revision 등.
- 가장 최근 2000개 측정까지 조회한다. 정렬은 sampled_at/received_at/측정 UUID 내림차순이며, 반환 points는 선택된 페이지를 역순으로 나열한다.
- `next`가 있으면 `before=<next 원문>`으로 이어본다. `before`는 `sampled_at|received_at|측정 UUID` cursor다. 세 필드를 이 순서대로 사전식 비교하여 경계보다 엄격히 이전인 행만 반환한다. 시각은 timezone과 마이크로초를 보존하며 클라이언트에서 Date/밀리초로 변환하지 않는다. 모든 요청 값은 URL 인코딩한다.
- cursor는 요청한 `[end-hours, end]` 범위 안에 추가로 적용된다. API 호출자가 같은 `hours`와 첫 응답 `end`를 유지하면 고정 범위를 탐색하며 `next=null`이면 그 범위의 끝이다.
- UI의 ‘이전 측정 보기’는 기존처럼 더 오래된 시간 범위로 이동한다. 같은 `hours`, 직전 응답의 `olderThan` 원문을 `end`, `next` 원문을 `before`로 보낸다. 경계 시각의 나머지 행과 새로 확장된 이전 시간 범위를 함께 조회하되 이미 본 행은 cursor로 제외한다. `olderThan`이 없는 응답은 `end`를 유지한다. 기간 변경·현재 시점·마지막 측정 이동에서는 cursor를 비운다. 원본은 DB에 남는다.
- `before`가 없으면 기존 hours/end 조회와 같다. 형식·시각·UUID가 잘못된 cursor(빈 값 포함)는 400 `invalid_cursor`, 잘못된 hours/end는 400 `invalid_period`다. cursor는 권한을 부여하지 않으며 항상 로그인 계정의 허용 사육장 범위에서 조회한다.
- `olderThan`은 기존대로 truncated 페이지의 가장 오래된 sampled_at이며, 비어 있거나 끝난 페이지에서는 null이다. 구형 클라이언트의 earlier-end 조회는 유지되지만 같은 시각 경계의 나머지 기록을 보장하지 못하므로 새 클라이언트는 `next`를 우선 사용한다. `next`가 없는 구형 서버에서는 기존 olderThan 방식으로 이어본다.
- command marker: `id`, `at`, `actuator`, `action`, `status`. 최대 500개, 초과 여부 별도 표시. cursor는 측정 행에만 적용되므로 명령 표시는 해당 페이지의 hours/end 시간 범위를 사용한다.
- 프론트엔드는 quality가 valid인 값만 사용한다. 센서 오류·stale_after_s를 넘긴 공백은 선으로 연결하지 않는다.
- 현재 구성과 다른 revision은 그래프와 CSV에서 제외하고 건수를 표시한다. 원본 payload는 기록 조회에 남는다.
- CSV는 현재 선택한 기간·센서·조회 범위의 수신 데이터만 포함한다. 전체 이력 다운로드라고 표시하지 않는다.

## 기록

`kind=all|telemetry.recorded|command.updated`, `q=<최대80자 키워드>`, `before=<이전 응답의 next>`.

응답 `items[]`: `id`, `kind`, `at`, `serverReceivedAt`, `sequence`, `payload`. 페이지당 50개. `next`가 null이면 끝이다. 발생 시각 내림차순, 같은 시각은 저장 ID 내림차순으로 고정한다. 서버 수신 시각은 별도 유지한다.

검색은 Pi가 보낸 센서·장치 ID와 payload 내용을 대상으로 한다. UI 한글 상태 설명을 번역 검색하는 기능은 아직 없다.

이상 이벤트의 사용자 확인/복구, GPU 결과, 카메라 프레임은 이번 Pi 계약에 없다. 임의로 생성하거나 API에 있는 것처럼 노출하지 않는다.

## 쓰기 작업

계정·매장·Pi 수신 설정은 서버 렌더링 관리 폼과 CSRF 검증을 사용한다. 일반 센서 화면에는 장치 제어용 POST API가 없다. 별도로 연결한 카메라의 IR은 아래 전용 API와 역할 검증을 사용한다.

## 카메라 HLS 중계와 IR

`GET /api/enclosures/{id}/camera/`는 현재 Pi 카메라 상태와 같은 출처의 재생 목록 주소를 반환한다. 영상 경로는 `GET /api/enclosures/{id}/camera/hls/{camera_id}/index.m3u8`, `GET /api/enclosures/{id}/camera/hls/{camera_id}/{session_uuid}/{sequence}.ts`다. 모든 요청에서 로그인, 사용자의 사육장 범위, 활성 Gateway와 현재 site/gateway/cage/camera 연결을 확인한다. Pi 키는 서버에서만 사용한다. 사육장에 아직 연결하지 않은 `/api/camera/`와 그 하위 경로는 기존대로 owner 전용이다.

HLS 요청에 한해 Pi의 장치 목록에서 검증한 카메라 ID 집합을 프로세스당 최대 32건, 3초 동안 재사용한다. 같은 구성의 동시 조회는 한 번만 요청하고 대기한다. 키는 전체 설정의 해시를 포함하므로 인증 키나 장치 매핑을 변경하면 이전 항목을 재사용하지 않는다. 별도 상태 조회에서 장치 식별 불일치나 조회 실패가 관측되면 해당 항목을 무효화하며, 진행 중인 조회도 이를 되살리지 못한다. 만료 후 갱신 실패 시 이전 값을 제공하지 않는다. 캐시는 권한을 부여하지 않으며 영상·프레임 시각·`fresh` 상태를 보관하지 않는다. 카메라 목록/상태 조회와 IR 작업은 이 캐시를 사용하지 않는다. Pi 측 식별 변경의 미관측 기간은 최대 TTL만큼 남을 수 있으므로 설정 변경과 Pi의 미디어 권한 검증도 유지해야 한다.

HLS view의 응답에는 `Cache-Control: no-store`, `X-Accel-Buffering: no`, `X-Request-ID`가 붙는다. Pi 미디어의 404/503은 그대로 전달하고, 404를 빈 영상이나 200으로 바꾸지 않는다. 재생 목록은 최대 128,000바이트이며 상대적인 UUID/순번 `.ts` 주소만 허용한다. 영상 조각은 Pi 계약에 맞춰 최대 2 MiB까지 읽어 응답한다. 이는 크기를 제한한 전체 본문 중계이며 점진적 스트리밍이 아니다. `X-Accel-Buffering`의 실제 반영 여부는 운영 역방향 프록시 설정도 확인해야 한다.

로그인·목록 조회·미디어 요청·동시 조회 대기는 HLS 요청 시작 후 8초의 남은 예산을 공유한다. 각 네트워크 호출에 남은 시간을 socket timeout으로 전달하며 401 재로그인도 예산을 초기화하지 않는다. `urllib` timeout은 소켓의 대기 제한이므로 느린 연속 수신 전체를 8초 안에 강제로 종료하는 총시간 제한은 아니다. 실제 프록시/WSGI timeout과 관측된 요청 시간을 함께 확인해야 한다. IR의 기존 timeout·재시도 동작은 변경하지 않는다.

`habitat.camera_ir`는 INFO 수준으로 콘솔에 `camera_hls` JSON 한 줄을 남긴다. 필드는 `request_id`, `kind`, 검증된 `camera_id`, UUID인 `session_id`, 0 이상 2⁶³ 미만인 `sequence`, `response_status`, `duration_ms`, `upstream_ms`, `inventory_cache`와 각 upstream의 `kind/status/duration_ms/error`다. URL·쿼리·본문·쿠키·인증 키·원본 예외 메시지는 기록하지 않는다. 요청 ID는 첫 글자가 영숫자이고 영숫자/`_.:-`만 쓰는 최대 64자 값을 허용하며, 나머지는 새 UUID로 대체한다. 같은 ID를 Pi 요청 헤더에 전달하지만 현재 Pi access log는 이 헤더를 기록하지 않으므로 양쪽 로그의 요청 ID 대조까지 검증된 것은 아니다. 인증 미들웨어·CSRF·메서드 검사에서 view 전에 거절된 요청은 이 HLS 전용 로그/헤더 대상이 아니다. IR 작업에는 이 로그를 추가하지 않는다.

`GET .../camera/ir/`는 관측 상태를 조회한다. `POST .../camera/ir/command/`는 기존대로 owner/manager 역할과 Django CSRF 검증을 요구한다. 허용 본문은 `{"action":"on"}` 또는 `{"action":"off"}`이고 ON은 서버에서 300초로 제한한다. Pi 제어 권한과 Pi CSRF도 확인한다. 이번 HLS 변경에는 IR 명령이나 자동 재시도를 추가하지 않았다.

자동 시험은 동일한 구성의 미디어 두 요청에서 upstream 목록 요청이 2회에서 1회로 줄고, 매번 미디어 요청은 유지되는 것을 확인한다. 이는 네트워크 왕복 횟수 검증이며 운영 SaaS 지연 개선 수치는 배포 후 같은 시간대의 요청 ID·상태·소요 시간으로 측정해야 한다.

## 측정 누적 이력

`history.points`는 서버가 받은 스냅샷과 Pi 측정 이벤트를 message_id 기준으로 합친 이력이다. `id`는 안정적인 측정 이력 ID, `piEventId`는 실제 Pi 이벤트 ID(스냅샷만 수신했으면 null), `receiptSource`는 `snapshot` 또는 `event`다. 호환 필드 `eventId`는 기존 화면의 행 식별용이며 `id`와 같다. Pi 이벤트 원본은 `records`에서 조회한다. `serverReceivedAt`은 최초 서버 저장 시각이며 `sampled_at`과 Pi `received_at`은 원본을 유지한다. CSV는 측정 이력 ID·실제 이벤트 ID·수신 경로·센서 message_id를 구분한다. 같은 측정의 후착 이벤트는 행을 추가하지 않는다. 2000건 조회 제한·이전 구간 조회는 유지하며 저장된 데이터는 삭제하지 않는다.

### 공간 추정 화면

사육장 응답의 `spatialLayout`은 해당 사육장 UUID, Pi ID, 사육장 ID 및 geometry/placement revision이 모두 일치할 때만 제공한다. 미등록·배치 변경 시 null이다. `edge/spatial-layouts.json`은 확인한 배치의 버전별 배포 설정이며 다른 사육장에 자동 적용하지 않는다. 현재 CAGE-001 설정은 사용자가 공유한 Pi 화면의 20×20×30cm와 T1/T2/T3 좌표를 옮긴 것으로 `positionsVerified: false`다. 새 배치는 revision을 변경하고 별도로 검증하여 등록한다.

브라우저는 센서 출처, 유효 품질, 일치하는 배치 버전의 온도만 사용한다. 가중치 1/d² 보간은 공기 흐름·장애물·습도 분포·물리 시뮬레이션·3DGS 학습을 포함하지 않는다. 세 센서 미만이면 공간 색상을 표시하지 않는다. 오래된 최신값에는 경고를 유지한다. 누적 이력은 기존 인증된 history API를 사용하며 최대 2,000건/페이지, 이전 기록 조회, 시각별 재생을 제공한다. 시간 사이의 누락을 메우거나 가상 기록을 실측으로 표시하지 않는다. 과거 화면도 등록된 가정 배치에 해당 시점의 실측을 적용한 추정이다.
