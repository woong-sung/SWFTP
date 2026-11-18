"""FTP adapter for the application's file operations."""

import contextlib
import datetime
import ftplib
import functools
import io
import posixpath
import re
import stat
import threading
from types import SimpleNamespace


def serialized(method):
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return wrapped


class FTPClient:
    def __init__(self, host, port, user, password, encoding="utf-8"):
        self.lock = threading.RLock()
        self.ftp = ftplib.FTP(encoding=encoding, timeout=30)
        try:
            self.ftp.connect(host, port)
            self.ftp.login(user, password)
            self.ftp.set_pasv(True)
            self.initial_directory = self.ftp.pwd()
        except Exception:
            self.ftp.close()
            raise

    @serialized
    def close(self):
        self.ftp.close()

    @serialized
    def listdir_attr(self, path):
        try:
            rows = list(self.ftp.mlsd(path))
        except ftplib.error_perm as exc:
            if not str(exc).startswith(("500", "501", "502", "504")):
                raise
            lines = []
            self.ftp.retrlines("LIST " + path, lines.append)
            return self._resolve_links(path, [self._parse_list(line) for line in lines
                    if line and not line.startswith("total ")])
        result = []
        for name, facts in rows:
            kind = facts.get("type", "file")
            if kind in ("cdir", "pdir"):
                continue
            if "slink" in kind.lower() or "symlink" in kind.lower():
                mode = stat.S_IFLNK | 0o777
            else:
                mode = stat.S_IFDIR | 0o755 if kind == "dir" else stat.S_IFREG | 0o644
            if facts.get("unix.mode"):
                mode = stat.S_IFMT(mode) | int(facts["unix.mode"], 8)
            modified = facts.get("modify", "19700101000000").split(".")[0]
            mtime = datetime.datetime.strptime(modified, "%Y%m%d%H%M%S").replace(
                tzinfo=datetime.timezone.utc).timestamp()
            result.append(self._entry(name, mode, int(facts.get("size", 0)), mtime))
        return self._resolve_links(path, result)

    def _resolve_links(self, path, entries):
        # FTP has no portable stat-following operation. CWD tests whether a
        # link leads to a directory; restore the session before returning.
        for entry in entries:
            if not stat.S_ISLNK(entry.st_mode):
                continue
            original = self.ftp.pwd()
            try:
                self.ftp.cwd(posixpath.join(path, entry.filename))
            except ftplib.error_perm:
                entry.target_is_dir = False
            else:
                try:
                    entry.target_is_dir = True
                finally:
                    self.ftp.cwd(original)
        return entries

    @staticmethod
    def _entry(name, mode, size, mtime, owner="-", group="-"):
        return SimpleNamespace(filename=name, st_mode=mode, st_size=size,
                               st_mtime=mtime, st_uid=owner, st_gid=group, longname="")

    @classmethod
    def _parse_list(cls, line):
        parts = line.split(None, 8)
        if len(parts) == 9 and parts[0][0] in "-dl":
            permissions, _, owner, group, size, month, day, year_time, name = parts
            mode = {"d": stat.S_IFDIR, "l": stat.S_IFLNK}.get(permissions[0], stat.S_IFREG)
            for index, char in enumerate(permissions[1:10]):
                if char in "rwxst":
                    mode |= 1 << (8 - index)
            now = datetime.datetime.now()
            stamp = f"{month} {day} {year_time}"
            if ":" in year_time:
                date = datetime.datetime.strptime(f"{now.year} {stamp}", "%Y %b %d %H:%M")
                if date > now + datetime.timedelta(days=1):
                    date = date.replace(year=now.year - 1)
            else:
                date = datetime.datetime.strptime(stamp, "%b %d %Y")
            if permissions[0] == "l":
                name = name.split(" -> ", 1)[0]
            return cls._entry(name, mode, int(size), date.timestamp(), owner, group)
        match = re.match(r"(\d{2}-\d{2}-\d{2,4})\s+(\d{2}:\d{2}[AP]M)\s+(<DIR>|\d+)\s+(.+)", line, re.I)
        if match:
            date, time, size, name = match.groups()
            fmt = "%m-%d-%Y" if len(date) == 10 else "%m-%d-%y"
            mtime = datetime.datetime.strptime(date + " " + time.upper(), fmt + " %I:%M%p").timestamp()
            directory = size.upper() == "<DIR>"
            return cls._entry(name, (stat.S_IFDIR | 0o755) if directory else (stat.S_IFREG | 0o644),
                              0 if directory else int(size), mtime)
        raise ValueError("Unsupported FTP directory listing: " + line)

    @serialized
    def get(self, remote, local, callback=None):
        try:
            self.ftp.voidcmd("TYPE I")
            total = self.ftp.size(remote) or 0
        except ftplib.error_perm:
            total = 0
        transferred = 0
        with open(local, "wb") as output:
            def receive(data):
                nonlocal transferred
                output.write(data)
                transferred += len(data)
                if callback:
                    callback(transferred, total)
            self.ftp.retrbinary("RETR " + remote, receive)

    @serialized
    def put(self, local, remote, callback=None):
        import os
        total = os.path.getsize(local)
        transferred = 0
        def sent(data):
            nonlocal transferred
            transferred += len(data)
            if callback:
                callback(transferred, total)
        with open(local, "rb") as source:
            self.ftp.storbinary("STOR " + remote, source, callback=sent)

    @serialized
    def remove(self, path):
        self.ftp.delete(path)

    @serialized
    def rmdir(self, path):
        self.ftp.rmd(path)

    @serialized
    def mkdir(self, path):
        self.ftp.mkd(path)

    @serialized
    def rename(self, oldpath, newpath):
        self.ftp.rename(oldpath, newpath)

    @serialized
    def chmod(self, path, mode):
        self.ftp.sendcmd(f"SITE CHMOD {mode:o} {path}")

    @contextlib.contextmanager
    def open(self, path, mode="r"):
        with self.lock:
            buffer = io.BytesIO()
            try:
                if "r" in mode:
                    self.ftp.retrbinary("RETR " + path, buffer.write)
                    buffer.seek(0)
                    yield buffer
                else:
                    text = io.StringIO()
                    try:
                        yield text
                        self.ftp.storbinary("STOR " + path, io.BytesIO(text.getvalue().encode("utf-8")))
                    finally:
                        text.close()
            finally:
                buffer.close()
