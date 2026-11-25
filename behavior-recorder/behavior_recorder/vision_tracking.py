"""Time-bounded ByteTrack associations with conservative, video-local track segments."""
from collections import Counter
import math
import re
from types import SimpleNamespace

from .core import number, require
from .vision_benchmark import intersection_over_union

TRACKING_REVISION = 2


def _distinct_continuations(overlaps, assignments, ambiguous):
    continuing = set()
    for index, candidates in overlaps.items():
        key = assignments.get(index)
        if index in ambiguous or key not in candidates:
            continue
        own = candidates[key]
        if (own >= 0.1 and all(own > score for other, score in candidates.items() if other != key)
                and all(own > scores[key] for other, scores in overlaps.items() if other != index)):
            continuing.add(key)
    return continuing


def tracking_options(config):
    require(config.get("camera_motion", "off") in {"off", "background-affine-v1"}, "unsupported camera motion mode")
    require(config.get("camera_motion", "off") == "off" or not config.get("target_seed"),
            "moving camera mode does not support an image-coordinate target seed")
    options = {"lost_seconds": config.get("track_lost_seconds", 1.0),
               "nms_iou": config.get("nms_iou", 0.5),
               "overlap_iou": config.get("association_overlap_iou", 0.3)}
    number(options["lost_seconds"], 0.01, 10)
    number(options["nms_iou"], 0.1, 0.9)
    number(options["overlap_iou"], 0.05, 0.9)
    if config.get("target_seed") is not None:
        seed = config["target_seed"]
        require(isinstance(seed, dict) and set(seed) == {"source_sha256", "xyxy"}, "invalid target seed")
        require(isinstance(seed["source_sha256"], str) and len(seed["source_sha256"]) == 64 and
                all(c in "0123456789abcdef" for c in seed["source_sha256"]), "target seed source hash required")
        require(isinstance(seed["xyxy"], list) and len(seed["xyxy"]) == 4, "target seed needs normalized xyxy")
        x1, y1, x2, y2 = [number(v, 0, 1) for v in seed["xyxy"]]
        require(x2 > x1 and y2 > y1, "target seed must have positive area")
    return options


class SeededTarget:
    """Optional one-animal aid: select detector proposals near an explicitly designated initial body."""
    def __init__(self, config, width, height):
        self.lost_seconds = tracking_options(config)["lost_seconds"]
        self.confidence = config["confidence"]
        self.box = [v * size for v, size in zip(config["target_seed"]["xyxy"], (width, height, width, height))]
        self.last_seen = 0.0
        self.expired = False

    def select(self, boxes, offset):
        number(offset, 0, 3600)
        if self.expired or offset - self.last_seen > self.lost_seconds:
            self.expired = True
            return [], "seed_lost_requires_new_selection"
        area = (self.box[2] - self.box[0]) * (self.box[3] - self.box[1])
        candidates = []
        for index, box in enumerate(boxes):
            x1, y1, x2, y2 = box["xyxy"]
            ratio = (x2 - x1) * (y2 - y1) / area
            overlap = intersection_over_union(self.box, box["xyxy"])
            if 0.4 <= ratio <= 2.5 and overlap >= 0.35:
                candidates.append((overlap, index))
        # Match strong proposals first; weak boxes are only a rescue when no strong match exists.
        candidates = [item for item in candidates if boxes[item[1]]["confidence"] >= self.confidence] or candidates
        candidates.sort(reverse=True)
        if not candidates:
            return [], "no_matching_seed_candidate"
        if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.1:
            return [], "ambiguous_seed_candidates"
        selected = boxes[candidates[0][1]]
        self.box, self.last_seen = selected["xyxy"], offset
        return [selected], "seed_matched"


class VideoTracker:
    """IDs denote continuous track segments, never biological identity or cross-video ReID."""
    def __init__(self, config, width, height, *, fuse_confirmation_score=True, memory_association=False,
                 memory_pending_association=False):
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.trackers.utils import matching
        require(type(fuse_confirmation_score) is bool, "confirmation score fusion must be boolean")
        require(type(memory_association) is bool, "memory association must be boolean")
        require(type(memory_pending_association) is bool and (not memory_pending_association or memory_association),
                "pending memory association requires memory association")
        self.memory_association = memory_association
        self.memory_pending_association = memory_pending_association

        class ConfirmationTracker(BYTETracker):
            def get_dists(self, tracks, detections):
                # Hybrid scores encode the acceptance gate, not association probabilities.
                if not fuse_confirmation_score and tracks and all(not t.is_activated for t in tracks):
                    return matching.iou_distance(tracks, detections)
                return super().get_dists(tracks, detections)

        self.fuse_confirmation_score = fuse_confirmation_score
        self.config, self.width, self.height = config, width, height
        self.options = tracking_options(config)
        self.detector_confidence = min(0.1, config["confidence"] / 2)
        self.engine = ConfirmationTracker(SimpleNamespace(
            track_high_thresh=config["confidence"], track_low_thresh=self.detector_confidence,
            new_track_thresh=config["confidence"],
            track_buffer=max(1, math.ceil(self.options["lost_seconds"] * config["sample_fps"])),
            match_thresh=0.8, fuse_score=True))
        self.states, self.next_segment, self.frame_number = {}, 1, 0
        self.pending = {}
        self.last_time = None
        self.frame_times = {}
        self.counts = Counter()

    def reset_for_scene_change(self):
        ended = sorted(state["segment"] for state in self.states.values())
        self.engine.reset()
        self.states.clear()
        self.pending.clear()
        self.frame_times.clear()
        self.frame_number = 0
        # Preserve public segment numbering and source-time monotonicity across resets.
        self.counts["scene_change"] += 1
        return [{"kind": "scene_change", "ended_track_ids": ended}]

    def update(self, boxes, offset, *, camera_motion=None):
        import numpy as np
        from ultralytics.engine.results import Boxes
        number(offset, 0, 3600)
        require(self.last_time is None or offset > self.last_time, "tracking timestamps must increase")
        matrix = None
        if camera_motion is not None:
            require(self.config.get("camera_motion") == "background-affine-v1", "camera motion mode is disabled")
            require(camera_motion["to_offset_seconds"] == offset, "camera motion target time differs")
            if camera_motion["status"] == "estimated":
                require(camera_motion["from_offset_seconds"] == self.last_time, "stale camera transform")
                matrix = np.asarray(camera_motion["matrix"], dtype=float)
                require(matrix.shape == (2, 3) and np.isfinite(matrix).all(), "invalid camera transform")
            else:
                require(camera_motion["status"] == "unavailable" and camera_motion["matrix"] is None,
                        "invalid camera motion evidence")
        require(len(boxes) <= 100, "too many detection candidates")
        if self.memory_association:
            keys=[box.get('memory_object_id') for box in boxes]
            require(all(isinstance(key,str) and len(key)<=40 and re.fullmatch(r'[1-9]\d*:[1-9]\d*',key) for key in keys)
                    and len(keys)==len(set(keys)), 'Invalid or duplicated memory object identity')
        for box in boxes:
            require(len(box["xyxy"]) == 4, "invalid detection coordinates")
            x1, y1, x2, y2 = box["xyxy"]
            for v in (x1, x2):
                number(v, 0, self.width)
            for v in (y1, y2):
                number(v, 0, self.height)
            require(x2 > x1 and y2 > y1, "degenerate detection")
            number(box["confidence"], 0, 1)
        self.frame_number += 1
        self.last_time = offset
        self.frame_times[self.frame_number] = offset
        events = []
        # The library's buffer counts updates. Expire using source time before association,
        # including variable frame rates and long gaps without an intermediate update.
        expired = {key for key, state in self.states.items()
                   if offset - state["time"] > self.options["lost_seconds"]}
        for key in sorted(expired):
            events.append({"kind": "expired", "track_id": self.states[key]["segment"]})
            del self.states[key]
        self.engine.tracked_stracks = [t for t in self.engine.tracked_stracks if t.track_id not in expired]
        self.engine.lost_stracks = [t for t in self.engine.lost_stracks if t.track_id not in expired]
        # Unconfirmed library tracks also expire by time, even before a public ID exists.
        for name in ("tracked_stracks", "lost_stracks"):
            setattr(self.engine, name, [t for t in getattr(self.engine, name)
                                       if offset - self.frame_times.get(t.frame_id, -math.inf) <= self.options["lost_seconds"]])
        self.frame_times = {i: time for i, time in self.frame_times.items()
                            if offset - time <= self.options["lost_seconds"]}
        array = np.asarray([[*b["xyxy"], b["confidence"], 0] for b in boxes], dtype=np.float32).reshape(-1, 6)
        assigned = self.engine.update(Boxes(array, (self.height, self.width)))
        by_detection = {int(track[-1]): int(track[4]) for track in assigned}
        require(len(by_detection) == len(assigned), "tracker assigned multiple IDs to one detection")
        high = [i for i, b in enumerate(boxes) if b["confidence"] >= self.config["confidence"]]
        if self.memory_association:
            # A consecutive neural object slot can survive a box-shape association miss.
            # It never bridges a reset, missing frame, jump, or competing animal.
            pool = dict(self.states)
            if self.memory_pending_association:
                pool.update((key,state) for key,state in self.pending.items() if key not in pool)
            for index in high:
                source=boxes[index]
                candidates=[(key,state) for key,state in pool.items()
                            if state.get('memory_object_id')==source['memory_object_id']
                            and state['frame']==self.frame_number-1 and not state['unsafe']
                            and (state.get('hits',0)>=2 or (self.memory_pending_association
                                 and (state.get('hits',0)>=1 or state.get('confidence',0)>=self.config['confidence'])))
                            and offset-state['time']<=self.config['max_gap_seconds']]
                if len(candidates)!=1:continue
                previous_key,state=candidates[0];assigned_key=by_detection.get(index)
                if assigned_key==previous_key or (assigned_key is not None and assigned_key in self.states):continue
                if any(key==previous_key for other,key in by_detection.items() if other!=index):continue
                was_pending = previous_key not in self.states
                unconfirmed = was_pending or state['hits'] < 2
                x1,y1,x2,y2=source['xyxy'];center=[(x1+x2)/2,(y1+y2)/2]
                if (intersection_over_union(state['box'],source['xyxy'])<.1
                        or math.dist(center,state['center'])/math.hypot(self.width,self.height)>self.config['max_step_diagonals']
                        or any(intersection_over_union(state['box'],boxes[other]['xyxy'])>=.1 for other in high if other!=index)
                        or any(intersection_over_union(other['box'],source['xyxy'])>=.1 for key,other in pool.items()
                               if key!=previous_key and offset-other['time']<=self.config['max_gap_seconds'])):
                    continue
                if assigned_key is None:
                    by_detection[index]=previous_key
                elif was_pending:
                    self.pending[assigned_key]=self.pending.pop(previous_key)
                else:
                    self.states[assigned_key]=self.states.pop(previous_key)
                events.append(dict(kind='memory_pending_association_recovered' if unconfirmed else 'memory_association_recovered',
                                   track_id=state.get('segment'),
                                   memory_object_id=source['memory_object_id'],previous_raw_id=previous_key,
                                   assigned_raw_id=assigned_key))
        ambiguous, affected = set(), set()
        for index in high:
            box = boxes[index]["xyxy"]
            for other in high:
                if other != index and intersection_over_union(box, boxes[other]["xyxy"]) >= self.options["overlap_iou"]:
                    ambiguous.update((index, other))
        recent = {key: state for key, state in self.states.items()
                  if offset - state["time"] <= self.config["max_gap_seconds"]}
        overlaps = {index: {key: intersection_over_union(boxes[index]["xyxy"], state["box"])
                            for key, state in recent.items()} for index in high}
        # Distinct, mutual-best continuations are evidence against a merged box.
        continuing = _distinct_continuations(overlaps, by_detection, ambiguous)
        for index in high:
            # A merged box may hide two previously separate animals.
            possible = {key for key, score in overlaps[index].items() if score >= 0.1}
            separate = by_detection.get(index) in continuing and possible <= continuing
            if len(possible) > 1 and not separate:
                ambiguous.add(index)
                affected.update(possible)
        pending_overlaps = {index: {key: intersection_over_union(boxes[index]["xyxy"], state["box"])
                                    for key, state in self.pending.items() if not state["unsafe"]
                                    and offset - state["time"] <= self.config["max_gap_seconds"]}
                            for index in high}
        pending_continuing = _distinct_continuations(pending_overlaps, by_detection, ambiguous)
        for index in high:
            key = by_detection.get(index)
            # A one-frame candidate can veto its own confirmation, not an established track.
            if key not in self.pending or key in self.states:
                continue
            possible = {key for key, score in pending_overlaps[index].items() if score >= 0.1}
            if len(possible) > 1 and not (key in pending_continuing and possible <= pending_continuing):
                ambiguous.add(index)
        affected.update(by_detection[i] for i in ambiguous if i in by_detection)
        for key in affected:
            if key in self.states:
                self.states[key]["unsafe"] = True
        result, present = [], set()
        for index, source in enumerate(boxes):
            box = dict(source)
            raw_id = by_detection.get(index)
            box.update(track_id=None, raw_track_id=raw_id, identity_status="tentative", motion_allowed=False)
            state = self.states.get(raw_id)
            if index in ambiguous:
                box["identity_status"] = "ambiguous_association"
            if raw_id is None:
                result.append(box)
                continue
            present.add(raw_id)
            x1, y1, x2, y2 = box["xyxy"]
            center = [(x1 + x2) / 2, (y1 + y2) / 2]
            raw_step = math.dist(center, state["center"]) / math.hypot(self.width, self.height) if state else 0
            jump = raw_step > self.config["max_step_diagonals"]
            memory_changed = bool(self.memory_association and state
                                  and state["memory_object_id"] != source["memory_object_id"])
            consecutive = bool(state and not memory_changed and state["frame"] == self.frame_number - 1
                               and offset - state["time"] <= self.config["max_gap_seconds"])
            # Only rescue an established, exclusive ByteTrack continuation. Do not invent an association.
            if (jump and matrix is not None and consecutive and not state["unsafe"]
                    and index not in ambiguous and state["hits"] >= 2 and index in high
                    and offset - state["time"] <= self.config["max_gap_seconds"]):
                def warped_box(old):
                    x1, y1, x2, y2 = old
                    corners = np.asarray([[x1, y1, 1], [x2, y1, 1], [x1, y2, 1], [x2, y2, 1]]) @ matrix.T
                    return [*corners.min(axis=0), *corners.max(axis=0)]
                expected = warped_box(state["box"])
                residual = math.dist(center, matrix @ [*state["center"], 1]) / math.hypot(self.width, self.height)
                exclusive = (intersection_over_union(expected, box["xyxy"]) >= .5
                    and all(intersection_over_union(expected, boxes[other]["xyxy"]) < .1 for other in high if other != index)
                    and all(intersection_over_union(warped_box(old["box"]), box["xyxy"]) < .1
                            for key, old in recent.items() if key != raw_id))
                if exclusive and residual <= self.config["max_step_diagonals"]:
                    jump = False
                    events.append({"kind": "camera_jump_compensated", "track_id": state["segment"],
                                   "raw_step_diagonals": raw_step, "background_residual_diagonals": residual})
            pending = self.pending.get(raw_id)
            confirmed_pending = bool(state is None and pending and not pending["unsafe"]
                and index not in ambiguous and box["confidence"] >= self.config["confidence"]
                and (not self.memory_association or pending["memory_object_id"] == source["memory_object_id"])
                and pending["frame"] == self.frame_number - 1
                and offset - pending["time"] <= self.config["max_gap_seconds"]
                and math.dist(center, pending["center"]) / math.hypot(self.width, self.height)
                    <= self.config["max_step_diagonals"])
            if state is None or (state["unsafe"] and index not in ambiguous) or jump or memory_changed:
                segment = self.next_segment
                self.next_segment += 1
                if state is not None:
                    events.append({"kind": "segment_break", "previous_track_id": state["segment"],
                                   "track_id": segment, "reason": "memory_identity_changed" if memory_changed
                                   else "jump" if jump else "ambiguous_association"})
                state = {"segment": segment, "hits": 0}
            strong = box["confidence"] >= self.config["confidence"]
            state["hits"] = state["hits"] + 1 if strong and consecutive else int(strong)
            if confirmed_pending:
                # ByteTrack already saw the first strong box while withholding its public ID.
                state["hits"] = 2
                events.append({"kind": "confirmed_pending", "track_id": state["segment"]})
            if index in ambiguous:
                state["hits"] = 0
            elif jump:
                box["identity_status"] = "implausible_jump"
            elif not strong:
                box["identity_status"] = "low_confidence"
            elif state["hits"] >= 2:
                box["identity_status"] = "active"
                box["motion_allowed"] = True
            elif state.get("time") is not None and not consecutive:
                box["identity_status"] = "reacquired"
                events.append({"kind": "reacquired", "track_id": state["segment"]})
            box["track_id"] = state["segment"]
            # A jump already opened a new segment; only unresolved overlap needs another reset.
            state.update(time=offset, center=center, box=box["xyxy"], frame=self.frame_number,
                         unsafe=index in ambiguous)
            if self.memory_association:state['memory_object_id']=source['memory_object_id']
            self.states[raw_id] = state
            result.append(box)
        for box in result:
            if box["identity_status"] in {"ambiguous_association", "implausible_jump"}:
                events.append({"kind": box["identity_status"], "track_id": box["track_id"]})
        lost = [{"track_id": state["segment"], "last_seen_seconds": state["time"],
                 "missing_seconds": offset - state["time"]}
                for key, state in self.states.items() if key not in present]
        self.pending = {}
        for track in self.engine.tracked_stracks:
            if not track.is_activated and track.frame_id == self.frame_number:
                index = int(track.idx)
                # A fallback already represented this observation in states. The library's
                # extra pending raw ID must not compete with it on the next frame.
                if self.memory_pending_association and index in by_detection:
                    continue
                x1, y1, x2, y2 = boxes[index]["xyxy"]
                self.pending[track.track_id] = {"time": offset, "frame": self.frame_number,
                    "box": [x1, y1, x2, y2], "center": [(x1+x2)/2, (y1+y2)/2],
                    "unsafe": index in ambiguous}
                if self.memory_association:
                    self.pending[track.track_id]["memory_object_id"] = boxes[index]["memory_object_id"]
                if self.memory_pending_association:
                    self.pending[track.track_id]["confidence"] = boxes[index]["confidence"]
        self.counts.update(e["kind"] for e in events)
        return result, lost, events

    def summary(self):
        return {"revision": TRACKING_REVISION, "implementation": "bytetrack-segments-2.9",
                "camera_motion": self.config.get("camera_motion", "off"),
                "memory_slot_association": self.memory_association,
                "memory_pending_association": self.memory_pending_association,
                "confirmation_score_fusion": self.fuse_confirmation_score,
                "backend": "ByteTrack", "options": self.options,
                "segments_created": self.next_segment - 1, "events": dict(self.counts),
                "identity_scope": "video_local_segments_only", "reidentification": False,
                "limitation": "Overlap and jump guards cannot detect every ID switch. Labeled video evaluation required."}


class BackgroundMotion:
    """Bounded background-only registration; missing geometric evidence is not zero motion."""
    def __init__(self, confidence, max_gap_seconds):
        import cv2
        self.confidence = number(confidence, .05, .95)
        self.max_gap_seconds = number(max_gap_seconds, .01, 60)
        self.orb = cv2.ORB_create(nfeatures=1500)
        self.previous = None

    def update(self, frame, boxes, offset, *, cut=False):
        import cv2
        import numpy as np
        number(offset, 0, 3600)
        old = self.previous
        require(old is None or offset > old["offset"], "camera motion timestamps must increase")
        require(frame.ndim == 3 and frame.shape[2] == 3 and frame.dtype == np.uint8, "camera motion needs uint8 BGR")
        height, width = frame.shape[:2]
        require(old is None or old["shape"] == (height, width), "camera dimensions changed")
        scale = min(1, 640 / max(width, height))
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        sx, sy = size[0] / width, size[1] / height
        gray = cv2.cvtColor(cv2.resize(frame, size), cv2.COLOR_BGR2GRAY)
        mask = np.full(gray.shape, 255, dtype=np.uint8)
        for box in boxes:
            if box["confidence"] < self.confidence:
                continue
            x1, y1, x2, y2 = np.asarray(box["xyxy"]) * [sx, sy, sx, sy]
            mask[max(0, int(y1)-8):min(size[1], math.ceil(y2)+8),
                 max(0, int(x1)-8):min(size[0], math.ceil(x2)+8)] = 0
        keys, descriptors = self.orb.detectAndCompute(gray, mask)
        self.previous = {"offset": offset, "shape": (height, width), "keys": keys, "descriptors": descriptors}
        report = {"status": "unavailable", "reason": None, "matrix": None,
                  "from_offset_seconds": old["offset"] if old else None, "to_offset_seconds": offset,
                  "keypoints": len(keys), "matches": 0, "inliers": 0, "revision": 1}
        if old is None or cut or offset - old["offset"] > self.max_gap_seconds:
            report["reason"] = "first_frame" if old is None else "scene_cut" if cut else "time_gap"
            return report
        if descriptors is None or old["descriptors"] is None:
            report["reason"] = "insufficient_background_features"
            return report
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        forward = matcher.knnMatch(old["descriptors"], descriptors, k=2)
        reverse = matcher.knnMatch(descriptors, old["descriptors"], k=2)
        back = {m.queryIdx: m.trainIdx for pair in reverse if len(pair) == 2
                for m, n in [pair] if m.distance < .75 * n.distance}
        matches = [m for pair in forward if len(pair) == 2 for m, n in [pair]
                   if m.distance < .75 * n.distance and back.get(m.trainIdx) == m.queryIdx]
        report["matches"] = len(matches)
        if len(matches) < 12:
            report["reason"] = "insufficient_background_matches"
            return report
        before = np.float32([old["keys"][m.queryIdx].pt for m in matches])
        after = np.float32([keys[m.trainIdx].pt for m in matches])
        matrix, inliers = cv2.estimateAffinePartial2D(before, after, method=cv2.RANSAC,
            ransacReprojThreshold=2, maxIters=2000, confidence=.99)
        if matrix is None or not np.isfinite(matrix).all():
            report["reason"] = "registration_failed"
            return report
        keep = inliers.ravel().astype(bool)
        count = int(keep.sum())
        hull = min(cv2.contourArea(cv2.convexHull(points[keep])) / (size[0] * size[1])
                   for points in (before, after)) if count >= 3 else 0
        span = min(float((np.ptp(points[keep], axis=0) / size).min())
                   for points in (before, after)) if count else 0
        zoom = math.hypot(matrix[0, 0], matrix[1, 0])
        rotation = math.degrees(math.atan2(matrix[1, 0], matrix[0, 0]))
        shift = math.hypot(*matrix[:, 2]) / math.hypot(*size)
        report.update(inliers=count, inlier_fraction=count / len(matches), background_hull_fraction=hull,
                      background_span_fraction=span, scale=zoom, rotation_degrees=rotation)
        if (count < 12 or count / len(matches) < .75 or hull < .1 or span < .25
                or not .95 <= zoom <= 1.05 or abs(rotation) > 5 or shift > .35):
            report["reason"] = "unreliable_background_registration"
            return report
        # Undo the independently rounded preview axes; evidence and tracking use source pixels.
        full = np.diag([1/sx, 1/sy, 1]) @ np.vstack([matrix, [0, 0, 1]]) @ np.diag([sx, sy, 1])
        report.update(status="estimated", reason=None, matrix=full[:2].tolist())
        return report
