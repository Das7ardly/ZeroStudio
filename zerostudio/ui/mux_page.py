"""Multiplex page: combine tracks from several files into one MKV."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIntValidator
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QGridLayout, QStackedWidget, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..commands import build_mux_args, quote_cmd, unique_path
from ..jobs import Job
from ..languages import guess_from_filename, name_tail, parse_list
from ..mediainfo import detect_text_charset, file_size_text, identify
from .batch_page import BatchMuxPage
from .fileinfo import (attachment_detail, attachment_title, file_summary, track_detail, track_title,
                       track_tooltip)
from .theme import C
from .widgets import (MEDIA_EXTS, CheckCell, DropFilter, LangCombo, LangListEdit, add_shortcuts, card, expand_paths,
                      page_header, pick_files, run_async)
from .icons import icon

TYPE_LABEL = {"video": "Video", "audio": "Audio", "subtitles": "Subtitles", "buttons": "Buttons"}
CHARSETS = ["", "UTF-8", "cp1251", "cp1250", "cp1252", "cp1253", "cp1254", "cp1256", "ISO-8859-1", "ISO-8859-2",
            "ISO-8859-5", "KOI8-R", "Big5", "GB18030", "Shift_JIS", "EUC-KR"]
COL_USE, COL_TYPE, COL_CODEC, COL_LANG, COL_NAME, COL_DEF, COL_FORCED, COL_DELAY, COL_CS, COL_SRC = range(10)
SPLIT_MODES = [("No splitting", ""), ("By size (e.g. 2G, 700M)", "size:"), ("By duration (e.g. 00:45:00)", "duration:"),
               ("After chapters (e.g. all or 3,6)", "chapters:"), ("By timestamps (e.g. 00:10:00,00:20:00)", "timestamps:")]


class MuxPage(QWidget):
    def __init__(self, app_ctx, parent=None):
        super().__init__(parent)
        self.ctx = app_ctx
        self.inputs = []          # {path, mf, append}
        self.rows = []            # {inp: input dict, track, use, language, name, default, forced, delay, charset}
        self.extra_attach = []    # file paths
        self._pending = 0
        self._src_open = {}       # source path -> expanded in the Sources list
        self._waiting = []        # files being read, in the order they were added: {path, append, done, mf, err}
        self._failed = []         # (file name, error) collected while a batch of files is read
        self._output_edited = False
        self._title_edited = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 8, 22, 12)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addLayout(page_header("Multiplex", "Combine video, audio, subtitles, chapters and fonts into one MKV. "
                                               "Drop files anywhere on this page."), 1)
        self.btn_new = QPushButton("New")
        self.btn_new.setIcon(icon("new", C["text"], 18))
        head.addWidget(self.btn_new, 0, Qt.AlignTop)
        root.addLayout(head)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)

        # Sources
        src_card, sl = card("Sources")
        self.src_status = QLabel("", objectName="Muted")
        src_card.title_row.addWidget(self.src_status)
        self.src_list = QTreeWidget()
        self.src_list.setHeaderLabels(["Item", "Details"])
        self.src_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.src_list.setAlternatingRowColors(True)
        self.src_list.setUniformRowHeights(True)
        self.src_list.setMinimumHeight(90)
        self.src_list.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.src_list.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.src_list.setColumnWidth(0, 360)
        self.src_list.itemChanged.connect(self._src_item_changed)
        self.src_drop_hint = QLabel("Drop video, audio and subtitle files here, or click Add files",
                                    objectName="DropHint", alignment=Qt.AlignCenter)
        sl.addWidget(self.src_list, 1)
        sl.addWidget(self.src_drop_hint)
        brow = QHBoxLayout()
        self.btn_add = QPushButton("Add files")
        self.btn_add.setIcon(icon("plus", C["text"], 18))
        self.btn_append = QPushButton("Append parts")
        self.btn_append.setToolTip("Join files end-to-end (e.g. CD1 + CD2). Tracks map onto the first file's tracks.")
        self.btn_remove = QPushButton("Remove")
        brow.addWidget(self.btn_add)
        brow.addWidget(self.btn_append)
        brow.addWidget(self.btn_remove)
        brow.addStretch(1)
        sl.addLayout(brow)
        split.addWidget(src_card)

        # Tabs: tracks / attachments / options
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tracks_tab(), "Tracks")
        self.tabs.addTab(self._build_attach_tab(), "Attachments")
        self.tabs.addTab(self._build_options_tab(), "Chapters and splitting")
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 4)
        split.setSizes([170, 450])
        root.addWidget(split, 1)

        # Output
        out_card, ol = card()
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.addWidget(QLabel("Title"), 0, 0)
        self.title_edit = QLineEdit(placeholderText="Movie title stored in the file (optional)")
        g.addWidget(self.title_edit, 0, 1, 1, 2)
        g.addWidget(QLabel("Output"), 1, 0)
        self.out_edit = QLineEdit(placeholderText="Output .mkv file")
        self.btn_out = QPushButton("Browse")
        g.addWidget(self.out_edit, 1, 1)
        g.addWidget(self.btn_out, 1, 2)
        g.setColumnStretch(1, 1)
        ol.addLayout(g)
        arow = QHBoxLayout()
        self.summary = QLabel("", objectName="Muted")
        arow.addWidget(self.summary, 1)
        self.btn_cmd = QPushButton("Show command")
        self.btn_go = QPushButton("Start multiplexing", objectName="Primary")
        self.btn_go.setIcon(icon("play", C["on_accent"], 18))
        arow.addWidget(self.btn_cmd)
        arow.addWidget(self.btn_go)
        ol.addLayout(arow)
        root.addWidget(out_card)

        # Signals
        self.btn_add.clicked.connect(lambda: self.add_files(pick_files(self, self.ctx.settings, "Add files")))
        self.btn_append.clicked.connect(
            lambda: self.add_files(pick_files(self, self.ctx.settings, "Append parts"), append=True))
        self.btn_remove.clicked.connect(self.remove_selected_inputs)
        self.btn_new.clicked.connect(self.reset)
        self.btn_out.clicked.connect(self._browse_out)
        self.btn_cmd.clicked.connect(self._show_command)
        self.btn_go.clicked.connect(self.start)
        self.out_edit.textEdited.connect(lambda: setattr(self, "_output_edited", True))
        self.title_edit.textEdited.connect(lambda: setattr(self, "_title_edited", True))
        for w in (self, self.src_list, self.table):
            DropFilter(w, lambda paths: self.add_files(expand_paths(paths, MEDIA_EXTS)))
        self.btn_go.setToolTip("Ctrl+Enter")
        add_shortcuts(self, add=self.btn_add.click, start=self.btn_go.click,
                      remove=(self.src_list, self.remove_selected_inputs))
        self._refresh()

    # ---------- UI construction ----------
    def _build_tracks_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["Use", "Type", "Codec", "Language", "Name", "Default", "Forced",
                                              "Delay ms", "Charset", "Source"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.table.horizontalHeader()
        for col, width in ((COL_USE, 40), (COL_TYPE, 78), (COL_CODEC, 150), (COL_LANG, 168), (COL_NAME, 200),
                           (COL_DEF, 62), (COL_FORCED, 58), (COL_DELAY, 68), (COL_CS, 88), (COL_SRC, 130)):
            self.table.setColumnWidth(col, width)
        h.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        h.setMinimumSectionSize(36)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.btn_up = QPushButton("Move up")
        self.btn_up.setIcon(icon("up", C["text"]))
        self.btn_down = QPushButton("Move down")
        self.btn_down.setIcon(icon("down", C["text"]))
        self.btn_smart = QPushButton("Smart defaults")
        self.btn_smart.setToolTip("Set the Default flag from your preferred audio/subtitle languages (Settings).\n"
                                  "Subtitles are only made default when the default audio is not in a preferred "
                                  "subtitle language.")
        self.keep_audio = LangListEdit(self.ctx.settings.batch_audio_keep)
        self.keep_subs = LangListEdit(self.ctx.settings.batch_sub_keep)
        for edit in (self.keep_audio, self.keep_subs):
            edit.setPlaceholderText("e.g. bul, eng")
            edit.setMaximumWidth(150)
        self.btn_keep = QPushButton("Keep only these")
        self.btn_keep.setToolTip("Untick audio and subtitle tracks in other languages. Tracks without a language "
                                 "(und) are kept. Empty field = leave that type alone.")
        self.btn_all = QPushButton("Use all")
        self.btn_none = QPushButton("Use none")
        for b in (self.btn_up, self.btn_down):
            row.addWidget(b)
        row.addSpacing(12)
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_none)
        row.addStretch(1)
        row.addWidget(self.btn_smart)
        lay.addLayout(row)
        krow = QHBoxLayout()
        la = QLabel("Keep audio")
        la.setStyleSheet(f"color: {C['audio']}; font-weight: 600;")
        ls = QLabel("subtitles")
        ls.setStyleSheet(f"color: {C['subtitles']}; font-weight: 600;")
        krow.addWidget(la)
        krow.addWidget(self.keep_audio)
        krow.addWidget(ls)
        krow.addWidget(self.keep_subs)
        krow.addWidget(self.btn_keep)
        krow.addStretch(1)
        lay.addLayout(krow)
        self.btn_keep.clicked.connect(self.keep_only)
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(1))
        self.btn_smart.clicked.connect(lambda: (self._collect(), self.apply_smart_defaults(), self._fill_table()))
        self.btn_all.clicked.connect(lambda: self._set_all_use(True))
        self.btn_none.clicked.connect(lambda: self._set_all_use(False))
        return w

    def _build_attach_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(QLabel("Ticked attachments are kept. Fonts are needed for styled ASS/SSA subtitles.",
                             objectName="Muted"))
        self.att_list = QListWidget()
        lay.addWidget(self.att_list, 1)
        row = QHBoxLayout()
        self.btn_att_add = QPushButton("Add files")
        self.btn_att_rm = QPushButton("Remove added")
        row.addWidget(self.btn_att_add)
        row.addWidget(self.btn_att_rm)
        row.addStretch(1)
        lay.addLayout(row)
        self.btn_att_add.clicked.connect(self._add_attachments)
        self.btn_att_rm.clicked.connect(self._remove_attachment)
        DropFilter(self.att_list, self._drop_attachments)
        return w

    def _build_options_tab(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(14, 14, 14, 14)
        g.setVerticalSpacing(10)
        info = QLabel("Chapters and tags from each source are listed under Sources above (click the arrow next "
                      "to a file). Untick them there to drop them.", objectName="Muted")
        info.setWordWrap(True)
        g.addWidget(info, 0, 0, 1, 3)
        g.addWidget(QLabel("Chapters file"), 2, 0)
        self.chap_edit = QLineEdit(placeholderText="Optional .xml / .txt (OGM) chapters to add")
        b = QPushButton("Browse")
        b.clicked.connect(self._browse_chapters)
        g.addWidget(self.chap_edit, 2, 1)
        g.addWidget(b, 2, 2)
        g.addWidget(QLabel("Split output"), 3, 0)
        self.split_mode = QComboBox()
        for label, val in SPLIT_MODES:
            self.split_mode.addItem(label, val)
        self.split_val = QLineEdit(placeholderText="value")
        g.addWidget(self.split_mode, 3, 1)
        g.addWidget(self.split_val, 3, 2)
        self.split_val.setEnabled(False)
        self.split_mode.currentIndexChanged.connect(lambda i: self.split_val.setEnabled(i > 0))
        g.setColumnStretch(1, 1)
        g.setRowStretch(4, 1)
        return w

    # ---------- inputs ----------
    def add_files(self, paths, append=False):
        if not paths:
            return
        if not self.ctx.engine.ok:
            self.ctx.need_engine()
            return
        mm = self.ctx.engine.tool("mkvmerge")
        for p in paths:
            self._pending += 1
            slot = {"path": p, "append": append, "done": False, "mf": None, "err": None}
            self._waiting.append(slot)
            run_async(lambda p=p: identify(mm, p), lambda mf, err, slot=slot: self._identified(slot, mf, err))
        self._refresh()

    def _identified(self, slot, mf, err):
        """Files are read in parallel and finish in any order; add them in the order the user gave them
        (the first source names the output, and appended parts must stay CD1, CD2 ...)."""
        self._pending -= 1
        slot["done"], slot["mf"], slot["err"] = True, mf, err
        while self._waiting and self._waiting[0]["done"]:
            s = self._waiting.pop(0)
            if s["err"]:
                self._failed.append((os.path.basename(s["path"]), str(s["err"])))
            else:
                self._add_input(s["path"], s["mf"], s["append"])
        if not self._waiting and self._failed:
            failed, self._failed = self._failed, []
            text = "\n\n".join(f"{name}\n{why}" for name, why in failed[:8])
            if len(failed) > 8:
                text += f"\n\n... and {len(failed) - 8} more"
            QMessageBox.warning(self, "Cannot add file" if len(failed) == 1 else f"Cannot add {len(failed)} files",
                                text)
        self._refresh()

    def _add_input(self, path, mf, append):
        self._collect()
        append = append and any(not i["append"] for i in self.inputs)
        inp = {"path": path, "mf": mf, "append": append}
        self.inputs.append(inp)
        if not append:
            fallback = self.ctx.settings.fallback_sub_charset
            ext_lang = None if mf.is_matroska else guess_from_filename(path)
            tags = [x.lower() for x in name_tail(path)]
            for t in mf.tracks:
                charset = "" if mf.is_matroska else (detect_text_charset(path, fallback) if t.type == "subtitles" else "")
                lang = t.language
                if lang == "und" and ext_lang:
                    lang = ext_lang
                forced = t.forced or (not mf.is_matroska and t.type == "subtitles" and "forced" in tags)
                self.rows.append({"inp": inp, "track": t, "use": True, "language": lang, "name": t.name,
                                  "default": t.default if mf.is_matroska else t.type != "subtitles",
                                  "forced": forced, "delay": 0, "charset": charset})
            if not self._title_edited and not self.title_edit.text() and mf.title:
                self.title_edit.setText(mf.title)
            if self.ctx.settings.smart_defaults_on_add:
                self.apply_smart_defaults()
        self._auto_output()
        self._fill_sources()
        self._fill_table()
        self._fill_attachments()
        self._refresh()

    def remove_selected_inputs(self):
        rows = set()
        for it in self.src_list.selectedItems():
            top = it if it.parent() is None else it.parent()
            rows.add(self.src_list.indexOfTopLevelItem(top))
        rows = sorted((r for r in rows if r >= 0), reverse=True)
        if not rows:
            return
        self._collect()
        for r in rows:
            inp = self.inputs.pop(r)
            self.rows = [x for x in self.rows if x["inp"] is not inp]
        if self.inputs and self.inputs[0]["append"]:
            self.inputs[0]["append"] = False
        self._auto_output()
        self._fill_sources()
        self._fill_table()
        self._fill_attachments()
        self._refresh()

    def reset(self):
        self.inputs, self.rows, self.extra_attach = [], [], []
        for s in self._waiting:      # files still being read belong to the list that was just cleared
            s["err"] = s["err"] or "skipped"
        self._failed = []
        self._output_edited = self._title_edited = False
        self.title_edit.clear()
        self.out_edit.clear()
        self.chap_edit.clear()
        self.split_mode.setCurrentIndex(0)
        self.split_val.clear()
        self._fill_sources()
        self._fill_table()
        self._fill_attachments()
        self._refresh()

    def _fill_sources(self):
        """Everything inside each source: tracks, attachments, chapters, tags (chapters/tags can be dropped)."""
        tree = self.src_list
        for i in range(tree.topLevelItemCount()):       # remember which sources the user opened
            it = tree.topLevelItem(i)
            self._src_open[it.toolTip(0)] = it.isExpanded()
        tree.blockSignals(True)
        tree.clear()
        bold = QFont(tree.font())
        bold.setBold(True)
        for idx, inp in enumerate(self.inputs):
            mf = inp["mf"]
            try:
                size = os.path.getsize(inp["path"])
            except OSError:
                size = None
            top = QTreeWidgetItem(tree)
            top.setText(0, ("+ append  " if inp["append"] else "") + os.path.basename(inp["path"]))
            top.setFont(0, bold)
            extra = [f"{n} {what}" for n, what in ((mf.chapters, "chapters"), (len(mf.attachments), "attachments")) if n]
            top.setText(1, file_summary(mf, size) + ("  ·  " + ", ".join(extra) if extra else ""))
            top.setToolTip(0, inp["path"])
            top.setData(0, Qt.UserRole, ("input", idx))
            for t in mf.tracks:
                it = QTreeWidgetItem(top)
                it.setText(0, track_title(t))
                it.setText(1, track_detail(t))
                it.setToolTip(0, track_tooltip(t))
                it.setToolTip(1, track_tooltip(t))
                it.setForeground(0, QColor(C.get(t.type, C["other"])))
                it.setData(0, Qt.UserRole, ("track", idx))
            for a in mf.attachments:
                it = QTreeWidgetItem(top)
                it.setText(0, attachment_title(a))
                it.setText(1, attachment_detail(a) + "   (keep or drop in the Attachments tab)")
                it.setData(0, Qt.UserRole, ("attachment", idx))
            for key, count, label in (("chapters", mf.chapters, "Chapters"),
                                      ("tags", mf.global_tags + mf.track_tags, "Tags")):
                if not count:
                    continue
                it = QTreeWidgetItem(top)
                it.setText(0, label)
                it.setText(1, f"{count} entr{'y' if count == 1 else 'ies'}   (tick to keep)")
                it.setData(0, Qt.UserRole, (key, idx))
                if inp["append"]:
                    it.setText(1, f"{count} entr{'y' if count == 1 else 'ies'}")
                else:
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(0, Qt.Checked if inp.get(key, True) else Qt.Unchecked)
            if not mf.tracks and not mf.attachments:
                QTreeWidgetItem(top, ["(nothing usable found)", ""])
            # The Tracks table below already lists every track, so a source starts closed (one row per file)
            top.setExpanded(self._src_open.get(inp["path"], False))
        tree.blockSignals(False)

    def _src_item_changed(self, item, col):
        data = item.data(0, Qt.UserRole)
        if col == 0 and data and data[0] in ("chapters", "tags"):
            self.inputs[data[1]][data[0]] = item.checkState(0) == Qt.Checked

    # ---------- tracks table ----------
    def _fill_table(self):
        t = self.table
        t.setRowCount(0)
        t.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            tr, mf = row["track"], row["inp"]["mf"]
            use = CheckCell(row["use"])
            use.box.toggled.connect(self._refresh)
            t.setCellWidget(r, COL_USE, use)
            it = QTableWidgetItem(TYPE_LABEL.get(tr.type, tr.type))
            it.setForeground(QColor(C.get(tr.type, C["other"])))
            t.setItem(r, COL_TYPE, it)
            det = tr.details()
            codec = QTableWidgetItem(tr.codec + (f"  ·  {det}" if det else ""))
            codec.setToolTip(f"{tr.codec_id or tr.codec}\n{det}")
            t.setItem(r, COL_CODEC, codec)
            t.setCellWidget(r, COL_LANG, LangCombo(row["language"]))
            name = QLineEdit(row["name"])
            name.setPlaceholderText("Track name")
            t.setCellWidget(r, COL_NAME, name)
            t.setCellWidget(r, COL_DEF, CheckCell(row["default"]))
            t.setCellWidget(r, COL_FORCED, CheckCell(row["forced"]))
            delay = QLineEdit(str(row["delay"] or ""))
            delay.setValidator(QIntValidator(-3600000, 3600000))
            delay.setPlaceholderText("0")
            t.setCellWidget(r, COL_DELAY, delay)
            if tr.type == "subtitles" and not mf.is_matroska and tr.props.get("text_subtitles", True):
                cs = QComboBox()
                cs.setEditable(True)
                cs.addItems(CHARSETS)
                cs.setItemText(0, "Auto")
                cs.setCurrentText(row["charset"] or "Auto")
                cs.setToolTip("Text encoding of the subtitle file. Bulgarian SRTs are often cp1251.")
                t.setCellWidget(r, COL_CS, cs)
            else:
                t.setItem(r, COL_CS, QTableWidgetItem(""))
            src = QTableWidgetItem(f"{os.path.basename(row['inp']['path'])}  #{tr.id}")
            src.setToolTip(row["inp"]["path"])
            t.setItem(r, COL_SRC, src)
        self._refresh()

    def _collect(self):
        """Read widget values back into self.rows."""
        t = self.table
        if t.rowCount() != len(self.rows):
            return
        for r, row in enumerate(self.rows):
            row["use"] = t.cellWidget(r, COL_USE).isChecked()
            row["language"] = t.cellWidget(r, COL_LANG).code()
            row["name"] = t.cellWidget(r, COL_NAME).text()
            row["default"] = t.cellWidget(r, COL_DEF).isChecked()
            row["forced"] = t.cellWidget(r, COL_FORCED).isChecked()
            try:
                row["delay"] = int(t.cellWidget(r, COL_DELAY).text() or 0)
            except ValueError:
                row["delay"] = 0
            cs = t.cellWidget(r, COL_CS)
            if cs is not None:
                txt = cs.currentText().strip()
                row["charset"] = "" if txt in ("", "Auto") else txt

    def _move(self, d):
        r = self.table.currentRow()
        n = r + d
        if r < 0 or not (0 <= n < len(self.rows)):
            return
        self._collect()
        self.rows[r], self.rows[n] = self.rows[n], self.rows[r]
        self._fill_table()
        self.table.selectRow(n)

    def _set_all_use(self, v):
        for r in range(self.table.rowCount()):
            self.table.cellWidget(r, COL_USE).setChecked(v)

    def keep_only(self):
        self._collect()
        s = self.ctx.settings
        s.batch_audio_keep, s.batch_sub_keep = self.keep_audio.text(), self.keep_subs.text()
        s.save()
        rules = {"audio": parse_list(self.keep_audio.text()), "subtitles": parse_list(self.keep_subs.text())}
        dropped = 0
        for r in self.rows:
            langs = rules.get(r["track"].type)
            if not langs:
                continue
            keep = r["language"] in langs or r["language"] == "und"
            if r["use"] and not keep:
                dropped += 1
            r["use"] = keep
        audio = [r for r in self.rows if r["track"].type == "audio"]
        if audio and not any(r["use"] for r in audio):
            for r in audio:
                r["use"] = True
            self.ctx.toast("No audio in those languages, kept all audio", error=True)
        if self.rows:
            self.apply_smart_defaults()
            if rules["audio"] or rules["subtitles"]:
                self._reorder_by_language(rules)
        self._fill_table()
        if dropped:
            self.ctx.toast(f"Unticked {dropped} track{'s' if dropped != 1 else ''}")

    def _reorder_by_language(self, rules):
        tr = {"video": 0, "audio": 1, "subtitles": 2}
        pos = {id(r): i for i, r in enumerate(self.rows)}

        def key(r):
            ty = r["track"].type
            prefs = rules.get(ty) or []
            rank = prefs.index(r["language"]) if r["language"] in prefs else len(prefs)
            return (tr.get(ty, 3), not r["use"], rank if ty in rules else 0, pos[id(r)])
        self.rows.sort(key=key)

    def apply_smart_defaults(self):
        s = self.ctx.settings
        pa, ps = parse_list(s.pref_audio_langs), parse_list(s.pref_sub_langs)

        def pick(kind, prefs):
            cands = [r for r in self.rows if r["use"] and r["track"].type == kind and not r["forced"]]
            for lang in prefs:
                for r in cands:
                    if r["language"] == lang:
                        return r, cands
            return None, cands

        audio, acands = pick("audio", pa)
        if audio:
            for r in acands:
                r["default"] = r is audio
        default_audio = audio or next((r for r in acands if r["default"]), None)
        sub, scands = pick("subtitles", ps)
        if scands:
            audio_ok = default_audio is not None and default_audio["language"] in ps
            for r in scands:
                r["default"] = (r is sub) and not audio_ok
        vids = [r for r in self.rows if r["use"] and r["track"].type == "video"]
        if vids and not any(r["default"] for r in vids):
            vids[0]["default"] = True

    # ---------- attachments ----------
    def _fill_attachments(self):
        prev = {}
        for i in range(self.att_list.count()):
            it = self.att_list.item(i)
            prev[it.data(Qt.UserRole)] = it.checkState()
        self.att_list.clear()
        for idx, inp in enumerate(self.inputs):
            if inp["append"]:
                continue
            for a in inp["mf"].attachments:
                key = ("src", id(inp), a.id)
                it = QListWidgetItem(f"{a.file_name}    {a.mime}, {file_size_text(a.size)}   "
                                     f"(from {os.path.basename(inp['path'])})")
                it.setData(Qt.UserRole, key)
                it.setData(Qt.UserRole + 1, (idx, a.id))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(prev.get(key, Qt.Checked))
                self.att_list.addItem(it)
        for p in self.extra_attach:
            key = ("file", p)
            it = QListWidgetItem(f"{os.path.basename(p)}    (new: {p})")
            it.setData(Qt.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(prev.get(key, Qt.Checked))
            self.att_list.addItem(it)
        self.tabs.setTabText(1, f"Attachments ({self.att_list.count()})" if self.att_list.count() else "Attachments")

    def _add_attachments(self):
        files = pick_files(self, self.ctx.settings, "Add attachments",
                           "Fonts and images (*.ttf *.otf *.ttc *.jpg *.jpeg *.png *.webp);;All files (*)")
        self._drop_attachments(files)

    def _drop_attachments(self, files):
        for f in files:
            if os.path.isfile(f) and f not in self.extra_attach:
                self.extra_attach.append(f)
        self._fill_attachments()

    def _remove_attachment(self):
        it = self.att_list.currentItem()
        if it and it.data(Qt.UserRole)[0] == "file":
            self.extra_attach.remove(it.data(Qt.UserRole)[1])
            self._fill_attachments()

    # ---------- output ----------
    def _auto_output(self):
        first = next((i for i in self.inputs if not i["append"]), None)
        if not first:
            if not self._output_edited:
                self.out_edit.clear()
            return
        if self._output_edited and self.out_edit.text():
            return
        folder = self.ctx.settings.mux_out_dir or os.path.dirname(first["path"])
        base = first["mf"].base
        cand = os.path.join(folder, base + ".mkv")
        if os.path.normcase(os.path.abspath(cand)) in {os.path.normcase(os.path.abspath(i["path"])) for i in self.inputs}:
            cand = os.path.join(folder, base + " (muxed).mkv")
        self.out_edit.setText(os.path.normpath(cand))

    def _browse_out(self):
        start = self.out_edit.text() or self.ctx.settings.last_dir
        f, _ = QFileDialog.getSaveFileName(self, "Save as", start, "Matroska (*.mkv);;WebM (*.webm);;"
                                                                    "Matroska audio (*.mka);;Matroska subtitles (*.mks)")
        if f:
            self.out_edit.setText(os.path.normpath(f))
            self._output_edited = True

    def _browse_chapters(self):
        f, _ = QFileDialog.getOpenFileName(self, "Chapters file", self.ctx.settings.last_dir,
                                           "Chapters (*.xml *.txt *.cue);;All files (*)")
        if f:
            self.chap_edit.setText(os.path.normpath(f))

    # ---------- spec ----------
    def build_spec(self):
        self._collect()
        spec = {"output": self.out_edit.text().strip(), "title": self.title_edit.text(), "inputs": [],
                "attach_files": [], "chapters_file": self.chap_edit.text().strip()}
        mode = self.split_mode.currentData()
        if mode and self.split_val.text().strip():
            spec["split"] = mode + self.split_val.text().strip()
        checked_src = set()
        for i in range(self.att_list.count()):
            it = self.att_list.item(i)
            key = it.data(Qt.UserRole)
            if it.checkState() == Qt.Checked:
                if key[0] == "file":
                    spec["attach_files"].append(key[1])
                else:
                    checked_src.add(it.data(Qt.UserRole + 1))
        for idx, inp in enumerate(self.inputs):
            d = {"path": inp["path"], "append": inp["append"], "chapters": inp.get("chapters", True),
                 "tags": inp.get("tags", True)}
            if not inp["append"]:
                d["tracks"] = []
                for row in self.rows:
                    if row["inp"] is inp:
                        t = row["track"]
                        d["tracks"].append({"id": t.id, "type": t.type, "use": row["use"],
                                            "language": row["language"], "name": row["name"],
                                            "default": row["default"], "forced": row["forced"],
                                            "delay": row["delay"], "charset": row["charset"]})
                d["attachments"] = [{"id": a.id, "use": (idx, a.id) in checked_src} for a in inp["mf"].attachments]
            spec["inputs"].append(d)
        idx_of = {id(inp): i for i, inp in enumerate(self.inputs)}
        spec["track_order"] = [[idx_of[id(r["inp"])], r["track"].id] for r in self.rows if r["use"]]
        return spec

    def _validate(self, spec):
        if not self.inputs:
            return "Add at least one source file."
        if not any(r["use"] for r in self.rows):
            return "No tracks are selected."
        if not spec["output"]:
            return "Choose an output file."
        out = os.path.normcase(os.path.abspath(spec["output"]))
        if out in {os.path.normcase(os.path.abspath(i["path"])) for i in self.inputs}:
            return "The output file cannot be one of the source files."
        if not os.path.isdir(os.path.dirname(os.path.abspath(spec["output"]))):
            return "The output folder does not exist."
        return None

    def _show_command(self):
        spec = self.build_spec()
        cmd = quote_cmd(self.ctx.engine.tool("mkvmerge") or "mkvmerge", build_mux_args(spec)) if self.inputs else ""
        dlg = QDialog(self)
        dlg.setWindowTitle("mkvmerge command")
        dlg.resize(760, 300)
        lay = QVBoxLayout(dlg)
        txt = QPlainTextEdit(cmd)
        txt.setReadOnly(True)
        lay.addWidget(txt)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()

    def start(self):
        if not self.ctx.engine.ok:
            self.ctx.need_engine()
            return
        spec = self.build_spec()
        err = self._validate(spec)
        if err:
            QMessageBox.information(self, "Multiplex", err)
            return
        if os.path.exists(spec["output"]):
            box = QMessageBox(QMessageBox.Question, "File exists",
                              f"{os.path.basename(spec['output'])} already exists.", parent=self)
            b_over = box.addButton("Overwrite", QMessageBox.DestructiveRole)
            b_ren = box.addButton("Save as new name", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() == b_ren:
                spec["output"] = unique_path(spec["output"])
                self.out_edit.setText(spec["output"])
            elif box.clickedButton() != b_over:
                return
        title = os.path.basename(spec["output"])
        self.ctx.queue.add(Job("mux", title, build_mux_args(spec), output=spec["output"],
                               delete_on_fail=spec["output"]))
        self.ctx.toast(f"Queued: {title}")
        self._output_edited = False

    # ---------- state ----------
    def _refresh(self):
        has = bool(self.inputs)
        self.src_drop_hint.setVisible(not has)
        self.src_list.setVisible(has)
        self.src_status.setText(f"  reading {self._pending} file(s)..." if self._pending else "")
        if self.table.rowCount() == len(self.rows) and self.rows:
            n = sum(1 for r in range(self.table.rowCount())
                    if self.table.cellWidget(r, COL_USE) and self.table.cellWidget(r, COL_USE).isChecked())
        else:
            n = sum(1 for r in self.rows if r["use"])
        kinds = {}
        for r in self.rows:
            kinds[r["track"].type] = kinds.get(r["track"].type, 0) + 1
        parts = [f"{v} {TYPE_LABEL.get(k, k).lower()}" for k, v in kinds.items()]
        self.summary.setText(f"{n} of {len(self.rows)} tracks selected" + (f"  ({', '.join(parts)})" if parts else "")
                             if self.rows else "")
        self.btn_go.setEnabled(has)
        self.btn_append.setEnabled(has)
        self.tabs.setTabText(0, f"Tracks ({len(self.rows)})" if self.rows else "Tracks")


class MultiplexPage(QWidget):
    """Switch between one-file muxing and batch episodes."""

    def __init__(self, app_ctx, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(22, 14, 22, 4)
        top.setSpacing(0)
        self.single = MuxPage(app_ctx)
        self.batch = BatchMuxPage(app_ctx)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.single)
        self.stack.addWidget(self.batch)
        grp = QButtonGroup(self)
        for i, text in enumerate(("One file", "Batch episodes")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setObjectName("SegLeft" if i == 0 else "SegRight")
            grp.addButton(b, i)
            top.addWidget(b)
        grp.button(0).setChecked(True)
        grp.idClicked.connect(self.stack.setCurrentIndex)
        self.seg = grp
        top.addStretch(1)
        lay.addLayout(top)
        lay.addWidget(self.stack, 1)

    def show_batch(self, on=True):
        self.seg.button(1 if on else 0).setChecked(True)
        self.stack.setCurrentIndex(1 if on else 0)

    def add_files(self, paths, append=False):
        self.show_batch(False)
        self.single.add_files(paths, append)
