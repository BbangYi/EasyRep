"""Open a trusted static Nerfacto checkpoint with the native Nerfstudio 1.1.5 viewer.

Only load trusted local YAML/checkpoints: Nerfstudio's loaders execute Python.
Model/config files are read only; viewer overrides exist only in this process.
"""

import argparse
from pathlib import Path

from nerfstudio.configs.base_config import ViewerConfig
from nerfstudio.data.datamanagers.base_datamanager import VanillaDataManager, VanillaDataManagerConfig
from nerfstudio.scripts.viewer import run_viewer
from nerfstudio.utils.eval_utils import eval_setup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--step", type=int, default=5000)
    parser.add_argument("--camera-index", type=int, default=249)
    parser.add_argument("--port", type=int, default=7007)
    args = parser.parse_args()
    if args.step < 0 or args.camera_index < 0 or not 1 <= args.port <= 65535:
        parser.error("step/camera-index must be nonnegative and port must be 1..65535")

    def configure(config):
        if config.method_name != "nerfacto":
            raise ValueError("This viewer launcher supports static Nerfacto only")
        config.load_step = args.step
        manager = config.pipeline.datamanager
        # eval_setup replaces old saved targets with newer method defaults.
        if type(manager) is VanillaDataManagerConfig:
            manager._target = VanillaDataManager
        return config

    config, pipeline, checkpoint, step = eval_setup(
        args.config, eval_num_rays_per_chunk=None, test_mode="test", update_config_callback=configure
    )
    if step != args.step or pipeline.datamanager.includes_time:
        raise ValueError("Expected the requested checkpoint from a static Nerfacto dataset")
    config.vis = "viewer"
    config.viewer = ViewerConfig(
        websocket_host="127.0.0.1", websocket_port=args.port, make_share_url=False,
        jpeg_quality=95, max_num_display_images=24,
        num_rays_per_chunk=config.viewer.num_rays_per_chunk,
    )

    class ReconstructionViewer(run_viewer.ViewerState):
        def _pick_drawn_image_idxs(self, total_num):
            if args.camera_index >= total_num:
                raise ValueError(f"camera-index must be less than {total_num}")
            indices = super()._pick_drawn_image_idxs(total_num)
            if args.camera_index not in indices:
                indices[-1] = args.camera_index
            return indices

        def _set_initial_camera(self, client):
            camera = getattr(self, "camera_handles", {}).get(args.camera_index)
            if camera is not None:
                with client.atomic():
                    client.camera.position = camera.position
                    client.camera.wxyz = camera.wxyz
                    self.current_camera_idx = args.camera_index

        def handle_new_client(self, client):
            super().handle_new_client(client)
            self._set_initial_camera(client)

        def init_scene(self, *args, **kwargs):
            super().init_scene(*args, **kwargs)
            self.set_camera_visibility(False)
            self.hide_images.visible = False
            self.show_images.visible = True
            for client in self.viser_server.get_clients().values():
                self._set_initial_camera(client)

        def update_scene(self, step, num_rays_per_batch=None):
            super().update_scene(step, num_rays_per_batch)
            self.update_step(step)  # Native eval mode returns early before clients connect.

    print(f"Viewing {checkpoint} (step {step}, initial camera {args.camera_index})", flush=True)
    run_viewer.ViewerState = ReconstructionViewer  # Process-local adapter; no package edits.
    run_viewer._start_viewer(config, pipeline, step)


if __name__ == "__main__":
    main()
