"""Export versioned JSON Schemas from the Pi's authoritative compute models."""
import argparse
import json
from pathlib import Path

from scripts.handoff import write_bundle

from habitat.compute.config import ComputeConfig
from habitat.compute.contracts import (CONTRACT_VERSION, CaptureManifest, CaptureStatus,
                                      ComputeHealth, FileReceipt, JobRequest, JobStatus)

ROOT = Path(__file__).resolve().parents[1]


def artifacts():
    models = (CaptureManifest, CaptureStatus, ComputeHealth, FileReceipt, JobRequest, JobStatus, ComputeConfig)
    return {f"{model.__name__}.schema.json": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:habitatos:compute:{CONTRACT_VERSION}:{model.__name__}",
        **model.model_json_schema(),
    } for model in models}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, help="Also package desktop documents and schemas as a ZIP")
    args = parser.parse_args()
    destination = ROOT / "configs/schemas/compute-v1"
    destination.mkdir(parents=True, exist_ok=True)
    for name, body in artifacts().items():
        (destination / name).write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    print(f"Exported compute {CONTRACT_VERSION} JSON Schemas to {destination}")
    if args.handoff:
        package_handoff(args.handoff)


def package_handoff(destination):
    files = {}
    for path in sorted((ROOT / "docs/gpu").rglob("*")):
        if path.is_file() and path.suffix in (".md", ".json"):
            content = path.read_text().replace("../../configs/schemas/compute-v1/", "schemas/compute-v1/")
            content = content.replace("../operations/compute-client.md", "pi-operations.md")
            files[str(path.relative_to(ROOT / "docs/gpu"))] = content.encode()
    for name, body in artifacts().items():
        files[f"schemas/compute-v1/{name}"] = (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode()
    operations = (ROOT / "docs/operations/compute-client.md").read_text()
    operations = operations.replace("../gpu/gpu-api-contract.md", "gpu-api-contract.md")
    operations = operations.replace("../../configs/schemas/compute-v1/", "schemas/compute-v1/")
    operations = operations.replace("../architecture/compute-client-plan.md", "pi-architecture-plan.md")
    operations = operations.replace("../deployment.md", "pi-deployment.md")
    files["pi-operations.md"] = operations.encode()
    files["pi-architecture-plan.md"] = (ROOT / "docs/architecture/compute-client-plan.md").read_bytes()
    deployment = (ROOT / "docs/deployment.md").read_text().replace("operations/compute-client.md", "pi-operations.md")
    deployment = deployment.replace("saas-integration.md", "pi-saas-integration.md")
    files["pi-deployment.md"] = deployment.encode()
    files["pi-saas-integration.md"] = (ROOT / "docs/saas-integration.md").read_bytes()
    files["AGENTS.md"] = (ROOT / "AGENTS.md").read_bytes()
    files["api/edge-sync.openapi.json"] = (ROOT / "docs/api/edge-sync.openapi.json").read_bytes()
    files["api/ABOUT.md"] = b"Reference Pi-to-SaaS sensor API only; not the GPU API.\n"
    count = write_bundle(destination, files)
    print(f"Packaged {count} files for desktop: {destination}")


if __name__ == "__main__":
    main()
