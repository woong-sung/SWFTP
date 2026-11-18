import concurrent.futures
import ftplib
import socket
import socketserver
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ftp_client import FTPClient


class FTPHandler(socketserver.StreamRequestHandler):
    """Loopback FTP fixture exercising real control and passive data sockets."""
    def handle(self):
        passive = None
        def reply(text):
            self.wfile.write((text + "\r\n").encode("utf-8"))
        reply("220 Test FTP")
        try:
            for raw in self.rfile:
                command, _, argument = raw.decode("utf-8").rstrip("\r\n").partition(" ")
                if command == "USER":
                    reply("331 Password required")
                elif command == "PASS":
                    reply("230 Logged in")
                elif command == "PWD":
                    reply('257 "/home"')
                elif command == "TYPE":
                    reply("200 Type set")
                elif command == "PASV":
                    passive = socket.socket()
                    passive.bind(("127.0.0.1", 0))
                    passive.listen(1)
                    port = passive.getsockname()[1]
                    reply(f"227 Passive (127,0,0,1,{port // 256},{port % 256})")
                elif command in ("MLSD", "RETR", "STOR"):
                    reply("150 Opening data connection")
                    connection, _ = passive.accept()
                    with connection:
                        if command == "MLSD":
                            for name, data in list(self.server.files.items()):
                                connection.sendall(f"type=file;size={len(data)};modify=20261105000000; {name}\r\n".encode("utf-8"))
                        elif command == "RETR":
                            connection.sendall(self.server.files[argument.rsplit("/", 1)[-1]])
                        else:
                            data = bytearray()
                            while block := connection.recv(8192):
                                data.extend(block)
                            self.server.files[argument.rsplit("/", 1)[-1]] = bytes(data)
                    passive.close()
                    passive = None
                    reply("226 Transfer complete")
                elif command == "SIZE":
                    reply("213 " + str(len(self.server.files[argument.rsplit("/", 1)[-1]])))
                elif command == "RNFR":
                    self.old = argument.rsplit("/", 1)[-1]
                    reply("350 Rename destination required")
                elif command == "RNTO":
                    self.server.files[argument.rsplit("/", 1)[-1]] = self.server.files.pop(self.old)
                    reply("250 Renamed")
                elif command == "DELE":
                    del self.server.files[argument.rsplit("/", 1)[-1]]
                    reply("250 Deleted")
                elif command == "MKD":
                    reply('257 "' + argument + '" created')
                elif command in ("RMD", "SITE"):
                    reply("250 Done")
                else:
                    reply("502 Unsupported command")
        finally:
            if passive:
                passive.close()


class FTPTests(unittest.TestCase):
    def test_symlink_directory_probe_and_restore(self):
        with patch("ftp_client.ftplib.FTP") as factory:
            ftp = factory.return_value
            ftp.pwd.return_value = "/home"
            ftp.mlsd.return_value = [
                ("folder link", {"type": "OS.unix=slink:/target"}),
                ("file link", {"type": "OS.unix=symlink"}),
                ("broken link", {"type": "OS.unix=slink"}),
            ]
            def change_directory(path):
                if path in ("/home/file link", "/home/broken link"):
                    raise ftplib.error_perm("550 Not a directory")
            ftp.cwd.side_effect = change_directory
            client = FTPClient("host", 21, "user", "pass")
            entries = client.listdir_attr("/home")
            self.assertTrue(all(stat.S_ISLNK(entry.st_mode) for entry in entries))
            self.assertEqual([entry.target_is_dir for entry in entries], [True, False, False])
            self.assertEqual([call.args[0] for call in ftp.cwd.call_args_list],
                             ["/home/folder link", "/home", "/home/file link", "/home/broken link"])

            ftp.mlsd.side_effect = ftplib.error_perm("502 Unsupported")
            ftp.retrlines.side_effect = lambda cmd, callback: callback(
                "lrwxrwxrwx 1 owner group 12 Nov 05 2026 folder link -> /target")
            entry = client.listdir_attr("/home")[0]
            self.assertEqual(entry.filename, "folder link")
            self.assertTrue(entry.target_is_dir)

    def test_real_passive_transfers_and_concurrent_listing(self):
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FTPHandler)
        server.files = {"한글 file.bin": bytes(range(256)) * 100}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = None
        try:
            client = FTPClient("127.0.0.1", server.server_address[1], "user", "password")
            self.assertEqual(client.initial_directory, "/home")
            with tempfile.TemporaryDirectory() as directory:
                local = str(Path(directory) / "download.bin")
                progress = []
                with concurrent.futures.ThreadPoolExecutor(2) as executor:
                    download = executor.submit(client.get, "/home/한글 file.bin", local,
                                               lambda count, total: progress.append((count, total)))
                    listing = executor.submit(client.listdir_attr, "/home")
                    download.result(timeout=10)
                    self.assertEqual(listing.result(timeout=10)[0].filename, "한글 file.bin")
                self.assertEqual(Path(local).read_bytes(), server.files["한글 file.bin"])
                self.assertEqual(progress[-1], (25600, 25600))
                client.put(local, "/home/upload.bin")
                self.assertEqual(server.files["upload.bin"], Path(local).read_bytes())
                client.rename("/home/upload.bin", "/home/renamed.bin")
                client.remove("/home/renamed.bin")
                self.assertNotIn("renamed.bin", server.files)
                client.mkdir("/home/folder")
                client.rmdir("/home/folder")
                with client.open("/home/edit.txt", "w") as output:
                    output.write("편집")
                with client.open("/home/edit.txt", "r") as source:
                    self.assertEqual(source.read(), "편집".encode())
                with self.assertRaises(ValueError):
                    with client.open("/home/aborted.txt", "w"):
                        raise ValueError("cancel write")
                self.assertNotIn("aborted.txt", server.files)
        finally:
            if client:
                client.close()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_legacy_list_fallback(self):
        with patch("ftp_client.ftplib.FTP") as factory:
            ftp = factory.return_value
            client = FTPClient("host", 21, "user", "pass", "cp949")
            self.assertEqual(factory.call_args.kwargs["encoding"], "cp949")
            ftp.mlsd.side_effect = ftplib.error_perm("502 MLSD unsupported")
            ftp.retrlines.side_effect = lambda cmd, callback: callback(
                "-rw-r--r-- 1 owner group 42 Nov 05 2026 한글 file.txt")
            self.assertEqual(client.listdir_attr("/")[0].filename, "한글 file.txt")
            ftp.mlsd.side_effect = ftplib.error_perm("550 Access denied")
            with self.assertRaises(ftplib.error_perm):
                client.listdir_attr("/private")
        entry = FTPClient._parse_list("11-05-26  09:30AM       <DIR>          Folder name")
        self.assertEqual(entry.filename, "Folder name")


if __name__ == "__main__":
    unittest.main()
