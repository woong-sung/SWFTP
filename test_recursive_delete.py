import os
import posixpath
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox
from app import SFTPClientApp, SFTPWorker
from file_operations import delete_remote_item


class RemoteTree:
    def __init__(self):
        self.nodes = {"/": stat.S_IFDIR, "/target": stat.S_IFDIR,
                      "/target/nested": stat.S_IFDIR, "/target/nested/deep": stat.S_IFDIR,
                      "/target/nested/deep/file": stat.S_IFREG, "/target/.hidden": stat.S_IFREG,
                      "/target/link": stat.S_IFLNK, "/outside": stat.S_IFDIR,
                      "/outside/keep": stat.S_IFREG}
        self.deleted = []
        self.denied = set()

    def listdir_attr(self, path):
        return [SimpleNamespace(filename=posixpath.basename(name), st_mode=mode)
                for name, mode in list(self.nodes.items())
                if name != path and posixpath.dirname(name) == path]

    def remove(self, path):
        if path in self.denied:
            raise PermissionError("denied")
        if stat.S_ISDIR(self.nodes[path]):
            raise IsADirectoryError(path)
        del self.nodes[path]
        self.deleted.append(path)

    def rmdir(self, path):
        if self.listdir_attr(path):
            raise OSError("not empty")
        del self.nodes[path]
        self.deleted.append(path)


class RecursiveDeleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_nested_remote_files_hidden_files_and_folders_are_deleted_in_order(self):
        client = RemoteTree()
        self.assertEqual(delete_remote_item(client, "/target", True), [])
        self.assertEqual(set(client.nodes), {"/", "/outside", "/outside/keep"})
        self.assertLess(client.deleted.index("/target/nested/deep/file"),
                        client.deleted.index("/target/nested/deep"))
        self.assertEqual(client.deleted[-1], "/target")

    def test_selected_directory_link_is_unlinked_without_traversal(self):
        client = RemoteTree()
        self.assertEqual(delete_remote_item(client, "/target/link", True), [])
        self.assertIn("/outside/keep", client.nodes)
        self.assertEqual(client.deleted, ["/target/link"])

    def test_permission_failure_is_reported_and_other_children_continue(self):
        client = RemoteTree()
        client.denied.add("/target/.hidden")
        worker = SFTPWorker("delete_multiple", sftp=client, items=[("/target", True)])
        results = []
        worker.finished_signal.connect(lambda action, errors: results.extend(errors))
        worker.run()
        self.assertEqual(len(results), 1)
        self.assertIn("/target/.hidden", results[0])
        self.assertIn("/target", client.nodes)
        self.assertNotIn("/target/nested", client.nodes)
        self.assertIn("/outside/keep", client.nodes)

    def test_root_cannot_be_deleted(self):
        client = RemoteTree()
        with self.assertRaises(ValueError):
            delete_remote_item(client, "/target/..", True)
        self.assertEqual(client.deleted, [])

    def test_local_delete_confirmation_covers_descendants_and_cancel_preserves_them(self):
        window = SFTPClientApp()
        try:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory, "target")
                nested = target / "nested" / "deep"
                nested.mkdir(parents=True)
                (nested / "file").write_text("data")
                sibling = Path(directory, "keep")
                sibling.write_text("keep")
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as confirm:
                    window.delete_file_items([(str(target), True)], False)
                    self.assertIn("하위 폴더와 파일", confirm.call_args.args[2])
                    self.assertTrue((nested / "file").exists())
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                    window.delete_file_items([(str(target), True)], False)
                self.assertFalse(target.exists())
                self.assertEqual(sibling.read_text(), "keep")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
