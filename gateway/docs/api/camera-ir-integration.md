# SaaS 개발자 전달: CAGE-001 RGB 카메라 2대와 IR 조명 제어

대상 화면은 기존 `https://easyrep.kro.kr/manage/`입니다. 기존 로그인과 매장·사육장 권한을 유지하면서 **사육장별 TOP/FRONT 영상과 IR 계속 켜기·끄기·선택 타이머**를 연결합니다. IR은 적외선 조명 출력 제어이며 온도·열화상 센서 API가 아닙니다.

Pi에는 카메라 조회와 IR 제어 API가 구현·배포되어 있습니다. 이 전달본은 그 API를 SaaS에 연결하기 위한 계약과 클라이언트입니다. **SaaS 운영 소스의 수정·배포와 SaaS 화면에서의 최종 연결 검증은 아직 수행하지 않았습니다.** 기존 센서 동기화와는 호출 방향이 다른 추가 기능입니다.

## 1. 전달 파일과 현재 대상

| 파일 | 용도 |
| --- | --- |
| [camera-ir.openapi.json](camera-ir.openapi.json) | 현재 Pi의 HTTPS API 명세 |
| [HabitatOS.CameraIR.postman_collection.json](HabitatOS.CameraIR.postman_collection.json) | 로그인, 목록·영상·IR 상태 및 명시적 제어 요청 예제 |
| [camera_ir.py](../../habitat/saas/camera_ir.py) | SaaS 백엔드용 Python 클라이언트 |
| [IR 제어 프로토콜](../protocols/ir-control.md) | ESP32 출력 상태, 명령 유효 기간, 장애 시 OFF 동작 |
| [기존 센서 API 안내](README.md) | Pi → SaaS 센서 수신 계약. 이번 연결로 변경하지 않음 |

현재 Pi의 기본 주소는 `https://gateway.example.ts.net`이며, 계약 기준 버전은 **0.4.24**입니다. `/camera`는 Pi 자체 화면이고, API 호출 시 기본 주소에 아래 경로를 붙입니다.

| 매장 / Gateway | 사육장 | 등록 역할 | 카메라 ID | IR 제어 |
| --- | --- | --- | --- | --- |
| `STORE-001` / `PI-001` | `CAGE-001` | TOP | `RGB-001` | CAGE-001 단위로 제공 |
| `STORE-001` / `PI-001` | `CAGE-001` | FRONT | `CAGE-001-FRONT` | 위와 같은 조명 제어 |

두 카메라의 등록 영상 크기는 800 × 640입니다. 실제 크기·연결 상태·등록 역할은 목록 응답으로 읽습니다. 위 표는 등록 정보이며 실물 부착 위치를 새로 검증했다는 뜻은 아닙니다. CAGE-002·003은 사육장 등록이 있어도 현재 카메라 연결과 IR 설정이 완료된 대상이 아니므로 사용 가능으로 표시하지 않습니다.

다른 매장에는 같은 코드를 배포하고 매장 ID, Gateway ID, 신뢰할 Pi 주소, 사육장·카메라 매핑과 비밀 설정만 추가합니다. `STORE-001`, `CAGE-001`, 현재 주소를 SaaS 업무 로직에 고정하지 않습니다.

## 2. 연결 구조와 인증 책임

```text
사용자 브라우저
  → 기존 SaaS 로그인·권한 검사
  → SaaS 백엔드의 매장별 카메라/IR 프록시
  → 등록된 Store Pi의 HTTPS /camera API
      → DFR1172 카메라 영상 수신
      → IR worker → MQTT → 해당 사육장의 ESP32 → IR 조명
```

브라우저는 SaaS와 같은 출처의 주소만 호출합니다. Pi의 `/camera` 화면은 CSP `frame-ancestors 'none'`이고 세션 쿠키는 `SameSite=Strict`이므로 외부 SaaS의 iframe으로 넣거나 브라우저에서 Pi로 직접 교차 출처 요청하는 방식으로 구현하지 않습니다. 이를 위해 Pi의 CORS, CSRF 또는 쿠키 보호를 해제하지 않습니다.

SaaS 백엔드는 **목록, 재생목록, 각 영상 조각, IR 조회, IR 명령마다** 로그인 사용자와 조직 → 매장 → Gateway → 사육장 소속을 검사합니다. 영상 조회 권한과 조명 제어 권한을 분리합니다. 카메라 ID가 실제로 선택한 사육장 소속인지도 검사해야 합니다. Pi 키는 SaaS 사용자의 조직·역할을 구분하지 않으므로 Pi 인증만으로 이 검사를 대신할 수 없습니다.

### 키와 세션 보관

- Pi의 영상 조회 키는 영상과 IR 상태 조회용입니다. 별도 제어 키는 조회와 IR 명령을 허용합니다.
- 키와 Pi 세션 쿠키는 SaaS 서버의 비밀 저장소와 서버 메모리에서 관리합니다. 브라우저 HTML, JavaScript, localStorage, URL, 공개 저장소와 로그에 넣지 않습니다.
- 실제 키는 이 전달본에 포함하지 않습니다. 소유자가 Pi의 비공개 제어 실행 파일 `/home/<gateway-user>/.config/habitatos/ir/camera-control.html`을 관리하며, SaaS 운영 담당자에게 제어 키를 별도 보안 채널로 전달해야 합니다. 파일 전체를 공개 첨부하지 않습니다.
- SaaS의 센서 수신 토큰, 일반 Gateway API 토큰, 내부 IR bridge 토큰, MQTT 계정은 이 API 연결에 사용하지 않습니다.
- Pi별 주소와 키를 분리합니다. 사용자가 보낸 임의 URL이나 Host 값으로 요청 대상을 선택하지 않습니다. 운영 설정에 등록한 HTTPS 주소만 허용하고 다른 출처로의 리다이렉트를 따르지 않습니다.

설정 형태의 예시입니다. `*_secret_ref`는 실제 키가 아닌 SaaS 비밀 저장소의 참조이며, 아래 구조는 SaaS 측 설정 제안입니다.

```json
{
  "site_id": "STORE-001",
  "gateway_id": "PI-001",
  "camera_ir_base_url": "https://gateway.example.ts.net",
  "viewer_key_secret_ref": "stores/STORE-001/PI-001/camera-viewer",
  "control_key_secret_ref": "stores/STORE-001/PI-001/camera-control",
  "allowed_cage_ids": ["CAGE-001"]
}
```

현재 기본 주소에 SaaS 서버가 HTTPS로 도달하는지 먼저 확인합니다. 주소나 공개 접속 방식이 바뀌면 매장 설정을 변경하며 카메라 보드의 사설 IP를 SaaS 서버에 직접 등록하지 않습니다. Pi가 이미 각 DFR1172의 스트림을 수신하므로 SaaS나 별도 프로그램이 같은 카메라 보드에 두 번째 수신 연결을 만들지 않습니다.

## 3. 현재 Pi API

모든 경로는 Pi 기본 주소 기준입니다. 인증이 필요한 조회는 로그인으로 받은 영상 세션 쿠키를 사용하며, IR 명령에는 제어 세션과 CSRF 토큰도 필요합니다.

| 메서드·경로 | 응답 / 역할 |
| --- | --- |
| `POST /camera/session` | Bearer 키를 12시간 세션 쿠키로 교환, `200 {"expires_in":43200}` |
| `DELETE /camera/session` | 세션 쿠키 삭제, 204. 진행 중인 IR 요청을 끄는 명령은 아님 |
| `GET /camera/control/session` | `can_control`, `csrf_token` 반환 |
| `GET /camera/api/cameras` | 매장·Gateway ID, 사육장 목록, 카메라별 상태와 영상 최신성 |
| `GET /camera/hls/{camera_id}/index.m3u8` | 최신 HLS 재생목록, `application/vnd.apple.mpegurl` |
| `GET /camera/hls/{camera_id}/{session_id}/{sequence}.ts` | HLS 영상 조각, `video/mp2t` |
| `GET /camera/api/ir/{cage_id}` | 해당 사육장의 현재 IR 연결·요청·GPIO 상태 |
| `POST /camera/api/ir/{cage_id}` | ON/OFF 요청 수락 시 202와 현재 상태 |

### 서버 간 로그인 순서

1. SaaS 서버가 등록된 Pi에 아래 요청을 보냅니다. 서버 내부 쿠키 저장소에 `Set-Cookie`를 저장하고 브라우저에는 전달하지 않습니다.

   ```http
   POST /camera/session
   Authorization: Bearer <서버 비밀 저장소에서 읽은 Pi 키>
   ```

2. 받은 쿠키로 `GET /camera/control/session`을 호출합니다. 제어 키로 로그인하면 `can_control: true`와 `csrf_token`이 반환됩니다. 조회 키는 `can_control: false`, `csrf_token: null`입니다.
3. 조회 요청에는 서버가 보관한 Pi 쿠키를 사용합니다. 명령에는 `Content-Type: application/json`과 `X-Habitat-CSRF: <위 토큰>`을 추가합니다.
4. SaaS 사용자의 브라우저 `Cookie`, `Authorization`, `Origin`을 Pi로 그대로 전달하지 않습니다. Pi용 인증 정보를 서버가 구성하며, 브라우저의 `Origin: https://easyrep.kro.kr`을 전달하면 Pi의 출처 검사에서 거절됩니다. SaaS 자체 명령 경로에도 기존 CSRF 보호를 적용합니다.
5. Pi 쿠키가 만료되면 서버에서 재로그인합니다. 상태 조회는 재시도할 수 있지만, 응답이 불확실한 ON 명령을 재로그인 후 자동 재전송하지 않습니다.

제어 키로 로그인하면 영상 조회 쿠키와 제어 쿠키가 함께 발급됩니다. 조회용 키로 다시 로그인하면 해당 쿠키 저장소의 제어 쿠키는 삭제됩니다. 서버 내부에서 조회·제어 자격 증명을 구분하고 의도치 않게 공유 세션을 덮어쓰지 않습니다.

### 영상 조회와 최신성

목록의 `site_id`, `gateway_id`가 설정과 맞는지 확인한 뒤 사용자가 볼 수 있는 사육장과 카메라만 반환합니다. `status`, `fresh`, `age_s`, `last_segment_at`을 화면 상태에 사용합니다. `configured_fps`는 설정값이며 측정된 수신 FPS가 아닙니다.

현재 두 영상의 경로는 다음과 같습니다.

```text
/camera/hls/RGB-001/index.m3u8
/camera/hls/CAGE-001-FRONT/index.m3u8
```

재생목록의 미디어 주소는 `<session_id>/<sequence>.ts`처럼 상대 경로입니다. SaaS 프록시도 `index.m3u8`과 영상 조각을 같은 카메라 경로 아래에 제공하면 상대 경로를 유지할 수 있습니다. 재작성한다면 허용된 Pi 카메라 경로만 SaaS 주소로 바꾸며 임의 외부 주소를 프록시하지 않습니다.

Pi는 최신 영상이 없으면 `503 {"detail":"waiting_fresh_video"}`를 반환합니다. 화면은 연결 끊김 또는 최신 영상 대기로 표시하고 플레이어를 중지·비워 과거 마지막 화면이 현재 실시간 영상처럼 남지 않게 합니다. 만료된 조각은 404가 될 수 있으므로 최신 재생목록을 다시 조회합니다. 재생목록과 조각의 `Cache-Control: no-store`를 유지합니다. 이번 연결은 실시간 조회이며 영구 녹화 저장을 자동으로 추가하지 않습니다.

0.4.28에서 현재 재생목록과 영상의 최신성 기준은 계속 15초입니다.
이미 재생목록에 안내한 조각이 목록에서 빠진 뒤 늦게 요청되는 경우에는,
원래 `PROGRAM-DATE-TIME` 기준 나이가 최대 40초인 조각까지 다시 조회할 수
있습니다. 안내 후 40초가 추가되는 것은 아닙니다. 카메라당 최대 48개 조각의
메타데이터만 기억하며, 실제 파일이 남아 있고 원래 해시와 일치해야 합니다.
인증·같은 수신 세션·현재 수신기 정상·최신 재생목록 조건도 계속 필요합니다.
중단되거나 교체된 수신기의 과거 영상을 현재 영상으로 제공하지 않습니다.

40초는 요청 허용 나이의 상한이며, 파일의 40초 보관을 보장하지 않습니다.
FFmpeg의 `hls_delete_threshold=40`은 초 단위 설정이 아니고, FFmpeg는
재생목록 길이에 따른 삭제 조건도 함께 적용하므로 파일이 더 일찍 삭제될 수
있습니다. 삭제된 조각의 404 응답에는 최신 재생목록을 다시 조회해야 합니다.
이 여유 시간은 지연된 조각 요청을 위한 것이며, 영구 녹화 기능이 아닙니다.

0.4.29부터 완료된 영상 조각 하나가 길이(0초 초과·4초 이하), 크기(2MiB
이하), MPEG-TS 프레이밍 조건을 위반해도 다른 정상 조각까지 차단하지
않습니다. 해당 조각을 제외하고 최신의 연속된 정상 구간만 재생목록으로
제공합니다. 제외된 조각 요청은 404가 될 수 있으므로 최신 목록으로 복귀해야
합니다. 정상 조각이 없으면 계속 503을 반환하며, 인증·수신기 상태·장치 확인·
세션 일치·15초 최신성 검사는 유지합니다. 잘못된 경로·시각·세션 메타데이터는
목록 전체를 거부합니다. 기존 영상 업로드 계약의 길이·크기 제한은 바뀌지 않습니다.

### 전원 재연결과 카메라 주소 변경

카메라를 껐다 켜도 Pi의 영상·IR 키, 카메라 ID와 위 HLS 경로는 바뀌지 않습니다.
세션이 만료되면 같은 키로 다시 로그인합니다. **전달 JSON은 연결정보이며 실행 프로그램이
아닙니다.** SaaS는 기존 백엔드에 로그인·영상 프록시·상태 조회와 화면 복구 처리를 연결해야 합니다.

Pi 0.4.25의 선택 설정 `camera_discovery`를 켜면, 설정된 매장 LAN에서 등록된
카메라의 `/identity`를 대조해 바뀐 IP를 찾습니다. 매장·Gateway·사육장·카메라 ID와
TOP/FRONT 역할이 모두 일치하는 경우에만 다시 연결합니다. 동일 ID가 여러 주소에서
응답하면 자동 선택하지 않습니다. 검색 범위와 활성화 방법은
[새 매장 설치 안내](../operations/new-store-setup.md)를 따릅니다. 이 기능은 내부
카메라 주소만 갱신하므로 SaaS의 키나 매핑을 다시 발급·변경할 필요가 없습니다.

복구 중에는 기존 API의 `fresh=false`와 영상 대기/실패 상태를 표시하고, 새 미디어가
확인되면 같은 HLS 경로에서 재생을 시작합니다. 카메라 Wi-Fi 연결, Pi 검색·재시도와
HLS 생성 시간이 있으므로 고정된 즉시 복구 시간을 가정하지 않습니다.

카메라 전원과 IR을 제어하는 BB6 전원은 별개입니다. 카메라만 꺼졌다 켜지는 동안
BB6·MQTT가 유지되면 IR 제어 연결도 유지됩니다. BB6 자체가 재시작하면 IR은 OFF로
시작하며, 새 상태를 받은 뒤 같은 키로 새 ON 명령을 보낼 수 있습니다. 이전 ON 명령을
자동으로 재생하지 않습니다. IR 동작 중 통신 단절의 오류 표시가 남으면 OFF 요청으로
상태를 정리하고 새로운 사용자 ON 요청을 받습니다.

### IR 계속 켜기·타이머·끄기

아래 요청은 설명용입니다. 개발 초기 연결 점검에서는 상태 조회까지만 수행하며 실제 명령은 현장 점등 시험 시 명시적으로 실행합니다.

```http
POST /camera/api/ir/CAGE-001
Content-Type: application/json
X-Habitat-CSRF: <서버가 받은 토큰>

{"action":"on"}
```

| 사용자 동작 | JSON 본문 | 표시 |
| --- | --- | --- |
| 계속 켜기 | `{"action":"on"}` 또는 `{"action":"on","seconds":null}` | `mode: "continuous"`, `remaining_s: null`이면 계속 켜기 요청 진행 중 |
| 타이머 켜기 | `{"action":"on","seconds":300}` | `mode: "timed"`, `remaining_s`에 남은 초 |
| 끄기 | `{"action":"off"}` | OFF 요청 후 상태를 다시 조회 |

타이머는 정수 1~900초이며 상태 응답의 `max_on_seconds`가 더 작으면 그 값을 상한으로 사용합니다. 0초, 문자열, 소수는 허용하지 않습니다. **0.4.24에서는 `seconds` 생략이 계속 켜기입니다.** 이전 0.4.23의 기본 300초 동작을 원하면 반드시 `seconds: 300`을 보냅니다.

`GET /camera/api/ir/CAGE-001`의 주요 필드는 다음과 같습니다.

| 필드 | 의미 |
| --- | --- |
| `configured` | 이 사육장의 IR 연동 설정 여부 |
| `online`, `outputs_locked` | 노드 응답과 출력 잠금 상태 |
| `status` | `offline`, `locked`, `off`, `starting`, `on`, `stopping`, `error`; 미설정 사육장은 `unconfigured` |
| `active`, `mode`, `remaining_s` | Pi 제어 요청 진행 여부, 계속/타이머 모드, 남은 시간 |
| `gpio_requested_on` | ESP32가 보고한 GPIO 출력 요청 상태 |
| `actual_ir_on` | 현재 항상 `null`. 실제 빛을 감지한 값이 없음 |
| `error` | 통신·응답·제어 오류 코드 또는 `null` |

HTTP 202는 요청 수락입니다. 화면은 이후 상태를 주기적으로 조회하고 요청 진행·노드 상태를 구분해 표시해야 합니다. `status: on`, MQTT ACK, `gpio_requested_on: true`만으로 실제 IR 조명이 빛을 냈다고 확정하지 않습니다. 실물이나 영상으로 점등을 확인해야 합니다.

계속 켜기는 Pi worker가 짧은 유효 기간의 명령을 갱신하는 방식입니다. **브라우저 종료·SaaS 로그아웃으로 이미 수락된 요청은 취소되지 않으며 끄기 버튼으로 종료합니다.** worker 재시작, MQTT·노드 연결 끊김, 노드 세션 변경으로 갱신이 중단되면 현재 명령의 유효 기간 이후 출력이 꺼지고, 재연결만으로 자동으로 켜지지 않습니다. 페이지 열기·로그인·새로고침·상태 복구는 조회만 수행하며 ON을 보내지 않습니다.

## 4. SaaS에 구현할 경로와 화면

다음은 **SaaS 측 구현 제안이며 현재 배포된 경로가 아닙니다.** 기존 `/manage/`의 라우터·권한 구조에 맞춰 이름을 조정할 수 있습니다. 새 별도 웹사이트를 만들지 않고 기존 매장·사육장 상세 화면에 추가합니다.

공통 경로를 다음처럼 두면 영상의 상대 경로를 그대로 유지할 수 있습니다.

```text
/manage/api/sites/{site_id}/gateways/{gateway_id}/cages/{cage_id}
```

| 공통 경로 뒤에 붙일 경로 | 메서드 | SaaS 백엔드 처리 |
| --- | --- | --- |
| `/cameras` | GET | Pi 카메라 목록에서 권한이 있는 해당 사육장만 반환 |
| `/hls/{camera_id}/index.m3u8` | GET | 카메라 소속 검사 후 Pi HLS 재생목록 반환 |
| `/hls/{camera_id}/{session_id}/{sequence}.ts` | GET | 같은 소속·조회 권한 검사 후 Pi 영상 조각 반환 |
| `/ir` | GET | 해당 사육장의 Pi IR 상태 반환 |
| `/ir` | POST | SaaS 제어 권한·CSRF·본문 검증 후 Pi IR 명령 전송 |

브라우저 응답에는 Pi의 `Set-Cookie`, 제어 키, CSRF 토큰, 내부 카메라 주소를 노출하지 않습니다. Pi의 재생목록·미디어 본문과 필요한 Content-Type·캐시 정책만 전달합니다. API 오류는 코드로 전달하되 인증 헤더·비밀·내부 디버그 정보는 제거합니다.

화면에는 TOP/FRONT 두 영상, 각 영상의 최신성, IR 상태와 **계속 켜기 / 끄기 / 선택 타이머**를 제공합니다. 조회 전용 사용자는 제어 버튼을 사용할 수 없어야 합니다. 미설정·오프라인·출력 잠금 상태를 OFF와 구분하고 해당 상태에 맞춰 명령을 제한합니다. OFF는 진행 중인 요청을 끝내는 명시적 동작이며 가능한 경우 계속 제공해야 합니다.

다중 사용자 환경에서는 SaaS 서버가 사용자·사육장·동작·요청 시각·응답 상태를 감사 기록에 남깁니다. 동일 사육장의 중복 ON을 직렬화하거나 진행 중으로 처리하고, `control_busy`를 새 ON 반복 전송으로 해결하지 않습니다. 다른 사육장의 제어와는 분리합니다.

## 5. 오류와 재시도

| 상황 | 처리 |
| --- | --- |
| 401 `camera_login_required` | 서버 Pi 세션 갱신 후 조회 재개. 사용자 브라우저에 Pi 키 입력을 요구하지 않음 |
| 401 `invalid_camera_key` | 해당 매장 비밀 설정 확인. 무한 재로그인 금지 |
| 403 `camera_control_required` / `invalid_csrf` | 제어 자격 증명·서버 쿠키·CSRF 구성 확인. 권한 우회 금지 |
| 404 `camera_not_found` / `cage_not_found` | 등록·매핑 확인. 다른 사육장 ID로 자동 대체하지 않음 |
| 404 `segment_expired` | 최신 HLS 재생목록 조회 |
| 409 `ir_not_configured` | IR 미설정으로 표시. CAGE-002·003을 동작 가능으로 표시하지 않음 |
| 409 `control_busy` / `outputs_locked` | 현재 요청·잠금 상태 조회 후 표시 |
| 422 | 본문·타이머 값 수정. 그대로 재시도하지 않음 |
| 503 `waiting_fresh_video` | 영상 대기/연결 끊김 표시, 과거 프레임 제거, 간격을 두고 조회 |
| IR 503 또는 통신 시간 초과 | 연결·노드 상태 조회. ON의 성공 여부가 불확실하면 자동 재전송하지 않음 |

프록시 요청에는 유한한 연결·응답 시간 제한을 둡니다. 서버가 Pi 상태를 읽지 못하면 마지막 관측값의 시각과 현재 연결 실패를 표시하며 마지막 값만으로 현재 ON/OFF를 단정하지 않습니다.

## 6. 연결 점검과 완료 기준

먼저 SaaS 서버 실행 환경에서 로그인, 목록, 두 HLS 재생목록과 각 최신 영상 조각, IR 상태를 읽습니다. 이 과정에는 ON 명령, 펌웨어 기록, MQTT 계정 변경, 서비스 재시작이 필요하지 않습니다. 실제 API 접근을 실행하기 전에는 Postman의 명령 요청을 자동 실행 목록에서 제외합니다.

Postman 컬렉션의 `01` 폴더는 읽기 점검용입니다. 실제 제어 요청은 해당 요청의 **Send**로 개별 실행하며, 컬렉션 변수 `ir_confirmation`에 `IR ON CAGE-001` 또는 `IR OFF CAGE-001`을 넣어야 합니다. 다른 사육장을 설정했다면 끝의 ID도 일치시킵니다. 이 값은 요청 전 한 번 사용 후 지워지고, 없거나 다르면 요청을 건너뜁니다. `pm.execution.skipRequest()`를 지원하는 Postman에서 사용하세요. 내보낸 파일에는 키·CSRF 토큰·확인 값이 비어 있습니다.

### Python 클라이언트 사용

제공 클라이언트는 Python 3.11 이상과 `httpx`를 사용합니다. 아래는 서버 실행 환경에 비밀을 주입한 뒤 수행할 읽기 전용 예제입니다. 환경 변수의 값은 저장소 파일에 기록하지 않습니다. 이 예제의 ID는 현재 설치 대상이며 운영 구현에서는 매장 설정에서 읽습니다.

```python
import os
from habitat.saas.camera_ir import CameraIRClient, CameraIRError

try:
    with CameraIRClient(
        base_url=os.environ["HABITAT_PI_ORIGIN"],
        key=os.environ["HABITAT_PI_CAMERA_KEY"],
        site_id="STORE-001",
        gateway_id="PI-001",
        cage_ids=["CAGE-001"],
        camera_ids={"RGB-001": "CAGE-001", "CAGE-001-FRONT": "CAGE-001"},
    ) as gateway:
        inventory = gateway.inventory()
        ir_state = gateway.ir_status("CAGE-001")
        top_playlist = gateway.playlist("RGB-001")
        front_playlist = gateway.playlist("CAGE-001-FRONT")
        # 권한을 확인한 SaaS 응답에 필요한 데이터만 반환합니다.
except CameraIRError as error:
    # code, status_code, outcome_unknown만 진단에 사용합니다.
    # 특히 outcome_unknown인 명령은 자동으로 다시 보내지 않습니다.
    raise
```

`with` 진입 시 로그인과 매장·Gateway·카메라 매핑 검증을 수행합니다. `segment(camera_id, session_id, sequence)`는 재생목록이 가리키는 영상 조각의 바이트를 반환합니다. 같은 매장의 서버 프로세스 내에서 세션을 재사용할 수 있으며 사용자 권한은 요청마다 SaaS가 별도로 확인합니다. 클라이언트 종료는 HTTP 자원만 정리하고 IR OFF나 로그아웃을 보내지 않습니다.

실제 제어 버튼을 처리할 때 사용할 메서드는 다음과 같습니다. 아래 호출은 읽기 점검 코드에 넣지 않습니다.

```python
gateway.command_ir("CAGE-001", "on")               # 계속 켜기
gateway.command_ir("CAGE-001", "on", seconds=300)  # 선택 타이머
gateway.command_ir("CAGE-001", "off")              # 명시적 끄기
```

### 완료 기준

완료 기준은 다음과 같습니다.

- 기존 SaaS 로그인으로 해당 매장·CAGE-001에 들어가 두 영상이 계속 갱신된다. 다른 조직·매장·사육장 ID를 경로에 넣으면 목록뿐 아니라 HLS 조각과 IR 조회·명령도 거절된다.
- 조회 사용자에게 제어가 거절되고 제어 권한 사용자만 명시적 ON/OFF를 실행한다. 키와 Pi 세션이 브라우저·로그에 나타나지 않는다.
- 계속 켜기, 명시적 끄기, 선택 타이머를 현장에서 검증하고 실제 조명과 상태 표시를 대조한다. 실제 점등 미확인 값은 `actual_ir_on: null`로 유지한다.
- 새로고침·로그인·페이지 재진입·통신 복구에서 ON이 재전송되지 않는다. 명령 응답 시간 초과도 ON 자동 재시도를 유발하지 않는다.
- 계속 켜기 중 브라우저를 닫아도 요청이 유지되며, 재접속 화면은 현재 상태만 읽는다. worker·노드 재시작 후에는 자동 ON이 발생하지 않는다.
- 한 카메라 연결이 끊기면 해당 영상이 대기/오프라인으로 바뀌고 오래된 정지 영상을 실시간으로 보여주지 않는다. 다른 영상과 기존 센서 수신은 계속 동작한다.
- CAGE-002·003의 미설정 상태와 향후 매장 추가가 코드 복사 없이 구성·매핑으로 처리된다.

### SaaS 개발 작업 지시

기존 SaaS 저장소에서 로그인·조직/매장/사육장 권한·상세 화면 구조를 먼저 확인한 뒤 위 Pi API를 재사용합니다. 매장별 Pi 설정과 서버 비밀을 등록하고, 인증된 동일 출처 HLS 프록시 및 IR 조회/명령 경로를 구현합니다. 기존 사육장 상세 화면에 TOP/FRONT와 계속 켜기·끄기·선택 타이머를 연결합니다. 권한·CSRF·카메라 소속·상대 HLS 경로·503 최신성·명령 재시도 방지를 통합 시험하고, 실제 CAGE-001 영상 및 IR을 현장에서 확인한 뒤 배포 결과를 남깁니다.

기존 Pi → SaaS `POST /v1/edge/sync` 센서 계약은 유지합니다. 별도로 문서화된 `POST /v1/edge/video` 영상 업로드 계약은 이번 SaaS → Pi 조회 방식과 다릅니다. **이번 연결을 위해 `video_upload.enabled`를 활성화하거나 두 경로를 동시에 구성하지 않습니다.** 내부 `127.0.0.1:8093` IR worker와 MQTT를 외부에 공개할 필요도 없습니다.

## 7. 검증 범위

### 0.4.26 카메라 H.264 직접 송출 호환성

새 `source_type="rtsp_h264"`는 카메라에서 만든 H.264를 Pi가
`-c:v copy`로 HLS에 포장한다. Pi는 이 경로에 H.264 재인코딩, FPS
변환, 확대 또는 밝기 필터를 적용하지 않는다. 진단용 JPEG 미리보기는
같은 입력에서 별도로 디코딩하며 카메라 연결은 하나만 사용한다.
기존 `http_mjpeg`/`uvc`의 동작은 유지되어 두 방식이 함께 동작할 수 있다.

네이티브 장치의 identity는 `color_range="limited"`,
`color_matrix="bt601"`도 명시한다. 카메라 ISP에서 이 형식으로 만든
YUV를 인코딩하고, Pi는 H.264 SPS의 색상 메타데이터를 일치시킨다.
이 비트스트림 필터는 압축된 화상 데이터(VCL)를 다시 인코딩하지 않는다.
밝기 범위가 다른 장치를 같은 설정으로 잘못 표시하지 않도록 장치 검색에서
두 값을 대조한다.

0.4.27의 네이티브 입력은 FFmpeg가 형식 분석 중 모아 둔 시작 프레임을
버리고 다음 키프레임부터 중계한다. 이로써 초기 버퍼에 쌓인 영상에 현재
시각을 붙여 HLS 시각이 앞으로 밀리는 현상을 방지한다. 실제 RTP 시각과
그 이후의 압축 프레임은 유지하며, FPS 변환이나 재인코딩을 하지 않는다.

카메라 ID, HLS 경로·상대 조각 주소, 영상/IR 키, SaaS 로그인과
IR 명령 계약은 그대로다. 목록의 `source_type` enum에 `rtsp_h264`가
추가되므로 이를 엄격하게 검사하는 SaaS 클라이언트는 먼저 갱신한다.
해상도와 FPS는 새 입력을 확인한 설정값으로 읽고 화면 비율을 보존한다.
해상도·FPS 메타데이터는 실측 전송 속도나 보정 완료를 뜻하지 않는다.

새 입력은 ID 확인과 함께 첫 완성 HLS 조각의 H.264 Baseline 계열,
해상도, 키프레임과 독립 디코딩을 확인한 뒤 노출한다. 기존의 최신성,
최대 4초·2MiB 조각 제한은 유지한다. 아직 검증되지 않은 조각이나
끊어진 수신기의 캐시를 현재 영상으로 제공하지 않는다.

이 변경은 Pi의 재압축 손실을 없애는 작업이다. 센서 노출, 렌즈 초점,
CSI 입력의 깨짐을 복구하거나 HLS 플레이어의 수초 버퍼를 없애는
기능은 아니다. 카메라별 실제 촬영·SaaS 표시와 CPU/네트워크 상태를
확인한 뒤 전환 완료로 판정한다.

기본 API 계약은 Pi 0.4.24에서 도입됐으며 위 네이티브 H.264 경로는
0.4.26에 추가된다. API·클라이언트 시험은 실제 카메라 영상·IR 광원과
SaaS 배포 검증을 대신하지 않는다. 운영 확인 시각과 결과를 전달 시 함께
기록하고, SaaS 화면도 위 완료 기준으로 확인한다.

### 2026-11-25 — SaaS 연결 후 지연·영상 깨짐 점검

사용자가 SaaS 영상의 약 10초 지연, 자글거림과 밝기 깜빡임을 보고했다.
19시대 Pi 0.4.25에서 기존 수신기의 HLS만 조회했다. 카메라에 추가
스트림을 연결하거나 서비스·펌웨어·IR 출력을 변경하지 않았다.

- 두 카메라 모두 `live`/`fresh=true`, H.264 800×640, 출력 설정 10fps,
  2초 세그먼트 6개였다. 각 최신 조각의 FFmpeg 디코딩 오류는 0개였다.
  출력 10fps는 센서의 실제 촬영 속도를 입증하지 않는다.
- Pi 내부 API는 조각당 약 0.018~0.019초, Pi에서 공개 주소를 조회한
  경로는 약 0.021초였다. 이는 **SaaS 서버에서 측정한 시간도,
  촬영부터 브라우저 표시까지의 지연도 아니다.**
- 기존 영상 10초분을 디코딩해 TOP·FRONT 모두 가로 색 띠, 부분적인
  흑백 영역과 급격한 밝기 변화를 직접 확인했다. 즉 이 영상 깨짐은
  SaaS 이전의 Pi HLS에도 있다. 디코딩 성공은 영상 내용의 정상성을
  보장하지 않는다. 원본 MJPEG와 Pi 변환 결과를 비교하기 전에는
  센서·CSI 연결·전원·카메라 펌웨어·Pi 디코더 중 원인을 확정하지 않는다.
- 점검 당시 IR은 온라인/OFF였고, 상태 조회만 했다.

EasyRep 저장소의 고정 커밋
[`f44b63246046a270b9059e29cf5d891a7a8e0680`](https://github.com/BbangYi/EasyRep/tree/f44b63246046a270b9059e29cf5d891a7a8e0680)
도 읽었다. 이 커밋이 실제 운영 배포와 일치하는지는 미확인이다.

1. `web/standalone/enclosure-viewer.tsx:124`는
   `new Hls({ liveSyncDurationCount: 2 })`만 사용한다. 현재 2초 HLS에서
   목표 재생 위치는 최신 끝보다 약 4초 뒤다. Pi 화면과 같은 지연
   누적 제한·따라잡기 설정을 적용하고 브라우저에서 재측정한다.

   ```ts
   new Hls({
     liveSyncDurationCount: 2,
     liveMaxLatencyDurationCount: 4,
     maxLiveSyncPlaybackRate: 1.15,
     backBufferLength: 0,
     maxBufferLength: 12,
   });
   ```

   위 설정은 전체 지연의 상한 보장이 아니다. 네이티브 HLS 분기는
   이 설정을 사용하지 않으므로 별도 확인한다. 변경 후 Vite 빌드와
   실제 운영 `FRONTEND_DIR`의 배포까지 확인해야 한다.
2. `web/server/habitat/camera_ir.py:203`의 `_media_context`는 재생목록과
   각 영상 조각마다 Pi 목록을 먼저 조회하고, 이어서 미디어를 조회한다.
   Pi 연결 재사용과 짧고 제한된 장치 신원 검증 캐시를 검토한다.
   사용자·매장·사육장 권한 검사는 요청마다 유지하며, 신원 검증을
   단순 삭제하지 않는다. 실제 SaaS는 별도 `PiClient`를 사용하므로
   이 저장소 `CameraIRClient`의 공용 잠금을 원인으로 지목하지 않는다.
3. SaaS 미들웨어에는 이미 캐시 차단이 있고 영상 재인코딩도 없다.
   현재 단계에서 캐시 누락이나 SaaS 재압축을 원인으로 단정하지 않는다.
   IR 화면의 8초 상태 조회 간격은 실제 출력과 화면 표시의 차이를
   만들 수 있으므로 영상 지연과 별도로 측정한다.

정확한 전체 지연은 같은 시계를 촬영해 Pi 화면과 SaaS 화면을 비교해
측정한다. `age_s`는 Pi가 만든 최신 조각 시각 기준이며 이를 대체하지
않는다. 위 개선안은 아직 SaaS에 적용하지 않았으며, 영상 깨짐도
해결 완료로 판정하지 않았다.
