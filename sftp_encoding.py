"""SFTP directory listings with legacy Korean filename support."""

import posixpath
import functools
import socket
import threading

from paramiko import SFTPAttributes, SFTPClient, SFTPError
from paramiko.sftp import CMD_CLOSE, CMD_HANDLE, CMD_NAME, CMD_OPENDIR, CMD_READDIR


def decode_name(raw):
    for encoding in ("utf-8", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="backslashreplace")


def serialized_operation(method):
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.operation_lock:
            try:
                return method(self, *args, **kwargs)
            except socket.timeout:
                # A late reply must not be consumed by the next operation.
                self.get_channel().close()
                raise
    return wrapped


class EncodingSFTPClient(SFTPClient):
    def __init__(self, sock):
        self._filename_bytes = {}
        self.operation_lock = threading.RLock()
        # Paramiko otherwise waits forever when a server stops responding.
        sock.settimeout(30)
        super().__init__(sock)

    @serialized_operation
    def _request(self, *args):
        return super()._request(*args)

    @serialized_operation
    def get(self, *args, **kwargs):
        return super().get(*args, **kwargs)

    @serialized_operation
    def put(self, *args, **kwargs):
        return super().put(*args, **kwargs)

    def _adjust_cwd(self, path):
        if isinstance(path, str):
            parent = b"" if path.startswith("/") else (self._cwd or b"")
            for component in path.split("/"):
                if not component:
                    if not parent:
                        parent = b"/"
                    continue
                raw = self._filename_bytes.get((parent, component))
                if raw is None:
                    raw = component.encode("utf-8")
                parent = posixpath.join(parent, raw)
            return parent
        return super()._adjust_cwd(path)

    @serialized_operation
    def listdir_attr(self, path="."):
        path = self._adjust_cwd(path)
        kind, msg = self._request(CMD_OPENDIR, path)
        if kind != CMD_HANDLE:
            raise SFTPError("Expected handle")
        handle = msg.get_binary()
        entries = []
        names = {}
        try:
            while True:
                try:
                    kind, msg = self._request(CMD_READDIR, handle)
                except EOFError:
                    break
                if kind != CMD_NAME:
                    raise SFTPError("Expected name response")
                for _ in range(msg.get_int()):
                    raw = msg.get_string()
                    name = decode_name(raw)
                    longname = decode_name(msg.get_string())
                    attr = SFTPAttributes._from_msg(msg, name, longname)
                    if raw in (b".", b".."):
                        continue
                    if name in names and names[name] != raw:
                        raise SFTPError("Different filename encodings produce the same name: " + name)
                    names[name] = raw
                    entries.append(attr)
        finally:
            self._request(CMD_CLOSE, handle)
        for name, raw in names.items():
            self._filename_bytes[(path, name)] = raw
        return entries
