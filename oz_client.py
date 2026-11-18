"""SFTP-shaped adapter for the official locally installed OZ 8 Repository API."""

import base64
import contextlib
import io
import json
import os
import posixpath
import queue
import shutil
import stat
import subprocess
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

from ftp_client import serialized

OZ_PROTOCOL = "OZ Report (HTTP)"


def normalize_server_url(url):
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("OZ 서버 URL을 입력해 주세요. 예: http://222.231.28.46:8080/oz80/server")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("OZ URL에는 서버 주소와 경로만 입력하고, 계정은 별도 입력란을 사용해 주세요.")
    # Validate an explicit port as well as the hostname.
    parts.port
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", "", ""))


def find_oz_runtime():
    roots = [Path(os.environ["OZ_REPORT_HOME"])] if os.environ.get("OZ_REPORT_HOME") else []
    roots += [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "FORCS" / "OZ Report 8.0"]
    for root in roots:
        for product in ("OZ Report Designer 8.0", "OZ Query Designer 8.0"):
            lib = root / product / "lib"
            if (lib / "ozsfw80.jar").is_file() and (lib / "log4j.jar").is_file():
                java = root / "jre" / "bin" / "java.exe"
                if not java.is_file():
                    java = shutil.which("java")
                if java:
                    return str(java), str(lib)
    raise RuntimeError("OZ Report 8.0의 Java 및 API 라이브러리를 찾지 못했습니다. OZ_REPORT_HOME을 설치 폴더로 설정해 주세요.")


class OZClient:
    initial_directory = "/"

    def __init__(self, url, user, password, use_usl=False):
        self.url = normalize_server_url(url)
        self.lock = threading.RLock()
        self.closed = False
        self.responses = queue.Queue()
        java, lib = find_oz_runtime()
        helper = Path(__file__).resolve().parent / "oz_bridge" / "oz_repository_bridge.jar"
        if not helper.is_file():
            raise RuntimeError("OZ 연결 모듈이 없습니다: " + str(helper))
        classpath = os.pathsep.join((str(helper), str(Path(lib) / "*")))
        self.process = subprocess.Popen(
            [java, "-Dfile.encoding=UTF-8", "-Djava.library.path=" + str(Path(lib).parent / "bin"),
             "-cp", classpath, "OZRepositoryBridge"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.reader = threading.Thread(target=self._read_responses, daemon=True)
        self.reader.start()
        try:
            self._request("connect", self.url, user, password, str(bool(use_usl)).lower())
        except Exception:
            self._terminate()
            raise

    def _read_responses(self):
        try:
            for line in self.process.stdout:
                if line.startswith(b"OZFTP\t"):
                    self.responses.put(line.decode("utf-8").rstrip("\r\n").split("\t"))
        finally:
            self.responses.put(None)

    def _terminate(self):
        self.closed = True
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()

    def _request(self, command, *args, callback=None, response_timeout=60):
        if self.closed or self.process.poll() is not None:
            raise ConnectionError("OZ 서버 연결이 종료되었습니다. 다시 연결해 주세요.")
        fields = [base64.b64encode(str(value).encode("utf-8")) for value in (command,) + args]
        try:
            self.process.stdin.write(b"\t".join(fields) + b"\n")
            self.process.stdin.flush()
            while True:
                response = self.responses.get(timeout=response_timeout)
                if response is None:
                    raise ConnectionError("OZ 연결 모듈이 종료되었습니다. OZ API 및 Java 설치를 확인해 주세요.")
                if response[1] == "PROGRESS":
                    if callback:
                        try:
                            callback(int(response[2]), int(response[3]))
                        except Exception:
                            # The SDK is blocked inside its transfer call. Stop the
                            # helper immediately rather than silently finish a cancelled upload.
                            self._terminate()
                            raise
                    continue
                payload = base64.b64decode(response[2]).decode("utf-8")
                if response[1] == "ERROR":
                    raise OSError(payload)
                return json.loads(payload)
        except (queue.Empty, BrokenPipeError, ConnectionError):
            self._terminate()
            raise ConnectionError("OZ 서버 응답이 없거나 연결이 종료되었습니다. 주소·네트워크·서버의 API 접속 허용 설정을 확인해 주세요.") from None

    @serialized
    def close(self):
        if self.closed:
            return
        try:
            try:
                self._request("quit", response_timeout=2)
            except (OSError, ConnectionError):
                pass
        finally:
            self._terminate()

    @staticmethod
    def _path(path):
        return posixpath.normpath("/" + path.lstrip("/"))

    @serialized
    def listdir_attr(self, path):
        result = self._request("list", self._path(path))
        entries = []
        for item in result:
            name = item["name"].rstrip("/").rsplit("/", 1)[-1]
            if name in ("", ".", ".."):
                continue
            mode = (stat.S_IFDIR | 0o755) if item["dir"] else (stat.S_IFREG | 0o644)
            entries.append(SimpleNamespace(filename=name, st_mode=mode, st_size=item["size"],
                          st_mtime=max(0, item["mtime"] / 1000), st_uid=item.get("owner") or "",
                          st_gid="", longname=""))
        return entries

    @serialized
    def stat(self, path):
        path = self._path(path)
        if path == "/":
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_size=0, st_mtime=0)
        for entry in self.listdir_attr(posixpath.dirname(path)):
            if entry.filename == posixpath.basename(path):
                return entry
        raise FileNotFoundError(path)

    lstat = stat

    @serialized
    def get(self, remote, local, callback=None):
        self._request("get", self._path(remote), os.path.abspath(local), callback=callback)

    @serialized
    def put(self, local, remote, callback=None):
        self._request("put", os.path.abspath(local), self._path(remote), callback=callback)

    @serialized
    def remove(self, path):
        self._request("remove", self._path(path))

    @serialized
    def rmdir(self, path):
        self._request("rmdir", self._path(path))

    @serialized
    def mkdir(self, path):
        self._request("mkdir", self._path(path))

    def rename(self, oldpath, newpath):
        raise NotImplementedError("OZ 연결에서는 이름 변경·이동을 지원하지 않습니다.")

    def chmod(self, path, mode):
        raise NotImplementedError("OZ 저장소 권한은 OZ Repository Manager에서 설정해 주세요.")

    @contextlib.contextmanager
    def open(self, path, mode="r"):
        with tempfile.TemporaryDirectory(prefix="oz_edit_") as directory:
            local = os.path.join(directory, "content")
            if "r" in mode:
                self.get(path, local)
                yield io.BytesIO(Path(local).read_bytes())
            else:
                text = io.StringIO()
                try:
                    yield text
                    Path(local).write_text(text.getvalue(), encoding="utf-8")
                    self.put(local, path)
                finally:
                    text.close()
