# Pi Compute 클라이언트의 점진적 구현 계획

2026-09-19. 사용자 제공 Engineering Goal은 루트 AGENTS.md에 보존했다.

## 기존 상태와 재사용

- `habitat_gateway`는 제어·MQTT·SQLite·SaaS 송신을 제공하며 GPU 실행/업로드 구현은 없다.
- 기존 CLI, config, API, 명령 제한·중복 처리·SaaS 대기열을 유지한다.
- `docs/gpu/gpu-api-contract.md` v1.0.0의 요청·응답을 따른다. 새 GPU 토픽이나 SaaS 이벤트를 임의로 추가하지 않는다.
- 공통 입력 모델과 URL/토큰 검사는 기존 구현을 재사용하거나 공통 모듈로 추출한다. 실제 GPU worker는 데스크톱 인계 범위다.
- Git 저장소/히스토리가 없는 현재 작업 디렉터리다. 기존 dist·구매 문서·설정·테스트를 무조건 이동/삭제하지 않는다.
- 기존 MQTT 토픽은 `node_topic`에서 관리한다. Engineering Goal의 토픽 예시 때문에 이미 전달한 v1 규약을 조용히 변경하지 않는다.

## 구현 경계

| 경계 | 책임 |
|---|---|
| `apps/worker` | config loading, dependency wiring, CLI, worker lifecycle |
| `habitat/compute` | GPU 계약, 로컬 사진 등록, 업로드/작업/결과 흐름, HTTP adapter |
| `habitat/persistence` | 제어 DB와 독립된 Compute 작업 SQLite 및 파일 보존 |
| `habitat/common` | 기존 코드와 공유할 stateless 모델/입력 검증 |
| `configs/examples` | GPU worker 설정 예시; 실제 설정은 외부 경로 가능 |
| `tests/unit`, `tests/contract`, `tests/integration` | 새 기능의 정식 검증 |

업로드·파일 해시·결과 다운로드는 제어 프로세스에서 실행하지 않는다. worker는 별도 프로세스로 실행하며 제어 DB를 열거나 ESP32 출력에 접근하지 않는다. 기본 GPU 전송은 비활성화다. 매장/cage/revision은 기존 게이트웨이 설정에서 읽어 중복 설정을 줄인다.

## 내구성과 실패 처리

- 사진은 입력 폴더에서 worker 소유 저장소로 복사하고 해시를 확정한다. 파일과 UUID를 보존한 뒤 네트워크 요청을 시작한다.
- capture_id/job_id를 SQLite에 보존한다. 재시도·재시작은 같은 ID를 사용한다.
- backend URL은 첫 전송 전에 작업에 바인딩한다. 다른 서버로 무심코 기존 작업을 재전송하지 않는다.
- 응답의 매장·Pi·사육장·revision·파일 ID·크기·해시를 검증한다.
- 결과 다운로드는 계약에 정의된 상대 경로만 사용하고 제한 크기·해시 확인 후 확정한다.
- 전송 오류는 재시도 간격과 상태를 저장한다. 인증/계약/입력 오류는 조용히 폐기하거나 빠르게 무한 반복하지 않는다.
- 실패/중단된 GPU 작업을 성공으로 만들거나 자동으로 새 job_id로 재실행하지 않는다.

## 호환성과 배포

기존 실행 명령과 `config/` 파일을 계속 지원한다. 제어 DB와 SaaS JSON 계약은 변경하지 않는다. 신규 runtime은 개발 시 `var/data/compute`에, 운영 시 별도 StateDirectory에 둔다. 새 worker도 모든 매장에 같은 wheel로 설치하고 설정만 다르게 제공한다. 배포 예제와 기존 릴리스에 새 기능이 포함되지 않는다는 점을 문서화한다.

## 검증·완료 근거

설정/계약 검증, 여러 매장 동일 코드 실행, 파일 변경·해시 오류, 응답 scope 위조, 중복/재시작, 업로드·다운로드 중단, 다른 host/경로 유도 거절, 잘못된 artifact, 로컬 제어 독립성, CLI와 HTTP 왕복을 검사한다. 기존 테스트도 실행한다. 실제 GPU 서버 URL/토큰과 Tailscale 등록이 없으면 모의 통신 결과를 실복원 완료로 보고하지 않는다.
