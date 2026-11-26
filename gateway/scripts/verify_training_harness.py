"""Read-only O1/O2 validation harness; no training, pruning or API changes.

Run as a module in the installed reconstruction Python. Outputs must be new
and outside jobs. Native ns-eval is the oracle for our diagnostic collector,
not independent proof that native Nerfstudio or the geometry is correct.
"""

import argparse
import json
import math
import sqlite3
import sys
import threading
from pathlib import Path

from habitat.gpu.backend import Backend
from habitat.gpu.diagnostics import atomic_json, file_hash, tree_hashes, verify_frozen


def metric_parity(expected, actual, tolerance=1e-5):
    differences = {}
    for metric in ("psnr", "ssim", "lpips"):
        for key in (metric, metric + "_std"):
            a, b = expected[key], actual[key]
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (a, b)):
                raise ValueError("Oracle metrics must be finite numbers")
            differences[key] = abs(a - b)
            if differences[key] > tolerance:
                raise ValueError(f"Official metric mismatch: {key}")
    return differences


def nonregression_gate(pair, tolerance=1e-5):
    """Conservative audit screen, NOT a statistical or absolute quality test."""
    regressions, unmeasured = [], []
    regions = [{"id": "full_frame", **pair["full_frame"]}, *pair["roi"]]
    for region in regions:
        for metric, direction in (("psnr", 1), ("ssim", 1), ("lpips", -1)):
            a, b = region["O1"].get(metric), region["O2"].get(metric)
            if a is None or b is None:
                unmeasured.append(f"{region['id']}/{metric}")
            elif not all(math.isfinite(x) for x in (a, b)):
                raise ValueError("Nonfinite quality metric")
            elif direction * (b - a) < -tolerance:
                regressions.append({"region": region["id"], "metric": metric, "O2_minus_O1": b - a})
    return {"status": "fail" if regressions else "no_measured_regression",
            "regressions": regressions, "unmeasured": unmeasured,
            "absolute_quality_validated": False,
            "policy": "Post-experiment conservative per-region audit, not a preregistered statistical test"}


def image_controls(official_path, diagnostic_path):
    import numpy as np
    from PIL import Image

    with Image.open(official_path) as image:
        official = np.asarray(image.convert("RGB"), dtype=np.int16)
    with Image.open(diagnostic_path) as image:
        diagnostic = np.asarray(image.convert("RGB"), dtype=np.int16)
    if official.shape != diagnostic.shape:
        raise ValueError("Official/collector image dimensions differ")
    error = np.abs(official - diagnostic)
    if error.max() > 1:
        raise ValueError("Official/collector RGB differ beyond one 8-bit level")
    width = official.shape[1] // 2
    target, prediction = official[:, :width], official[:, width:]
    # In-memory negative controls only; never write modified images or poses.
    shifted = np.roll(target, 32, axis=1)
    reversed_channels = target[:, :, ::-1]
    controls = {"shift_32_pixels_rejected": bool(np.max(np.abs(target - shifted)) > 1),
                "red_blue_swap_rejected": bool(np.max(np.abs(target - reversed_channels)) > 1)}
    if not all(controls.values()):
        raise ValueError("Image identity negative control was not detected")
    return {"shape_hwc": list(official.shape), "max_byte_error": int(error.max()),
            "mean_byte_error": float(error.mean()), "negative_controls": controls,
            "rgb_mse": float(np.mean(((target.astype(float) - prediction) / 255) ** 2)),
            "note": "PNG identity controls only; quality metrics use native float tensors"}


def require_idle(jobs):
    with sqlite3.connect(f"file:{jobs.parent / 'compute.sqlite3'}?mode=ro", uri=True) as db:
        if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]:
            raise RuntimeError("GPU worker is not idle; refuse concurrent evaluation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--jobs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    jobs, output = args.jobs.resolve(strict=True), args.output.resolve()
    if output.exists() or output.is_relative_to(jobs):
        raise ValueError("Use a new external output directory")
    require_idle(jobs)
    backend = Backend({"python": sys.executable,
                       "stage_timeout_seconds": {"pair": 180, "O1_oracle": 240, "O2_oracle": 240}})
    output.mkdir(parents=True, mode=0o700)
    measurements = {"stage_seconds": {}}
    cancel = threading.Event()
    report = {"schema_version": 1, "status": "running", "harness_sha256": file_hash(Path(__file__)),
              "read_only": True, "oracles": {}, "measurements": measurements,
              "limitations": ["native implementation is a shared dependency, not an independent renderer",
                              "no fresh training or multi-seed reproduction", "no geometry ground truth test"]}
    snapshots = {}
    try:
        for label in ("O1", "O2"):
            record = json.loads((args.study / f"{label}-api.json").read_text())
            job = jobs / record["job"]["job_id"]
            snapshots[label] = (job, tree_hashes(job))
        atomic_json(output / "source-snapshots.json", {k: {"job": str(p), "files": hashes}
                    for k, (p, hashes) in snapshots.items()})
        backend._command([sys.executable, "-m", "scripts.compare_reconstruction_study",
                          "--study", str(args.study.resolve()), "--jobs", str(jobs),
                          "--output", str(output / "pair.json")], output, "pair", cancel, measurements)
        pair = json.loads((output / "pair.json").read_text())
        report["paired_invariants_verified"] = pair["paired_invariants_verified"]
        report["quality_gate"] = nonregression_gate(pair["comparisons"][-1])
        atomic_json(output / "harness.json", report)
        for label, (job, _) in snapshots.items():
            require_idle(jobs)
            config = job / "trained/habitat-preview/splatfacto/run/config.yml"
            diagnostics = json.loads((job / "diagnostics/diagnostics.json").read_text())
            checkpoint = diagnostics["splatfacto"]["checkpoints"][-1]
            oracle = output / f"{label}-official.json"
            renders = output / f"{label}-official-renders"
            backend._command([sys.executable, "-m", "nerfstudio.scripts.eval", "--load-config", str(config),
                              "--output-path", str(oracle), "--render-output-path", str(renders)],
                             output, f"{label}_oracle", cancel, measurements)
            native = json.loads(oracle.read_text())
            if Path(native["checkpoint"]).resolve() != Path(checkpoint["checkpoint"]).resolve():
                raise ValueError("Oracle selected a different checkpoint")
            differences = metric_parity(checkpoint["aggregate"], native["results"])
            shifted_scores = dict(native["results"], psnr=native["results"]["psnr"] + 1)
            try:
                metric_parity(checkpoint["aggregate"], shifted_scores)
            except ValueError:
                wrong_metric_rejected = True
            else:
                raise ValueError("Corrupted metric negative control was not detected")
            image_checks = [image_controls(renders / f"eval_img_{index:04d}.png",
                            job / "diagnostics/evaluation" / view["images"]["comparison"])
                            for index, view in enumerate(checkpoint["views"])]
            report["oracles"][label] = {"checkpoint_sha256": checkpoint["checkpoint_sha256"],
                "official_json_sha256": file_hash(oracle), "absolute_metric_differences": differences,
                "wrong_metric_rejected": wrong_metric_rejected, "image_checks": image_checks}
            atomic_json(output / "harness.json", report)
        for label in ("B0", "B1"):
            frozen = json.loads((args.study / f"{label}-frozen.json").read_text())
            verify_frozen(jobs / frozen["source_job_id"], frozen)
        report["original_baselines_unchanged"] = True
        report["status"] = "pass"
    except Exception as exc:
        report.update(status="fail", error={"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        report["experiment_files_unchanged"] = all(tree_hashes(job) == hashes for job, hashes in snapshots.values())
        if not report["experiment_files_unchanged"]:
            report["status"] = "fail"
        atomic_json(output / "harness.json", report)
    if report["status"] != "pass":
        raise RuntimeError("Harness failed; see protected report")
    print(json.dumps({"execution_checks": report["status"], "quality_gate": report["quality_gate"]["status"],
                      "training_recipe_validated": False, "output": str(output / "harness.json")}))


if __name__ == "__main__":
    main()
