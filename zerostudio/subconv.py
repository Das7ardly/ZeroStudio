"""Detect subtitle text encodings and convert files to UTF-8."""
import codecs
import os
import shutil

SUB_EXTS = ("srt", "ass", "ssa", "sub", "txt", "vtt", "smi", "sami", "usf", "lrc")
CANDIDATES = ["cp1251", "cp1252", "cp1250", "koi8_r", "iso8859_5", "cp866", "iso8859_2", "cp1253", "cp1254",
              "iso8859_1"]
ENCODINGS = ["utf-8", "utf-8-sig", "utf-16"] + CANDIDATES
LABELS = {"utf-8": "UTF-8", "utf-8-sig": "UTF-8 (BOM)", "utf-16": "UTF-16", "cp1251": "Windows-1251 (Cyrillic)",
          "cp1252": "Windows-1252 (Western)", "cp1250": "Windows-1250 (Central Europe)", "koi8_r": "KOI8-R",
          "iso8859_5": "ISO-8859-5 (Cyrillic)", "cp866": "DOS 866 (Cyrillic)", "iso8859_2": "ISO-8859-2",
          "cp1253": "Windows-1253 (Greek)", "cp1254": "Windows-1254 (Turkish)", "iso8859_1": "ISO-8859-1"}

_CYR_COMMON = set("оаеинтсрвлкдмпуяъбзгчжйхшцщюьфыэё")
_LAT_ACCENTS = set("áéíóúàèìòùäöüßçñãõâêîôûåæøčšžćđłńśźżőűěřůýťďňĺľŕëïœÿ")
_GREEK = set("αβγδεζηθικλμνξοπρστυφχψωάέήίόύώ")
_TURK = set("çğıöşüİ")


def _is_ascii_letter(ch):
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _non_latin(ch):
    o = ord(ch)
    return 0x0370 <= o <= 0x052F      # Greek + Cyrillic


def _score(text):
    """Higher = more plausible natural-language text. Only non-ASCII characters matter.
    Mixing Latin and Greek/Cyrillic letters inside one word is heavily penalised: that is what a wrong
    code page produces (e.g. German 'f\u00fcr' read as Greek)."""
    s = 0
    n = len(text)
    for i, ch in enumerate(text):
        if ord(ch) < 128:
            continue
        if _non_latin(ch) and ((i > 0 and _is_ascii_letter(text[i - 1])) or
                               (i + 1 < n and _is_ascii_letter(text[i + 1]))):
            s -= 4
            continue
        if ch in _CYR_COMMON or ch in _LAT_ACCENTS or ch in _GREEK or ch in _TURK:
            s += 3
        elif ch.isalpha() and ch.islower():
            s += 1
        elif ch.isalpha():
            s += 0.3        # stray capitals are typical of a wrong code page
        elif ch in "\u2013\u2014\u2026\u201c\u201d\u201e\u2018\u2019\u00ab\u00bb\u00a0\u2116":
            s += 1
        else:
            s -= 3          # box drawing, symbols, control chars
    return s


def detect(raw: bytes, fallback="cp1251"):
    """Return (encoding, note). note explains how sure we are."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", "UTF-8 with BOM"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16", "UTF-16 with BOM"
    sample = raw[:400_000]
    if sample and sample.count(b"\x00") > len(sample) // 4:
        enc = "utf-16-le" if sample[1:2] == b"\x00" else "utf-16-be"
        return enc, "UTF-16 without BOM"
    try:      # not final: raw can be the first 2 MB of a file and stop inside a character
        codecs.getincrementaldecoder("utf-8")().decode(raw, final=False)
        return "utf-8", "already UTF-8" if any(b > 127 for b in sample) else "plain ASCII"
    except UnicodeDecodeError:
        pass
    order = [fallback] + [c for c in CANDIDATES if c != fallback] if fallback in CANDIDATES else list(CANDIDATES)
    best, best_score = None, None
    for enc in order:
        try:
            text = sample.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        sc = _score(text)
        if best_score is None or sc > best_score + 0.5:   # ties keep the earlier (preferred) one
            best, best_score = enc, sc
    return (best or fallback), "guessed"


def read(path, limit=None):
    with open(path, "rb") as f:
        return f.read() if limit is None else f.read(limit)


def decode(raw, enc):
    return raw.decode(enc, errors="replace")


def is_utf8(enc):
    return enc in ("utf-8", "utf-8-sig")


def convert(path, enc, mode="replace_backup", bom=False, out_dir="", suffix=".utf8"):
    """Write the file as UTF-8. mode: replace_backup | replace | new | folder. Returns the written path."""
    raw = read(path)
    text = raw.decode(enc, errors="strict")
    if text.startswith("﻿"):
        text = text[1:]
    data = (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")
    root, ext = os.path.splitext(path)
    if mode in ("replace", "replace_backup"):
        if mode == "replace_backup":
            bak = path + ".bak"
            if not os.path.exists(bak):
                shutil.copy2(path, bak)
        target = path
    elif mode == "folder":
        os.makedirs(out_dir, exist_ok=True)
        target = os.path.join(out_dir, os.path.basename(path))
    else:
        target = root + suffix + ext
    tmp = target + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, target)
    return target
