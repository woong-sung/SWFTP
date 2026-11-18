import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox
from app import TabbedFTPClientApp


class FolderNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.paths = [str(Path(self.directory.name, name)) for name in ("a", "b", "c")]
        for path in self.paths:
            Path(path).mkdir()
        self.window = TabbedFTPClientApp()
        self.session = self.window.connection_tabs.widget(0)

    def tearDown(self):
        self.session.sftp_client = None
        self.window.close()
        self.directory.cleanup()

    def test_mouse_back_forward_and_new_branch_on_local_pane(self):
        session = self.session
        for path in self.paths[:2]:
            session.set_local_directory(path)
        QTest.mouseClick(session.local_table.viewport(), Qt.MouseButton.BackButton)
        self.assertEqual(session.current_local_dir, self.paths[0])
        self.assertEqual(session.local_path_input.text(), self.paths[0])
        QTest.mouseClick(session.local_path_input, Qt.MouseButton.ForwardButton)
        self.assertEqual(session.current_local_dir, self.paths[1])
        QTest.mouseClick(session.local_table.viewport(), Qt.MouseButton.BackButton)
        session.set_local_directory(self.paths[2])
        QTest.mouseClick(session.local_table.viewport(), Qt.MouseButton.ForwardButton)
        self.assertEqual(session.current_local_dir, self.paths[2])
        self.assertNotIn(self.paths[1], session.local_navigation_paths)

    def test_remote_history_commits_after_listing_and_is_separate(self):
        session = self.session
        session.sftp_client = Mock()
        for path in ("/home", "/home/one", "/home/two"):
            session.set_remote_directory(path)
            session.on_worker_done("list_dir", [])
        local_path = session.current_local_dir
        with patch.object(session, "start_worker", side_effect=lambda worker:
                          worker.finished_signal.emit("list_dir", [])):
            QTest.mouseClick(session.remote_table.viewport(), Qt.MouseButton.BackButton)
            self.assertEqual(session.current_remote_dir, "/home/one")
            self.assertEqual(session.remote_navigation_index, 1)
            QTest.mouseClick(session.remote_path_input, Qt.MouseButton.ForwardButton)
            self.assertEqual(session.current_remote_dir, "/home/two")
            self.assertEqual(session.remote_navigation_index, 2)
        self.assertEqual(session.current_local_dir, local_path)
        self.assertEqual(session.remote_navigation_paths, ["/home", "/home/one", "/home/two"])

    def test_failed_remote_history_navigation_preserves_current_path(self):
        session = self.session
        session.sftp_client = Mock()
        for path in ("/home", "/home/one"):
            session.set_remote_directory(path)
            session.on_worker_done("list_dir", [])
        with patch.object(session, "start_worker", side_effect=lambda worker:
                          worker.error_signal.emit("list_dir", "permission denied")), \
                patch.object(QMessageBox, "critical"):
            QTest.mouseClick(session.remote_table.viewport(), Qt.MouseButton.BackButton)
        self.assertEqual(session.current_remote_dir, "/home/one")
        self.assertEqual(session.remote_navigation_index, 1)
        session.disconnect_sftp()
        self.assertEqual(session.remote_navigation_paths, [])

    def test_history_is_independent_between_tabs_and_refresh_does_not_duplicate(self):
        first = self.session
        first.set_local_directory(self.paths[0])
        first.set_local_directory(self.paths[1])
        paths = first.local_navigation_paths[:]
        first.set_local_directory(self.paths[1])
        first.populate_local_dir()
        self.assertEqual(first.local_navigation_paths, paths)
        second = self.window.add_connection_tab()
        second.set_local_directory(self.paths[2])
        QTest.mouseClick(first.local_table.viewport(), Qt.MouseButton.BackButton)
        self.assertEqual(first.current_local_dir, self.paths[0])
        self.assertEqual(second.current_local_dir, self.paths[2])


if __name__ == "__main__":
    unittest.main()
