import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import QApplication, QTableWidgetItem
from app import FileTableWidget, SFTPClientApp


class ExternalDropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = [str(Path(self.temp.name, name)) for name in ('first.txt', '한글 space.txt')]
        for p in self.paths:
            Path(p).write_text('data', encoding='utf-8')
        self.parent = SimpleNamespace(sftp_client=object(), current_remote_dir='/dest',
                                      upload_multiple_files=Mock())
        self.table = FileTableWidget(0, 1, self.parent, is_remote=True)
        self.mime = QMimeData()
        self.mime.setUrls([QUrl.fromLocalFile(p) for p in self.paths])

    def tearDown(self):
        self.table.close()
        self.temp.cleanup()

    def drop(self, y=100):
        event = QDropEvent(QPointF(10, y), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                           self.mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
        self.table.dropEvent(event)
        return event

    def test_external_multiple_files_are_copied_to_current_directory(self):
        event = self.drop()
        self.assertTrue(event.isAccepted())
        self.assertEqual(event.dropAction(), Qt.DropAction.CopyAction)
        self.parent.upload_multiple_files.assert_called_once_with(self.paths, '/dest')
        self.assertTrue(all(Path(p).exists() for p in self.paths))

    def test_folder_row_is_destination(self):
        self.table.setRowCount(1)
        item = QTableWidgetItem('folder')
        item.setData(Qt.ItemDataRole.UserRole, ('folder', True))
        self.table.setItem(0, 0, item)
        self.drop(5)
        self.parent.upload_multiple_files.assert_called_once_with(self.paths, '/dest/folder')

    def test_enter_and_move_force_copy(self):
        for event_type in (QDragEnterEvent, QDragMoveEvent):
            event = event_type(QPoint(10, 10), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                               self.mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
            self.table.accept_file_drag(event)
            self.assertTrue(event.isAccepted())
            self.assertEqual(event.dropAction(), Qt.DropAction.CopyAction)

    def test_disconnected_or_nonlocal_drop_is_rejected(self):
        self.parent.sftp_client = None
        self.assertFalse(self.drop().isAccepted())
        self.parent.sftp_client = object()
        self.mime.setUrls([QUrl('https://example.com/file')])
        self.assertFalse(self.drop().isAccepted())
        self.parent.upload_multiple_files.assert_not_called()

    def test_files_and_directory_all_reach_transfer_queue(self):
        folder = Path(self.temp.name, 'folder')
        folder.mkdir()
        self.paths.append(str(folder))
        self.parent.add_to_transfer_queue = Mock()
        SFTPClientApp.upload_multiple_files(self.parent, self.paths, '/dest')
        self.assertEqual(self.parent.add_to_transfer_queue.call_count, 3)
        self.assertEqual([c.args[2] for c in self.parent.add_to_transfer_queue.call_args_list],
                         ['/dest/first.txt', '/dest/한글 space.txt', '/dest/folder'])


if __name__ == '__main__':
    unittest.main()
