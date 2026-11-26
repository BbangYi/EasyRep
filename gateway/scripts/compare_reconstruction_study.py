"""Compare an existing frozen-geometry pair; never trains or modifies any job."""

import argparse
import dataclasses
import html
import json
import os
from pathlib import Path

from habitat.gpu.diagnostics import atomic_json, file_hash, tree_hashes, verify_frozen


def config_leaves(value, prefix=""):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {name: leaf for key, child in value.items()
                for name, leaf in config_leaves(child, prefix + "." + str(key)).items()}
    return {prefix: str(value)}


def verify_report_provenance(report, job, config, collector_hashes):
    """Reject stale or misbound measurements before declaring a valid pair."""
    if (report.get("source_job_id") != job.name or report.get("status") != "ok"
            or report["splatfacto"].get("status") != "ok"):
        raise ValueError("Diagnostics must be complete and belong to the selected job")
    provenance = report["provenance"]
    if provenance.get("training_config_sha256") != file_hash(config):
        raise ValueError("Training configuration changed after diagnostics")
    if provenance.get("collector_sha256") != collector_hashes:
        raise ValueError("Diagnostic collector sources differ from the recorded versions")
    for row in report["splatfacto"]["checkpoints"]:
        checkpoint = Path(row["checkpoint"]).resolve(strict=True)
        if (row.get("status") != "ok" or not checkpoint.is_relative_to((job / "trained").resolve())
                or row.get("checkpoint_sha256") != file_hash(checkpoint)):
            raise ValueError("Checkpoint diagnostics are incomplete, misbound or stale")


def visual_page(reports, jobs, destination):
    """Local PNG comparison only: no renderer, JavaScript, network or API route."""
    columns = [(label, checkpoint) for label in ("O1", "O2")
               for checkpoint in reports[label]["splatfacto"]["checkpoints"]]
    escape = html.escape
    def picture(label, relative):
        path = jobs[label] / "diagnostics/evaluation" / relative
        url = escape(Path(os.path.relpath(path, destination.parent)).as_posix(), quote=True)
        return f'<a href="{url}"><img src="{url}" loading="lazy" alt="Native evaluation RGB"></a>'
    heading = "<th>View / ROI</th><th>GT</th>" + "".join(
        f"<th>{label} step {checkpoint['actual_step']}</th>" for label, checkpoint in columns)
    rows = []
    for index, base in enumerate(columns[0][1]["views"]):
        cells = "".join("<td>" + picture(label, checkpoint["views"][index]["images"]["pred"]) + "</td>"
                        for label, checkpoint in columns)
        rows.append(f"<tr><th>{escape(base['image_name'])}</th><td>{picture('O1', base['images']['gt'])}</td>{cells}</tr>")
        for ri, roi in enumerate(base["rois"]):
            cells = "".join("<td>" + picture(label, checkpoint["views"][index]["rois"][ri]["images"]["pred"]) + "</td>"
                            for label, checkpoint in columns)
            rows.append(f"<tr><th>{escape(roi['id'])}</th><td>{picture('O1', roi['images']['gt'])}</td>{cells}</tr>")
    return ('<!doctype html><meta charset="utf-8"><title>HabitatOS controlled noise comparison</title>'
            '<style>body{font:16px sans-serif;background:#eee;color:#111}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:8px;vertical-align:top}img{max-width:360px;max-height:260px}th{position:sticky;top:0;background:#eee}</style>'
            '<h1>O1/O2 — fixed geometry, fixed views and ROI</h1><p>O1 scale regularization OFF; O2 ON. Click images for native resolution. PNGs are visual evidence; metrics use original float tensors. SfM-conditioned validation, not independent geometry truth.</p>'
            '<table><thead><tr>' + heading + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>')


def main():
    import yaml  # Installed Nerfstudio environment, trusted local configs only.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--jobs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".html").exists() or args.output.resolve().is_relative_to(args.jobs.resolve()):
        raise ValueError("Use a new external report path")
    records = {label: json.loads((args.study / f"{label}-api.json").read_text()) for label in ("O1", "O2")}
    jobs = {label: args.jobs / record["job"]["job_id"] for label, record in records.items()}
    if any(record.get("last_status", {}).get("status") != "succeeded"
           or record["last_status"].get("job_id") != jobs[label].name for label, record in records.items()):
        raise ValueError("Both selected jobs require a matching successful API result")
    reports = {label: json.loads((job / "diagnostics/diagnostics.json").read_text()) for label, job in jobs.items()}
    frozen = json.loads((args.study / "B0-frozen.json").read_text())
    for label in ("B0", "B1"):
        original = json.loads((args.study / f"{label}-frozen.json").read_text())
        verify_frozen(args.jobs / original["source_job_id"], original)
    for label, job in jobs.items():
        if tree_hashes(job / "processed") != frozen["processed_files"]:
            raise ValueError(f"{label} processed inputs differ from frozen B0")
    configs = {label: job / "trained/habitat-preview/splatfacto/run/config.yml" for label, job in jobs.items()}
    collector_root = Path(__file__).resolve().parents[1] / "habitat/gpu"
    collector_hashes = {name: file_hash(collector_root / name) for name in
                        ("diagnostics.py", "colmap_diagnostics.py", "splat_diagnostics.py")}
    for label, report in reports.items():
        verify_report_provenance(report, jobs[label], configs[label], collector_hashes)
    native = {label: config_leaves(yaml.load(path.read_text(), Loader=yaml.Loader)) for label, path in configs.items()}
    diff = {key: [native["O1"].get(key), native["O2"].get(key)]
            for key in native["O1"].keys() | native["O2"].keys() if native["O1"].get(key) != native["O2"].get(key)}
    expected = {".data", ".output_dir", ".pipeline.datamanager.data", ".pipeline.datamanager.dataparser.data",
                ".pipeline.model.use_scale_regularization"}
    if set(diff) != expected or diff[".pipeline.model.use_scale_regularization"] != ["False", "True"]:
        raise ValueError("Paired configurations differ outside paths/scale regularization")
    for key in ("split_sha256",):
        if reports["O1"]["splatfacto"][key] != reports["O2"]["splatfacto"][key]:
            raise ValueError("Paired split or input image hashes differ")
    if reports["O1"]["provenance"]["roi_sha256"] != reports["O2"]["provenance"]["roi_sha256"]:
        raise ValueError("Paired ROI annotations differ")
    paired = []
    for first, second in zip(reports["O1"]["splatfacto"]["checkpoints"], reports["O2"]["splatfacto"]["checkpoints"], strict=True):
        if first["actual_step"] != second["actual_step"]:
            raise ValueError("Checkpoint steps differ")
        for key in ("dataparser_transform", "dataparser_scale"):
            if first[key] != second[key]:
                raise ValueError("Normalized coordinate transforms differ")
        regions = []
        for a, b in zip(first["views"], second["views"], strict=True):
            if a["image_name"] != b["image_name"] or (a["width"], a["height"]) != (b["width"], b["height"]):
                raise ValueError("Evaluation views differ")
            for x, y in zip(a["rois"], b["rois"], strict=True):
                if x["id"] != y["id"] or x["mapping"] != y["mapping"]:
                    raise ValueError("ROI mapping differs")
                delta = {k: y["metrics"][k] - x["metrics"][k] if x["metrics"][k] is not None and y["metrics"][k] is not None else None
                         for k in ("psnr", "ssim", "lpips")}
                regions.append({"id": x["id"], "category": x["category"], "O1": x["metrics"], "O2": y["metrics"], "O2_minus_O1": delta})
        paired.append({"actual_step": first["actual_step"], "full_frame": {label: row["aggregate"] for label, row in (("O1", first), ("O2", second))},
                       "roi": regions, "gaussians": {label: row["gaussians"] for label, row in (("O1", first), ("O2", second))}})
    if [p["actual_step"] for p in paired] != [3000, 15000, 29999]:
        raise ValueError("Expected all three controlled checkpoints")
    value = {"schema_version": 1, "status": "ok", "paired_invariants_verified": True,
             "original_baselines_unchanged": True, "config_differences": diff,
             "config_sha256": {label: file_hash(path) for label, path in configs.items()},
             "diagnostics_sha256": {label: file_hash(job / "diagnostics/diagnostics.json") for label, job in jobs.items()},
             "comparison_script_sha256": file_hash(Path(__file__)),
             "comparisons": paired, "causality_limitations": ["one seed pair, CUDA non-determinism", "three SfM-conditioned validation views", "RGB metrics are not geometry ground truth"]}
    atomic_json(args.output, value)
    with args.output.with_suffix(".html").open("x", encoding="utf-8") as output:
        if os.name == "posix":
            os.fchmod(output.fileno(), 0o600)
        output.write(visual_page(reports, jobs, args.output.with_suffix(".html")))
    print(json.dumps({"output": str(args.output), "paired_invariants_verified": True}))


if __name__ == "__main__":
    main()
