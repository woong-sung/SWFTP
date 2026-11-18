"""Recursive deletion using file APIs, without following directory symlinks."""

import os
import posixpath
import shutil
import stat


def upload_directory(client, source, destination, callback, cancelled):
    """Upload a tree, retaining empty folders and reporting aggregate progress."""
    directories = []
    files = []

    def check_cancelled():
        if cancelled():
            raise RuntimeError("Cancelled")

    def scan(local, remote):
        check_cancelled()
        if os.path.islink(local) or os.path.isjunction(local):
            raise ValueError(f"Directory links are not supported: {local}")
        directories.append(remote)
        with os.scandir(local) as entries:
            for entry in entries:
                check_cancelled()
                target = posixpath.join(remote, entry.name)
                if entry.is_symlink() or entry.is_junction():
                    raise ValueError(f"Links are not supported: {entry.path}")
                if entry.is_dir(follow_symlinks=False):
                    scan(entry.path, target)
                elif entry.is_file(follow_symlinks=False):
                    files.append((entry.path, target, entry.stat().st_size))
                else:
                    raise ValueError(f"Unsupported file: {entry.path}")

    scan(source, destination)
    total = sum(size for _, _, size in files)
    for remote in directories:
        check_cancelled()
        try:
            client.mkdir(remote)
        except Exception:
            # Only accept mkdir failures when the destination is a directory.
            entries = client.listdir_attr(posixpath.dirname(remote) or "/")
            if not any(entry.filename == posixpath.basename(remote)
                       and stat.S_ISDIR(entry.st_mode) for entry in entries):
                raise
    completed = 0
    for local, remote, size in files:
        check_cancelled()
        client.put(local, remote,
                   callback=lambda sent, ignored: callback(completed + sent, total))
        completed += size
        callback(completed, total)
    check_cancelled()
    callback(total, total)


def delete_local_item(path):
    path = os.path.abspath(path)
    if os.path.dirname(path) == path:
        raise ValueError("드라이브 루트는 삭제할 수 없습니다.")
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def delete_remote_item(client, path, is_dir):
    """Return per-path errors; delete children before their parent directory."""
    path = posixpath.normpath(path)
    if not path.startswith("/") or path == "/":
        raise ValueError("원격 루트 경로는 삭제할 수 없습니다.")
    errors = []

    def remove(current, mode):
        try:
            if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                client.remove(current)
                return
            previous_errors = len(errors)
            for entry in client.listdir_attr(current):
                name = entry.filename
                if name in (".", ".."):
                    continue
                if not name or "/" in name or "\\" in name:
                    errors.append(f"{current}: Invalid directory entry {name!r}")
                    continue
                remove(posixpath.join(current, name), entry.st_mode)
            if len(errors) == previous_errors:
                client.rmdir(current)
        except Exception as error:
            errors.append(f"{current}: {error}")

    if is_dir:
        # UI listings follow links for navigation. Re-read raw metadata before
        # deleting a selected directory so its link target is never traversed.
        lstat = getattr(type(client), "lstat", None)
        if lstat is not None:
            mode = client.lstat(path).st_mode
        else:
            entry = next((entry for entry in client.listdir_attr(posixpath.dirname(path))
                          if entry.filename == posixpath.basename(path)), None)
            if entry is None:
                raise FileNotFoundError(path)
            mode = entry.st_mode
    else:
        mode = stat.S_IFREG
    remove(path, mode)
    return errors
