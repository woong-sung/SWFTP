"""Run the actual Java bridge against a deterministic local SDK fixture."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from oz_client import OZClient, find_oz_runtime
from file_operations import delete_remote_item


class OZBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.java, cls.lib = find_oz_runtime()
        except RuntimeError as error:
            raise unittest.SkipTest(str(error))
        compiler = Path(r"C:\Program Files\Java\latest\jdk-21\bin\javac.exe")
        if not compiler.is_file():
            compiler = shutil.which("javac")
        if not compiler:
            raise unittest.SkipTest("JDK required to compile regression fixture")
        cls.fixture = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.classes = Path(cls.fixture.name)
        subprocess.run([str(compiler), "--release", "8", "-Xlint:-options", "-encoding", "UTF-8",
                        "-classpath", str(Path(cls.lib) / "ozsfw80.jar"), "-d", str(cls.classes),
                        "test_fixtures/oz_api/RepositoryEx.java"], check=True, capture_output=True)

    def client(self, mode):
        original_popen = subprocess.Popen

        def launch(command, **kwargs):
            command = command[:]
            index = command.index("-cp") + 1
            command[index] = str(self.classes) + os.pathsep + command[index]
            return original_popen(command, **kwargs)

        with patch("oz_client.subprocess.Popen", side_effect=launch):
            client = OZClient("http://fixture.invalid/oz/server", mode, "fixture")
        self.addCleanup(client.close)
        return client

    def test_folder_ids_unicode_and_slash_variants_keep_files_visible(self):
        for mode in ("plain", "compat", "trailing"):
            with self.subTest(mode=mode):
                client = self.client(mode)
                self.assertEqual([e.filename for e in client.listdir_attr("/")], ["보고서"])
                files = client.listdir_attr("/보고서")
                self.assertEqual({e.filename for e in files}, {"하위", "명세서.ozr"})
                self.assertEqual([e.filename for e in client.listdir_attr("/보고서/하위")], ["하위파일.odi"])
                with tempfile.TemporaryDirectory() as folder:
                    target = Path(folder) / "download.ozr"
                    client.get("/보고서/명세서.ozr", str(target))
                    self.assertEqual(target.read_bytes(), b"report-data")
                    client.get("/보고서/하위/하위파일.odi", str(target))
                    self.assertEqual(target.read_bytes(), b"nested-data")
                client.close()

    def test_upload_and_checkin_use_actual_parent_and_item_ids(self):
        client = self.client("compat")
        client.listdir_attr("/")
        client.listdir_attr("/보고서")
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.ozr"
            target = Path(folder) / "download.ozr"
            source.write_bytes(b"new report")
            client.put(str(source), "/보고서/새보고서.ozr")
            client.get("/보고서/새보고서.ozr", str(target))
            self.assertEqual(target.read_bytes(), b"new report")
            source.write_bytes(b"checked in")
            client.put(str(source), "/보고서/새보고서.ozr")
            client.get("/보고서/새보고서.ozr", str(target))
            self.assertEqual(target.read_bytes(), b"checked in")
            client.listdir_attr("/보고서")
            client.remove("/보고서/새보고서.ozr")
            self.assertNotIn("새보고서.ozr", [e.filename for e in client.listdir_attr("/보고서")])

    def test_recursive_delete_uses_actual_ids_for_nested_oz_categories(self):
        client = self.client("compat")
        client.listdir_attr("/")
        self.assertEqual(delete_remote_item(client, "/보고서", True), [])
        self.assertEqual(client.listdir_attr("/"), [])


if __name__ == "__main__":
    unittest.main()
