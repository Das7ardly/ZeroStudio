"""Pure functions that turn a job spec (plain dicts) into MKVToolNix arguments.

Arguments are written to a UTF-8 JSON option file and passed as `@file.json`, which keeps
non-ASCII file names and titles safe on every Windows code page.
"""
import os

TYPE_FLAGS = {
    "video": ("--video-tracks", "--no-video"),
    "audio": ("--audio-tracks", "--no-audio"),
    "subtitles": ("--subtitle-tracks", "--no-subtitles"),
    "buttons": ("--button-tracks", "--no-buttons"),
}


def build_mux_args(spec: dict) -> list:
    """spec = {output, title, chapters_file, split, attach_files, track_order, inputs:[{path, append,
    tracks:[{id,type,use,language,name,default,forced,delay,charset}], attachments:[{id,use}],
    chapters, tags}]}"""
    a = ["--gui-mode", "-o", spec["output"]]
    if spec.get("title") is not None:
        a += ["--title", spec["title"]]
    if spec.get("chapters_file"):
        a += ["--chapters", spec["chapters_file"]]
    if spec.get("split"):
        a += ["--split", spec["split"]]
    for f in spec.get("attach_files", []):
        a += ["--attach-file", f]

    for inp in spec["inputs"]:
        tracks = inp.get("tracks", [])
        # Track selection per type
        for ttype, (sel, none) in TYPE_FLAGS.items():
            of_type = [t for t in tracks if t["type"] == ttype]
            if not of_type:
                continue
            used = [t for t in of_type if t.get("use", True)]
            if not used:
                a.append(none)
            elif len(used) != len(of_type):
                a += [sel, ",".join(str(t["id"]) for t in used)]
        for t in tracks:
            if not t.get("use", True):
                continue
            tid = t["id"]
            if t.get("language"):
                a += ["--language", f"{tid}:{t['language']}"]
            if t.get("name") is not None:
                a += ["--track-name", f"{tid}:{t['name']}"]
            if "default" in t:
                a += ["--default-track-flag", f"{tid}:{1 if t['default'] else 0}"]
            if "forced" in t:
                a += ["--forced-display-flag", f"{tid}:{1 if t['forced'] else 0}"]
            if t.get("delay"):
                a += ["--sync", f"{tid}:{int(t['delay'])}"]
            if t.get("charset") and t["type"] == "subtitles":
                a += ["--sub-charset", f"{tid}:{t['charset']}"]
        atts = inp.get("attachments", [])
        if atts:
            used = [x for x in atts if x.get("use", True)]
            if not used:
                a.append("--no-attachments")
            elif len(used) != len(atts):
                a += ["--attachments", ",".join(str(x["id"]) for x in used)]
        if not inp.get("chapters", True):
            a.append("--no-chapters")
        if not inp.get("tags", True):
            a += ["--no-global-tags", "--no-track-tags"]
        if inp.get("append"):
            a.append("+")
        a.append(inp["path"])

    order = spec.get("track_order")
    if order:
        a += ["--track-order", ",".join(f"{fi}:{tid}" for fi, tid in order)]
    return a


def build_extract_args(spec: dict) -> list:
    """spec = {path, tracks:[{id, file, timestamps(file|''), cues(file|'')}], attachments:[{id,file}],
    chapters(file|''), chapters_simple, tags(file|''), cuesheet(file|'')}"""
    a = [spec["path"]]
    tracks = spec.get("tracks", [])
    if tracks:
        a.append("tracks")
        a += [f"{t['id']}:{t['file']}" for t in tracks]
    ts = [t for t in tracks if t.get("timestamps")]
    if ts:
        a.append("timestamps_v2")
        a += [f"{t['id']}:{t['timestamps']}" for t in ts]
    if spec.get("attachments"):
        a.append("attachments")
        a += [f"{x['id']}:{x['file']}" for x in spec["attachments"]]
    if spec.get("chapters"):
        a.append("chapters")
        if spec.get("chapters_simple"):
            a.append("--simple")
        a.append(spec["chapters"])
    if spec.get("tags"):
        a += ["tags", spec["tags"]]
    if spec.get("cuesheet"):
        a += ["cuesheet", spec["cuesheet"]]
    cues = [t for t in tracks if t.get("cues")]
    if cues:  # last: mkvextract stops at the first failing mode
        a.append("cues")
        a += [f"{t['id']}:{t['cues']}" for t in cues]
    a.append("--gui-mode")
    return a


def build_extract_remux(path: str, temp: str, tracks: list, keep_ids: list, chapters: bool, tags: bool):
    """mkvextract only reads Matroska. For MP4/AVI/TS/... ZeroStudio first copies the wanted tracks into a temp
    MKV (stream copy, no re-encode) and extracts from that.
    tracks = [(id, type)] of the source in order; keep_ids = source IDs to keep, in extract order.
    Returns (mkvmerge args, {source id: id in the temp file})."""
    keep = [i for i in keep_ids if any(t[0] == i for t in tracks)]
    if not keep and tracks:      # chapters/tags only: mkvmerge still needs one track to write a file
        keep = [tracks[0][0]]
    a = ["--gui-mode", "-o", temp, "--no-attachments"]
    types = {tid: ttype for tid, ttype in tracks}
    for ttype, (sel, none) in TYPE_FLAGS.items():
        if not any(tt == ttype for tt in types.values()):
            continue
        ids = [i for i in keep if types[i] == ttype]
        a += [sel, ",".join(map(str, ids))] if ids else [none]
    if not chapters:
        a.append("--no-chapters")
    if not tags:
        a += ["--no-global-tags", "--no-track-tags"]
    a.append(path)
    if keep:
        a += ["--track-order", ",".join(f"0:{i}" for i in keep)]
    return a, {old: new for new, old in enumerate(keep)}


def build_propedit_args(spec: dict) -> list:
    """spec = {path, title (None = unchanged), tracks:[{number, language, name, default, forced, enabled}],
    delete_attachments:[ids], add_attachments:[paths]}"""
    a = [spec["path"], "--gui-mode"]
    if spec.get("title") is not None:
        a += ["--edit", "info"]
        a += ["--set", f"title={spec['title']}"] if spec["title"] else ["--delete", "title"]
    for t in spec.get("tracks", []):
        a += ["--edit", f"track:@{t['number']}"]
        if t.get("language"):
            a += ["--set", f"language={t['language']}"]
        if "name" in t:
            a += ["--set", f"name={t['name']}"] if t["name"] else ["--delete", "name"]
        for key, prop in (("default", "flag-default"), ("forced", "flag-forced"), ("enabled", "flag-enabled")):
            if key in t:
                a += ["--set", f"{prop}={1 if t[key] else 0}"]
    for aid in spec.get("delete_attachments", []):
        a += ["--delete-attachment", str(aid)]
    for p in spec.get("add_attachments", []):
        a += ["--add-attachment", p]
    return a


def unique_path(path: str, taken=None) -> str:
    """Return path, or 'name (2).ext' etc. if it exists on disk or is in `taken`."""
    taken = taken if taken is not None else set()
    root, ext = os.path.splitext(path)
    cand, n = path, 2
    while os.path.exists(cand) or os.path.normcase(cand) in taken:
        cand = f"{root} ({n}){ext}"
        n += 1
    taken.add(os.path.normcase(cand))
    return cand


def quote_cmd(program: str, args: list) -> str:
    """Human-readable command line for display/copy."""
    def q(s):
        s = str(s)
        if not s or any(c in s for c in ' "&|<>^()'):
            return '"' + s.replace('"', '\\"') + '"'
        return s
    return " ".join(q(x) for x in [program] + list(args))
