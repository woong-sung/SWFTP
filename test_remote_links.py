import stat
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app import SFTPWorker


class RemoteLinkTests(unittest.TestCase):
    def test_listing_follows_directory_links_and_keeps_broken_links(self):
        client = Mock()
        def entry(name, mode):
            return SimpleNamespace(filename=name, st_mode=mode, st_size=0,
                                   st_mtime=0, st_uid=0, st_gid=0, longname="")
        client.listdir_attr.return_value = [
            entry("folder link", stat.S_IFLNK | 0o777),
            entry("file link", stat.S_IFLNK | 0o777),
            entry("broken link", stat.S_IFLNK | 0o777),
            entry("regular", stat.S_IFREG | 0o644),
        ]
        client.stat.side_effect = [entry("target", stat.S_IFDIR | 0o755),
                                   entry("target", stat.S_IFREG | 0o644),
                                   FileNotFoundError("broken link")]
        worker = SFTPWorker("list_dir", sftp=client, path="/home")
        results, errors = [], []
        worker.finished_signal.connect(lambda action, files: results.extend(files))
        worker.error_signal.connect(errors.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertEqual(results[0]["name"], "folder link")
        self.assertTrue(results[0]["is_dir"])
        self.assertTrue(all(not row["is_dir"] for row in results[1:]))
        self.assertTrue(results[0]["mode"].startswith("l"))
        self.assertEqual([call.args[0] for call in client.stat.call_args_list],
                         ["/home/folder link", "/home/file link", "/home/broken link"])


if __name__ == "__main__":
    unittest.main()
