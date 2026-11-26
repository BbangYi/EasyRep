# SaaS 서버에서 실행할 작업 지시서

## 2026-11-09 현재 요청: CAGE-001 무선 RGB 카메라 두 대

Pi Gateway와 Air Viewer에 `0.4.20-47b0ca40e3f7` 배포를 완료했다.
DFR1172 두 대의 공식 ESP32-P4 펌웨어·공통 프로그램·Wi-Fi 설정을 기록하고,
각각 5V USB 어댑터만 연결한 상태의 자동 실행을 확인했다. 실제 800×640 영상
두 개를 Pi 상시 서비스에서 동시에 수신한다. 인증된 카메라 목록에서 두 대 모두
`live/fresh`, HLS 실제 디코딩과 최신 세그먼트 갱신을 확인했다. 프레임 속도에는
차이가 있으므로 일정한 고속 FPS나 장기 안정성 검증 완료로 해석하지 않는다.

운영 매핑은 `STORE-001 / PI-001 / CAGE-001`이며 다음 ID를 사용한다.

| camera_id | 예정 역할 | 현재 상태 |
| --- | --- | --- |
| `RGB-001` | TOP | 실제 무선 영상 수신 중 |
| `CAGE-001-FRONT` | FRONT | 실제 무선 영상 수신 중 |

사용자가 실제 TOP/FRONT 장착 위치는 아직 정하지 않았다고 확인했다. 위 역할은
설치 예정이며 물리 위치 검증을 뜻하지 않는다. 기존 ID `RGB-001`을
`CAGE-001-TOP`으로 임의 교체하지 않는다. CAGE-002·003의 카메라 설정은
준비됐지만 실제 카메라 URL은 아직 없으므로 live로 표시하지 않는다.

현재 Pi의 SaaS 센서 수신 주소는 `https://easyrep.kro.kr/v1/edge/sync`이며
최근 이벤트 ACK 성공을 확인했다. 이를 문서의 목표 도메인 `habitatos.kro.kr`로
임의 변경하지 않았다. 같은 호스트의 `/v1/edge/video`는 GET에서 JSON 404,
기존 Pi Bearer 토큰을 사용한 빈 JSON POST에서 HTML 403을 반환했다.
실제 영상은 SaaS로 전송하지 않았으며 `video_upload.enabled=false`를 유지한다.
이 결과만으로 프록시 차단, 인증·권한, 라우팅, 미구현 중 원인을 특정하지 않는다.
운영 SaaS 소스와 배포 접근은 이 Pi 및 연결된 GitHub에서 찾지 못했다.

팀원에게 전달할 작업:

```text
Pi의 CAGE-001 무선 RGB 카메라 두 대 설치와 실제 동시 수신은 완료됐습니다.
운영 SaaS 소스 저장소·배포 환경을 확인하고 다음을 연결해주세요.

1. 현재 운영 호스트와 POST /v1/edge/video의 실제 라우팅·프록시·인증을 확인합니다.
   기존 Pi Bearer 토큰으로 빈 JSON POST가 HTML403을 반환합니다.
   전역 보안 검사를 끄지 말고, Pi 전용 인증/권한을 검사하는 JSON API로 연결합니다.
2. STORE-001 / PI-001 / CAGE-001의 카메라 권한에
   RGB-001(TOP 예정), CAGE-001-FRONT(FRONT 예정)를 각각 등록합니다.
   센서 sync만으로 카메라가 자동 등록되지는 않습니다.
   VideoSegment v1에는 view가 없으므로 TOP/FRONT 표시는 서버 inventory에 둡니다.
3. docs/saas-integration.md의 실시간 영상 v1과
   docs/api/edge-sync.openapi.json을 따릅니다.
   habitat/saas/video_contract.py, video_receiver.py,
   tests/contract/test_video.py를 참고하되 기존 서버 언어·DB·로그인을 유지합니다.
   센서 sync/MQTT 계약과 event_sequence는 변경하지 않습니다.
4. 기존 사육장 페이지에 두 개의 독립 플레이어를 연결합니다.
   playlist와 모든 TS 조회에 기존 웹 로그인·매장/사육장 권한을 적용하고,
   Pi 토큰은 브라우저에 전달하지 않습니다. 한쪽 단절·오래된 프레임을 구분합니다.
5. 구현 후 실제 영상 POST 주소, 등록된 두 camera_id, 배포 revision,
   인증된 웹 재생 경로를 알려주세요. 토큰 원문은 문서·메신저에 넣지 않습니다.
   이후 Pi 업로드를 활성화하고 실제 세그먼트의 저장 ACK와 웹 재생을 대조합니다.
```

Pi의 독립 HTTPS 카메라 화면은 동작하지만, 이것을 운영 SaaS 카메라 탭 통합
완료로 해석하지 않는다. 신규 매장·사육장 등록에도 카메라 두 개와 예정 view의
권한·inventory 등록 절차가 필요하다. 모든 매장 Pi에는 같은 release를 적용하고,
SaaS에서도 매장별 차이는 등록 설정으로 관리한다.

<a id="air-saas-work"></a>
## 2026-11-04 추가 대상: CAGE-002

사용자는 CAGE-002 조립 완료와 카메라 미설치를 확인했다. Pi 공기 추정은
T1·T2·T3를 사용하며 카메라 설치 여부로 화면을 숨기면 안 된다. 사용자가
확인한 크기·센서 위치는 기존 CAGE-001 설정과 같다: 20×20×30cm,
T1=(10,10,28), T2=(2,2,8), T3=(18,18,8)cm.

아래 서버 작업의 최초 CAGE-001 대상에 `STORE-001 / PI-001 / CAGE-002 /
ESP32-002`를 추가한다. CAGE-002의 실제 enclosure UUID와 revision은 운영
등록에서 조회해야 하며 CAGE-001 UUID를 재사용하지 않는다. 두 사육장의
측정값·추정 격자가 섞이지 않는지 검증한다. Pi에서는 CAGE-002 viewer 설정을
준비했지만 관리자 권한이 없어 아직 적용하지 못했고 SaaS 전송도 비활성이다.
배포 및 실제 데이터 검증 완료로 해석하지 않는다.

같은 날 19:05 KST 후속 확인에서는 사용자 적용 후 Pi viewer의 CAGE-002
등록과 실제 T1·T2·T3 수신, live 추정 격자 생성을 확인했다. 위의 Pi 적용
대기는 해소됐으며, SaaS 전송 활성화·저장 ACK·웹 연동은 여전히 별도 작업이다.

같은 날 21:39 KST에는 사용자 요청으로 **Pi SaaS 전송을 활성화**하고
서비스 재시작 및 `cloud_enabled=True`를 확인했다. CAGE-001·002 모두
실제 POST를 시작했으나 서버 ACK를 받지 못했다. 21:40 재확인에서
요청 크기는 각각 37,415바이트와 33,814바이트로 계약의 96 KiB 이내였지만
둘 다 HTML HTTP 413을 반환했다. 서비스 로그에 403도 한 차례 있어,
서버팀은 다음 두 항목을 먼저 확인해야 한다.

- `/v1/edge/air`로 향하는 모든 프록시·웹 서버·앱 계층에서 계약의 최대
  JSON 본문 98,304바이트를 허용하는지 확인한다. 압축 해제된 온도 격자의
  48,000바이트 제한은 JSON 전체 본문 제한과 다르므로 각각 유지한다.
- 기존 Pi 토큰의 두 사육장 권한과 node/revision/enclosure UUID 매핑을
  확인한다. 403 로그만으로 원인이나 대상 사육장을 확정하지 않는다.

Pi 전송은 활성 상태로 실패 시 최대 60초 간격으로 재시도한다. 저장 ACK와
실제 SaaS 화면 표시 검증은 아직 남아 있다.

이번 진단에서 `https://easyrep.kro.kr/v1/edge/air`는 기존 Pi 토큰을 사용한
GET·OPTIONS 모두 JSON 404를 반환했다. `/v1/edge/sync`의 비인증 GET은
405였다. 이 결과만으로 서버 내부 미구현과 경로·등록·권한 문제를 구분할 수
없으므로 실제 POST 경로와 사육장 매핑을 서버에서 확인해야 한다. 추정값 POST,
저장 ACK 또는 로그인된 웹 조회는 이번에 검증하지 않았다.

## 2026-10-25 현재 요청: 사육장별 3D 공기 온도 화면

운영 SaaS 소스는 Pi 작업 환경에 없으므로, 아래 작업은 서버 담당자가 실제 SaaS
저장소에서 적용해야 한다. Pi 전송기·참고 수신기·공통 화면·OpenAPI와 계약/통합
테스트는 구현했으며, 운영 사이트 `easyrep.kro.kr`의 배포 완료 여부는 별도로 확인해야 한다.

```text
기존 EasyRep SaaS의 사육장 환경 페이지에 Pi의 3D 공기 온도 추정을 연결해줘.
docs/saas-integration.md의 air-estimate-v1과 docs/api/edge-sync.openapi.json을 읽고,
기존 서비스 언어·DB·로그인·사육장 권한을 유지해서 적용해줘.

1. POST /v1/edge/air를 실제 API로 구현한다.
   참고: habitat/saas/air_contract.py, air_receiver.py, habitat_gateway/saas_reference.py.
   기존 Pi 토큰의 site/gateway/cage 권한 범위와 서버의 node/revision 등록을 검사한다.
   UUID는 서버의 사육장 등록에서 매핑하며 본문만 믿고 자동 등록하지 않는다.
   최초 대상: STORE-001 / PI-001 / CAGE-001 / ESP32-001.
   환경 화면 UUID: 507a8d53-a6b1-49d7-aab3-1becba7a0451.
   현재 geometry_revision/placement_revision과 실제 등록을 먼저 확인한다.
2. 압축된 Float32 격자는 base64 디코딩 → 크기를 제한한 zlib 압축 해제 →
   정확히 48,000바이트인지 확인하는 순서로 처리한다. SHA-256, 값의 유한성과
   허용 범위, 값의 개수 12,000개, 좌표, 버전, 시각을 검사한다.
   JSON 요청 본문은 96 KiB, 압축 해제된 필드는 48,000바이트 한도로 검사하며,
   뒤에 추가된 압축 스트림도 거절한다.
   사육장별 최신 결과 1개와 최근 receipt 256개를 보관한다. DB 커밋이 끝난 뒤에만
   AirAck를 반환한다. 같은 ID로 다른 내용이 오면 409로 응답한다. 같거나 이전
   시각의 측정값은 최신 결과를 덮어쓰지 않으며, 중복 재전송이나 웹 조회로
   측정 시각 또는 수신 시각을 갱신하지 않는다.
3. GET /v1/enclosures/{uuid}/air를 기존 웹 로그인 세션·사육장 권한으로 보호한다.
   참고 수신기의 viewer bearer는 격리된 테스트용이다. Pi 토큰을 브라우저에 넣지 않는다.
   sampled_at 기준으로 30초가 지났으면 held/stale로 반환한다.
   아직 저장된 추정값이 없으면 404로 응답한다.
   기존 센서 이력은 기존 sync 경로로 저장한다. 3D 추정값을 수신했다는 사실만으로
   원본 측정 이력이 저장됐다고 판단하지 않는다.
4. habitat/digital_twin/air/web의 HTML/JS를 SaaS 자산으로 통합한다.
   동일 출처의 조회 주소를 #air-app의 data-air-endpoint에 지정하거나, 뷰 초기화 후
   window.HabitatAirView.setEndpoint('/v1/enclosures/<uuid>/air')를 호출한다.
   스크립트는 문서당 한 번 로드한다. SPA에서는 기존 뷰 DOM을 유지하면서
   endpoint만 바꾼다. DOM 전체를 교체하는 프레임워크라면 해당 컴포넌트의
   수명주기에 맞게 이식하거나, SaaS가 제공하는 동일 출처의 뷰 문서를 iframe으로
   로드한다. 조회 주소에 Pi의 localhost를 넣지 않는다.
   baseline이 없는 것은 정상이며, 주 추정 격자만 표시한다. 사육장을 전환할 때는
   이전 값을 지우고 늦게 도착한 이전 사육장의 응답을 무시한다.
   실측값, 추정값, CSV 재생을 구분해서 표시한다.
5. 다른 매장/사육장 조회 거절, 재시도 ACK, 잘못된 본문/압축, revision 변경,
   30초 지연, 두 사육장 간 전환, 지연 응답 차단, 기존 센서 API와의 호환성을 검증한다.
   tests/contract/test_air_receiver.py와 tests/integration/test_air_pipeline.py를 참고한다.
6. 배포 후 실제 API 주소, UUID 매핑, 인증 방식, 배포 revision을 Pi 담당자에게 전달한다.
   그다음 Pi의 upload.json을 활성화한다. 자연스럽게 발생한 실제 측정 message_id를
   기준으로 Pi → 서버 커밋/ACK → 해당 UUID의 웹 조회를 추적하며,
   측정값과 field_sha256을 대조한다.

기존 event_sequence·MQTT·센서 핀·TLS는 변경하지 마.
참고 수신기에 새 SQLite 테이블이 있다는 이유로 운영 DB 전체를 교체하지 마.
기존 구조에 추가 마이그레이션으로 반영한다.
```

## 2026-10-20 추가 요청: CAGE-001 실시간 카메라

아래는 과거 센서 API 구축 지시와 분리된 현재 추가 작업이다.
로그인 조회로 확인한 환경 화면은
`/#environment/507a8d53-a6b1-49d7-aab3-1becba7a0451`이며, 매핑은
`STORE-001 / PI-001 / CAGE-001 / RGB-001`이다. 웹 화면 UUID를 Pi ID 대신
보내지 않는다. 현재 카메라 탭은 `미연동`, `영상 연동 예정`을 고정 표시한다.

```text
기존 HabitatOS SaaS에 Pi의 HLS 실시간 영상을 연결해줘.
docs/saas-integration.md의 "실시간 영상 전송 v1"과 갱신된
docs/api/edge-sync.openapi.json을 먼저 읽어줘.

1. 기존 Pi 토큰 등록/권한 검사로 POST /v1/edge/video를 구현한다.
   참고: habitat/saas/video_contract.py, video_receiver.py 및
   habitat_gateway/saas_reference.py. 센서 event_sequence/schema를 바꾸지 않는다.
2. 등록된 camera_id→cage_id와 site/gateway 권한을 검사한다.
   JSON 3 MiB, TS 조각 2 MiB, 촬영 시각·SHA-256·세션·순서를 검증한다.
   커밋 후 정확한 VideoAck를 반환한다. 동일 중복은 같은 ACK,
   충돌/이전 세션은 409, 오래된 영상은 live로 제공하지 않는다.
3. 기존 로그인 세션과 사육장 권한으로 playlist/모든 TS 조회를 보호한다.
   Pi 토큰을 브라우저에 전달하지 않는다. 참고 구현의 viewer bearer는
   로컬 검증용이며 운영에서는 기존 세션 인증으로 대체한다.
4. 기존 카메라 탭에 <video controls muted playsinline>과 프로젝트가
   관리하는 고정 버전 hls.js를 연결한다. 동일 출처 세션으로 재생하고
   401/403/503, 재접속, 언마운트 시 destroy를 처리한다.
   HLS 네이티브 브라우저는 동일한 세션 URL을 사용한다.
   촬영 중/연결 끊김/지연 상태를 실제 응답으로 표시한다.
5. 환경 페이지 UUID를 기존 DB에서 site/gateway/cage로 해석한다.
   Pi IP나 사용자가 입력한 임의 외부 URL로 직접 접속하지 않는다.
6. 다른 매장 접근 거절, Pi 토큰의 조회 거절, 재시도, 15초 stale,
   Pi 재시작을 검사한다. 카메라별 최대 12조각, 재생목록은 최신 연속
   6조각만 유지한다. 기존 ingress에 요청 속도·동시 요청 제한을 적용한다.

완료 후 실제 업로드/조회 URL, 인증 방식, 테스트·배포 결과를 알려줘.
Pi 송신 기능은 소스에 준비돼 있으며 SaaS 배포 확인 후 활성화한다.
```

실제 SaaS 소스/배포 접근은 Pi 작업환경에 없다. 이 참고 코드 작성은 운영
웹사이트의 변경 완료를 뜻하지 않는다. 다음 절부터는 과거 인계 기록이다.

> 이 문서는 초기 구현 당시의 인계 지시서다. 팀원은 SaaS 연결을 구성했고 2026-09-20 기존 샘플 조회·웹·CSV를 확인했다. 아래의 “필요한 작업”, “확인 전”은 작성 당시 범위이며, 현재 미구현 목록으로 그대로 해석하지 않는다. 기존 구현을 유지하고 [운영 사이트 전수 조사](../operations/saas-site-review-2026-09-20.md)의 오류·미검증 항목을 먼저 확인한다.

민우님이 **habitatos SaaS의 실제 소스 저장소**를 열고 아래 작업 지시문을 사용한다. 인계 ZIP은 API·샘플·참고 코드이며, 운영 SaaS 소스나 배포 완료 파일이 아니다.

Pi 프로그램은 0.3.0, Pi→SaaS 센서 계약은 계속 v1.0.0이다. Pi→GPU 클라이언트 추가로 센서 수신 경로가 바뀌지는 않는다. 현재 기본 Pi 설정은 STORE-001 / PI-001 / CAGE-001의 시뮬레이션이며, 새 사육장 3개는 계획이다. 실제 센서값과 GPU 복원 결과는 아직 확보되지 않았다.

## 전달 범위

| 데이터 흐름 | 현재 제공하는 것 | SaaS에서 필요한 작업 |
|---|---|---|
| Pi → SaaS | `POST /v1/edge/sync`, OpenAPI, 요청/ACK 예시, Postman, 수신 참고 구현 | 인증·저장·중복 처리·실제 서버 라우팅 |
| SaaS → 브라우저 | 아래 조회/표시 요구사항 | 기존 로그인/매장 권한에 연결한 조회 API, 상태·이력 차트, 데모 데이터 교체 |
| Pi → GPU | 별도 `/v1/gpu` 계약과 Pi 클라이언트 구현 | 이 GPU 서버 API를 SaaS 센서 수신기로 착각하지 않기 |
| GPU → SaaS → 브라우저 | 아래 결과 연동 요구사항; 아직 API 합의/구현 전 | 파일 업로드·결과 등록 계약 합의, 모델 저장소와 웹 뷰 연결 |
| 영상/행동/열화상 | 전체 시스템의 후속 기능 | 실제 입력·권한·배포 경로를 확인한 뒤 별도 계약으로 구현 |

## 복사할 작업 지시문

```text
이 저장소의 HabitatOS SaaS를 실제 Pi 데이터와 연결해줘. 기존 코드와 사용자 인증·매장 모델·DB·API 라우팅·프런트엔드부터 확인하고, 기존 구조를 활용해 구현과 테스트까지 진행해줘.

첨부 인계 폴더의 docs/api/README.md, edge-sync.openapi.json, sync-request.json, sync-response.json, heartbeat-request.json을 먼저 읽어줘. Python 수신 참고 코드는 habitat_gateway/saas_reference.py와 sync_contract.py다. 기존 SaaS의 언어/프레임워크를 유지해도 된다. 참고 코드를 읽을 때 habitat/common/에 있는 공유 입력 검증도 함께 봐줘.

[역할과 현재 상태]
- 각 매장의 Pi가 여러 사육장의 ESP32를 관리하고 센서·출력·명령 이력을 SaaS에 전송한다. 한 매장에 Pi가 여러 대 있을 수 있다.
- 모든 매장에 같은 Pi 프로그램을 쓰며 site_id/gateway_id/cage_id와 등록 설정으로 구분한다.
- Pi 송신 코드와 로컬 참고 수신기는 구현됐다. 운영 habitatos API와의 실연결은 아직 확인 전이다.
- Pi 프로그램 버전 0.3.0, 센서 API 계약 v1.0.0(schema_version=1)이다. GPU 기능 추가 때문에 센서 JSON 필드를 임의 변경하지 마.
- 기본 검증 대상은 STORE-001 / PI-001 / CAGE-001 한 개의 가상 노드다. CAGE-002/003은 후속 등록 예정이며 아직 측정값이 있다고 표시하면 안 된다.
- 사육장 센서와 장치의 안전 제어는 ESP32/Pi가 담당한다. SaaS는 수신한 command.updated를 장치 명령으로 다시 실행하지 않는다.

[1. Pi 수신 API 구현]
- 목표 수신 주소는 POST https://habitatos.kro.kr/v1/edge/sync다. 아직 배포됐다고 가정하지 말고 실제 서버 라우팅을 확인해줘.
- 이 경로는 HTML 프런트엔드 fallback이나 리다이렉트 대신 API JSON을 반환해야 한다.
- Authorization: Bearer 방식의 Pi 전용 토큰을 사용한다. SaaS 사용자 로그인 토큰과 구분해줘.
- 토큰에서 tenant/site/gateway/허용 cage 목록을 조회한다. 본문의 site_id만 믿어 다른 매장 데이터에 접근하거나 자동 등록·이관하지 마.
- 한 사육장의 활성 담당 Pi는 하나로 관리하고, Pi마다 별도 토큰을 발급해줘. 개발 등록만 시뮬레이션을 명시적으로 허용해줘.
- schema_version, ID 참조, timezone, 이벤트 종류/순서, 센서 품질, 8 MiB 요청 한도를 검사해줘. OpenAPI와 모델의 교차 필드 검증을 함께 따라줘.
- 원본 이벤트와 최신 gateway/cage 상태를 구분해 저장해줘. 중복 키는 (site_id, gateway_id, event_id)다. tenant는 서버 등록 정보에서 찾고 전역 ID 공간이 충돌하지 않게 연결해줘.
- 같은 이벤트 재수신은 중복 저장/실행하지 않고 이미 저장한 ID를 ACK한다. 같은 ID 또는 같은 Pi의 같은 sequence에 다른 내용이 오면 충돌로 거절해줘.
- DB 트랜잭션 커밋이 끝난 뒤 HTTP 200으로 schema_version, site_id, gateway_id, accepted_event_ids를 반환해줘. 204/202/{success:true}는 현재 Pi의 성공 ACK가 아니다.
- events=[] heartbeat도 허용하고 accepted_event_ids=[]로 응답해줘.
- 늦게 도착한 과거 이벤트는 이력에 보존하되 현재 화면을 과거 상태로 되돌리지 마. 센서는 sampled_at, 명령 이력은 해당 Pi의 event_sequence, gateway snapshot은 sent_at을 각각 사용해줘.
- event_sequence를 다른 Pi와 비교하지 마. DB 초기화/장치 이관은 등록 세대 또는 새 gateway_id로 명시적으로 처리해줘.

[2. 기존 웹 화면에 실제 조회 데이터 연결]
- 기존 서버의 조회 API 패턴과 로그인·매장 권한을 재사용해 매장 목록 → Pi/사육장 목록 → 사육장 상세·이력 화면을 연결해줘. 브라우저에는 HABITAT_CLOUD_TOKEN/HABITAT_GPU_TOKEN을 노출하지 마.
- 온도·습도·조도는 configuration의 센서 ID와 단위를 함께 사용해줘. 대표 센서는 설정으로 정하고 센서별 값도 볼 수 있게 해줘.
- quality가 valid가 아니거나 값이 null이면 오류/측정 불가로 표시해줘. 0으로 바꾸거나 임의의 정상값을 만들지 마.
- data_source=simulation은 가상 데이터라고 표시하고 실제 센서 수치와 구분해줘. 시각은 저장 시 UTC, 표시 시 사용자 시간대로 변환해줘.
- Pi의 최근 수신 시각, 센서의 sampled_at/received_at을 별도로 보존·표시해줘. Pi가 온라인이어도 센서가 오래됐을 수 있다. heartbeat가 최근이라는 이유만으로 센서값을 최신으로 만들지 마.
- gateway heartbeat offline 판정 시간은 SaaS 설정으로, 센서 stale 기준은 현재 센서 수집/게이트웨이 정책과 맞춰 관리하고 적용값을 문서화해줘. payload에 없는 판단값을 Pi가 측정한 값처럼 표시하지 마.
- light/mister 등 출력 상태는 관측값과 관측 시각을 표시해줘. ON 명령을 보냈다는 사실만으로 실제 작동 완료나 물 토출 성공으로 표시하지 마.
- command.updated의 published/applied/rejected/expired/interrupted를 구분해 명령 결과 이력을 보여줘.
- 데모 숫자는 실제 데이터 수신 뒤 서버 조회값으로 교체하고 미수신/오류/오프라인 상태를 구현해줘. 카메라나 3D 모델이 없으면 준비 중/미연결로 보여줘.
- 로컬 Pi 제어 API를 인터넷에 노출해 브라우저가 직접 조작하는 경로를 새로 만들지 마. SaaS→Pi 원격 명령 수신 계약은 아직 구현하지 않았으므로 원격 제어 버튼을 작동한다고 표시하지 마.

[3. GPU 결과와 영상 연결은 후속 계약으로 정리]
- docs/gpu/gpu-api-contract.md와 configs/schemas/compute-v1/는 Pi→GPU 계약이다. SaaS→GPU 또는 GPU→SaaS API가 이미 구현됐다는 뜻이 아니다.
- 3DGS 결과는 별도 파일 업로드와 결과 metadata 등록으로 설계해줘. /v1/edge/sync에 camera/3dgs/behavior 이벤트를 임의 추가하지 마.
- GPU가 SaaS가 관리하는 모델 저장소에 업로드한 뒤, SaaS가 해시/크기/권한을 검증하고 결과를 등록하는 방향을 우선 검토해줘. 실제 업로드·등록 URL과 요청/ACK 스키마는 문서 초안으로 제공하고 Pi/GPU 담당자와 합의할 변경 목록을 남겨줘.
- 최소 연결 정보는 site_id/gateway_id/cage_id, capture_id/job_id, geometry_revision/placement_revision, artifact_id, format, size_bytes, sha256, metric_scale_verified, 생성 시각, backend/model metadata다. 원본 Pi/GPU ID를 보존해 중복 등록과 다른 사육장 연결을 막아줘.
- 사용자 브라우저에 GPU의 Tailscale IP나 /v1/gpu/.../artifacts/...를 그대로 모델 주소로 넘기지 마. SaaS 로그인 권한을 거친 모델 URL/단기 다운로드 URL을 제공하는 경로를 설계해줘.
- 업로드만 끝났다고 현재 모델을 바꾸지 마. 파일 검증/metadata 등록 완료 후 해당 geometry_revision의 모델을 게시하고 기존 모델과 수정 이력을 보존해줘.
- v1 GPU 결과는 metric_scale_verified=false다. 보정되지 않은 3DGS를 실측 좌표로 쓰지 마. 실제 센서값, 공간 추정, 열화상 표면값은 데이터와 UI에서 구분해줘.
- 라이브 영상은 별도 미디어 중계와 브라우저 재생 경로가 필요하다. 스트림/카메라가 없으면 모의 영상을 실시간이라고 표시하지 마. 객체 탐지·행동 분석·열화상은 아직 공급되는 데이터가 없으므로 임의로 생성하지 마.
- 이 단계의 GPU→SaaS 수신 경로는 합의 전이다. 센서 수신·웹 조회 작업을 완료하고 GPU 계약 문서의 미확정 항목을 명시해줘. 빈 모듈·미작동 endpoint를 완료된 기능처럼 만들지 마.

[4. 검증과 인계]
- 제공 JSON으로 정상 수신, 동일 이벤트 재전송, 빈 heartbeat, 잘못된 토큰, 타 매장/cage, ID 충돌, DB 저장 실패, 늦게 도착한 이벤트와 offline/stale 표시를 검증해줘.
- 서버 테스트 통과와 실제 Pi→공개 HTTPS 수신 검증은 따로 기록해줘. Pi 연결 없이 실제 센서 연동 성공이라고 보고하지 마.
- SAAS_API_RESULT.md를 만들어 실제 배포 URL, 계약 버전, 담당 저장소/실행 방법, 등록된 Pi/cage, simulation 허용 여부, 웹 조회 API, 테스트 결과, 남은 작업을 정리해줘.
- 새 조회 API의 OpenAPI나 동등한 명세, GPU 결과 업로드/등록 계약 초안도 함께 반환해줘.
- 토큰 원문·비밀번호·private key는 문서/로그/응답에 넣지 마. Pi에 전달할 결과에는 HABITAT_CLOUD_TOKEN이라는 환경변수 이름과 설정 필요 여부만 기록하고 값은 별도 비밀 전달 경로를 사용해줘.
```

## 민우님에게 함께 보낼 짧은 메시지

> SaaS 연동 자료도 준비했어. ZIP 안 `docs/api/saas-codex-prompt.md`를 SaaS 저장소에서 실행하면 돼. 우선 `POST /v1/edge/sync` 수신·저장·ACK와 매장/사육장별 웹 조회를 연결해줘. Pi 송신 코드는 준비돼 있고, GPU 작업 추가 후에도 이 센서 API는 v1 그대로야. GPU 결과 파일·영상은 별도 연결이라 필요한 계약 초안도 지시서에 적었어. 배포한 HTTPS 주소와 등록한 Pi/cage 정보를 알려주면 Pi 쪽에서 실제 송신을 연결할게. 토큰 값은 문서나 채팅에 넣지 말고 따로 설정하자.

이 문서는 전달 초안이며 메시지를 자동 발송하지 않았다.
