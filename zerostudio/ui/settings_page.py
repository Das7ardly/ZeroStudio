"""Settings page."""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import APP_NAME, VERSION
from ..engine import DOWNLOAD_PAGE, IS_WIN
from ..paths import data_dir
from .. import mkvsetup
from .mux_page import CHARSETS
from .setup_dialog import MkvSetupDialog
from .widgets import LangListEdit, card, open_path, page_header

WINGET = "winget install MoritzBunkus.MKVToolNix"


class SettingsPage(QWidget):
    def __init__(self, app_ctx, parent=None):
        super().__init__(parent)
        self.ctx = app_ctx
        s = app_ctx.settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        root.addLayout(page_header("Settings"))

        # Engine
        ec, el = card("MKVToolNix", "does the actual work")
        self.engine_status = QLabel()
        self.engine_status.setWordWrap(True)
        el.addWidget(self.engine_status)
        row = QHBoxLayout()
        self.dir_edit = QLineEdit(s.mkvtoolnix_dir)
        self.dir_edit.setPlaceholderText("Auto-detect (Program Files, PATH, ...)")
        b_browse = QPushButton("Browse")
        b_detect = QPushButton("Detect again")
        row.addWidget(self.dir_edit, 1)
        row.addWidget(b_browse)
        row.addWidget(b_detect)
        el.addLayout(row)
        row2 = QHBoxLayout()
        if mkvsetup.supported():
            b_get = QPushButton("Download / update automatically")
            b_get.setToolTip("Downloads the latest portable MKVToolNix into ZeroStudio's folder (no admin rights)")
            b_get.clicked.connect(lambda: MkvSetupDialog(self.ctx, self).exec())
            row2.addWidget(b_get)
        b_dl = QPushButton("Open download page")
        row2.addWidget(b_dl)
        if IS_WIN:
            b_wg = QPushButton("Copy winget command")
            b_wg.setToolTip(WINGET)
            b_wg.clicked.connect(lambda: (QGuiApplication.clipboard().setText(WINGET),
                                          self.ctx.toast("Copied: " + WINGET)))
            row2.addWidget(b_wg)
        row2.addStretch(1)
        el.addLayout(row2)
        b_browse.clicked.connect(self._browse)
        b_detect.clicked.connect(self._detect)
        b_dl.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DOWNLOAD_PAGE)))
        self.dir_edit.editingFinished.connect(self._detect)
        root.addWidget(ec)

        # Jobs
        jc, jl = card("Jobs")
        f = QFormLayout()
        self.parallel = QComboBox()
        for n in range(1, 7):
            self.parallel.addItem(str(n), n)
        self.parallel.setCurrentIndex(max(0, min(5, int(s.max_parallel) - 1)))
        self.parallel.setFixedWidth(90)
        self.parallel.currentIndexChanged.connect(self._save)
        f.addRow("Run at the same time", self.parallel)
        jl.addLayout(f)
        jl.addWidget(QLabel("Muxing is disk-bound: 2 is a good value for one drive, more helps when sources and "
                            "outputs sit on different drives.", objectName="Muted", wordWrap=True))
        root.addWidget(jc)

        # Mux
        mc, ml = card("Multiplex")
        f = QFormLayout()
        self.audio_langs = LangListEdit(s.pref_audio_langs)
        self.sub_langs = LangListEdit(s.pref_sub_langs)
        self.audio_langs.setPlaceholderText("e.g. bul, eng")
        self.sub_langs.setPlaceholderText("e.g. bul")
        self.smart = QCheckBox("Apply smart defaults when files are added")
        self.smart.setChecked(s.smart_defaults_on_add)
        self.charset = QComboBox()
        self.charset.setEditable(True)
        self.charset.addItems([c for c in CHARSETS if c])
        self.charset.setCurrentText(s.fallback_sub_charset)
        self.mux_dir = QLineEdit(s.mux_out_dir)
        self.mux_dir.setPlaceholderText("Same folder as the first source")
        for w in (self.audio_langs, self.sub_langs, self.charset):
            w.setMaximumWidth(260)
        f.addRow("Preferred audio languages", self.audio_langs)
        f.addRow("Preferred subtitle languages", self.sub_langs)
        f.addRow("", self.smart)
        f.addRow("Non-UTF-8 subtitles are", self.charset)
        f.addRow("Default output folder", self.mux_dir)
        ml.addLayout(f)
        for w in (self.audio_langs, self.sub_langs, self.mux_dir):
            w.editingFinished.connect(self._save)
        self.smart.toggled.connect(self._save)
        self.charset.currentTextChanged.connect(self._save)
        root.addWidget(mc)

        # About
        ac, al = card("About")
        from .brand import LogoWidget
        big = LogoWidget()
        big.setMaximumWidth(260)
        al.addWidget(big)
        al.addWidget(QLabel(f"{APP_NAME} {VERSION}. A front end for MKVToolNix by Moritz Bunkus "
                            "(mkvmerge, mkvextract, mkvpropedit).", wordWrap=True))
        b_data = QPushButton("Open data folder")
        b_data.clicked.connect(lambda: open_path(str(data_dir())))
        r3 = QHBoxLayout()
        r3.addWidget(b_data)
        r3.addStretch(1)
        al.addLayout(r3)
        root.addWidget(ac)
        root.addStretch(1)
        self._update_status()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "MKVToolNix folder (contains mkvmerge)", self.dir_edit.text())
        if d:
            self.dir_edit.setText(os.path.normpath(d))
            self._detect()

    def _detect(self):
        self.ctx.settings.mkvtoolnix_dir = self.dir_edit.text().strip()
        self.ctx.settings.save()
        self.ctx.engine.reload(self.ctx.settings.mkvtoolnix_dir)
        self._update_status()
        self.ctx.engine_changed()

    def _update_status(self):
        e = self.ctx.engine
        if e.ok:
            self.engine_status.setText(f"Found: {e.version() or 'mkvmerge'}\n{e.folder}")
            self.engine_status.setObjectName("")
        else:
            self.engine_status.setText("Not found. Install MKVToolNix (free) or point to its folder. The portable "
                                       "version works too: unzip it and choose that folder.")
        self.engine_status.setStyleSheet("" if e.ok else "color: #e9b44c;")

    def _save(self):
        s = self.ctx.settings
        s.max_parallel = self.parallel.currentData()
        s.pref_audio_langs = self.audio_langs.text()
        s.pref_sub_langs = self.sub_langs.text()
        s.smart_defaults_on_add = self.smart.isChecked()
        s.fallback_sub_charset = self.charset.currentText().strip() or "cp1251"
        s.mux_out_dir = self.mux_dir.text().strip()
        s.save()
        self.ctx.queue._pump()
