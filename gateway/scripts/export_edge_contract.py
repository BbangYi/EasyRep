"""Regenerate the handoff artifacts from the reference API and the real Pi sender."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL

from scripts.handoff import write_bundle

from habitat_gateway.cloud import CloudSync
from habitat_gateway.config import CloudConfig, load_settings
from habitat_gateway.gateway import Gateway
from habitat_gateway.models import CommandRequest
from habitat_gateway.saas_reference import create_receiver
from habitat_gateway.sync_contract import SYNC_PATH, SyncRequest
from habitat_gateway.transport import SimulatedTransport

ROOT = Path(__file__).resolve().parents[1]


def artifacts():
    receiver = create_receiver(":memory:", [])
    try:
        spec = receiver.openapi()
    finally:
        receiver.state.db.close()
    settings = load_settings(ROOT / "config/simulation.toml").model_copy(update={
        "database": ":memory:",
        "cloud": CloudConfig(enabled=True, endpoint=f"https://habitatos.kro.kr{SYNC_PATH}"),
    })
    now = lambda: datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)
    transport = SimulatedTransport(settings, now=now)
    gateway = Gateway(settings, transport, now=now)
    try:
        transport.start(gateway)
        gateway.send_command("CAGE-001", CommandRequest(
            request_id=UUID("970b7984-85ea-422b-93cc-f15be33bb471"),
            actuator_id="light", action="on", duration_s=5,
        ))
        transport.step()
        payload = CloudSync(gateway, None)._prepare()
    finally:
        gateway.store.close()
    # Preserve cross-references while making generated examples reproducible.
    identifiers = {}

    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items()}
        if isinstance(value, list):
            return [stable(v) for v in value]
        if isinstance(value, str):
            try:
                UUID(value)
            except ValueError:
                return value
            return identifiers.setdefault(value, str(uuid5(NAMESPACE_URL, f"habitat-example-{len(identifiers)}")))
        return value

    payload = stable(payload)
    SyncRequest.model_validate(payload)
    ack = {"schema_version": 1, "site_id": payload["site_id"], "gateway_id": payload["gateway_id"],
           "accepted_event_ids": [e["event_id"] for e in payload["events"]]}
    heartbeat = {**payload, "events": []}
    collection = {
        "info": {"name": "HabitatOS Pi → SaaS v1", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "variable": [{"key": "base_url", "value": "http://127.0.0.1:9000"}, {"key": "pi_token", "value": ""}],
        "item": [{"name": "Receive sensor and command events", "request": {
            "method": "POST", "url": "{{base_url}}" + SYNC_PATH,
            "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{pi_token}}", "type": "string"}]},
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "body": {"mode": "raw", "raw": json.dumps(payload, ensure_ascii=False, indent=2),
                     "options": {"raw": {"language": "json"}}},
        }}],
    }
    return {"edge-sync.openapi.json": spec, "sync-request.json": payload, "sync-response.json": ack,
            "heartbeat-request.json": heartbeat, "HabitatOS.postman_collection.json": collection}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, help="Also package the SaaS implementer handoff ZIP")
    args = parser.parse_args()
    destination = ROOT / "docs/api"
    destination.mkdir(parents=True, exist_ok=True)
    for name, body in artifacts().items():
        (destination / name).write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    print(f"Exported OpenAPI, request/response examples and Postman collection to {destination}")
    if args.handoff:
        package_handoff(args.handoff)


def package_handoff(destination):
    # Fixed allowlist: never sweep the project root or include live configs, data or credentials.
    files = {}
    for directory in ("habitat_gateway", "habitat", "apps"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            if not path.is_symlink():
                files[str(path.relative_to(ROOT))] = path.read_bytes()
    for directory in ("docs/api", "configs/schemas/compute-v1", "docs/gpu/examples"):
        for path in sorted((ROOT / directory).iterdir()):
            if path.is_file() and not path.is_symlink() and path.suffix in (".md", ".json"):
                files[str(path.relative_to(ROOT))] = path.read_bytes()
    for name in ("AGENTS.md", "pyproject.toml", "requirements.lock", "docs/saas-integration.md",
                 "docs/gpu/gpu-api-contract.md", "config/saas-reference.toml", "config/simulation.toml",
                 "scripts/export_edge_contract.py", "scripts/handoff.py",
                 "tests/test_saas_reference.py", "tests/conftest.py", "tests/__init__.py",
                 "tests/contract/__init__.py", "tests/contract/test_video.py",
                 "tests/integration/test_video_capture.py"):
        files[name] = (ROOT / name).read_bytes()
    files[".gitignore"] = b".venv/\n__pycache__/\n.pytest_cache/\n*.egg-info/\ndata/\nvar/\ndist/\nbuild/\n.env\nconfig/local.toml\nconfigs/local/\n"
    files["README.md"] = """# HabitatOS SaaS 연동 전달 자료

Pi 프로그램 0.3.0 / Pi→SaaS 센서 API 계약 v1.0.0. 실제 운영 서버에 배포된 파일이 아닙니다.

1. **실제 SaaS 저장소에서 작업:** `docs/api/saas-codex-prompt.md`의 지시문을 사용하세요.
2. **수신 API 구현:** `docs/api/README.md`, OpenAPI, 요청/ACK 예시, Postman을 확인하세요.
3. **GPU 결과 연동:** 작업 지시서의 후속 요구사항을 확인하세요. `docs/gpu/gpu-api-contract.md`는 Pi→GPU 규격이며 GPU→SaaS API는 아직 합의 전입니다.

기존 SaaS의 언어/프레임워크를 그대로 사용할 수 있습니다. 아래 Python 프로그램은 비교·검증용 수신 참고 구현입니다. 공통 코드의 import/설치 일관성을 위해 Pi 패키지 소스도 포함하지만 SaaS에서 gateway/compute worker를 실행할 필요는 없습니다.

## 참고 구현 설치·검증

압축을 푼 폴더에서 Python 3.11 이상으로 실행합니다. ARM wheel은 포함하지 않고, 설치 시 해당 컴퓨터용 의존성을 내려받습니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e '.[test]'
.venv/bin/python -m pytest -q tests/test_saas_reference.py
```

토큰 설정과 수신기 실행은 `docs/api/README.md`의 로컬 실행 항목을 따르세요. 실행 명령은 `python -m habitat_gateway.saas_reference`이고 기본 바인딩은 `127.0.0.1:9000`입니다. 사용자 로그인·웹 조회·차트는 실제 SaaS 저장소에서 구현해야 합니다.

`config/saas-reference.toml`은 시뮬레이션용 등록 예시이고, 모든 요청 JSON은 합성 데이터입니다. 실제 토큰/운영 DB/매장 설정은 포함하지 않습니다. 참고 구현을 실행해도 실제 사육장 장치가 작동하지 않습니다.

명세·예시·ZIP 재생성:

```bash
.venv/bin/python -m scripts.export_edge_contract --handoff dist/HabitatOS_SaaS_API_v1.zip
```

확인 결과는 지시서에 따라 SAAS_API_RESULT.md와 조회 API 명세/후속 GPU 계약 초안으로 반환하세요. 토큰 원문은 포함하지 않습니다.
""".encode()
    count = write_bundle(destination, files)
    print(f"Packaged {count} files for SaaS: {destination}")


if __name__ == "__main__":
    main()
