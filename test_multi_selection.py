import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QItemSelectionModel, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox
from app import SFTPClientApp, SFTPWorker
from ftp_client import FTPClient


class MultiSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.window = SFTPClientApp()
        self.window.set_local_directory(self.folder.name)
        for name in ("one.txt", "two.txt", "three.txt"):
            Path(self.folder.name, name).write_text(name)
        self.window.populate_local_dir()

    def tearDown(self):
        self.window.close()
        self.folder.cleanup()

    def select_rows(self, table, rows):
        table.clearSelection()
        for row in rows:
            table.selectionModel().select(table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def test_copy_paste_and_delete_key_confirm_entire_selection(self):
        table = self.window.local_table
        self.select_rows(table, [0, 1])
        expected = [table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in (0, 1)]
        QTest.keyClick(table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.window.app_clipboard["paths"], expected)
        with tempfile.TemporaryDirectory() as destination:
            self.window.current_local_dir = destination
            QTest.keyClick(table, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(sorted(p.name for p in Path(destination).iterdir()),
                             sorted(Path(p).name for p in expected))
        self.window.set_local_directory(self.folder.name)
        self.window.populate_local_dir()
        self.select_rows(table, [0, 1])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as confirm:
            QTest.keyClick(table, Qt.Key.Key_Delete)
            confirm.assert_called_once()
            for path in expected:
                self.assertIn(Path(path).name, confirm.call_args.args[2])
                self.assertTrue(Path(path).exists())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as confirm:
            QTest.keyClick(table, Qt.Key.Key_Delete)
            confirm.assert_called_once()
        self.assertEqual(len(list(Path(self.folder.name).iterdir())), 1)

    def test_mouse_drag_selects_multiple_rows(self):
        self.window.show()
        self.application.processEvents()
        table = self.window.local_table
        table.clearSelection()
        first = table.visualRect(table.model().index(0, 0)).center()
        last = table.visualRect(table.model().index(2, 0)).center()
        QTest.mousePress(table.viewport(), Qt.MouseButton.LeftButton, pos=first)
        QTest.mouseMove(table.viewport(), last)
        QTest.mouseRelease(table.viewport(), Qt.MouseButton.LeftButton, pos=last)
        self.assertEqual(table.selected_file_rows(), [0, 1, 2])

    def test_remote_delete_and_download_use_all_selected_rows(self):
        window = self.window
        window.sftp_client = Mock()
        entries = [dict(name=name, is_dir=False, size=1, mtime=0,
                        mode="-rw-r--r--", raw_mode=0o100644, owner="u", group="g")
                   for name in ("one.txt", "two.txt", "three.txt")]
        window.populate_remote_table(entries)
        self.select_rows(window.remote_table, [0, 1])
        with patch.object(window, "download_multiple_files") as download:
            window.download_selected_files()
            self.assertEqual(len(download.call_args.args[0]), 2)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No), \
                patch.object(window, "start_worker") as start:
            QTest.keyClick(window.remote_table, Qt.Key.Key_Delete)
            start.assert_not_called()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                patch.object(window, "start_worker") as start:
            QTest.keyClick(window.remote_table, Qt.Key.Key_Delete)
            worker = start.call_args.args[0]
            self.assertEqual(len(worker.args["items"]), 2)
            worker.run()
            self.assertEqual(window.sftp_client.remove.call_count, 2)

    def test_batch_delete_reports_failure_and_continues(self):
        client = Mock()
        client.remove.side_effect = [OSError("denied"), None]
        worker = SFTPWorker("delete_multiple", sftp=client,
                            items=[("/one", False), ("/two", False)])
        results = []
        worker.finished_signal.connect(lambda action, errors: results.append(errors))
        worker.run()
        self.assertEqual(client.remove.call_count, 2)
        self.assertEqual(len(results[0]), 1)
        self.assertIn("/one", results[0][0])

    def test_ftp_batch_copy_uses_separate_destination_files(self):
        client = Mock(spec=FTPClient)
        client.get.side_effect = lambda source, local: Path(local).write_bytes(source.encode())
        uploads = {}
        client.put.side_effect = lambda local, destination: uploads.update({destination: Path(local).read_bytes()})
        worker = SFTPWorker("copy_remote_multiple", sftp=client,
                            remotepaths=["/source/one", "/source/two"], destdir="/target")
        errors = []
        worker.error_signal.connect(lambda action, error: errors.append(error))
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(uploads, {"/target/one": b"/source/one", "/target/two": b"/source/two"})


if __name__ == "__main__":
    unittest.main()
