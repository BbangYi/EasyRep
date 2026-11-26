# HabitatOS 0.4.15 — Pi hardware arrival

Pi: MQTT sensor gateway, private local API, SQLite history, SaaS sync, UVC snapshots,
GPU prediction client. Model weights and CUDA execution remain on the GPU desktop.
An Arduino board is not used: Arduino CLI only builds the ESP32 firmware.

Current software and deployment evidence is in the
[verification record](../hardware-design/assembly-verification.md) and
[Pi operation guide](pi-update.md). The dated simulation sections below retain
their original versions and results; they do not describe current SaaS delivery.

## CAGE-002 GPIO 설정 재대조 — 2026-11-04

사용자가 제공한 14:09:17.567~14:09:25.573 KST 결과와 Pi에 저장된
`/home/<gateway-user>/cage002_sensor_check_20261104.json`이 일치한다. 새 메시지가
추가됐지만 T1·RH1·T2·T3는 모두 null/invalid다. 이 JSON에는 GPIO 정보가
없으므로 현재 실행 중인 ESP32의 핀 설정을 이 결과로 판정하지 않는다.

이번 확인에서 기존 소스·노드별 비공개 설정·사용자 배선 PDF를 직접
재대조했다. PDF의 SHA-256은 아래 11월 3일 기록과 같으며, 1·3·25쪽의
센서 핀은 SDA25/SCL26/T2=32/T3=33이다.

| 확인 대상 | SDA / SCL / T2 / T3 | 설정 범위 |
| --- | --- | --- |
| `firmware/cage_node/config.h` | 지정 없음 → 21 / 22 / 18 / 19 기본값 | MQTT ID가 ESP32-001인 소스 폴더 설정 |
| `~/.config/habitatos/nodes/ESP32-001/config.h` | 지정 없음 → 21 / 22 / 18 / 19 기본값 | Cage001 전용 |
| `~/.config/habitatos/nodes/ESP32-002/config.h` | 25 / 26 / 32 / 33 | Cage002 전용, 배선 PDF와 일치 |
| `~/.config/habitatos/nodes/ESP32-003/config.h` | 25 / 26 / 32 / 33 | Cage003 전용, 배선 PDF와 일치 |

Cage002 전용 설정의 수정 시각은 11월 3일 17:10:17 KST이며 두 R15 옵션은
0이다. Cage003도 두 옵션이 0이고 각 노드의 MQTT ID/topic은 서로 구분된다.
따라서 **Cage002 설정에 네 핀 지정이 없다는 이전 설명은 정정한다.**
소스 폴더의 Cage001 설정과 소스 외부의 Cage002 설정을 구분해야 한다.

아래 11월 3일 작업 기록에는 Cage002 재업로드와 17:17·17:37 부팅 로그의
`SENSOR_PINS sda=25 scl=26 T2=32 T3=33` 확인이 남아 있다. 이는 과거 작업
기록이며 이번에 flash를 다시 읽거나 직렬 로그를 수집한 결과는 아니다.
당시 확인 환경의 `/dev/serial/by-id`, `/dev/ttyUSB*`, `/dev/ttyACM*`에서
직렬 장치를 찾지 못해 실행 중인 펌웨어의 GPIO 재확인은 하지 못했다. Cage003의
실물 업로드를 확인한 기록도 없다.

`python3 -B tests/hardware/check_cage_node.py`를 실행해 기존/38핀 배치의
GPIO 매핑, 각 배치의 R15 59건·GPIO scheduling 2건·probe 12건·Hello
serializer·센서 진단 검사와 잘못된 설정 거부 5건이 통과했다. 이 검사는
호스트 회귀 검사이며 현재 ESP32 빌드·실물 센서 측정 검증을 대신하지 않는다.
테스트 임시 빌드는 자동 정리됐고, 이번 변경은 이 운영 기록뿐이다. 펌웨어·
노드 설정·MQTT 계약·서비스·기기 상태는 변경하지 않았다. 센서 읽기 실패의
원인은 여전히 미확정이며, 현재 설정 누락으로 설명할 근거는 없다.

### USB 연결 후 실행 중인 GPIO·센서 진단 확인 — 14:31 KST

사용자가 USB 직렬 연결을 완료했다고 알려 직접 확인했다. 샌드박스에서는
`/dev/ttyUSB*`가 보이지 않았지만 sysfs에는 CP2102N과 Cage002 고유 USB
serial `30ffeac78e89ef11afc8ad95ef8776e9`가 확인됐다. 샌드박스 밖에서
동일 고유번호·VID/PID를 대조한 뒤 `/dev/ttyUSB0`만 115200 baud로 열었다.
샌드박스의 장치 파일 부재를 실제 USB 미연결로 단정하면 안 된다.

14:31:04.882~14:31:49.996에 45초간 로그를 관찰했다. DTR/RTS를 false로
지정했지만 포트를 연 직후 POWERON_RESET이 출력됐으므로 이 시작을 자연
재부팅의 증거로 해석하지 않는다. 14:31:55에 포트를 닫았다.

- 14:31:05.362의 실제 부팅 로그는 `SENSOR_PINS sda=25 scl=26 T2=32 T3=33`이다.
  **현재 실행 중인 Cage002 펌웨어도 배선 PDF와 같은 네 핀을 사용한다.**
- T2는 GPIO32에서 ROM `284F16000A0000C5`, T3는 GPIO33에서 ROM
  `28380C000A000019`가 발견됐다. 이는 센서 발견 단계의 통과이며 정상
  온도 측정이나 전원 품질의 검증은 아니다.
- 14:31:06.338과 14:31:36.630 모두 SHT31은 `init_failed`, I²C
  0x44/0x45는 timeout(5), 두 DS18B20은 `external_power_not_reported`였다.
  SDA/SCL 디지털 입력은 0/0, 두 DQ는 1/1이었다. 실제 공급 전압을 측정한
  결과가 아니므로 전원·접촉·풀업 중 어느 것이 원인인지 확정하지 않는다.
- 14:31:25~14:31:45의 네트워크 로그는 Wi-Fi·시간 동기화·MQTT 모두 정상이다.
  이 직렬 관찰에서 Pi DB 저장이나 Cage002 개별 SaaS ACK는 재검증하지 않았다.

GPIO 설정 일치는 실기 로그로 확인했지만 센서 읽기 실패는 계속된다. 다음
물리 확인 대상은 사용자 배선 PDF의 공통 3.3V 분배, 특히 `e25↔f25` 점퍼다.
사용자가 이 점퍼를 점검·수정했다고 확인한 결과는 이번 관찰에 없다.
펌웨어·설정·서비스는 변경하지 않았고 별도 진단 파일은 생성하지 않았다.

### USB 센서 진단 재확인 — 14:34 KST

사용자의 재확인 요청으로 같은 Cage002 USB 고유번호를 확인하고
14:34:03.276~14:34:48.382에 45초간 다시 관찰했다. 포트를 연 직후
POWERON_RESET이 출력됐고, 14:34:53.438에 포트를 닫았다. 실제 GPIO는
다시 SDA25/SCL26/T2=32/T3=33으로 확인했으며 T2·T3 ROM도 앞선 관찰과 같다.
사용자가 변경한 구체적인 배선 내용은 확인되지 않아 특정 점퍼 수정의 효과로
단정하지 않는다.

- 14:34:04.774와 14:34:35.152 모두 **T2=ok, T3=ok**로 바뀌었다.
  펌웨어의 외부 전원 응답·변환 완료·scratchpad CRC·측정 범위 검사를
  통과했다. 직렬 로그에는 실제 온도 숫자가 없어 수치는 확인하지 않았다.
- 두 시점 모두 I²C 0x45는 ACK(0), 0x44는 주소 NACK(2)이며
  SHT31은 **read_failed**다. 이전의 양쪽 주소 timeout 및 초기화 실패에서
  상태가 달라졌지만 온도·습도 읽기 중 하나 이상은 여전히 실패한다.
  SDA/SCL/T2 DQ/T3 DQ 순간 입력은 모두 1이다. 이는 전압 계측이 아니다.
- 14:34:23~14:34:43에는 Wi-Fi·시간 동기화·MQTT 연결이 모두 정상이다.
- 내용을 확인한 기존 읽기 전용 DB helper를 `sudo -n python3 -B
  /home/<gateway-user>/cage002_sensor_check_20261104.py`로 실행했지만
  `sudo: a password is required`로 실패했다. 따라서 이번 확인에서 실제
  온도 숫자·Pi 저장·SaaS 전달을 검증했다고 표현하지 않는다.

현재 확인 범위는 **두 DS18B20의 측정 검사 통과, SHT31 읽기 실패 지속**이다.
펌웨어·설정·서비스 변경이나 별도 진단 파일 생성은 없으며 이 기록만 갱신했다.

### 사용자 실행 결과로 Pi 저장값 확인 — 14:37 KST

사용자가 Pi 터미널에서 기존 DB helper를 sudo로 실행한 결과를 제공했다.
조회 시각은 14:37:20.954548과 14:37:28.960402 KST이며,
`new_message_seen=true`다. 두 조회의 중복 메시지 한 건을 제외하면 서로 다른
메시지 5건이며, 두 번째 조회에서 첫 번째 조회 이후의 메시지 2건을 확인했다.
다섯 건 모두 T2=24.25°C, T3=24.437°C로 valid이고 T1·RH1은 null/invalid다.

최신 메시지 `0a75ad3a-8db1-437e-8062-422d1d9254e9`는 sampled_at
14:37:27, received_at 14:37:27.105793 KST다. 나열된 다섯 메시지의 수신
간격은 약 5.06초다. 따라서 **두 DS18B20은 유효한 실측값의 Pi 수신·저장까지
확인됐고, 천장 SHT31 온도·습도 읽기 실패가 남아 있다.** 이는 사용자가
제공한 읽기 전용 조회 결과이며 이번에 별도로 DB를 직접 조회한 것은 아니다.
SaaS ACK나 사이트 화면 반영은 이 결과의 검증 범위에 포함되지 않는다.
설정·펌웨어 변경 없이 기존 운영 기록만 갱신했다.

### USB 재검증: SHT31 주소 응답 없음 — 15:03~15:04 KST

사용자의 재확인 요청으로 동일한 Cage002 USB 고유번호를 확인하고
15:03:48.282~15:04:33.385에 45초간 직렬 로그를 관찰했다.
포트를 연 직후 POWERON_RESET이 출력됐고 15:04:38.525에 포트를 닫았다.
부팅 GPIO는 SDA25/SCL26/T2=32/T3=33이고 두 DS18B20의 ROM도 이전과 같다.

15:03:49.746과 15:04:20.103의 두 진단 모두 T2=ok, T3=ok였다.
SHT31은 **init_failed**로 바뀌었고 I²C **0x44·0x45 모두 주소 NACK(2)**다.
이는 14:34의 0x45 ACK/read_failed와 다른 관찰 결과이며 timeout으로
표현하지 않는다. 네 신호선의 순간 디지털 입력은 모두 1이었다.
15:03:53~15:04:28의 네트워크 로그는 Wi-Fi·시간 동기화·MQTT 모두 정상이다.

이번 요청 전 사용자가 센서를 분리하거나 배선을 변경했는지는 확인되지 않았다.
따라서 무응답을 새 고장이나 납땜 불량으로 확정하지 않는다. 현재 SHT31의
실제 연결 상태·공급 전압·접촉 확인이 필요하다. 실제 온도 숫자와 Pi DB·SaaS
전달은 이번에 재검증하지 않았다. 펌웨어·설정·서비스 변경 없이 기존 운영
기록만 갱신했고 별도 진단 파일은 생성하지 않았다.

15:22:40.956~15:23:26.071에 같은 USB 고유번호로 45초간 재확인했다.
포트를 연 직후 POWERON_RESET이 출력됐고 15:23:31.325에 닫았다.
GPIO와 두 DS18B20 ROM은 같으며, 15:22:42.628 및 15:23:12.978 모두
T2=ok, T3=ok, SHT31=init_failed다. 이번에는 I²C 0x44/0x45가 모두
**timeout(5)**이고 SDA/SCL 순간 입력은 **0/0**, T2/T3 DQ는 1/1이다.
앞선 15:03~15:04의 주소 NACK(2)·SDA/SCL=1/1과 구분한다. 두 시점의
LOW 관찰만으로 계속 LOW였다고 단정하거나 단락·납땜 불량을 확정하지 않는다.
15:22:46~15:23:21의 Wi-Fi·시간 동기화·MQTT는 정상이다. 실제 공급 전압과
사용자의 물리 배선 변경 여부는 미확인이다. 이번에도 펌웨어·설정·서비스는
변경하지 않았으며 DB·SaaS 전달 재검증 없이 이 기록만 갱신했다.

15:49:07.516~15:49:52.617에 같은 Cage002 USB 고유번호로 45초간 재확인했다.
포트 개방 직후 POWERON_RESET이 출력됐고 15:49:57.757에 닫았다.
GPIO는 계속 SDA25/SCL26/T2=32/T3=33이다. 15:49:08.980과 15:49:39.335
두 진단 모두 **SHT31=init_failed, 0x44/0x45=주소 NACK(2)**이며 SDA/SCL
순간 입력은 **1/1**이다. 앞선 15:22~15:23의 timeout(5)·LOW와 달라졌지만
SHT31 주소 응답은 여전히 확인되지 않았다. T2/T3는 모두 ok이고
15:49:13~15:49:48의 Wi-Fi·시간 동기화·MQTT도 정상이다. 물리 배선 변경과
실제 전압은 미확인이고 고장 원인은 확정하지 않았다. 이번에도 펌웨어·설정·
서비스 변경이나 별도 진단 파일 생성 없이 기존 기록만 갱신했다.

15:54:37.277~15:55:22.381에도 같은 Cage002 고유번호로 45초간 재확인했다.
포트 개방 직후 POWERON_RESET과 같은 GPIO 설정이 출력됐다.
15:54:38.742 및 15:55:09.098 모두 SHT31=init_failed,
0x44/0x45=주소 NACK(2), SDA/SCL=1/1, T2=ok, T3=ok로 15:49와 같았다.
15:54:42~15:55:17의 Wi-Fi·시간 동기화·MQTT도 정상이다. 펌웨어·설정·서비스를
변경하지 않았고, 실제 배선·전압과 Pi DB·SaaS 전달은 이번 확인 범위에 없다.

## CAGE-002 최초 펌웨어 설치 — 2026-11-03

**16:50 수신한 새 배선도에 따른 정정:** Cage002·003은 HG-ESP32-DEVKIT V4
38핀 장착 배치이며 SDA25/SCL26/T2=32/T3=33을 사용한다. 아래 초기 조사와
분리 시험은 Cage001 기준인 21/22/18/19를 읽은 기록이다. 따라서 해당 결과로
새 배선의 센서·기판 불량을 추론한 결론은 철회한다. 잘못된 핀의 timeout이나
NACK는 실제 센서 버스 상태를 증명하지 않는다. 이후 수정·재검증 기록을 따른다.

사용자가 두 번째 센서 사육장의 조립과 전원 연결을 완료했고 아직 펌웨어를
업로드하지 않았다고 확인했다. SHT31 SDA21/SCL22, DS18B20 GPIO18/GPIO19
배선은 사용자 확인을 받았다. 기존 gateway 설정과 MQTT ACL에는 이미
`CAGE-002` / `ESP32-002`와 T1·RH1·T2·T3가 등록돼 있어 재등록하지 않았다.

- 13:14:34 KST에 새 CP2102N USB 보드가 인식됐다. USB serial은
  `30ffeac78e89ef11afc8ad95ef8776e9`, ESP32 MAC은 `b0:3f:d3:64:24:28`이다.
  칩은 ESP32-D0WD-V3 revision 3.1, flash 4MB로 직접 조회했다. 이전 CH340
  보드와 구분하고 업로드 직전에 USB 고유번호를 다시 확인했다.
- 기존 `firmware/cage_node/cage_node.ino`를 그대로 사용했다. 노드별 코드
  복사본이나 별도 센서 구현을 추가하지 않았다. 센서 전용 역할을 명시하고
  `HABITAT_R15_CENTRAL=0`, `HABITAT_R15_REQUEST_OUTPUTS=0`을 유지했다.
- Cage002 비공개 설정의 Wi-Fi 비밀번호가 현재 정상 노드의 설정과 달라
  현재 연결 정보로 갱신했다. MQTT 사용자·비밀번호·topic은 기존 Cage002
  고유 값을 보존했다. 인증서는 문자열 표현만 다르고 실제 PEM 내용은
  현재 broker와 같았다. TLS 인증서 검증은 유지했다.
- Arduino CLI 1.5.1은 공식 배포 SHA-256을 대조해 임시로 사용했다.
  기존 ESP32 core 3.3.12, SHT31 2.2.2, BusIO 1.17.4, OneWire 2.3.8,
  PubSubClient 2.8을 재사용했다. `FlashSize=4M,FlashMode=dio,FlashFreq=40`,
  upload 460800, `EraseFlash=none`으로 빌드·업로드했다.
- 빌드는 성공했고 프로그램 1,050,997 bytes, 전역 RAM 50,564 bytes였다.
  업로드한 application binary SHA-256은
  `273d8dad977fe60c761f7e053db36ab0f7f98beebf080b381103252a0ec02c3f`다.
  esptool 5.3.1이 bootloader·partition·boot_app0·application의 쓰기 후
  hash 검증을 모두 통과했다.
- 사용한 설정은 `/home/<gateway-user>/.config/habitatos/nodes/ESP32-002/config.h`에
  0600 권한으로 저장했다. 인증정보·인증정보가 포함된 binary는 문서나 배포
  패키지에 넣지 않는다. 기존 Pi 서비스와 source의 Cage001 설정은 변경하지 않았다.
- `python3 -B tests/hardware/check_cage_node.py`의 probe 12건,
  R15 host 59건, GPIO scheduling 2건과 Hello serializer 검사가 통과했다.
  이는 센서 정확도·실물 배선·출력 작동 검증을 대신하지 않는다.
- 13:28:32 KST, 새 보드의 MAC과 IP `192.168.219.106`을 대응시켰고
  Pi TLS MQTT 8883 연결을 확인했다. Cage001도 `192.168.219.100`에서
  함께 연결돼 최신 실측을 수신했다. SaaS HTTP 200·이벤트 ACK는 이어졌다.

### 센서 읽기 실패와 전송 성공의 구분 — 14:04~14:09 KST

운영 DB·API 인증파일은 관리자 권한이 필요하므로 사용자가 Pi 터미널에서
읽기 전용 검증을 직접 실행했다. 14:04:29.260~14:05:04.303의 35초 관찰 결과:

- Cage002 저장 행은 시작 시 482건이었으며 신규 메시지 7건을 추가로 확인했다.
  수신 간격 중앙값 5.012초, 최대 5.104초였다.
- 최종 메시지 `926673b9-460f-4a2b-ab36-abcfdff4e790`은
  sampled_at 14:05:04, received_at 14:05:04.134였다. T1·RH1·T2·T3는
  **모두 `value=null`, `quality=invalid`**였다. 관찰 구간의 전체 정상 판정도
  실패했으며, 통신 성공을 센서 정상 측정으로 간주하지 않는다.
- Cage002 전용 outbox 이벤트 6건의 삭제와 ACK high watermark 진행을
  함께 관찰했다. 순번은 61859, 61861, 61863, 61865, 61867, 61869다.
  이는 센서 읽기 실패 상태를 포함한 메시지가 Pi에 저장되고 SaaS ACK를
  받았다는 근거다. 6건 중 1건은 관찰 시작 전 측정으로, 신규 7건 전부의
  개별 ACK를 확인했다고 표현하지 않는다.
- 마지막 `last_event_success_at`은 14:05:04.078, 연속 전송 실패는 0이었다.
  기존 충돌 격리 이벤트 8건(`cloud_event_conflicts`)은 별도 미해결 이력이며,
  이번 Cage002 전송을 막지 않았다. 기존 이력·순번·격리를 변경하지 않았다.
- 같은 시점 Cage001은 T1 18.83°C / RH1 47.84% / T2 18.562°C /
  T3 19.562°C, 네 항목 모두 valid였다. 출력은 두 cage 모두
  `hardware_not_commissioned`로 잠겨 있다.

사용자는 Cage002의 센서 기판과 선이 모두 연결돼 있으며 멀티미터는 없다고
확인했다. 정확한 USB 고유번호로 Cage002만 선택해 부팅·센서 발견 로그를
45초 관찰했다. 포트를 연 14:08:54에 POWERON_RESET과 센서 전용 시작 로그가
나왔고, 14:09:00부터 14:09:35까지 Wi-Fi·시간 동기화·MQTT는 정상이었다.
이 부팅 세션에서는 GPIO18/19의 `probe ... event=found` 로그가 없었다.
이는 현재 펌웨어의 유효한 단일 DS18B20 검색 조건이 충족되지 않았다는 뜻이며,
센서 자체 고장이나 전원 불량을 확정한 것은 아니다. SHT31의 실패 원인은
현재 직렬 로그만으로 세분할 수 없다. 포트는 종료 후 닫았다.

다음 확인 대상은 센서 공통 전원/GND, 실제 GPIO 번호와 기판 연결 위치다.
멀티미터가 없어 기판 사진으로 먼저 대조한다. 이번 재검증에서는 펌웨어나
운영 설정을 다시 변경하지 않았다. **Cage002는 통신 연결 완료·센서 검증 미완료**다.

사용자 요청으로 14:14:07.680~14:14:42.731 KST에 같은 읽기 전용 검증을
직접 재실행했다. 신규 메시지 7건, 수신 간격 중앙값 5.018초·최대 5.105초,
Cage002 개별 ACK 7건(순번 62084, 62086, 62088, 62090, 62092, 62094,
62096)을 관찰했다. ACK는 신규 메시지 중 6건과 관찰 시작 전 측정 1건이다.
최종 메시지 `eca32c6a-88ed-4af7-b709-beb74ae4d23d`는
sampled_at 14:14:38, received_at 14:14:38.745이며 T1·RH1·T2·T3가 여전히
모두 null/invalid였다. 같은 시점 Cage001 네 채널은 valid, SaaS 연속 전송
실패는 0이었다. 펌웨어 업로드·장치 재시작·설정 변경 없이 재조회한 결과이며
센서 읽기 실패는 해결되지 않았다.

### 센서 버스 진단 추가 — 14:29~14:30 KST

사용자가 배선을 모두 대조했으나 문제가 없다고 확인하여 소프트웨어와 실제
센서 버스를 추가 조사했다. Cage002의 application flash 1,051,152 bytes를
읽은 SHA-256은 최초 업로드 binary와 정확히 일치했다. 잘못된 노드에 업로드했거나
이전 업로드가 유실됐다는 근거는 없다.

기존 `cage_node.ino`의 센서 validation에 실패 사유를 추가하고, 부팅 때 실제
센서 GPIO와 30초 간격의 직렬 진단을 출력하도록 확장했다. GPIO 재배치·다른 핀
검색·validation 완화·MQTT payload 변경은 하지 않았다. 기존 host probe 12건에
각 실패 사유 검증을 추가했고, 진단의 주소 제한·30초 주기 검사도 통과했다.
R15 host 59건·GPIO 2건·Hello serializer와 MQTT adapter 2건도 통과했다.
진단 해석과 제한은 [MQTT 문서의 직렬 진단 안내](../mqtt-protocol.md)에 기록했다.

같은 core 3.3.12와 기존 라이브러리로 classic ESP32 빌드가 성공했다.
프로그램은 1,051,997 bytes, 전역 RAM은 50,564 bytes다. application binary
SHA-256은 `1fe2356def4c619e4abdb72ffcbb2b0148d83342d7b6893829e728f2a7efb116`이다.
고유 USB serial로 Cage002만 다시 식별하고 application 영역 0x10000에만
기록한 뒤 esptool hash 검증을 통과했다. 부트로더·partition·인증정보·출력 잠금·
Pi 서비스·Cage001 펌웨어는 변경하지 않았다.

14:29:57 부팅의 `SENSOR_PINS`는 SDA21/SCL22/T2=18/T3=19였다.
실제 직렬 진단은 다음과 같다. 0/1은 순간적인 디지털 입력이며 전압 측정이 아니다.

| KST | SDA/SCL/T2 DQ/T3 DQ | I²C 0x44 / 0x45 | SHT31 | T2 | T3 |
| --- | --- | --- | --- | --- | --- |
| 14:29:58.541 | 1 / 0 / 0 / 0 | timeout / timeout | init_failed | not_detected | not_detected |
| 14:30:28.574 | 1 / 1 / 1 / 1 | timeout / timeout | init_failed | not_detected | unexpected_family |

T3의 두 번째 검색은 DS18B20 family로 검증되지 않은 응답을 보았다. 이 결과만으로
다른 센서 제품이 달렸다고 단정하지 않으며, 신호 불안정도 구분되지 않았다.
Wi-Fi·시간 동기화·MQTT는 14:30:02~14:30:37 정상이고 45초 관찰 후 포트를 닫았다.
센서 공급 전압·풀업 저항·접촉 상태는 여전히 미계측이며 근본 원인은 미확정이다.
다음 분리 시험은 Cage002 전원을 끄고 DS18B20 두 개를 분리한 뒤 SHT31만 남겨
다시 켜는 절차로 안내했다. 사용자 완료 응답 전에는 이 상태의 결과로 판정하지 않는다.

### SHT31 단독 연결 확인 — 14:36~14:53 KST

사용자가 DS18B20 두 개를 분리하고 SHT31만 연결해 다시 켰다고 확인했다.
14:36:13·14:36:19·14:36:49의 진단에서 0x44·0x45 모두 timeout,
SHT31은 `init_failed`였다. 이 상태의 T2·T3 `not_detected`는 의도적으로
분리한 센서의 결과이므로 새로운 고장 증거로 해석하지 않는다.

14:36:18에 `SW_CPU_RESET` 한 건을 관찰했다. 당시 필터된 로그에 원인을
설명하는 정보가 없어 재시작 원인은 미확정이다. 오류·panic·backtrace도
포함하도록 수집을 확장하여 14:52:44~14:53:34에 50초간 재확인했다.
포트를 열 때의 POWERON_RESET 이후 추가 reset·panic·backtrace는 없었다.
시간 동기화 뒤 14:53:04부터 Wi-Fi·MQTT는 정상이며, 센서 진단은 여전히
0x44·0x45 timeout / SHT31 `init_failed`였다. 재시작이 재현되지 않았다는
것만으로 원인이 해결됐다고 판정하지 않는다.

기존 펌웨어와 설치된 Wire·OneWire 구현을 확인했다. SHT31은 GPIO21/22,
DS18B20은 GPIO18/19를 사용하며 R15는 compile-time guard로 비활성이다.
센서 GPIO를 다른 기능이 다시 설정하는 경로는 현재 소스에서 발견하지 못했다.
다음 분리 시험은 센서 기판 연결을 ESP32에서 모두 제거한 상태의 동일한
펌웨어 진단으로, 사용자 확인 후 실행한다.

### ESP32 단독 분리 시험 — 15:06~15:07 KST

사용자가 센서 기판 연결을 모두 제거하고 ESP32만 Pi USB에 연결했다고 확인했다.
펌웨어를 변경하지 않고 고유 USB serial을 대조해 관찰했다. 15:06:51.657에
SDA/SCL/T2 DQ/T3 DQ는 1/1/1/1, `i2c44=2`, `i2c45=2`였다.
연결 상태의 timeout(5)이 센서가 없는 주소 NACK(2)로 바뀌었다. 이 비교는
연결된 센서·기판·배선 쪽으로 조사 범위를 좁히지만 특정 부품 고장을 확정하거나
ESP32 모든 핀의 정상 동작을 증명하지는 않는다.

15:06:55~15:07:10에는 Wi-Fi·시간 동기화·MQTT가 정상이었다.
예정한 40초 관찰은 15:07:12 USB disconnect로 중단됐으며 커널 journal에도
같은 CP210x 분리가 기록됐다. 따라서 완료된 40초 관찰이나 자연 재부팅으로
표현하지 않는다. 다음 시험은 센서 기판을 우회하여 SHT31의 VCC/VIN→3V3,
GND→GND, SDA→GPIO21, SCL→GPIO22만 직접 연결하는 절차다.
배선 변경은 Cage002 전원을 끈 상태에서 하도록 안내했고 사용자 응답을 기다린다.

### 새 38핀 배선도 적용과 실제 재검증 — 16:50~17:18 KST

사용자가 SCP로 보낸 `/home/<gateway-user>/CAGE002_003_BB6_38pin.pdf` 1·3·25쪽을
확인했다. SHA-256은
`b876bc5ed31be4498dde8fe6ef07a41f354c6f3638d249bc9dde22060a5ed7f0`이다.
Cage002·003의 GPIO는 SDA25/SCL26/T2=32/T3=33이며, 이전 펌웨어가
21/22/18/19를 읽고 있었던 불일치를 확인했다. 사용자가 새 PDF대로 센서 세 개를
다시 연결하고 Cage002를 Pi USB에 연결했다고 확인했다.

- 기존 `cage_node.ino`에 네 `HABITAT_*_PIN` 설정을 추가했다. 모두 생략한
  기본값은 21/22/18/19로 유지한다. 부분 지정·중복·사용 불가 핀은 빌드에서
  거부하고 R15 옵션의 기존 잠금을 유지한다. 노드 ID에 따른 소스 분기는 없다.
- 외부 `~/.config/habitatos/nodes/ESP32-002/config.h`와 `ESP32-003/config.h`에
  새 핀 네 개와 R15 옵션 0을 저장했다. Cage003의 오래된 Wi-Fi 비밀번호도
  현재 매장 정보로 맞췄다. 각 노드의 MQTT 계정·비밀번호·topic은 보존했다.
  Cage001의 설정과 기기 펌웨어는 변경하지 않았다.
- 기존 host 검사에서 두 배치 각각 R15 59건·GPIO scheduling 2건·probe 12건·
  Hello serializer·센서 로그 검사를 통과했다. 기본/override 핀 매핑과 부분 지정·
  중복·입력 전용 핀·각 R15 옵션 활성화 거부 5건도 통과했다. MQTT adapter 2건 통과.
- 같은 classic ESP32 FQBN/core로 빌드 성공: 프로그램 1,051,997 bytes,
  RAM 50,564 bytes, application 1,052,144 bytes. application SHA-256:
  `242c61c7582bda74659faa9ca68537116f3ab3a19008bbad3b9bf14ade869e31`.
  Cage002 고유 USB serial과 MAC `b0:3f:d3:64:24:28`을 확인하고 0x10000
  application만 업로드했으며 esptool hash 검증이 통과했다.
  Cage003은 설정만 준비했으며 실물 업로드·센서 검증은 하지 않았다.

17:17:10~17:17:55의 45초 직렬 관찰에서 `SENSOR_PINS sda=25 scl=26 T2=32
T3=33`을 확인했다. T2 ROM `284F16000A0000C5`, T3 ROM
`28380C000A000019`가 각각 발견됐다. 네트워크는 17:17:15 이후 정상이다.
17:17:11에는 두 probe가 `conversion_incomplete`, 17:17:42에는 둘 다
`external_power_not_reported`였다. 두 시점 모두 SHT31 `init_failed`,
I²C 0x44/0x45 timeout이었다. 따라서 **핀 설정 불일치는 수정했으나 정상 실측은
아직 복구되지 않았다.** 외부 전원 응답 실패는 전압 계측을 대신하지 않는다.

같은 시간대 gateway journal의 HTTP 200/ACK는 각 23건, sync delayed는 0건이다.
이는 전체 gateway 전송 상태이며 Cage002의 개별 메시지 ACK 검증으로 표현하지
않는다. 관리자 인증이 만료돼 DB 검증 helper는 아직 재실행하지 않았다.
다음 확인은 PDF 4쪽의 공통 센서 전원 `e25↔f25` 연결이다. 사용자에게 USB를
뺀 상태로 해당 점퍼만 확인하도록 요청했다. 핀 변경은 MQTT 계약을 바꾸지 않으며
설정·이행 절차는 [MQTT 문서](../mqtt-protocol.md)에 기록했다.

사용자의 재확인 요청으로 17:37:14~17:37:54에 Cage002 직렬 로그를 40초간
관찰했다. 새 GPIO 25/26/32/33과 동일한 T2/T3 ROM 발견을 다시 확인했다.
17:37:16에는 SHT31 `init_failed`, 두 probe `conversion_incomplete`였고,
17:37:46에는 SHT31 `init_failed`, T2 `out_of_range`, T3
`external_power_not_reported`였다. 두 시점의 I²C 0x44/0x45는 모두 timeout이다.
범위 밖이라는 진단만으로 구체적인 온도값을 추정하지 않는다. 17:37:35부터
시간 동기화·Wi-Fi·MQTT는 정상이다. 포트를 열 때 POWERON_RESET이 있었고
관찰 종료 후 닫았다. 여전히 센서 측정 정상화는 확인하지 못했다.
DB helper는 `sudo: a password is required`로 실행되지 않아 사용자에게
Pi 터미널에서 기존 읽기 전용 명령 실행을 요청했다. 이 관찰만으로 Cage002의
최신 사이트 ACK나 전체 측정 주기의 품질을 검증했다고 표현하지 않는다.

사용자가 Pi 터미널에서 DB helper를 실행한 결과를 17:40:00.203~17:40:35.249
KST 구간으로 확인했다. 신규 Cage002 메시지 7건 모두 T1·RH1·T2·T3가
`invalid`였으며, 최종 메시지 `9f311842-ba9a-48c0-84ff-53c289984fc8`의
네 값은 모두 null이었다. 수신 간격 중앙값 5.038초, 최대 5.154초였다.
최종 received_at은 17:40:33.608이다.
Cage002 ACK 7건(순번 65047·65049·65051·65053·65055·65057·65059)을
관찰했으며 신규 7건 중 6건과 관찰 시작 전 측정 1건에 해당한다. 마지막 신규
측정은 관찰 종료 시 아직 개별 ACK를 확인하지 못했으므로 유실로 판정하지 않는다.
이는 읽기 실패 상태를 포함한 메시지가 Pi에 저장되고 SaaS에 전달된 근거이며
사이트 화면 표시 자체를 직접 확인한 것은 아니다.
게이트웨이 health는 ok, SaaS 연속 전송 실패는 0, 최종 이벤트 성공은
17:40:32.258이었다. 기존 충돌 격리 8건은 그대로이며 신규 전송과 구분한다.
같은 시점 Cage001은 T1 20.21°C, RH1 51.04%, T2 20.375°C,
T3 21.562°C로 모두 valid다. 이번 검증은 읽기 전용이며 펌웨어·배선·운영
설정을 추가 변경하지 않았다. Cage002 센서 읽기 문제는 여전히 미해결이다.
결과를 요약한 뒤 임시 `verification.json`은 제거했고 재검증 helper는 유지한다.

최초 업로드의 임시 빌드와 요약한 DB 검증 JSON은 삭제했다. 새 GPIO 펌웨어의
테스트·업로드·직렬 결과를 위에 요약한 뒤 `/tmp/habitat-sensor-diagnostics-8eoys8b3`
전체를 제거했다. 임시 CLI·빌드·ELF·application 백업·인증정보가 포함된 config
사본·binary/cache·원시 로그는 남기지 않았다. 실제 노드별 설정은 소스 외부에 유지한다.
물리 연결 점검 후 재검증에 필요한
`/tmp/habitat-cage002-ut7jh23u/verify.py`도 임시로 유지한다. localhost GET과
read-only SQLite SELECT로 35초간 관찰하고 인증값 없는 결과를 저장하는 도구다.
조립 검증 완료 후 제거하며, Pi 재부팅으로 없어지면 다시 준비해야 한다.

## CAGE-001 간헐적 수신·Pi USB 연결 후 확인 — 2026-11-03

사용자가 사이트의 센서 연결이 반복해서 끊겼으며, ESP32를 Pi USB에 연결한
뒤에는 정상으로 보인다고 확인했다. 실제 Pi의 journal, USB 장치, TCP 연결과
로컬 조회 API를 조사했다. 아래 시각은 별도 표기가 없으면 KST다.

- 12:15:24 커널에 CH340 USB 시리얼 `/dev/ttyUSB0`가 등록됐고, 12:15:31
  센서 저장기가 `receiving`으로 전환됐다. USB 연결 전 마지막 `stale`은
  12:13:25였다. 12:40까지 추가 `stale` 전환이 없었다.
- 12:40 기준 직전 24시간의 gateway journal에서 운영
  `https://easyrep.kro.kr/v1/edge/sync` HTTP 200 응답 17,063건,
  `Cloud events acknowledged` 2,254건, `Cloud sync delayed` 0건을 확인했다.
  같은 기간 센서 저장기는 `stale`로 30번 전환했다. 따라서 이 관찰에서 확인한
  반복 단절은 ESP32→Pi 수신 구간이다. 웹 로그인 이후 화면은 직접 검증하지 않았다.
- 운영 gateway는 `0.4.16-92e6792d58ff`, `transport=mqtt`, health `ok`다.
  ESP32 `192.168.219.100`→Pi `192.168.219.103:8883` 연결을 확인했다.
  USB 연결이 센서 데이터의 USB 직렬 전송 전환을 의미하지 않는다.
- USB 진단을 115200 baud로 40초간 읽었다. DTR/RTS를 비활성으로 지정했지만,
  포트를 연 직후 12:41:46에 `wifi=0, clock_gate=0, mqtt=0`이 나타났다.
  12:41:51 Wi-Fi 연결, 12:42:06 시간 동기화·MQTT 연결이 확인됐으며,
  이후 12:42:26까지 정상 NET 상태였다. 포트 열기에 따른 자동 리셋 가능성을
  배제하지 않는다. 이 진단 구간을 기존 자연 단절의 증거로 합산하지 않는다.
  로그의 `telemetry_publish_failed`는 0건이었다. 포트는 검사 후 닫았다.
- 포트를 닫은 뒤 12:44:34~12:45:09의 서로 다른 실측 메시지 8건을 로컬
  `/api/air?cage_id=CAGE-001`에서 확인했다. 36.4초 관찰 중 상태는 계속
  `live`, `fresh=true`였고 수신 간격 중앙값 5.060초, 최대 5.061초였다.
  같은 구간 SaaS HTTP 200·이벤트 ACK가 이어졌으며, 마지막 ACK 순번은
  60439였다. gateway·recorder·mosquitto는 모두 active, `NRestarts=0`이었다.

USB 연결 후 개선된 이유를 전원 어댑터·케이블 불량으로 확정하지 않는다.
전원 공급 경로, 재부팅/재접속, 배치 변화가 분리되지 않았고 ESP32 전압·RSSI·
Wi-Fi disconnect reason은 계측하지 않았다. 현재 정상인 USB 전원 연결을 유지하며
재발 시 ESP32 수신 시각과 사이트 ACK 시각을 구분해서 조사한다.
펌웨어 업로드, 운영 설정/코드 변경, 서비스 재시작, 장치 제어, DB 초기화는 하지 않았다.
별도 진단 파일·원시 로그 복사본은 생성하지 않고 이 문서에 결과만 남긴다.

<a id="bb6-actual-20261020"></a>
## 현재 실물 사육장: BB6 센서 저장·USB 카메라 검증 (2026-10-20)

CAGE-001은 **실제 센서·카메라 사육장**이다. 추가 부품을 이용한 펌프·밸브·SAFE
R15 확장은 미완료다. 현재 실행은 `transport=mqtt`, `data_source=sensor`이며
서비스 명령에 `--heartbeat-only`가 없다. 실제 API 응답과 파일을 확인한 상태다.
실측 운영으로 변경하기 위한 설정 전환은 필요하지 않았다. Heartbeat는 연결 상태와
현재 실측 스냅샷을 알리는 통신이며 가상 측정이라는 뜻이 아니다.

실행 환경: `habitat-pi`, 사용자 `<gateway-user>`, Debian 13 (trixie), aarch64.
`docs/HabitatOS_BB6_One_Cage_Expansion.zip`의 매니페스트 28개 파일이 일치했다.
ZIP SHA-256: `8128cbf16c3877c2ceae9148af8043c0e084b4cc525347b68d77911d4d886505`.
패키지 설치 절차의 백업 → 의존성 확인 → 설치 → 신규 3건 검증을 직접 실행했다.
필요 도구가 이미 있어 apt 설치는 하지 않았다. 패키지 원본 ZIP과 운영 코드는
수정하지 않았으며 설치된 도구 사본은 `/opt/habitat-recorder/package-20261020/`에 있다.

현재 핀은 SHT31 SDA21/SCL22, T2 GPIO18, T3 GPIO19다. 개인 설정의
`HABITAT_R15_CENTRAL=0`, `HABITAT_R15_REQUEST_OUTPUTS=0`과 BB6 guard를 유지했다.
ESP32는 별도 전원·Wi-Fi로 통신하며 이번에 빌드·플래시·배선 변경을 하지 않았다.
향후 SAFE J112-8 ARMED의 ESP32 종단과 `r15ArmedPin`을 함께 GPIO27로 변경한다.
T3는 GPIO19를 유지하며, 이번 작업에서는 이 미래 변경을 적용하지 않았다.

### 백업·설치·실수신 증거

- 개인 소스/설정/보고된 빌드 산출물 백업:
  `/home/<gateway-user>/habitat-backups/BB6_BASELINE_20261020_647meeok/`.
  폴더 0700, 파일 0600. `project-source.tar.gz`는 프로젝트 소스도 보존한다
  (가상환경·runtime·cache·Git 제외). `config.h` 실제 내용은 별도 `cage_node/`에 보존했다.
- 기존 시스템 설정과 SQLite 일관성 백업:
  `/root/habitat-bb6-preinstall-csft67kn/`.
  설치기 자체 백업: `/root/habitat-recorder-backup-0d25o62m/`.
- 신규 서비스: `/etc/systemd/system/habitat-sensor-recorder.service`;
  코드: `/opt/habitat-recorder/recorder.py`;
  설정·기존 읽기 계정 인증·공개 인증서: `/etc/habitat-recorder/`.
  인증 파일은 root 소유, 전용 서비스 그룹에만 읽기를 허용하는 0440이다.
- SQLite: `/var/lib/habitat-recorder/telemetry.sqlite3`.
  설치 전 이 저장기 DB는 없었다. 기존 게이트웨이 DB의 실측 957행은 전부
  동일하게 남았고 최종 대조 시 1,023행으로 증가했다. 펌웨어·개인 설정·기존
  게이트웨이 설정/인증·브로커 파일 17개의 해시가 작업 전후 일치했다.
- 증거 폴더:
  `/home/<gateway-user>/.local/state/habitatos/bb6-bringup-20261020-cur0_ykx/`.
  `sensor-verification.json`, `verify-live.log`, `services.log`, `gateway-state.json`,
  `final-checks.json`, `recorder-journal.log`에 실제 실행 결과를 보존했다.

`pi_logger/verify_live.py`는 시작 행 번호 이후의 신규 3건만 선택했다. 별도 읽기
전용 SQL로 같은 ID를 재조회해 시작 시각 이후 수신임을 다시 대조했다.
아래 시각은 **2026-10-20 KST**, 값 순서는 T1 °C / RH1 % / T2 °C / T3 °C다.

| message_id | sampled_at | received_at | T1 / RH1 / T2 / T3 | quality |
|---|---|---|---|---|
| `3838ec81-ceda-4ccc-b157-797f41b9d744` | 04:42:40.000 | 04:42:40.662 | 22.39 / 48.45 / 22.625 / 23.062 | 네 항목 모두 valid |
| `cfcb82a6-f3f0-41ee-9280-b307c458aeb4` | 04:42:45.000 | 04:42:45.701 | 22.35 / 48.49 / 22.625 / 23.062 | 네 항목 모두 valid |
| `92365206-02ce-4fbd-bec0-98fc69db57f0` | 04:42:50.000 | 04:42:50.758 | 22.33 / 48.50 / 22.562 / 23.000 | 네 항목 모두 valid |

저장 서비스는 `active/running`, `enabled`, 자동 재시작 횟수 0이었다. MQTT와
기존 게이트웨이도 active/enabled다. 상태는 `receiving`, SQLite integrity는 `ok`다.
invalid/null 저장은 패키지 회귀시험으로 확인했으며 실물 정상값을 바꾸거나 가짜
측정값을 발행하지 않았다. QoS0 단절 중 측정값 복구를 보장하지 않는다.

### 실제 카메라 촬영

`camera/camera_check.py probe`로 USB `1e45:8022`, Generic USB camera,
`uvcvideo`, serial `200901010001`을 확인했다. 실제 캡처 노드는 `/dev/video0`,
고정 경로는 `/dev/v4l/by-id/usb-Generic_USB_camera_200901010001-video-index0`이다.
`/dev/video1` 메타데이터와 Pi 내부 영상 노드는 제외했다. USB 설명만으로
구매품의 센서 칩이나 실제 화각을 추가 검증한 것은 아니다.

지원 목록의 **모드 5: MJPG 1280×720, 요청 30fps**를 선택했다. 사육장 관찰에
쓸 HD 해상도에서 USB 압축 전송과 영상 stream-copy로 Pi 처리량을 줄이는 선택이다.
기존 게이트웨이의 카메라 리더가 점유 중이라 짧은 촬영 중에만 게이트웨이를 중지하고
`finally`에서 복구했다. MQTT·새 저장기는 계속 동작했고 그 구간에도 새 실측 1건을
저장했다. 기존 녹화 설정/파일을 보존했으며 신규 공개 스트리밍·상시 녹화 서비스를
추가하지 않았다. 기존 녹화의 2GiB 한도와 가득 찼을 때 보존·중지 정책은 유지된다.

촬영 폴더:
`/home/<gateway-user>/.local/state/habitatos/bb6-bringup-20261020-cur0_ykx/camera/20261020_044347_ddazmadx/`.

- `frame.jpg`: 1280×720, 1프레임. 직접 열어 보았으며 거의 검은 영상이었다.
- `clip.mkv`: MJPEG 1280×720, 요청 5초, 실제 4.965초, 디코딩된 37프레임
  (약 7.45fps). 컨테이너의 명목 30fps를 실제 수신 속도로 간주하지 않는다.
- 전체 영상 `ffmpeg -xerror` 디코딩 종료 코드 0. `result.json`, `request.json`,
  `still.log`, `clip.log`, `decode.log`와 USB inventory/지원 모드를 함께 보존했다.
- 촬영 입력에는 `EOI missing, emulating` 경고가 있었으나 명령은 성공했고, 저장된
  영상 전체 디코딩의 오류 로그는 비어 있었다. 경고를 없앴다고 보고하지 않는다.
- 사용자가 소등된 장소임을 확인했다. 파일 수집/디코딩 성공과 피사체·초점 확인을
  구분한다. 밝은 환경에서 시야·초점·FPS를 확인하는 시험은 남아 있다.

### 오류·시험 범위와 남은 항목

설치 직후 추가 검증 래퍼가 DB 생성보다 먼저 조회하여
`sqlite3.OperationalError: unable to open database file`이 1회 발생했다.
서비스는 정상 기동 중이었다. 래퍼에 DB 준비 대기를 적용하고 **재설치 없이**
검증을 다시 실행하여 신규 3건과 무결성 검사를 통과했다. 운영 코드를 수정한 오류가
아니며 임시 래퍼는 작업 종료 시 제거했다.

패키지 저장기 시험은 일반 사용자 실행 시 설치 fixture의 소유자 가정 때문에
14건 중 4건이 실패했다(임시 디렉터리 실제 UID1000, 모의 서비스 UID998,
chown은 mock). 계정·systemctl·경로가 모두 mock임을 확인하고 root에서 원본
시험을 재실행하여 **14/14 통과**했다. 카메라 시험 **6/6**, 독립 회귀 **4/4**도
통과했다. 이들은 실제 촬영·실수신 시험과 별개의 소프트웨어 검증이다.

Pi 재부팅 자동 복구, ESP32 전원 재인가·네트워크 단절 복구, 센서 정확도·장기
안정성, 밝은 환경의 초점/화각/지속 FPS는 미시험이다. SaaS 상태 스냅샷 ACK는
성공하지만 과거부터의 이벤트 이력은 `cloud_continuity_unverified`로 막혀 있다.
이것은 실측/가상 여부와 다른 문제다. 기존 outbox와 sequence를 초기화하거나
서버 수신 순서를 추측해 잠금을 해제하지 않았다. 웹사이트 영상 재생도 이번 범위가 아니다.

<a id="standalone-camera-20261020"></a>
## 별도 실시간 카메라 배포 — 2026-10-20

사용자가 휴대폰·다른 PC에서 별도로 볼 수 있도록 요청하여 Pi 릴리스
`0.4.15-e724b3a0b4e4`를 설치했다. 이전 `0.4.14-5a9bc13f4f2f`는 복구용이다.
GPU·ESP32는 배포하지 않았다. 기존 HTTPS Funnel 주소의 `/camera`에 영상 전용
인증·HLS 플레이어를 추가했다. [접속·인증 안내](../saas-integration.md#standalone-camera)를 따른다.

- 설정 변경: `/etc/habitat-gateway/gateway.toml`의 기존 RGB-001에
  `live_stream=true`; `/etc/habitat-gateway/gateway.env`에 별도
  `HABITAT_CAMERA_VIEWER_TOKEN`. SaaS 영상 업로드는 비활성이다.
- 실제 입력은 기존 USB by-path 장치, MJPG 640×480이며 설정 FPS는 10이다.
  기존 FFmpeg 입력을 공유하고 H.264 HLS를 추가한다. 기존 녹화 한도·미리보기·
  출력 잠금·MQTT 설정은 보존한다. 소등 환경의 영상으로 초점/피사체를 확정하지 않는다.
- 변경 전 비공개 백업: `/root/habitat-live-backup-9yabylcb/`.
  설정·인증·서비스 파일과 SQLite backup을 포함한다.
- 설치 직후 기존 게이트웨이 telemetry 1,757행 보존, 펌웨어·개인 설정·브로커
  파일 14개의 SHA-256 일치, health `ok`, MQTT 연결, 버전 0.4.15를 확인했다.
- 실행 증거: `/home/<gateway-user>/.local/state/habitatos/live-camera-20261020-_4rj_4g0/`.
  `deployment.json`, `install.log`, `tests.log`에 설치와 검사 결과가 있다.
- 접속 파일: `/home/<gateway-user>/.config/habitatos/camera-viewer.html` 및
  `camera-viewer-qr.png`. 파일은 0600, 폴더는 0700. 파일에 포함된 접속 키를
  이 문서·일반 로그·소스에 복사하지 않는다.

추가 코드: `habitat_gateway/camera_viewer.py`, `camera.html`, 고정 hls.js/라이선스,
`tests/contract/test_camera_viewer.py`. 기존 API 시작점·패키지 리소스·릴리스 빌더·
설치기와 관련 배포 시험을 확장했다. 빌더는 개인 `firmware/cage_node/config.h`,
컴파일 결과·중첩 빌드 폴더를 배포 묶음에서 제외하도록 수정했다.

첫 설치는 호출자의 umask 077이 공개 릴리스 디렉터리에 적용되어 서비스의
DynamicUser가 실행 파일에 접근하지 못했다. 설치기가 이전 릴리스로 자동 복구했다.
공개 코드 준비 구간만 umask 022를 사용하고 원래 umask를 복원하도록 설치기를
수정했다. 비공개 설정/백업 권한은 유지하며 재빌드·재설치는 성공했다.
영상 계약·FFmpeg 통합·기존 API/runtime·배포 묶음 111건 통과 후, umask 회귀를
추가한 배포 묶음 35건도 통과했다. 두 묶음의 중복을 합산하지 않는다.

공개 HTTPS에서 비인증 영상 API 401, 인증 후 Secure/HttpOnly 쿠키, RGB-001
목록과 최신 HLS 조각 수신을 확인했다. 실제 H.264 640×480 조각의 20프레임을
전체 디코딩했고 종료 코드는 0이었다. 재생목록 진행, 단일 카메라 FFmpeg 리더,
완료 캐시 8조각(검사 시 약 2MB), 세 서비스 active/enabled를 확인했다.
`live-verification.json`에 저장했다. Pi 온도 61.15°C는 검사 시점의 단일 값이며
장기 부하 시험을 의미하지 않는다.

Pi 자동 검사 Chromium은 로컬/HTTPS 페이지 전환에서 시간 초과로 중단되었다.
별도 Firefox 프로필에서 공개 HTTPS로 다시 검사하여 640×480 영상 재생을
확인했다. 재생 시간은 9.615 → 12.632 → 17.693초, 누적 프레임은 16 → 46 →
97, 버린 프레임은 0이었다. hls.js가 보고한 live-edge 지연은 약 4.03초이며
카메라 센서부터 화면까지 계측한 전체 지연은 아니다. fragment가 제거되고 로그인
폼이 숨겨졌으며 인증 쿠키로 재생했다. `browser-verification.json`과
`camera-browser.png`가 증거다. 캡처를 직접 열어 사육장 내부 물체가 보이는 것도
확인했다. 초기 소등 촬영과 시점이 다르며 초점/화각 교정은 수행하지 않았다.

Pi 재부팅·장시간 재생·브라우저 통신 단절 복구·휴대폰 실물 시험은 별도 확인
항목이다. SaaS 이벤트 연속성 차단은 기존 상태를 유지하며 초기화하지 않았다.

후속 확인에서 ESP32의 센서 수신이 끊긴 상태를 발견했다. 마지막 수신은
2026-10-20 14:31:08 KST, broker에는 keepalive timeout이 있었고 외부 ESP32
연결은 없었다. Pi 센서 저장 서비스와 broker는 active, NRestarts=0이었다.
검증 시작 이후 신규 3건 검사는 35초 안에 수신이 없어 실패했으며 이전 행을
신규로 대체하지 않았다. `sensors-after-live.log`가 해당 결과다. 사용자는 ESP32와
공유기 전원을 확인한 뒤 요청에 따라 ESP32를 재시작했다. 원인 확정이나 펌웨어
수정·재업로드는 수행하지 않았다.

사용자가 재시작 완료를 알린 뒤 신규 3건을 다시 기다렸으나 35초 안에 수신하지
못했다(`sensors-after-esp-restart.log`). 사용자는 Wi-Fi 연결과 센서 상태가 정상이라고
알렸다. 이 관찰을 센서 고장으로 단정하지 않으며, 사용자 보고와 Pi 저장기 수신
결과를 구분한다. USB 진단 로그 수집·펌웨어 변경은 수행하지 않았다.

최종 확인에서 row_id 797, message_id `bf5b0b88-3159-49d9-b32a-e6423c321208`을
확인했다. sampled_at은 15:14:32 KST, received_at은 15:14:34.094 KST다.
T1 23.01°C / RH1 53.08% / T2 22.625°C / T3 22.625°C, 모두 valid였다.
수신 재개 이후 다시 실행한 신규 3건 검사도 35초 안에 채워지지 않았다.
따라서 단발 실수신 재개와 지속 수신 복구를 구분한다. `sensor-final-state.json`,
`sensor-final-live.log`에 기록했다. 이 간헐적 단절은 미해결이며, 저장값을 보정하거나
가짜 메시지로 채우지 않았다. 임시 검사 브라우저·도구·빌드 산출물은 제거했고,
실행 증거와 비공개 접속 파일·백업은 유지했다.

### ESP32 Wi-Fi 통신 재진단 — 2026-10-20 15:42~15:52 KST

사용자가 연결 확인을 요청하여 Pi에서 직접 조사했다. 사용자는 ESP32와 공유기가
같은 방 1~2m 이내임을 확인했고, USB 연결 없이 Wi-Fi 상태 그대로 진단했다.
증거 폴더는 `/home/<gateway-user>/.local/state/habitatos/esp32-link-20261020-z1ldl2uu/`다.

- Pi `192.168.219.103`, ESP32 `192.168.219.104`. ESP32 주소의 ARP 확인은
  유선·무선 경로에서 각각 5회 응답했다. IP ping은 각각 5회 중 0회 응답했으나
  이것만으로 Wi-Fi 미접속이라고 판단하지 않는다. ESP32의 TCP 접속도 관찰했다.
- broker의 ESP32 인증 성공 뒤 keepalive timeout이 반복된다. 15:30:47 접속,
  15:31:11 종료 사례와 인증 전에 90초가량 기다리다 종료하는 사례가 있다.
- 50초간 ESP32 관련 TCP/ICMP 헤더 메타데이터 37건만 수집했다. 암호문을 포함한
  통신 본문은 저장하지 않았다. TCP 중간 순번이 빠진 뒤 뒤쪽 순번이 먼저 도착하고,
  Pi가 같은 ACK를 반복하다 종료하는 동작과 SYN-ACK 재전송을 확인했다.
  ESP32 측 통신 경로에서 데이터가 정상적으로 이어지지 않는 증거이며, 무선 신호·
  공유기 호환·ESP32 드라이버/절전·전원 중 어느 것이 근본 원인인지는 확정하지 못했다.
- Pi→공유기 ping은 eth0/wlan0 각각 10/10 성공, 평균 0.564/5.054ms였다.
  Pi 자체 Wi-Fi 신호는 -17dBm이었다. 이것을 ESP32의 RSSI로 간주하지 않는다.
  Pi 전압/클럭 경고 조회는 `throttled=0x0`; ESP32 전원 품질을 검증한 결과는 아니다.
- Pi의 loopback/LAN 주소에서 CA·호스트 검증을 유지한 TLS 연결이 각각 성공했다.
  인증서 유효기간과 SAN이 맞고, 조회한 방화벽 규칙에 해당 LAN 통신 차단은 없었다.
  broker·gateway·sensor-recorder는 active/enabled, NRestarts=0이었다.
- ESP32 한 주소의 `/32` 반환 경로만 잠시 wlan0로 바꿔 비교했다. ping 0/5,
  신규 3건 검사는 35초 내 수신 없음으로 실패했다. `finally`에서 임시 경로를
  삭제하고 `eth0 src 192.168.219.103` 복원을 확인했다. 기본 경로는 변경하지 않았다.
- 진단 중 row_id 799/800/801이 새로 저장됐다. 마지막 수신은 15:44:36.973 KST,
  T1 23.02°C / RH1 54.60% / T2 22.625°C / T3 22.812°C, 모두 valid였다.
  이후 연속 수신 검사는 실패했으므로 이 세 행을 지속 연결 복구의 근거로 쓰지 않는다.

`initial-state.json`, `network-probe.json`, `packet-metadata.json`,
`pi-tls-firewall.json`, `wifi-path-comparison.json`, `router-path-check.json`,
`latest-state.json`에 결과를 보존했다. 이 진단으로 지속 연결을 복구하지는 못했다.
센서 배선·펌웨어·개인 설정·MQTT 인증/TLS·카메라 설정을 변경하거나 서비스를
재시작하지 않았다. ESP32의 오류·RSSI·재접속 사유가 현재 원격 메시지에 없으므로
Pi 관찰만으로 ESP32 내부 원인을 단정하지 않는다.

### ESP32 통신 지연 재진단 — 2026-10-25 04:11~04:16 KST

사용자는 ESP32가 USB 충전기/전원 어댑터에 연결되어 있고 현재 Pi에 데이터 USB로
연결하기 어렵다고 확인했다. Pi에는 해당 USB 시리얼 장치가 없었다. 펌웨어 업로드,
센서·핀·Wi-Fi·라우팅·TLS·인증 설정 변경 및 운영 서비스 재시작 없이 조사했다.

- Pi는 `NTPSynchronized=yes`, NTP offset +1.454ms, delay 5.990ms였다.
  현재 Pi 시계에서 수십 초 오차는 관찰되지 않았다. ESP32의 현재 NTP 상태나
  측정 당시 시계 오차를 직접 확인한 결과는 아니다.
- Pi→공유기 `192.168.219.1` ping은 8/8 성공, 평균 0.598ms였다.
  Pi→ESP32 `192.168.219.100`은 1/8 응답, 응답 시간 291.735ms였다.
  ICMP 응답률만으로 Wi-Fi 신호 저하나 전원 고장을 확정하지 않는다.
- 같은 ESP32의 TLS 포트 TCP 상태에서도 재전송과 미응답 데이터가 확인됐다.
  04:15:20의 source port 50142 연결은 초기 두 TCP segment 이후 약 85초 동안
  데이터 진행이 없었다. 이후 FIN 재전송이 증가했다. 새 50143 연결에서도
  `rcv_ooopack=3`, `bytes_retrans=484`, 송신 대기 242 bytes와 미확인 segment를
  관찰했다. 따라서 시각 표시 외에 실제 TCP 전달/응답 불안정의 근거가 있다.
  무선 구간·AP·ESP32 Wi-Fi/절전·전원 중 근본 원인은 아직 구분하지 못했다.
- 04:15:20부터 42초 동안 별도 임시 client ID로 동일 telemetry/status topic을
  수신 전용 관찰했다. 실시간 telemetry/status 0건, DB 신규 행 0건이었다.
  임시 subscriber는 종료·회수했으며 메시지를 발행하거나 통신 본문을 저장하지 않았다.

마지막 실제 메시지 `bfb4f6fb-fb28-4d4f-93fa-6ef580849f41`의 시각은 다음과 같다.

| 항목 | 한국 시각 |
| --- | --- |
| payload의 `sampled_at` | 03:56:36 |
| broker의 MQTT 연결 성공 기록 | 03:57:31 (초 단위 로그) |
| recorder의 `received_at` | 03:57:31.375 |
| broker의 keepalive timeout | 03:57:53 |

T1 22.63°C, RH1 61.93%, T2 22.313°C, T3 22.375°C는 모두 valid다.
측정 시각과 수신 시각 차이는 55.375초지만, MQTT 연결이 성립한 같은 초에
수신됐다. 이 차이를 연결 성립 후 MQTT 패킷 전송 시간으로 해석하지 않는다.

소스의 `loop()`는 `time(nullptr)`를 먼저 읽고 `mqtt.connect()`·`mqtt.loop()`를
수행한 뒤 이전 값을 `sampled_at`으로 사용한다. 따라서 연결 전 대기나 loop 내부의
정체가 이 차이에 포함될 수 있다. 설정된 `mqtt.setSocketTimeout(5)`는
ESP32 core 3.3.12의 TLS handshake 기본 120초·TCP/socket 기본 30초를 줄이지 않는다.
MQTT keepalive는 기본 15초이며 broker의 `k15`와 일치한다. 정상 센서 처리의
DS18B20 변환은 800ms 비동기 대기이며 SHT31 각 읽기의 정상 대기는 20ms다.
이 정상 센서 읽기만으로 수십 초 정체를 설명할 근거는 없다.

현재 원본의 setup/loop/센서 helper는 마지막 보고된
`/home/<gateway-user>/habitat-bb6-build.P7T6VG/cache/sketch/cage_node.ino.cpp`와 일치한다.
해당 빌드의 `.ino.bin`과 `_flashed.bin`도 해시가 같지만, 현재 장치 플래시를 직접
대조하지는 않았다. 따라서 소스상 대기 가능성을 현재 장치의 함수별 실행 시간으로
확정하지 않는다.

USB가 가능해지면 Wi-Fi disconnect reason/RSSI, UTC와 monotonic 시각,
MQTT connect/loop/publish 소요시간을 실제 장치에서 대조해야 한다. 기존 NET 로그는
연결 상태와 시계 gate만 제공하여 모든 항목을 직접 측정하지는 못한다.
`sampled_at`만 최신으로 바꾸는 수정은 하지 않았다. 재접속 전에 시작한 DS18B20
변환이 오래됐을 수 있으므로, 그 경우 변환 경과 시간 제한/재측정까지 함께 검증해야 한다.
진단 중 gateway·recorder·broker는 기존 PID와 재시작 0회를 유지했다.

## Verified software status — 2026-10-07

Pi is running release `0.4.14-5a9bc13f4f2f`, and the GPU API source is also 0.4.14.
The installed Pi runtime matches the simulation source; the GPU's nine recorded
source hashes match the checked files. Existing private configurations, credentials
and environment models were preserved. Pi health is `ok` with MQTT connected;
GPU service PID 4040 is active and RTX 4060 CUDA/reconstruction readiness is confirmed.
[Pi installation](../../var/reports/commissioning/software-r15-20261007-pi-014.json),
[GPU application](../../var/reports/commissioning/software-r15-20261007-gpu-014.json).

| Check | Result and scope |
|---|---|
| Actual Pi → GPU | 360 schema 2 CUDA replies across three virtual cages and 120 accelerated virtual minutes; all 360 complete REQ/expected RUN plans validated |
| Wall time / HTTPS latency | 97.068661 seconds; median 0.068625 seconds, maximum 1.925126 seconds |
| Virtual pump | 75 executions; final pump OFF, no open valve, phase `idle` |
| Pi Linux selected regressions | 208 tests and 141 subtests passed in 33.46 seconds; isolated broker cases include old 2s hello and explicit 5s capability/request |
| Environment API fixtures | 3 tests and 38 subtests passed in 2.99 seconds; the tested implementation is unchanged across the version metadata update |
| ESP32 target build | Both sensor and N1 central roles passed with `HABITAT_R15_REQUEST_OUTPUTS=0`; no upload, source hashes unchanged, temporary toolchain removed |

[Integration receipt](../../var/reports/commissioning/software-r15-20261007-integration.json),
[test commands and scope](../../var/reports/commissioning/software-r15-20261007-checks.json),
[ESP32 target receipt](../../var/reports/commissioning/esp32-target-build-20261007.json).
Sensor values, plant response, pump and valves are virtual. The integration run
does not write the production DB, publish MQTT outputs or send SaaS telemetry.
Fault, cancellation, expiry, duplicate and restart checks use separate isolated
test fixtures; they are not physical faults injected into the normal CUDA run.
Only executed virtual RUN intervals feed the next input history. Physical water
volume is unknown. Conditional future plans are retained, but later replanning
changes future actions, so forecast accuracy was not scored in this run.

Physical flashing, GPIO/electrical verification and hydraulic tests remain **0**.
The original Pico BENCH interlock and Pi/ESP output locks remain in place.
Model provenance remains `SYNTHETIC_ONLY`; `field_validated=false` and
`hardware_execution_allowed=false` are unchanged. This release does not
establish real-enclosure forecast accuracy, species suitability or 3D quality.

SaaS heartbeat ACK `2026-10-07T05:42:44.867608Z` is successful with no heartbeat
error, but event continuity remains `blocked` / `cloud_continuity_unverified`.
The original sequence 1 event is preserved; pending events = 1, acknowledged
high watermark = 0, server high watermark is unknown, and event success is null.
Do not guess a server sequence, reset the DB or treat heartbeat success as event
delivery. [Actual cloud status](../../var/reports/commissioning/software-r15-20261007-cloud.json).

## Earlier deployment observations (history)

The camera's optional `expected_model` is configured metadata, not USB hardware
identification. Pi release `0.4.11-7967566bb2ea` added the names of all three configured
cameras as `SMG-A USB-OV5628-A (OV5693, Auto Focus/120deg)`. Each remains
`waiting_usb_port_binding`; actual camera capture and FPS have not been measured.
The seller's exact-SKU UVC/MJPEG/YUY2 mode table is recorded in the verification
record. The corresponding OEM product-family page describes a different lens
option, so its power rating is not used for the purchased AF120 module.

Release `0.4.12-76a2b5356b9c` separates new-ON admission from active-request
safety checks. A normal shared reservation or active request no longer generates
a safety OFF on the next 250ms control tick. Further ON requests remain blocked,
and sensor faults, stale status, link/lease loss and STOP keep their safety handling.
The corrected R15/MQTT checks passed 46 cases; the Pi full suite passed 396 cases
and 231 subtests with 7 dependency-related skips. These use isolated test state and
MQTT packet fixtures, not physical ESP/Pico outputs. See the current verification
record and [deployment evidence](../../var/reports/commissioning/software-r15-20261005-active-reservation-deployment.json).

On 2026-10-06, Pi release `0.4.13-a1337300e296` changed the control screen to
label ON durations as request time, because REQ hold is not pump RUN time.
The related API, LiveScene and handoff checks passed 15 cases and 21 subtests;
installed HTML and gateway code matched the checked files, and configuration,
credentials and the pending SaaS event remained unchanged. Physical outputs
and the R15 bridge remain disabled. See [Pi evidence](../../var/reports/commissioning/software-r15-20261006-request-semantics-deployment.json).
The GPU was offline during that update; at the time its last verified version was
0.4.12 and matching 0.4.13 deployment on both hosts was unverified. The 0.4.14
verification above supersedes that deployment status.

Schema 2 request/RUN planning was initially unverified development source after
the UI release. The installed 0.4.13 file hashes and earlier 38-case request-fixture
check did not cover its revised Linux regressions, ESP32 target builds or CUDA
round trip. Those checks now have the separate 2026-10-07 evidence linked above.
Earlier results remain historical evidence and are not reclassified as schema 2
results. Version strings alone do not establish matching source.

## Assembly review — 2026-10-04

The user confirmed that all 12 original HWP items have been acquired but remain unassembled.
Use the [illustrated assembly guide](../hardware-design/assembly-guide.html),
[Markdown guide](../hardware-design/assembly-guide.md), and
[verification record](../hardware-design/assembly-verification.md) together.
The R8 PDF includes a different camera model and extra purchases; it is not the final assembly authority.
The new DS18B20 conversion checks and ROM diagnostics passed host regression checks only.
This revision has not been flashed or electrically tested on the real ESP32 boards.
The sensor role supports one SHT31 and two DS18B20 probes per cage. The same sketch
now includes an optional N1 central R15 request bridge, disabled and output-locked
by default. Its pin map, session/expiry/duplicate/STOP contract and Pi adapter are
implemented; see the [R15 bridge contract](../protocols/r15-bridge.md).
A second SHT31 still needs implementation and verification. The central request
bridge's earlier 3000ms request-limit revision passed software and ESP32 target-build
checks, but has not been flashed or electrically commissioned on real ESP/Pico
hardware. Those earlier builds do not verify the new 5000ms request-limit source;
the latter has its own two-role target build on 2026-10-07, linked above. Neither
target build has been flashed or electrically commissioned on a physical board.

## Installed profile and scope

The first assembly stage uses the user's ORIGINAL purchase HWP (12 rows, filename
without `(1)`) and their existing Raspberry Pi **5**. The later
`HabitatOS_750000원_나머지_구매목록(1).xlsx` is the current stage-two purchase review;
the earlier `(2).xlsx` is preserved as an earlier draft.
R8 is a wiring reference, not authority to add its extra purchases or reinstall its
older non-TLS wireless software. Pico H is inventoried in stage one. The SAFE R15
circuit and J112 pin contract are defined in the supplied R15 documentation; actual
central wiring, flashing and hydraulic commissioning remain pending. The original
Pico BENCH interlock and all request-output locks remain in place.
USB data/power cables, suitable supplies and mounting tools absent from the original
HWP must be checked as available prerequisites, not represented as delivered items.

`/etc/habitat-gateway/gateway.toml` maps CAGE-001/002/003 to ESP32-001/002/003 and RGB-001/002/003.
Each node reads one SHT31 (T1/RH1) and two DS18B20 probes (T2 hot/T3 cool).
The former heater/fan demonstration policies are absent from this profile.
Engineering RH bands 45–55, 60–70, 75–85% and temperature 23–29°C are simulation settings;
they are not a universal husbandry prescription. Different species need separately chosen settings.

`habitat-gateway.service` and `mosquitto.service` start on boot. The old user heartbeat service
is disabled only after the full gateway passes health checks. The original user release and
configuration remain available for rollback. No simulated measurements enter production SaaS.

## Operator commands

In each Pi terminal, define the following temporary shell function before using the
`habitat` commands in this guide. Do not assume that a permanent wrapper is installed
or that a non-interactive SSH shell has the same aliases or PATH.

```sh
habitat() {
  sudo /opt/habitat-gateway/current/venv/bin/python \
    /opt/habitat-gateway/current/edge_tools.py "$@"
}
habitat status
```

The existing tool reads protected credentials in place and never prints the tokens.
`sudo` may ask for the Pi user's password. `habitat cameras` discovers connected USB
devices. `habitat gpu-test` sends an explicitly synthetic
30-minute input to the GPU for each configured cage and checks 5/10/30/60-minute results;
it neither inserts sensor history nor operates hardware.

## Connect the incoming parts

1. 현재 BB6 ESP32-D0WD-V3: SHT31 SDA=GPIO21, SCL=GPIO22;
   DS18B20 T2=GPIO18, T3=GPIO19. 과거 DevKitC의 GPIO13/14 안내로 되돌리지 않는다.
   Each DQ needs its own 4.7kΩ pull-up to 3.3V. Use three-wire powered probes and common ground.
   Follow the supplied Fritzing wiring. Do not connect the 24V misting supply to sensor GPIO.
2. 현재 ESP32는 이미 실측을 보내고 있으므로 저장기·카메라 설치 때문에 재업로드하지 않는다.
   새 노드를 준비할 때만 `firmware/cage_node/cage_node.ino`를 classic ESP32용으로 빌드한다.
   Dependencies: Espressif ESP32
   Arduino core, Adafruit SHT31 Library with Adafruit BusIO, OneWire, PubSubClient.
   Copy the matching private `/home/<gateway-user>/.config/habitatos/nodes/ESP32-00N/config.h` into
   a temporary sketch folder, then flash the corresponding node. These headers contain Wi-Fi
   and node credentials and must stay outside the repository and shared release.
   MQTT uses TLS port 8883, node-specific credentials and topic ACLs. Never disable certificate verification.
   If the Pi's Wi-Fi was unavailable during provisioning, fill Wi-Fi fields locally. Reserve the Pi's LAN IP.
3. Plug OV5693 USB cameras into the powered hub's data ports. Run `habitat cameras`.
   Connect one camera at a time to identify its persistent USB path, then run:
   `habitat bind-camera RGB-001 /dev/v4l/by-path/ACTUAL-PATH-video-index0` (repeat for 002/003).
   Mapping requires the real device path and cannot be guessed before delivery.
   The service retries a missing/reconnected camera. Initial snapshots are 640×480 every 30 seconds.
   If capture fails, inspect `v4l2-ctl --list-formats-ext -d /dev/videoN` and set a supported size.
4. Inspect `habitat status`. Missing nodes show no telemetry, disconnected sensors report null/invalid,
   and absent cameras show waiting states. No values or images are fabricated.

### USB camera check (2026-10-20)

One physical camera enumerated as `1e45:8022 Generic USB camera` through
`uvcvideo`, with capture node `/dev/video0` and stable path
`/dev/v4l/by-path/platform-xhci-hcd.0-usb-0:1:1.0-video-index0`.
This USB description alone does not confirm the purchased sensor model.
V4L2 advertised MJPEG at 1920×1080 / 30 FPS and continuous autofocus.
A bounded five-second MJPEG capture received 46 frames (about 9 FPS under the
current conditions), exited successfully, and produced a decoded 1920×1080
still. The enclosure was visible but dark and blurred. FFmpeg reported
`EOI missing, emulating`; sustained capture quality and 30 FPS are not verified.
The temporary still was inspected and removed; no video archive was retained.

After the owner confirmed CAGE-001, the existing `bind-camera` command registered
that USB path as RGB-001. Its first restart exposed a permissions bug: the tool
replaced the previously readable gateway TOML with a root-only 0600 file, causing
`gateway_configuration_unreadable` under the system service's DynamicUser.
The live TOML's original 0644 permissions were restored and the service restarted
successfully. Credentials remain in their separate protected environment file.
Only RGB-001's device binding changed in the configuration.

Automatic operation was verified at the configured 640×480 resolution:
`preview_ready`, `recording=running`, two preview timestamps 30.01 seconds apart,
and HTTP 200 for the authenticated JPEG endpoint. The first completed MJPEG MKV
was 59.904 seconds / 10,091,011 bytes and readable by FFprobe. Recordings remain
under `/var/lib/habitat-gateway/cameras/recordings/RGB-001/`; the temporary copy
of the preview used for inspection was removed. The image remains dark and needs
lighting/placement adjustment. The existing 2 GiB archive limit and 1 GiB free-space
threshold still pause recording without deleting older clips.

The service is active/enabled, with MQTT connected and zero restarts after repair.
RGB-002 and RGB-003 remain unbound. SaaS heartbeat ACKs were confirmed, while event
upload still reports `cloud_continuity_unverified`; no continuity override was
applied. Website video display and behavior recognition were not verified.

The source `deploy/edge_tools.py` now preserves configuration ownership and mode
on binding and rollback, with regression coverage for 0644, 0640 and 0600.
The targeted permission, camera-state and FFmpeg integration checks passed:
**9 passed, 27 deselected**. An initial broader run was terminated with exit 143
before producing a final result and is not counted as a pass.
The installed immutable 0.4.14 release was not rewritten or repackaged; the tool
fix belongs in the next release. Until then, another binding with the installed
tool requires restoring the TOML's prior access permissions before restarting.

## Prediction and commissioning

After 30 consecutive fresh minute samples, the Pi requests **shadow predictions**.
The model still has SYNTHETIC_ONLY training provenance and hardware_execution_allowed=false.
Forecasts, identity, timestamp, expiry and horizons are validated. GPU failures do not block
sensor collection, local recording or SaaS sync. Shadow results are in
`/var/lib/habitat-gateway/environment/status.json` and the authenticated `/v1/environment` endpoint.
Expired results remain historical records; they never become actuator commands.
The deployed 0.4.14 source sends schema 2 with the exact R15 timing profile. An older GPU
may reject it; such a failure must remain a failure, not fall back silently to the
historical schema 1 or generate hardware commands.

Each cage keeps its planned `mister` slot to preserve the existing SaaS v1 contract, which
requires at least one actuator configuration. `hardware_outputs_enabled=false` blocks ON and
automatic mode locally; observations remain null and the reason is `hardware_not_commissioned`.
These slots do not imply that the ESP32 currently drives the central pump/valves.
During sensor-only commissioning, shadow forecasts assume zero mist and no manual/external water.
Water interlocks are uncommissioned, so proposals are vetoed. Enabling outputs or observing any
active actuator blocks inference with `waiting_measured_mist_history` until measured mist
history is integrated; command intent is not an acceptable substitute for delivered water.

During initial commissioning, the empty-actuator profile returned SaaS 422;
reusing the existing planned actuator schema with null observations and the
explicit blocked reason returned 200 without changing SaaS credentials or code.
This historical result does not resolve the current event-sequence conflict.
The continuity guard introduced in 0.4.10 still preserves and blocks unverified
events in 0.4.14 while the same Pi service sends heartbeats. The current heartbeat
and blocked event state are recorded at the top of this guide. Restoring event delivery requires verified server
sequence information or the original database and an audited reconciliation.
New R15 status/metadata compatibility on the operating SaaS is unverified.
See [SaaS recovery conditions](../saas-integration.md).

The central Pico/SAFE R15 pin map and request contract are documented. Historical
schema 1 uses ideal virtual RUN candidates of 1/2/3 seconds. Revised schema 2 uses
REQ candidates of 2000/3000/4000/4500/5000ms and maps each complete 60-minute plan
forward through `r15_esp20_pico_window1ms_phase0_v1` before the environment model
receives the RUN plan. `selected_plan.request_hold_ms` contains 60 strict integers
in 0..5000 (zero means no request); `expected_virtual_run_s` contains the paired
phase-0 expectations in 0..3 seconds. The first proposal must match both arrays.
Pi sends its REQ value, not `pulse_seconds`, as the mapped command's `duration_s`.

Only our ESP REQ ceiling increases to 5000ms; original Pico RUN remains limited
to 3000ms. New hello advertises `max_request_hold_ms=5000`; a missing capability
means 3000ms, and Pi rejects a longer hold before publication. Deploy Pi first
with all output locks retained. Never clamp a rejected request or issue a fresh
ON identity to replace a failed or missing ACK. Admission TTL remains at most
5000ms, heartbeat freshness remains 1000ms, and recycle remains 7000ms.
RUN stops independently at 3 seconds even while REQ is HIGH. The virtual valve
drains for 1 second after pump stop; a new request also waits for REQ LOW stable
20ms, WINDOW LOW and the 7-second recycle guard. Request receipt, pump stop,
REQ LOW and release are distinct events. ARMED/LEVEL HIGH can result from an
unpowered/open line and cannot prove powered hardware or successful execution.

Schema 2 records the planning expectation, actual fixture receipt-phase
expectation and executed virtual RUN intervals separately. Next-minute history
uses only those executed intervals. Water volume remains unknown. Full future
plans are retained, but closed-loop replanning changes their execution conditions,
so the run is not scored as fixed-plan forecast accuracy. The bridge implements
bounded leases, STOP, duplicate/reconnect handling and shared-station reservation;
the virtual controller checks single-pump sequencing and injected interlock faults.
These checks do not prove real GPIO timing, Pico RUN duration, protection or water
flow. ESP request-hold time is not a measurement of RUN or delivered water. Actual
wiring, maximum-on/cooldown/STOP/water interlocks, startup and nozzle flow must be
commissioned after assembly. Measure sensor bias and choose species-specific bands;
collect real sensor/action logs and validate the model on held-out real runs before
enabling physical automatic misting.

The same revised 0.4.14 source has been verified on Pi and GPU as recorded above.
To repeat the checks, run from the Pi development checkout with the existing
protected GPU environment loaded. The commands below are a rerun recipe; the
dated receipts record the completed invocation and results. Use a new path under
the project's `var/data/simulation/` so previous results are preserved. The
simulator copies the configuration in memory, uses isolated virtual device/database
state, and does not publish MQTT or SaaS.

```sh
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/integration/test_shared_misting.py \
  tests/unit/test_r15_timing.py tests/unit/test_environment_timing.py \
  tests/unit/test_release_cleanup.py tests/contract/test_environment.py \
  tests/test_r15_bridge.py tests/test_saas_reference.py \
  tests/integration/test_r15_mqtt_loopback.py

.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/integration/test_api.py -k environment

.venv/bin/python -B -m apps.worker.simulate_misting \
  --gateway-config /etc/habitat-gateway/gateway.toml \
  --plant-module experiments/environment_sim/predictive_misting.py \
  --timing-mode r15_request_fixture \
  --output-dir <new_result_path> --minutes 120
```

Record actual source hashes, host, reply schema/profile, complete selected plans,
execution intervals, fault/STOP/restart/duplicate outcomes and final virtual OFF.
Keep output locks and the production database/configuration unchanged. Physical
timing and model accuracy still require the assembly measurements described above.

## Completed isolated integration simulation (2026-10-02)

The development checkout now contains `apps.worker.simulate_misting`, the shared-pump
`MistingCoordinator` and `VirtualMistingTransport`. This simulator uses the actual Gateway
command/ACK/lease path, real HTTPS CUDA inference, and synthetic sensor/plant inputs. It
cannot construct MQTT or cloud writers. It does not change the installed sensor-only release.
The existing uncalibrated plant is an explicitly provided fixture, not measured enclosure
physics. Executed virtual pulse intervals, including interrupted fractional seconds, become
the next history input. Delivered water volume remains unknown.

On the actual Pi: 120 accelerated virtual minutes, 360 CUDA responses, 57 virtual pulses;
all three cages received pulses, one valve at a time, and final outputs were off. A separate
trace audit confirmed ordered valve-on/pump-on/pump-off/valve-off transitions and no
overlapping pump executions. Real wall duration was 576.583 seconds, median HTTPS round
trip 1.422 seconds, maximum 1.642 seconds. These are not two hours of physical operation.
The Pi test suite passed 212 tests (two dependency deprecation warnings), including injected
leak/low-water/STOP/link-loss/sensor faults, restart, expiry and duplicate handling. Those
fault tests use explicit prediction fixtures; they are not physical fault tests.

Receipts: `/home/<gateway-user>/.local/share/habitatos/simulation/shared-pump-20261002/`.
The production database, GPIO, MQTT outputs and SaaS telemetry were not used by this run.
GPU weights remain on the GPU; training provenance remains `SYNTHETIC_ONLY`.

## Pi 기존 환경 통합 모의실험 재실행 (2026-10-04)

실행 위치는 실제 Pi `habitat-pi`(aarch64, Python 3.13.5)의
`/home/<gateway-user>/Desktop/habitat`와 기존 `.venv`다. Windows에서는 `fcntl` 모듈이 없어
테스트 수집이 중단되었고, 이를 제거하거나 모의 잠금으로 대체하지 않고 Pi에서 실행했다.
`fcntl` 오류는 파일의 잠금 해제가 필요한 상태가 아니라 운영체제 API 차이다.

실행 전 `test_shared_misting.py`, `test_environment.py`, `test_commissioning.py`,
`test_control.py`의 **41개 테스트가 0.66초에 통과**했다. 이 테스트들은 명시적 예측
fixture로 제어·계약·장애 처리를 검사하며 실제 GPU 추론 횟수에 포함하지 않는다.
모의실험 진입점·공용 펌프 코드·공용 펌프 테스트·Plant 소스·Plant 설정의 SHA-256은
현재 Windows 정본과 일치했다.

그 후 보호된 기존 GPU 인증환경을 읽고 `apps.worker.simulate_misting --minutes 60`을
실행했다. 요청은 기존 GPU HTTPS API로 전달했으며 mock 예측이나 로컬 재학습으로
대체하지 않았다. 결과는 다음과 같다.

| 항목 | 이번 실행 결과 |
|---|---:|
| 통합 실행 상태 | PASS |
| 가상 사육장 | 3개 |
| 준비용 가상 이력 | 29분 진행 후 30개 입력 시점 |
| 이후 가상 제어 기간 | 60분 |
| 실제 GPU 예측 응답 | 180회 |
| 응답의 예측 시점 | 5·10·30·60분 |
| 모델 ID | `synthetic-mlp-7d56293563ff` |
| 응답에 기록된 GPU | NVIDIA GeForce RTX 4060 |
| 실제 경과 시간 | 41.2335초 |
| HTTPS 왕복 중앙값 / 최대 | 0.060297초 / 2.103904초 |
| 가상 분무 실행 | 31회 |
| CAGE-001 / 002 / 003 분무 횟수 | 8회 / 8회 / 15회 |
| CAGE-001 / 002 / 003 실행 합계 | 28초 / 38초 / 90초 |
| 마지막 상태 | 펌프 OFF, 열린 밸브 없음 |
| 실행 중 기록된 실패 | 0건 |

실험 시작 직전의 Pi UTC 시각은 `2026-10-04T09:06:08Z`였다. 시뮬레이터 내부
가상 날짜는 기존 재현 조건인 2026-10-02부터 시작한다. 이를 실제 실행 날짜나 실측
센서 날짜로 해석하지 않는다. GPU 응답의 신선도 검사에는 별도로 현재 시각을 사용한다.

원본 결과는 Pi의 `var/data/simulation/shared-pump-20261004/` 한 폴더에 보관한다
(실행 후 `du -sh` 기준 2.8M). 운영 DB와 별도 SQLite, 요청/응답, 환경 변화,
분무 실행, 출력 전이 기록을 포함한다. PC로 원본을 복제하거나 ZIP을 만들지 않았다.
이번 실행은 운영 서비스를 재배포·재시작하지 않았다. 실행 전후 운영 서비스는
active, PID 2703이었고 `gateway.toml` SHA-256도 동일했다.

별도 읽기 전용 감사 코드로 원본 기록을 다시 계산하여 **PASS**를 확인했다.
31개 실행의 실제 가상 시작·종료 시각에서 지속시간을 재계산했고, 중복 command ID와
펌프 실행 겹침은 없었다. 124개 출력 전이가 밸브 ON → 펌프 ON → 펌프 OFF →
밸브 OFF 순서와 일치했으며 요청·제어 큐의 순서도 유지됐다. 180개 응답의 요청 ID,
사육장·매장 ID, 모델 ID, 네 예측 시점과 60개 trace의 제안·실행값을 대조했다.
**5,400개 이력 슬롯**의 분무시간이 요청한 시간이 아니라 해당 구간에서 가상 펌프가
실행한 시간과 일치했다. 지연시간의 중앙값·최대값도 원본에서 재계산했다.
이 감사는 결과 기록의 정합성 검사이며 GPU 커널 실행을 별도 프로파일링한 것은 아니다.

이 결과는 **실제 Pi·GPU에서 제어 흐름이 연결됨**을 검증한다. 센서값과 환경 반응,
펌프·밸브는 가상이다. Plant 계수는 미실측 가정이고 모델의 학습 출처는
`SYNTHETIC_ONLY`다. 실제 분무량·전력·사육장 예측 정확도·종별 적합성·임계값 대비
개선률을 이번 결과로 주장하지 않는다. 누수·수위·비상정지 등 장애 주입은 앞의
별도 fixture 테스트에서 검사했으며, 이번 60분 정상 운전 중 주입한 것은 아니다.
실물 ESP32 펌웨어, MQTT 무선 구간, 배선·전원, 실제 펌프와 카메라/3D 복원은
이 모의실험의 시험 범위에 포함하지 않는다. GPIO·MQTT 출력·SaaS 데이터 전송도 없다.

재실행은 Pi 프로젝트 루트에서 다음처럼 수행한다. GPU 인증환경은 기존 보호된
환경파일에서 로딩하며 출력하거나 문서에 복사하지 않는다. 출력 경로는 기존 결과를
덮어쓰지 않는 새 경로여야 한다.

```sh
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/integration/test_shared_misting.py tests/contract/test_environment.py \
  tests/integration/test_commissioning.py tests/test_control.py

.venv/bin/python -B -m apps.worker.simulate_misting \
  --gateway-config /etc/habitat-gateway/gateway.toml \
  --plant-module experiments/environment_sim/predictive_misting.py \
  --timing-mode desired_run_ideal \
  --output-dir <새_실험결과_경로> --minutes 60
```

결과의 `scope` 문자열만으로 실행 위치를 판단하지 않는다. 현재 시뮬레이터는 Pi/CUDA
범위를 고정 문자열로 기록하므로, 다른 PC에서 실행할 경우 실제 호스트·아키텍처와
실행 위치를 따로 기록해야 한다. 이번에는 실제 Pi에서 실행했음을 직접 확인했다.

USB RGB snapshots alone do not create LiveScene geometry. A reconstruction scan needs overlapping
views, calibrated intrinsics/poses and suitable masks/state labels. Three fixed cameras in separate
cages are three separate scenes. Keep the existing static geometry and update environmental state;
do not reconstruct every snapshot. The reconstruction backend was unconfigured
at this historical run; later 0.4.10 activation is recorded in the
[GPU operation guide](gpu-service.md). Environment prediction readiness still
does not prove reconstruction quality or actual enclosure capture readiness.

## 연속 영상과 크레스티드 게코 학습 자료 (2026-10-03)

구매품 확인 정정 (2026-10-04): 최초 HWP의 [상품번호 15668138](https://www.devicemart.co.kr/goods/view?no=15668138)은
SMG-A **OV5693 USB 카메라 모듈 (Auto Focus/120°) [USB-OV5628-A]**다.
판매 사양은 5MP, 자동초점, 시야각 120°, USB 2.0이다. 같은 센서를 사용하는
Waveshare OV5693(A)의 렌즈·FPS 사양을 이 구매품의 사양으로 적용하지 않는다.
지원 해상도별 FPS, 영상 형식, 초점 잠금 지원은 도착한 모듈의 V4L2 정보로 확인한다.
120°의 수평/수직/대각 구분과 왜곡 계수는 확인되지 않았으므로 시야각 표기만으로
카메라 내부 파라미터를 확정하지 않는다. 사용 해상도·초점 조건에서 렌즈를 보정한다.

운영 입력은 **사육장별 고정 카메라 한 대**다. 고정 영상은 검출·추적·행동 분석의
입력으로 사용하며, 같은 시점의 프레임을 늘리는 것만으로 COLMAP/Nerfacto에 필요한
다시점 관측이 생기지 않는다. [COLMAP 공식 촬영 지침](https://colmap.github.io/tutorial.html#structure-from-motion)도
서로 다른 위치의 겹치는 시점을 요구한다. 완전 고정 운영에서 단안 깊이 모델을
사용한다면 보이는 표면의 깊이는 **모델 추정**으로, 미관측 뒤쪽은 미관측으로 표시한다.
실측 치수로 만든 사육장 형상과 영상으로 복원한 형상도 구분한다. 같은 카메라를
설치 전에 이동시켜 초기 스캔하는 방식은 별도 선택지이며, 상시 고정 영상만으로
완전한 자유시점 복원이 검증됐다고 보고하지 않는다.

0.4.2는 카메라별 `record_video = true`를 지원한다. 장치 연결이 확인되기 전에는
`waiting_usb_port_binding` 또는 `waiting_camera`로 대기한다. 실제 영상이 없으면
프레임이나 행동 판정을 만들지 않는다. 첫 종은 크레스티드 게코이며 개체 ID는 실제
개체를 확인한 다음 부여한다.

카메라 도착 후 기존 `bind-camera` 명령으로 USB 포트와 사육장을 대응시킨다. 먼저
`v4l2-ctl --device <고정 USB 경로> --list-formats-ext`로 MJPEG, 해상도, FPS 지원을
확인한다. 현재 기본 요청은 640×480, 10 FPS, 60초 클립이며 행동 인식에 충분한
설정으로 검증된 값은 아니다. 혀·먹이 등 작은 동작이 보이는지 실제 영상으로 확인하고
해상도/FPS/노출/조명을 조정한다. 지원되지 않는 형식은 오류 상태로 남으며 임의의
정상 영상으로 대체하지 않는다.

`/etc/habitat-gateway/gateway.toml`의 각 `[[cameras]]`에서 설정한다.

```toml
record_video = true
fps = 10
segment_s = 60
archive_max_mb = 2048
min_free_mb = 1024
```

설정 변경 후 서비스를 재시작한다. 카메라 한 대당 FFmpeg 프로세스 하나가 장치를
읽으며, 같은 입력으로 MKV 기록과 기존 30초 간격 미리보기를 만든다. 별도 카메라
프로세스를 동시에 띄우지 않는다. [FFmpeg segment muxer](https://ffmpeg.org/ffmpeg-formats.html#segment_002c-stream_005fsegment_002c-ssegment)를 사용한다.

영상은 `/var/lib/habitat-gateway/cameras/recordings/<camera_id>/<session>/`에 저장된다.
`segments.csv`의 구간 시간은 미디어 PTS이고 `session.json`의 UTC는 프로세스 시작
시각이다. 둘의 차이를 측정하기 전에는 센서와 영상이 프레임 단위로 동기화됐다고
주장하지 않는다. 처리 완료된 클립만 학습 자료로 옮기고, 실제 영상 속 개체와 촬영일을
확인해 기록한다. 촬영일은 프로젝트 전체에서 같은 시간대(Asia/Seoul)를 쓴다.

한도는 카메라별이며 5초 주기의 검사 사이에 초과량이 발생할 수 있다. 한도 도달이나
디스크 여유 부족 시 `archive_full`로 멈추고 기존 클립은 삭제하지 않는다. 자료를
검증된 저장소로 옮겨 공간을 확보하면 다음 주기에 수집이 재개된다. 계속 운영하려면
영상 이관·보존 작업도 수행해야 한다. 현재 GPU 자동 영상 업로드·행동 추론·SaaS 표시까지
구현된 상태는 아니다. 강제 전원 차단으로 끝나지 않은 마지막 클립은 별도로 검사한다.

관찰 행동 라벨의 첫 기준은 다음과 같다. 자동 규칙이 아니라 검수자가 영상을 보고
부여하는 학습 정답이다. 한 구간의 동시 행동은 `labels` 배열에 함께 넣는다.

| 라벨 | 영상으로 확인할 내용 |
|---|---|
| moving | 몸통 위치가 변하는 이동 |
| climbing | 벽·가지 등을 발로 붙잡고 올라가거나 내려가는 동작 |
| stationary | 관찰 가능한 상태에서 몸통 이동이 없음; 수면이라는 뜻은 아님 |
| eating | 먹이 섭취 동작이 직접 확인됨; 먹이 근처 접근만으로 부여하지 않음 |
| licking | 혀가 물방울·물체·신체에 닿는 동작이 보임; 갈증 판정이 아님 |
| hide_entry / hide_exit | 은신처의 관찰 가능한 경계를 통과해 들어감/나옴 |
| other_visible | 보이지만 현재 행동 정의에 해당하지 않는 구간 |
| unobservable | 가림·화면 밖·빛 부족으로 행동 관찰 불가 |
| uncertain | 검수 후에도 행동을 확정하지 못함 |

수면·질병·배고픔·갈증은 이 행동 라벨에 포함하지 않는다. 이후 환경·급이·급수 이력과
확인된 상태 자료를 결합하는 별도 과제다. 질병·탈수·굶주림을 유도해 자료를 만들지 않는다.

학습용 manifest는 `species: "Correlophus ciliatus"`와 `clips` 목록을 갖는다. 각 clip에는
`file`(manifest 아래 상대 경로), `sha256`, `subject_id`, `enclosure_id`, `capture_day`,
`session_id`, `split`(train/validation/test), `annotator`, `reviewer`, `annotations`가 필요하다.
각 annotation은 `start_s`, `end_s`, `labels`를 갖는다. 예: 시작 1초, 끝 3초에
`["moving", "climbing"]`. 미라벨 구간은 학습에서 제외하며 정상/무행동 정답으로 쓰지 않는다.

```sh
/opt/habitat-gateway/current/venv/bin/python -m habitat.vision.behavior_dataset /path/to/manifest.json
```

이 검사는 다른 검수자 확인, 구간 범위, 실제 파일 해시·영상 길이, 개체·사육장·촬영일·세션·
동일 영상의 분리 여부를 확인한다. 통과는 데이터 형식/분리 검증이며 모델 정확도 검증이 아니다.
인식기는 RGB 특징과 자세의 시간 변화를 받는 causal TCN을 우선 비교 대상으로 삼는다.
관찰 불가 구간을 분리하고 행동별 F1, 시간당 오탐, 행동 구간 오차를 새 개체·사육장·날짜에서
측정한 뒤 배포한다. 프레임을 무작위로 섞어 높은 정확도를 만드는 분할은 사용하지 않는다.

## 복원 추천 실험의 해석

GPU `run_reconstruction_study.py collect-learning-data --output <새 경로>`는 기존 정적
Nerfacto 설정을 재사용한다. 같은 학습 스케줄에서 1,000/2,000/3,000/4,000/5,000/7,500/
10,000스텝을 저장하고 PSNR·배경 PSNR·SSIM·LPIPS를 기록한다. 평가 중 난수 상태를
복구하여 평가가 다음 학습의 표본 추출을 바꾸지 않도록 한다. 현재 파일명 스텝은 0부터
시작하는 Nerfstudio 기준이며 실제 업데이트 수는 별도 `updates_completed`에 남긴다.

시점 비교의 첫 실험은 공통 사진 15장에 후보 사진 한 장을 달리한 네 구성이다.
초기 가중치 해시와 2,000스텝 예산을 같게 맞춘다. 후보 RGB는 정답 생성에만 사용한다.
이는 같은 초기 가중치에서 다시 학습한 고정 예산 비교이며, 학습 중인 모델에 새 사진을
추가한 효과를 검증한 것은 아니다. 현재 공개 문 장면 하나의 개발용 자료이므로 추천기를
학습하거나 새 사육장 성능으로 발표하지 않는다. 같은 장면의 체크포인트를 나누어 학습·
시험 표본 수가 늘어난 것처럼 세지 않는다.

여러 실제 사육장 자료가 생기면 스텝 추천은 초반 품질 곡선에서 이후 LPIPS/SSIM을
예측하는 작은 신경망, 위치 추천은 현재 관측 특징·후보 자세에서 실제 품질 변화를 예측하는
신경망으로 학습한다. 고정 촬영/고정 스텝과 같은 예산에서 비교하고, 품질 예측 오차와
후보 선택으로 잃은 품질을 보고한다. 모델을 쓰지 않은 정답 직접 비교는 **실험 분석**이지
학습된 추천 기능이 아니다. 기록된 경과 시간에 작업 일시정지가 포함된 실행은 속도
벤치마크로 사용하지 않는다.

교수님 피드백의 주 실험은 계속 **실제 온습도/분무 이력 → GPU 5·10·30·60분 예측 →
후보 분무 계획 비교 → Pi 실행 → 센서 재관측**이다. 수동/임계값/예측 기반 제어를
동일한 외란·목표 범위에서 비교하고, 온습도 MAE, 범위 이탈 시간, 실제 분무량·횟수,
개입 횟수를 기록한다. 센서 8/6/4/2/1 실험은 실제 확보한 센서 구성 안에서 수행하며
입력에서 뺀 위치도 독립 참조 센서로 평가해야 한다. 같은 날짜의 미래 데이터가 학습에
들어가지 않도록 분리하고, 합성 실험과 실측 결과를 별도로 보고한다. 3D의 실측 점·공간
추정·미래 예측을 구분하며, 검증 전 개선률이나 완료 날짜를 만들지 않는다.

## Rollback

For a prior full gateway release, use the verified release installer with its previous config.
To return to the original heartbeat-only setup: stop/disable system `habitat-gateway.service`, then
enable/start user `habitat-heartbeat.service` as <gateway-user>. Never run both SaaS senders simultaneously.
Keep runtime databases and private configuration; do not delete them during rollback.

References: Raspberry Pi camera software documentation, Eclipse Mosquitto authentication/manual,
Espressif Arduino NetworkClientSecure documentation. Firmware and real USB modes require hardware
verification when delivered; software test receipts describe only the checks actually completed.
