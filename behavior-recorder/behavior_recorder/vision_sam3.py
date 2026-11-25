"""Experimental SAM3 + verified primary detector, with isolated neural runtimes."""
import json
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
from threading import Thread
from time import perf_counter

from .analysis_features import fingerprint
from .core import digest, number, read_json, relative, require
from .vision_benchmark import intersection_over_union
from .vision_hybrid import load_hybrid_bundle

VERIFIER_THRESHOLD = .7871378526750628
AUXILIARY_THRESHOLD = .5
PRIMARY_THRESHOLD = .4


def park_frozen_weights(model, cpu_state=None):
    """Reuse immutable CPU weights; only nonpersistent buffers need a device copy."""
    require(not any(module.training for module in model.modules())
            and not any(parameter.requires_grad for parameter in model.parameters()),
            'CPU weight reuse requires frozen inference modules')
    if cpu_state is not None:
        require(all(value.device.type == 'cpu' for value in cpu_state.values()), 'Weight snapshot left CPU')
        model.load_state_dict(cpu_state, strict=True, assign=True)
    model.to('cpu')
    return model.state_dict() if cpu_state is None else cpu_state


def select_sam3_queries(outputs):
    """Drop queries the unchanged route cannot accept before expanding their masks."""
    from types import SimpleNamespace
    import torch
    logits, boxes, masks, presence = (getattr(outputs, name) for name in
                                     ('pred_logits', 'pred_boxes', 'pred_masks', 'presence_logits'))
    require(logits.ndim == 2 and logits.shape[0] == 1 and boxes.shape == (*logits.shape, 4)
            and masks.ndim == 4 and masks.shape[:2] == logits.shape and presence.shape == (1, 1),
            'SAM3 query shapes differ')
    require(all(t.device.type == 'cpu' and t.dtype == torch.float32 for t in (logits, boxes, masks, presence)),
            'SAM3 query filtering requires float32 CPU outputs')
    scores = logits.sigmoid() * presence.sigmoid()
    require(bool(torch.isfinite(scores).all()), 'Nonfinite SAM3 scores')
    indices = torch.nonzero(scores[0] >= AUXILIARY_THRESHOLD, as_tuple=True)[0]
    selected = SimpleNamespace(pred_logits=logits.index_select(1, indices),
                               pred_boxes=boxes.index_select(1, indices),
                               pred_masks=masks.index_select(1, indices), presence_logits=presence)
    return selected, dict(input_queries=logits.shape[1], kept_query_indices=indices.tolist(),
                          minimum_score=AUXILIARY_THRESHOLD, score_dtype='float32_cpu')


def memory_allowance(other_driver_bytes):
    remaining = 3 * 1024**3 - sum(number(value, 0, 3 * 1024**3) for value in other_driver_bytes)
    require(remaining > 0, 'Idle workers exhausted the shared MPS allowance')
    return int(remaining)


def clear_position_caches(model):
    """Release device tensors retained outside buffers by the pinned SAM3 runtime."""
    from inspect import getclosurevars
    cleared, methods = set(), set()
    for module in model.modules():
        for name in ('build_sine_position_embedding', '_get_coords'):
            method = getattr(module, name, None)
            if method is None:
                continue
            methods.add(name)
            cached = getclosurevars(method).nonlocals.get('func_with_cache')
            require(cached is not None and callable(getattr(cached, 'cache_clear', None)), 'SAM3 cache wrapper changed')
            if id(cached) not in cleared:
                cached.cache_clear()
                cleared.add(id(cached))
    require(methods == {'build_sine_position_embedding', '_get_coords'}, 'SAM3 position cache inventory changed')
    return len(cleared)


def normalise_masks(masks, count, *, width, height):
    import numpy as np
    require(masks.ndim == 3 and len(masks) == count, 'Instance mask count differs')
    if not count:
        return np.zeros((0, height, width), dtype=bool)
    require(masks.shape[1:] == (height, width), 'Masks are not in original image coordinates')
    return masks.astype(bool)


def choose_verified(primary, auxiliary, verifier_scores, *, route_revision=1):
    """Replace only unambiguous matches; retain other primary animals and weak hints."""
    require(type(route_revision) is int and route_revision in (1, 2), 'Unsupported SAM3 route revision')
    require(len(auxiliary) == len(verifier_scores), 'Verifier score count differs')
    for proposal in primary + auxiliary:
        number(proposal['confidence'], 0, 1)
        coordinates = [number(v, 0, 1e8) for v in proposal['xyxy']]
        require(len(coordinates) == 4 and coordinates[0] < coordinates[2] and coordinates[1] < coordinates[3], 'Invalid proposal geometry')
    scores = [number(score, 0, 1) for score in verifier_scores]
    verified = [i for i, box in enumerate(auxiliary) if box['confidence'] >= AUXILIARY_THRESHOLD and scores[i] >= VERIFIER_THRESHOLD]

    def related(a, b):
        intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
        smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
        return intersection_over_union(a, b) >= .3 or intersection / smaller >= .8

    # Weak recovery hints are not accepted animals and cannot veto verified detections.
    matches = {i: [j for j, box in enumerate(primary)
                   if (route_revision == 1 or box['confidence'] >= PRIMARY_THRESHOLD)
                   and related(auxiliary[i]['xyxy'], box['xyxy'])] for i in verified}
    selected, replaced = [], set()
    for index in verified:
        anchors = matches[index]
        if not anchors:
            selected.append(index)
        elif len(anchors) == 1 and sum(anchors[0] in values for values in matches.values()) == 1:
            selected.append(index)
            replaced.add(anchors[0])
    result = [dict(auxiliary[i]) for i in selected] + [dict(box) for i, box in enumerate(primary) if i not in replaced]
    return result, dict(selected_auxiliary_indices=selected, replaced_primary_indices=sorted(replaced),
                        unverified_fallback=False, ambiguous_auxiliary_indices=[i for i in verified if i not in selected])


def load_sam3_bundle(directory):
    directory = Path(directory).resolve()
    card = read_json(directory / 'model-card.json')
    require(card['schema_version'] == 1 and card['backend'] == 'sam3-hybrid' and card['species'] == 'lizard'
            and card['status'] == 'experimental' and card['production_validated'] is False, 'Unsupported SAM3 package')
    require(card['model_id'] == fingerprint({k: v for k, v in card.items() if k != 'model_id'}), 'SAM3 package identity differs')
    require(card['recipe'] == dict(image_size=640) and type(card['route_revision']) is int
            and card['route_revision'] in (1, 2), 'Unsupported SAM3 recipe')
    paths = {name: (directory / path).resolve() for name, path in card['paths'].items()}
    require(set(paths) == {'primary', 'sam3', 'primary_runtime', 'sam3_runtime'} and all(p.is_dir() for p in paths.values()), 'Missing neural component')
    primary = load_hybrid_bundle(paths['primary'])
    require(primary[0]['package_id'] == card['primary_package_id'] and primary[1]['threshold'] == VERIFIER_THRESHOLD, 'Primary component differs')
    for name, checksum in card['sam3_files'].items():
        require(digest(relative(paths['sam3'], name)) == checksum, 'SAM3 component changed: ' + name)
    require({'model.safetensors', 'config.json', 'processor_config.json', 'tokenizer.json', 'tokenizer_config.json'} <= card['sam3_files'].keys(), 'Incomplete SAM3 package')
    for name in ('primary_runtime', 'sam3_runtime'):
        require(digest(paths[name] / 'transformers/__init__.py') == card['runtime_entry_sha256'][name], 'Runtime version changed')
    return card, paths


class NeuralWorker:
    """One request at a time; failure closes the process instead of reusing stale results."""
    def __init__(self, command, *, environment, log, timeout=60):
        self.timeout, self.counter = timeout, 0
        self.messages = Queue()
        self.log = Path(log).open('xb')
        try:
            self.process = subprocess.Popen(command, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=self.log, text=True, bufsize=1)
        except BaseException:
            self.log.close()
            raise
        def read_messages():
            try:
                for line in self.process.stdout:
                    self.messages.put(line)
            finally:
                self.messages.put(None)
        self.reader = Thread(target=read_messages, daemon=True)
        self.reader.start()
        try:
            self.ready = self.receive(0)
        except BaseException:
            self.close()
            raise

    def receive(self, request_id):
        try:
            line = self.messages.get(timeout=self.timeout)
            require(line is not None, 'Neural worker exited before replying')
            require(len(line) < 4 * 1024**2, 'Neural worker response exceeded limit')
            response = json.loads(line)
            require(response.get('id') == request_id, 'Stale neural worker response')
            require(response.get('ok') is True, 'Neural worker failed: ' + str(response.get('error', 'unknown')))
            return response
        except Empty as exc:
            self.close()
            raise TimeoutError('Neural worker response deadline exceeded') from exc
        except BaseException:
            self.close()
            raise

    def request(self, **payload):
        require(self.process.poll() is None, 'Neural worker is no longer running')
        self.counter += 1
        try:
            self.process.stdin.write(json.dumps(dict(payload, id=self.counter), allow_nan=False) + '\n')
            self.process.stdin.flush()
        except BaseException:
            self.close()
            raise
        return self.receive(self.counter)

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        self.reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()
        self.log.close()


class Sam3HybridPredictor:
    def __init__(self, directory, bundle, device, artifact_directory):
        require(device == 'mps', 'Experimental SAM3 streaming currently requires the measured MPS runtime')
        self.card, paths = bundle
        self.directory = Path(artifact_directory).resolve()
        self.directory.mkdir()
        (self.directory / 'frames').mkdir()
        (self.directory / 'masks').mkdir()
        self.workers, self.index, self.device, self.idle = {}, 0, device, {}
        root = Path(__file__).resolve().parents[1]
        try:
            for kind in ('primary', 'sam3'):
                environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(paths[kind + '_runtime']), str(root))),
                    OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', TOKENIZERS_PARALLELISM='false',
                    HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                    PYTORCH_ENABLE_MPS_FALLBACK='0')
                command = [sys.executable, '-m', 'behavior_recorder.vision_neural_worker', kind, str(paths[kind]), str(self.directory)]
                self.workers[kind] = NeuralWorker(command, environment=environment, log=self.directory / (kind + '.log'))
                self.idle[kind] = self.workers[kind].ready['idle_mps']['driver_bytes']
        except BaseException:
            self.close()
            raise

    def predict_frame(self, frame):
        import cv2
        from PIL import Image
        started = perf_counter()
        path = self.directory / 'frames' / f'{self.index:06d}.png'
        Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).save(path)
        checksum = digest(path)
        request = dict(image=str(path), image_sha256=checksum)
        def invoke(kind, **payload):
            budget = memory_allowance([value for name, value in self.idle.items() if name != kind])
            reply = self.workers[kind].request(**request, **payload, mps_limit_bytes=budget)
            self.idle[kind] = reply['idle_mps']['driver_bytes']
            return reply
        primary = invoke('primary', operation='detect')
        auxiliary = invoke('sam3', operation='segment', mask_name=f'{self.index:06d}.npz')
        verified = invoke('primary', operation='verify', proposals=auxiliary['predictions'])
        require(all(reply['image_sha256'] == checksum for reply in (primary, auxiliary, verified)), 'Frame identity changed between models')
        boxes, route = choose_verified(primary['predictions'], auxiliary['predictions'], verified['scores'],
                                       route_revision=self.card['route_revision'])
        evidence = dict(actual_device=self.device, seconds=perf_counter() - started, model='sam3-hybrid',
            package_id=self.card['model_id'], route_revision=self.card['route_revision'],
            frame_sequence=self.index, input_image='segmentation/frames/' + path.name,
            input_image_sha256=checksum, primary=primary, sam3=auxiliary, verifier=verified, route=route,
            mask_artifact='segmentation/masks/' + auxiliary['mask_name'], mask_sha256=auxiliary['mask_sha256'],
            neural_processes={name: worker.process.pid for name, worker in self.workers.items()},
            gpu_execution='sequential; each worker parks weights on CPU before replying',
            detector_windows=2, mps_allocator_limit_bytes=3 * 1024**3)
        self.index += 1
        return [dict(xyxy=p['xyxy'], confidence=p['confidence']) for p in boxes], evidence

    def close(self):
        for worker in self.workers.values():
            worker.close()
