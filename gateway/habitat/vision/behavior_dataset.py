"""Validate reviewed crested-gecko action labels and leakage-free evaluation splits.

Usage: python -m habitat.vision.behavior_dataset /path/to/manifest.json
This validates data. It does not train a classifier or infer health states.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Literal

from pydantic import Field, model_validator
from habitat.common.models import Identifier, Model

Action = Literal["moving", "climbing", "stationary", "eating", "licking",
                 "hide_entry", "hide_exit", "other_visible", "unobservable", "uncertain"]


class Annotation(Model):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    labels: list[Action] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.start_s >= self.end_s or len(self.labels) != len(set(self.labels)):
            raise ValueError("annotation needs a positive interval and unique labels")
        if set(self.labels) & {"unobservable", "uncertain"} and len(self.labels) != 1:
            raise ValueError("unobserved/uncertain intervals cannot carry action labels")
        return self


class Clip(Model):
    file: str = Field(min_length=1)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    subject_id: Identifier
    enclosure_id: Identifier
    capture_day: date
    session_id: Identifier
    split: Literal["train", "validation", "test"]
    annotator: Identifier
    reviewer: Identifier
    annotations: list[Annotation] = Field(min_length=1)

    @model_validator(mode="after")
    def reviewed(self):
        if self.annotator == self.reviewer:
            raise ValueError("a second reviewer must confirm the labels")
        ordered = sorted(self.annotations, key=lambda a: a.start_s)
        if any(a.end_s > b.start_s for a, b in zip(ordered, ordered[1:])):
            raise ValueError("use multiple labels in one interval instead of overlapping intervals")
        return self


class Dataset(Model):
    species: Literal["Correlophus ciliatus"]
    clips: list[Clip] = Field(min_length=1)

    @model_validator(mode="after")
    def separate_groups(self):
        partitions = {}
        seen = set()
        for clip in self.clips:
            if clip.file in seen:
                raise ValueError("duplicate clip path")
            seen.add(clip.file)
            for key in ("subject_id", "enclosure_id", "capture_day", "session_id", "sha256"):
                group = (key, str(getattr(clip, key)))
                if group in partitions and partitions[group] != clip.split:
                    raise ValueError(f"train/evaluation leakage: {key}")
                partitions[group] = clip.split
        if {c.split for c in self.clips} != {"train", "validation", "test"}:
            raise ValueError("independent train, validation and test groups are required")
        return self


def validate_manifest(path):
    path = Path(path).resolve(strict=True)
    if path.stat().st_size > 4*1024**2:
        raise ValueError("manifest exceeds 4 MiB")
    dataset = Dataset.model_validate_json(path.read_text())
    counts = {}
    for clip in dataset.clips:
        video = (path.parent / clip.file).resolve(strict=True)
        if not video.is_relative_to(path.parent) or not video.is_file():
            raise ValueError("clip must be inside the dataset directory")
        digest = hashlib.sha256()
        with video.open("rb") as stream:
            for block in iter(lambda: stream.read(1024**2), b""):
                digest.update(block)
        if digest.hexdigest() != clip.sha256:
            raise ValueError("clip hash mismatch")
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "json", str(video)], check=True, capture_output=True,
                               text=True, timeout=20)
        duration = float(json.loads(probe.stdout)["format"]["duration"])
        if not 0 < duration < float("inf") or any(a.end_s > duration for a in clip.annotations):
            raise ValueError("annotation exceeds the decoded clip duration")
        for annotation in clip.annotations:
            for label in annotation.labels:
                key = clip.split + "/" + label
                counts[key] = counts.get(key, 0) + 1
    return {"species": dataset.species, "clips": len(dataset.clips), "annotation_counts": counts,
            "split_integrity": "pass", "model_trained": False,
            "note": "Unlabeled intervals are excluded, never treated as negative examples."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    print(json.dumps(validate_manifest(parser.parse_args().manifest), indent=2))
