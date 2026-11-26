"""Render a held-out view and five door states from a locally trained LiveScene config.

Only load trusted local Nerfstudio YAML/checkpoints (their loaders execute Python).
Run after training stops: this intentionally does not share the 8 GB GPU with training.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image
import torch
from nerfstudio.utils.eval_utils import eval_setup


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--api-request", action="store_true", help="Read a bounded render request from stdin")
    parser.add_argument("--request-file", type=Path, help="Trusted server-side request file for supervised rendering")
    args = parser.parse_args()
    if args.api_request:
        request = json.loads(args.request_file.read_text()) if args.request_file else json.load(sys.stdin)
        render_request(args.config, args.output, request)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    config, pipeline, checkpoint, step = eval_setup(args.config, eval_num_rays_per_chunk=2048)
    assert config.method_name == "livescene"
    assert pipeline.controller.num_attributes == 1, "This check targets the one-door sample"
    pipeline.eval()
    # Keep the same held-out camera across checkpoints, with LiveScene's frame-ID metadata.
    pipeline.datamanager.eval_dataloader = pipeline.datamanager.fixed_indices_eval_dataloader
    camera, batch = pipeline.datamanager.next_eval_image(0)
    source_image = pipeline.datamanager.eval_dataset.image_filenames[int(batch["image_idx"])]
    camera = copy.deepcopy(camera)
    camera.rescale_output_resolution(0.5)
    size = (int(camera.width.item()), int(camera.height.item()))
    truth = Image.fromarray((batch["image"].cpu().numpy() * 255).round().clip(0, 255).astype(np.uint8))
    truth = truth.resize(size, Image.Resampling.BILINEAR)
    truth.save(args.output / "heldout-ground-truth.png")
    batch["image"] = torch.from_numpy(np.array(truth).copy()).float() / 255

    def render(name):
        with torch.no_grad():
            outputs = pipeline.model.get_outputs_for_camera(camera)
        rgb = outputs["rgb"]
        assert tuple(rgb.shape) == (size[1], size[0], 3) and torch.isfinite(rgb).all()
        image = Image.fromarray((rgb.cpu().numpy() * 255).round().clip(0, 255).astype(np.uint8))
        image.save(args.output / name)
        return outputs, image

    outputs, _ = render("heldout-prediction.png")
    with torch.no_grad():
        metrics, _ = pipeline.model.get_image_metrics_and_images(outputs, batch)
    assert all(np.isfinite(value) for value in metrics.values())

    # The real viewer uses cam_idx to select slider-controlled state, not a frame ID.
    camera.metadata = {"cam_idx": 0}
    states = [0.0, 0.25, 0.5, 0.75, 1.0]
    images = []
    for state in states:
        pipeline.controller.slider_0.value = state
        _, image = render(f"door-{state:.2f}.png")
        images.append(image)
    delta = np.abs(np.asarray(images[-1], dtype=float) - np.asarray(images[0], dtype=float)).mean() / 255
    images[0].save(args.output / "door-states.gif", save_all=True,
                   append_images=images[1:] + images[-2:0:-1], duration=700, loop=0)
    result = {
        "config": str(args.config.resolve()), "config_sha256": digest(args.config),
        "checkpoint": str(checkpoint), "checkpoint_sha256": digest(checkpoint), "step": step,
        "heldout_frame_index": int(batch["image_idx"]), "render_size": list(size),
        "heldout_source_image": str(source_image),
        "evaluation_scope": "one held-out view, half-resolution; not a dataset benchmark",
        "heldout_metrics": metrics, "slider_states": states,
        "slider_endpoint_mean_absolute_rgb_change": float(delta),
        "note": "State-dependent image change is not proof of visual quality or physical actuation",
        "elapsed_seconds": time.monotonic() - started,
        "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))


def render_request(config_path, output, request):
    """Server chooses the trusted config and pinned checkpoint; clients never send filesystem paths."""
    started = time.monotonic()
    assert torch.cuda.is_available()
    def select_saved_run(config):
        config.load_step = request['checkpoint_step']
        return config
    config, pipeline, checkpoint, step = eval_setup(config_path, eval_num_rays_per_chunk=1024,
                                                   update_config_callback=select_saved_run)
    assert config.method_name == 'livescene'
    checkpoint_sha256 = digest(checkpoint)
    assert checkpoint_sha256 == request['checkpoint_sha256']
    assert pipeline.controller.num_attributes == 1
    assert pipeline.device.type == 'cuda'
    pipeline.eval()
    dataset = pipeline.datamanager.eval_dataset
    index = request['camera_index']
    assert 0 <= index < len(dataset)
    camera = copy.deepcopy(dataset.cameras[index:index+1]).to(pipeline.device)
    camera.rescale_output_resolution(min(1., request['max_width']/int(camera.width.item())))
    if request['state'] is None:
        camera.metadata = {'id': dataset.metadata['ids'][index:index+1].to(pipeline.device)}
    else:
        assert 0 <= request['state'] <= 1
        camera.metadata = {'cam_idx': 0}
        pipeline.controller.slider_0.value = request['state']
    with torch.no_grad():
        outputs = pipeline.model.get_outputs_for_camera(camera)
        rgb = outputs['rgb'].cpu().numpy()
    assert np.isfinite(rgb).all()
    Image.fromarray((rgb*255).round().clip(0,255).astype(np.uint8)).save(output / 'render.png')
    if request.get('include_interaction', False):
        # Learned classes from this exact render; 0 is background, 1 is the trained object.
        probability = outputs['atrb_0_raw']
        assert torch.isfinite(probability).all() and torch.all((0 <= probability) & (probability <= 1))
        labels = torch.cat((1-probability, probability), dim=-1).argmax(dim=-1)
        Image.fromarray(labels.cpu().numpy().astype(np.uint8)).save(output / 'objects.png')
    result = {'request_id': request['request_id'], 'checkpoint_sha256': checkpoint_sha256,
              'step': step, 'camera_index': index, 'state': request['state'],
              'width': int(camera.width.item()), 'height': int(camera.height.item()),
              'device': 'cuda', 'gpu_name': torch.cuda.get_device_name(),
              'elapsed_seconds': time.monotonic()-started}
    (output / 'render.json').write_text(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
