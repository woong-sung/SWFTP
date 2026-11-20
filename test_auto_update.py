import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from auto_update import UpdateWorker, select_asset, repository, install_on_exit


class UpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def release(self, content=b"MZexample"):
        return {"tag_name": "v99.0.0", "assets": [{"name": "SFTP_Client.exe",
                "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                "size": len(content), "browser_download_url":
                "https://github.com/woong-sung/SWFTP/releases/download/v99.0.0/SFTP_Client.exe"}]}

    def test_repository(self):
        self.assertEqual(repository(), "woong-sung/SWFTP")

    def test_old_and_prerelease_are_ignored(self):
        release = self.release()
        release["tag_name"] = "v0.0.1"
        self.assertIsNone(select_asset(release))
        release["tag_name"] = "v99.0.0"
        release["prerelease"] = True
        self.assertIsNone(select_asset(release))

    def test_missing_digest_is_rejected(self):
        release = self.release()
        release["assets"][0]["digest"] = None
        with self.assertRaises(ValueError):
            select_asset(release)

    def test_download_is_verified(self):
        worker = UpdateWorker()
        ready = []
        worker.ready.connect(lambda *args: ready.append(args))
        with patch("auto_update.request", side_effect=[io.BytesIO(json.dumps(self.release()).encode()), io.BytesIO(b"MZexample")]):
            worker.run()
        self.assertEqual(len(ready), 1)
        try:
            self.assertEqual(Path(ready[0][0]).read_bytes(), b"MZexample")
        finally:
            Path(ready[0][0]).unlink()

    def test_corrupted_download_is_rejected_and_removed(self):
        worker = UpdateWorker()
        ready, messages = [], []
        worker.ready.connect(lambda *args: ready.append(args))
        worker.message.connect(messages.append)
        with tempfile.TemporaryDirectory() as directory:
            with patch("tempfile.tempdir", directory), patch("auto_update.request", side_effect=[io.BytesIO(json.dumps(self.release()).encode()), io.BytesIO(b"MZcorrupt")]):
                worker.run()
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(ready, [])
        self.assertTrue(any("mismatch" in message for message in messages))

    def test_installer_replaces_only_a_temporary_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "client.exe")
            staged = Path(directory, "download.exe")
            target.write_bytes(b"old executable")
            staged.write_bytes(b"new executable")
            install_on_exit(str(staged), hashlib.sha256(staged.read_bytes()).hexdigest(),
                            executable=str(target), pid=2147483646)
            deadline = time.monotonic() + 12
            while staged.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertEqual(target.read_bytes(), b"new executable")
            self.assertEqual(Path(str(target) + ".previous").read_bytes(), b"old executable")
            self.assertFalse(staged.exists())

    def test_installer_waits_and_replaces_with_backup(self):
        with patch("auto_update.subprocess.Popen") as launch:
            install_on_exit("C:/temp/update.exe", "a" * 64, executable="C:/App/client.exe", pid=123)
        command = launch.call_args.args[0]
        script = base64.b64decode(command[-1]).decode("utf-16le")
        self.assertIn("Wait-Process", script)
        self.assertIn("File]::Replace", script)
        self.assertIn(".previous", script)
        self.assertLess(script.index("Get-FileHash"), script.index("File]::Replace"))
        self.assertIn("Hidden", command)


if __name__ == "__main__":
    unittest.main()
