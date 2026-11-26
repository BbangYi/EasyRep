# Pi Compute 0.3.0 검증 기록

2026-09-19, Raspberry Pi 5 / Debian 13 / aarch64 / Python 3.13.5.

## 이번 작업의 범위

사용자가 요청한 Pi GPU 클라이언트를 기존 GPU API 계약 v1.0.0에 맞게 구현하고, 첨부 Engineering Goal을 AGENTS.md로 보존하여 적용했다. GPU 데스크톱 구현은 인계 문서의 별도 작업이다. 새 소스/설정/계약/테스트/배포 자료를 만들었으며 실제 GPIO나 사육장 출력, 운영 SaaS/GPU 서비스 설정을 변경하지 않았다.

## 적용 원칙과 근거

| 점검 | 결과/근거 |
|---|---|
| 기존 구조 검토, 필요한 부분만 이전 | 기존 gateway/config/cloud/store/transport/배포를 검토한 뒤 `docs/architecture/compute-client-plan.md` 작성. 기존 entrypoint·config·제어 DB 유지 |
| 책임 분리 | apps/worker는 설정·배선·생명주기, habitat/compute는 계약/작업/HTTP, persistence는 별도 SQLite/파일, common은 공유 검증 |
| 같은 코드, 다른 매장 | 두 매장/site/gateway/cage 설정으로 동일 client의 전체 흐름 테스트; 다른 매장의 DB 열기 거절 |
| 교체 가능한 Compute backend | HTTP adapter를 worker에 주입. GPU origin은 config로 받고 task 최초 전송 시 고정; 하드코딩된 데스크톱 IP 없음 |
| 계약 일관성과 호환성 | GPU v1.0.0 경로/JSON 유지, Pydantic 모델→7개 JSON Schema 생성과 drift test. 기존 MQTT/SaaS payload와 URL 설정 경계 유지 |
| 내구성 | 전송 전 원본 복사본/manifest/UUID 저장. 부분 업로드·응답 유실·프로세스 재시작 후 같은 ID 유지. SHA-256/범위/revision/결과 구조 검증 |
| 장애 격리 | 별도 프로세스/DB, GPU timeout 중 gateway 가상 명령 ACK와 SaaS 모의 서버 수신 유지 통합 테스트. systemd CPU/메모리 제한 템플릿 |
| 배포 | 기존 build_release.py 확장, 두 entrypoint가 들어간 단일 0.3.0 wheel. 기존 설치기로 오프라인 staging install 및 두 CLI 실행 확인 |
| 비밀값/운영 데이터 분리 | 실제 토큰을 수집하거나 소스에 저장하지 않음. 테스트 값은 합성 fixture 전용. runtime var/와 configs/local/ ignore, 운영 /etc와 /var/lib 경로 문서화 |
| 정식 테스트, 임시 자료 정리 | 새 테스트는 unit/contract/integration에 편입. 사진/합성 결과는 pytest 임시 경로, 설치 임시 경로 삭제 완료. 기존 구매 문서·구버전 배포 자료 보존 |
| 문서/진단 | README, 전체 구조, Pi/desktop 인계, API, 배포, 운영·복구 안내 갱신. worker는 통제된 오류 code만 로그에 기록 |
| 단계적 확장 | 빈 firmware/vision/digital_twin class·폴더를 만들지 않음. 실제 펌웨어/모델/열화상/스트리밍은 입력·계약이 준비될 후속 기능 |

## 실행 결과

- `.venv/bin/python -m pytest -q`: **129 passed**, 기존 Starlette/AnyIO deprecation warning 2개, 11.30초.
- 신규 GPU 관련 **48개** 테스트 포함: 파일/설정/계약, 모의 HTTP, 실제 subprocess+loopback HTTP. 실제 GPU 연산 증거는 아니다.
- `.venv/bin/python -m apps.worker ... check-config`: valid=true, enabled=false, STORE-001/PI-001/CAGE-001.
- disabled `work --once`: 네트워크/DB 없이 status=disabled.
- 릴리스 **0.3.0-011629817059**, Python 3.13 / aarch64용 의존성 wheel 묶음 생성, manifest 해시 검증.
- 해당 릴리스를 임시 root에 `--no-service`로 오프라인 설치. STORE-VERIFY/PI-VERIFY 설정으로 설치된 gateway와 habitat-compute 명령 모두 config 검증 통과. `pip check`: No broken requirements found.
- 운영 systemd 서비스는 설치/실행하지 않았다. staging 경로는 제거했다.
- `dist/HabitatOS_GPU_Desktop_Handoff_v1.zip`: 문서·JSON Schema·예시 29개, 내부 manifest와 ZIP 무결성 검증. SHA-256 파일 함께 생성.

## 변경 파일 묶음

- 새 기능: `apps/worker/`, `habitat/common/`, `habitat/compute/`, `habitat/persistence/compute.py`.
- 새 설정/계약 자료: `configs/examples/compute.toml`, `configs/schemas/compute-v1/`, `scripts/export_compute_contract.py`.
- 새 운영 자료: `deploy/systemd/habitat-compute.service`, `docs/operations/compute-client.md`, 이 검증 기록, `docs/architecture/compute-client-plan.md`, `AGENTS.md`.
- 수정: `habitat_gateway/models.py`, `config.py`의 공통 검증 재사용, `__init__.py` 버전; `pyproject.toml`, `requirements.lock`, `.gitignore`, 기존 release builder, 관련 README/API/배포/인계 문서.
- 테스트: `tests/unit/test_compute_files.py`, `test_compute_storage.py`, `tests/contract/test_compute.py`와 합성 peer, `tests/integration/test_compute_runtime.py`; 기존 API 버전 기대값 0.3.0 반영.
- 사용자 기존 파일 삭제/대규모 이동 없음. `dist/0.2.0-*`는 기존 스냅샷으로 보존한다.

## 실제 연결에 남은 조건

1. Pi Tailscale 설치와 로그인/장치 등록. 현재 미설치이며 비대화식 sudo 불가를 확인했다.
2. 데스크톱이 반환할 실제 HTTPS base URL, desktop-result.json/OpenAPI, 계약 1.0.0과 scope 등록 상태.
3. Pi와 GPU에 별도로 설정한 같은 HABITAT_GPU_TOKEN. 토큰 값을 대화/인계 JSON에 포함하지 않는다.
4. 실제 다시점 사진과 4060/CUDA/backend 준비. 실제 업로드→COLMAP→학습→결과 다운로드/시각 검증.
5. 카메라 입력, SaaS 모델 등록·웹 뷰, 열화상 교정은 별도 후속 구현/검증.

3DGS 파일의 구조 검증은 복원 품질·실측 스케일 검증이 아니다. 대규모 촬영/다운로드와 SD카드 용량·I/O 경쟁, 전원 차단 중 저장 복구는 실제 장치 실험이 더 필요하다. 자동 데이터 보존기간/정리와 Compute 서비스의 자동 설치·업그레이드/롤백은 아직 제공하지 않으며 운영 문서에 수동 절차와 제한을 기록했다.

## 2026-09-20 개발 원칙 적용 점검 및 설정 오류 보완

사용자의 원래 Engineering Goal 첨부와 현재 `AGENTS.md`가 줄바꿈 정규화 후 동일함을 확인했다. 이 원칙은 이후 작업에도 저장소 지침으로 유지한다. 목표 디렉터리와 미래 기능을 미리 생성하지 않고 현재 구현·인계 작업에 해당하는 요구사항을 아래 근거로 점검했다.

| 원칙 번호 | 현재 적용 근거와 검증 범위 |
|---|---|
| 1·3·7·14: 매장 Gateway와 동일 코드/설정 경계 | `Settings`, 매장 설정 생성기와 배포 도구, 동일 Compute 코드의 서로 다른 site/gateway/cage 흐름 테스트. 조직/rack 전체 관리 UI가 구현됐다는 의미는 아님 |
| 2·4·5·18·19·20: 책임 분리·재사용·점진적 이전 | `apps/worker`는 CLI/배선, `habitat/compute`는 작업 흐름/HTTP, `habitat/persistence`는 별도 저장소. 기존 gateway는 이전 계획에 따라 유지. 이번 수정은 기존 CLI 두 곳과 기존 테스트 파일에 통합 |
| 6·8: ESP32 경계·장애 격리 | Pi에 물리 드라이버를 추가하지 않음. GPU 지연 중 가상 제어 ACK와 모의 SaaS 전송 지속을 실제 subprocess+loopback 통합 테스트로 확인. 물리 ESP32 watchdog/interlock 시험은 포함되지 않음 |
| 9·10: 중앙 계약·교체 가능한 Compute | `node_topic`, `sync_contract`, Compute 계약/HTTP adapter 유지. MQTT/SaaS 계약 테스트와 생성된 GPU Schema 일치 검사 통과. GPU 주소·토큰은 설정/환경변수 경계 유지 |
| 11·12·13: 영상/모델/디지털 트윈 | 아직 없는 카메라·모델을 완료로 표시하지 않음. geometry/placement revision과 시뮬레이션 표시 유지. GPU Goal에 실제 복원·실측 축척 미검증·NoIR 한계·후속 행동/열화상 범위를 명시 |
| 15·16: 비밀값·runtime 분리 | Gateway와 SaaS 참고 수신기 CLI의 잘못된 설정/인증 오류에서 입력 원문·traceback 노출을 제거. 합성 비밀값으로 로그 비노출과 DB 생성 전 종료 확인. 토큰·운영 설정·DB를 전달 ZIP에서 제외하는 기존 구성 유지 |
| 17·21: 정식 검증·동일 릴리스 배포 | 기존 테스트를 재사용해 회귀 사례 추가. 설치 무결성·매장 ID 보존·실패 롤백 테스트 통과. 기존 버전별 릴리스는 수정하지 않음; 이번 CLI 수정은 소스/전달 ZIP에 반영되며 새 운영 릴리스 배포를 뜻하지 않음 |
| 22·23·24·25: 문서·완료 근거·작업 순서·기존 자료 보존 | 기존 구조/테스트 조사 → 오류 재현 → CLI 수정 → 회귀/전체 테스트 → 문서/ZIP 갱신. 사용자 파일 삭제/대이동이나 사용하지 않는 추상화 추가 없음. Git 이력이 없는 디렉터리이므로 commit/PR 검증을 했다고 주장하지 않음 |

발견한 오류는 유효하지 않은 `cloud.endpoint`의 userinfo/query나 잘못 추가한 `token` 필드가 Pydantic/TOML 오류 원문에 포함되어 stderr에 출력되는 문제였다. `habitat_gateway/__main__.py`와 `habitat_gateway/saas_reference.py`의 시작 전 검증 경계에서 고정 오류 코드·종료 코드 2로 처리한다. 포트 문자열도 같은 경계에서 검증한다. 정상 Gateway `--check-config` JSON, 수신기 시작 옵션, HTTP 계약과 직접 `create_receiver()` 동작은 유지했다.

- 수정 후 `.venv/bin/python -m pytest -q`: **171 passed**, 기존 라이브러리 deprecation warning 2개, 32.56초.
- 설정 오류 회귀 **42개 추가**: 실제 CLI subprocess의 비밀값/환경변수명/설정 경로 비노출, traceback 부재, 시작 전 DB 미생성, 정상 설정 검사 및 참고 수신기 시작 경로. 테스트는 합성 비밀과 임시 디렉터리만 사용했다.
- Gateway와 Compute의 기본 `check-config` 명령 통과. 기본 simulation/Compute disabled 상태를 유지했다.
- 오류별 확인 방법은 [배포 안내](../deployment.md)와 [SaaS 참고 수신기 안내](../api/README.md)에 기록했다.
- 수정 파일: Gateway/참고 수신기 CLI 두 곳, `tests/test_runtime.py`, `tests/test_saas_reference.py`, 관련 README/배포·검증 문서. 신규 소스 파일·DB migration·API/schema 변경 없음.
- GPU 전달 ZIP 29개 파일, SaaS 전달 ZIP 64개 파일 재생성 후 내부 manifest와 ZIP SHA-256을 검증했다. 두 ZIP의 AGENTS.md와 SaaS ZIP의 모든 Python 소스가 현재 작업본과 동일하다. 운영 설정·DB·비밀 파일 경로를 포함하지 않는 것도 확인했다. SaaS OpenAPI·GPU 계약·GPU Schema 7개의 해시는 수정 전과 동일하다.

실제 GPU 복원·Pi↔GPU 통신·새 Pi 데이터의 운영 SaaS ACK·물리 제어 검증은 이번 코드 점검의 증거로 대체하지 않는다. GPU 데스크톱 작업은 [Goal 프롬프트](../gpu/desktop-codex-prompt.md)의 A~D와 실제 Pi 연결 E를 구분해 진행한다. 기존 `dist/0.3.0-011629817059`는 2026-09-19 스냅샷이며 이번 CLI 수정은 포함하지 않는다.
