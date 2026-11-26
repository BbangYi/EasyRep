# Connect a new store's Raspberry Pi

This setup keeps the Pi connected to HabitatOS without sensors. It sends connection heartbeats only. Sensor installation is a separate step.

## Before starting

1. Connect the Pi to power and Wi-Fi or Ethernet, and sign in as its normal user.
2. On the website, register this store, this Pi, and at least one cage. Keep the **Store ID, Pi/Gateway ID, Cage IDs, and the token issued for this Pi** ready. Each Pi needs its own registration and token.
3. Obtain the HabitatOS release package for this Pi's OS/Python version from your administrator. The current package is for **64-bit ARM (aarch64), Python 3.13**. Python venv support and systemd must be installed. Use the administrator-provided checksum to verify the download.

The token alone does not contain all setup details. The current website API requires the registered IDs too; this program does not create website accounts or register devices automatically.

## Run setup

Extract the release package. Open a terminal in the extracted folder and run:

```bash
bash connect.sh
```

Do not run the entire setup with `sudo`. It will ask for:

- Store ID, exactly as registered on the website.
- Pi/Gateway ID for this device.
- Cage IDs, separated by commas if there are several.
- SaaS sync URL. Press Enter to use the supplied HabitatOS default.
- This Pi's token. **Pasting the token displays no characters; press Enter afterward.**

Setup checks the website's acknowledgment before saving the token. It then saves private credentials, installs the shared program release, and enables connection after reboot and logout. Raspberry Pi OS may request administrator authentication to enable startup after logout. Enter that OS password only in its local prompt.

When it displays **CONNECTED**, the background service has also received a valid acknowledgment. Open the website and check that the Pi is online. Sensor readings will remain unavailable. The program uses inactive example inventory with `UNASSIGNED-*` node names until an engineer configures the real hardware.

## After setup

Keep the Pi powered and connected to the internet. It sends a heartbeat about every five seconds and retries connection failures. It automatically starts again after the Pi boots. While powered off, it cannot communicate and the website will mark it offline.

Check the service:

```bash
systemctl --user status habitat-heartbeat --no-pager
```

Recent connection results:

```bash
journalctl --user-unit=habitat-heartbeat.service -n 20 --no-pager
```

The token is in `~/.config/habitatos/gateway.env`, outside the program folder, with owner-only file permissions (`0600`). It is never a command-line argument or included in the release package.

If the token or IDs are rejected, correct them on the website and run setup again. If setup says it is saved but the background acknowledgment is unconfirmed, the service is already installed and retrying; inspect the log command above instead of creating another registration.

Running setup on an already configured Pi stops without replacing its settings or token. For upgrades or token rotation, use the existing installation workflow with your administrator. Before installing real sensors, stop the heartbeat-only service and have an engineer configure the actual sensor/controller mapping and local safety controls.

## 매장별 센서·TOP/FRONT 카메라 배포 (0.4.20)

매장 Pi는 동일한 versioned release를 사용한다. 매장과 사육장마다 소스를 복사하지
않고 외부 `gateway.toml`의 `site_id`, `gateway_id`, `cages`, `cameras`를 구성한다.
센서는 기존 ESP32 Cage Node와 MQTT 계약을 사용하고, DFR1172 카메라는 각각
Wi-Fi에서 HTTP MJPEG를 송출한다. Pi의 기존 카메라 worker가 카메라당 입력을
하나만 열어 미리보기·HLS·선택적 녹화에 공유한다. SaaS가 없어도 Pi의 `/camera`
화면에서 사육장을 선택해 TOP과 FRONT를 동시에 볼 수 있다.

기존 USB 설정은 `source_type` 생략 시 `uvc`로 유지된다. 새 네트워크 카메라는
`source_type="http_mjpeg"`, `view="top"` 또는 `"front"`, 실제 LAN
`url="http://카메라IP:5000/video_feed"`를 사용한다. 같은 URL을 여러 카메라에
등록하거나 한 사육장에 같은 view를 두 번 지정하면 검증에서 거부한다.
URL을 생략한 카메라는 `waiting_network_camera_binding`으로 대기하며 가상
영상을 만들지 않는다. 현재 설정 상한은 매장당 16대이며 예제에는 사육장 3개,
각각 두 대의 카메라가 있다. `width`/`height`는 실제 수신 영상으로 확인해 맞춘다.

### DFR1172 카메라 보드에 공통 프로그램 설치

TOP 한 대부터 Pi의 데이터 USB 케이블을 DFR1172 **USB CDC** 포트에 연결한다.
전원을 분리한 상태에서 CSI 리본을 장착한다. 실행 중인 BB6의 CP2102 포트는
카메라 설치 대상이 아니다. 연결 전후 장치 목록을 비교해 P4의 포트를 지정하며,
Thonny 등 같은 포트를 사용하는 프로그램은 닫는다. 아래의 `P4_PORT`는 확인한
실제 포트로 바꾼다. 자동 포트 선택은 사용하지 않는다.

설치 도구 `esptool`과 `mpremote`는 Gateway 실행 환경과 분리한 운영용 Python
환경에 준비한다. 아래 예시는 esptool 5의 명령 표기를 사용한다.

```bash
mpremote connect list
P4_PORT='/dev/serial/by-id/실제로_확인한_P4_장치'
P4_FIRMWARE='/home/<gateway-user>/HabitatOS_DFR1172_First_Connection_R1/firmware/DFRobot_ESP32P4_MicroPython.bin'
esptool --chip esp32p4 --port "$P4_PORT" chip-id
esptool --chip esp32p4 image-info "$P4_FIRMWARE"
```

다운로드 모드가 필요하면 BOOT를 누른 상태로 RST를 눌렀다 놓고 BOOT를 놓는다.
감지된 칩이 ESP32-P4인지 확인한다. 이 패키지 이미지의 지원 revision은
**0.1~1.99**이며 실제 칩 revision이 범위 밖이면 기록하지 않는다. 불일치를
`--force`로 우회하지 않는다. 기록 주소 **0x2000**은 이 DFRobot P4 이미지의
지정값이다. [DFRobot 펌웨어 설치](https://wiki.dfrobot.com/tutorial/22586),
[esptool 명령](https://docs.espressif.com/projects/esptool/en/latest/esp32p4/esptool/basic-commands.html).

소스 외부의 비공개 JSON 파일을 편집기로 준비한다. 내용은 `wifi_ssid`와
`wifi_password` 두 문자열 필드이며, Pi와 통신 가능한 2.4 GHz Wi-Fi를 사용한다.
파일은 생성할 때부터 `0600`, 상위 디렉터리는 `0700`으로 두고 비밀번호를
명령 인자나 셸 기록에 넣지 않는다. 다음의 매장·Gateway ID는 현재 설정의
실제 값으로 지정하고, 출력 폴더는 아직 없는 경로를 사용한다.

```bash
NODE_DIR='/home/<gateway-user>/.config/habitatos/camera-nodes/CAGE-001-TOP'
/opt/habitat-gateway/current/venv/bin/python \
  /opt/habitat-gateway/current/camera_node.py \
  --package /home/<gateway-user>/HabitatOS_DFR1172_First_Connection_R1 \
  --wifi-file /home/<gateway-user>/.config/habitatos/camera-wifi.json \
  --output "$NODE_DIR" \
  --site-id "$SITE_ID" --gateway-id "$GATEWAY_ID" \
  --cage-id CAGE-001 --camera-id CAGE-001-TOP --view top
```

준비 도구는 외부 펌웨어의 크기와 SHA-256 및 검토한 패키지의 Microdot 해시를
검증하고 `main.py`, `microdot.py`, `config.json`을 비공개 파일로 만든다.
모든 카메라는 같은 `main.py`를 사용하며 사육장·위치·Wi-Fi 차이는
`config.json`에만 둔다. 준비 명령은 보드 기록이나 전체 삭제를 수행하지 않는다.
소스에서 실행할 때는 같은 도구인 `deploy/camera_node.py`를 사용한다.

USB 전원을 사용하는 실시간 카메라는 공통 프로그램이 Wi-Fi 절전을
`PM_NONE`으로 해제한다. 실물 시험에서 센서 캡처는 빨라도 절전 상태에서는
HTTP 프레임 전송이 크게 지연될 수 있었다. 적용 결과는 `CAMERA_WIFI pm=...`
로그로 확인한다. 해당 API가 지원되지 않으면 인증정보나 예외 내용을 노출하지
않고 `CAMERA_WIFI pm_unavailable`만 남긴 뒤 접속을 계속한다. 이 경우 실제
프레임 수신 속도를 별도로 확인한다.

위 검사에 성공한 초기 설치 보드에 다음을 실행한다. 펌웨어 기록은 대상 보드의
기존 프로그램을 교체한다. 기록 후 같은 포트에서 전체 이미지를 재검증하고
watchdog reset으로 부팅한다. 초기 RTS 재설정만으로 REPL에 진입하지 못했던
보드에서 아래 검증·재설정 경로를 확인했다. 첫 부팅은 VFS 파일시스템 준비가
끝날 때까지 기다린다. 빈 직렬 응답만으로 즉시 재기록하지 않는다. 필요하면
RST 또는 전원 재연결 후 부팅 로그를 확인한다. USB 장치 경로가 달라졌으면
`mpremote connect list`로 다시 확인해 `P4_PORT`를 갱신한다.

```bash
esptool --chip esp32p4 --port "$P4_PORT" --after no-reset write-flash 0x2000 "$P4_FIRMWARE"
esptool --chip esp32p4 --port "$P4_PORT" --before no-reset --after watchdog-reset verify-flash 0x2000 "$P4_FIRMWARE"
mpremote connect "$P4_PORT" fs cp "$NODE_DIR/microdot.py" :microdot.py
mpremote connect "$P4_PORT" fs cp "$NODE_DIR/config.json" :config.json
mpremote connect "$P4_PORT" fs cp "$NODE_DIR/main.py" :main.py
mpremote connect "$P4_PORT" reset
mpremote connect "$P4_PORT" repl
```

직렬 출력의 `CAMERA_READY`에서 IP와 camera ID/view를 확인한다. 로그에 Wi-Fi
인증정보는 출력하지 않는다. 직렬 모니터는 Ctrl-]로 종료한다.
USB 직렬 포트를 다시 여는 동작이 보드를 재설정할 수 있으므로 HTTP 영상의
연속 수신·성능 시험 중에는 Thonny나 `mpremote`를 새로 연결하지 않는다.
[공식 카메라 송출 예제](https://wiki.dfrobot.com/dfr1172/docs/22908),
[mpremote 파일 복사·포트 지정](https://docs.micropython.org/en/latest/reference/mpremote.html).

**Pi 영상 수신을 시작하기 전에** 다음으로 응답의 매장·Gateway·사육장·카메라
ID와 `view`를 대조한다. 제공된 Microdot은 MicroPython에서 동기식이므로
`/video_feed` 수신 중에는 `/identity` 응답이 대기할 수 있다.

```bash
curl --fail --max-time 5 "http://${TOP_IP}:5000/identity"
```

FRONT에도 출력 폴더·camera ID를 `CAGE-001-FRONT`, `--view front`로 바꿔
반복하고 FRONT의 `/identity`도 먼저 확인한다. 카메라를 직접 보는 브라우저는
닫은 뒤 아래의 등록 명령으로 Pi만 각 스트림을 한 번씩 열도록 한다.
`/identity` 성공은 영상 검증을 대신하지 않는다. 실제 프레임 갱신, 전원 재연결,
동작 중 Wi-Fi 단절 후 복구는 실물로 검증해야 한다.

2026-11-07 현장에서는 ESP32-P4 revision 1.3 두 대의 공식 펌웨어 기록을
검증했고 실제 Wi-Fi 영상 수신 시험을 진행하고 있다. 설치·단일 수신 성공과
두 영상의 지속 갱신·재연결 검증 완료를 구분한다. 매장별 실제 IP는 운영 설정에 둔다.

### 기존 사육장에 두 대 등록

Gateway와 설치된 Air Viewer를 모두 0.4.20 이상으로 업그레이드한 뒤 실제
카메라 주소 두 개를 사용한다. 두 프로그램이 같은 `gateway.toml`을 읽으므로
구 Air Viewer도 새 카메라 필드가 있는 설정을 거부한다. 다음의
`TOP_IP`·`FRONT_IP`는 해당 매장의 카메라에서 확인한 IP로 지정해야 한다.
공유기의 DHCP 예약을 사용하면 재부팅 뒤 같은 주소로 재연결할 수 있다.

0.4.25부터 Pi의 장치 ID 기반 주소 검색을 선택적으로 사용할 수 있다. 공유기에서
카메라 IP가 바뀌어도 카메라 ID와 TOP/FRONT 역할은 유지한다. 매장 LAN에 맞춰
기존 Gateway 설정에 다음 항목을 추가한다. 아래 네트워크는 예제이며 실제 매장
주소 범위로 바꿔야 한다. 기본값은 비활성화이므로 기존 설치 동작은 유지된다.

```toml
[camera_discovery]
enabled = true
networks = ["192.168.1.0/24"]
port = 5000
interval_s = 30
timeout_s = 1.0
max_workers = 16
```

Gateway는 등록된 HTTP 카메라를 시작하거나 다시 연결할 때 `/identity`의
`schema_version=1`, `device_type=dfr1172_camera`, 매장·Gateway·사육장·카메라 ID,
`view`, `stream_path=/video_feed`를 대조한다. IP만 같거나 다른 사육장의 카메라이면
연결하지 않는다. 같은 장치 ID가 여러 주소에서 발견되면 자동 선택하지 않는다.
검색은 명시한 IPv4 사설 LAN 범위에서 제한된 주기로 수행하며, 정상 영상 수신 중인
카메라의 주소에는 추가 요청을 보내지 않는다. DFR1172는 스트림 수신 중에 별도
`/identity` 요청을 처리하지 못할 수 있으므로 카메라별 단일 수신기를 유지한다.

확인된 주소는 Gateway 데이터 디렉터리의 `cameras/camera-bindings.json`에 저장한다.
`/etc/habitat-gateway/gateway.toml`의 원래 주소나 인증정보를 자동으로 고쳐 쓰지 않는다.
재시작 후 저장된 주소도 장치 ID를 다시 확인하고 사용한다. 새 사육장을 연결할 때는
카메라 ID·사육장·역할을 먼저 등록해야 하며, 검색된 임의 장치를 자동 등록하지 않는다.
카메라 노드의 Wi-Fi 설정·전원·카메라 서버가 정상이어야 검색할 수 있다.

검색·재시도·HLS 생성 시간이 있으므로 전원 인가 직후 즉시 영상이 나온다고 보장하지
않는다. 이 기능은 신뢰하는 매장 LAN의 주소 변경 복구용이며 `/identity`를 암호학적으로
인증하는 장치 인증서 기능은 아니다. 외부 인터넷 주소를 검색 대상으로 넣지 않는다.

기존 Air Viewer도 같은 Gateway 설정을 읽으므로, 설정을 활성화하기 전에
`--with-air`로 만든 동일 릴리스로 Air Viewer를 먼저 갱신하고 Gateway를 갱신한다.
롤백 시에는 새 설정 항목도 이전 설정으로 복원한다. 카메라·BB6 펌웨어와 IR worker의
재설치는 필요하지 않으며, 기존 영상·제어 키를 유지한다.

```bash
sudo /opt/habitat-gateway/current/venv/bin/python \
  /opt/habitat-gateway/current/edge_tools.py \
  bind-camera-pair CAGE-001 \
  --top "http://${TOP_IP}:5000/video_feed" \
  --front "http://${FRONT_IP}:5000/video_feed"
```

위 명령은 기본적으로 검증만 한다. `--output /tmp/gateway-camera.toml`로
검토할 후보를 만들거나 `--apply`로 원자적으로 적용한다. 적용은 기존 파일
소유자·권한을 보존하고 Gateway를 재시작하며, 재시작 실패 시 이전 설정으로
복원한다. 재시작 후에는 health와 두 영상의 최신 수신을 확인해야 한다.
동일 설정 재적용은 재시작하지 않는다. 기존의 이름 없는 USB 카메라나 다른
사육장·센서·제어 설정은 보존된다. 기존 view 카메라 ID는 유지하고 새 view는
기본적으로 `CAGE-001-TOP`, `CAGE-001-FRONT` 같은 ID를 만든다.

### DFR1172 하드웨어 H.264로 한 대씩 전환 (0.4.26 이상)

이 절은 네이티브 펌웨어의 설치·부팅·실제 영상 검증을 마친 카메라를 Gateway에
연결하는 절차다. **문서와 빌드가 있다는 이유만으로 운영 전환이나 실물 영상
검증이 완료된 것은 아니다.** 기존 MicroPython MJPEG 카메라와 USB UVC는
그대로 지원하며, 같은 Pi에서 MJPEG와 H.264 카메라를 함께 사용할 수 있다.

새 경로는 `카메라 하드웨어 H.264 → RTSP/TCP → Pi HLS 복사 → SaaS`다.
Pi의 HLS 분기는 `-c:v copy`를 사용하므로 해상도·색감·비트레이트·GOP는
카메라가 결정한다. 별도 JPEG 미리보기와 수신 검증에는 디코딩이 사용되지만
실시간 HLS를 다시 H.264로 인코딩하지 않는다.
화면 깨짐을 감추기 위한 확대·색감 필터를 이 경로에 적용하지 않는다.
네이티브 펌웨어의 빌드·전체 flash 복구본·비공개 USB 설정 절차는
[H.264 노드 안내](../../firmware/camera_node/h264_node/README.md)를 따른다.
릴리스 묶음에서는 `firmware/camera_node/h264_node/README.md`에 같은 안내가 있다.
기존 MicroPython 이미지의 `0x2000` 기록 명령을 새 앱 전체에 재사용하지 말고,
새 빌드의 `flash-manifest.json`에 있는 파일별 주소와 해시를 확인한다.

먼저 실제 ID가 `CAGE-001-FRONT`인 보드 한 대를 전환 대상으로 확인한다.
현재 TOP에 등록된 `RGB-001`은 MJPEG 상태로 유지하며, FRONT가 검증된 뒤
별도 이행한다. 장착 위치의 별칭만 보고 ID를 바꾸거나 두 보드를 함께 기록하지
않는다. 아래는 **기존 FRONT 테이블을 수정하는 후보 예시**이며 IP는 확인한
매장 LAN 주소로 바꾼다. 같은 ID의 테이블을 추가로 만들지 않는다.

```toml
[[cameras]]
id = "CAGE-001-FRONT"
cage_id = "CAGE-001"
view = "front"
source_type = "rtsp_h264"
url = "rtsp://192.168.1.42:8554/stream"
width = 800
height = 800
fps = 20
live_stream = true
record_video = false
```

800×800/20fps는 이번 네이티브 노드의 설정이다. `/identity`와 실제 H.264
SPS 및 프레임 수신을 대조한 뒤 등록한다. 이전 800×640을 늘린 값이나
보장된 실제 촬영 속도로 표시하지 않는다. 기존 `interval_s`·녹화 정책 등
이 예시에 생략된 설정은 보존한다. `bind-camera-pair`는 기존 MJPEG 등록
도구이므로 이 전환에 사용하지 않는다.

장치 검색은 같은 HTTP 포트 5000의 `/identity`를 사용한다. H.264 대상은
기존 매장·Gateway·사육장·카메라·view에 더해 `schema_version=2`,
`stream_transport=rtsp_tcp`, `codec=h264`, `stream_port=8554`,
`stream_path=/stream`, `profile=baseline`, `sps_pps_at_idr=true`와 등록된
width/height/fps, `color_range=limited`, `color_matrix=bt601`를 대조한다.
Pi는 압축된 화상을 유지하면서 SPS 색상 메타데이터를 같은 범위와 행렬로
표시한다. 비트레이트는 256,000~4,000,000 bit/s,
GOP는 1프레임 이상·2초 이하여야 한다. 장치가 응답한 임의 URL을 사용하지
않고, 실제 확인한 LAN IP로 RTSP 주소를 구성한다. MJPEG는 기존 schema 1
대조를 유지한다. 새 H.264 세션은 Pi에 도착한 영상 조각의 코덱·프로파일·크기·
독립 디코딩을 확인한 뒤 제공하므로, ID 응답만으로 정상 영상으로 표시하지 않는다.

Gateway 배포는 기존 버전 설치기를 재사용한다.

1. 실제 운영 설정·릴리스·키를 보존하고, 후보 설정에서 바뀐 항목이 **대상
   카메라의 source_type/url/width/height/fps만**인지 구조 비교한다.
   센서·IR·MQTT·다른 카메라·장치 검색 범위는 보존한다. 준비 당시 설정의
   SHA-256을 기록하고 적용 직전 값이 달라졌으면 중단해 다시 준비한다.
2. `--with-air`로 같은 버전의 릴리스를 만들고 archive·manifest 해시와
   후보 설정을 검증한다. 임시 root의 `--no-service` 설치도 먼저 시험한다.
3. 비공개 운영 백업에 config/env, Gateway·Air unit과 current 링크를 저장한다.
   **기존 설정을 유지한 채 Air Viewer를 먼저 새 릴리스로 설치**한다.
   Air도 공통 설정을 읽으므로 구버전은 새 `rtsp_h264` 값을 거부한다.
4. 이어서 Gateway를 새 릴리스와 FRONT 후보 설정으로 설치한다. Gateway
   재시작 동안 센서 수신과 영상 제공은 잠시 중단될 수 있다. MQTT 브로커·
   IR worker 재시작이나 IR 출력 명령은 이 변경에 포함하지 않는다.
5. health의 릴리스·매장 ID, TOP의 기존 영상, FRONT의 새 HLS, 센서의 새
   수신 시각, IR 상태 조회와 기존 키 로그인을 확인한다. 영상 프로세스가
   HLS에 `copy`를 사용하고 카메라별 입력이 하나인지 확인한다. 조각 단독
   디코딩과 실제 SaaS 브라우저에서 화면 갱신·해상도·화질을 확인한 뒤 완료로
   기록한다. API health 성공만으로 카메라 수신 완료로 기록하지 않는다.

해제된 릴리스 디렉터리를 `RELEASE_DIR`, 검증한 후보 설정을
`CANDIDATE_CONFIG`에 지정한 운영자의 설치 명령은 다음과 같다. 실제 적용은
위 준비와 검증을 완료한 시점에만 실행한다.

```bash
sudo python3 "$RELEASE_DIR/install_air.py" "$RELEASE_DIR"
sudo python3 "$RELEASE_DIR/install.py" --release "$RELEASE_DIR" --config "$CANDIDATE_CONFIG"
```

각 설치기는 실패 시 자신의 설정·unit·링크를 복원한다. Air 성공 뒤 Gateway가
실패하면 Air까지 함께 자동 복원되지는 않는다. 전체 묶음을 되돌릴 때는 이전
Gateway 설정을 먼저 복구한 뒤 이전 Air 링크·unit과 실행 상태를 복원한다.
P4 펌웨어 복구는 Pi 서비스 롤백과 별개다. 네이티브 펌웨어가 남아 있는 보드에
구 MJPEG 설정만 복원하면 영상은 복구되지 않으므로, 보존한 전체 flash와 기존
비공개 설정으로 해당 보드도 복원한 뒤 MJPEG 수신을 확인한다.

LAN 전송과 외부 인증의 경계를 구분한다. RTSP·장치 identity는 신뢰하는
매장 LAN에서 사용하며 장치 인증서나 암호화 전송을 제공하지 않는다. Gateway의
기존 HTTPS 영상·IR 키와 SaaS 권한 검사는 유지한다. 최초 RTSP 주소는 사설
IPv4/루프백·8554·`/stream`으로 제한하지만, **현재 FFmpeg RTSP demuxer의
서버 유도 리다이렉트를 HTTP의 `-max_redirects 0`처럼 차단한다고 보장하지
않는다.** TCP 프로토콜 허용 목록만으로 목적지 IP까지 제한되는 것은 아니다.
따라서 불신 장치를 같은 카메라 LAN에 넣지 않으며, 목적지 제한이 필요한
설치에서는 별도의 네트워크 송신 정책으로 카메라 서브넷을 제한한다.

카메라 ID·사육장 매핑·HLS 경로와 접속 키는 전환 전후 동일하다. SaaS가
`source_type`을 검사한다면 `rtsp_h264`를 허용하도록 같은 API 계약을 반영한다.
기존 4:3 화면 상자에 `object-fit: contain`으로 표시하면 800×800 영상의
좌우에 여백이 생길 수 있으며, 이는 해상도 손실이나 크롭의 증거가 아니다.

### 사육장 추가

```bash
sudo /opt/habitat-gateway/current/venv/bin/python \
  /opt/habitat-gateway/current/edge_tools.py \
  add-cage CAGE-004 --node-id ESP32-004 --template-cage CAGE-001 \
  --top "http://${TOP_IP}:5000/video_feed" \
  --front "http://${FRONT_IP}:5000/video_feed" \
  --output /tmp/gateway-new-cage.toml
```

지정한 기존 사육장의 센서·액추에이터 inventory를 재사용하며 정책은 빈 상태로
시작한다. 매장별 source 수정은 필요 없다. 새 node의 MQTT 계정·ACL·비공개
펌웨어 설정과 실물 센서 검증은 별도로 완료해야 한다. 명령 결과의
`sensor_credentials_provisioned=false`는 이 경계를 나타낸다. ID를 추가했다는
이유만으로 설치되지 않은 센서를 실측으로 표시하거나 출력 잠금을 풀지 않는다.
실제 출력은 기존 commissioning과 safety interlock을 통과한 장치만 사용한다.

### 검증과 이행

1. TOP과 FRONT 각각에서 실제 JPEG가 수신되고 갱신되는지 확인한다.
2. `/v1/cameras`와 `/camera/api/cameras`의 상태·신선도를 확인하고 사육장별
   두 화면에서 TOP/FRONT 구분을 실물로 대조한다. 오래된 마지막 프레임이나
   설정만 존재하는 상태를 정상 영상으로 판정하지 않는다.
3. 한 대를 분리했을 때 해당 화면만 대기 상태가 되고 다른 카메라·센서 수신이
   계속되는지, 재연결 후 새 세션 영상이 들어오는지 확인한다.
4. SaaS가 Pi의 인증된 HLS API를 조회하는 방식은 기존 카메라 ID·키·프록시를
   사용한다. [카메라·IR 연동 계약](../api/camera-ir-integration.md)을 따른다.
   별도 push 방식인 `video_upload.enabled`/`camera_cages`와 혼동하거나,
   이번 카메라 연결을 위해 두 전송 경로를 동시에 활성화하지 않는다.

새 URL/view/source_type 필드는 구 릴리스에서 허용하지 않는다. Gateway와 설치된
Air Viewer의 코드 업그레이드를 먼저 하고 설정을 적용하며, 구 릴리스로 rollback할
때는 새 필드를 넣기 전의 설정도 함께 복원한다. `.before-camera.toml`은 직전
적용의 복구본이며, 여러
사육장을 순서대로 수정할 때는 최초 이행 전 설정을 별도 운영 백업으로 보관한다.
카메라 장애·SaaS 장애가 ESP32 로컬 안전제어를 해제하거나 중단시키지 않는다.
