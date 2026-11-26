# HabitatOS Cage Node ↔ Store Gateway MQTT v1

이 규약은 현재 저장소에서 새로 정의한 구현 규약입니다. PDF의 역할·명령 수명주기·로컬 안전 원칙을 구체화했으며, 기존 ESP32 펌웨어와의 호환성은 아직 검증하지 않았습니다.

## 토픽

접두사는 `habitat/v1/{site_id}/cages/{cage_id}/nodes/{node_id}`입니다. ID에는 영문·숫자·`_`·`-`만 사용합니다.

| 끝부분 | 방향 | QoS | retain |
|---|---|---|---|
| `/telemetry` | ESP32 → Pi | 1 | false |
| `/command` | Pi → ESP32 | 1 | **false** |
| `/ack` | ESP32 → Pi | 1 | false |
| `/status` | ESP32 → Pi | 1 | true |

노드 상태는 `{"online":true}`이고 Last Will은 `{"online":false}`입니다. Pi의 상태 토픽은 `habitat/v1/{site_id}/gateways/{gateway_id}/status`입니다. MQTT 5 broker가 필요합니다. 명령에는 `MessageExpiryInterval`도 설정합니다. payload TTL 검증은 ESP32에서 별도로 수행합니다.

브로커 ACL로 각 노드는 자기 telemetry/ack/status만 쓰고 자기 command만 읽게 제한합니다. 게이트웨이 계정만 command를 발행합니다. API 인증과 MQTT 인증은 서로 다른 자격 증명입니다.

## Telemetry 예

```json
{
  "schema_version": 1,
  "data_source": "sensor",
  "message_id": "f706b252-ae93-4e1a-8a59-142cd7b8b42e",
  "sampled_at": "2026-09-18T00:00:00+00:00",
  "geometry_revision": 1,
  "placement_revision": 1,
  "readings": {
    "T1": {"value": 24.2, "quality": "valid"},
    "T2": {"value": 24.5, "quality": "valid"},
    "T3": {"value": 24.0, "quality": "valid"},
    "T4": {"value": 23.8, "quality": "valid"},
    "T5": {"value": 24.1, "quality": "valid"},
    "RH1": {"value": 65.0, "quality": "valid"},
    "LUX1": {"value": 100.0, "quality": "valid"}
  },
  "actuators": {"heater": false, "fan": false, "mister": false, "light": false}
}
```

단위는 설정 파일의 센서 정의에서 고정합니다. 온도 `degC`, 습도 `percent_rh`, 조도 `lux`입니다. `quality`는 `valid`, `invalid`, `crc_error`, `disconnected` 중 하나입니다. 유효하지 않은 측정은 `value=null`이어야 합니다. DS18B20의 초기값/오류값을 정상 측정으로 발행하지 않습니다.

현재 BB6 센서 펌웨어는 자세한 실패 단계를 **115200 baud USB 직렬 로그**에
남긴다. MQTT v1의 topic/payload/quality는 바꾸지 않으며 실패한 값은 계속
`null/invalid`로 전송한다. `SENSOR_PINS`는 실제 코드가 사용하는 SDA·SCL·T2·T3
GPIO를 부팅 때 출력하고, `SENSOR`는 첫 측정 완료 후와 이후 30초마다 출력한다.

센서 GPIO는 노드별 비공개 `config.h`에서 설정한다. 사육장별 소스 복사본을
만들지 않는다. 네 설정을 모두 생략하면 기존 30핀 배치를 유지하며, 변경할
때는 네 값을 함께 지정한다. 아래 38핀 배치는 사용자 제공
`CAGE002_003_BB6_38pin.pdf` 1·3·25쪽 기준이다. 핀 수만으로 자동 선택하지 않는다.

| 설정 | 기존 배치 / Cage001 기본값 | 새 배치 / Cage002·003 |
| --- | --- | --- |
| `HABITAT_SHT_SDA_PIN` | 21 | 25 |
| `HABITAT_SHT_SCL_PIN` | 22 | 26 |
| `HABITAT_T2_PIN` | 18 | 32 |
| `HABITAT_T3_PIN` | 19 | 33 |

```cpp
// Cage002 / Cage003 private config.h; identities and MQTT credentials stay node-specific.
#define HABITAT_SHT_SDA_PIN 25
#define HABITAT_SHT_SCL_PIN 26
#define HABITAT_T2_PIN 32
#define HABITAT_T3_PIN 33
#define HABITAT_R15_CENTRAL 0
#define HABITAT_R15_REQUEST_OUTPUTS 0
```

펌웨어는 현재 classic ESP32용이다. 부분 설정·중복 핀과 flash/UART/strapping/
입력 전용 핀은 빌드에서 거부한다. 이 센서 펌웨어의 R15 옵션 두 개는 계속 0이어야
한다. 특히 새 센서 배치의 25·26·32·33은 R15 중앙 제어와 충돌하므로 함께 켜지 않는다.
설정 변경은 해당 노드의 재빌드·업로드가 필요하며 Pi GPIO나 MQTT schema 변경은 없다.
설정 없는 기존 노드는 같은 GPIO를 계속 사용한다. 업로드 후 `SENSOR_PINS`와
새 실측·Pi 저장·SaaS ACK까지 확인해야 물리 배선 검증을 완료한 것으로 본다.

- `i2c44`, `i2c45`: 기존 I²C 버스에서 0x44/0x45 주소에 데이터 없이 응답을
  확인한 Wire 반환값이다. ESP32 core 3.3.12에서 0은 ACK, 2는 주소 NACK,
  5는 timeout, 4는 그 밖의 오류다. 두 확인은 기존 transaction timeout
  (기본 50ms)을 사용하며 다른 GPIO나 전체 I²C 주소를 검색하지 않는다.
- `sda`, `scl`, `dq_t2`, `dq_t3`: 확인 시점의 디지털 입력 LOW/HIGH다.
  **센서 공급 전압·접촉 상태·풀업 저항을 계측한 값이 아니다.**
- `sht`: `init_failed`, `read_failed`, `out_of_range`, `ok`로 SHT31 초기화와
  읽기 단계의 실패를 구분한다. `read_failed`만으로 CRC와 전원 문제를 구분하지 않는다.
- `T2`, `T3`: `not_detected`, `unexpected_family`, `rom_crc_error`,
  `multiple_devices`, `lost_before_power_check`, `external_power_not_reported`,
  `lost_before_conversion`, `conversion_not_started`, `conversion_incomplete`,
  `lost_before_read`, `scratchpad_crc_error`, `out_of_range`, `ok`를 구분한다.
  외부 전원이 보고되지 않았다는 진단도 VDD 전압 측정을 대신하지 않는다.

로그는 기존 센서 validation의 결과를 설명하며, ROM CRC·단일 프로브 조건·외부
전원 응답·변환 완료·scratchpad CRC·측정 범위 검사를 우회하지 않는다.
비밀번호와 MQTT 인증값은 출력하지 않는다. 직렬 포트를 열면 보드에 따라 자동
리셋될 수 있으므로 운영 중 관찰과 의도한 재부팅 시험을 구분한다.

`sampled_at`은 **측정 시각**입니다. 재전송할 때 현재 시각으로 바꾸면 안 됩니다. 시각은 timezone을 포함하는 UTC를 권장합니다. 같은 MQTT 메시지를 재전송할 때 동일 `message_id`를 유지합니다. 더 오래된 샘플은 이력에 저장하되 최신 제어 입력을 덮어쓰지 않습니다. Retained telemetry는 제어 입력에 사용하지 않습니다.

센서값은 실측입니다. IDW/RBF 공간추정이나 미래 예측값을 이 필드에 넣지 않습니다. 센서별 비동기 수집은 측정 시각을 보존한 별도 메시지로 설계 확장이 필요합니다. 현재 제어 입력은 같은 수집 주기의 **전체 snapshot**을 전제로 하므로 필수 센서가 빠지면 ON이 차단됩니다.

## Command 예

```json
{
  "schema_version": 1,
  "command_id": "f78b7a17-a590-49a5-b145-cf5e17cf03dd",
  "sequence": 42,
  "site_id": "STORE-001",
  "gateway_id": "PI-001",
  "cage_id": "CAGE-001",
  "node_id": "ESP32-001",
  "actuator_id": "fan",
  "action": "on",
  "duration_s": 5,
  "created_at": "2026-09-18T00:00:00+00:00",
  "expires_at": "2026-09-18T00:00:10+00:00",
  "geometry_revision": 1,
  "placement_revision": 1,
  "source": "manual"
}
```

`expires_at`은 **실행 시작 기한**입니다. 실행 시간은 `duration_s`이고, ESP32는 실행 직후부터 자체 monotonic timer로 제한합니다. 타이머를 Pi나 MQTT에 의존하면 안 됩니다. Gateway와 Node의 시계가 맞지 않거나 신뢰할 수 없으면 노드는 ON을 거절합니다.

노드에서 필요한 동작:

1. 정확한 site/cage/node/gateway, 장치 ID, JSON 타입·범위, revision을 확인합니다. Retained command를 거절합니다.
2. 만료 명령을 거절합니다. 게이트웨이 재연결과 무관하게 검사합니다.
3. 처리한 `command_id`는 결과를 재응답하며 **출력을 다시 작동하거나 타이머를 연장하지 않습니다.**
4. `(gateway_id, actuator_id)`별 마지막 `sequence` 이하의 새 명령을 거절합니다. 늦게 도착한 이전 ON이 더 최근의 OFF를 뒤집으면 안 됩니다. 마지막 sequence와 중복 방지 정보는 재부팅을 고려해 보존해야 합니다. 같은 command_id의 다른 payload도 거절합니다.
5. ON에 대해 노드 자체의 센서 품질·최신성·온습도 한계·최대 작동시간·cooldown을 검사합니다. Pi가 보낸 duration이 로컬 제한보다 길면 거절합니다. OFF는 센서 이상 상태에서도 처리합니다.
6. 실행 후 ACK를 보내고 실제 출력 상태를 telemetry에 반복 보고합니다. 소프트웨어 출력 상태와 물리적인 릴레이 접점 상태는 별도 피드백 센서가 없으면 동일하다고 보장할 수 없습니다.
7. 통신이 끊겨도 로컬 타이머·interlock·watchdog를 계속 실행합니다. 부팅·센서 장애 시 출력 정책과 독립 과열 차단은 실제 장치에 맞춰 검증합니다.

현재 시뮬레이터는 주요 명령·로컬 타이머·센서 interlock을 검증하는 대역입니다. ESP32의 하드웨어 watchdog, 플래시 내구성, 재부팅 후 중복 방지, 실제 시간 동기화를 검증한 펌웨어가 아닙니다.

## ACK 예

```json
{
  "command_id": "f78b7a17-a590-49a5-b145-cf5e17cf03dd",
  "actuator_id": "fan",
  "status": "applied",
  "applied_state": true,
  "occurred_at": "2026-09-18T00:00:00.100000+00:00",
  "reason": ""
}
```

`status`는 `applied` 또는 `rejected`입니다. 거절 시 `reason`에 `local_sensor_invalid` 등 원인을 기록합니다. `applied`에는 실제로 설정한 출력 상태가 필수입니다. ON/OFF 요청과 ACK 상태가 다르면 Pi는 실행 완료로 취급하지 않습니다. 늦은 ACK는 감사 로그에 남기고 만료된 명령을 성공으로 바꾸지 않습니다. 최신 물리 상태는 이후 telemetry로 갱신합니다.

Pi의 상태 흐름은 `publishing → published → applied/rejected`입니다. ACK 대기시간이 지나면 `expired`, 프로세스 재시작 또는 불확실한 전송 실패는 `interrupted`입니다. 사전 검사에서 실패한 명령은 바로 `rejected`로 기록됩니다.
