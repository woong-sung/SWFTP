import os
import socketserver
import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox
from app import TabbedFTPClientApp
from test_ftp_client import FTPHandler


class ConnectionTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 10
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_two_live_servers_keep_connections_and_transfers_isolated(self):
        servers = []
        window = TabbedFTPClientApp()
        try:
            first = window.connection_tabs.widget(0)
            second = window.add_connection_tab()
            for i, session in enumerate((first, second)):
                server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FTPHandler)
                server.files = {f"server-{i}.txt": b"original"}
                servers.append(server)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                session.protocol_combo.setCurrentText("FTP")
                session.host_input.setText("127.0.0.1")
                session.port_input.setText(str(server.server_address[1]))
                session.user_input.setText("user")
                session.pass_input.setText("password")
                session.connect_sftp()
                self.assertEqual(next(iter(session.loading_dialogs.values())).windowModality(),
                                 Qt.WindowModality.NonModal)
            self.wait_for(lambda: all(s.sftp_client and not s.has_running_operations()
                                      for s in (first, second)))
            self.assertIsNot(first.sftp_client, second.sftp_client)
            self.assertIsNot(first.transfer_queue, second.transfer_queue)
            self.assertIn("server-0.txt", first.remote_table.item(0, 0).text())
            self.assertIn("server-1.txt", second.remote_table.item(0, 0).text())
            with tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "upload.txt"
                source.write_bytes(b"first tab upload")
                first.add_to_transfer_queue("upload", str(source), "/home/upload.txt", source.stat().st_size)
                window.connection_tabs.setCurrentWidget(second)
                self.wait_for(lambda: first.transfer_queue[0]["status"] == "Completed"
                              and not first.has_running_operations())
                self.assertEqual(servers[0].files["upload.txt"], b"first tab upload")
                self.assertNotIn("upload.txt", servers[1].files)
            window.connection_tabs.setCurrentWidget(first)
            first.sftp_client.remove("/home/server-0.txt")
            self.assertNotIn("server-0.txt", servers[0].files)
            self.assertIn("server-1.txt", servers[1].files)
            window.close_connection_tab(0)
            self.assertIs(window.connection_tabs.widget(0), second)
            self.assertEqual(second.sftp_client.listdir_attr("/home")[0].filename,
                             "server-1.txt")
            window.close_connection_tab(0)
            self.assertEqual(window.connection_tabs.count(), 1)
            self.assertIsNone(window.connection_tabs.widget(0).sftp_client)
        finally:
            window.close()
            for server in servers:
                server.shutdown()
                server.server_close()

    def test_busy_tab_cannot_be_closed(self):
        window = TabbedFTPClientApp()
        session = window.connection_tabs.widget(0)
        with patch.object(session, "has_running_operations", return_value=True), \
                patch.object(QMessageBox, "information") as message:
            window.close_connection_tab(0)
            self.assertEqual(window.connection_tabs.count(), 1)
            self.assertIs(window.connection_tabs.widget(0), session)
            message.assert_called_once()
            self.assertFalse(window.close())
        window.close()


if __name__ == "__main__":
    unittest.main()
