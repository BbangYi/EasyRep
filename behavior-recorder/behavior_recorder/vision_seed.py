"""Geometry for checking proposed tracking seeds against another detection."""
import math

from .core import number, require
from .vision_benchmark import intersection_over_union
from .vision_tracking_eval import checked_box


def padded_crop(box, width, height, padding=.25):
    number(width, 1, 16384); number(height, 1, 16384)
    checked_box(box, width, height)
    number(padding, 0, 2)
    x1, y1, x2, y2 = box
    dx, dy = (x2-x1)*padding, (y2-y1)*padding
    return [max(0, math.floor(x1-dx)), max(0, math.floor(y1-dy)),
            min(width, math.ceil(x2+dx)), min(height, math.ceil(y2+dy))]


def confirm_seed(proposal, crop, predictions, width, height, *, confidence=.4, iou=.3):
    number(width, 1, 16384); number(height, 1, 16384)
    checked_box(proposal, width, height)
    checked_box(crop, width, height)
    require(all(type(v) is int for v in crop), 'crop must use integer source pixels')
    require(crop[0] <= proposal[0] < proposal[2] <= crop[2] and
            crop[1] <= proposal[1] < proposal[3] <= crop[3], 'crop must contain the proposal')
    number(confidence, .01, .99); number(iou, .1, .95)
    require(isinstance(predictions, list) and len(predictions) <= 100, 'invalid verification predictions')
    matches = []
    for prediction in predictions:
        require(isinstance(prediction, dict), 'invalid verification prediction')
        box, score = prediction.get('xyxy'), prediction.get('confidence')
        checked_box(box, crop[2]-crop[0], crop[3]-crop[1])
        number(score, 0, 1)
        mapped = [box[0]+crop[0], box[1]+crop[1], box[2]+crop[0], box[3]+crop[1]]
        overlap = intersection_over_union(proposal, mapped)
        if score >= confidence and overlap >= iou:
            matches.append(dict(accepted=True, confirmed_box=mapped, confidence=score, iou=overlap))
    return max(matches, key=lambda row: (row['confidence'], row['iou'])) if matches else dict(
        accepted=False, confirmed_box=None, confidence=None, iou=None)


def choose_consensus_seed(primary, secondary, width, height, *, primary_confidence=.4,
                          secondary_confidence=.25, iou=.5):
    """Retain a primary box only when another detector agrees in the same source frame.

    Agreement is a seed gate, not proof of animal identity or calibrated confidence.
    The caller must ensure both lists came from the identical frame and pixel geometry.
    """
    number(width, 1, 16384); number(height, 1, 16384)
    number(primary_confidence, .01, .99); number(secondary_confidence, .01, .99); number(iou, .1, .95)
    for predictions in (primary, secondary):
        require(isinstance(predictions, list) and len(predictions) <= 100, 'invalid seed predictions')
        for prediction in predictions:
            require(isinstance(prediction, dict), 'invalid seed prediction')
            checked_box(prediction.get('xyxy'), width, height)
            number(prediction.get('confidence'), 0, 1)
    matches = []
    for index, proposal in enumerate(primary):
        if proposal['confidence'] < primary_confidence:
            continue
        for confirmation in secondary:
            overlap = intersection_over_union(proposal['xyxy'], confirmation['xyxy'])
            if confirmation['confidence'] >= secondary_confidence and overlap >= iou:
                matches.append(dict(box=list(proposal['xyxy']), primary_index=index,
                                    confidence=proposal['confidence'], agreement_iou=overlap,
                                    confirmation_box=list(confirmation['xyxy']),
                                    confirmation_confidence=confirmation['confidence']))
    return max(matches, key=lambda r: (r['confidence'], r['agreement_iou'], r['confirmation_confidence'])) if matches else None
