"""GitHub Releases updates for the Windows one-file distribution."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

from PyQt6.QtCore import QThread, pyqtSignal
from app_version import APP_VERSION

ASSET_NAME = "SFTP_Client.exe"


def version_tuple(value):
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise ValueError("Release tags must use vMAJOR.MINOR.PATCH")
    return tuple(map(int, value.lstrip("v").split(".")))


def repository():
    config = Path(sys.executable).with_name("update_config.json")
    if not config.exists():
        config = Path(__file__).with_name("update_config.json")
    value = json.loads(config.read_text(encoding="utf-8" )).get("repository", "")
    if value and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("Invalid GitHub repository")
    return value


def request(url):
    return urlopen(Request(url, headers={"User-Agent": "SFTP-Client-Updater",
                                       "Accept": "application/vnd.github+json"}), timeout=15)


def select_asset(release):
    if release.get("draft") or release.get("prerelease"):
        return None
    if version_tuple(release["tag_name"]) <= version_tuple(APP_VERSION):
        return None
    asset = next((a for a in release["assets"] if a["name"] == ASSET_NAME), None)
    if asset is None:
        raise ValueError(f"Release is missing {ASSET_NAME}")
    if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", asset.get("digest") or ""):
        raise ValueError("Release asset is missing its SHA-256 digest")
    return asset


class UpdateWorker(QThread):
    ready = pyqtSignal(str, str, str)  # file, digest, version
    message = pyqtSignal(str)

    def run(self):
        staged = None
        try:
            repo = repository()
            if not repo:
                return
            with request(f"https://api.github.com/repos/{repo}/releases/latest") as response:
                release = json.load(response)
            asset = select_asset(release)
            if asset is None or self.isInterruptionRequested():
                return
            url = asset["browser_download_url"]
            if not url.startswith(f"https://github.com/{repo}/releases/download/"):
                raise ValueError("Unexpected release download URL")
            self.message.emit("새 버전을 다운로드하고 있습니다…")
            digest = hashlib.sha256()
            with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as output:
                staged = Path(output.name)
                with request(url) as response:
                    while True:
                        if self.isInterruptionRequested():
                            return
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
            expected = asset["digest"].split(":", 1)[1].lower()
            if digest.hexdigest() != expected or staged.stat().st_size != asset["size"]:
                raise ValueError("Update checksum or size mismatch")
            with staged.open("rb") as downloaded:
                if downloaded.read(2) != b"MZ":
                    raise ValueError("Update is not a Windows executable")
            self.ready.emit(str(staged), expected, release["tag_name"])
            staged = None
        except Exception as error:
            self.message.emit(f"자동 업데이트 확인 실패: {error}")
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)


def install_on_exit(staged, digest, executable=None, pid=None):
    """Start a hidden helper; retain the current executable on any failure."""
    target = str(Path(executable or sys.executable).resolve())
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = f"""
$ErrorActionPreference = 'Stop'
$source = {quote(staged)}
$target = {quote(target)}
$pending = $target + '.update-' + [guid]::NewGuid().ToString('N')
try {{
    $parent = Get-Process -Id {pid or os.getpid()} -ErrorAction SilentlyContinue
    if ($parent) {{ $parent | Wait-Process -Timeout 120 }}
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne {quote(digest)}) {{ throw 'Checksum mismatch' }}
    Copy-Item -LiteralPath $source -Destination $pending
    $replaced = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {{
        try {{
            [System.IO.File]::Replace($pending, $target, $target + '.previous', $true)
            $replaced = $true
            break
        }} catch {{ Start-Sleep -Milliseconds 1000 }}
    }}
    if (-not $replaced) {{ throw 'Executable replacement failed' }}
}} catch {{
    $_ | Out-String | Set-Content -LiteralPath ($source + '.log')
}} finally {{
    Remove-Item -LiteralPath $pending -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $source -ErrorAction SilentlyContinue
}}
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                      "-EncodedCommand", encoded], creationflags=subprocess.CREATE_NO_WINDOW)
