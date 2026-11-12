"""Batch multiplexing of episodes: pair external subtitles with episodes and apply language rules."""
import os
import re
from dataclasses import dataclass, field

from .languages import guess_from_filename, name_tail, normalize, parse_list
from .mediainfo import detect_text_charset

_EP_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})"),          # S01E02, s1e2, S01.E02
    re.compile(r"(?<!\d)(\d{1,2})[xX](\d{2,3})(?!\d)"),         # 1x02
    re.compile(r"(?<![A-Za-z])[Ee][Pp]?(\d{1,3})(?!\d)"),        # E02, Ep02 (not Se7en, Blade2)
    re.compile(r"(?:^|[ ._\-\[])(\d{2,3})(?:[ ._\-\]v]|$)"),     # " - 02 ", "[02]"
]


def episode_key(path: str):
    """'Show.S01E02.1080p.mkv' -> (1, 2); 'Show - 07.srt' -> (0, 7); None if no number found."""
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"(?i)(1080p|720p|2160p|480p|x26[45]|h\.?26[45]|10bit|ddp?\d\.\d|aac\d\.\d|5\.1|7\.1)", " ", name)
    for i, pat in enumerate(_EP_PATTERNS):
        m = pat.search(name)
        if m:
            if i < 2:
                return int(m.group(1)), int(m.group(2))
            return 0, int(m.group(1))
    return None


def _norm_base(path):
    return re.sub(r"[\W_]+", "", os.path.splitext(os.path.basename(path))[0].lower())


def match_subtitles(episodes, subs):
    """Return ({episode_path: [sub paths]}, [unmatched subs]). Episode number first, then file-name prefix."""
    result = {e: [] for e in episodes}
    keys = {}
    for e in episodes:
        k = episode_key(e)
        if k is not None:
            keys.setdefault(k, []).append(e)
    unmatched = []
    for s in subs:
        target = None
        sb = _norm_base(s)
        k = episode_key(s)
        # 1. exactly the same season and episode number (S01E10 never lands on S01E1)
        if k is not None and len(keys.get(k) or []) == 1:
            target = keys[k][0]
        # 2. same base name (Movie.mkv <- Movie.bg.srt); the longest match wins (Aliens.srt -> Aliens.mkv)
        if target is None:
            best = 0
            for e in episodes:
                eb = _norm_base(e)
                if eb and sb.startswith(eb) and len(eb) > best:
                    target, best = e, len(eb)
        # 3. same episode number (season 0 means "unknown season": match on episode only)
        if target is None and k is not None and not keys.get(k):
            cands = [e for ek, es in keys.items() for e in es
                     if ek[1] == k[1] and (ek[0] == 0 or k[0] == 0)]
            if len(cands) == 1:
                target = cands[0]
        if target is None:
            unmatched.append(s)
        else:
            result[target].append(s)
    return result, unmatched


AUDIO_EXTS = ("ac3", "eac3", "ec3", "aac", "m4a", "dts", "thd", "truehd", "mka", "flac", "opus", "ogg", "mp3",
              "mp2", "wav", "w64")
IMAGE_SUB_EXTS = (".sup", ".idx", ".sub")
_KIND_RE = [
    ("SDH", re.compile(r"(?i)(?<![a-z])(sdh|hi|hoh|hearing[ _-]?impaired|deaf)(?![a-z])")),
    ("CC", re.compile(r"(?i)(?<![a-z])(cc|closed[ _-]?captions?)(?![a-z])")),
    ("Signs", re.compile(r"(?i)(?<![a-z])(signs?|songs?|signs?[ _&+/-]*(and[ _-]*)?songs?)(?![a-z])")),
]


def is_sdh(t, path="", ref=""):
    """Subtitles the 'Remove SDH / CC / Signs' option targets. Returns '' or the kind: 'SDH', 'CC' or 'Signs'.
    Looks at the Matroska hearing-impaired flag, then the track name, then the subtitle file name,
    e.g. 'English SDH', 'English[CC]', 'English[Signs]', 'Signs & Songs', 'Show.S01E01.eng.sdh.srt'."""
    texts = [t.name or ""]
    if path:      # only the tags after the title: 'Hi.Score.Girl' and 'Love.Song' are not SDH / Signs
        texts.append(" ".join(name_tail(path, ref)))
    for text in texts:
        for kind, rx in _KIND_RE:
            if text and rx.search(text):
                return kind
    if t.props.get("flag_hearing_impaired"):
        return "SDH"
    return ""


def is_image_sub(t, path=""):
    """PGS (Blu-ray), VobSub (DVD) or DVB bitmap subtitles."""
    cid = t.codec_id or ""
    if cid.startswith(("S_HDMV/PGS", "S_VOBSUB", "S_DVBSUB")) or t.props.get("text_subtitles") is False:
        return True
    if path and os.path.splitext(path)[1].lower() in IMAGE_SUB_EXTS:
        return True
    return "PGS" in (t.codec or "") or "VobSub" in (t.codec or "")


def parse_nums(text):
    """'1, 3, 5-7' -> {1, 3, 5, 6, 7}"""
    out = set()
    for part in re.split(r"[,;\s]+", text or ""):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            if a.strip().isdigit() and b.strip().isdigit():
                lo, hi = sorted((int(a), int(b)))
                out.update(range(lo, hi + 1))
        elif part.isdigit():
            out.add(int(part))
    return out


@dataclass
class Rules:
    audio_keep: list = field(default_factory=lambda: ["bul", "eng"])   # empty = keep all; order = preference
    sub_keep: list = field(default_factory=lambda: ["bul", "eng"])
    keep_und: bool = True
    drop_embedded_subs: bool = False
    drop_sdh: bool = False
    drop_image_subs: bool = False
    one_sub_per_lang: bool = False
    ext_lang: str = "bul"                # language for added subs when the file name doesn't say
    ext_name: str = ""                   # track name for added subs ('' = none)
    ext_audio_lang: str = "bul"
    ext_audio_name: str = ""
    ext_audio_delay: int = 0             # ms, applied to added audio files
    audio_by_num: str = "off"            # off | keep | drop  (track numbers = position among the audio tracks)
    audio_nums: str = ""
    sub_by_num: str = "off"
    sub_nums: str = ""
    default_sub: str = "smart"           # smart | first | none
    reorder: bool = True
    fallback_charset: str = "cp1251"

    @classmethod
    def from_settings(cls, s):
        try:
            delay = int(str(s.batch_ext_audio_delay or 0).strip() or 0)
        except ValueError:
            delay = 0
        return cls(audio_keep=parse_list(s.batch_audio_keep), sub_keep=parse_list(s.batch_sub_keep),
                   keep_und=s.batch_keep_und, drop_embedded_subs=s.batch_drop_embedded_subs,
                   drop_sdh=s.batch_drop_sdh, drop_image_subs=s.batch_drop_image_subs,
                   one_sub_per_lang=s.batch_one_sub_per_lang,
                   ext_lang=normalize(s.batch_ext_lang or "bul"), ext_name=s.batch_ext_name,
                   ext_audio_lang=normalize(s.batch_ext_audio_lang or "bul"), ext_audio_name=s.batch_ext_audio_name,
                   ext_audio_delay=delay, audio_by_num=s.batch_audio_by_num, audio_nums=s.batch_audio_nums,
                   sub_by_num=s.batch_sub_by_num, sub_nums=s.batch_sub_nums, default_sub=s.batch_default_sub, reorder=s.batch_reorder,
                   fallback_charset=s.fallback_sub_charset or "cp1251")


def _rank(lang, prefs):
    return prefs.index(lang) if lang in prefs else len(prefs)


def track_key(source, track_id):
    return f"{source}:{track_id}"


def plan_episode(mf, ext, rules: Rules, output: str, overrides=None):
    """mf = MediaFile of the episode, ext = [(path, MediaFile)] added subtitle / audio files.
    overrides = {"source:track_id": True/False} manual keep/remove choices for this episode.
    Returns (mkvmerge spec, summary dict)."""
    notes = []
    overrides = overrides or {}

    def lang_ok(lang, prefs):
        if not prefs or lang in prefs:
            return True
        return rules.keep_und and lang == "und"

    by_num = {"audio": (rules.audio_by_num, parse_nums(rules.audio_nums)),
              "subtitles": (rules.sub_by_num, parse_nums(rules.sub_nums))}
    type_pos = {}
    rows = []   # [input_idx, track, decision dict, path]
    unused = []  # (input_idx, track): video etc. inside an added subtitle/audio file, never muxed
    for t in mf.tracks:
        type_pos[t.type] = type_pos.get(t.type, 0) + 1
        pos = type_pos[t.type]
        d = {"use": True, "language": t.language, "name": t.name, "default": t.default, "forced": t.forced,
             "external": False, "reason": "", "sdh": "", "image": False, "type_pos": pos}
        mode, nums = by_num.get(t.type, ("off", set()))
        if t.type == "subtitles":
            d["sdh"], d["image"] = is_sdh(t), is_image_sub(t)
        if t.type == "subtitles" and rules.drop_embedded_subs:
            d["use"], d["reason"] = False, "embedded subs off"
        elif mode == "keep" and nums:
            if pos not in nums:
                d["use"], d["reason"] = False, "track number"
        elif mode == "drop" and nums:
            if pos in nums:
                d["use"], d["reason"] = False, "track number"
        elif t.type == "audio" and not lang_ok(t.language, rules.audio_keep):
            d["use"], d["reason"] = False, "language"
        elif t.type == "subtitles" and not lang_ok(t.language, rules.sub_keep):
            d["use"], d["reason"] = False, "language"
        rows.append([0, t, d, mf.path])
    audio = [r for r in rows if r[1].type == "audio"]

    for i, (path, smf) in enumerate(ext, start=1):
        for t in smf.tracks:
            if t.type == "subtitles":
                d = {"use": True, "language": guess_from_filename(path, mf.path) or rules.ext_lang, "name": rules.ext_name,
                     "default": False, "forced": "forced" in [x.lower() for x in name_tail(path, mf.path)], "external": True, "reason": "",
                     "sdh": is_sdh(t, path, mf.path), "image": is_image_sub(t, path),
                     "charset": detect_text_charset(path, rules.fallback_charset)}
            elif t.type == "audio":
                lang = guess_from_filename(path, mf.path)
                if not lang or lang == "und":
                    lang = t.language if t.language != "und" else rules.ext_audio_lang
                d = {"use": True, "language": lang, "name": rules.ext_audio_name or t.name, "default": False,
                     "forced": False, "external": True, "reason": "", "sdh": "", "image": False,
                     "delay": rules.ext_audio_delay}
            else:
                unused.append((i, t))
                continue
            rows.append([i, t, d, path])

    # SDH / image subtitle filters (never remove the last subtitle of a language)
    subs = [r for r in rows if r[1].type == "subtitles"]
    for flag, enabled, why in (("sdh", rules.drop_sdh, "SDH"), ("image", rules.drop_image_subs, "PGS/image")):
        if not enabled:
            continue
        for lang in {r[2]["language"] for r in subs if r[2]["use"]}:
            same = [r for r in subs if r[2]["use"] and r[2]["language"] == lang]
            bad = [r for r in same if r[2][flag]]
            if bad and len(bad) == len(same):
                notes.append(f"kept {bad[0][2]['sdh'] if flag == 'sdh' else why} {lang}: it is the only {lang} subtitle")
                continue
            for r in bad:
                r[2]["use"], r[2]["reason"] = False, (r[2]["sdh"] if flag == "sdh" else why)

    # One subtitle per language (forced tracks are separate and kept)
    if rules.one_sub_per_lang:
        groups = {}
        for r in subs:
            if r[2]["use"] and not r[2]["forced"]:
                groups.setdefault(r[2]["language"], []).append(r)
        for lang, group in groups.items():
            if len(group) < 2:
                continue
            best = min(group, key=lambda r: (not r[2]["external"], r[2]["image"], bool(r[2]["sdh"]), rows.index(r)))
            for r in group:
                if r is not best:
                    r[2]["use"], r[2]["reason"] = False, f"duplicate {lang}"

    # Never end up without audio because of language rules
    if audio and not any(r[2]["use"] for r in rows if r[1].type == "audio"):
        for r in audio:
            r[2]["use"], r[2]["reason"] = True, ""
        notes.append("no audio in the kept languages, kept all audio")

    # Manual choices win over every rule
    for r in rows:
        k = track_key(r[0], r[1].id)
        if k in overrides and r[1].type in ("audio", "subtitles", "video"):
            r[2]["use"] = bool(overrides[k])
            r[2]["reason"] = "by you"
            r[2]["manual"] = True
    if audio and not any(r[2]["use"] for r in rows if r[1].type == "audio"):
        notes.append("no audio left!")

    used = lambda kind: [r for r in rows if r[1].type == kind and r[2]["use"]]  # noqa: E731

    # Default audio: first by preference order, added dub wins a tie
    ua = used("audio")
    if ua:
        best = min(ua, key=lambda r: (_rank(r[2]["language"], rules.audio_keep), not r[2]["external"], rows.index(r)))
        for r in ua:
            r[2]["default"] = r is best
    default_audio_lang = next((r[2]["language"] for r in ua if r[2]["default"]), None)

    # Default subtitle
    us = [r for r in used("subtitles") if not r[2]["forced"]]
    for r in used("subtitles"):
        r[2]["default"] = False
    if us and rules.default_sub != "none":
        best = min(us, key=lambda r: (_rank(r[2]["language"], rules.sub_keep), not r[2]["external"], rows.index(r)))
        # Smart: no default subtitle when the default audio is already in a language you prefer at least as
        # much as the best subtitle (Bulgarian audio + "bul, eng" subtitles -> no subtitle on by default)
        skip = (rules.default_sub == "smart" and default_audio_lang is not None
                and (default_audio_lang == best[2]["language"]
                     or (default_audio_lang in rules.sub_keep
                         and _rank(default_audio_lang, rules.sub_keep) <= _rank(best[2]["language"], rules.sub_keep))))
        if not skip:
            best[2]["default"] = True
    uv = used("video")
    for j, r in enumerate(uv):
        r[2]["default"] = j == 0

    # Order: video, audio, subtitles, other; by language preference, added subs before embedded
    if rules.reorder:
        type_rank = {"video": 0, "audio": 1, "subtitles": 2}

        def key(r):
            ty = r[1].type
            prefs = rules.audio_keep if ty == "audio" else rules.sub_keep
            lang_rank = _rank(r[2]["language"], prefs) if ty in ("audio", "subtitles") else 0
            return (type_rank.get(ty, 3), lang_rank, not r[2]["external"], rows.index(r))
        ordered = sorted(rows, key=key)
    else:
        ordered = rows

    inputs = [{"path": mf.path, "tracks": [], "chapters": True, "tags": True}]
    inputs += [{"path": p, "tracks": [], "chapters": False} for p, _ in ext]
    for idx, t in unused:
        inputs[idx]["tracks"].append({"id": t.id, "type": t.type, "use": False})
    for idx, t, d, _p in rows:
        entry = {"id": t.id, "type": t.type, "use": d["use"], "language": d["language"], "name": d["name"],
                 "default": d["default"], "forced": d["forced"]}
        if d.get("charset"):
            entry["charset"] = d["charset"]
        if d.get("delay"):
            entry["delay"] = d["delay"]
        inputs[idx]["tracks"].append(entry)
    spec = {"output": output, "title": mf.title, "inputs": inputs, "attach_files": [],
            "track_order": [[idx, t.id] for idx, t, d, _p in ordered if d["use"]]}

    def describe(kind):
        out = []
        for idx, t, d, _p in ordered:
            if t.type == kind and d["use"]:
                tag = d["language"] + ("+" if d["external"] else "") + ("*" if d["default"] else "") + \
                      ("(f)" if d["forced"] else "")
                out.append(tag)
        return out
    dropped = sum(1 for _, t, d, _p in rows if not d["use"])
    position = {}
    n = 0
    for idx, t, d, _p in ordered:
        if d["use"]:
            n += 1
            position[(idx, t.id)] = n
    tracks = []
    for idx, t, d, _p in rows:
        tracks.append({"source": idx, "path": inputs[idx]["path"], "track": t, "use": d["use"],
                       "external": d["external"], "language": d["language"], "name": d["name"],
                       "default": d["default"], "forced": d["forced"], "charset": d.get("charset", ""),
                       "delay": d.get("delay", 0), "reason": d.get("reason", ""), "sdh": d["sdh"],
                       "image": d["image"], "manual": d.get("manual", False), "key": track_key(idx, t.id),
                       "type_pos": d.get("type_pos", 0),
                       "position": position.get((idx, t.id))})
    summary = {"audio": describe("audio"), "subs": describe("subtitles"), "dropped": dropped, "notes": notes,
               "tracks": tracks}
    return spec, summary
