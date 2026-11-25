"""Loopback-only image inspection, durable video jobs, and human-reviewed references."""
import argparse
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from urllib.parse import unquote, urlparse
from uuid import uuid4

from .analysis_features import save_artifact
from .appearance_journal import Journal, MAX_PHOTO
from .behavior_windows import compare_contexts, evaluate_reviewed_windows, fit_reference_bank, window_observations
from .core import RecorderError, atomic_json, digest, lock, now, read_json, relative, require, timestamp, validate_config
from .vision_data import load_dataset, read_boxes
from .vision_model import load_model_card

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "baseline": ("기존 기준 모델 · 27장 학습", "data/gpu-jobs/crested-commons-seed-01/result/model"),
    "candidate": ("오검출 감소 후보 · 누락 증가", "data/gpu-jobs/crested-commons-v2-01/result/low-lr-frozen-seed43"),
    "public_lizard": ("공개 자료 도마뱀 모델 · 624장 학습", "data/gpu-jobs/lizard-public-v1-02/result/transfer-frozen"),
    "diverse_lizard": ("자료 다양화 후보 · 1,613장 학습", "data/gpu-jobs/lizard-openimages-v1-01/result/diverse-full"),
    "camera_lizard": ("카메라 조건 보강 후보 · 1,674장 학습", "data/gpu-jobs/lizard-camera-v1-01/result/camera-adapted"),
    "captive_lizard": ("사육 환경 보강 후보 · 1,693장 학습", "data/gpu-jobs/lizard-captive-v1-01/result/captive-adapted"),
    "publisher_sawit": ("SAWIT 연구자 공개 모델 · 도마뱀", "data/public-reptile-research-20261018/publisher-model/model"),
    "warm_lizard": ("최근 비교 기준 · 초당 3장 분석 · 실사용 미검증", "data/gpu-jobs/lizard-absence-warm-v2-01/result/absence-balanced-warm"),
    "captive_diversity": ("1,355장 추가 학습 후보 · 초당 3장 분석 · 실험용", "data/gpu-jobs/lizard-captive-diversity-v1-01/result/captive-diversity-warm"),
    "memory_lizard_v8": ("연속 추적 v8 · 초당 2장 분석 · 실험용", "data/models/lizard-sam2-hybrid-v8"),
}
MODEL_BACKENDS = {"memory_lizard_v8": "sam2-hybrid"}
MODEL_TRACKING_CONFIGS = {
    "warm_lizard": "examples/vision.tracking.development.json",
    "captive_diversity": "examples/vision.tracking.development.json",
    "memory_lizard_v8": "examples/vision.tracking.memory.json",
}
MAX_UPLOAD = 256 * 1024**2
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}


def load_registered_card(key):
    directory = relative(ROOT, MODELS[key][1])
    if MODEL_BACKENDS.get(key) == "sam2-hybrid":
        from .vision_memory import load_memory_bundle
        return load_memory_bundle(directory)[0]
    return load_model_card(directory)


def stop_job_process(process):
    """Stop the job's dedicated process group, including neural subprocesses."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # The parent may exit before a child that ignores TERM.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)
    else:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def process_job(storage, job_id):
    from .vision_video import infer_video
    storage = storage.resolve()
    job = read_json(relative(storage, f"jobs/{job_id}/job.json"))
    run = relative(storage, f"jobs/{job_id}")
    model = relative(ROOT, MODELS[job["model"]][1])
    backend = MODEL_BACKENDS.get(job["model"], "yolo")
    require(job.get("backend", "yolo") == backend, "registered detector backend changed; submit a new job")
    require(backend != "sam2-hybrid" or job["device"] == "mps", "연속 추적 모델은 MPS 모드에서 실행하세요.")
    require(load_registered_card(job["model"])["model_id"] == job["model_id"], "registered model changed; submit a new job")
    video = relative(storage, "uploads/" + job["upload_id"] + job["suffix"])
    require(digest(video) == job["source_sha256"], "uploaded video changed")
    config = job.get("tracking_config") or read_json(ROOT / "examples/vision.tracking.json")
    config["zones"] = job["zones"]
    summary = infer_video(model, run / "analysis", config, video=video, device=job["device"],
                          threads=1 if backend == "sam2-hybrid" else 2,
                          provenance=job["provenance"], backend=backend)
    observations = [json.loads(line) for line in (run / "analysis/observations.jsonl").read_text().splitlines()]
    features = window_observations(summary, observations, job["context"], window_seconds=job["window_seconds"])
    for row in features["windows"]:
        row["run_id"] = job_id
    save_artifact(run / "features.json", features)
    # Browser-compatible derivative only; source video and PTS are retained unchanged.
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(run / "analysis/review.mp4"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart",
                    str(run / "review-browser.mp4")], check=True, timeout=180)
    atomic_json(run / "complete.json", {"finished_at": now(), "field_validated": False})


class Lab:
    def __init__(self, storage, *, device="cpu", load_catalog=True, watch_config=None, conditions=""):
        self.storage = Path(storage).resolve()
        self.storage.mkdir(parents=True, exist_ok=True)
        for directory in ("uploads", "jobs", "references"):
            (self.storage / directory).mkdir(exist_ok=True)
        self.device = device
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.token = secrets.token_urlsafe(32)
        self.assets = {}
        self.catalog = self.make_catalog() if load_catalog else []
        self.models = []
        for key, (label, directory) in MODELS.items():
            backend = MODEL_BACKENDS.get(key, "yolo")
            manifest = "model-card.json" if backend == "sam2-hybrid" else "model.json"
            if (ROOT / directory / manifest).exists():
                card = load_registered_card(key)
                self.models.append({"key": key, "label": label, "model_id": card["model_id"], "species": card["species"],
                                    "backend": backend, "available": backend != "sam2-hybrid" or device == "mps"})
        self.jobs = {}
        for path in sorted((self.storage / "jobs").glob("*/job.json")):
            job = read_json(path)
            if job["state"] in {"running", "queued"}:
                if (path.parent / "complete.json").exists():
                    job.update(state="complete", finished_at=read_json(path.parent / "complete.json")["finished_at"])
                else:
                    job.update(state="interrupted", error="서버가 종료되어 중단됨. 원본은 보존되었습니다.")
                atomic_json(path, job)
            self.jobs[job["id"]] = job
        self.reviews = read_json(self.storage / "reviews.json") if (self.storage / "reviews.json").exists() else {}
        self.behavior_reviews = (read_json(self.storage / "behavior-reviews.json")
                                 if (self.storage / "behavior-reviews.json").exists() else {})
        self.reference = read_json(self.storage / "active-reference.json") if (self.storage / "active-reference.json").exists() else None
        self.watch_config = Path(watch_config).resolve() if watch_config else None
        self.conditions = conditions
        self.watch_state = {"mode": "manual", "last_received_at": None, "last_captured_at": None, "error": None}
        self.watch_index = read_json(self.storage / "watch-index.json") if (self.storage / "watch-index.json").exists() else {}
        self.watch_retries = {}
        if self.watch_config:
            self.camera_config = validate_config(read_json(self.watch_config))
            require(len(self.camera_config["animals"]) == 1 and self.camera_config["animals"][0]["species"] == "crested_gecko",
                    "camera watch requires one configured crested gecko")
            inbox = Path(self.camera_config["input"]["inbox"])
            self.inbox = (self.watch_config.parent / inbox).resolve() if not inbox.is_absolute() else inbox.resolve()
            require(self.inbox.is_dir(), "camera inbox does not exist")
            self.watch_state["mode"] = "finalized_file"
            for entry in self.watch_index.values():
                if entry.get("received_at", "") > (self.watch_state["last_received_at"] or ""):
                    self.watch_state.update(last_received_at=entry["received_at"], last_captured_at=entry.get("captured_at"))

    def asset(self, path):
        path = Path(path).resolve()
        require(path.is_file() and (path.is_relative_to(ROOT) or path.is_relative_to(self.storage)), "media outside lab")
        require(path.suffix.lower() in {".jpg", ".jpeg", ".png", ".mp4", ".mov", ".webm", ".mkv"}, "unsupported media")
        key = hashlib.sha256(str(path).encode()).hexdigest()
        self.assets[key] = path
        return "/media/" + key

    def make_catalog(self):
        directory = ROOT / "data/datasets/crested-commons-v2r1"
        manifest = load_dataset(directory)
        prediction_dataset_id = manifest["dataset_id"]
        expanded = ROOT / "data/datasets/crested-commons-v3"
        if (expanded / "status.json").exists():
            newer = load_dataset(expanded)
            inventory = {row["id"]: row for row in newer["records"]}
            for row in manifest["records"]:
                require(row["id"] in inventory and all(inventory[row["id"]][key] == row[key]
                        for key in ("image_sha256", "label_sha256", "group_id", "split")),
                        "expanded dataset changes an earlier comparison record")
            directory, manifest = expanded, newer
        sources = {s["id"]: s for s in manifest["sources"]}
        predictions = {}
        for model_key, run_name in (("baseline", "baseline"), ("candidate", "low-lr-frozen-seed43")):
            for split in ("val", "test"):
                path = ROOT / f"data/gpu-jobs/crested-commons-v2-01/result/{run_name}-{split}/benchmark.json"
                if path.exists():
                    report = read_json(path)
                    require(report["dataset_id"] == prediction_dataset_id, "benchmark dataset differs")
                    for row in report["per_image"]:
                        predictions.setdefault(row["image_id"], {})[model_key] = row
        catalog = []
        for row in manifest["records"]:
            boxes = [[(x-w/2)*row["width"], (y-h/2)*row["height"], (x+w/2)*row["width"], (y+h/2)*row["height"]]
                     for x,y,w,h in read_boxes(relative(directory, row["label"]))]
            source = sources[row["source_id"]]
            catalog.append({"id": row["id"], "split": row["split"], "width": row["width"], "height": row["height"],
                            "collection": "crested", "target": "crested_gecko",
                            "image": self.asset(relative(directory, row["image"])), "references": boxes,
                            "review_method": row["review_method"], "source": source,
                            "predictions": predictions.get(row["id"], {})})
        collections = (
            ("public", "data/datasets/lizard-public-v1/dataset", "public_lizard", "lizard-public-v1-02", "transfer-frozen"),
            ("expanded", "data/openimages-lizard-20261019/filtered/combined/dataset", "diverse_lizard", "lizard-openimages-v1-01", "diverse-full"),
            ("camera", "data/sawit-adaptation-20261019/combined/dataset", "camera_lizard", "lizard-camera-v1-01", "camera-adapted"),
            ("captive", "data/captive-adaptation-20261019/combined/dataset", "captive_lizard", "lizard-captive-v1-01", "captive-adapted"),
        )
        for collection, dataset_path, model_key, job_name, run_name in collections:
            public = ROOT / dataset_path
            if not (public / "status.json").exists():
                continue
            expanded = load_dataset(public, inspection_only=True)
            sources = {s["id"]: s for s in expanded["sources"]}
            predictions = {}
            comparisons = [(model_key, run_name, model_key)]
            if collection == "expanded":
                comparisons.append(("baseline", "baseline", "public_lizard"))
            elif collection == "camera":
                comparisons.append(("baseline", "baseline", "diverse_lizard"))
            elif collection == "captive":
                comparisons.append(("baseline", "baseline", "camera_lizard"))
            for prediction_key, report_name, registered_key in comparisons:
                model_path = ROOT / MODELS[registered_key][1] if registered_key in MODELS else None
                if not model_path or not (model_path / "model.json").exists():
                    continue
                model_id = load_model_card(model_path)["model_id"]
                for split in ("val", "test"):
                    report_path = ROOT / f"data/gpu-jobs/{job_name}/result/{report_name}-{split}/benchmark.json"
                    if collection == "expanded" and split == "val":
                        variant = "baseline" if prediction_key == "baseline" else "candidate"
                        compared = ROOT / f"data/openimages-lizard-20261019/nms-comparison/result/{variant}-nms05/benchmark.json"
                        if compared.exists():
                            require(read_json(compared)["nms_iou"] == 0.5, "display NMS configuration differs")
                            report_path = compared
                    if report_path.exists():
                        report = read_json(report_path)
                        if report["model_id"] == model_id:
                            require(report["dataset_id"] == expanded["dataset_id"], "public benchmark dataset differs")
                            for result in report["per_image"]:
                                predictions.setdefault(result["image_id"], {})[prediction_key] = result
            for index, row in enumerate(expanded["records"], 1):
                if not row['box_count'] and row['review_method'] == 'publisher_annotations' and not row.get('target_absence_review'):
                    # Archived empty labels have incomplete target coverage, not verified background truth.
                    continue
                boxes = [[(x-w/2)*row["width"], (y-h/2)*row["height"], (x+w/2)*row["width"], (y+h/2)*row["height"]]
                         for x, y, w, h in read_boxes(relative(public, row["label"]))]
                catalog.append({"id": collection + ":" + row["id"], "collection": collection, "target": "lizard",
                                "display_name": row.get("publisher_metadata", {}).get("Title") or
                                    ("도마뱀 사진 " if boxes else "배경 사진 ") + str(index),
                                "split": row["split"], "width": row["width"], "height": row["height"],
                                "image": self.asset(relative(public, row["image"])), "references": boxes,
                                "review_method": row["review_method"], "source": sources[row["source_id"]],
                                "predictions": predictions.get(row["id"], {})})
        return catalog

    def persist_job(self, job):
        atomic_json(relative(self.storage, f"jobs/{job['id']}/job.json"), job)

    def create_job(self, request):
        with self.lock:
            require(len(self.jobs) < 100, "작업 100개 한도에 도달했습니다. 별도 저장 폴더로 시작하세요.")
            require(sum(j["state"] in {"queued", "running"} for j in self.jobs.values()) < 4, "대기열이 찼습니다. 완료 후 추가하세요.")
            upload = relative(self.storage, "uploads/" + request["upload_id"] + ".json")
            meta = read_json(upload)
            require(request["model"] in {m["key"] for m in self.models}, "등록된 모델을 선택하세요.")
            backend = MODEL_BACKENDS.get(request["model"], "yolo")
            require(backend != "sam2-hybrid" or self.device == "mps", "연속 추적 모델은 MPS 모드에서 실행하세요.")
            model_id = next(m["model_id"] for m in self.models if m["key"] == request["model"])
            require(request["provenance"] in {"real_camera", "public_real", "synthetic_test", "unverified_file"}, "영상 출처를 선택하세요.")
            credit = request.get("credit", {})
            require(isinstance(credit, dict), "출처 정보가 올바르지 않습니다.")
            for value in credit.values():
                require(isinstance(value, str) and len(value) <= 1000, "출처 정보는 항목별 1000자 이내입니다.")
            if request["provenance"] == "public_real":
                require(all(credit.get(k) for k in ("url", "author", "license")), "공개 영상의 원문 주소·저자·라이선스를 입력하세요.")
                require(urlparse(credit["url"]).scheme in {"http", "https"}, "원문은 http/https 주소여야 합니다.")
            context = request.get("context", {})
            require(isinstance(context, dict), "관측 맥락이 올바르지 않습니다.")
            for key in ("animal_id", "camera_revision", "conditions", "recording_id"):
                value = context.get(key, "")
                require(isinstance(value, str) and len(value) <= 160, "관측 맥락은 160자 이내입니다.")
            timestamp(context.get("captured_at"))
            from .vision_video import validate_tracking_config
            config = read_json(ROOT / MODEL_TRACKING_CONFIGS.get(request["model"], "examples/vision.tracking.json"))
            selected_model = next(m for m in self.models if m["key"] == request["model"])
            config["species"] = selected_model.get("species", "crested_gecko")
            config["zones"] = request.get("zones", {})
            if request.get("target_box") is not None:
                config["target_seed"] = {"source_sha256": meta["sha256"], "xyxy": request["target_box"]}
            validate_tracking_config(config)
            require(request.get("window_seconds", 30) in (5, 10, 30, 60), "분석 구간은 5/10/30/60초입니다.")
            identity = {"source": meta["sha256"], "model": model_id, "context": context,
                        "tracking_config": config,
                        "zones": config["zones"], "provenance": request["provenance"], "credit": credit,
                        "window_seconds": request.get("window_seconds", 30)}
            if backend != "yolo":
                identity["backend"] = backend
            signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            existing = next((j for j in self.jobs.values() if j["signature"] == signature and j["state"] in {"queued", "running", "complete"}), None)
            if existing:
                return copy.deepcopy(existing)
            key = uuid4().hex
            job = {"id": key, "state": "queued", "created_at": now(), "name": meta["name"],
                   "upload_id": request["upload_id"], "suffix": meta["suffix"], "source_sha256": meta["sha256"],
                   "model": request["model"], "model_id": model_id, "backend": backend, "device": self.device, "provenance": request["provenance"],
                   "context": context, "credit": credit, "zones": config["zones"], "window_seconds": identity["window_seconds"], "signature": signature}
            job["tracking_config"] = config
            job["target_box"] = request.get("target_box")
            (self.storage / "jobs" / key).mkdir()
            self.persist_job(job)
            self.jobs[key] = job
            return copy.deepcopy(job)

    def retry_job(self, key):
        with self.lock:
            require(key in self.jobs, "작업을 찾을 수 없습니다.")
            previous = self.jobs[key]
            require(previous["state"] in {"failed", "interrupted"}, "실패·중단된 작업만 다시 처리할 수 있습니다.")
            # Keep failed artifacts and logs; a retry gets its own output directory.
            request = {k: previous[k] for k in
                       ("upload_id", "model", "provenance", "context", "zones", "window_seconds", "credit")}
            request["target_box"] = previous.get("target_box")
            return self.create_job(request)

    def job_detail(self, key):
        with self.lock:
            require(key in self.jobs, "작업을 찾을 수 없습니다.")
            job = copy.deepcopy(self.jobs[key])
            run = relative(self.storage, "jobs/" + key)
            if job["state"] != "complete":
                return job
            job["summary"] = read_json(run / "analysis/summary.json")
            job["video"] = self.asset(run / "review-browser.mp4")
            job["review_render_version"] = job["summary"].get("review_render_version", 1)
            revised = run / "review-v2"
            if (revised / "status.json").exists() and read_json(revised / "status.json")["state"] == "complete":
                manifest = read_json(revised / "render.json")
                require(manifest["source_sha256"] == job["source_sha256"] and
                        manifest["model_id"] == job["summary"]["model_id"] and
                        manifest["observations_sha256"] == digest(run / "analysis/observations.jsonl") and
                        manifest["preview_sha256"] == digest(revised / "review-browser.mp4"), "review artifact differs from analysis")
                job["video"] = self.asset(revised / "review-browser.mp4")
                job["review_render_version"] = manifest["render_version"]
            job["observations"] = [json.loads(line) for line in (run / "analysis/observations.jsonl").read_text().splitlines()]
            features = read_json(run / "features.json")
            for row in features["windows"]:
                row.update(self.reviews.get(row["window_id"], {}))
                behavior = self.behavior_reviews.get(self.behavior_review_key(key, row["window_id"]))
                if behavior:
                    row["behavior_review"] = copy.deepcopy(behavior)
            job["features"] = features
            job["comparison"] = compare_contexts(features["windows"], self.reference)
            return job

    def verification(self):
        path = self.storage / "verification.json"
        if not path.exists():
            return None
        report = read_json(path)
        frames_path = self.storage / "case-frames.json"
        if frames_path.exists():
            frames = read_json(frames_path)
            require(frames["source_sha256"] == report["sha256"], "comparison frames have a different source")
            for frame in frames["frames"]:
                frame["image"] = self.asset(relative(self.storage, frame.pop("image_file")))
            report["frames"] = frames["frames"]
        return report

    def visual_memory_check(self):
        path = self.storage / "visual-memory-check.json"
        if not path.exists():
            return None
        report = read_json(path)
        require(report.get("schema_version") == 1 and isinstance(report.get("cases"), list) and
                len(report["cases"]) <= 10, "invalid visual memory report")
        for case in report["cases"]:
            for variant in case["variants"].values():
                variant["video"] = self.asset(relative(ROOT, variant.pop("video_file")))
        return report

    def review(self, request):
        with self.lock:
            job = self.job_detail(request["job_id"])
            require(job["state"] == "complete", "완료된 영상만 검토할 수 있습니다.")
            windows = job["features"]["windows"]
            require(any(r["window_id"] == request["window_id"] for r in windows), "구간을 찾을 수 없습니다.")
            require(request["assessment"] in {"normal", "anomaly", "uncertain", "detection_error"}, "검토 결과를 선택하세요.")
            reviewer = request.get("reviewer", "").strip()
            require(0 < len(reviewer) <= 120, "검토자 이름을 입력하세요.")
            require(request.get("review_method") in {"human", "assistant"}, "사람 검토와 AI 검토를 구분해야 합니다.")
            require(request.get("partition") in {"reference", "calibration", "evaluation"}, "자료 용도를 선택하세요.")
            record = {"assessment": request["assessment"], "reviewer": reviewer, "review_method": request["review_method"],
                      "partition": request["partition"], "reviewed_at": now()}
            invalidates = self.reference and request["window_id"] in self.reference.get("reviewed_window_ids", [])
            if invalidates:
                # Invalidate before changing the review, including across interrupted writes.
                (self.storage / "active-reference.json").unlink(missing_ok=True)
                self.reference = None
            # Write-once audit entry plus a replaceable current review index.
            history = self.storage / "review-history"
            history.mkdir(exist_ok=True)
            save_artifact(history / (uuid4().hex + ".json"), {**request, **record})
            self.reviews[request["window_id"]] = record
            atomic_json(self.storage / "reviews.json", self.reviews)
            if invalidates:
                record = {**record, "reference_invalidated": True}
            return record

    @staticmethod
    def behavior_review_key(job_id, window_id):
        require(isinstance(job_id, str) and job_id and isinstance(window_id, str) and window_id,
                "job and window ID required")
        return job_id + ":" + window_id

    def behavior_review(self, request):
        """Persist a human behavior-state label without treating missing tracking as rest."""
        with self.lock:
            job = self.job_detail(request["job_id"])
            require(job["state"] == "complete", "완료된 영상만 행동을 검토할 수 있습니다.")
            window = next((row for row in job["features"]["windows"]
                           if row["window_id"] == request["window_id"]), None)
            require(window is not None, "구간을 찾을 수 없습니다.")
            reviewer = request.get("reviewer", "").strip()
            require(0 < len(reviewer) <= 120, "검토자 이름을 입력하세요.")
            visibility = request.get("visibility")
            certainty = request.get("certainty")
            behavior = request.get("behavior")
            require(visibility in {"visible", "partial", "unobservable"}, "관측 상태를 선택하세요.")
            require(certainty in {"certain", "uncertain"}, "확신 수준을 선택하세요.")
            fully_labeled = visibility == "visible" and certainty == "certain"
            if fully_labeled:
                require(window.get("quality") == "usable", "추적 품질이 부족한 구간은 unobservable로만 저장할 수 있습니다.")
                require(behavior in {"moving", "resting"}, "행동 상태는 moving 또는 resting이어야 합니다.")
            else:
                require(behavior is None, "fully visible and certain labels alone can include a behavior.")
            if window.get("quality") != "usable":
                require(visibility == "unobservable", "추적 품질이 부족한 구간은 unobservable로 저장하세요.")
            key = self.behavior_review_key(job["id"], window["window_id"])
            previous = self.behavior_reviews.get(key)
            record = {"schema_version": 1, "label_id": "lab-behavior:" + uuid4().hex,
                      "clip_id": job["id"], "job_id": job["id"], "window_id": window["window_id"],
                      "animal_id": window.get("scope", {}).get("animal_id"),
                      "recording_id": window.get("recording_id"),
                      "source_sha256": window.get("source_sha256") or job.get("source_sha256"),
                      "start_seconds": window["start_seconds"], "end_seconds": window["end_seconds"],
                      "behavior": behavior, "visibility": visibility, "certainty": certainty,
                      "annotator": reviewer, "reviewer": reviewer, "review_method": "human",
                      "tracking_quality": window.get("quality"),
                      "note": "Vision Lab human behavior review; only visible+certain+usable labels are training candidates.",
                      "supersedes": previous.get("label_id") if previous else None,
                      "reviewed_at": now()}
            history = self.storage / "behavior-review-history"
            history.mkdir(exist_ok=True)
            save_artifact(history / (record["label_id"].split(":", 1)[1] + ".json"), record)
            self.behavior_reviews[key] = record
            atomic_json(self.storage / "behavior-reviews.json", self.behavior_reviews)
            return copy.deepcopy(record)

    def behavior_labels(self):
        """Export current labels in the recorder-compatible shape; audit history stays immutable."""
        with self.lock:
            labels = []
            for record in self.behavior_reviews.values():
                label = {key: record.get(key) for key in ("label_id", "clip_id", "animal_id", "start_seconds",
                         "end_seconds", "behavior", "visibility", "certainty", "annotator", "note")}
                label["supersedes"] = None
                labels.append(label)
            return {"schema_version": 1, "kind": "vision_lab_behavior_labels", "labels":
                    sorted(labels, key=lambda row: (row["clip_id"], row["start_seconds"], row["label_id"])),
                    "training_ready": False,
                    "limitation": "Only visible, certain, usable windows become classifier candidates; no model is fit here."}

    def train_reference(self):
        with self.lock:
            reviewed = self.reviewed_windows()
            model = fit_reference_bank(reviewed)
            target = self.storage / "references" / (model["model_id"] + ".json")
            if not target.exists():
                save_artifact(target, model)
            atomic_json(self.storage / "active-reference.json", model)
            self.reference = model
            return {"model_id": model["model_id"], "contexts": len(model["models"]), "pending": len(model["pending"]),
                    "references": sum(len(m["references"]) for m in model["models"].values()),
                    "calibration": sum(m["calibration_windows"] for m in model["models"].values()), "field_validated": False}

    def reviewed_windows(self):
        rows = []
        for key, job in self.jobs.items():
            if job["state"] == "complete":
                for row in read_json(self.storage / "jobs" / key / "features.json")["windows"]:
                    row.update(self.reviews.get(row["window_id"], {}))
                    rows.append(row)
        return rows

    def enqueue_descriptor(self, descriptor_path, config, conditions):
        """Reuse the recorder's finalized-file contract; never claim hardware connectivity."""
        from .media import copy_clip, validate_descriptor
        require(not descriptor_path.is_symlink(), "descriptor symlinks are not supported")
        descriptor = read_json(descriptor_path, 65536)
        session = SimpleNamespace(manifest={"config": config},
                                  space=lambda size: require(shutil.disk_usage(self.storage).free > size + 1024**3,
                                                             "insufficient free space"))
        camera = validate_descriptor(session, descriptor)
        require(camera["kind"] == "rgb", "vision requires an RGB camera")
        source = relative(descriptor_path.parent, descriptor["file"])
        require(source.suffix.lower() in VIDEO_SUFFIXES, "unsupported video container")
        require(source.stat().st_size <= MAX_UPLOAD, "camera clip exceeds upload limit")
        key = hashlib.sha256(json.dumps(descriptor, sort_keys=True).encode()).hexdigest()
        with self.lock:
            destination = self.storage / "uploads" / (key + source.suffix.lower())
            metadata_path = destination.with_suffix(".json")
            if not metadata_path.exists():
                used = sum(p.stat().st_size for p in self.storage.rglob('*') if p.is_file())
                require(used + source.stat().st_size <= 10 * 1024**3, "lab storage limit reached")
                require(shutil.disk_usage(self.storage).free > source.stat().st_size + 1024**3, "insufficient free space")
                temporary = destination.with_suffix(".partial")
                if temporary.exists():
                    temporary.rename(temporary.with_name(temporary.name + ".interrupted-" + uuid4().hex))
                if destination.exists():
                    require(digest(destination) == descriptor["sha256"], "stored camera copy checksum mismatch")
                else:
                    try:
                        copy_clip(session, source, temporary, descriptor["sha256"])
                        temporary.replace(destination)
                    finally:
                        temporary.unlink(missing_ok=True)
                save_artifact(metadata_path, {"id":key, "name":source.name, "suffix":source.suffix.lower(),
                                             "bytes":destination.stat().st_size, "sha256":descriptor["sha256"],
                                             "received_at":now(), "capture_descriptor":descriptor})
            revision = f"{camera['camera_id']}:{descriptor['placement_revision']}:{descriptor['calibration_revision']}"
            job = self.create_job({"upload_id":key, "model":"baseline", "provenance":descriptor["provenance"],
                                   "context":{"animal_id":config["animals"][0]["animal_id"], "camera_revision":revision,
                                              "conditions":conditions, "recording_id":descriptor["recording_id"],
                                              "captured_at":descriptor["captured_at"]}})
            self.watch_state.update(last_received_at=now(), last_captured_at=descriptor["captured_at"], error=None)
            return job

    def watch_inbox(self):
        while not self.stop.wait(2):
            self.scan_inbox()

    def scan_inbox(self):
        for path in sorted(self.inbox.glob("*.capture.json")):
            if self.stop.is_set():
                return
            with self.lock:
                if sum(j["state"] in {"queued", "running"} for j in self.jobs.values()) >= 4:
                    return
            identity = str(path)
            if self.watch_retries.get(identity, 0) > time.monotonic():
                continue
            try:
                require(path.stat().st_size <= 65536 and not path.is_symlink(), "invalid camera descriptor")
                stamp = digest(path)
                if self.watch_index.get(identity, {}).get("sha256") == stamp:
                    continue
                job = self.enqueue_descriptor(path, self.camera_config, self.conditions)
                with self.lock:
                    self.watch_index[identity] = {"sha256":stamp,"job_id":job["id"], "received_at":now(),
                                                  "captured_at":job["context"].get("captured_at")}
                    atomic_json(self.storage / "watch-index.json", self.watch_index)
                    self.watch_retries.pop(identity, None)
            except (OSError, RecorderError, ValueError, KeyError, TypeError) as exc:
                with self.lock:
                    self.watch_state["error"] = f"{path.name}: {exc}"
                    self.watch_retries[identity] = time.monotonic() + 60
                # A bad producer file must not block other completed recordings.
                continue
        with self.lock:
            self.watch_state["pending_file_errors"] = len(self.watch_retries)

    def worker(self):
        while not self.stop.wait(0.5):
            with self.lock:
                job = next((j for j in self.jobs.values() if j["state"] == "queued"), None)
                if job is None:
                    continue
                job.update(state="running", started_at=now())
                self.persist_job(job)
                run = self.storage / "jobs" / job["id"]
            try:
                require(shutil.disk_usage(self.storage).free > 1024**3, "분석을 위한 여유 공간이 1GiB 미만입니다.")
                with (run / "execution.log").open("wb") as log:
                    process = subprocess.Popen([sys.executable, "-m", "behavior_recorder.vision_lab", "--process-job",
                                                str(self.storage), job["id"]], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                               start_new_session=os.name == "posix")
                    deadline = time.monotonic() + 1800
                    while process.poll() is None:
                        if self.stop.wait(0.5) or time.monotonic() >= deadline:
                            stop_job_process(process)
                            raise RecorderError("분석 중단 또는 30분 시간 제한. 원본은 보존되었습니다.")
                    if process.returncode != 0:
                        stop_job_process(process)
                    require(process.returncode == 0 and (run / "complete.json").exists(),
                            (run / "execution.log").read_text(errors="replace")[-1500:])
                with self.lock:
                    job.update(state="complete", finished_at=now())
                    self.persist_job(job)
            except (OSError, RecorderError) as exc:
                with self.lock:
                    job.update(state="interrupted" if self.stop.is_set() else "failed", error=str(exc), finished_at=now())
                    self.persist_job(job)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            # Seeking or leaving a video cancels an in-flight media response.
            self.close_connection = True

    def log_message(self, *args):
        pass

    def guard(self, mutation=False):
        expected = f"127.0.0.1:{self.server.server_port}"
        require(self.headers.get("Host") == expected, "loopback host required")
        require(self.headers.get("Sec-Fetch-Site") not in {"cross-site", "same-site"}, "cross-site access denied")
        origin = self.headers.get("Origin")
        require(origin is None or origin == "http://" + expected, "origin denied")
        if mutation:
            require(secrets.compare_digest(self.headers.get("X-Lab-Token", ""), self.server.lab.token), "session token required")

    def send(self, code, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def body_json(self):
        require(self.headers.get("Content-Type", "").split(";")[0] == "application/json", "JSON body required")
        size = int(self.headers.get("Content-Length", "0"))
        require(0 < size <= 65536, "request size limit")
        return json.loads(self.rfile.read(size), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid number")))

    def do_GET(self):
        try:
            self.guard()
            route = urlparse(self.path).path
            lab = self.server.lab
            if route == "/api/appearance":
                self.send(200, {**self.journal().state(), "token": lab.token})
            elif route in {"/appearance", "/appearance.js", "/appearance.css"} or (route == "/" and getattr(lab, "appearance_only", False)):
                name = "appearance.html" if route in {"/", "/appearance"} else route[1:]
                path = Path(__file__).parent / "lab_static" / name
                self.send(200, path.read_bytes(), mimetypes.guess_type(name)[0] + "; charset=utf-8")
            elif getattr(lab, "appearance_only", False) and route != "/lab.css":
                self.send(404, {"error": "appearance journal only"})
            elif route in {"/", "/lab.js", "/lab.css"}:
                name = "lab.html" if route == "/" else route[1:]
                path = Path(__file__).parent / "lab_static" / name
                self.send(200, path.read_bytes(), mimetypes.guess_type(name)[0] + "; charset=utf-8")
            elif route == "/api/state":
                with lab.lock:
                    self.send(200, {"token": lab.token, "images": lab.catalog, "models": lab.models,
                                    "jobs": list(lab.jobs.values()), "device": lab.device,
                                    "reference": {"model_id": lab.reference["model_id"]} if lab.reference else None,
                                    "verification": lab.verification(),
                                    "training_experiment": read_json(lab.storage / "training-results.json") if (lab.storage / "training-results.json").exists() else None,
                                    "public_research": read_json(lab.storage / "public-research-results.json") if (lab.storage / "public-research-results.json").exists() else None,
                                    "diversity_experiment": read_json(lab.storage / "diversity-experiment.json") if (lab.storage / "diversity-experiment.json").exists() else None,
                                    "camera_experiment": read_json(lab.storage / "camera-experiment.json") if (lab.storage / "camera-experiment.json").exists() else None,
                                    "captive_experiment": read_json(lab.storage / "captive-experiment.json") if (lab.storage / "captive-experiment.json").exists() else None,
                                    "tracking_check": read_json(lab.storage / "tracking-check.json") if (lab.storage / "tracking-check.json").exists() else None,
                                    "visual_memory_check": lab.visual_memory_check(),
                                    "camera_input": lab.watch_state, "camera_connected": False, "field_validated": False})
            elif route.startswith("/api/jobs/"):
                self.send(200, lab.job_detail(route.rsplit("/", 1)[1]))
            elif route == "/api/evaluation":
                with lab.lock:
                    self.send(200, evaluate_reviewed_windows(lab.reviewed_windows(), lab.reference))
            elif route == "/api/behavior-labels":
                self.send(200, lab.behavior_labels())
            elif route.startswith("/media/"):
                key = route.rsplit("/", 1)[1]
                with lab.lock:
                    require(key in lab.assets, "unknown media")
                    path = lab.assets[key]
                self.send_media(path)
            else:
                self.send(404, {"error": "not found"})
        except (RecorderError, ValueError, KeyError, OSError, TypeError) as exc:
            self.send(400, {"error": str(exc)})

    def send_media(self, path):
        size = path.stat().st_size
        start, end = 0, size - 1
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
            if not match:
                self.send(416, {"error": "single byte range required"})
                return
            start = int(match[1])
            end = min(int(match[2]) if match[2] else end, end)
            if not 0 <= start <= end < size:
                self.send(416, {"error": "range outside media"})
                return
        self.send_response(206 if requested else 200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("X-Content-Type-Options", "nosniff")
        if requested:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                block = stream.read(min(65536, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def do_POST(self):
        try:
            self.guard(mutation=True)
            self.connection.settimeout(120)
            route = urlparse(self.path).path
            if route == "/api/appearance/records":
                self.send(201, self.journal().record(self.body_json()))
            elif route == "/api/appearance/photo":
                self.connection.settimeout(10)
                size = int(self.headers.get("Content-Length", "0"))
                require(0 < size <= MAX_PHOTO, "photo must be at most 8 MiB")
                content = self.rfile.read(size)
                require(len(content) == size, "photo upload interrupted")
                self.send(201, self.journal().photo(content, unquote(self.headers.get("X-Filename", ""))))
            elif getattr(self.server.lab, "appearance_only", False):
                self.close_connection = True
                self.send(404, {"error": "appearance journal only"})
            elif route == "/api/upload":
                self.upload()
            elif route == "/api/jobs":
                self.send(201, self.server.lab.create_job(self.body_json()))
            elif route == "/api/review":
                self.send(200, self.server.lab.review(self.body_json()))
            elif route == "/api/behavior-review":
                self.send(200, self.server.lab.behavior_review(self.body_json()))
            elif route == "/api/retry":
                self.send(201, self.server.lab.retry_job(self.body_json()["job_id"]))
            elif route == "/api/reference":
                self.body_json()
                self.send(200, self.server.lab.train_reference())
            else:
                self.send(404, {"error": "not found"})
        except (RecorderError, ValueError, KeyError, OSError, TypeError) as exc:
            self.close_connection = True
            self.send(400, {"error": str(exc)})

    def journal(self):
        lab = self.server.lab
        if getattr(lab, "appearance_only", False):
            return lab.journal
        with lab.lock:
            if not hasattr(lab, "journal"):
                lab.journal = Journal(lab.storage / "appearance-journal")
            return lab.journal

    def upload(self):
        lab = self.server.lab
        size = int(self.headers.get("Content-Length", "0"))
        require(0 < size <= MAX_UPLOAD, "영상은 256MiB 이하입니다. 짧은 원본 구간을 사용하세요.")
        name = Path(unquote(self.headers.get("X-Filename", "video.mp4"))).name
        suffix = Path(name).suffix.lower()
        require(suffix in VIDEO_SUFFIXES and len(name) <= 240, "MP4/MOV/MKV/WebM 파일을 선택하세요.")
        with lab.lock:
            used = sum(p.stat().st_size for p in lab.storage.rglob('*') if p.is_file())
            require(used + size <= 10 * 1024**3 and shutil.disk_usage(lab.storage).free > size + 1024**3, "영상 저장 공간 한도 또는 여유 공간 부족")
            key = uuid4().hex
            partial = lab.storage / "uploads" / (key + ".partial")
            try:
                with partial.open("xb") as stream:
                    remaining = size
                    while remaining:
                        block = self.rfile.read(min(1024**2, remaining))
                        require(block, "영상 전송이 중단되었습니다.")
                        stream.write(block)
                        remaining -= len(block)
                    stream.flush()
                    os.fsync(stream.fileno())
                final = partial.with_suffix(suffix)
                partial.replace(final)
                metadata = {"id": key, "name": name, "suffix": suffix, "bytes": size, "sha256": digest(final), "received_at": now()}
                save_artifact(final.with_suffix(".json"), metadata)
            finally:
                partial.unlink(missing_ok=True)
        self.send(201, metadata)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local crested gecko evidence and video workbench")
    parser.add_argument("--storage", type=Path, default=ROOT / "data/vision-lab")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--open-browser", action="store_true", help="Open the local workbench after startup")
    parser.add_argument("--watch-config", type=Path, help="Recorder config for automatic finalized-file ingestion")
    parser.add_argument("--conditions", default="", help="Operator-declared camera conditions, e.g. night-ir")
    parser.add_argument("--process-job", nargs=2, metavar=("STORAGE", "JOB_ID"))
    parser.add_argument("--appearance-only", action="store_true", help="Manual diary only; no camera, model loading, or analysis worker")
    parser.add_argument("--test-journal", action="store_true", help="Mark the separate diary storage as synthetic test data")
    args = parser.parse_args(argv)
    if args.appearance_only and (args.process_job or args.watch_config):
        parser.error("appearance-only cannot start camera ingestion or analysis")
    if args.test_journal and not args.appearance_only:
        parser.error("test-journal requires appearance-only and separate storage")
    if args.process_job:
        process_job(Path(args.process_job[0]), args.process_job[1])
        return
    args.storage.mkdir(parents=True, exist_ok=True)
    with lock(args.storage / ".server.lock"):
        if args.appearance_only:
            lab = SimpleNamespace(appearance_only=True, storage=args.storage, token=secrets.token_urlsafe(32),
                                  journal=Journal(args.storage / "appearance-journal", dataset_kind="test" if args.test_journal else "real"))
        else:
            lab = Lab(args.storage, device=args.device, watch_config=args.watch_config, conditions=args.conditions)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        server.daemon_threads = True
        server.lab = lab
        worker = threading.Thread(target=lab.worker, daemon=True) if not args.appearance_only else None
        watcher = threading.Thread(target=lab.watch_inbox, daemon=True) if args.watch_config else None
        if worker:
            worker.start()
        if watcher:
            watcher.start()
        print(f"Vision Lab: http://127.0.0.1:{server.server_port}", flush=True)
        if args.open_browser:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{server.server_port}")
        def shutdown_signal(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, shutdown_signal)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, shutdown_signal)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if worker:
                lab.stop.set()
            server.server_close()
            if worker:
                worker.join(timeout=15)
            if watcher:
                watcher.join(timeout=10)


if __name__ == "__main__":
    main()
