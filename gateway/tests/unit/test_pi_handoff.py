"""The portable updater validates its payload without touching a running store."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from deploy import pi_handoff


class PiHandoffTests(unittest.TestCase):
    def package(self, path, *, extra=None, corrupt=False, duplicate=False, symlink=False):
        content = {'__main__.py': b'# launcher',
                   'source/pyproject.toml': b'[project]\nversion = "0.4.5"\n',
                   'source/requirements.lock': b'# dependency lock',
                   'source/deploy/build_release.py': b'# builder',
                   'source/deploy/install.py': b'# installer'}
        if extra:
            content[extra] = b'# unsafe path'
        manifest = {'version': '0.4.5', 'files': {
            name: hashlib.sha256(data).hexdigest() for name, data in content.items()}}
        if corrupt:
            content['source/deploy/install.py'] += b' changed'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in content.items():
                item = zipfile.ZipInfo(name)
                if symlink and name == 'source/deploy/install.py':
                    item.external_attr = 0o120777 << 16
                archive.writestr(item, data)
            archive.writestr('handoff.json', json.dumps(manifest))
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    archive.writestr('__main__.py', b'# duplicate')

    def test_payload_rejects_tampering_duplicate_names_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'update.pyz'
            cases = [{'corrupt': True}, {'duplicate': True}, {'symlink': True},
                     {'extra': 'source/../../escape.py'}, {'extra': '/absolute.py'},
                     {'extra': 'source\\escape.py'}, {'extra': 'unexpected.py'}]
            for case in cases:
                with self.subTest(case=case):
                    self.package(archive, **case)
                    with self.assertRaises(ValueError):
                        pi_handoff.read_package(archive)

    def test_inspect_checks_hashes_and_never_runs_or_claims_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'update.pyz'
            self.package(archive)
            output = io.StringIO()
            with patch('sys.argv', [str(archive), '--inspect']), \
                    patch.object(pi_handoff, 'check_environment', side_effect=AssertionError('must not probe Pi')), \
                    patch.object(pi_handoff.subprocess, 'run', side_effect=AssertionError('must not execute')), \
                    contextlib.redirect_stdout(output):
                pi_handoff.main()
            result = json.loads(output.getvalue())
            self.assertTrue(result['package_verified'])
            self.assertFalse(result['installed'])
            self.assertNotIn('INSTALL_OK', output.getvalue())
            self.assertEqual(list(Path(directory).iterdir()), [archive])

    def test_existing_config_must_explicitly_disable_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'gateway.toml'
            with patch.object(pi_handoff, 'CONFIG', config), \
                    patch.object(pi_handoff.platform, 'system', return_value='Linux'):
                for content in ('', 'hardware_outputs_enabled = true', 'hardware_outputs_enabled = 0'):
                    with self.subTest(content=content):
                        config.write_text(content, encoding='utf-8')
                        with self.assertRaisesRegex(ValueError, 'hardware_outputs_enabled = false'):
                            pi_handoff.check_environment(Path('unused'))


if __name__ == '__main__':
    unittest.main()
