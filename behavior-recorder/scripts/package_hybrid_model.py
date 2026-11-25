"""Bundle existing, bound hybrid weights and heads for offline video inference."""
import argparse
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from behavior_recorder.analysis_features import fingerprint
from behavior_recorder.core import atomic_json, digest, read_json, require
from behavior_recorder.vision_hybrid import (
    DETECTOR_FILES, ENCODER_FILES, SETTINGS, load_hybrid_bundle)


def package_model(detector, encoder, verifier, joint, output):
    output = Path(output).resolve()
    require(not output.exists(), "output exists; choose a new package directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hybrid-package-", dir=output.parent) as temporary:
        bundle = Path(temporary)/"model"
        for folder, source, names in (
            ("detector", Path(detector), DETECTOR_FILES),
            ("encoder", Path(encoder), ENCODER_FILES),
        ):
            destination = bundle/folder
            destination.mkdir(parents=True)
            for name in names:
                require((source/name).is_file(), "missing component: " + str(source/name))
                shutil.copy2(source/name, destination/name)
            for name in ("README.md", "LICENSE", "LICENSE.txt"):
                if (source/name).is_file():
                    shutil.copy2(source/name, destination/name)
        shutil.copy2(verifier, bundle/"verifier.json")
        shutil.copy2(joint, bundle/"joint.json")
        card = dict(schema_version=1, backend="grounding-dinov2-hinge", species="lizard",
                    status="experimental", production_validated=False,
                    model_id=read_json(bundle/"joint.json")["model_id"],
                    recipe=dict(image_size=640), settings=SETTINGS,
                    files={p.relative_to(bundle).as_posix():digest(p)
                           for p in sorted(bundle.rglob("*")) if p.is_file()})
        card["package_id"] = fingerprint(card)
        atomic_json(bundle/"model-card.json", card)
        load_hybrid_bundle(bundle)
        require(not output.exists(), "output appeared during packaging")
        bundle.rename(output)
    return card


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("detector", "encoder", "verifier", "joint", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    card = package_model(**vars(parser.parse_args()))
    print("Verified offline package:", card["package_id"])


if __name__ == "__main__":
    main()
