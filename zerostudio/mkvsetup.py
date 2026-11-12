"""Download the portable MKVToolNix for Windows into ZeroStudio's data folder (no admin rights needed)."""
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import APP_NAME, VERSION
from .engine import NO_WINDOW
from .paths import data_dir, sub_dir

BASE = "https://mkvtoolnix.download"
RELEASES = BASE + "/windows/releases/"
WINGET = "winget install MoritzBunkus.MKVToolNix"


class SetupError(Exception):
    pass


def sevenzip_exe():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "zerostudio" / "vendor" / "7za.exe"
    return Path(__file__).resolve().parent / "vendor" / "7za.exe"


def supported():
    return sys.platform == "win32" and sevenzip_exe().exists()


def _open(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{VERSION} (MKVToolNix setup)"})
    return urllib.request.urlopen(req, timeout=timeout)


def _vkey(v):
    return tuple(int(x) for x in v.split("."))


def latest_version():
    """Newest Windows release number, e.g. '97.0'."""
    errors = []
    for url in (BASE + "/latest-release.xml", BASE + "/latest-release.xml.gz"):
        try:
            with _open(url) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                import gzip
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8", "replace")
            m = re.search(r"<latest-windows-binary>.*?<version>\s*([\d.]+)\s*</version>", text, re.S) or \
                re.search(r"<version>\s*([\d.]+)\s*</version>", text)
            if m:
                return m.group(1)
        except Exception as e:  # noqa: BLE001 - try the next source
            errors.append(f"{url}: {e}")
    try:
        with _open(RELEASES) as r:
            html = r.read().decode("utf-8", "replace")
        versions = set(re.findall(r'href="(\d+\.\d+(?:\.\d+)?)/?"', html))
        if versions:
            return max(versions, key=_vkey)
    except Exception as e:  # noqa: BLE001
        errors.append(f"{RELEASES}: {e}")
    raise SetupError("Could not find the latest MKVToolNix version.\n" + "\n".join(errors))


def archive_url(version):
    return f"{RELEASES}{version}/mkvtoolnix-64-bit-{version}.7z"


def download(url, dest, progress=None, cancelled=None):
    """Stream url to dest. progress(done_bytes, total_bytes)."""
    tmp = str(dest) + ".part"
    try:
        with _open(url, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            last = 0.0
            while True:
                if cancelled and cancelled():
                    raise SetupError("Cancelled")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and time.time() - last > 0.1:
                    progress(done, total)
                    last = time.time()
        if total and done < total:
            raise SetupError("The download was cut off. Try again.")
        os.replace(tmp, dest)
    except SetupError:
        raise
    except Exception as e:  # noqa: BLE001
        raise SetupError(f"Download failed: {e}")
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def extract(archive, cancelled=None):
    """Unpack with the bundled 7-Zip and install into <data>/bin/mkvtoolnix. Returns that folder."""
    work = sub_dir("tmp") / "mkvtoolnix-unpack"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    proc = subprocess.Popen([str(sevenzip_exe()), "x", "-y", f"-o{work}", str(archive)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    while proc.poll() is None:
        if cancelled and cancelled():
            proc.kill()
            raise SetupError("Cancelled")
        time.sleep(0.2)
    out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
    if proc.returncode != 0:
        raise SetupError("Unpacking failed:\n" + out[-600:])
    found = None
    for root, _dirs, files in os.walk(work):
        if "mkvmerge.exe" in files:
            found = Path(root)
            break
    if not found:
        raise SetupError("mkvmerge.exe was not found in the downloaded archive.")
    target = data_dir() / "bin" / "mkvtoolnix"
    old = target.with_name("mkvtoolnix.old")
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        target.rename(old)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(found), str(target))
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    return target


def install(progress=None, cancelled=None, status=None):
    """Full flow. status(text) for messages, progress(done, total) during download. Returns install folder."""
    say = status or (lambda _t: None)
    say("Looking up the latest MKVToolNix version...")
    version = latest_version()
    say(f"Downloading MKVToolNix {version}...")
    archive = sub_dir("tmp") / f"mkvtoolnix-64-bit-{version}.7z"
    download(archive_url(version), archive, progress, cancelled)
    say(f"Unpacking MKVToolNix {version}...")
    try:
        folder = extract(archive, cancelled)
    finally:
        try:
            os.remove(archive)
        except OSError:
            pass
    return folder, version
