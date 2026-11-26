import copy
import pytest
from pydantic import ValidationError
from habitat.vision.behavior_dataset import Dataset


def test_reviewed_labels_split_integrity_and_no_diagnosis_from_video():
    data = {"species": "Correlophus ciliatus", "clips": [
        {"file": f"{i}.mkv", "sha256": str(i)*64, "subject_id": f"GECKO-{i}",
         "enclosure_id": f"CAGE-{i}", "capture_day": f"2026-10-0{i+1}", "session_id": f"SESSION-{i}",
         "split": split, "annotator": "A", "reviewer": "B",
         "annotations": [{"start_s": 0, "end_s": 1, "labels": ["moving", "climbing"]}]}
        for i, split in enumerate(("train", "validation", "test"))]}
    assert len(Dataset.model_validate(data).clips) == 3
    for key in ("subject_id", "enclosure_id", "capture_day", "session_id", "sha256"):
        invalid = copy.deepcopy(data)
        invalid["clips"][1][key] = invalid["clips"][0][key]
        with pytest.raises(ValidationError, match="leakage"):
            Dataset.model_validate(invalid)
    for label in ("sleeping", "sick", "hungry", "thirsty"):
        invalid = copy.deepcopy(data)
        invalid["clips"][0]["annotations"][0]["labels"] = [label]
        with pytest.raises(ValidationError):
            Dataset.model_validate(invalid)
    for fields in ({"start_s": 2, "end_s": 1}, {"labels": ["moving", "unobservable"]}):
        invalid = copy.deepcopy(data)
        invalid["clips"][0]["annotations"][0].update(fields)
        with pytest.raises(ValidationError):
            Dataset.model_validate(invalid)
    invalid = copy.deepcopy(data)
    invalid["clips"][0]["reviewer"] = "A"
    with pytest.raises(ValidationError):
        Dataset.model_validate(invalid)
