import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase

SCRIPT = Path(__file__).resolve().parents[1] / "ops/backup_database.py"

class BackupTests(SimpleTestCase):
    def run_backup(self, database, directory, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--database", str(database), "--directory", str(directory), *args], capture_output=True, text=True)

    def test_online_backup_restores_wal_and_preserves_unrelated_files(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); database = root / "source.sqlite3"; directory = root / "backups"
            directory.mkdir()
            old = directory / "habitatos-20000101T000000000000Z.sqlite3"; old.write_text("expired backup")
            os.utime(old, (1, 1))
            unrelated = directory / "manual.sqlite3"; unrelated.write_text("keep")
            with sqlite3.connect(database) as live:
                live.execute("PRAGMA journal_mode=WAL")
                live.execute("CREATE TABLE measurement (value real)")
                live.execute("INSERT INTO measurement VALUES (23.75)"); live.commit()
                result = self.run_backup(database, directory)
                self.assertEqual(result.returncode, 0, result.stderr)
                backups = list(directory.glob("habitatos-*.sqlite3"))
                self.assertEqual(len(backups), 1)
                self.assertFalse(old.exists())
                self.assertTrue(unrelated.exists())
                self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
                with sqlite3.connect(backups[0]) as restored:
                    self.assertEqual(restored.execute("select value from measurement").fetchone(), (23.75,))
                self.assertFalse(list(directory.glob("*.partial")))

    def test_failed_backup_does_not_prune_previous_backup(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); database = root / "broken.sqlite3"; database.write_text("not sqlite")
            directory = root / "backups"; directory.mkdir()
            old = directory / "habitatos-20000101T000000000000Z.sqlite3"; old.write_text("keep on failure")
            os.utime(old, (1, 1))
            result = self.run_backup(database, directory)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(old.exists())
            self.assertFalse(list(directory.glob("*.partial")))

    def test_missing_database_and_invalid_retention_fail_closed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); database = root / "missing.sqlite3"
            for args in ((), ("--keep-days", "0")):
                result = self.run_backup(database, root / "backups", *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(database.exists())
