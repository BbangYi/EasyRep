"""Conservative supervision from reviewed coarse masks; -1 pixels are unknown."""
import cv2
import numpy as np

from behavior_recorder.core import require


def build_weak_target(masks, boxes, target_index, *, margin=8):
    """Return -1 unknown, 0 distant background, 1 target core, 2 other core.

    Callers must review mask ownership and box coverage first. Erosion cannot
    repair a mask that includes the wrong animal or large background regions.
    """
    require(isinstance(masks, np.ndarray) and masks.dtype == bool and masks.ndim == 3,
            'Expected boolean instance masks')
    count, height, width = masks.shape
    require(count > 0 and height > 0 and width > 0, 'Empty mask set')
    require(type(target_index) is int and 0 <= target_index < count, 'Invalid target index')
    require(type(margin) is int and 0 < margin < min(height, width), 'Invalid uncertainty margin')
    boxes = np.asarray(boxes, dtype=float)
    require(boxes.shape == (count, 4) and np.isfinite(boxes).all(), 'Invalid reference boxes')
    require(bool(np.all(boxes[:, :2] >= 0) and np.all(boxes[:, 2] <= width)
                 and np.all(boxes[:, 3] <= height) and np.all(boxes[:, :2] < boxes[:, 2:])),
            'Reference box outside image or empty')
    kernel = np.ones((2 * margin + 1, 2 * margin + 1), np.uint8)
    cores = np.stack([cv2.erode(mask.astype(np.uint8), kernel, borderType=cv2.BORDER_CONSTANT,
                              borderValue=0).astype(bool) for mask in masks])
    expanded = np.stack([cv2.dilate(mask.astype(np.uint8), kernel).astype(bool) for mask in masks])
    uncertain = expanded.any(axis=0)
    for x1, y1, x2, y2 in boxes:
        uncertain[max(0, int(np.floor(y1)) - margin):min(height, int(np.ceil(y2)) + margin),
                  max(0, int(np.floor(x1)) - margin):min(width, int(np.ceil(x2)) + margin)] = True
    others = np.arange(count) != target_index
    target_core = cores[target_index] & ~expanded[others].any(axis=0)
    other_core = cores[others].any(axis=0) & ~expanded[target_index]
    require(bool(target_core.any()), 'No unambiguous foreground core remains')
    labels = np.full((height, width), -1, dtype=np.int8)
    labels[~uncertain] = 0
    labels[target_core] = 1
    labels[other_core] = 2
    return labels
