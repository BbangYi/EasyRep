# HabitatOS Engineering Goal

> Codex가 HabitatOS에서 작업할 때 따라야 하는 아키텍처, 구현, 테스트,
> 배포 및 유지보수 원칙.

HabitatOS는 단일 Raspberry Pi용 일회성 프로토타입이 아니라 여러 매장과
다수 사육장에 동일한 코드베이스를 배포하는 **Edge--GPU--SaaS
시스템**으로 개발한다.

## 1. Project Vision

``` text
HabitatOS SaaS (habitatos.kro.kr)
        |
   Site / Store
        |
Raspberry Pi 5 Store Edge Gateway
        |
      Rack
        |
   Enclosure(s)
        |
 ESP32 Cage Node(s)
```

확장 계층은
`Organization → Site/Store → Rack → Enclosure → Device → Sensor/Actuator`를
기본으로 한다.

각 매장의 Raspberry Pi 5는 Store Edge Gateway, 각 사육장의 ESP32는 Cage
Controller로 동작한다. 고부하 연산은 GPU Compute Node로 분리한다.

확정된 배포 구조: 매장당 Pi 1대, 별도 SaaS PC, 별도 GPU PC.
모든 Pi에 같은 프로그램을 배포하고 매장 ID·인증정보·사육장 구성과
SaaS/GPU 주소를 각각 설정한다. SaaS와 GPU를 같은 호스트로 가정하지 않는다.

## 2. Core Engineering Principles

기능은 단순히 실행된다는 이유만으로 완료로 판단하지 않는다.

-   명확한 책임 분리
-   높은 응집도와 낮은 결합도
-   재사용성과 테스트 가능성
-   장애 격리
-   배포 및 확장 가능성
-   장기 유지보수성

객체지향은 목적이 아니라 책임 분리와 교체 가능성을 위한 수단이다. 작은
stateless utility까지 불필요하게 class로 만들지 않는다.

## 3. Single Codebase Principle

매장별 소스 복사본을 만들지 않는다.

금지 예:

``` text
habitat_store1/
habitat_store2/
gateway_store1.py
gateway_final.py
gateway_new.py
```

모든 Store Gateway는 동일한 versioned release를 사용한다. 매장별 차이는
`site_id`, `gateway_id`, cage/device mapping, sensor placement, network,
control policy 등의 configuration으로 관리한다.

``` text
HabitatOS v1.4.0
 ├─ Store A + Config A
 ├─ Store B + Config B
 └─ Store C + Config C
```

새 Pi 설치를 위해 source code를 수정하지 않는다.

## 4. Target Repository Architecture

``` text
habitat/
├── apps/
│   ├── gateway/
│   ├── api/
│   └── worker/
├── habitat/
│   ├── devices/
│   ├── telemetry/
│   ├── control/
│   ├── messaging/
│   ├── vision/
│   ├── digital_twin/
│   ├── compute/
│   ├── saas/
│   ├── persistence/
│   └── common/
├── firmware/
│   └── cage_node/
├── configs/
│   ├── defaults/
│   ├── schemas/
│   └── examples/
├── models/
│   └── manifests/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── hardware/
├── scripts/
├── migrations/
├── docs/
│   ├── architecture/
│   ├── hardware/
│   ├── protocols/
│   └── operations/
├── deploy/
│   ├── docker/
│   ├── systemd/
│   └── install/
├── var/
│   ├── log/
│   ├── data/
│   ├── cache/
│   └── tmp/
├── pyproject.toml
├── compose.yaml
├── .env.example
├── .gitignore
└── README.md
```

이는 목표 구조다. 빈 디렉터리·class·interface를 미리 대량 생성하지
않는다. 실제 책임이 필요할 때만 만든다.

## 5. Application Layer

`apps/`에는 실행 entrypoint만 둔다. Business/domain logic은 `habitat/`
package에 둔다. `apps/`는 configuration loading, dependency wiring,
lifecycle, startup을 담당한다.

## 6. ESP32 Firmware Boundary

실제 sensor/actuator driver는 `firmware/cage_node/`가 소유한다.

ESP32 책임: - DS18B20, SHT31, BH1750 등 센서 입력 -
fan/mist/heating/cooling 출력 - sensor validation - watchdog - safety
interlock - local fallback control - Gateway communication

Pi는 ESP32 telemetry를 처리한다. Pi와 ESP32의 책임을 혼합하지 않는다.

## 7. Store Gateway Responsibility

Raspberry Pi 5는 단일 cage 전용 컴퓨터가 아니라 Store Edge Gateway다.

주요 책임: - ESP32 device management - telemetry ingestion/validation -
MQTT - local persistence - store orchestration - control policy - camera
management - edge AI inference - GPU Compute Node communication - SaaS
synchronization - health monitoring

## 8. Safety and Fault Containment

``` text
CRITICAL: ESP32, sensor validation, safety interlock, actuator safety, local fallback
IMPORTANT: Store Pi Gateway, telemetry, local DB, orchestration
NON-CRITICAL: GPU, behavior analytics, 3D reconstruction, Digital Twin/SaaS visualization
```

Internet, SaaS, GPU, 3DGS 또는 AI inference 장애가 critical local safety
control을 불필요하게 중단시키지 않는다.

## 9. Messaging and Contracts

MQTT topic/payload schema를 코드 여러 곳에 독립적으로 하드코딩하지
않는다. 중앙에서 관리하고 schema version을 둔다.

``` text
habitat/v1/{site_id}/{gateway_id}/{device_id}/telemetry
habitat/v1/{site_id}/{gateway_id}/{device_id}/state
habitat/v1/{site_id}/{gateway_id}/{device_id}/command
habitat/v1/{site_id}/{gateway_id}/{device_id}/ack
```

ESP32↔Pi, Pi↔Compute, Pi↔SaaS 변경에는 contract test를 적용한다.

## 10. GPU Compute Boundary

특정 GPU PC에 직접 결합하지 않고 `compute/` abstraction과 명시적 job/API
contract를 사용한다.

예: `submit_reconstruction`, `submit_heavy_inference`,
`submit_thermal_registration`, `get_job_status`, `get_artifact`.

Backend는 local GPU desktop, workstation, university server, cloud GPU
등으로 교체 가능해야 한다.

## 11. Vision and Behavior

``` text
Camera Capture → Live Streaming → Detection → Tracking → Behavior Recognition
```

Live stream과 영구 저장은 분리한다. Pi inference 여부는 accuracy, FPS,
latency, CPU utilization, temperature, system impact benchmark 후
결정한다.

## 12. AI Model Management

`best.pt` 같은 경로나 파일명을 business logic에 하드코딩하지 않는다.
대용량 weight를 Git에 무분별하게 저장하지 않는다.

Model manifest에서 model id, version, task, artifact URI/checksum,
runtime configuration을 관리한다.

## 13. Digital Twin

Static geometry와 dynamic environmental state를 분리한다.

사육장 구조 변경 시
`RGB Scan → Pi → GPU Compute → COLMAP → 3DGS → geometry_revision`을
수행한다.

평상시에는 reconstruction을 반복하지 않고 기존 geometry 위에 measured
temperature, spatial estimate, humidity, thermal surface temperature,
gecko position/behavior, actuator/device state를 갱신한다.

실측값, 공간추정값, 미래예측값을 데이터와 UI에서 구분한다.

## 14. SaaS Boundary

Store Gateway는 `habitatos.kro.kr`과 명확한 API/MQTT contract로
통신한다. URL을 business logic 곳곳에 하드코딩하지 않는다.

## 15. Configuration and Secrets

Repository에는 defaults, schemas, examples만 둔다. 실제 Store config는
`/etc/habitatos/` 같은 source 외부 경로에 배포 가능하게 한다.

Password, API token, MQTT credential, private key, Wi-Fi password를
Git에 commit하지 않는다.

## 16. Runtime Artifact Separation

사용자 요청(2026-10-03): 개발 소스는 `Desktop/HabitatOS` 한 곳에서 관리한다.
바탕화면에 실험별 폴더·날짜별 복사본·검증 ZIP을 만들지 않는다.
명시적으로 배포/내보내기를 요청할 때만 `dist/`에 패키지를 만든다.
테스트 임시파일은 종료 시 제거하고, 결과는 필요한 요약만 기존 문서에 남긴다.
GPU의 데이터·체크포인트·영상은 Windows에 중복 다운로드하지 않는다.

로그, 영상, CSV, 모델 출력, cache, temporary file을 source tree에
저장하지 않는다.

개발 runtime은 `var/log`, `var/data`, `var/cache`, `var/tmp`로 분리하고
기본적으로 Git에서 제외한다.

## 17. Test Management

`test1.py`, `test_new.py`, `test_final.py`, `temp_test.py` 같은 파일을
계속 만들지 않는다.

반복 가능한 검증은 `tests/unit`, `tests/integration`, `tests/contract`,
`tests/hardware`에 통합한다.

일회성 diagnostic script는 꼭 필요한 경우만 `scripts/`에 명확한 이름으로
만들고, 재사용 가치가 없으면 제거한다.

## 18. File Creation Rule

새 파일 전에 확인한다.

1.  기존 module로 해결 가능한가?
2.  기존 파일의 책임에 포함되는가?
3.  동일/유사 구현이 이미 있는가?
4.  재사용되는 코드인가?
5.  production/test/operational/diagnostic 중 무엇인가?
6.  어느 architecture boundary가 소유하는가?

기존 구현이 있다면 병렬 구현을 만들지 말고 확장 또는 리팩터링한다.

## 19. Dependency Direction

Domain logic이 MQTT library, DB driver, SaaS endpoint 같은
infrastructure에 직접 강결합되지 않도록 명확한 client/adapter boundary를
사용한다. Circular dependency를 만들지 않는다.

단, 실제 교체 가능성이나 책임 경계가 없는 곳에 이론적인 abstraction
layer를 불필요하게 추가하지 않는다.

## 20. Incremental Refactoring

현재 repository를 목표 구조로 한 번에 rewrite하지 않는다.

구조 변경 전에 current tree, entrypoints, imports/dependencies,
duplicates, temporary scripts, runtime artifacts, tests, configuration,
hardcoded values, dead code를 분석한다.

대규모 변경 전 migration plan을 작성하고 기존 기능/테스트를 유지하며
점진적으로 개선한다.

## 21. Deployment

Store별 source 복붙 대신:

``` text
Git Repository → Versioned Release → Artifact → Deployment
                                      ├─ Store A + Config A
                                      ├─ Store B + Config B
                                      └─ Store C + Config C
```

장기적으로 install, config validation, upgrade, rollback, health
verification을 자동화 가능하게 한다.

## 22. Documentation

Architecture, API, MQTT contract, schema, configuration, hardware
mapping, deployment, safety policy, Digital Twin contract, Compute job
contract 변경 시 관련 문서를 함께 갱신한다.

## 23. Definition of Done

-   [ ] 책임이 올바른 module에 위치한다.
-   [ ] 기존 구현을 먼저 검토했다.
-   [ ] 불필요한 중복 구현이 없다.
-   [ ] Store-specific value가 하드코딩되지 않았다.
-   [ ] secret이 commit되지 않았다.
-   [ ] 필요한 test가 정식 test suite에 통합되었다.
-   [ ] cross-system contract 변경 시 compatibility 검증이 있다.
-   [ ] 임시 script/file을 제거했거나 유지 이유가 명확하다.
-   [ ] runtime artifact가 source와 섞이지 않는다.
-   [ ] GPU/SaaS/Internet 장애가 critical local control을 불필요하게
    중단시키지 않는다.
-   [ ] 다른 Store Gateway에도 source 수정 없이 배포 가능하다.
-   [ ] 관련 config/schema/API/docs가 갱신되었다.
-   [ ] 로그/오류가 진단에 유용하고 secret을 노출하지 않는다.
-   [ ] contract/config 변경 시 migration/backward compatibility 영향을
    검토했다.

## 24. Codex Working Procedure

비단순 작업은 다음 순서를 따른다.

1.  **Inspect** --- 관련 기존 코드, 구조, test, config, interface를 먼저
    읽는다.
2.  **Reuse** --- 새 구현 전에 기존 module 확장 가능성을 확인한다.
3.  **Plan** --- 책임 boundary, 영향 interface, test, migration impact를
    정한다.
4.  **Implement** --- 요구사항을 만족하는 가장 작은 coherent change를
    수행한다.
5.  **Test** --- 필요한 unit/integration/contract/hardware test를
    실행하거나 추가한다.
6.  **Clean** --- 작업 중 만든 임시파일, debug code, 중복 구현, 불필요한
    artifact를 정리한다.
7.  **Verify** --- 기존 동작의 unintended regression을 확인한다.
8.  **Document** --- architecture/config/schema/API 영향이 있으면 문서를
    갱신한다.
9.  **Report** --- 변경 파일, 생성/삭제 파일, 실행 test와 결과, contract
    변화, 남은 risk를 요약한다.

## 25. Current Repository Migration Safety

현재 repository에 실험 script, 임시 test, 중복 기능, runtime artifact가
존재할 수 있다.

단순히 지저분해 보인다는 이유로 즉시 삭제/이동하지 않는다.

정리 전 반드시: - 참조 여부 확인 - entrypoint 영향 확인 - test 영향
확인 - Git history/현재 사용 여부 확인 - 대체 구현 존재 여부 확인

그 후 안전하게 삭제, 이동, 통합 또는 deprecate한다.

------------------------------------------------------------------------

## Final Rule

**새 코드를 추가하는 것보다 기존 구조를 이해하는 것을 우선한다.**

**동작하는 코드를 무조건 재작성하지 않는다.**

**일회성 prototype 편의를 위해 장기 architecture를 훼손하지 않는다.**

**반대로 미래 확장만을 이유로 현재 필요하지 않은 abstraction과
infrastructure를 미리 만들지 않는다.**

HabitatOS의 목표는 코드가 많아지는 것이 아니라, 기능이 증가해도 구조가
이해 가능하고 검증 가능하며 여러 Store Gateway에 동일하게 배포 가능한
시스템을 유지하는 것이다.
