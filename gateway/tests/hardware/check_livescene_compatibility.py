"""CPU regression check; run with the patched LiveScene environment's Python."""

import sys
from types import SimpleNamespace
from unittest.mock import patch

import torch


def main():
    from livescene import livescene_field as field_module
    # Exercise the shared training/render selector: object, background and tie.
    samples = SimpleNamespace(
        frustums=SimpleNamespace(get_positions=lambda: torch.zeros(1, 3, 3)),
        metadata={"atrb_val": torch.tensor([[[.7], [.7], [.7]]])},
    )
    field = SimpleNamespace(grids=None, clip_val=False, cat_embed=False,
        semantic_net=lambda _: torch.tensor([[[4., 0.], [0., 4.], [0., 0.]]]),
        max_prob=0., training=False, train_with_lang=False,
        background_aware_selection=True)
    with patch.object(field_module, "interpolate_ms_features", return_value=torch.zeros(3, 1)):
        _, _, selected, _ = field_module.LiveSceneLanguageField.lang_fn(field, samples, viewer=True)
        assert torch.allclose(selected.flatten(), torch.tensor([.7, 0., 0.]))
        field.background_aware_selection = False
        _, _, legacy, _ = field_module.LiveSceneLanguageField.lang_fn(field, samples, viewer=True)
        assert torch.allclose(legacy.flatten(), torch.full((3,), .7))
    # Missing optional encoders must not break imports or slider-only construction.
    with patch.dict(sys.modules, {"clip": None, "open_clip": None}):
        from livescene import livescene_controller as controller_module
        from livescene import livescene_model as model_module
        from livescene.datamanager.livescene_datamanager import (
            LiveSceneDataManager,
            LiveSceneDataManagerConfig,
            VanillaDataManager,
        )

        with patch.object(controller_module, "LiveSceneClipEncoder", side_effect=AssertionError("CLIP loaded")):
            controller = controller_module.LiveSceneControllerConfig().setup(train_with_lang=False)
        controller.register_slider(1)
        assert controller.clip_encoder is None
        assert controller.get_slider_vals() == [0.0]
        assert not hasattr(controller, "prompt")

        # No datasets exist here: accessing them to stack images would fail.
        with patch.object(VanillaDataManager, "__init__", lambda self, **kwargs: torch.nn.Module.__init__(self)):
            manager = LiveSceneDataManager(
                LiveSceneDataManagerConfig(), image_encoder=None, use_gt_val=False, train_with_lang=False
            )
        assert manager.img_encoder is None

    for valid, labels in (
        (torch.zeros(2, 1, dtype=torch.bool), torch.tensor([[1.0, 0.0], [0.0, 1.0]])),
        (torch.ones(2, 1, dtype=torch.bool), torch.tensor([[1.0, 0.0], [1.0, 0.0]])),
        (torch.ones(1, 1, dtype=torch.bool), torch.tensor([[1.0, 0.0]])),
    ):
        probabilities = torch.zeros_like(labels, requires_grad=True)
        loss = model_module.repulsion_loss([probabilities], [labels], [valid])
        assert loss.item() == 0.0
        loss.backward()
        assert torch.isfinite(probabilities.grad).all()

    for loss_fn in (model_module.cross_entropy_loss, model_module.huber_loss):
        predictions = torch.ones(2, 2, requires_grad=True)
        loss = loss_fn([predictions], [torch.zeros_like(predictions)], [torch.zeros(2, 1, dtype=torch.bool)])
        assert loss.item() == 0.0
        loss.backward()
        assert torch.isfinite(predictions.grad).all()

    # Nonempty repulsion retains the upstream formula (two opposite classes).
    probabilities = torch.tensor([[0.2, 0.4], [0.8, 0.1]], requires_grad=True)
    labels = torch.eye(2)
    loss = model_module.repulsion_loss([probabilities], [labels], [torch.ones(2, 1, dtype=torch.bool)])
    expected = torch.nn.functional.elu(10.0 - (probabilities[0] - probabilities[1]).abs().mean()) + 1
    assert torch.allclose(loss, expected)
    loss.backward()
    assert torch.isfinite(probabilities.grad).all()

    grid = SimpleNamespace(plane_coefs=[torch.zeros(1, 2, 2) for _ in range(3)])
    model = SimpleNamespace(
        device="cpu", training=True, kwargs={"use_gt_val": False},
        config=model_module.LiveSceneModelConfig(num_proposal_iterations=0),
        renderer_rgb=SimpleNamespace(blend_background=lambda image: image),
        psnr=torch.nn.MSELoss(), embed_loss=torch.nn.MSELoss(),
        proposal_networks=[SimpleNamespace(grids=grid)],
        proposal_language_networks=[SimpleNamespace(grids=grid, val_embeds=grid)],
        field=SimpleNamespace(grids=[grid]),
    )
    for has_labels in (False, True):
        values = torch.tensor([[[0.2]], [[0.6]]], requires_grad=True)
        batch = {
            "image": torch.zeros(2, 3), "atrb_mask": labels,
            "mask_valid": torch.ones(2, 2, dtype=torch.bool),
            "atrb_val": torch.tensor([[0.0, 0.0], [1.0, 0.0]]),
            "atrb_val_mask": torch.full((2, 2), has_labels, dtype=torch.bool),
        }
        outputs = {
            "rgb": batch["image"], "weights_list": [], "ray_samples_list": [],
            "prop_mask_0": torch.ones(2, 2), "query_value_list": [values],
        }
        # Sampling regularizers are unrelated to the sparse-label regression.
        with patch.object(model_module, "interlevel_loss", return_value=torch.tensor(0.0)), \
                patch.object(model_module, "distortion_loss", return_value=torch.tensor(0.0)):
            loss = model_module.LiveSceneModel.get_metrics_dict(model, outputs, batch)["embed_val_mse"]
        expected = torch.nn.functional.mse_loss(values[:, 0, 0], batch["atrb_val"][:, 0]) if has_labels else torch.tensor(0.0)
        assert torch.allclose(loss, expected)
        loss.backward()
        assert torch.isfinite(values.grad).all()

    print("LiveScene compatibility checks passed (CPU; no CLIP imports or downloads).")


if __name__ == "__main__":
    main()
