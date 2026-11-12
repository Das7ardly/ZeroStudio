"""Read file structure with `mkvmerge -J` and helpers for naming extracted files."""
import codecs
import json
import os
import re
import subprocess
from dataclasses import dataclass, field

from .engine import NO_WINDOW, child_env
from . import subconv
from .languages import normalize

CODEC_EXT = {
    "V_MPEG4/ISO/AVC": "h264", "V_MPEGH/ISO/HEVC": "h265", "V_MPEGI/ISO/VVC": "h266", "V_AV1": "ivf",
    "V_VP8": "ivf", "V_VP9": "ivf", "V_MPEG1": "mpg", "V_MPEG2": "mpg", "V_MPEG4/ISO/SP": "m4v",
    "V_MPEG4/ISO/ASP": "m4v", "V_MPEG4/ISO/AP": "m4v", "V_MS/VFW/FOURCC": "avi", "V_THEORA": "ogv",
    "V_REAL": "rm", "V_PRORES": "mov", "V_UNCOMPRESSED": "raw",
    "A_AAC": "aac", "A_AC3": "ac3", "A_EAC3": "eac3", "A_DTS": "dts", "A_TRUEHD": "thd", "A_MLP": "mlp",
    "A_FLAC": "flac", "A_OPUS": "opus", "A_VORBIS": "ogg", "A_MPEG/L3": "mp3", "A_MPEG/L2": "mp2",
    "A_MPEG/L1": "mp1", "A_ALAC": "caf", "A_TTA1": "tta", "A_WAVPACK4": "wv", "A_REAL": "ra", "A_MS/ACM": "wav",
    "S_TEXT/UTF8": "srt", "S_TEXT/ASCII": "srt", "S_TEXT/ASS": "ass", "S_TEXT/SSA": "ssa", "S_ASS": "ass",
    "S_SSA": "ssa", "S_TEXT/USF": "usf", "S_TEXT/WEBVTT": "vtt", "S_VOBSUB": "sub", "S_HDMV/PGS": "sup",
    "S_HDMV/TEXTST": "textst", "S_KATE": "ogg", "S_DVBSUB": "dvbsub",
}
TEXT_SUB_EXTS = {".srt", ".ass", ".ssa", ".sub", ".txt", ".vtt", ".usf", ".smi"}


# Fallback when mkvmerge reports no codec_id (some non-Matroska readers): match on the codec name
CODEC_NAME_EXT = [
    ("hevc", "h265"), ("h.265", "h265"), ("avc", "h264"), ("h.264", "h264"), ("vvc", "h266"), ("av1", "ivf"),
    ("vp9", "ivf"), ("vp8", "ivf"), ("mpeg-1/2", "mpg"), ("mpeg-4p2", "m4v"), ("xvid", "m4v"), ("divx", "m4v"),
    ("e-ac-3", "eac3"), ("ac-3", "ac3"), ("truehd", "thd"), ("dts", "dts"), ("aac", "aac"), ("flac", "flac"),
    ("opus", "opus"), ("vorbis", "ogg"), ("mp3", "mp3"), ("mp2", "mp2"), ("pcm", "wav"), ("alac", "caf"),
    ("subrip", "srt"), ("srt", "srt"), ("timed text", "srt"), ("substation", "ass"), ("ass", "ass"),
    ("webvtt", "vtt"), ("vobsub", "sub"), ("pgs", "sup"), ("dvb", "dvbsub"),
]


def codec_ext(codec_id: str, kind: str, codec: str = "") -> str:
    if not codec_id and codec:
        low = codec.lower()
        for key, ext in CODEC_NAME_EXT:
            if key in low:
                return ext
    if codec_id in CODEC_EXT:
        return CODEC_EXT[codec_id]
    for k, v in CODEC_EXT.items():
        if codec_id.startswith(k):
            return v
    if codec_id.startswith("A_PCM"):
        return "wav"
    if codec_id.startswith("A_AAC"):
        return "aac"
    return {"video": "bin", "audio": "bin", "subtitles": "sub"}.get(kind, "bin")


@dataclass
class Track:
    id: int
    type: str
    codec: str
    codec_id: str = ""
    language: str = "und"
    name: str = ""
    default: bool = False
    forced: bool = False
    enabled: bool = True
    number: int = 0
    props: dict = field(default_factory=dict)

    @property
    def ext(self):
        return codec_ext(self.codec_id, self.type, self.codec)

    @property
    def has_cues(self):
        return self.props.get("num_index_entries", 0) > 0

    def details(self):
        p = self.props
        if self.type == "video":
            bits = [p.get("pixel_dimensions", "")]
            dd = p.get("default_duration")
            if dd:
                bits.append(f"{1e9 / dd:.3f}".rstrip("0").rstrip(".") + " fps")
            return " ".join(b for b in bits if b)
        if self.type == "audio":
            ch = p.get("audio_channels")
            hz = p.get("audio_sampling_frequency")
            out = []
            if ch:
                out.append({1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(ch, f"{ch}ch"))
            if hz:
                out.append(f"{hz / 1000:g} kHz")
            return ", ".join(out)
        if self.type == "subtitles":
            return p.get("encoding", "") if p.get("text_subtitles") else "bitmap"
        return ""


@dataclass
class Attachment:
    id: int
    file_name: str
    mime: str
    size: int
    description: str = ""


@dataclass
class MediaFile:
    path: str
    container: str = ""
    title: str = ""
    duration_ns: int = 0
    tracks: list = field(default_factory=list)
    attachments: list = field(default_factory=list)
    chapters: int = 0
    global_tags: int = 0
    track_tags: int = 0
    is_matroska: bool = False
    warnings: list = field(default_factory=list)

    @property
    def base(self):
        return os.path.splitext(os.path.basename(self.path))[0]

    def duration_text(self):
        s = int(self.duration_ns / 1e9) if self.duration_ns else 0
        if not s:
            return ""
        return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"

    def layout(self):
        """Track-type signature used to match files with the same structure."""
        return tuple(t.type for t in self.tracks)


class IdentifyError(Exception):
    pass


def parse_identify(data: dict, path: str) -> MediaFile:
    c = data.get("container", {}) or {}
    if not c.get("recognized", False):
        raise IdentifyError("Unrecognised file format")
    if not c.get("supported", True):
        raise IdentifyError("File format is recognised but not supported by mkvmerge")
    cp = c.get("properties", {}) or {}
    mf = MediaFile(path=path, container=c.get("type", ""), title=cp.get("title", "") or "",
                   duration_ns=cp.get("duration", 0) or 0, is_matroska=c.get("type") in ("Matroska", "WebM"))
    for t in data.get("tracks", []):
        p = t.get("properties", {}) or {}
        mf.tracks.append(Track(
            id=t["id"], type=t.get("type", ""), codec=t.get("codec", ""), codec_id=p.get("codec_id", ""),
            language=normalize(p.get("language", "und") or "und"), name=p.get("track_name", "") or "",
            default=bool(p.get("default_track", False)), forced=bool(p.get("forced_track", False)),
            enabled=bool(p.get("enabled_track", True)), number=p.get("number", 0) or 0, props=p))
    for a in data.get("attachments", []):
        mf.attachments.append(Attachment(id=a["id"], file_name=a.get("file_name", f"attachment{a['id']}"),
                                         mime=a.get("content_type", ""), size=a.get("size", 0),
                                         description=a.get("description", "") or ""))
    mf.chapters = sum(x.get("num_entries", 0) for x in data.get("chapters", []))
    mf.global_tags = sum(x.get("num_entries", 0) for x in data.get("global_tags", []))
    mf.track_tags = sum(x.get("num_entries", 0) for x in data.get("track_tags", []))
    mf.warnings = list(data.get("warnings", []))
    return mf


def identify(mkvmerge: str, path: str) -> MediaFile:
    try:
        r = subprocess.run([mkvmerge, "-J", path], capture_output=True, timeout=120,
                           creationflags=NO_WINDOW, env=child_env())
    except subprocess.TimeoutExpired:
        raise IdentifyError("mkvmerge timed out reading the file")
    except OSError as e:
        raise IdentifyError(f"Could not run mkvmerge: {e}")
    try:
        data = json.loads(r.stdout.decode("utf-8", errors="replace"))
    except ValueError:
        raise IdentifyError((r.stdout + r.stderr).decode("utf-8", "replace").strip()[:300] or "No output")
    if data.get("errors"):
        raise IdentifyError("; ".join(data["errors"]))
    return parse_identify(data, path)


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(s: str) -> str:
    s = _BAD.sub("_", s).strip().rstrip(".")
    return s or "_"


def render_template(template: str, mf: MediaFile, track: Track) -> str:
    vals = {
        "base": mf.base, "id": track.id, "num": track.number, "type": track.type, "lang": track.language,
        "name": track.name, "codec": track.codec.split("/")[0], "title": mf.title,
    }
    try:
        out = template.format(**vals)
    except (KeyError, IndexError, ValueError):
        out = "{base}_track{id}_[{lang}]".format(**vals)
    out = re.sub(r"\[\s*\]|\(\s*\)", "", out).strip(" _-.")
    return safe_name(out) + "." + track.ext


def file_size_text(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


ICONV_NAME = {"cp1251": "cp1251", "cp1252": "cp1252", "cp1250": "cp1250", "cp1253": "cp1253", "cp1254": "cp1254",
              "koi8_r": "KOI8-R", "iso8859_5": "ISO-8859-5", "cp866": "CP866", "iso8859_2": "ISO-8859-2",
              "iso8859_1": "ISO-8859-1", "utf-16-le": "UTF-16LE", "utf-16-be": "UTF-16BE"}


def detect_text_charset(path: str, fallback: str) -> str:
    """'' if the subtitle file is UTF-8 (or not a text sub), else its code page as mkvmerge wants it.
    The code page is detected from the text; the fallback wins ties and is used as is when it is not one
    of the code pages ZeroStudio can tell apart (e.g. Big5)."""
    if os.path.splitext(path)[1].lower() not in TEXT_SUB_EXTS:
        return ""
    try:
        with open(path, "rb") as f:
            raw = f.read(2_000_000)
    except OSError:
        return ""
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        return ""
    if is_utf8_bytes(raw):
        return ""
    try:
        pref = codecs.lookup(fallback).name.replace("-", "_")
    except LookupError:
        return fallback
    if pref not in subconv.CANDIDATES:
        return fallback
    enc, _note = subconv.detect(raw, pref)
    return fallback if enc == pref else ICONV_NAME.get(enc, fallback)


def is_utf8_bytes(raw: bytes) -> bool:
    """True if raw is valid UTF-8. raw may be the first part of a bigger file, so an unfinished character
    at the very end is fine (a 2 MB sample often stops in the middle of a Cyrillic letter)."""
    try:
        codecs.getincrementaldecoder("utf-8")().decode(raw, final=False)
        return True
    except UnicodeDecodeError:
        return False
