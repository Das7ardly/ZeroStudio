"""Shared text for showing what is inside a media file (tracks, attachments, chapters, tags)."""
from ..mediainfo import file_size_text

TYPE_NAME = {"video": "Video", "audio": "Audio", "subtitles": "Subtitles", "buttons": "Buttons"}


def track_title(t):
    s = f"Track {t.id}  {TYPE_NAME.get(t.type, t.type)}  [{t.language}]"
    return s + (f"  “{t.name}”" if t.name else "")


def track_flags(t):
    flags = []
    if t.default:
        flags.append("default")
    if t.forced:
        flags.append("forced")
    if not t.enabled:
        flags.append("disabled")
    return flags


def track_detail(t):
    det = t.details()
    flags = track_flags(t)
    return f"{t.codec}" + (f"  ·  {det}" if det else "") + (f"  ({', '.join(flags)})" if flags else "")


def track_tooltip(t):
    p = t.props
    lines = [track_title(t), f"Codec: {t.codec}  ({t.codec_id or '?'})"]
    for key, label in (("pixel_dimensions", "Resolution"), ("display_dimensions", "Display size"),
                       ("audio_channels", "Channels"), ("audio_sampling_frequency", "Sample rate"),
                       ("audio_bits_per_sample", "Bits"), ("encoding", "Text encoding"),
                       ("language_ietf", "Language (IETF)"), ("number", "Track number")):
        if p.get(key) not in (None, ""):
            lines.append(f"{label}: {p[key]}")
    flags = track_flags(t)
    if flags:
        lines.append("Flags: " + ", ".join(flags))
    return "\n".join(lines)


def attachment_title(a):
    return f"Attachment {a.id}  {a.file_name}"


def attachment_detail(a):
    return f"{a.mime}, {file_size_text(a.size)}" + (f"  {a.description}" if a.description else "")


def file_summary(mf, size=None):
    bits = [mf.container]
    n = len(mf.tracks)
    if n:
        bits.append(f"{n} track{'s' if n != 1 else ''}")
    if mf.duration_text():
        bits.append(mf.duration_text())
    if size is not None:
        bits.append(file_size_text(size))
    if mf.title:
        bits.append(f"title “{mf.title}”")
    return "  ·  ".join(bits)
