"""Batch multiplex: many episodes + a folder of subtitles, same language rules for all."""
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIntValidator
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QRadioButton, QScrollArea,
                               QSizePolicy, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ..batch import AUDIO_EXTS, Rules, episode_key, match_subtitles, plan_episode
from ..commands import build_mux_args
from ..jobs import Job
from ..mediainfo import identify
from .fileinfo import TYPE_NAME
from .icons import icon
from .theme import C
from .widgets import (DropFilter, LangCombo, LangListEdit, add_shortcuts, card, expand_paths, page_header, pick_files,
                      pick_folder, run_async)

VIDEO_EXTS = ("mkv", "mp4", "m4v", "avi", "ts", "m2ts", "mov", "webm")
SUB_EXTS = ("srt", "ass", "ssa", "sup", "sub", "idx", "vtt", "usf")
EXTRA_EXTS = SUB_EXTS + AUDIO_EXTS
DEFAULT_SUB = [("smart", "Smart: preferred, but not when audio is already that language"),
               ("first", "Always the first preferred subtitle"), ("none", "No default subtitle")]


class BatchMuxPage(QWidget):
    def __init__(self, app_ctx, parent=None):
        super().__init__(parent)
        self.ctx = app_ctx
        s = app_ctx.settings
        self.episodes = {}       # path -> MediaFile
        self.subs = {}           # added files (subtitles and audio): path -> MediaFile
        self.overrides = {}      # episode path -> {"source:track_id": keep?}
        self.plans = {}          # episode path -> (spec, summary)
        self.unchecked = set()   # episodes the user excluded
        self._pending = 0

        # The page scrolls when the window is too low for everything (small screens with "More rules" open)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setMinimumWidth(1)      # never wider than the window: squeeze, don't scroll sideways
        scroll.setWidget(body)
        outer.addWidget(scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(22, 8, 22, 12)
        root.setSpacing(12)
        root.addLayout(page_header("Batch episodes",
                                   "Add a season plus its subtitle and audio files. They are matched by S01E02, 1x02 or "
                                   "file name, unwanted tracks are dropped, and every episode is muxed with the same "
                                   "rules. Tick or untick any track below to override."))

        # Rules
        rc, rl = card("Rules", "applied to every episode")
        g = QGridLayout()       # everyday rules, always visible
        g2 = QGridLayout()      # the rest, behind "More rules"
        for grid in (g, g2):
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)
            grid.setColumnMinimumWidth(0, 112)
            grid.setColumnMinimumWidth(2, 112)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(3, 1)
        g.addWidget(self._lab("Keep audio", "audio"), 0, 0)
        self.audio_keep = LangListEdit(s.batch_audio_keep)
        self.audio_keep.setPlaceholderText("all  (or e.g. bul, eng)")
        self.audio_keep.setToolTip("Audio languages to keep, in order of preference. The first one becomes Default.\n"
                                   "If an episode has none of them, all its audio is kept.")
        g.addWidget(self.audio_keep, 0, 1)
        g.addWidget(self._lab("Keep subtitles", "subtitles"), 0, 2)
        self.sub_keep = LangListEdit(s.batch_sub_keep)
        self.sub_keep.setPlaceholderText("all  (or e.g. bul, eng)")
        self.sub_keep.setToolTip("Embedded subtitle languages to keep, in order of preference. Added subtitle files "
                                 "are always kept.")
        g.addWidget(self.sub_keep, 0, 3)
        self.keep_und = QCheckBox("Keep tracks without a language (und)")
        self.keep_und.setChecked(s.batch_keep_und)
        g2.addWidget(self.keep_und, 1, 3)
        self.drop_sdh = QCheckBox("Remove SDH / CC / Signs")
        self.drop_sdh.setChecked(s.batch_drop_sdh)
        self.drop_sdh.setToolTip("Hearing-impaired and signs-only subtitles: the Matroska hearing-impaired flag, or "
                                 "SDH, HI, CC, Signs or Songs in the track or file name\n(e.g. 'English SDH', "
                                 "'English[CC]', 'English[Signs]', 'Signs & Songs').\nThe only subtitle of a language is never removed.")
        self.drop_img = QCheckBox("Remove PGS / image subs")
        self.drop_img.setChecked(s.batch_drop_image_subs)
        self.drop_img.setToolTip("Blu-ray PGS, DVD VobSub and DVB bitmap subtitles (not text).\n"
                                 "The only subtitle of a language is never removed.")
        self.one_per_lang = QCheckBox("Only one subtitle per language")
        self.one_per_lang.setChecked(s.batch_one_sub_per_lang)
        self.one_per_lang.setToolTip("Keeps the best one per language: your added file first, then text over PGS, "
                                     "then regular over SDH.\nForced subtitles are separate and stay.")
        self.drop_subs = QCheckBox("Remove all embedded subtitles")
        self.drop_subs.setChecked(s.batch_drop_embedded_subs)
        g2.addWidget(self._lab("Subtitle clean-up", "subtitles"), 2, 0)
        g2.addWidget(self.drop_sdh, 2, 1)
        g2.addWidget(self.drop_img, 2, 3)
        g2.addWidget(self.one_per_lang, 3, 1)
        g2.addWidget(self.drop_subs, 3, 3)
        g2.addWidget(QLabel("Default subtitle"), 1, 0)
        self.default_sub = QComboBox()
        for key, text in DEFAULT_SUB:
            self.default_sub.addItem(text, key)
        self.default_sub.setCurrentIndex(max(0, self.default_sub.findData(s.batch_default_sub)))
        g2.addWidget(self.default_sub, 1, 1)
        g2.addWidget(self._lab("Added audio", "audio"), 0, 0)
        self.ext_audio_lang = LangCombo(s.batch_ext_audio_lang)
        self.ext_audio_lang.setToolTip("Language for added audio files (dubs) when the file name doesn't say.")
        g2.addWidget(self.ext_audio_lang, 0, 1)
        g2.addWidget(QLabel("Name / delay"), 0, 2)
        ar = QHBoxLayout()
        self.ext_audio_name = QLineEdit(s.batch_ext_audio_name)
        self.ext_audio_name.setPlaceholderText("optional, e.g. Български дублаж")
        self.ext_audio_delay = QLineEdit(str(s.batch_ext_audio_delay or "0"))
        self.ext_audio_delay.setValidator(QIntValidator(-3600000, 3600000))
        self.ext_audio_delay.setMaximumWidth(90)
        self.ext_audio_delay.setToolTip("Shift added audio by this many milliseconds (negative = earlier) "
                                        "if the dub is out of sync.")
        ar.addWidget(self.ext_audio_name, 1)
        ar.addWidget(self.ext_audio_delay)
        ar.addWidget(QLabel("ms"))
        g2.addLayout(ar, 0, 3)
        g.addWidget(self._lab("Added subtitles", "subtitles"), 1, 0)
        self.ext_lang = LangCombo(s.batch_ext_lang)
        self.ext_lang.setToolTip("Used when the subtitle file name has no language (Show.S01E02.bg.srt says bul).")
        g.addWidget(self.ext_lang, 1, 1)
        g.addWidget(QLabel("Track name"), 1, 2)
        self.ext_name = QLineEdit(s.batch_ext_name)
        self.ext_name.setPlaceholderText("optional, e.g. Български")
        g.addWidget(self.ext_name, 1, 3)
        # By track number (position among that type: Audio 1, Audio 2, Subtitles 1 ...)
        self.audio_num_mode, self.audio_nums = self._num_row(s.batch_audio_by_num, s.batch_audio_nums, "audio")
        self.sub_num_mode, self.sub_nums = self._num_row(s.batch_sub_by_num, s.batch_sub_nums, "subtitles")
        g2.addWidget(self._lab("Audio by track", "audio"), 4, 0)
        na = QHBoxLayout()
        na.addWidget(self.audio_num_mode)
        na.addWidget(self.audio_nums, 1)
        g2.addLayout(na, 4, 1)
        g2.addWidget(self._lab("Subs by track", "subtitles"), 4, 2)
        ns = QHBoxLayout()
        ns.addWidget(self.sub_num_mode)
        ns.addWidget(self.sub_nums, 1)
        g2.addLayout(ns, 4, 3)
        self.reorder = QCheckBox("Order tracks by language preference (added files first)")
        self.reorder.setChecked(s.batch_reorder)
        g2.addWidget(self.reorder, 5, 1, 1, 3)
        rl.addLayout(g)
        rc.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        mrow = QHBoxLayout()
        self.btn_more = QPushButton("More rules", objectName="Expander")
        self.btn_more.setCheckable(True)
        self.btn_more.setChecked(bool(s.batch_more_rules))
        self.btn_more.setCursor(Qt.PointingHandCursor)
        self.btn_more.setToolTip("Added audio, default subtitle, SDH / PGS clean-up, tracks by number, track order")
        self.more_summary = QLabel("", objectName="Muted")
        mrow.addWidget(self.btn_more)
        mrow.addWidget(self.more_summary, 1)
        rl.addLayout(mrow)
        self.more = QWidget()
        g2.setContentsMargins(0, 0, 0, 0)
        self.more.setLayout(g2)
        rl.addWidget(self.more)
        self.btn_more.toggled.connect(self._toggle_more)
        self._toggle_more(self.btn_more.isChecked(), save=False)
        root.addWidget(rc)

        # Episodes
        ec, el = card("Episodes")
        self.status = QLabel("", objectName="Muted")
        ec.title_row.addWidget(self.status)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Episode / track", "Now in the file", "After muxing", "Notes"])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setMinimumHeight(190)
        hh = self.tree.header()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        for col, w in ((0, 300), (1, 250), (2, 250)):
            self.tree.setColumnWidth(col, w)
        self.hint = QLabel("Drop episodes, subtitle files, audio files or whole folders here", objectName="DropHint",
                           alignment=Qt.AlignCenter)
        el.addWidget(self.tree, 1)
        el.addWidget(self.hint, 1)
        self.unmatched = QLabel("", objectName="Muted")
        self.unmatched.setWordWrap(True)
        self.unmatched.setStyleSheet(f"color: {C['warn']};")
        el.addWidget(self.unmatched)
        br = QHBoxLayout()
        self.btn_eps = QPushButton("Add files")
        self.btn_eps.setIcon(icon("plus", C["text"], 18))
        self.btn_eps.setToolTip("Episodes, subtitle files and audio files (dubs: .ac3 .eac3 .aac .dts .mka .flac "
                                ".opus ...) in one go.\nZeroStudio tells them apart and matches subtitles and audio "
                                "to their episodes.  Ctrl+O")
        self.btn_folder = QPushButton("Add folder")
        self.btn_folder.setIcon(icon("folder", C["text"], 18))
        self.btn_folder.setToolTip("Adds every video, subtitle and audio file inside (subfolders too)")
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setToolTip("Remove the selected episodes or added files from the list (Delete)")
        self.btn_clear = QPushButton("Clear")
        for b in (self.btn_eps, self.btn_folder, self.btn_remove, self.btn_clear):
            br.addWidget(b)
        br.addStretch(1)
        self.btn_reset = QPushButton("Undo my ticks", objectName="Flat")
        self.btn_reset.setToolTip("Forget the tracks you ticked or unticked by hand and use the rules again")
        self.btn_reset.clicked.connect(self._reset_overrides)
        br.addWidget(self.btn_reset)
        self.btn_expand = QPushButton("Expand all", objectName="Flat")
        self.btn_collapse = QPushButton("Collapse all", objectName="Flat")
        self.btn_expand.clicked.connect(self.tree.expandAll)
        self.btn_collapse.clicked.connect(self.tree.collapseAll)
        br.addWidget(self.btn_expand)
        br.addWidget(self.btn_collapse)
        el.addLayout(br)
        root.addWidget(ec, 1)

        # Output
        oc, ol = card()
        orow = QHBoxLayout()
        orow.addWidget(QLabel("Save to"))
        self.rb_sub = QRadioButton('Subfolder "muxed" next to the episodes')
        self.rb_custom = QRadioButton("Folder")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_sub)
        grp.addButton(self.rb_custom)
        (self.rb_custom if s.batch_out_mode == "custom" else self.rb_sub).setChecked(True)
        self.out_dir = QLineEdit(s.batch_out_dir)
        self.out_dir.setPlaceholderText("Choose a folder")
        self.btn_out = QPushButton("Browse")
        orow.addWidget(self.rb_sub)
        orow.addWidget(self.rb_custom)
        orow.addWidget(self.out_dir, 1)
        orow.addWidget(self.btn_out)
        ol.addLayout(orow)
        arow = QHBoxLayout()
        self.summary = QLabel("", objectName="Muted")
        arow.addWidget(self.summary, 1)
        self.btn_go = QPushButton("Mux episodes", objectName="Primary")
        self.btn_go.setToolTip("Ctrl+Enter")
        self.btn_go.setIcon(icon("play", C["on_accent"], 18))
        arow.addWidget(self.btn_go)
        ol.addLayout(arow)
        root.addWidget(oc)

        # Signals
        self._timer = QTimer(self, singleShot=True, interval=250, timeout=self.replan)
        for w in (self.audio_keep, self.sub_keep, self.ext_name, self.ext_audio_name, self.ext_audio_delay,
                  self.audio_nums, self.sub_nums):
            w.textChanged.connect(self._timer.start)
        self.audio_num_mode.currentIndexChanged.connect(self._timer.start)
        self.sub_num_mode.currentIndexChanged.connect(self._timer.start)
        for w in (self.keep_und, self.drop_subs, self.reorder, self.drop_sdh, self.drop_img, self.one_per_lang):
            w.toggled.connect(self._timer.start)
        self.default_sub.currentIndexChanged.connect(self._timer.start)
        self.ext_lang.currentTextChanged.connect(self._timer.start)
        self.ext_audio_lang.currentTextChanged.connect(self._timer.start)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        def pat(exts):
            return " ".join("*." + e for e in exts)
        self.btn_eps.clicked.connect(lambda: self.add_paths(pick_files(
            self, s, "Add episodes, subtitles and audio",
            f"Episodes, subtitles and audio ({pat(VIDEO_EXTS + EXTRA_EXTS)});;Video files ({pat(VIDEO_EXTS)});;"
            f"Subtitles ({pat(SUB_EXTS)});;Audio ({pat(AUDIO_EXTS)});;All files (*)")))
        self.btn_folder.clicked.connect(self._add_folder)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_clear.clicked.connect(self._clear)
        self.btn_out.clicked.connect(self._browse_out)
        self.btn_go.clicked.connect(self.start)
        self.tree.itemChanged.connect(self._item_changed)
        for w in (self, self.tree):
            DropFilter(w, lambda paths: self.add_paths(expand_paths(paths, VIDEO_EXTS + EXTRA_EXTS)))
        add_shortcuts(self, add=self.btn_eps.click, start=self.btn_go.click, remove=(self.tree, self._remove))
        self._refresh()

    def _toggle_more(self, on, save=True):
        self.more.setVisible(on)
        self.btn_more.setIcon(icon("chevron_down" if on else "chevron_right", C["muted"], 16))
        self._update_more_summary()
        if save:
            self.ctx.settings.batch_more_rules = bool(on)
            try:
                self.ctx.settings.save()
            except OSError:
                pass

    def _update_more_summary(self):
        """While "More rules" is closed, say which of them are active so nothing works behind your back."""
        if self.btn_more.isChecked():
            self.more_summary.setText("")
            return
        on = []
        for cb, text in ((self.drop_sdh, "remove SDH / CC / Signs"), (self.drop_img, "remove PGS"),
                         (self.one_per_lang, "one subtitle per language"), (self.drop_subs, "remove embedded subtitles")):
            if cb.isChecked():
                on.append(text)
        if not self.keep_und.isChecked():
            on.append("drop tracks without a language")
        if self.default_sub.currentData() != "smart":
            on.append("default subtitle: " + ("first preferred" if self.default_sub.currentData() == "first" else "none"))
        for combo, edit, what in ((self.audio_num_mode, self.audio_nums, "audio"), (self.sub_num_mode, self.sub_nums, "subtitle")):
            if combo.currentData() != "off" and edit.text().strip():
                on.append(f"{'keep only' if combo.currentData() == 'keep' else 'remove'} {what} tracks {edit.text().strip()}")
        if (self.ext_audio_delay.text() or "0").strip() not in ("0", "", "-0"):
            on.append(f"added audio {self.ext_audio_delay.text().strip()} ms")
        if not self.reorder.isChecked():
            on.append("original track order")
        self.more_summary.setText("active: " + ", ".join(on) if on else "added audio, default subtitle, clean-up, tracks by number")
        self.more_summary.setStyleSheet(f"color: {C['accent_hi'] if on else C['muted']};")

    NUM_MODES = [("off", "Use languages"), ("keep", "Keep only tracks"), ("drop", "Remove tracks")]

    def _num_row(self, mode, nums, kind):
        combo = QComboBox()
        for key, text in self.NUM_MODES:
            combo.addItem(text, key)
        combo.setCurrentIndex(max(0, combo.findData(mode)))
        edit = QLineEdit(nums)
        edit.setPlaceholderText("e.g. 1, 3 or 2-4")
        what = "audio" if kind == "audio" else "subtitle"
        tip = (f"Pick {what} tracks by number in every episode: 1 = first {what} track, 2 = second ...\n"
               f"The numbers are shown in the list below (e.g. '{'Audio' if kind == 'audio' else 'Subtitles'} 2').\n"
               f"When this is on, the language list only decides order and default for {what}.")
        combo.setToolTip(tip)
        edit.setToolTip(tip)
        combo.setMinimumWidth(150)

        def update():
            edit.setEnabled(combo.currentData() != "off")
        combo.currentIndexChanged.connect(update)
        update()
        return combo, edit

    @staticmethod
    def _lab(text, kind):
        lab = QLabel(text)
        lab.setStyleSheet(f"color: {C[kind]}; font-weight: 600;")
        return lab

    # ---------- loading ----------
    def _add_folder(self):
        d = pick_folder(self, self.ctx.settings, "Add folder")
        if d:
            self.add_paths(expand_paths([d], VIDEO_EXTS + EXTRA_EXTS))

    def add_paths(self, paths):
        if not paths:
            return
        if not self.ctx.engine.ok:
            self.ctx.need_engine()
            return
        mm = self.ctx.engine.tool("mkvmerge")
        for p in paths:
            ext = os.path.splitext(p)[1].lower().lstrip(".")
            if ext == "sub" and os.path.exists(os.path.splitext(p)[0] + ".idx"):
                continue   # VobSub: mkvmerge reads the .idx, the .sub is its data file
            if p in self.episodes or p in self.subs:
                continue
            is_sub = ext in EXTRA_EXTS
            self._pending += 1
            run_async(lambda p=p: identify(mm, p), lambda mf, err, p=p, s=is_sub: self._identified(p, mf, err, s))
        self._refresh()

    def _identified(self, path, mf, err, is_sub):
        self._pending -= 1
        if err:
            self.ctx.toast(f"Skipped {os.path.basename(path)}: {err}", error=True)
        elif is_sub:
            self.subs[path] = mf
        else:
            self.episodes[path] = mf
        if self._pending == 0:
            self.replan()
        else:
            self._refresh()

    def _remove(self):
        for it in self.tree.selectedItems():
            path = it.data(0, Qt.UserRole)
            if path in self.episodes:
                del self.episodes[path]
            elif path in self.subs:
                del self.subs[path]
        self.replan()

    def _clear(self):
        self.episodes, self.subs, self.plans = {}, {}, {}
        self.overrides.clear()
        self.unchecked.clear()
        self.replan()

    # ---------- planning ----------
    def rules(self):
        self._save_prefs()
        return Rules.from_settings(self.ctx.settings)

    def output_for(self, path):
        base = os.path.splitext(os.path.basename(path))[0] + ".mkv"
        if self.rb_custom.isChecked() and self.out_dir.text().strip():
            return os.path.join(self.out_dir.text().strip(), base)
        return os.path.join(os.path.dirname(path), "muxed", base)

    def _sorted_episodes(self):
        return sorted(self.episodes, key=lambda p: (episode_key(p) or (999, 999), os.path.basename(p).lower()))

    def replan(self):
        rules = self.rules()
        self._update_more_summary()
        outputs = set()
        eps = self._sorted_episodes()
        matched, unmatched = match_subtitles(eps, sorted(self.subs))
        self.plans = {}
        expanded = {self.tree.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.tree.topLevelItemCount())
                    if self.tree.topLevelItem(i).isExpanded()}
        first_time = self.tree.topLevelItemCount() == 0
        scroll = self.tree.verticalScrollBar().value()
        self.tree.blockSignals(True)
        self.tree.clear()
        bold = QFont(self.tree.font())
        bold.setBold(True)
        for e in eps:
            mf = self.episodes[e]
            ext = [(p, self.subs[p]) for p in matched.get(e, [])]
            out = self.output_for(e)        # two episodes with the same name must not share one output file
            root_, ext_, n_ = os.path.splitext(out)[0], os.path.splitext(out)[1], 2
            while os.path.normcase(out) in outputs:
                out, n_ = f"{root_} ({n_}){ext_}", n_ + 1
            outputs.add(os.path.normcase(out))
            spec, summ = plan_episode(mf, ext, rules, out, self.overrides.get(e))
            self.plans[e] = (spec, summ)
            it = QTreeWidgetItem(self.tree)
            it.setText(0, os.path.basename(e))
            it.setFont(0, bold)
            it.setToolTip(0, f"{e}\n-> {spec['output']}")
            it.setData(0, Qt.UserRole, e)
            before_a = [t.language for t in mf.tracks if t.type == "audio"]
            before_s = [t.language + ("(f)" if t.forced else "") for t in mf.tracks if t.type == "subtitles"]
            it.setText(1, f"A: {' '.join(before_a) or '-'}   S: {' '.join(before_s) or '-'}")
            it.setText(2, f"A: {' '.join(summ['audio']) or '-'}   S: {' '.join(summ['subs']) or '-'}")
            it.setToolTip(1, "Audio and subtitle languages in the episode now")
            it.setToolTip(2, "After muxing, in the new order.  * = default   + = added file   (f) = forced")
            it.setForeground(2, QColor(C["accent_hi"]))
            notes = []
            if summ["dropped"]:
                notes.append(f"{summ['dropped']} track{'s' if summ['dropped'] != 1 else ''} removed")
            added_s = sum(1 for x in summ["tracks"] if x["external"] and x["use"] and x["track"].type == "subtitles")
            added_a = sum(1 for x in summ["tracks"] if x["external"] and x["use"] and x["track"].type == "audio")
            if added_a:
                notes.append(f"{added_a} audio added")
            if added_s:
                notes.append(f"{added_s} subtitle{'s' if added_s != 1 else ''} added")
            if any(x["manual"] for x in summ["tracks"]):
                notes.append("your changes")
            warn = list(summ["notes"])
            if not ext and self.subs:
                warn.append("no added file matched")
            it.setText(3, "; ".join(notes + warn))
            if warn:
                it.setForeground(3, QColor(C["warn"]))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked if e in self.unchecked else Qt.Checked)
            self._add_track_rows(it, summ["tracks"], e)
            it.setExpanded(e in expanded or (first_time and len(eps) <= 2))
        self.tree.blockSignals(False)
        self.tree.verticalScrollBar().setValue(scroll)
        if unmatched:
            names = ", ".join(os.path.basename(u) for u in unmatched[:4]) + (" ..." if len(unmatched) > 4 else "")
            self.unmatched.setText(f"{len(unmatched)} added file(s) did not match an episode: {names}")
        else:
            self.unmatched.setText("")
        self._refresh()

    REASONS = {"language": "language not kept", "SDH": "SDH", "CC": "CC", "Signs": "Signs", "PGS/image": "PGS / image",
               "embedded subs off": "embedded subs removed", "by you": "by you",
               "track number": "track number"}
    # "duplicate eng" from the one-per-language rule is shown as is

    def _add_track_rows(self, parent, tracks, episode):
        strike = QFont(self.tree.font())
        strike.setStrikeOut(True)
        for x in tracks:
            t = x["track"]
            ch = QTreeWidgetItem(parent)
            det = t.details()
            tags = []
            if x["sdh"]:
                tags.append(x["sdh"])
            if x["image"]:
                tags.append("PGS/image")
            if x["external"]:
                ch.setText(0, f"+ {os.path.basename(x['path'])}")
                ch.setData(0, Qt.UserRole, x["path"])
                ch.setToolTip(0, x["path"])
                ch.setText(1, f"not in the file (new {'audio' if t.type == 'audio' else 'subtitle'})")
                ch.setForeground(1, QColor(C["muted"]))
            else:
                label = TYPE_NAME.get(t.type, t.type) + (f" {x['type_pos']}" if x["type_pos"] else "")
                ch.setText(0, f"{label}   {t.codec}" + (f"  {det}" if det else ""))
                flags = [f for f, on in (("default", t.default), ("forced", t.forced)) if on] + tags
                ch.setText(1, t.language + (f"  \u201c{t.name}\u201d" if t.name else "") +
                           (f"  ({', '.join(flags)})" if flags else ""))
                ch.setToolTip(1, ch.text(1))
            ch.setForeground(0, QColor(C.get(t.type, C["other"])))
            ch.setData(0, Qt.UserRole + 1, (episode, x["key"]))
            ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
            ch.setCheckState(0, Qt.Checked if x["use"] else Qt.Unchecked)
            ch.setToolTip(0, (x["path"] + "\n" if x["external"] else "") +
                          "Tick or untick to keep or remove this track. Right-click to do the same in all episodes.")
            if x["use"]:
                flags = [f for f, on in (("default", x["default"]), ("forced", x["forced"])) if on]
                if x["external"]:
                    flags += tags
                after = f"#{x['position']}  {x['language']}" + (f"  \u201c{x['name']}\u201d" if x["name"] else "")
                if flags:
                    after += f"  ({', '.join(flags)})"
                if x["external"]:
                    after += "  added"
                    if x["charset"]:
                        after += f", {x['charset']} -> UTF-8"
                    if x["delay"]:
                        after += f", {x['delay']:+d} ms"
                if x["manual"]:
                    after += "  (by you)"
                changed = (x["external"] or x["manual"] or x["default"] != t.default or x["language"] != t.language)
                ch.setText(2, after)
                ch.setToolTip(2, after)
                ch.setForeground(2, QColor(C["accent_hi"] if changed else C["text"]))
            else:
                why = self.REASONS.get(x["reason"], x["reason"])
                ch.setText(2, "removed" + (f"  ({why})" if why else ""))
                ch.setFont(2, strike)
                ch.setForeground(2, QColor(C["bad"]))
                ch.setForeground(1, QColor(C["muted"]))

    def _set_override(self, episode, key, keep):
        self.overrides.setdefault(episode, {})[key] = keep

    def _reset_overrides(self):
        self.overrides.clear()
        self.replan()

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        data = item.data(0, Qt.UserRole + 1) if item else None
        if not data:
            return
        episode, key = data
        x = next((t for t in self.plans[episode][1]["tracks"] if t["key"] == key), None)
        if not x:
            return
        m = QMenu(self)
        a_keep = m.addAction("Keep this track in all episodes (same language)")
        a_drop = m.addAction("Remove this track in all episodes (same language)")
        a_keep_n = a_drop_n = None
        if not x["external"] and x["type_pos"] and x["track"].type in ("audio", "subtitles"):
            label = f"{TYPE_NAME.get(x['track'].type)} {x['type_pos']}"
            m.addSeparator()
            a_keep_n = m.addAction(f"Keep {label} in all episodes (same track number)")
            a_drop_n = m.addAction(f"Remove {label} in all episodes (same track number)")
        m.addSeparator()
        a_reset = m.addAction("Undo my ticks in this episode")
        act = m.exec(self.tree.viewport().mapToGlobal(pos))
        if act in (a_keep, a_drop):
            n = self._apply_everywhere(episode, x, act == a_keep)
            self.ctx.toast(f"Applied to {n} episode{'s' if n != 1 else ''}")
            self.replan()
        elif act is not None and act in (a_keep_n, a_drop_n):
            n = 0
            for ep, (_spec, summ) in self.plans.items():
                for t in summ["tracks"]:
                    if (not t["external"] and t["track"].type == x["track"].type
                            and t["type_pos"] == x["type_pos"]):
                        self._set_override(ep, t["key"], act == a_keep_n)
                        n += 1
            self.ctx.toast(f"Applied to {n} episode{'s' if n != 1 else ''}")
            self.replan()
        elif act == a_reset:
            self.overrides.pop(episode, None)
            self.replan()

    def _apply_everywhere(self, episode, x, keep):
        """Match the same track in other episodes: same type, language, added-or-not, and its position
        among tracks with that type and language (so 'the second English subtitle' maps to the second)."""
        def signature(tracks, target):
            same = [t for t in tracks if t["track"].type == target["track"].type
                    and t["language"] == target["language"] and t["external"] == target["external"]]
            return same.index(target) if target in same else -1

        src_tracks = self.plans[episode][1]["tracks"]
        nth = signature(src_tracks, x)
        n = 0
        for ep, (_spec, summ) in self.plans.items():
            same = [t for t in summ["tracks"] if t["track"].type == x["track"].type
                    and t["language"] == x["language"] and t["external"] == x["external"]]
            if 0 <= nth < len(same):
                self._set_override(ep, same[nth]["key"], keep)
                n += 1
        return n

    def _item_changed(self, item, col):
        data = item.data(0, Qt.UserRole + 1)
        if col == 0 and data:
            episode, key = data
            self._set_override(episode, key, item.checkState(0) == Qt.Checked)
            self._timer.start()
            return
        if col == 0 and item.parent() is None:
            path = item.data(0, Qt.UserRole)
            if item.checkState(0) == Qt.Checked:
                self.unchecked.discard(path)
            else:
                self.unchecked.add(path)
            self._refresh()

    def _browse_out(self):
        d = pick_folder(self, self.ctx.settings, "Output folder")
        if d:
            self.out_dir.setText(os.path.normpath(d))
            self.rb_custom.setChecked(True)
            self.replan()

    def _save_prefs(self):
        s = self.ctx.settings
        s.batch_audio_keep = self.audio_keep.text()
        s.batch_sub_keep = self.sub_keep.text()
        s.batch_keep_und = self.keep_und.isChecked()
        s.batch_drop_embedded_subs = self.drop_subs.isChecked()
        s.batch_ext_lang = self.ext_lang.code()
        s.batch_ext_name = self.ext_name.text()
        s.batch_default_sub = self.default_sub.currentData()
        s.batch_reorder = self.reorder.isChecked()
        s.batch_drop_sdh = self.drop_sdh.isChecked()
        s.batch_drop_image_subs = self.drop_img.isChecked()
        s.batch_one_sub_per_lang = self.one_per_lang.isChecked()
        s.batch_ext_audio_lang = self.ext_audio_lang.code()
        s.batch_ext_audio_name = self.ext_audio_name.text()
        s.batch_ext_audio_delay = self.ext_audio_delay.text() or "0"
        s.batch_audio_by_num = self.audio_num_mode.currentData()
        s.batch_audio_nums = self.audio_nums.text()
        s.batch_sub_by_num = self.sub_num_mode.currentData()
        s.batch_sub_nums = self.sub_nums.text()
        s.batch_out_mode = "custom" if self.rb_custom.isChecked() else "subfolder"
        s.batch_out_dir = self.out_dir.text()
        try:
            s.save()
        except OSError:
            pass

    # ---------- run ----------
    def start(self):
        if not self.ctx.engine.ok:
            self.ctx.need_engine()
            return
        if self.rb_custom.isChecked() and not self.out_dir.text().strip():
            QMessageBox.information(self, "Batch", "Choose an output folder.")
            return
        self.replan()
        todo = [e for e in self._sorted_episodes() if e not in self.unchecked]
        if not todo:
            QMessageBox.information(self, "Batch", "No episodes are ticked.")
            return
        sources = {os.path.normcase(os.path.abspath(p)) for p in list(self.episodes) + list(self.subs)}
        for e in todo:
            if os.path.normcase(os.path.abspath(self.plans[e][0]["output"])) in sources:
                QMessageBox.warning(self, "Batch", "An output file would overwrite a source file. "
                                                   "Choose another output folder.")
                return
        existing = [e for e in todo if os.path.exists(self.plans[e][0]["output"])]
        skip = set()
        if existing:
            box = QMessageBox(QMessageBox.Question, "Files exist",
                              f"{len(existing)} output file(s) already exist.", parent=self)
            b_over = box.addButton("Overwrite", QMessageBox.DestructiveRole)
            b_skip = box.addButton("Skip those", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() == b_skip:
                skip = set(existing)
            elif box.clickedButton() != b_over:
                return
        n = 0
        for e in todo:
            if e in skip:
                continue
            spec = self.plans[e][0]
            try:
                os.makedirs(os.path.dirname(spec["output"]), exist_ok=True)
            except OSError as ex:
                QMessageBox.warning(self, "Batch", f"Cannot create folder:\n{os.path.dirname(spec['output'])}\n\n{ex}")
                return
            self.ctx.queue.add(Job("mux", os.path.basename(spec["output"]), build_mux_args(spec),
                                   output=spec["output"], delete_on_fail=spec["output"]))
            n += 1
        self.ctx.toast(f"Queued {n} episode{'s' if n != 1 else ''}")

    def _refresh(self):
        has = bool(self.episodes)
        self.tree.setVisible(has)
        self.hint.setVisible(not has)
        n = sum(1 for e in self.episodes if e not in self.unchecked)
        bits = []
        if self._pending:
            bits.append(f"reading {self._pending} file(s)...")
        if self.episodes or self.subs:
            bits.append(f"{len(self.episodes)} episodes, {len(self.subs)} added files")
        self.status.setText("  " + ", ".join(bits) if bits else "")
        self.summary.setText("Expand an episode to see every track: what it has now and what it gets after muxing."
                             if has else "")
        self.btn_go.setEnabled(n > 0 and not self._pending)
        self.btn_go.setText(f"Mux {n} episode{'s' if n != 1 else ''}" if n else "Mux episodes")
