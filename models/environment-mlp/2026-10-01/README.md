# Environment MLP: 2026-10-01

This model set was trained on synthetic simulation data only. It has not been validated here against live enclosures and is not evidence of operational control accuracy.

The training report describes a 210-128-128-240 tanh MLP with 30 minutes of history and 60 minutes of candidate actions. It includes separate weights for one, two, and three sensors. Training source/configuration hashes, episode splits and validation metrics are recorded in `training_report.json`.

Verify the three model files and the report after checkout:

```sh
sha256sum --check SHA256SUMS
```

The artifact hashes were checked against the GPU-host files. This folder records model artifacts; compatibility with the gateway's final training and inference code must be checked separately when that code is integrated.

## Integration status

The Pi gateway branch `jaysj0226/gateway-firmware-models`, checked at commit `58d7a7bcff44226ad0c437948f8e4232f63ce885`, has different hashes from those recorded for the training source and configuration:

| File | Training report SHA-256 | Gateway branch SHA-256 |
| --- | --- | --- |
| `gateway/experiments/environment_sim/predictive_misting.py` | `547efea658c3ae3870cee9b5eca4d4defe1921777a545feab64e37956f9c629c` | `9c97f1a7f36c361d8ec38aec04518be81f6ab289e195eb768a0949bac1773074` |
| `gateway/experiments/environment_sim/simulation_config.json` | `2d2f282603cc921c4e1e40ef060696a8861ada1b7cdb783d4639be1dc826c178` | `1d8666c0589904f960350fa37a03d400c7386b4738bae43169b65f68e62041be` |

These differences identify a version change; they do not by themselves establish incompatibility. Loading and inference with the gateway branch have not been tested as part of this artifact upload.

When integrating the gateway branch, reconcile its root environment MLP manifest and README, which currently mark original artifact verification as pending. For deployment, use the gateway's configured external model directory rather than writing evaluation output into this repository.
