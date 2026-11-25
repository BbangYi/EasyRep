"""Causal image-discontinuity guard; it does not identify animals or their absence."""
from .core import require


class SceneBoundary:
    """Use the HSV content score and default 27 threshold documented by PySceneDetect."""
    def __init__(self):
        self.previous = None
        self.shape = None
        self.cuts = 0

    def update(self, frame):
        import cv2
        import numpy as np
        require(isinstance(frame, np.ndarray) and frame.ndim == 3 and frame.shape[2] == 3
                and frame.dtype == np.uint8 and min(frame.shape[:2]) > 0, "scene guard requires a uint8 BGR frame")
        height, width = frame.shape[:2]
        target_width = min(320, width)
        image = cv2.resize(frame, (target_width, max(1, round(height * target_width / width))),
                           interpolation=cv2.INTER_AREA)
        current = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.int16)
        dimensions_changed = self.shape is not None and self.shape != frame.shape
        delta = None
        if self.previous is not None and not dimensions_changed:
            delta = np.abs(current - self.previous).mean(axis=(0, 1)).tolist()
        score = sum(delta) / 3 if delta is not None else None
        cut = dimensions_changed or (score is not None and score >= 27.0)
        self.previous, self.shape = current, frame.shape
        self.cuts += int(cut)
        return {"cut": cut, "content_score": score, "hsv_delta": delta,
                "reason": "dimensions_changed" if dimensions_changed else "content_change" if cut else None}

    def summary(self):
        return {"implementation": "causal-hsv-27-v1", "threshold": 27.0, "analysis_max_width": 320,
                "cuts_detected": self.cuts, "future_frames_used": False,
                "reference": "https://www.scenedetect.com/docs/latest/api/detectors.html#contentdetector",
                "limitation": "May miss similar-looking cuts or reset on fast motion/lighting changes. Not an absence detector."}
