import base64
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox
from app import SFTPClientApp, SFTPWorker
from oz_client import OZClient, OZ_PROTOCOL, find_oz_runtime, normalize_server_url


def response(value, status="OK"):
    payload = json.dumps(value, ensure_ascii=False) if status == "OK" else value
    return b"OZFTP\t" + status.encode() + b"\t" + base64.b64encode(payload.encode()) + b"\n"


class OZClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def fake_client(self, replies):
        process = Mock()
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO(b"unrelated SDK output\n" + b"".join(replies))
        process.poll.return_value = None
        process.wait.return_value = 0
        with patch("oz_client.find_oz_runtime", return_value=("java", "lib")), \
                patch("oz_client.subprocess.Popen", return_value=process) as launch:
            client = OZClient("http://example.test:8080/oz80/server", "user", "password")
        self.addCleanup(client._terminate)
        return client, process, launch

    def test_url_validation(self):
        self.assertEqual(normalize_server_url(" http://example.test:8080/oz80/server/ "),
                         "http://example.test:8080/oz80/server")
        for url in ("example.test", "ftp://example.test", "http://u:p@example.test/server",
                    "http://example.test/server?password=p", "http://example.test:abc/server"):
            with self.assertRaises(ValueError):
                normalize_server_url(url)

    def test_listing_unicode_and_credentials_sent_only_over_stdin(self):
        listing = [dict(name="한글.ozr", dir=False, size=123, mtime=1700000000000, owner="manager"),
                   dict(name="/보고서/", dir=True, size=0, mtime=0, owner="manager")]
        client, process, launch = self.fake_client([response([]), response(listing)])
        entries = client.listdir_attr("/")
        self.assertEqual([e.filename for e in entries], ["한글.ozr", "보고서"])
        self.assertEqual(entries[0].st_mtime, 1700000000)
        self.assertEqual(entries[0].st_size, 123)
        command_line = launch.call_args.args[0]
        self.assertNotIn("password", command_line)
        self.assertNotIn("user", command_line)
        fields = process.stdin.getvalue().splitlines()[0].split(b"\t")
        self.assertEqual([base64.b64decode(v).decode() for v in fields],
                         ["connect", "http://example.test:8080/oz80/server", "user", "password", "false"])

    def test_transfer_progress_and_remote_errors(self):
        client, process, _ = self.fake_client([response([]), b"OZFTP\tPROGRESS\t3\t10\n",
            b"OZFTP\tPROGRESS\t10\t10\n", response(None), response("OZ 403: permission denied", "ERROR")])
        progress = []
        client.get("/report.ozr", "report.ozr", callback=lambda a, b: progress.append((a, b)))
        self.assertEqual(progress, [(3, 10), (10, 10)])
        with self.assertRaisesRegex(OSError, "permission denied"):
            client.put("report.ozr", "/report.ozr")

    def test_cancel_stops_helper_and_connection(self):
        client, process, _ = self.fake_client([response([]), b"OZFTP\tPROGRESS\t3\t10\n"])
        def cancel(a, b):
            raise ValueError("cancelled")
        with self.assertRaisesRegex(ValueError, "cancelled"):
            client.get("/report.ozr", "report.ozr", callback=cancel)
        self.assertTrue(client.closed)
        process.kill.assert_called_once()

    def test_ui_accepts_complete_url_and_routes_to_oz_worker(self):
        session = SFTPClientApp()
        try:
            session.host_input.setText("http://example.test:8080/oz80/server")
            session.user_input.setText("test-user")
            session.pass_input.setText("test-password")
            session.port_input.setText("invalid-but-unused")
            with patch.object(session, "start_worker") as start:
                session.connect_sftp()
            worker = start.call_args.args[0]
            self.assertEqual(session.protocol_combo.currentText(), OZ_PROTOCOL)
            self.assertFalse(session.port_input.isEnabled())
            self.assertFalse(session.key_input.isEnabled())
            self.assertEqual(worker.args["protocol"], OZ_PROTOCOL)
            self.assertEqual(worker.credentials[1], 0)
            client = Mock(spec=OZClient)
            client.initial_directory = "/"
            worker.finished_signal.disconnect()
            with patch("app.OZClient", return_value=client) as connect:
                results = []
                worker.finished_signal.connect(lambda action, value: results.append(value))
                worker.run()
                connect.assert_called_once_with("http://example.test:8080/oz80/server", "test-user", "test-password", False)
                self.assertEqual(results, [(None, client)])
            with patch.object(session, "fetch_remote_dir"):
                session.on_worker_done("connect", (None, client))
            self.assertFalse(session.remote_cmd_btn.isEnabled())
            self.assertFalse(session.stats_timer.isActive())
        finally:
            session.disconnect_sftp()
            session.close()

    def test_installed_sdk_and_java_bridge_start_without_linkage_errors(self):
        try:
            find_oz_runtime()
        except RuntimeError:
            self.skipTest("OZ Report 8.0 is not installed")
        # Local closed port exercises the real SDK startup without logging into
        # the user's production server or guessing credentials.
        with self.assertRaises(OSError) as result:
            OZClient("http://127.0.0.1:1/oz/server", "fixture", "fixture")
        self.assertIn("OZCPException", str(result.exception))


if __name__ == "__main__":
    unittest.main()
