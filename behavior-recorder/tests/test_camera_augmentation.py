import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from behavior_recorder.core import RecorderError
from behavior_recorder.vision_model import camera_augmentations, validate_training_options, verify_camera_augmentation


class CameraAugmentationTests(unittest.TestCase):
    def test_recipe_rejects_unknown_preset_and_missing_dependency(self):
        self.assertEqual(validate_training_options({"camera_augmentation": "grayscale-v1"}),
                         {"camera_augmentation": "grayscale-v1"})
        for value in (True, {}, "unknown", None):
            with self.assertRaises(RecorderError):
                validate_training_options({"camera_augmentation": value})
        self.assertEqual(camera_augmentations(None), [])
        with patch.dict(sys.modules, {"albumentations": None}):
            with self.assertRaisesRegex(RecorderError, "Albumentations"):
                camera_augmentations("grayscale-v1")

    def test_training_rejects_silently_disabled_transform(self):
        Albumentations = type("Albumentations", (), {})
        wrapper = Albumentations()
        wrapper.transform = None
        trainer = SimpleNamespace(train_loader=SimpleNamespace(dataset=SimpleNamespace(
            transforms=SimpleNamespace(transforms=[wrapper]))))
        with self.assertRaisesRegex(RecorderError, "not active"):
            verify_camera_augmentation(trainer)
        ToGray = type("ToGray", (), {"p": 0.35})
        RandomBrightnessContrast = type("RandomBrightnessContrast", (), {"p": 0.5})
        wrapper.transform = SimpleNamespace(transforms=[ToGray(), RandomBrightnessContrast()])
        verify_camera_augmentation(trainer)
        wrapper.transform.transforms[0].p = 0
        with self.assertRaisesRegex(RecorderError, "not active"):
            verify_camera_augmentation(trainer)
