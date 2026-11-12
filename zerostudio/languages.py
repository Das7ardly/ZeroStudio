"""Common language codes (ISO 639-2/B as used by Matroska) plus lookup helpers."""
import re

# (639-2/B, 639-1, English name)
LANGS = [
    ("und", "", "Undetermined"), ("bul", "bg", "Bulgarian"), ("eng", "en", "English"),
    ("rus", "ru", "Russian"), ("ukr", "uk", "Ukrainian"), ("srp", "sr", "Serbian"), ("hrv", "hr", "Croatian"),
    ("bos", "bs", "Bosnian"), ("slv", "sl", "Slovenian"), ("mac", "mk", "Macedonian"), ("gre", "el", "Greek"),
    ("tur", "tr", "Turkish"), ("rum", "ro", "Romanian"), ("hun", "hu", "Hungarian"), ("cze", "cs", "Czech"),
    ("slo", "sk", "Slovak"), ("pol", "pl", "Polish"), ("ger", "de", "German"), ("fre", "fr", "French"),
    ("spa", "es", "Spanish"), ("ita", "it", "Italian"), ("por", "pt", "Portuguese"), ("dut", "nl", "Dutch"),
    ("swe", "sv", "Swedish"), ("nor", "no", "Norwegian"), ("nob", "nb", "Norwegian Bokmal"),
    ("dan", "da", "Danish"), ("fin", "fi", "Finnish"), ("ice", "is", "Icelandic"), ("est", "et", "Estonian"),
    ("lav", "lv", "Latvian"), ("lit", "lt", "Lithuanian"), ("alb", "sq", "Albanian"), ("arm", "hy", "Armenian"),
    ("geo", "ka", "Georgian"), ("aze", "az", "Azerbaijani"), ("kaz", "kk", "Kazakh"), ("bel", "be", "Belarusian"),
    ("heb", "he", "Hebrew"), ("ara", "ar", "Arabic"), ("per", "fa", "Persian"), ("urd", "ur", "Urdu"),
    ("hin", "hi", "Hindi"), ("ben", "bn", "Bengali"), ("tam", "ta", "Tamil"), ("tel", "te", "Telugu"),
    ("mal", "ml", "Malayalam"), ("kan", "kn", "Kannada"), ("mar", "mr", "Marathi"), ("pan", "pa", "Punjabi"),
    ("guj", "gu", "Gujarati"), ("tha", "th", "Thai"), ("vie", "vi", "Vietnamese"), ("ind", "id", "Indonesian"),
    ("may", "ms", "Malay"), ("fil", "", "Filipino"), ("tgl", "tl", "Tagalog"), ("chi", "zh", "Chinese"),
    ("jpn", "ja", "Japanese"), ("kor", "ko", "Korean"), ("mon", "mn", "Mongolian"), ("cat", "ca", "Catalan"),
    ("baq", "eu", "Basque"), ("glg", "gl", "Galician"), ("wel", "cy", "Welsh"), ("gle", "ga", "Irish"),
    ("lat", "la", "Latin"), ("epo", "eo", "Esperanto"), ("afr", "af", "Afrikaans"), ("swa", "sw", "Swahili"),
    ("amh", "am", "Amharic"), ("zul", "zu", "Zulu"), ("yid", "yi", "Yiddish"), ("mul", "", "Multiple languages"),
    ("zxx", "", "No linguistic content"),
]
ALIASES = {"deu": "ger", "fra": "fre", "ces": "cze", "slk": "slo", "nld": "dut", "ell": "gre", "ron": "rum",
           "zho": "chi", "fas": "per", "hye": "arm", "kat": "geo", "sqi": "alb", "isl": "ice", "mkd": "mac",
           "msa": "may", "eus": "baq", "cym": "wel", "iw": "he", "in": "id"}

BY_CODE = {c: n for c, _, n in LANGS}
_LOOKUP = {}
for c3, c1, name in LANGS:
    _LOOKUP[c3] = c3
    if c1:
        _LOOKUP[c1] = c3
    _LOOKUP[name.lower()] = c3
for a, c in ALIASES.items():
    _LOOKUP[a] = _LOOKUP.get(c, c)
_LOOKUP.update({"bg": "bul", "bgr": "bul", "en": "eng", "pt-br": "por", "ptbr": "por", "esla": "spa"})


def normalize(code: str) -> str:
    """Map 'bg', 'bul', 'Bulgarian', 'en-US' to a 3-letter code. Unknown values are returned cleaned."""
    if not code:
        return "und"
    c = code.strip().lower()
    if c in _LOOKUP:
        return _LOOKUP[c]
    base = re.split(r"[-_]", c)[0]
    return _LOOKUP.get(base, c)


def is_known(code: str) -> bool:
    return normalize(code) in BY_CODE


def display(code: str) -> str:
    c = normalize(code)
    name = BY_CODE.get(c)
    return f"{c} - {name}" if name else c


def parse_list(text: str):
    return [normalize(t) for t in re.split(r"[,;\s]+", text or "") if t.strip()]


_SPLIT = re.compile(r"[.\s_\-\[\]()]+")
_MARKER = re.compile(r"(?i)(?<![a-z0-9])(?:s\d{1,2}[ ._-]*e\d{1,3}(?:[-e]+\d{1,3})*|\d{1,2}x\d{2,3}|ep?\d{1,3})(?![a-z0-9])")
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_AMBIGUOUS = ("in", "is", "it", "no", "am", "be", "ca", "id", "la", "ms")
MODIFIERS = ("forced", "sdh", "cc", "hi", "hoh", "default", "full", "signs", "songs")


def _lang_token(tok):
    t = tok.lower()
    if len(t) >= 2 and t in _LOOKUP and t not in _AMBIGUOUS:
        return _LOOKUP[t]
    return None


def name_tail(path: str, ref: str = ""):
    """The part of a subtitle/audio file name that can carry tags (language, SDH, forced), without the title.
    Words of the title must never count: 'La.Casa.de.Papel' is not German, 'Hi.Score.Girl' is not SDH.
    Returns the list of tokens after, in this order of preference: the video's own name (ref), the episode
    marker (S01E02, 1x02, E02), the year; otherwise only the trailing tokens that are tags themselves."""
    import os
    stem = os.path.splitext(os.path.basename(path))[0]
    if ref:
        rstem = os.path.splitext(os.path.basename(ref))[0]
        if rstem and stem.lower().startswith(rstem.lower()):
            return [t for t in _SPLIT.split(stem[len(rstem):]) if t]
    m = _MARKER.search(stem)
    if m:
        return [t for t in _SPLIT.split(stem[m.end():]) if t]
    years = list(_YEAR.finditer(stem))
    if years and years[-1].start() > 0:
        return [t for t in _SPLIT.split(stem[years[-1].end():]) if t]
    tokens = [t for t in _SPLIT.split(stem) if t]
    tail = []
    for tok in reversed(tokens[1:]):
        if tok.lower() in MODIFIERS or _lang_token(tok):
            tail.insert(0, tok)
        else:
            break
    return tail


def guess_from_filename(path: str, ref: str = ""):
    """'Movie.bg.srt' -> 'bul', 'Movie [English].ass' -> 'eng', 'Show.S01E02.eng.forced.srt' -> 'eng'.
    Only tags count, never words of the title (see name_tail). ref = the video file this one belongs to."""
    tail = name_tail(path, ref)
    for skip_hi in (True, False):      # 'en.hi' = English SDH; a lone 'hi' = Hindi
        for tok in reversed(tail):
            if skip_hi and tok.lower() == "hi":
                continue
            lang = _lang_token(tok)
            if lang:
                return lang
    return None
