import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from app import SingleFileTransferWorker, SFTPClientApp
from file_operations import upload_directory


class Remote:
    def __init__(self):
        self.directories = {"/dest", "/dest/design"}
        self.files = {}

    def mkdir(self, path):
        if path in self.directories:
            raise FileExistsError(path)
        self.directories.add(path)

    def listdir_attr(self, path):
        return [SimpleNamespace(filename="design", st_mode=stat.S_IFDIR)]

    def put(self, source, destination, callback):
        self.files[destination] = Path(source).read_bytes()
        callback(len(self.files[destination]), len(self.files[destination]))


class DirectoryUploadTests(unittest.TestCase):
    def test_worker_uploads_nested_hidden_and_empty_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "design")
            (root / "nested" / "empty").mkdir(parents=True)
            (root / "nested" / "한글.txt").write_bytes(b"abc")
            (root / ".hidden").write_bytes(b"de")
            remote = Remote()
            worker = SingleFileTransferWorker(remote, "upload", str(root), "/dest/design", 0)
            results = []
            progress = []
            worker.finished_signal.connect(lambda *args: results.append(args))
            worker.progress_signal.connect(lambda sent, total, speed: progress.append((sent, total)))
            worker.run()
            self.assertEqual(results, [(True, "")])
            self.assertEqual(remote.files["/dest/design/nested/한글.txt"], b"abc")
            self.assertEqual(remote.files["/dest/design/.hidden"], b"de")
            self.assertIn("/dest/design/nested/empty", remote.directories)
            self.assertEqual(progress[-1], (5, 5))

    def test_cancelled_directory_does_not_create_remote_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            remote = Remote()
            with self.assertRaisesRegex(RuntimeError, "Cancelled"):
                upload_directory(remote, directory, "/dest/new", lambda *_: None, lambda: True)
            self.assertNotIn("/dest/new", remote.directories)

    def test_directory_is_queued_with_its_name(self):
        with tempfile.TemporaryDirectory() as directory:
            queued = []
            window = SimpleNamespace(sftp_client=object(),
                                     add_to_transfer_queue=lambda *args: queued.append(args))
            SFTPClientApp.upload_multiple_files(window, [directory + os.sep], "/dest")
            self.assertEqual(queued, [("upload", os.path.normpath(directory),
                                      "/dest/" + Path(directory).name, 0)])


if __name__ == "__main__":
    unittest.main()
