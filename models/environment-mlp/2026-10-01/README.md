# Environment MLP: 2026-10-01

This model set was trained on synthetic simulation data only. It has not been validated here against live enclosures and is not evidence of operational control accuracy.

The training report describes a 210-128-128-240 tanh MLP with 30 minutes of history and 60 minutes of candidate actions. It includes separate weights for one, two, and three sensors. Training source/configuration hashes, episode splits and validation metrics are recorded in `training_report.json`.

Verify the three model files and the report after checkout:

```sh
sha256sum --check SHA256SUMS
```

The artifact hashes were checked against the GPU-host files. This folder records model artifacts; compatibility with the gateway's final training and inference code must be checked separately when that code is integrated.
