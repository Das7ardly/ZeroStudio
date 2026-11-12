"""Locate the MKVToolNix command-line tools (mkvmerge, mkvextract, mkvpropedit)."""
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .paths import data_dir

TOOLS = ("mkvmerge", "mkvextract", "mkvpropedit")
IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WIN else 0
DOWNLOAD_PAGE = "https://mkvtoolnix.download/downloads.html"


def _exe(name):
    return name + ".exe" if IS_WIN else name


def _registry_dirs():
    out = []
    if not IS_WIN:
        return out
    try:
        import winreg
        key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\mkvtoolnix-gui.exe"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, key) as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    out.append(str(Path(val.strip('"')).parent))
            except OSError:
                pass
    except ImportError:
        pass
    return out


def candidate_dirs(custom=""):
    dirs = []
    if custom:
        dirs.append(custom)
    dirs += [str(data_dir() / "bin" / "mkvtoolnix"), str(data_dir() / "bin")]
    if IS_WIN:
        for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if base:
                dirs.append(os.path.join(base, "MKVToolNix"))
        dirs += _registry_dirs()
        dirs.append(str(Path.home() / "scoop" / "apps" / "mkvtoolnix" / "current"))
    elif sys.platform == "darwin":
        dirs += sorted(glob.glob("/Applications/MKVToolNix*.app/Contents/MacOS"), reverse=True)
        dirs += ["/opt/homebrew/bin", "/usr/local/bin"]
    return dirs


class Engine:
    def __init__(self, custom_dir=""):
        self.paths = {}
        self.folder = ""
        self.reload(custom_dir)

    def reload(self, custom_dir=""):
        self.paths = {}
        self.folder = ""
        for d in candidate_dirs(custom_dir):
            if all(os.path.isfile(os.path.join(d, _exe(t))) for t in TOOLS):
                self.paths = {t: os.path.join(d, _exe(t)) for t in TOOLS}
                self.folder = d
                break
        if not self.paths:
            found = {t: shutil.which(t) for t in TOOLS}
            if all(found.values()):
                self.paths = found
                self.folder = str(Path(found["mkvmerge"]).parent)
        self._version = None

    @property
    def ok(self):
        return bool(self.paths)

    def tool(self, name):
        return self.paths.get(name)

    def version(self):
        if not self.ok:
            return ""
        if self._version is None:
            try:
                r = subprocess.run([self.paths["mkvmerge"], "--version"], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=10, creationflags=NO_WINDOW)
                self._version = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
            except Exception:
                self._version = ""
        return self._version


def child_env():
    """Environment for engine processes: force UTF-8 on Unix so non-ASCII names work."""
    env = dict(os.environ)
    if not IS_WIN and "UTF-8" not in env.get("LC_ALL", env.get("LANG", "")).upper():
        env["LC_ALL"] = "C.UTF-8"
        env["LANG"] = "C.UTF-8"
    return env
