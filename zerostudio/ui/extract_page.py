"""Extract page: pull tracks, attachments, chapters, tags, timestamps and cues out of MKV files (batch).
Non-Matroska inputs (MP4, AVI, TS, MOV...) are remuxed to a temporary MKV first, then extracted."""
import os
import uuid

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QRadioButton,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..commands import build_extract_args, build_extract_remux
from ..jobs import Job
from ..languages import BY_CODE
from ..mediainfo import file_size_text, identify, render_template, safe_name
from .theme import C
from .widgets import (EXTRACT_EXTS, EXTRACT_FILTER, DropFilter, add_shortcuts, card, expand_paths, page_header, pick_files, pick_folder, run_async)
from .icons import icon

FILTER_TYPES = [("attachments", "Attachments"), ("chapters", "Chapters"), ("tags", "Tags")]
TRACK_TYPES = [("video", "Video"), ("audio", "Audio"), ("subtitles", "Subtitles")]
MODES = [("all", "All tracks"), ("none", "None"), ("first", "First track only"),
         ("default", "Default track only"), ("lang", "By language"), ("num", "By position (1st, 2nd...)")]
SUB_MODES = [("forced", "Forced only"), ("notforced", "All except forced")]


class TrackSelector(QWidget):
    """One row: which tracks of a given type to tick in every loaded file."""
    changed = Signal()

    def __init__(self, ttype, label, state, parent=None):
        super().__init__(parent)
        self.ttype = ttype
        self.available = {}          # lang -> count across loaded files
        self.checked_langs = list(state.get("langs", []))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lab = QLabel(label)
        lab.setFixedWidth(78)
        lab.setStyleSheet(f"color: {C.get(ttype, C['text'])}; font-weight: 600;")
        lay.addWidget(lab)
        self.mode = QComboBox()
        for key, text in MODES + (SUB_MODES if ttype == "subtitles" else []):
            self.mode.addItem(text, key)
        i = self.mode.findData(state.get("mode", "all"))
        self.mode.setCurrentIndex(max(0, i))
        self.mode.setMinimumWidth(190)
        lay.addWidget(self.mode)
        self.lang_btn = QToolButton()
        self.lang_btn.setPopupMode(QToolButton.InstantPopup)
        self.lang_btn.setMinimumWidth(170)
        self.lang_btn.setStyleSheet(f"QToolButton {{ background: {C['surface2']}; border: 1px solid {C['border']};"
                                    f" border-radius: 6px; padding: 5px 10px; color: {C['text']}; text-align: left; }}"
                                    "QToolButton::menu-indicator { subcontrol-position: right center; right: 6px; }")
        self.menu = QMenu(self.lang_btn)
        self.lang_btn.setMenu(self.menu)
        lay.addWidget(self.lang_btn)
        self.nums = QLineEdit(state.get("nums", "1"))
        self.nums.setPlaceholderText("e.g. 1,3")
        self.nums.setToolTip("Position among this file's tracks of this type: 1 = first, 2 = second...")
        self.nums.setMaximumWidth(120)
        lay.addWidget(self.nums)
        self.count = QLabel("", objectName="Muted")
        lay.addWidget(self.count)
        lay.addStretch(1)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.nums.textChanged.connect(lambda: self.changed.emit())
        self._rebuild_menu()
        self._mode_changed(emit=False)

    def _mode_changed(self, *_, emit=True):
        m = self.mode.currentData()
        self.lang_btn.setVisible(m == "lang")
        self.nums.setVisible(m == "num")
        if emit:
            self.changed.emit()

    def set_available(self, langs):
        self.available = langs
        self._rebuild_menu()

    def _rebuild_menu(self):
        self.menu.clear()
        langs = sorted(set(self.available) | set(self.checked_langs),
                       key=lambda c: (-self.available.get(c, 0), c))
        if not langs:
            a = self.menu.addAction("Load files to see their languages")
            a.setEnabled(False)
        for code in langs:
            n = self.available.get(code, 0)
            a = self.menu.addAction(f"{code} - {BY_CODE.get(code, code)}" + (f"   ({n})" if n else ""))
            a.setCheckable(True)
            a.setChecked(code in self.checked_langs)
            a.setData(code)
            a.toggled.connect(self._lang_toggled)
        self._update_btn()

    def _lang_toggled(self, on):
        code = self.sender().data()
        if on and code not in self.checked_langs:
            self.checked_langs.append(code)
        elif not on and code in self.checked_langs:
            self.checked_langs.remove(code)
        self._update_btn()
        self.changed.emit()

    def _update_btn(self):
        self.lang_btn.setText(", ".join(self.checked_langs) if self.checked_langs else "Pick languages")

    def state(self):
        return {"mode": self.mode.currentData(), "langs": list(self.checked_langs), "nums": self.nums.text()}

    def pick(self, tracks):
        """tracks = this file's tracks of self.ttype in order. Returns the set of chosen track IDs."""
        m = self.mode.currentData()
        if not tracks or m == "none":
            return set()
        if m == "all":
            return {t.id for t in tracks}
        if m == "first":
            return {tracks[0].id}
        if m == "default":
            d = [t for t in tracks if t.default]
            return {(d or tracks)[0].id}
        if m == "lang":
            return {t.id for t in tracks if t.language in self.checked_langs}
        if m == "num":
            want = set()
            for part in self.nums.text().replace(";", ",").split(","):
                part = part.strip()
                if "-" in part:
                    a, _, b = part.partition("-")
                    if a.strip().isdigit() and b.strip().isdigit():
                        want.update(range(int(a), int(b) + 1))
                elif part.isdigit():
                    want.add(int(part))
            return {t.id for i, t in enumerate(tracks, 1) if i in want}
        if m == "forced":
            return {t.id for t in tracks if t.forced}
        if m == "notforced":
            return {t.id for t in tracks if not t.forced}
        return set()
TEMPLATE_HELP = ("Placeholders: {base} file name, {id} track ID, {num} track number, {type}, {lang}, {name} track "
                 "name, {codec}, {title}. Extension is added automatically. Empty brackets are removed.")


class ExtractPage(QWidget):
    def __init__(self, app_ctx, parent=None):
        super().__init__(parent)
        self.ctx = app_ctx
        s = app_ctx.settings
        self.files = []        # {path, mf, item}
        self._pending = 0
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 12)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addLayout(page_header("Extract", "Pull tracks, fonts, chapters and tags out of MKV, MP4, AVI, TS, MOV and other video files. "
                                              "Load a whole season and pick what you want once."), 1)
        root.addLayout(head)

        # Filter card
        fc, fl = card("Track selection", "applied to every loaded file; you can still tick items by hand below")
        sel_state = s.extract_selectors if isinstance(s.extract_selectors, dict) else {}
        self.selectors = {}
        for ttype, label in TRACK_TYPES:
            ts = TrackSelector(ttype, label, sel_state.get(ttype, {"mode": "all"}))
            ts.changed.connect(self._schedule_apply)
            self.selectors[ttype] = ts
            fl.addWidget(ts)
        row = QHBoxLayout()
        lab = QLabel("Also")
        lab.setFixedWidth(78)
        row.addWidget(lab)
        self.type_boxes = {}
        for key, label in FILTER_TYPES:
            cb = QCheckBox(label)
            cb.setChecked(key in (s.extract_types or []))
            cb.toggled.connect(self._schedule_apply)
            self.type_boxes[key] = cb
            row.addWidget(cb)
        row.addStretch(1)
        self.btn_apply = QPushButton("Re-apply")
        self.btn_apply.setToolTip("Reset the ticks below to the selection above (undoes manual ticks)")
        self.btn_none = QPushButton("Clear ticks")
        row.addWidget(self.btn_apply)
        row.addWidget(self.btn_none)
        fl.addLayout(row)
        self._apply_timer = QTimer(self, singleShot=True, interval=150, timeout=self.apply_filter)
        root.addWidget(fc)

        # Files tree
        tc, tl = card("Files")
        self.status = QLabel("", objectName="Muted")
        tc.title_row.addWidget(self.status)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item", "Details", "Saved as"])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        hh = self.tree.header()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree.setColumnWidth(0, 320)
        self.tree.setColumnWidth(1, 250)
        self.hint = QLabel("Drop video files (MKV, MP4, AVI, TS, MOV...) or folders here, or click Add files", objectName="DropHint",
                           alignment=Qt.AlignCenter)
        tl.addWidget(self.tree, 1)
        tl.addWidget(self.hint, 1)
        brow = QHBoxLayout()
        self.btn_add = QPushButton("Add files")
        self.btn_add.setIcon(icon("plus", C["text"], 18))
        self.btn_folder = QPushButton("Add folder")
        self.btn_folder.setIcon(icon("folder", C["text"], 18))
        self.btn_remove = QPushButton("Remove")
        self.btn_clear = QPushButton("Clear")
        for b in (self.btn_add, self.btn_folder, self.btn_remove, self.btn_clear):
            brow.addWidget(b)
        brow.addStretch(1)
        self.btn_expand = QPushButton("Expand all", objectName="Flat")
        self.btn_collapse = QPushButton("Collapse all", objectName="Flat")
        brow.addWidget(self.btn_expand)
        brow.addWidget(self.btn_collapse)
        tl.addLayout(brow)
        root.addWidget(tc, 1)

        # Output card
        oc, ol = card("Output")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        self.rb_source = QRadioButton("Next to each source file")
        self.rb_custom = QRadioButton("Into folder")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_source)
        grp.addButton(self.rb_custom)
        (self.rb_custom if s.extract_out_mode == "custom" else self.rb_source).setChecked(True)
        self.dir_edit = QLineEdit(s.extract_out_dir)
        self.dir_edit.setPlaceholderText("Choose a folder")
        self.btn_dir = QPushButton("Browse")
        self.sub_box = QCheckBox("Subfolder per file")
        self.sub_box.setChecked(s.extract_subfolder)
        g.addWidget(self.rb_source, 0, 0)
        g.addWidget(self.rb_custom, 0, 1)
        g.addWidget(self.dir_edit, 0, 2)
        g.addWidget(self.btn_dir, 0, 3)
        g.addWidget(self.sub_box, 0, 4)
        g.addWidget(QLabel("File names"), 1, 0)
        self.tpl_edit = QLineEdit(s.extract_template)
        self.tpl_edit.setToolTip(TEMPLATE_HELP)
        g.addWidget(self.tpl_edit, 1, 1, 1, 2)
        self.chap_fmt = QComboBox()
        self.chap_fmt.addItem("Chapters as XML", False)
        self.chap_fmt.addItem("Chapters as simple OGM text", True)
        self.chap_fmt.setCurrentIndex(1 if s.chapters_simple else 0)
        g.addWidget(self.chap_fmt, 1, 3, 1, 2)
        self.ts_box = QCheckBox("Also timestamps (v2) for ticked tracks")
        self.ts_box.setChecked(s.extract_timestamps)
        self.cues_box = QCheckBox("Also cues (index) for ticked tracks")
        self.cues_box.setChecked(s.extract_cues)
        g.addWidget(self.ts_box, 2, 1, 1, 2)
        g.addWidget(self.cues_box, 2, 3, 1, 2)
        g.setColumnStretch(2, 1)
        ol.addLayout(g)
        arow = QHBoxLayout()
        self.summary = QLabel("", objectName="Muted")
        arow.addWidget(self.summary, 1)
        self.btn_go = QPushButton("Extract", objectName="Primary")
        self.btn_go.setIcon(icon("extract", C["on_accent"], 18))
        arow.addWidget(self.btn_go)
        ol.addLayout(arow)
        root.addWidget(oc)

        # Signals
        self.btn_add.clicked.connect(lambda: self.add_files(pick_files(self, s, "Add video files", EXTRACT_FILTER)))
        self.btn_folder.clicked.connect(self._add_folder)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_clear.clicked.connect(self._clear)
        self.btn_expand.clicked.connect(self.tree.expandAll)
        self.btn_collapse.clicked.connect(self.tree.collapseAll)
        self.btn_apply.clicked.connect(self.apply_filter)
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        self.btn_dir.clicked.connect(self._browse_dir)
        self.btn_go.clicked.connect(self.start)
        self.tree.itemChanged.connect(self._item_changed)
        for w in (self.tpl_edit, self.dir_edit):
            w.textChanged.connect(self.update_names)
        for w in (self.rb_source, self.rb_custom, self.sub_box):
            w.toggled.connect(self.update_names)
        self.chap_fmt.currentIndexChanged.connect(self.update_names)
        for w in (self, self.tree):
            DropFilter(w, lambda paths: self.add_files(expand_paths(paths, EXTRACT_EXTS)))
        self.btn_go.setToolTip("Ctrl+Enter")
        add_shortcuts(self, add=self.btn_add.click, start=self.btn_go.click, remove=(self.tree, self._remove))
        self._refresh()

    # ---------- loading ----------
    def _add_folder(self):
        d = pick_folder(self, self.ctx.settings, "Add folder")
        if d:
            self.add_files(expand_paths([d], EXTRACT_EXTS))

    def add_files(self, paths):
        if not paths:
            return
        if not self.ctx.engine.ok:
            self.ctx.need_engine()
            return
        known = {os.path.normcase(f["path"]) for f in self.files}
        mm = self.ctx.engine.tool("mkvmerge")
        for p in paths:
            if os.path.normcase(p) in known:
                continue
            known.add(os.path.normcase(p))
            self._pending += 1
            run_async(lambda p=p: identify(mm, p), lambda mf, err, p=p: self._identified(p, mf, err))
        self._refresh()

    def _identified(self, path, mf, err):
        self._pending -= 1
        if err:
            self.ctx.toast(f"Skipped {os.path.basename(path)}: {err}", error=True)
        elif not mf.tracks and not mf.chapters:
            self.ctx.toast(f"Skipped {os.path.basename(path)}: no tracks mkvmerge can read ({mf.container})", error=True)
        else:
            self._add_tree_file(path, mf)
        self._refresh()

    def _add_tree_file(self, path, mf):
        self._updating = True
        top = QTreeWidgetItem(self.tree)
        top.setText(0, os.path.basename(path))
        f = QFont(top.font(0))
        f.setBold(True)
        top.setFont(0, f)
        bits = [mf.duration_text()]
        if not mf.is_matroska:
            bits.insert(0, mf.container or "non-MKV")
            top.setToolTip(1, "Not a Matroska file: it is copied to a temporary MKV first (no re-encoding), "
                              "then extracted. The temp file is deleted afterwards.")
        try:
            bits.append(file_size_text(os.path.getsize(path)))
        except OSError:
            pass
        top.setText(1, "  ·  ".join(b for b in bits if b))
        top.setToolTip(0, path)
        top.setFlags(top.flags() | Qt.ItemIsUserCheckable)
        top.setCheckState(0, Qt.Unchecked)
        entry = {"path": path, "mf": mf, "item": top}
        for t in mf.tracks:
            it = QTreeWidgetItem(top)
            label = f"Track {t.id}  {t.type}  [{t.language}]" + (f"  {t.name}" if t.name else "")
            it.setText(0, label)
            flags = [x for x in ("default" if t.default else "", "forced" if t.forced else "") if x]
            it.setText(1, f"{t.codec}  {t.details()}" + (f"  ({', '.join(flags)})" if flags else ""))
            it.setForeground(0, QColor(C.get(t.type, C["other"])))
            it.setData(0, Qt.UserRole, ("track", t.id))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked)
        for a in mf.attachments:
            it = QTreeWidgetItem(top)
            it.setText(0, f"Attachment {a.id}  {a.file_name}")
            it.setText(1, f"{a.mime}, {file_size_text(a.size)}")
            it.setData(0, Qt.UserRole, ("attachment", a.id))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked)
        if mf.chapters:
            it = QTreeWidgetItem(top)
            it.setText(0, "Chapters")
            it.setText(1, f"{mf.chapters} entr{'y' if mf.chapters == 1 else 'ies'}")
            it.setData(0, Qt.UserRole, ("chapters", 0))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked)
        if mf.global_tags or mf.track_tags:
            it = QTreeWidgetItem(top)
            it.setText(0, "Tags")
            it.setText(1, f"{mf.global_tags + mf.track_tags} entries")
            it.setData(0, Qt.UserRole, ("tags", 0))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked)
        self.files.append(entry)
        self._apply_filter_to(entry)
        top.setExpanded(len(self.files) <= 3)
        self._updating = False
        self._update_selector_info()
        self.update_names()

    def _remove(self):
        tops = {it if it.parent() is None else it.parent() for it in self.tree.selectedItems()}
        for top in tops:
            self.files = [f for f in self.files if f["item"] is not top]
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(top))
        self._update_selector_info()
        self._refresh()

    def _clear(self):
        self.files = []
        self.tree.clear()
        self._update_selector_info()
        self._refresh()

    # ---------- selection ----------
    def _schedule_apply(self, *_):
        self._apply_timer.start()

    def _selected_track_ids(self, mf):
        chosen = set()
        for ttype, sel in self.selectors.items():
            chosen |= sel.pick([t for t in mf.tracks if t.type == ttype])
        other = [t for t in mf.tracks if t.type not in self.selectors]
        return chosen, other

    def _apply_filter_to(self, entry):
        types = {k for k, cb in self.type_boxes.items() if cb.isChecked()}
        chosen, _ = self._selected_track_ids(entry["mf"])
        top = entry["item"]
        for i in range(top.childCount()):
            ch = top.child(i)
            kind, ident = ch.data(0, Qt.UserRole)
            if kind == "track":
                want = ident in chosen
            else:
                want = {"attachment": "attachments", "chapters": "chapters", "tags": "tags"}[kind] in types
            ch.setCheckState(0, Qt.Checked if want else Qt.Unchecked)

    def _update_selector_info(self):
        for ttype, sel in self.selectors.items():
            langs, picked, files_with = {}, 0, 0
            for e in self.files:
                tracks = [t for t in e["mf"].tracks if t.type == ttype]
                for t in tracks:
                    langs[t.language] = langs.get(t.language, 0) + 1
                n = len(sel.pick(tracks))
                picked += n
                files_with += 1 if n else 0
            sel.set_available(langs)
            sel.count.setText(f"{picked} track{'s' if picked != 1 else ''} in {files_with} "
                              f"file{'s' if files_with != 1 else ''}" if self.files else "")

    def apply_filter(self):
        self._updating = True
        for e in self.files:
            self._apply_filter_to(e)
        self._updating = False
        self._update_selector_info()
        self.update_names()
        self._save_prefs()

    def _set_all(self, v):
        self._updating = True
        for e in self.files:
            for i in range(e["item"].childCount()):
                e["item"].child(i).setCheckState(0, Qt.Checked if v else Qt.Unchecked)
        self._updating = False
        self.update_names()

    def _item_changed(self, item, col):
        if self._updating or col != 0:
            return
        self._updating = True
        if item.parent() is None:
            st = Qt.Unchecked if item.checkState(0) == Qt.Unchecked else Qt.Checked
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, st)
        self.update_names()
        self._updating = False

    def _sync_parents(self):
        for e in self.files:
            top = e["item"]
            n = top.childCount()
            on = sum(1 for i in range(n) if top.child(i).checkState(0) == Qt.Checked)
            top.setCheckState(0, Qt.Checked if n and on == n else (Qt.PartiallyChecked if on else Qt.Unchecked))

    # ---------- naming ----------
    def _out_dir(self, entry):
        if self.rb_custom.isChecked() and self.dir_edit.text().strip():
            d = self.dir_edit.text().strip()
        else:
            d = os.path.dirname(entry["path"])
        if self.sub_box.isChecked():
            d = os.path.join(d, safe_name(entry["mf"].base))
        return d

    def plan(self, entry, taken=None, fonts=None):
        """Return the extract spec for one file (only ticked items), plus a map item->output path.
        taken / fonts are shared by all files of one run: jobs run in parallel, so no two of them may write
        the same file. taken = output paths in use; fonts = attachment path -> size. The same attachment
        (same name and size, e.g. the fonts of a season) is extracted once, by the first file that has it."""
        mf = entry["mf"]
        top = entry["item"]
        out_dir = self._out_dir(entry)
        tpl = self.tpl_edit.text().strip() or "{base}_track{id}_[{lang}]"
        taken = set() if taken is None else taken
        fonts = {} if fonts is None else fonts

        def key(name):
            return os.path.normcase(os.path.join(out_dir, name))

        def uniq(name):
            root, ext = os.path.splitext(name)
            cand, n = name, 2
            while key(cand) in taken:
                cand = f"{root} ({n}){ext}"
                n += 1
            taken.add(key(cand))
            return os.path.join(out_dir, cand)

        spec = {"path": entry["path"], "tracks": [], "attachments": [], "chapters": "", "tags": "",
                "chapters_simple": bool(self.chap_fmt.currentData())}
        names = {}
        shared = set()       # attachments another file of this run extracts (same name and size)
        for i in range(top.childCount()):
            ch = top.child(i)
            if ch.checkState(0) != Qt.Checked:
                continue
            kind, ident = ch.data(0, Qt.UserRole)
            if kind == "track":
                t = next(x for x in mf.tracks if x.id == ident)
                fn = uniq(render_template(tpl, mf, t))
                stem = os.path.splitext(fn)[0]
                d = {"id": t.id, "file": fn}
                if self.ts_box.isChecked():
                    d["timestamps"] = stem + ".timestamps.txt"
                if self.cues_box.isChecked() and t.has_cues and mf.is_matroska:
                    d["cues"] = stem + ".cues.txt"
                spec["tracks"].append(d)
                names[id(ch)] = fn
            elif kind == "attachment":
                a = next(x for x in mf.attachments if x.id == ident)
                same = key(safe_name(a.file_name))
                if fonts.get(same) == a.size:      # another file of this run already writes this very file
                    names[id(ch)] = os.path.join(out_dir, safe_name(a.file_name))
                    shared.add(id(ch))
                    continue
                fn = uniq(safe_name(a.file_name))
                fonts.setdefault(key(os.path.basename(fn)), a.size)
                spec["attachments"].append({"id": a.id, "file": fn})
                names[id(ch)] = fn
            elif kind == "chapters":
                fn = uniq(safe_name(mf.base) + (".chapters.txt" if spec["chapters_simple"] else ".chapters.xml"))
                spec["chapters"] = fn
                names[id(ch)] = fn
            elif kind == "tags":
                fn = uniq(safe_name(mf.base) + ".tags.xml")
                spec["tags"] = fn
                names[id(ch)] = fn
        spec["shared"] = shared
        return spec, names, out_dir

    def update_names(self):
        was = self._updating
        self._updating = True
        taken, fonts = set(), {}
        for e in self.files:
            spec, names, _ = self.plan(e, taken, fonts)
            top = e["item"]
            for i in range(top.childCount()):
                ch = top.child(i)
                p = names.get(id(ch))
                once = id(ch) in spec["shared"]
                ch.setText(2, (os.path.basename(p) + ("   (same file, saved once)" if once else "")) if p else "")
                ch.setToolTip(2, (p + ("\nThe same attachment is in an earlier file of this list and is saved "
                                       "only once." if once else "")) if p else "")
        self._sync_parents()
        self._updating = was
        self._refresh()

    def _browse_dir(self):
        d = pick_folder(self, self.ctx.settings, "Output folder")
        if d:
            self.dir_edit.setText(os.path.normpath(d))
            self.rb_custom.setChecked(True)

    def _save_prefs(self):
        s = self.ctx.settings
        s.extract_types = [k for k, cb in self.type_boxes.items() if cb.isChecked()]
        s.extract_selectors = {k: sel.state() for k, sel in self.selectors.items()}
        s.extract_out_mode = "custom" if self.rb_custom.isChecked() else "source"
        s.extract_out_dir = self.dir_edit.text()
        s.extract_template = self.tpl_edit.text()
        s.extract_subfolder = self.sub_box.isChecked()
        s.extract_timestamps = self.ts_box.isChecked()
        s.extract_cues = self.cues_box.isChecked()
        s.chapters_simple = bool(self.chap_fmt.currentData())
        s.save()

    # ---------- run ----------
    def start(self):
        if not self.ctx.engine.ok:
            self.ctx.need_engine()
            return
        if self.rb_custom.isChecked() and not self.dir_edit.text().strip():
            QMessageBox.information(self, "Extract", "Choose an output folder, or pick 'Next to each source file'.")
            return
        jobs = []
        overwrite = []
        taken, fonts = set(), {}
        for e in self.files:
            spec, names, out_dir = self.plan(e, taken, fonts)
            shared = spec.pop("shared")
            if not (spec["tracks"] or spec["attachments"] or spec["chapters"] or spec["tags"]):
                continue
            jobs.append((e, spec, out_dir))
            overwrite += [p for i, p in names.items() if i not in shared and os.path.exists(p)]
        if not jobs:
            QMessageBox.information(self, "Extract", "Nothing is ticked.")
            return
        if overwrite:
            r = QMessageBox.question(self, "Overwrite files?",
                                     f"{len(overwrite)} output file(s) already exist, e.g.\n"
                                     f"{os.path.basename(overwrite[0])}\n\nOverwrite them?")
            if r != QMessageBox.Yes:
                return
        for e, spec, out_dir in jobs:
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as ex:
                QMessageBox.warning(self, "Extract", f"Cannot create folder:\n{out_dir}\n\n{ex}")
                return
            self.ctx.queue.add(self._make_job(e, spec, out_dir))
        self._save_prefs()
        self.ctx.toast(f"Queued {len(jobs)} extraction job{'s' if len(jobs) != 1 else ''}")

    @staticmethod
    def _make_job(entry, spec, out_dir):
        mf = entry["mf"]
        title = os.path.basename(entry["path"])
        if mf.is_matroska:
            return Job("extract", title, build_extract_args(spec), output=out_dir)
        # mkvextract reads only Matroska: remux the ticked tracks to a temp MKV first, then extract with new IDs
        temp = os.path.join(out_dir, f".zerostudio-temp-{uuid.uuid4().hex[:8]}.mkv")
        pre, idmap = build_extract_remux(entry["path"], temp, [(t.id, t.type) for t in mf.tracks],
                                         [t["id"] for t in spec["tracks"]], bool(spec["chapters"]), bool(spec["tags"]))
        spec = dict(spec, path=temp, attachments=[],
                    tracks=[dict(t, id=idmap[t["id"]]) for t in spec["tracks"] if t["id"] in idmap])
        return Job("extract", title, build_extract_args(spec), output=out_dir, pre_args=pre, temp_file=temp)

    def _refresh(self):
        has = bool(self.files)
        self.tree.setVisible(has)
        self.hint.setVisible(not has)
        items = files = 0
        for e in self.files:
            top = e["item"]
            n = sum(1 for i in range(top.childCount()) if top.child(i).checkState(0) == Qt.Checked)
            items += n
            files += 1 if n else 0
        self.status.setText(f"  reading {self._pending} file(s)..." if self._pending else
                            (f"  {len(self.files)} loaded" if has else ""))
        self.summary.setText(f"{items} item{'s' if items != 1 else ''} from {files} file{'s' if files != 1 else ''}"
                             if has else "")
        self.btn_go.setEnabled(items > 0)
        self.btn_go.setText(f"Extract {items} item{'s' if items != 1 else ''}" if items else "Extract")
