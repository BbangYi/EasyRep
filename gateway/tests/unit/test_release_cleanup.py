"""Release export leaves one archive, not a second unpacked dependency tree."""
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import zipfile

from deploy import build_release


class ReleaseCleanupTests(unittest.TestCase):
    def test_camera_firmware_export_excludes_private_config_and_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, exported = root / "source", root / "export"
            source.mkdir()
            (source / "main.py").write_text("# shared camera program")
            (source / "config.example.json").write_text('{"wifi_password":"YOUR_WIFI_PASSWORD"}')
            (source / "config.json").write_text('{"wifi_password":"PRIVATE"}')
            (source / "firmware.bin").write_bytes(b"private-or-large-binary")
            build_release.copy_public_camera_firmware(source, exported)
            self.assertEqual({p.name for p in exported.iterdir()}, {"main.py", "config.example.json"})
            self.assertFalse(any(b"PRIVATE" in p.read_bytes() for p in exported.iterdir()))

    def test_wheel_and_handoff_include_environment_runtime_without_model_data_or_secrets(self):
        project = Path(__file__).resolve().parents[2]
        temporary_root = project / "var/tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        required = {"experiments/environment_sim/" + name for name in
                    ("gpu_predict.py", "predictive_misting.py", "simulation_config.json")}
        required.add("habitat/control/r15_timing.py")
        with tempfile.TemporaryDirectory(prefix="release-runtime-", dir=temporary_root) as directory:
            work = Path(directory)
            source = work / "source"
            source.mkdir()
            for name in ("habitat", "habitat_gateway", "apps", "deploy",
                         "configs", "config", "firmware", "docs/operations"):
                shutil.copytree(project / name, source / name,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for name in ("pyproject.toml", "requirements.lock", "README.md", "docs/saas-integration.md",
                         "docs/protocols/r15-bridge.md", "docs/protocols/ir-control.md",
                         *sorted(name for name in required if name.startswith("experiments/"))):
                destination = source / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(project / name, destination)
            # Deliberately place private/runtime files beside the worker. Package
            # selection must exclude them, rather than rely on their absence.
            private = {"experiments/environment_sim/" + name for name in
                       ("model_3sensors.npz", "training_report.json", "training_data.npy", "gpu.env")}
            for name in private:
                (source / name).write_bytes(b"private-runtime-fixture-must-not-be-shipped")
            wheels = work / "wheels"
            wheels.mkdir()
            command = [sys.executable, "-B", "-c",
                       "from setuptools.build_meta import build_wheel; build_wheel('" + wheels.as_posix() + "')"]
            built = subprocess.run(command, cwd=source, capture_output=True, text=True, timeout=60,
                                   env={**os.environ, "PIP_NO_INDEX": "1"})
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            wheel, = wheels.glob("*.whl")
            installed = work / "installed"
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
                self.assertTrue(required <= names, required - names)
                self.assertFalse(private & names, private & names)
                self.assertEqual({name for name in names if name.startswith("experiments/")},
                                 required - {"habitat/control/r15_timing.py"})
                for name in required:
                    self.assertEqual(archive.read(name), (project / name).read_bytes())
                archive.extractall(installed)
            # Exercise the real path calculation from an extracted installation,
            # outside the checkout. No model weights, CUDA or worker execution.
            probe = subprocess.run([sys.executable, "-B", "-c",
                "import json; from pathlib import Path; from habitat.gpu import environment_api; "
                "from experiments.environment_sim import predictive_misting as experiment; "
                "root=Path(environment_api.__file__).resolve().parents[2]/'experiments/environment_sim'; "
                "assert root==experiment.SOURCE; assert (root/'gpu_predict.py').is_file(); "
                "assert experiment.settings()['max_pulse_seconds']==3; "
                "print(json.dumps({'installed_worker_path_valid':True,'RUN_max_s':3}))"],
                cwd=work, env={**os.environ, "PYTHONPATH": str(installed)}, capture_output=True,
                text=True, timeout=30)
            self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
            self.assertTrue(json.loads(probe.stdout)["installed_worker_path_valid"])
            for name in required - {"experiments/environment_sim/simulation_config.json"}:
                ast.parse((installed / name).read_text(encoding="utf-8"), feature_version=(3, 10))
            handoff = work / "handoff"
            handoff.mkdir()
            version = tomllib.loads((source / "pyproject.toml").read_text())["project"]["version"]
            with contextlib.redirect_stdout(io.StringIO()):
                build_release.build_source_handoff(source, handoff, version)
            package, = handoff.glob("*.pyz")
            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
                self.assertTrue({"source/" + name for name in required} <= names)
                self.assertFalse({"source/" + name for name in private} & names)
                self.assertEqual({name for name in names if name.startswith("source/experiments/")},
                                 {"source/" + name for name in required if name.startswith("experiments/")})
                manifest = json.loads(archive.read("handoff.json"))
                for name, digest in manifest["files"].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
        self.assertFalse(work.exists())

    def test_only_archive_and_checksum_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def fake_pip(command, **kwargs):
                if 'wheel' in command:
                    wheels = Path(command[command.index('--wheel-dir') + 1])
                    (wheels / 'habitat_gateway-0.4.3-py3-none-any.whl').write_bytes(b'test wheel')

            with patch.object(sys, 'argv', ['build_release', '--output', str(output)]), \
                    patch.object(build_release.subprocess, 'run', side_effect=fake_pip), \
                    patch.object(build_release.platform, 'machine', return_value='aarch64'), \
                    patch('builtins.print'):
                build_release.main()
            archives = list(output.glob('*.tar.gz'))
            self.assertEqual(len(archives), 1)
            archive = archives[0]
            self.assertEqual({p.name for p in output.iterdir()}, {archive.name, archive.name + '.sha256'})
            self.assertEqual((output / (archive.name + '.sha256')).read_text().split()[0],
                             hashlib.sha256(archive.read_bytes()).hexdigest())
            with tarfile.open(archive) as bundle:
                manifest = next(m for m in bundle.getmembers() if m.name.endswith('/release.json'))
                release = json.load(bundle.extractfile(manifest))
                for name, digest in release['files'].items():
                    data = bundle.extractfile(release['release_id'] + '/' + name).read()
                    self.assertEqual(hashlib.sha256(data).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
