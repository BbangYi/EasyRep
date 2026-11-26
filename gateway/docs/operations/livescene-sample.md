# LiveScene 공식 문 샘플 준비 및 실행

## 2026-10-04 18:22 KST 운영 경로 재확인

실제 Pi 운영 API에서 조회한 GPU 모델은 `interreal-door-original-30000` 하나이며,
`source_kind=reference_dataset`, `quality_status=experimental_background_motion_unresolved`다.
정적 Nerfacto 5,000은 아래 별도 네이티브 뷰어 경로로, 이 Pi 모델 목록에 등록되어 있지 않다.
LiveScene은 기존 모델 렌더만 configured이고 `rgb_training_configured=false`다.
새 Gaussian 복원 작업 backend의 `not_configured`는 별도 상태로 유지된다.

Pi의 운영 `/v1/livescene/render`를 통한 320px 객체 지도 포함 요청은 HTTP 429였다.
거절 응답 0.0975초는 렌더 성능으로 사용하지 않는다. 이어서 GPU에서 정적 뷰어
`habitat-static-viewer.service`가 active, PID 1909이며 공유 reconstruction.lock을
점유한 것을 확인했다. 기존 뷰어와 잠금은 유지했고 이번에 새 렌더·학습 파일을 만들지 않았다.
따라서 아래 10/03의 20~23초 렌더 수치는 과거 측정이며 오늘 재측정 성공 수치가 아니다.

이번 가상 분무 실험과 3D·SaaS의 전체 범위는 [현재 시스템 상태](../system-architecture.md)에 정리했다.

## 2026-10-04 정적 5,000스텝 자유시점 확인

GPU를 켠 뒤 WSL Ubuntu를 시작하고 기존 정적 Nerfacto 체크포인트를 native Nerfstudio 1.1.5
뷰어로 열었다. Pi의 `/livescene` 정지 렌더 화면과 별도이며, GPU에서 시점을 바꿔 새 영상을 계산한다.
학습이나 PLY 내보내기는 실행하지 않았다. 이 장면은 공개 InterReal 문 장면이며 실제 사육장 촬영이 아니다.

- 설정: `/home/<gpu-user>/.local/share/habitat-gpu/livescene/study-20261002/runs/static/nerfacto/run/config.yml`
- 체크포인트: 같은 실행의 `nerfstudio_models/step-000005000.ckpt` (176,068,710 bytes)
- 설정 SHA-256: `6753fcb6ef76c9aa8a79ea29adb441459bee63d40d4b5f465fb7ca2c15b5a2fd`
- 체크포인트 SHA-256: `71d9ffd93cc7bb627c4ae509b5ebbb911f4ba515dc38dce4f87eabf867e1b289b`
- 현재 PC 주소: `http://127.0.0.1:7007/` (GPU PC와 SSH 포트 전달이 켜져 있어야 함)

[`scripts/view_reconstruction.py`](../../scripts/view_reconstruction.py)는 네이티브 뷰어를 재사용한다.
Nerfstudio의 `eval_setup`이 저장된 VanillaDataManager를 ParallelDataManager로 치환해 발생하던
`queue_size` 오류는 평가 콜백에서 원래 데이터 로더를 유지해 해결했다. 원본 설정·체크포인트·
site-packages는 수정하지 않는다. 프로세스 안에서 step 5000을 지정하고 초기 카메라 249,
학습 카메라 숨김, 실제 Step 표시를 적용한다. 사용자 접속 전 통계 갱신이 조기 반환되어
Step 0으로 남던 네이티브 뷰어 표시도 바로잡았다.

GPU WSL에서 실행하는 명령:

```bash
systemd-run --user --unit=habitat-static-viewer --collect \
  --property=Type=exec --property=TimeoutStopSec=20 \
  --working-directory=/home/<gpu-user>/.local/share/habitat-gpu/livescene \
  /usr/bin/flock -n /home/<gpu-user>/.local/share/habitat-gpu/livescene/reconstruction.lock \
  /home/<gpu-user>/.venvs/habitat-livescene/bin/python \
  /mnt/c/Users/<user>/Desktop/HabitatOS/scripts/view_reconstruction.py \
  --config /home/<gpu-user>/.local/share/habitat-gpu/livescene/study-20261002/runs/static/nerfacto/run/config.yml \
  --step 5000 --camera-index 249 --port 7007
```

뷰어는 기존 복원 잠금을 공유하므로 켜진 동안 다른 LiveScene 렌더 요청은 busy로 대기/거절될 수 있다.
환경 예측 서비스와 Pi 물리 제어 설정은 변경하지 않았다. 종료는 GPU WSL의
`systemctl --user stop habitat-static-viewer`이며, 이 unit은 재부팅 자동 시작을 설정하지 않았다.

현재 PC의 접속 통로:

```powershell
ssh -N -L 127.0.0.1:7007:127.0.0.1:7007 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 jsj_desktop
```

브라우저 검증: HTTP 200, Step 5000, 처음부터 실내 시점, 새로고침 후 단계 표시를 확인했다.
40×10px 회전에서 ViewerCameraMessage 송신 11→29, GPU BackgroundImageMessage 수신 7→24,
캔버스 영역 변화와 정지 후 512×433 렌더를 확인했다. JavaScript 오류는 0건이었다.
검증 이미지는 메모리에서만 확인했으며 새 렌더 묶음·압축파일·모델 복사본을 저장하지 않았다.
사용자 브라우저를 자동으로 여는 연결 도구는 없으므로 접속 링크를 전달한다.

조작은 왼쪽 드래그로 회전, 오른쪽 드래그로 이동, 휠로 확대/축소한다.
이동 중 저해상도 미리보기는 정지 후 갱신된다. 더 큰 정지 화면은 `Max res`를 올려 확인할 수 있다.
이번 확인은 자유시점 렌더 동작과 시각 검수이며, 실제 사육장 복원이나 모든 시점의 품질 합격 판정은 아니다.

## 0.4.7 화면 개편 — Pi 배포 완료

0.4.7은 같은 `/livescene` 화면을 흰 바탕의 사진 갤러리로 개편한다. 매장 연결 화면,
사육장 목록, 상세 화면의 색·글자·간격을 함께 정리하고, 반복 SVG 대신 사육장 형태별 AI 생성 표지를 사용한다.
목록은 4:3 표지와 이름·종·온습도를 중심으로 구성하며 데스크톱 3열에서 작은 화면 1열까지 전환한다.
녹색은 주요 동작과 상태 표시에 절제해서 사용하고, 카드 전체를 둘러싼 진한 테두리는 제거한다.
사용자가 요청한 카드 선택과 `+` 카드 추가 흐름은 유지한다.
2026-10-04 Pi에 `0.4.7-f630b8c2c0bd`를 설치했고 MQTT 연결·서비스 상태가 정상이다.
제공 HTML의 SHA-256은 `aef9b91dfc0a124e74eff26461040b94ba57eea97291ba6f120233c3927603db`로
Windows 소스·패키지·운영 응답이 일치한다. 표지 3개의 바이트와 해시도 일치한다.

검증: Pi의 API·LiveScene 계약·배포 테스트 38개와 하위 검사 11개 통과.
1440px·390px 브라우저에서 사육장 선택·등록·재접속·오류·등록 경쟁조건을 확인했고
가로 넘침과 JavaScript 오류는 없었다. 검색 시 미설정 사육장의 표지가 바뀌지 않는 것도 확인했다.
공개 DNS로 직접 연결한 외부 HTTPS에서 화면·표지 3개 모두 200, TLS 검증 성공,
접속 키 없는 `/v1/enclosures`는 401이었다. 운영 등록 항목은 기존 3개 그대로이며
하드웨어 출력은 잠금 상태다. GPU 실행 검증은 사용자의 요청에 따라 이번 작업에서 하지 않았다.
배포용 임시 아카이브는 설치 후 제거했다. 아래 0.4.6은 이전 배포 기록이다.

### 공식 시각 참고와 설계 의도

- [Steam Library 공식 소개](https://store.steampowered.com/libraryupdate): 시각적인 라이브러리에서 항목을 고르고 상세 화면으로 이동하는 구성 원리를 참고했다. 이 링크는 과거 Library 개편 소개이며 최신 Steam 화면이라는 의미는 아니다.
- [Airbnb 2026 Summer Release](https://news.airbnb.com/airbnb-2026-summer-release): 공식 호텔 목록·상세 이미지에서 큰 사진, 사진 아래의 간결한 이름·메타데이터, 목록에서 상세로 이어지는 위계를 확인했다. HabitatOS에서는 흰 바탕과 큰 표지, 짧은 설명으로 적용한다.
- [Linear 2026 UI refresh 설계 설명](https://linear.app/now/behind-the-latest-design-refresh): 공식 전후 비교 이미지의 절제된 사이드바·아이콘과 약한 구분선을 참고했다. 탐색 요소보다 선택할 사육장과 현재 작업이 먼저 보이도록 한다.
- [TerraLiving 공식 사이트](https://www.theterraliving.com/): 실제 테라리움 사진의 유리 반사, 식물 질감, 조명으로 생기는 깊이를 시각 참고로 확인했다. 해당 사진이나 제품 디자인을 HabitatOS 자산으로 복사하지 않았다.

참고 사이트 이미지는 조사 후 임시 파일을 삭제했다. 제품에 포함되는 표지 3개는 내장 이미지 생성 도구로
별도 생성한 예시이며, 실제 매장·개체 촬영이나 LiveScene 복원 결과가 아니다.
화면에도 `예시 이미지`와 AI 생성 안내를 표시한다. 표지 선택은 실제 센서·장치 설정을 바꾸지 않는다.

| 패키지 자산 | 용도 |
|---|---|
| `habitat_gateway/assets/terrarium-tropical.webp` | 수직형 사육장 표지 및 매장 연결 화면 |
| `habitat_gateway/assets/terrarium-desert.webp` | 수평형 사육장 표지 |
| `habitat_gateway/assets/terrarium-aquatic.webp` | 수생형 사육장 표지 |

### 표지 생성 기록

내장 `image_gen` 도구의 generate 모드로 각각 생성했다. 외부 API/CLI는 사용하지 않았다.
1536×1024 원본을 같은 해상도의 WebP quality 82로 인코딩했으며, 배포 자산 합계는 980,604바이트다.
아래는 실제 사용한 최종 프롬프트다.

#### tropical

```text
Use case: photorealistic-natural. Asset type: original photographic cover for a Korean terrarium management web application. A lush vertical tropical terrarium interior: layered emerald ferns, delicate moss, one natural cork-bark climbing branch, a few broad deep-green leaves, dark rich natural substrate. A subtle black glass enclosure frame at the outer edges; sophisticated botanical studio still-life. Close, immersive landscape composition with distinct foreground and background depth, contents fill the frame. Natural side light, crisp believable material detail, premium editorial photography, balanced light exposure with luminous highlights, no muddy flat green filter. Landscape 3:2, about 1536x1024. No animals, people, text, lettering, logo, watermarks, UI, diagram, labels, collages or split panels. This is illustrative cover photography, not a technical assembly diagram.
```

#### desert

```text
Use case: photorealistic-natural. Asset type: original photographic cover for a Korean terrarium management web application. An arid reptile terrarium interior: sculptural warm sandstone, pale sand, a weathered natural branch, a small dry grass tuft and subtle succulent. A subtle black glass enclosure frame at the outer edges; sophisticated natural-history studio still-life. Close, immersive landscape composition with distinct foreground and background depth, contents fill the frame. Natural side light, crisp believable material detail, premium editorial photography, balanced light exposure with luminous highlights, no muddy flat green filter. Landscape 3:2, about 1536x1024. No animals, people, text, lettering, logo, watermarks, UI, diagram, labels, collages or split panels. This is illustrative cover photography, not a technical assembly diagram.
```

#### aquatic

```text
Use case: photorealistic-natural. Asset type: original photographic cover for a Korean terrarium management web application. A paludarium interior: mossy dark slate rocks, delicate green ferns and a still shallow pool with beautiful real waterline reflections. A subtle black glass enclosure frame at the outer edges; sophisticated botanical studio still-life. Close, immersive landscape composition with distinct foreground and background depth, contents fill the frame. Natural side light, crisp believable material detail, premium editorial photography, balanced light exposure with luminous highlights, no muddy flat green filter. Landscape 3:2, about 1536x1024. No animals, people, text, lettering, logo, watermarks, UI, diagram, labels, collages or split panels. This is illustrative cover photography, not a technical assembly diagram.
```

## 사육장 라이브러리·객체 선택 및 장치 제어 화면 — 0.4.6

Pi 게이트웨이의 `/livescene`은 같은 프로젝트에 포함된 브라우저 화면이다.
0.4.6에서는 매장 사육장 라이브러리에서 카드를 선택해 3D·센서·장치 제어 상세를 연다.
새 사육장의 이름·종·형태는 Pi에 영구 등록하지만, 센서·노드 설정이나 SaaS 등록을 자동으로 생성하지 않는다.
신규 항목은 `pending_setup`이며 실제 장치 구성이 등록될 때까지 제어할 수 없다.
카드 일러스트는 실제 촬영·복원 영상이 아니다. 운영 릴리스 `0.4.6-e55b121673e8` 설치와 제공 HTML 해시 확인을 완료했다.
GPU의 인증키는 서버에 남겨두며, Pi API 인증키는 브라우저 메모리에서만 사용한다.

외부 PC·휴대폰은 별도 앱 없이 [매장 화면](https://gateway.example.ts.net/livescene)에 접속한다.
Pi의 기존 Tailscale Funnel을 사용하며 방문자에게 Tailscale 설치가 필요하지 않다.
공개 DNS 주소로 직접 연결해 화면 HTTPS 200·TLS 검증 성공·무인증 API 401을 확인했다.
매장 접속 키는 계속 필요하며 SaaS 계정 로그인과는 별개다.
아래 SSH·Connect 안내는 추가 관리자용 접속 경로다. Pi의 원래 서비스는 loopback을 유지한다.
PC에서 다음 포트 전달을 유지하면
`http://127.0.0.1:18000/livescene`에 접속한다.

```powershell
ssh -N -L 127.0.0.1:18000:127.0.0.1:8000 <gateway-user>@192.168.219.103
```

외부 네트워크에서는 같은 Tailscale에 로그인한 PC에서 Pi의 등록 주소
`100.102.106.40`을 사용한다. 현재 PC에 저장된 기존 Pi 호스트 키로 검증하려면:

```powershell
ssh -N -o HostKeyAlias=192.168.219.103 -o StrictHostKeyChecking=yes -L 127.0.0.1:18000:127.0.0.1:8000 <gateway-user>@100.102.106.40
```

[Raspberry Pi Connect](https://connect.raspberrypi.com/devices)의 화면 공유로 접속한 경우에는
Pi 안의 브라우저에서 `http://127.0.0.1:8000/livescene`을 연다. Connect의 원격 셸로
서비스 상태를 확인할 수도 있다. 화면의 Pi API 인증키는 SSH 암호와 다르며,
운영 관리자만 `/etc/habitat-gateway/gateway.env`에서 확인한다.

1. Pi API 인증키로 매장에 연결한 뒤 라이브러리에서 사육장 카드를 선택한다. 등록 모델이 있는 사육장은 모델·촬영 시점을 선택한다. 새 사육장은 추가 창에서 이름·종·형태를 입력하며, 저장 응답이 확인된 경우에만 목록에 추가된다.
2. 렌더를 요청하면 GPU가 RGB와 같은 카메라·상태의 객체 ID 지도를 함께 생성한다.
3. 객체 픽셀을 클릭하거나 객체 목록에서 선택하고, 상태를 지정한 뒤 적용한다.
   배경의 ID는 0이며, 현재 단일 문 모델의 ID는 1이다. 학습된 분류 확률의 argmax를 사용한다.
4. 장치 패널은 Pi의 실제 연결·센서·차단 상태를 보여준다. 분무는 대상과 작동 시간을
   확인하여 명시적으로 요청하며, 전송 상태와 노드의 실제 적용 응답을 구분한다.
   GPU 렌더가 실행 중이거나 실패해도 Pi의 직접 정지·OFF 경로는 유지된다.

현재 렌더는 요청마다 모델을 읽는 방식이며 실시간 드래그 스트리밍이 아니다.
슬라이더를 움직일 때마다 렌더하지 않고 적용할 때만 요청한다. 렌더와 클릭 지도는
검증 후 메모리로 전달하며, 요청별 임시 디렉터리는 삭제한다.
현재 등록 모델은 공개 문 장면으로 실제 사육장 복원이나 분무 장치 위치를 나타내지 않는다.
이 화면은 Pi 패키지에 포함된다. 다른 팀원 PC의 SaaS 화면에는 별도 연동이 필요하다.

### 실제 객체와 장치 연결

GPU의 보호된 모델 manifest에 `objects`, `geometry_revision`, `placement_revision`을 등록하고,
실제 촬영 모델(`source_kind=camera_capture`)의 객체에 대해서만 Pi 설정에
`[[livescene_bindings]]`를 추가한다. 필요한 키는 `model_id`, `cage_id`, `object_id`,
`actuator_id`, `checkpoint_sha256`, `geometry_revision`, `placement_revision`이다.
실측한 객체 식별자·기존 사육장 장치 ID·고정 체크포인트 SHA를 사용하며 임의 값을 넣지 않는다.

Pi는 등록된 매장·사육장, 모델 종류, 체크포인트, 객체, 기하·배치 버전을 다시 확인하고
기존 `gateway.send_command`로 명령을 전달한다. 공개 샘플·미연결 객체·오래된 배치는 거절한다.
물리 출력 허용, 센서 유효성, 최대 작동 시간, 재분무 대기시간, 노드 응답 검사는 그대로 유지한다.
현재 운영 Pi의 `hardware_outputs_enabled=false`와 빈 바인딩 목록은 유지한다.

### 추가 HTTP 계약

- Pi `GET /v1/enclosures`: `cage_id`, `name`, `species`, `form_factor`, `configuration_status`, `sensors:[{id,unit}]` 목록을 반환한다. 기존 설정에 프로필이 없으면 이름은 사육장 ID, 종은 빈 문자열, 형태는 `null`이며 센서 메타데이터는 실제 설정에서 가져온다.
- Pi `POST /v1/enclosures`: `name`(1~80자), `species`(1~120자), `form_factor`(`vertical`/`horizontal`/`aquatic`)만 받는다. 이름·종의 공백을 정리하고 매장 내 이름 중복과 총 1,000개 한도를 검사한다. 성공 시 서버가 UUID 기반 ID를 부여해 `pending_setup`, `sensors:[]`인 프로필을 201로 반환한다. 등록과 로컬 감사 기록은 함께 저장되며 재시작 후에도 유지된다. 입력으로 매장·노드·장치 제어 필드를 지정할 수 없다.
- 신규 프로필은 기존 `/v1/cages` 장치 목록이나 SaaS 동기화 데이터에 자동으로 추가되지 않는다. 실제 장치 설정이 없는 ID의 제어 요청은 기존처럼 거절된다.
- GPU/Pi `GET /v1/livescene/models`: 인증 범위 내 모델·객체·리비전 목록. 파일 경로와 키는 제외한다.
- GPU/Pi `POST /v1/livescene/render`: 기존 요청에 선택적 `include_interaction=true`를 추가했다.
  이 경우 응답의 `interaction`에 동일 크기의 `L` 모드 PNG, SHA-256, 객체 목록이 포함된다.
  기존 CLI 요청·응답 방식은 유지한다.
- Pi `POST /v1/livescene/commands`: `request_id`, `model_id`, `cage_id`, `object_id`, `action`,
  `duration_s`, `checkpoint_sha256`, `geometry_revision`, `placement_revision`을 받는다.
  화면에 표시했던 모델·배치가 현재 등록과 일치해야 한다. 실제 `actuator_id`는 서버가 결정한다.
  GPU 조회 대기 중 정지 또는 다른 명령이 실행되면 뒤늦은 ON 요청은 거절한다.
- 기존 `/v1/cages/{cage_id}/commands`, `/stop`, `/v1/commands/{command_id}`는 계속 사용한다.
  작동 요청의 재시도는 같은 식별자로 확인하며, 네트워크 오류를 새 작동 요청으로 자동 재전송하지 않는다.

### 0.4.6 검증 범위

Pi API 검사 9개, 전체 검사 294개·subtest 145개가 통과했고 7개는 제외됐다(101.32초).
Chrome 합성 API 및 별도의 실제 Pi 임시 모의 서버에서 1440px·390px 화면의 등록·상세 이동을 검증했다.
실제 Pi 검사에서는 클라우드·GPU를 끄고 임시 DB를 사용했으며, 등록 201·`pending_setup` 렌더 차단·페이지 새로고침/재인증 후 항목 보존·기존 사육장 센서 표시와 출력 잠금을 확인했다.
가로 넘침과 JavaScript 오류는 없었고 임시 서버·DB는 제거했다. 검증 UI SHA-256은 `de6e299c4d18c2ee1fc9fa7ef4e0173ce2820ffc63e40537a5e8755377d0e1d5`다.
이후 운영 릴리스 `0.4.6-e55b121673e8` 설치·서비스 건강·매장 ID 검사를 통과했고, 제공 HTML 68,428 bytes의 SHA-256이 위 값과 일치했다.
운영 `/v1/enclosures`는 무인증 조회·잘못된 키 조회·무인증 등록에 각각 401을 반환했고, 유효한 키 조회는 200과 기존 설정 사육장 3개·등록 대기 0개를 반환했다. 실물 출력은 계속 꺼져 있다.
SaaS 마지막 ACK는 `2026-10-03T18:16:50Z`였으며 오류와 전송 대기 항목은 없었다.
기존 권한으로 Tailscale Funnel의 HTTPS 443을 백그라운드 활성화했다. 공개 DNS의 `203.0.113.11`으로 직접 연결해 화면 HTTPS 200·TLS 검증 성공과 무인증 API 401을 확인했으며, 별도 관리 정책을 추가하지 않았다.
GPU 실제 재검증은 사용자 요청으로 보류 중이다. 이전 GPU 성공 결과는 아래 당시 기록으로 보존한다.

## 2026-10-03 모델·GPU 검증 기록 (과거)

원래 문 장면의 step 30000 학습은 종료했고 체크포인트를 보존했다. 실제 Pi가 Tailscale HTTPS의 `GET /v1/livescene/health`, `POST /v1/livescene/render`를 호출해 GPU에서 새로 렌더한 320×237 PNG를 받았다. 첫 원본 모델 요청 왕복은 23.119초, 서버 렌더 작업은 16.696초였다. Pi에서 PNG 크기·SHA-256·요청 식별자·모델 식별자를 검증했다. 요청별 모델 로딩 방식이며 실시간 스트리밍이 아니다.

서버 설정은 `[backend.livescene]`의 `python`, `manifest`, `lock_file`을 사용한다. 보호된 모델 manifest에는 scope, 모델 ID, config 경로·SHA-256, checkpoint step·SHA-256, 평가 카메라 수, source_kind와 quality_status를 기록한다. 클라이언트는 서버 파일 경로를 지정할 수 없다. 학습과 렌더는 같은 flock을 사용하며 학습 중 요청은 429다. 환경 예측 API는 별도 경로를 유지하고 학습 중 실제 Pi의 합성 입력 왕복도 통과했다.

LiveScene API는 등록 모델의 렌더 기능을 제공한다. `rgb_training_configured=false`, `field_validated=false`이며 원시 RGB 업로드→마스크/상태 라벨 자동 생성→LiveScene 재학습은 연결되지 않았다. SaaS 운영 화면도 이 변경으로 배포되지 않았다. 기존 `/v1/gpu`의 Gaussian PLY 작업 계약과 `not_configured` 상태는 별도이며, 이를 LiveScene 성공으로 위장하지 않는다.

정적 배경 Nerfacto 5000스텝은 동일 train 320/eval 35 분할에서 실행했다. 같은 6개 평가 시점의 배경 평균 PSNR은 Nerfacto 27.044 dB, 원래 LiveScene 19.061 dB다. 모델 구조와 학습 목표가 달라 이 차이만으로 포즈 오류를 배제하거나 원인을 확정하지 않는다. 상세 비교 증거는 GPU 런타임 `livescene/study-20261002/evaluation/`에 저장한다.

원래 step 30000에서 스케줄 상태를 복원하고 비교 모델과 배경 판별 후보를 각각 2000스텝 추가 학습했다. step 32000의 비교 모델/후보는 평균 PSNR 18.516/19.309 dB, 저장 PNG의 SSIM 0.7122/0.7086, LPIPS 0.3787/0.4078이다. 고정 배경 상태 간섭은 98.55% 감소했지만 SSIM·LPIPS가 악화하여 **후보를 채택하지 않았다**. API는 보존된 원본 모델을 명시적으로 렌더한다. 재학습 준비 중 스케줄 상태를 초기화해 실패한 `rejected-scheduler-reset` 시도는 최종 비교에서 제외했으며, 해당 산출물은 2026-10-03 GPU 정리에서 삭제했다. 현재 설정의 `background_aware_selection` 기본값은 false로 기존 동작을 유지한다.

실제 Pi에서 상태 0·1 렌더 요청도 각각 22.339/20.983초에 완료했으며 다른 PNG·해시를 확인했다. 서버는 기존 Backend의 프로세스 감시·시간 제한·자식 프로세스 정리를 재사용한다. CLI는 별도 `--request-file`로 보호된 임시 요청 파일을 받으며 임의 클라이언트 경로를 실행하지 않는다.

## 2026-09-21 설치 및 최초 실행 기록 (과거)

2026-09-21 설치 및 실행 기록이다. 공식 샘플 입력 검증, 별도 Python 환경, 호환성 패치 및 tiny-cuda-nn 빌드·설치를 완료했다. CPU 호환성 검사, `ns-train livescene --help`, 실제 tiny-cuda-nn `FullyFusedMLP` CUDA forward/backward의 유한값 검사도 통과했다. **512 / 4,096 rays의 100회 smoke test는 모두 정상 종료했고 checkpoint 저장을 확인했다. 512 rays checkpoint의 렌더 경로도 통과했다. 현재 30,001회 본학습 중이며, 장면 품질·의미 있는 문 상태 변화는 아직 합격 판정하지 않았다.**

아래 최초 실행 당시에는 공식 LiveScene의 별도 샘플 실행이었다. 공개 `/v1/gpu` API는 LiveScene으로 전환하지 않았으며, 이 샘플 실행은 API job이나 artifact를 생성하지 않았다. 기존 Splatfacto 결과는 LiveScene 성공 증거로 사용하지 않는다.

GPU 동시 사용을 막기 위해 queued/running job이 0개임을 확인한 뒤 운영 `gpu.toml`의 `backend.name`을 `not_configured`로 설정하고 API를 재시작했다. API의 인증·업로드·조회 구조는 유지되며, 신규 3DGS 작업 접수는 503, backend 상태는 degraded이다. 이는 LiveScene API 연동 완료를 의미하지 않는다.

2026-09-21 14:31 KST, 사용자 승인 범위인 B0/B1/O1/O2 결과 33개 항목 **17,188,388,179 bytes(16.01GiB)**를 Linux 휴지통으로 이동했다. 영구 삭제가 아니므로 복구 가능하며 디스크 공간이 확보된 것은 아니다. 해당 job은 기존 계약에 맞춰 `failed / artifacts_removed`, 빈 artifacts로 기록했다. 원래 요청·ID·created_at은 보존하고 updated_at은 갱신했다. 삭제된 artifact 다운로드는 404 대상이다. 원본 capture·processed/COLMAP 등 보존 대상 417개 파일의 전후 SHA-256이 일치했다. 세부 대상과 원래 job 상태·복구 위치는 [정리 목록](splatfacto-retirement-inventory.json) 및 런타임 `verification/splatfacto-retirement-5jk0dpa7/receipt.json`에 있다. 이 정리는 최종 LiveScene 품질 합격 판정이 아니다.

14:35 KST 실제 Tailscale HTTPS 재검증: TLS 확인, 무토큰 401, health `degraded/not_configured`, 4개 job `failed/artifacts_removed`, 기존 artifact 404, capture `ready`, 신규 job 503 및 DB 행 미생성을 확인했다. 증거는 같은 영수증 디렉터리의 `api-verification.json`이다.

## 고정 소스와 저장 위치

| 항목 | 값 |
|---|---|
| LiveScene 원본 | [Tavish9/livescene](https://github.com/Tavish9/livescene), commit `5a44fcd3b6248155aa2fe84f3ea58b7d31140700` |
| tiny-cuda-nn | [NVlabs/tiny-cuda-nn](https://github.com/NVlabs/tiny-cuda-nn), v1.6 commit `8e6e242f36dd197134c9b9275a8e5108a8e3af78` |
| 런타임 루트 | `/home/<gpu-user>/.local/share/habitat-gpu/livescene` |
| LiveScene 소스 | 런타임 루트의 `source/` |
| tiny-cuda-nn 소스 / wheel | 런타임 루트의 `tiny-cuda-nn/`, `wheels/` |
| 별도 Python 환경 | `/home/<gpu-user>/.venvs/habitat-livescene` |
| 빌드에 사용한 기존 GPU Python | `/home/<gpu-user>/.venvs/habitat-gpu/bin/python` |
| 실행 결과 | 런타임 루트의 `runs/door-XXXXXXXX/` |

기본 패키지는 [requirements-gpu.lock](../../requirements-gpu.lock)의 Python 3.10 / PyTorch `2.1.2+cu118` / torchvision `0.16.2+cu118` / Nerfstudio `1.1.5` / NumPy `1.26.4` 조합을 새 환경에 복제했다. 느린 약 2.2 GiB 재다운로드를 피하기 위해 기존 `site-packages`를 `cp -a --reflink=auto`로 복사하고, 새 환경에 Nerfstudio `1.1.5`를 오프라인 재설치하여 실행 파일을 등록했다. Torch CUDA 공유 라이브러리의 기존/새 파일 inode가 서로 다름을 확인했으며, 기존 환경과 하드링크로 같은 파일을 공유하는 방식이 아니다. 기존 환경의 패키지를 변경하지 않았다.

기본 고정 목록은 유지했으며, 별도 LiveScene 환경에서 실제 tiny-cuda-nn CUDA forward/backward 검사를 통과했다. 이는 학습 전체 또는 시각 품질 검증과는 별개다. CUDA toolkit은 `/usr/local/cuda-11.8`, GPU는 RTX 4060 8 GB이다.

## 공식 입력과 출처

원본은 [IPEC-COMMUNITY/LiveScene](https://huggingface.co/datasets/IPEC-COMMUNITY/LiveScene)의 InterReal 문 장면이다. 데이터 revision은 `add647e5af15b6a6e9ded1b94927eb1f5b8e0802`로 고정했다.

| 항목 | 검증 기록 |
|---|---|
| 원본 압축 파일 | [InterReal/seq003_door.tar.gz](https://huggingface.co/datasets/IPEC-COMMUNITY/LiveScene/resolve/add647e5af15b6a6e9ded1b94927eb1f5b8e0802/InterReal/seq003_door.tar.gz) |
| 압축 파일 크기 | 37,028,990 bytes |
| 압축 파일 SHA-256 | `14a1e8289aa6e81185fe4f9037044d96c903b8c937e93bb2017ac283e16b2510` |
| 압축 해제 파일 총크기 | 556,958,376 bytes |
| RGB / 카메라 pose | 355개, 원본 RGB 994×738, 유효한 4×4 변환 및 양의 초점거리 |
| 객체 mask | 355개, 각 `[738, 994, 2]`, door / background 이진 채널 |
| 객체 및 상태 | `mapping.yaml`의 객체 0 = `door`; `key_frame_value.yaml`의 원본 keyframe 31개, 상태값 -1 / 0 / 1 |
| 상태 확인 | frame 00001 (-1): 닫힌 문, frame 00355 (+1): 열린 문. 파서는 상태값을 [0, 1]로 정규화한다. |

압축 파일과 상세 출처 기록은 런타임의 `datasets/InterReal/seq003_door.tar.gz`, `datasets/InterReal/seq003_door.PROVENANCE.md`에 보관했다. 압축 파일 SHA-256은 Hugging Face LFS 해시와 대조했다. 압축 해제 전에 경로 이탈, 절대 경로, 링크 및 특수 파일을 검사했으며, 원본 RGB·mask·pose·상태값은 수정하지 않았다.

입력 디렉터리는 `/home/<gpu-user>/.local/share/habitat-gpu/livescene/datasets/InterReal/seq003_door`이다. 이 공식 압축 파일에는 depth 디렉터리가 없으며, 실제 파서는 RGB, `transforms.json`, `masks/*.npy`, `mapping.yaml`, `key_frame_value.yaml`을 사용한다. 일반 사진만 제출하는 기존 API 입력으로 이 장면의 학습 요구사항을 충족했다고 볼 수 없다.

실제 `LiveSceneRealDataParserConfig(downscale_factor=1)` CPU 실행도 통과했다. train 320장/상태 라벨 27개, val 35장/상태 라벨 4개이며, 두 split 모두 정규화된 상태값과 camera-to-world 행렬이 유한하다. mask의 높이·너비가 해당 camera의 738×994와 일치함을 assert로 확인했다.

## 호환성 패치와 설치 상태

[livescene-compatibility.patch](../../scripts/patches/livescene-compatibility.patch)는 위 LiveScene commit에 적용하는 일반 Git 패치다. 별도 모델로 교체하지 않는다.

- `train_with_lang=False`에서는 CLIP/OpenCLIP을 import하거나 생성하지 않고, 사용하지 않는 전체 train/eval 이미지 tensor도 만들지 않는다.
- CLIP을 생성하지 않는 경로에 기존 기본값인 512차원 설정을 제공한다.
- keyframe label이나 유효한 객체 쌍이 없는 batch의 MSE·repulsion·cross entropy·Huber 손실을 미분 가능한 0으로 처리한다. 비어 있지 않은 입력의 원래 수식은 유지한다.

패치 역적용 검사와 [CPU 회귀 검사 스크립트](../../tests/hardware/check_livescene_compatibility.py)의 실제 실행을 통과했다. CLIP import·다운로드 없이 슬라이더 경로를 구성하고, 비어 있는 손실과 비어 있지 않은 손실의 유한값 및 backward를 확인한다. `ns-train livescene --help`도 통과했다. 기본 패키지 복제 전의 최초 시도에서 발생했던 `ModuleNotFoundError: torch`는 현재 설치 상태의 오류가 아니다.

실제 추가 설치 버전은 `rasterio==1.4.3`, `omegaconf==2.3.0`, `affine==3.0.1`, `antlr4-python3-runtime==4.9.3`, `click-plugins==1.1.1.2`, `cligj==0.7.2`이다. LiveScene은 `--no-deps --no-build-isolation -e`로 새 환경에 등록했다. 이번 슬라이더 샘플에는 CLIP/OpenCLIP을 설치하지 않았다. upstream 의존성 선언에는 CLIP이 있으므로 설치 후 `pip check`만으로 선택적 CLIP 비활성 경로의 정상 작동을 판단하지 않고, 실제 회귀 검사와 학습 결과를 확인한다.

tiny-cuda-nn v1.6은 기존 C++14 바인딩 설정 때문에 PyTorch 2.1의 C++17 요구사항을 충족하지 못했다. [tinycudann-torch21.patch](../../scripts/patches/tinycudann-torch21.patch)로 `bindings/torch/setup.py`의 C++ 컴파일 옵션 한 줄을 C++17로 변경했고, 패치 역적용 검사를 통과했다. 이후 `cusparse.h` 부재를 해결하기 위해 `libcusparse-dev-11-8`, `libcublas-dev-11-8`, `libcusolver-dev-11-8` 및 해당 런타임 의존성을 포함한 총 6개 패키지 설치를 완료했다. 패키지 안내 기준 다운로드 약 837 MB, 추가 디스크 약 3.2 GB이며 Linux NVIDIA 드라이버는 설치하지 않았다.

모든 컴파일을 통과한 뒤 linker가 `-lcuda`를 찾지 못하는 문제는 `LIBRARY_PATH=/usr/lib/wsl/lib`로 WSL 드라이버 라이브러리 검색 경로를 지정하여 해결했다. 동일한 Torch/CUDA 조합을 가진 기존 GPU Python의 `pip wheel --no-deps --no-build-isolation`로 빌드했으며, 기존 환경에는 설치하지 않고 새 LiveScene 환경에만 설치했다.

| 빌드 결과 | 값 |
|---|---|
| wheel | `wheels/tinycudann-1.6-cp310-cp310-linux_x86_64.whl` |
| 크기 | 27,859,386 bytes |
| SHA-256 | `d91bf40206d51a66cca318f70feffeb9f159265ab06c92bb09b691bca2e5c5db` |
| 실제 GPU 검사 | `FullyFusedMLP` CUDA forward/backward 유한값 검사 통과 |

기존 서비스·backend 회귀 검사는 중복을 제외한 68개가 통과했다. 통합 23개, API 단위 34개, COLMAP 5개, Splatfacto 8개 실행 중 2개가 중복이며 API 단위 검사에는 별도로 11개 skip이 있었다. 이는 기존 코드의 회귀 결과이며 LiveScene 샘플 학습 완료나 품질 합격을 의미하지 않는다.

## 재현 순서

아래 명령은 WSL Ubuntu에서 저장소 루트를 작업 디렉터리로 사용한다. 현재 준비된 경로를 재사용하며, 완료된 설치나 패치를 다시 적용할 필요는 없다. 환경 설치 성공과 샘플 학습 완료·품질 합격은 각각 별도로 확인한다.

```bash
cd '/mnt/c/Users/<user>/Desktop/HabitatOS'
sample_runtime=/home/<gpu-user>/.local/share/habitat-gpu/livescene
sample_env=/home/<gpu-user>/.venvs/habitat-livescene
uv_cmd=/home/<gpu-user>/.local/bin/uv

# 새 설치에서만 실행. 기존 GPU 환경의 Python 버전을 사용한다.
"$uv_cmd" venv --python /home/<gpu-user>/.venvs/habitat-gpu/bin/python "$sample_env"
cp -a --reflink=auto /home/<gpu-user>/.venvs/habitat-gpu/lib/python3.10/site-packages/. \
  "$sample_env/lib/python3.10/site-packages/"
"$uv_cmd" pip install --python "$sample_env/bin/python" --reinstall --no-deps --offline nerfstudio==1.1.5

# 실제 설치한 추가 패키지와 버전.
"$uv_cmd" pip install --python "$sample_env/bin/python" \
  'rasterio==1.4.3' 'omegaconf==2.3.0' 'affine==3.0.1' \
  'antlr4-python3-runtime==4.9.3' 'click-plugins==1.1.1.2' 'cligj==0.7.2'
```

이 복제 경로는 이미 고정 목록대로 설치된 기존 GPU 환경과 로컬 Nerfstudio wheel 캐시를 전제로 한다. 기존 환경이 없는 새 시스템에서는 기본 패키지를 `uv pip install --python "$sample_env/bin/python" --no-deps -r requirements-gpu.lock --extra-index-url https://download.pytorch.org/whl/cu118 --index-strategy unsafe-best-match`로 준비할 수 있다. 현재 작업에서 완료한 경로는 위의 환경 복제 방식이다.

2026-10-03 정리에서 설치 다운로드·wheel 캐시와 미사용 중간 체크포인트를 제거했다. 설치된 환경과 등록 모델은 보존되어 현재 서비스는 그대로 실행된다. 위 설치 기록의 `--offline` 명령은 캐시가 있는 경우에만 사용할 수 있으며, 새 설치에는 패키지 재다운로드와 CUDA 확장 재빌드가 필요할 수 있다.

새 소스 checkout을 준비할 때는 LiveScene을 위 commit에 고정하고, tiny-cuda-nn을 위 v1.6 commit에 고정한 뒤 `git submodule update --init --recursive`로 그 commit의 하위 저장소를 준비한다. 기존 checkout의 고정값과 패치 적용 여부는 다음과 같이 확인한다.

```bash
git -C "$sample_runtime/source" rev-parse HEAD
git -C "$sample_runtime/tiny-cuda-nn" rev-parse HEAD

# 패치 전 원본 checkout에서만 적용한다.
git -C "$sample_runtime/source" apply --check "$PWD/scripts/patches/livescene-compatibility.patch"
git -C "$sample_runtime/source" apply "$PWD/scripts/patches/livescene-compatibility.patch"
git -C "$sample_runtime/tiny-cuda-nn" apply --check "$PWD/scripts/patches/tinycudann-torch21.patch"
git -C "$sample_runtime/tiny-cuda-nn" apply "$PWD/scripts/patches/tinycudann-torch21.patch"

# 이미 적용된 checkout은 대신 --check --reverse로 확인한다.
```

성공한 tiny-cuda-nn 빌드·설치 및 CPU 회귀 검사 명령은 다음과 같다. 패치 적용과 CUDA 개발 패키지 설치가 선행되어야 한다.

```bash
sudo apt-get install -y --no-install-recommends \
  libcusparse-dev-11-8 libcublas-dev-11-8 libcusolver-dev-11-8
env CUDA_HOME=/usr/local/cuda-11.8 LIBRARY_PATH=/usr/lib/wsl/lib \
  PATH=/home/<gpu-user>/.venvs/habitat-gpu/bin:/usr/local/cuda-11.8/bin:/usr/bin:/bin \
  CC=gcc-11 CXX=g++-11 MAX_JOBS=2 TCNN_CUDA_ARCHITECTURES=89 \
  /home/<gpu-user>/.venvs/habitat-gpu/bin/python -m pip wheel --no-deps --no-build-isolation \
  "$sample_runtime/tiny-cuda-nn/bindings/torch" --wheel-dir "$sample_runtime/wheels"

# 빌드 성공 뒤 생성된 tinycudann wheel을 새 환경에만 설치한다.
"$uv_cmd" pip install --python "$sample_env/bin/python" --no-deps \
  "$sample_runtime"/wheels/tinycudann-*.whl
"$uv_cmd" pip install --python "$sample_env/bin/python" --no-deps --no-build-isolation -e "$sample_runtime/source"
"$sample_env/bin/python" tests/hardware/check_livescene_compatibility.py
```

## 완료한 smoke test와 현재 본학습

다음 두 systemd user unit은 `inactive`, `Result=success`, `ExecMainStatus=0`으로 정상 종료했다. 두 실행 모두 `step-000000099.ckpt`를 저장했고, checkpoint의 모델 tensor 및 기록된 TensorBoard scalar가 유한함을 확인했다. 시간은 TensorBoard의 `Train Total (time)`이며 환경 초기화·후속 렌더 시간은 제외한다. 메모리는 PyTorch가 보고한 최대 할당량으로 Windows·CUDA 캐시를 포함한 전체 GPU 사용량과 다르다.

| 실행 디렉터리 / unit | Train rays | 100회 학습 시간 | 최대 할당량 | 마지막 기록 train PSNR / loss (step 90) |
|---|---:|---:|---:|---:|
| `door-KAgIWJdc` / `habitat-livescene-smoke` | 512 | 13.81초 | 1,348.88 MiB | 14.429 / 0.06751 |
| `door-7W3ZjQ2k` / `habitat-livescene-batch4096` | 4,096 | 27.31초 | 3,300.36 MiB | 14.597 / 0.06578 |

512 rays 실행은 [render_livescene_sample.py](../../scripts/render_livescene_sample.py)로 checkpoint를 다시 로드하여 고정 held-out view와 슬라이더 상태 0 / 0.25 / 0.5 / 0.75 / 1을 렌더했다. 결과는 `runs/door-KAgIWJdc/render-smoke/`의 PNG·GIF·`result.json`에 있다. `frame_00011.jpg` 한 장을 절반 해상도 497×369로 평가한 값은 PSNR **14.047**, SSIM **0.72897**, LPIPS **0.68091**이다. 전체 데이터셋 평가가 아니며, 영상은 아직 흐리다. 상태 0↔1의 평균 RGB 차이도 `2.492e-5`로 매우 작아 **의미 있는 문 열림·닫힘 검증에는 아직 부족하다**. 렌더 실행 시간은 28.65초였다.

해당 렌더의 config SHA-256은 `566b6f1834c44f8a392abfdc271a00201cdd1161ea0742069cb33f662a1eb055`, checkpoint SHA-256은 `6ae0d34b7bca83ceb8c751d97760b5ba650f0e7d546bc89377ebdaeee5bd294f`이다. 후속 학습 성능으로 이 smoke 수치를 덮어쓰지 않는다.

본학습은 **2026-09-21 14:17 KST**에 systemd user unit `habitat-livescene-train.service`로 시작했다. 실행 루트는 `/home/<gpu-user>/.local/share/habitat-gpu/livescene/runs/door-nFDV3fA5`, 설정은 그 아래 `habitat-door/livescene/run/config.yml`이다. **14:25:42 KST 확인 시 active, step 1,945 / 목표 30,001회**였으며 다음은 중간값이다.

- train step 1,940: PSNR 19.447, loss 0.01900; eval batch step 1,500: PSNR 17.452.
- 최대 PyTorch 할당량 3,326.03 MiB, 기록된 scalar 모두 유한, `step-000001000.ckpt` 저장 확인.
- 당시 step당 약 0.262초, 표시된 남은 시간 약 2시간 3분. 평가·viewer 사용에 따라 바뀌는 추정치이며 완료 약속이 아니다.

추가로 **step 3,000의 native eval-image**가 완료됐다. 원본 994×738 해상도의 held-out 이미지 1장에 대해 PSNR **19.9541**, SSIM **0.79653**, LPIPS **0.38487**이다. 전체 35장 평균이 아니며, 100회 smoke의 고정 이미지·절반 해상도 지표와 직접적인 paired 비교를 하지 않는다. TensorBoard 원본 좌GT/우복원 이미지를 `runs/door-nFDV3fA5/native-eval-step3000/ground-truth-and-prediction.png`로 추출하고 해당 지표를 `result.json`에 기록했다. 직접 확인한 결과 문·방의 대략적인 윤곽은 보이지만 문틈·손잡이·책상 물체와 벽 세부 표현은 크게 흐리다. **중간 품질은 합격이 아니며 본학습을 계속한다.**

14:36:42 KST 추가 확인: step **4,690**, 1k/2k/3k/4k checkpoint 저장, 기록된 scalar 모두 유한했다. 당시 남은 시간 추정은 약 97분이었다. 소스 commit, 설치 패키지 버전, dataset archive·호환성 패치·launcher·config의 SHA-256은 실행 루트 `provenance.json`에 기록했다. 최종 결과는 학습 성공 후 생성할 `render-final/result.json`에서 별도로 확인한다.

## 2026-09-21 실행과 viewer 기록 (과거)

아래는 당시 학습·viewer 설치 기록이다. 이 절의 “현재 학습 중”, “구현하지 않았다”, “실행 전”은 2026-09-21 당시 상태를 뜻한다. 본학습은 이후 종료되었으며, 현재 0.4.5의 Pi 객체 선택·장치 제어 화면과 남은 제한은 문서 상단에 기록했다. 아래의 과거 상태를 현재 운영 상태로 해석하지 않는다.

[run_livescene_sample.sh](../../scripts/run_livescene_sample.sh)는 공식 `ns-train livescene`을 직접 실행하고 매번 별도 `runs/door-XXXXXXXX/`와 `training.log`를 만든다. **현재 본학습이 실행 중이므로 아래 명령으로 두 번째 GPU 학습을 동시에 시작하지 않는다.** 새 실행이 필요할 때만 사용한다.

```bash
# 현재 실행 상태 / 로그 확인
systemctl --user status habitat-livescene-train --no-pager
journalctl --user -u habitat-livescene-train -n 30 --no-pager

# 기존 학습이 종료된 뒤 새 실행이 필요할 때만 선택하여 실행
HABITAT_LIVESCENE_RAYS=512 bash scripts/run_livescene_sample.sh 100
bash scripts/run_livescene_sample.sh 100   # 기본 4,096 rays smoke
bash scripts/run_livescene_sample.sh       # 기본 30,001회, 새 디렉터리
```

기본 설정은 seed 42, **train 4,096 / eval 512 rays**, model/viewer chunk 2,048 rays, checkpoint 저장 주기 1,000회 및 이전 checkpoint 보존이다. 전체 eval-image 순회는 비활성화하며, 평가 batch는 500회, 평가 image는 3,000회 간격이다. `HABITAT_LIVESCENE_RAYS`로 train rays만 1~4,096 사이에서 지정할 수 있다.

`--pipeline.use-gt-val False`는 희소한 keyframe 상태값으로부터 나머지 상태를 학습하도록 한다. `--pipeline.train-with-lang False`는 객체 슬라이더를 사용하는 설정이며, 자연어 문장에 의한 제어 기능은 포함하지 않는다. CLIP 의존성 생략도 이 조건에 한정된다.

`livescene-real-data --downscale-factor 1`은 원본 RGB와 mask의 994×738 좌표를 맞추기 위해 필요하다. 입력 이미지에만 축소 옵션을 적용하면 원본 파서의 mask 좌표와 어긋난다. 메모리 조정은 우선 rays/chunk 수로 수행한다.

학습 중 viewer 주소는 **http://127.0.0.1:7007**이며 loopback에만 바인딩한다. 공개 API나 Tailscale 공개 포트는 변경하지 않았다. [브라우저 검사](../../tests/hardware/check_livescene_viewer.mjs)로 Windows의 별도 임시 Edge 세션에서 실제 sample camera를 선택하고 `Hide Train Cams`로 윤곽선을 숨겨 512×452 렌더를 확인했다. `controller → attribute_0`를 0→1로 조절해 화면 갱신을 확인한 뒤 0·카메라 표시를 복구하고 검사 브라우저를 종료했다. 사용 중인 사용자 브라우저 설정은 변경하지 않았다.

증거는 런타임의 `browser-slider-verified/report.json`, `slider-0.png`, `slider-1.png`이다. 약 2.4k~2.8k 학습 중 촬영한 두 화면은 다르지만 **아직 흐리며, 동시에 학습도 계속되어 두 이미지의 차이를 순수한 상태 변화량이나 품질 점수로 해석할 수 없다**. 모델이 고정된 최종 checkpoint의 상태 렌더는 후속 자동 평가로 남긴다.

검사 중 Three.js bounding-sphere NaN 메시지 2건은 숨기지 않고 기록했다. 실제 오류 객체는 instanceCount=0, position itemSize=2, count=4, 좌표값 8개가 모두 유한한 Viser의 빈 Gaussian 화면용 quad였다. LiveScene 카메라/장면 좌표의 NaN을 검출한 결과가 아니다. 이 정확한 메시지·객체 조합만 알려진 진단으로 분리하며 다른 console error와 예외는 검사 실패로 처리한다. 검사 전용 브라우저의 WebGL은 SwiftShader로 실행해 학습 GPU와의 충돌을 피했다. 이는 모델 CUDA 학습/렌더를 CPU로 바꾸는 설정이 아니다.

환경과 런타임 경로를 바꿀 때는 launcher의 `HABITAT_LIVESCENE_ENV`, `HABITAT_LIVESCENE_RUNTIME`을 사용한다.

launcher의 `quit_on_train_completion=True`에 따라 학습용 viewer는 종료된다. 현재 systemd 연결은 **학습 정상 종료 → `habitat-livescene-render.service` → `habitat-livescene-viewer.service`**이다. 렌더 unit은 최종 checkpoint의 held-out view·문 상태를 새 `render-final/`에 저장한 뒤 종료하며 상한은 600초다. 렌더 성공·실패 모두 이후 native `ns-viewer`를 같은 주소에서 시작하므로, viewer가 떴다고 평가까지 성공한 것은 아니다. 세 단계는 GPU에서 순차 실행한다.

render/viewer unit은 `~/.config/systemd/user/`에 있으며, 현재 학습의 `OnSuccess=habitat-livescene-render.service` 설정은 `/run/user/1000/systemd/user/habitat-livescene-train.service.d/10-viewer.conf`에 있다. 후자는 재부팅 시 사라지며 자동 학습 재개를 구현한 것이 아니다. 학습 unit의 실행 상한은 4시간이다. 이 연결은 설치·설정 검증을 마쳤지만 최종 checkpoint의 렌더·품질 검증은 아직 실행 전이다.

학습 완료 후 viewer 상태 확인 및 수동 재시작은 다음과 같다. **학습이 아직 실행 중이면 viewer를 별도로 시작하지 않는다**(같은 GPU와 7007 포트를 사용한다). Windows 재부팅 후에는 WSL Ubuntu를 먼저 시작하고, 저장된 checkpoint가 있는 이 실행의 viewer만 아래 명령으로 다시 켤 수 있다. viewer unit은 부팅 자동 시작으로 enable하지 않았다.

```bash
systemctl --user status habitat-livescene-viewer --no-pager
systemctl --user restart habitat-livescene-viewer
# 평가 성공 여부는 viewer와 별개로 확인
systemctl --user status habitat-livescene-render --no-pager
journalctl --user -u habitat-livescene-render -n 30 --no-pager
```

별도 렌더 검사 역시 본학습·자동 렌더·viewer와 동시 실행하지 않는다. 자동 평가 외에 추가 검사가 필요하다면 viewer를 정지한 뒤 아래처럼 **새 출력 디렉터리**를 지정한다. 기존 출력 디렉터리는 덮어쓰지 않는다.

```bash
systemctl --user stop habitat-livescene-viewer
"$sample_env/bin/python" scripts/render_livescene_sample.py \
  "$sample_runtime/runs/door-nFDV3fA5/habitat-door/livescene/run/config.yml" \
  "$sample_runtime/runs/door-nFDV3fA5/render-manual-01"
systemctl --user start habitat-livescene-viewer
```

학습 산출물은 Nerfstudio `config.yml`, `nerfstudio_models/step-*.ckpt`, 학습 로그와 TensorBoard 기록이다. LiveScene은 방사장 모델이므로 이번 경로의 산출물 계약은 Gaussian PLY가 아니다. 기존 `ns-export gaussian-splat`을 그대로 사용할 수 없다.

실제 Pi·문 모터·센서·로봇 제어는 구현하지 않았다. 학습한 장면의 문 상태 렌더링, 원본 관측과의 일치, 자연어 제어, 실제 물리 장치 제어는 각각 별도 항목이다. 이 355장 문 샘플과 기존 38장 장면은 다른 입력이므로, 샘플 학습 성공만으로 기존 reconstruction noise 해결이나 Splatfacto 대비 속도 우위를 주장하지 않는다. 본학습 완료 뒤 최종 checkpoint·종료 상태·실측 시간 및 고정 카메라에서의 문 상태 시각 검증을 추가해야 한다.
