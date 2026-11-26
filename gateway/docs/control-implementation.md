# 설계서와 현재 제어 구현의 대응

기준: `HabitatOS 국제학회 논문·설계서 업데이트 심층 리서치.pdf`, 24쪽. 이 PDF는 기존 설계서 v0.2와 논문계획 v0.3를 비교한 연구·설계 업데이트 문서입니다. 구현 시 별도의 Google Drive 원본을 변경하지 않았습니다.

## 현재 구현 범위

```text
센서·출력 장치
      ↕
ESP32 Cage Node          ← 현재는 프로세스 안의 가상 노드
      ↕ MQTT
Raspberry Pi 5 Store Edge Gateway
  ├─ 메시지 수신·검증          transport.py / models.py
  ├─ 사육장·장치·정책 설정      config.py
  ├─ 안전 검사·제어 정책       gateway.py
  ├─ 명령·센서·감사 이력       store.py
  └─ 상태·제어 API           api.py
```

| PDF의 요구 | 위치 | 구현·검증 상태 |
|---|---|---|
| Pi는 여러 Cage를 담당하는 Store Gateway | p.3, p.17 | 사육장별 설정·토픽·상태 분리. 두 사육장 간 제어·ACK 격리 테스트 |
| ESP32 센싱·actuation·local interlock, Pi 정책·aggregation | p.3, p.17 | Pi 정책·제어 구현. 로컬 interlock은 시뮬레이터와 펌웨어 규약까지 작성 |
| MQTT 명령 lifecycle, local safety 유지 | p.1, p.3 | request UUID, 증가 sequence, TTL, QoS 1, non-retained, 노드 ACK, 재시작 시 미확인 명령 격리 |
| 센서·장치 상태와 revision 동기화 | p.18–19 | 측정 시각, 수신 시각, 센서 품질, geometry/placement revision 저장. 행동 이벤트·model revision 연결은 후속 범위 |
| measured/estimated/predicted 구분 | p.4–5, p.16 | 현재 제어는 원시 센서 snapshot만 사용. 보간·예측 없음. 가상 데이터 출처를 명시 |
| Store/GPU/SaaS failure domain 분리 | p.3, p.7, p.18 | Pi 로컬 서비스는 GPU·SaaS 없이 실행. 물리 안전 지속성은 향후 ESP32 구현·E7 실험 필요 |
| E3 latency·loss·duplicate·stale 검증 | p.11 | 중복·stale·ACK·만료의 소프트웨어 동작 테스트. p50/p95/p99 실측 미수행 |
| E7 장애 격리 실험 | p.13 | 시뮬레이션 연결 단절·로컬 타이머·센서 장애·명령 역순·재시작 테스트. 실제 fault injection 미수행 |

## 주요 구현 결정

- 기본 transport는 `simulated`. GPIO/시리얼 접근은 없습니다. 실제 MQTT 모드는 설정과 인증정보가 필요합니다.
- 초기 DB는 SQLite WAL입니다. PDF의 기존 Pi 최소 배포에 나오는 PostgreSQL과는 다르며, DB 모듈을 분리해 추후 변경할 수 있게 했습니다.
- 실제 명령 대상은 예제로 정의한 heater/fan/mister/light입니다. 사용자가 실제 보유·연결한 하드웨어 목록으로 확정한 것은 아닙니다.
- 자동제어는 대표 센서의 히스테리시스와 유한 작동시간·cooldown을 사용합니다. 공간 보간 기반 정책, PID, 조명 스케줄은 포함하지 않습니다.
- 각 프로세스 시작 시 manual 모드로 진입합니다. 이전 자동 모드나 미확인 명령을 자동으로 재개하지 않습니다.
- 중앙 API·네트워크가 장치별 물리 안전장치를 대신하지 않습니다. 명령 ACK가 없는 경우 실제 출력을 추정하여 성공으로 표시하지 않습니다.

## 이후 실제 연결에 필요한 작업

1. ESP32 보드, 센서 버스·ID, 릴레이 active level, 핀, 장치 정격 및 배선을 확정합니다.
2. 실제 센서 수집·릴레이 출력·로컬 제한시간·watchdog·중복/역순 방지를 갖춘 ESP32 펌웨어를 구현합니다.
3. 보드와 Pi의 시각 동기화, 인증된 MQTT 연결, 실제 데이터의 품질·revision·측정 시각을 확인합니다.
4. 동물 없는 환경에서 최대 작동시간, 센서 분리, broker/Pi 재시작, 연결 단절 시 출력을 검증합니다.
5. E1 센서 신뢰성과 E3/E7 실측 프로토콜로 결과를 수집합니다. 현재 소프트웨어 테스트 통과를 논문 실험 결과로 사용하지 않습니다.

실제 운영의 장기 이력 보관·삭제·백업, PostgreSQL, SaaS 수신 서버/웹 연결, 영상/AI, 공간추정과 3DGS는 별도 구현 범위입니다. Pi의 SaaS 전송/재전송은 이후 추가했으며 [연동 규격](saas-integration.md)에 구현 범위를 기록했습니다.

## 매장별 배포 추가

버전 0.2.0에서 공통 프로그램 릴리스, 매장별 설정 생성, Pi별 인증키, systemd 서비스 설치, 업데이트 시 DB 백업 및 실패 복구, SSH 기반 순차 배포를 추가했습니다. 설치 경로와 사용법은 [매장별 배포 안내](deployment.md)에 있습니다. 이후 작업 트리에 SaaS 송신 기능을 추가했으므로 새 배포에는 릴리스를 다시 빌드해야 합니다. 기존 dist 묶음에는 이 기능이 없습니다.
