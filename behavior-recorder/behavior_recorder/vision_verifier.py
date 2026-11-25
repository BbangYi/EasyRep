"""Small, deterministic pieces of the experimental crop-presence verifier."""
from collections import Counter
import math

from .core import number, require


def padded_crop_box(box, width, height, padding=.1):
    require(type(width) is int and width > 0 and type(height) is int and height > 0,
            "invalid image dimensions")
    require(isinstance(box, (list, tuple)) and len(box) == 4, "box requires four coordinates")
    x1, y1, x2, y2 = [number(v, -1e8, 1e8) for v in box]
    number(padding, 0, 1)
    require(x2 > x1 and y2 > y1, "empty box")
    dx, dy = (x2-x1)*padding, (y2-y1)*padding
    crop = [max(0, math.floor(x1-dx)), max(0, math.floor(y1-dy)),
            min(width, math.ceil(x2+dx)), min(height, math.ceil(y2+dy))]
    require(crop[0] < crop[2] and crop[1] < crop[3], "crop is outside image")
    return crop


def source_balanced_weights(rows):
    """Each class has half the loss; each image has equal weight within its class."""
    require(isinstance(rows, list) and rows, "training rows required")
    labels, counts = {}, Counter()
    for row in rows:
        identifier, label = row.get("id"), row.get("presence_label")
        require(isinstance(identifier, str) and identifier, "source image id required")
        require(type(label) is int and label in (0, 1), "presence label must be 0 or 1")
        require(identifier not in labels or labels[identifier] == label, "conflicting source labels")
        labels[identifier] = label
        counts[identifier] += 1
    class_images = Counter(labels.values())
    require(set(class_images) == {0, 1}, "both presence classes required")
    return [.5 / (class_images[row["presence_label"]] * counts[row["id"]]) for row in rows]


def presence_threshold(positive_scores, minimum_recall=.95):
    """Largest observed positive score retaining the required integer count."""
    require(isinstance(positive_scores, list) and positive_scores, "positive calibration scores required")
    number(minimum_recall, 1e-9, 1)
    scores = sorted(number(score, 0, 1) for score in positive_scores)
    required = math.ceil(minimum_recall * len(scores))
    return scores[len(scores)-required]


def score_feature_vector(features, head):
    """Score stored features using fit-only statistics; no tensor runtime required."""
    dimensions = head.get("feature_dim")
    require(type(dimensions) is int and 0 < dimensions <= 4096, "invalid feature dimension")
    require(len(features) == dimensions, "feature dimension mismatch")
    require(len(head["mean"]) == len(head["std"]) == dimensions, "invalid feature statistics")
    values = [number(v, -1e12, 1e12) for v in features]
    indices, coefficients = head["active_indices"], head["coefficients"]
    require(indices and len(indices) == len(coefficients) and len(set(indices)) == len(indices),
            "invalid active feature inventory")
    terms = []
    for index, coefficient in zip(indices, coefficients):
        require(type(index) is int and 0 <= index < dimensions, "invalid active feature index")
        mean = number(head["mean"][index], -1e12, 1e12)
        scale = number(head["std"][index], 1e-12, 1e12)
        terms.append((values[index]-mean)/scale * number(coefficient, -1e12, 1e12))
    logit = number(head["bias"], -1e12, 1e12) + math.fsum(terms)
    require(math.isfinite(logit), "non-finite verifier score")
    if logit >= 0:
        return 1 / (1 + math.exp(-logit))
    exponential = math.exp(logit)
    return exponential / (1 + exponential)


def crop_verifier_image(image, crop):
    """Preserve the whole crop in the frozen 224px square-padding transform."""
    from PIL import Image
    require(len(crop) == 4 and all(type(v) is int for v in crop), "integer crop required")
    x1, y1, x2, y2 = crop
    require(0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height, "crop outside image")
    region = image.convert("RGB").crop(tuple(crop))
    side = max(region.size)
    square = Image.new("RGB", (side, side), (124, 116, 104))
    square.paste(region, ((side-region.width)//2, (side-region.height)//2))
    return square.resize((224, 224), Image.Resampling.BILINEAR)
