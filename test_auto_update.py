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

    def test_check_only_announces_without_downloading(self):
        worker = UpdateWorker(check_only=True)
        available, ready = [], []
        worker.available.connect(available.append)
        worker.ready.connect(lambda *args: ready.append(args))
        with patch("auto_update.request", return_value=io.BytesIO(json.dumps(self.release()).encode())) as request:
            worker.run()
        self.assertEqual(len(available), 1)
        self.assertEqual(ready, [])
        self.assertEqual(request.call_count, 1)

    def test_confirmation_controls_download(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from PyQt6.QtWidgets import QMessageBox
        from app import TabbedFTPClientApp
        window = SimpleNamespace(close_after_update_check=False, update_worker=None,
                                 on_update_ready=Mock(), finish_update_check=Mock(), statusBar=Mock())
        with patch("app.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel), patch("app.UpdateWorker") as worker:
            TabbedFTPClientApp.confirm_update(window, self.release())
            worker.assert_not_called()
        with patch("app.QMessageBox.question", return_value=QMessageBox.StandardButton.Ok), patch("app.UpdateWorker") as worker:
            TabbedFTPClientApp.confirm_update(window, self.release())
            worker.assert_called_once_with(window, release=self.release())
            worker.return_value.start.assert_called_once()

    def test_restart_waits_for_active_transfers(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from app import TabbedFTPClientApp
        session = Mock()
        window = SimpleNamespace(pending_update=("file", "digest"), connection_tabs=Mock(),
                                 statusBar=Mock(), close=Mock(), restart_for_update=Mock())
        window.connection_tabs.count.return_value = 1
        window.connection_tabs.widget.return_value = session
        session.has_running_operations.return_value = True
        with patch("app.QTimer.singleShot") as timer:
            TabbedFTPClientApp.restart_for_update(window)
            timer.assert_called_once()
            window.close.assert_not_called()
        session.has_running_operations.return_value = False
        TabbedFTPClientApp.restart_for_update(window)
        window.close.assert_called_once()

    def test_restart_is_launched_after_replacement(self):
        with patch("auto_update.subprocess.Popen") as launch:
            install_on_exit("C:/temp/update.exe", "a" * 64, executable="C:/App/client.exe", pid=123, restart=True)
        script = base64.b64decode(launch.call_args.args[0][-1]).decode("utf-16le")
        self.assertLess(script.index("File]::Replace"), script.index("Start-Process"))

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
        self.assertEqual(launch.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")


if __name__ == "__main__":
    unittest.main()
