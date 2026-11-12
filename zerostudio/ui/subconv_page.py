"""Convert subtitle files (SRT, ASS, ...) from old code pages to UTF-8, with a live preview."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import subconv
from .icons import icon
from .theme import C
from .widgets import CheckCell, DropFilter, add_shortcuts, card, expand_paths, page_header, pick_files, pick_folder, show_in_folder

COL_USE, COL_FILE, COL_DET, COL_ENC, COL_STATUS = range(5)
SAVE_MODES = [("replace_backup", "Replace the original, keep a .bak copy"), ("replace", "Replace the original"),
              ("new", "New file next to it (name.utf8.srt)"), ("folder", "Into folder")]


class SubConvPage(QWidget):
    def __init__(self, app_ctx, parent=None):
        super().__init__(parent)
        self.ctx = app_ctx
        self.files = []     # {path, raw_head, detected, note}

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 12)
        root.setSpacing(12)
        root.addLayout(page_header("Subtitles to UTF-8",
                                   "Fix subtitles that show broken letters (Ñëó÷àé or ????). The encoding is "
                                   "detected per file; check the preview and change it if the text looks wrong."))
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)

        fc, fl = card("Files")
        self.status = QLabel("", objectName="Muted")
        fc.title_row.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Convert", "File", "Detected", "Read as", "Result"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        h = self.table.horizontalHeader()
        for col, w in ((COL_USE, 64), (COL_DET, 170), (COL_ENC, 220)):
            self.table.setColumnWidth(col, w)
        h.setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_STATUS, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_STATUS, 220)
        self.hint = QLabel("Drop .srt / .ass / .ssa / .sub / .vtt files or folders here", objectName="DropHint",
                           alignment=Qt.AlignCenter)
        fl.addWidget(self.table, 1)
        fl.addWidget(self.hint, 1)
        br = QHBoxLayout()
        self.btn_add = QPushButton("Add files")
        self.btn_add.setIcon(icon("plus", C["text"], 18))
        self.btn_folder = QPushButton("Add folder")
        self.btn_folder.setIcon(icon("folder", C["text"], 18))
        self.btn_remove = QPushButton("Remove")
        self.btn_clear = QPushButton("Clear")
        for b in (self.btn_add, self.btn_folder, self.btn_remove, self.btn_clear):
            br.addWidget(b)
        br.addStretch(1)
        fl.addLayout(br)
        split.addWidget(fc)

        pc, pl = card("Preview")
        self.preview_label = QLabel("", objectName="Muted")
        pc.title_row.addWidget(self.preview_label)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(10)
        self.preview.setFont(mono)
        pl.addWidget(self.preview, 1)
        split.addWidget(pc)
        split.setSizes([300, 220])
        root.addWidget(split, 1)

        oc, ol = card()
        row = QHBoxLayout()
        row.addWidget(QLabel("Save"))
        self.mode = QComboBox()
        for key, text in SAVE_MODES:
            self.mode.addItem(text, key)
        row.addWidget(self.mode)
        self.out_dir = QLineEdit(placeholderText="Choose a folder")
        self.btn_out = QPushButton("Browse")
        row.addWidget(self.out_dir, 1)
        row.addWidget(self.btn_out)
        ol.addLayout(row)
        row2 = QHBoxLayout()
        self.bom = QCheckBox("Add BOM (helps some TVs and old players detect UTF-8)")
        self.skip_utf8 = QCheckBox("Skip files that are already UTF-8")
        self.skip_utf8.setChecked(True)
        row2.addWidget(self.bom)
        row2.addWidget(self.skip_utf8)
        row2.addStretch(1)
        self.btn_go = QPushButton("Convert", objectName="Primary")
        self.btn_go.setIcon(icon("save", C["on_accent"], 18))
        row2.addWidget(self.btn_go)
        ol.addLayout(row2)
        root.addWidget(oc)

        self.btn_add.clicked.connect(lambda: self.add_files(pick_files(
            self, self.ctx.settings, "Add subtitles",
            "Subtitles (" + " ".join("*." + e for e in subconv.SUB_EXTS) + ");;All files (*)")))
        self.btn_folder.clicked.connect(self._add_folder)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_clear.clicked.connect(self._clear)
        self.btn_out.clicked.connect(self._browse_out)
        self.btn_go.clicked.connect(self.convert)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.skip_utf8.toggled.connect(self._apply_skip)
        self.table.itemSelectionChanged.connect(self.update_preview)
        for w in (self, self.table):
            DropFilter(w, lambda paths: self.add_files(expand_paths(paths, subconv.SUB_EXTS)))
        self.btn_go.setToolTip("Ctrl+Enter")
        add_shortcuts(self, add=self.btn_add.click, start=self.btn_go.click, remove=(self.table, self._remove))
        self._mode_changed()
        self._refresh()

    # ---------- files ----------
    def _add_folder(self):
        d = pick_folder(self, self.ctx.settings, "Add folder")
        if d:
            self.add_files(expand_paths([d], subconv.SUB_EXTS))

    def add_files(self, paths):
        known = {os.path.normcase(f["path"]) for f in self.files}
        fallback = self.ctx.settings.fallback_sub_charset or "cp1251"
        for p in paths:
            if os.path.normcase(p) in known or p.endswith(".bak") or not os.path.isfile(p):
                continue
            known.add(os.path.normcase(p))
            try:
                raw = subconv.read(p, 2_000_000)
            except OSError as e:
                self.ctx.toast(f"Cannot read {os.path.basename(p)}: {e}", error=True)
                continue
            enc, note = subconv.detect(raw, fallback)
            self.files.append({"path": p, "raw": raw, "detected": enc, "note": note})
            self._add_row(self.files[-1])
        if self.files and not self.table.selectedItems():
            self.table.selectRow(0)
        self._refresh()

    def _add_row(self, f):
        r = self.table.rowCount()
        self.table.insertRow(r)
        utf8 = subconv.is_utf8(f["detected"])
        use = CheckCell(not (utf8 and self.skip_utf8.isChecked()))
        use.box.toggled.connect(self._refresh)
        self.table.setCellWidget(r, COL_USE, use)
        it = QTableWidgetItem(os.path.basename(f["path"]))
        it.setToolTip(f["path"])
        self.table.setItem(r, COL_FILE, it)
        det = QTableWidgetItem(subconv.LABELS.get(f["detected"], f["detected"]))
        det.setToolTip(f["note"])
        det.setForeground(QColor(C["ok"] if utf8 else C["warn"]))
        self.table.setItem(r, COL_DET, det)
        combo = QComboBox()
        encs = list(subconv.ENCODINGS)
        if f["detected"] not in encs:
            encs.insert(0, f["detected"])
        for e in encs:
            combo.addItem(subconv.LABELS.get(e, e), e)
        combo.setCurrentIndex(combo.findData(f["detected"]))
        combo.currentIndexChanged.connect(lambda _i, row=r: self._enc_changed(row))
        self.table.setCellWidget(r, COL_ENC, combo)
        st = QTableWidgetItem("Already UTF-8" if utf8 else f"Ready ({f['note']})")
        st.setForeground(QColor(C["muted"]))
        self.table.setItem(r, COL_STATUS, st)

    def _enc_changed(self, row):
        self.table.selectRow(row)
        self.update_preview()

    def _remove(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
            self.files.pop(r)
        self._rebind_combos()
        self._refresh()
        self.update_preview()

    def _rebind_combos(self):
        for r in range(self.table.rowCount()):
            combo = self.table.cellWidget(r, COL_ENC)
            try:
                combo.currentIndexChanged.disconnect()
            except (RuntimeError, TypeError):
                pass
            combo.currentIndexChanged.connect(lambda _i, row=r: self._enc_changed(row))

    def _clear(self):
        self.files = []
        self.table.setRowCount(0)
        self.preview.clear()
        self.preview_label.setText("")
        self._refresh()

    def _apply_skip(self, on):
        for r, f in enumerate(self.files):
            if subconv.is_utf8(f["detected"]):
                self.table.cellWidget(r, COL_USE).setChecked(not on)

    # ---------- preview ----------
    def update_preview(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows or rows[0] >= len(self.files):
            self.preview.clear()
            self.preview_label.setText("")
            return
        r = rows[0]
        f = self.files[r]
        enc = self.table.cellWidget(r, COL_ENC).currentData()
        text = subconv.decode(f["raw"][:60_000], enc)
        lines = text.splitlines()
        # Jump to the first lines that contain non-ASCII text so the preview shows the letters that matter
        start = next((i for i, line in enumerate(lines) if any(ord(c) > 127 for c in line)), 0)
        start = max(0, start - 3)
        self.preview.setPlainText("\n".join(lines[start:start + 60]))
        self.preview_label.setText(f"  {os.path.basename(f['path'])} read as {subconv.LABELS.get(enc, enc)}"
                                   "  - if the letters look wrong, pick another 'Read as'")

    # ---------- convert ----------
    def _mode_changed(self, *_):
        custom = self.mode.currentData() == "folder"
        self.out_dir.setVisible(custom)
        self.btn_out.setVisible(custom)

    def _browse_out(self):
        d = pick_folder(self, self.ctx.settings, "Output folder")
        if d:
            self.out_dir.setText(os.path.normpath(d))

    def convert(self):
        mode = self.mode.currentData()
        if mode == "folder" and not self.out_dir.text().strip():
            QMessageBox.information(self, "Subtitles to UTF-8", "Choose an output folder.")
            return
        done = failed = 0
        last = ""
        for r, f in enumerate(self.files):
            if not self.table.cellWidget(r, COL_USE).isChecked():
                continue
            enc = self.table.cellWidget(r, COL_ENC).currentData()
            st = self.table.item(r, COL_STATUS)
            try:
                out = subconv.convert(f["path"], enc, mode, self.bom.isChecked(), self.out_dir.text().strip())
            except UnicodeDecodeError:
                st.setText(f"Not valid {subconv.LABELS.get(enc, enc)}, pick another encoding")
                st.setForeground(QColor(C["bad"]))
                failed += 1
                continue
            except OSError as e:
                st.setText(f"Error: {e}")
                st.setForeground(QColor(C["bad"]))
                failed += 1
                continue
            st.setText("Converted" + ("" if out == f["path"] else f" -> {os.path.basename(out)}"))
            st.setToolTip(out)
            st.setForeground(QColor(C["ok"]))
            self.table.cellWidget(r, COL_USE).setChecked(False)
            if out == f["path"]:
                f["raw"] = subconv.read(out, 2_000_000)
                f["detected"], f["note"] = subconv.detect(f["raw"])
                det = self.table.item(r, COL_DET)
                det.setText(subconv.LABELS.get(f["detected"], f["detected"]))
                det.setForeground(QColor(C["ok"]))
                combo = self.table.cellWidget(r, COL_ENC)
                combo.setCurrentIndex(max(0, combo.findData(f["detected"])))
            done += 1
            last = out
        msg = f"Converted {done} file{'s' if done != 1 else ''}" + (f", {failed} failed" if failed else "")
        self.ctx.toast(msg, error=bool(failed))
        if done and mode == "folder":
            show_in_folder(last)
        self._refresh()
        self.update_preview()

    def _refresh(self):
        has = bool(self.files)
        self.table.setVisible(has)
        self.hint.setVisible(not has)
        n = sum(1 for r in range(self.table.rowCount()) if self.table.cellWidget(r, COL_USE).isChecked())
        need = sum(1 for f in self.files if not subconv.is_utf8(f["detected"]))
        self.status.setText(f"  {len(self.files)} files, {need} not UTF-8" if has else "")
        self.btn_go.setEnabled(n > 0)
        self.btn_go.setText(f"Convert {n} file{'s' if n != 1 else ''}" if n else "Convert")
