"""Camera-optional human diary. Attachments are unreviewed, never training data."""
import hashlib
from pathlib import Path
import re

from .analysis_features import fingerprint, save_artifact
from .core import digest, identifier, lock, now, read_json, relative, require, timestamp

MAX_PHOTO = 8 * 1024**2
MAX_RECORDS = 512
ASSESSMENTS = {"usual", "paler", "started", "completed", "uncertain"}
INPUT_FIELDS = {"record_id", "animal_id", "enclosure_id", "observer", "earliest_at", "latest_at",
                "assessment", "note", "identity_confirmed", "photo_id"}


class Journal:
    def __init__(self, storage, *, dataset_kind="real", read_only=False):
        self.storage = Path(storage).resolve()
        require(dataset_kind in {"test", "real"}, "invalid dataset kind")
        self.dataset_kind = dataset_kind
        self.read_only = read_only
        expected = {"schema_version": 1, "dataset_kind": dataset_kind, "species": "crested_gecko"}
        if read_only:
            require(self.storage.is_dir() and all(relative(self.storage, name).is_dir()
                    for name in ("records", "photos")), "existing journal required for read-only access")
            require(read_json(relative(self.storage, "journal.json"), limit=65536) == expected,
                    "journal dataset kind mismatch")
            return
        self.storage.mkdir(parents=True, exist_ok=True)
        for name in ("records", "photos"):
            relative(self.storage, name).mkdir(exist_ok=True)
        settings = relative(self.storage, "journal.json")
        with lock(self.storage / ".write.lock"):
            if settings.exists():
                require(read_json(settings) == expected, "journal dataset kind mismatch; use separate storage")
            else:
                save_artifact(settings, expected)

    def validate(self, row):
        require(isinstance(row, dict) and set(row) == INPUT_FIELDS, "invalid diary fields")
        require(isinstance(row["record_id"], str) and re.fullmatch(r"[0-9a-f]{32}", row["record_id"]), "invalid record ID")
        for key in ("animal_id", "observer"):
            identifier(row[key])
        if row["enclosure_id"] is not None:
            identifier(row["enclosure_id"])
        require(row["identity_confirmed"] is True, "confirm the observed individual")
        first, last = timestamp(row["earliest_at"]), timestamp(row["latest_at"])
        require(first is not None and last is not None and first <= last, "ordered, timezone-aware observation interval required")
        require(last <= timestamp(now()), "observation cannot be in the future")
        require(isinstance(row["assessment"], str) and row["assessment"] in ASSESSMENTS, "invalid assessment")
        require(isinstance(row["note"], str) and 0 < len(row["note"].strip()) <= 2000, "observation note required, up to 2000 characters")
        photo_id = row["photo_id"]
        require(photo_id is None or (isinstance(photo_id, str) and re.fullmatch(r"[0-9a-f]{64}", photo_id)), "invalid photo ID")

    def photo(self, content, name):
        require(not self.read_only, "read-only journal cannot store attachments")
        require(isinstance(name, str) and 0 < len(name) <= 240 and Path(name).name == name and "\\" not in name,
                "invalid photo filename")
        require(0 < len(content) <= MAX_PHOTO, "photo must be at most 8 MiB")
        suffix = Path(name).suffix.lower()
        require((suffix == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or
                (suffix in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff")), "PNG or JPEG signature required")
        # Bytes are retained without decoding, resizing, feature extraction, or asserting image validity.
        key = hashlib.sha256(content).hexdigest()
        path = relative(self.storage, f"photos/{key}.source")
        metadata_path = relative(self.storage, f"photos/{key}.json")
        with lock(self.storage / ".write.lock"):
            if metadata_path.exists():
                metadata = read_json(metadata_path)
                require(path.is_file() and digest(path) == key, "stored attachment changed")
                return metadata
            files = list((self.storage / "photos").iterdir())
            require(len(files) < 2 * MAX_RECORDS and sum(p.stat().st_size for p in files) + len(content) <= 256 * 1024**2,
                    "diary attachment storage limit reached")
            if path.exists():
                require(digest(path) == key, "incomplete attachment retained; use another storage location")
            else:
                with path.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    import os
                    os.fsync(stream.fileno())
            metadata = {"id": key, "path": f"photos/{key}.source", "original_name": name,
                        "bytes": len(content), "sha256": key, "received_at": now(),
                        "status": "unreviewed_attachment", "decoded": False, "media_rights_verified": False}
            save_artifact(metadata_path, metadata)
            return metadata

    def record(self, row):
        require(not self.read_only, "read-only journal cannot store records")
        self.validate(row)
        with lock(self.storage / ".write.lock"):
            photo = None
            if row["photo_id"] is not None:
                metadata_path = relative(self.storage, f"photos/{row['photo_id']}.json")
                require(metadata_path.is_file(), "unknown photo ID")
                photo = read_json(metadata_path)
                path = relative(self.storage, f"photos/{row['photo_id']}.source")
                require(path.is_file() and path.stat().st_size <= MAX_PHOTO and digest(path) == row["photo_id"],
                        "stored attachment changed")
            path = relative(self.storage, f"records/{row['record_id']}.json")
            if path.exists():
                previous = self.load(path)
                require(previous["input"] == row, "record ID already has different content")
                return previous
            require(len(list((self.storage / "records").glob("*.json"))) < MAX_RECORDS, "diary record limit reached")
            record = {"schema_version": 1, "kind": "appearance_diary_entry", "dataset_kind": self.dataset_kind,
                      "species": "crested_gecko", "received_at": now(), "input": row,
                      "input_sha256": fingerprint(row), "photo": photo,
                      "identity_basis": "operator_declared_not_independently_verified",
                      "training_admitted": False, "prediction": None, "actuation_allowed": False}
            save_artifact(path, record)
            return record

    def load(self, path):
        record = read_json(relative(self.storage, f"records/{path.name}"), limit=65536)
        self.validate(record["input"])
        require(record["input_sha256"] == fingerprint(record["input"]) and
                record["dataset_kind"] == self.dataset_kind and record["species"] == "crested_gecko" and
                record["kind"] == "appearance_diary_entry" and record["schema_version"] == 1 and
                record["input"]["record_id"] == path.stem and record["training_admitted"] is False and
                record["prediction"] is None and record["actuation_allowed"] is False, "diary record integrity mismatch")
        return record

    def state(self):
        paths = list((self.storage / "records").glob("*.json"))
        require(len(paths) <= MAX_RECORDS, "diary record limit exceeded")
        records = [self.load(path) for path in paths]
        records.sort(key=lambda row: (timestamp(row["input"]["earliest_at"]), row["input"]["record_id"]))
        return {"dataset_kind": self.dataset_kind, "records": records, "prediction": None,
                "prediction_status": "not_implemented", "training_readiness": "not_assessed",
                "actuation_allowed": False, "camera_required": False,
                "limits": {"record_count": MAX_RECORDS, "photo_bytes": MAX_PHOTO}}
