"""Quick edit page: change titles, track names, languages and flags in place with mkvpropedit (no remux)."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..commands import build_propedit_args
from ..jobs import DONE, WARN, Job
from ..mediainfo import file_size_text, identify
from .theme import C
from .widgets import (MKV_FILTER, CheckCell, DropFilter, LangCombo, add_shortcuts, card, expand_paths, page_header, pick_files,
                      run_async)
from .icons import icon

MKV_EXTS = ("mkv", "mka", "mks", "mk3d", "webm")
COL_NUM, COL_TYPE, COL_CODEC, COL_LANG, COL_NAME, COL_DEF, COL_FORCED, COL_EN = range(8)


def state_from(mf):
    return {"title": mf.title,
            "tracks": [{"number": t.number, "type": t.type, "language": t.language, "name": t.name,
                        "default": t.default, "forced": t.forced, "enabled": t.enabled} for t in mf.tracks],
            "keep_att": {a.id: True for a in mf.attachments}, "add_att": []}


def diff_spec(path, mf, st, include_title=True):
    """Only properties that differ from what is in the file."""
    spec = {"path": path, "tracks": [], "delete_attachments": [], "add_attachments": list(st["add_att"])}
    spec["title"] = st["title"] if include_title and st["title"] != mf.title else None
    for orig, new in zip(mf.tracks, st["tracks"]):
        d = {}
        if new["language"] != orig.language:
            d["language"] = new["language"]
        if new["name"] != orig.name:
            d["name"] = new["name"]
        for k in ("default", "forced", "enabled"):
            if new[k] != getattr(orig, k):
                d[k] = new[k]
        if d:
            d["number"] = orig.number
            spec["tracks"].append(d)
    spec["delete_attachments"] = [aid for aid, keep in st["keep_att"].items() if not keep]
    changed = spec["title"] is not None or spec["tracks"] or spec["delete_attachments"] or spec["add_attachments"]
    return spec if changed else None


class EditPage(QWidget):
    def __init__(self, app_ctx, parent=None):
        super().__init__(parent)
        self.ctx = app_ctx
        self.files = []          # {path, mf, state}
        self.current = None
        self._pending = 0
        self._job_paths = {}     # job id -> path to re-read after edit

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 12)
        root.setSpacing(12)
        root.addLayout(page_header("Quick edit", "Change the title, track names, languages and Default/Forced flags "
                                                 "in place. No remux, takes a second even on big files."))
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        lc, ll = card("Files")
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.hint = QLabel("Drop MKV files\nor folders here", objectName="DropHint", alignment=Qt.AlignCenter)
        ll.addWidget(self.list, 1)
        ll.addWidget(self.hint, 1)
        br = QHBoxLayout()
        self.btn_add = QPushButton("Add files")
        self.btn_add.setIcon(icon("plus", C["text"], 18))
        self.btn_remove = QPushButton("Remove")
        br.addWidget(self.btn_add)
        br.addWidget(self.btn_remove)
        br.addStretch(1)
        ll.addLayout(br)
        split.addWidget(lc)

        rc, rl = card("Header")
        self.file_label = QLabel("", objectName="Muted")
        rc.title_row.addWidget(self.file_label)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Title"))
        self.title_edit = QLineEdit(placeholderText="(no title)")
        trow.addWidget(self.title_edit, 1)
        rl.addLayout(trow)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["#", "Type", "Codec", "Language", "Name", "Default", "Forced", "Enabled"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        for col, w in ((COL_NUM, 34), (COL_TYPE, 78), (COL_CODEC, 140), (COL_LANG, 168), (COL_DEF, 62),
                       (COL_FORCED, 58), (COL_EN, 62)):
            self.table.setColumnWidth(col, w)
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        self.table.setWordWrap(False)
        rl.addWidget(self.table, 3)
        rl.addWidget(QLabel("Attachments (untick to delete)", objectName="CardTitle"))
        self.att_list = QListWidget()
        self.att_list.setMaximumHeight(110)
        rl.addWidget(self.att_list, 1)
        arow = QHBoxLayout()
        self.btn_att_add = QPushButton("Add attachment")
        arow.addWidget(self.btn_att_add)
        arow.addStretch(1)
        rl.addLayout(arow)
        split.addWidget(rc)
        split.setSizes([240, 860])
        root.addWidget(split, 1)

        bc, bl = card()
        row = QHBoxLayout()
        self.summary = QLabel("", objectName="Muted")
        row.addWidget(self.summary, 1)
        self.title_all = QCheckBox("Include title when applying to all")
        self.btn_all = QPushButton("Apply to all matching files")
        self.btn_all.setToolTip("Copies track names, languages and flags to every loaded file with the same track "
                                "layout (same number and order of video/audio/subtitle tracks).")
        self.btn_apply = QPushButton("Apply to this file", objectName="Primary")
        self.btn_apply.setIcon(icon("save", C["on_accent"], 18))
        row.addWidget(self.title_all)
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_apply)
        bl.addLayout(row)
        root.addWidget(bc)

        self.btn_add.clicked.connect(lambda: self.add_files(pick_files(self, self.ctx.settings, "Add MKV files",
                                                                       MKV_FILTER)))
        self.btn_remove.clicked.connect(self._remove)
        self.list.currentRowChanged.connect(self._select)
        self.btn_apply.clicked.connect(self.apply_current)
        self.btn_all.clicked.connect(self.apply_all)
        self.btn_att_add.clicked.connect(self._add_att)
        app_ctx.queue.job_finished.connect(self._job_finished)
        for w in (self, self.list):
            DropFilter(w, lambda paths: self.add_files(expand_paths(paths, MKV_EXTS)))
        self.btn_apply.setToolTip("Ctrl+Enter")
        add_shortcuts(self, add=self.btn_add.click, start=self.btn_apply.click, remove=(self.list, self._remove))
        self._refresh()

    # ---------- files ----------
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
        if err or not mf.is_matroska:
            self.ctx.toast(f"Skipped {os.path.basename(path)}: {err or 'not a Matroska file'}", error=True)
            self._refresh()
            return
        self.files.append({"path": path, "mf": mf, "state": state_from(mf)})
        self.files.sort(key=lambda f: f["path"].lower())
        cur = self.current["path"] if self.current else path
        self._fill_list(cur)
        self._refresh()

    def _fill_list(self, select_path=None):
        self.list.blockSignals(True)
        self.list.clear()
        sel = 0
        for i, f in enumerate(self.files):
            it = QListWidgetItem(os.path.basename(f["path"]))
            it.setToolTip(f["path"])
            self.list.addItem(it)
            if select_path and f["path"] == select_path:
                sel = i
        self.list.blockSignals(False)
        if self.files:
            self.list.setCurrentRow(sel)
            self._select(sel, force=True)

    def _remove(self):
        r = self.list.currentRow()
        if r < 0:
            return
        f = self.files.pop(r)
        if self.current is f:
            self.current = None
        self._fill_list(self.files[min(r, len(self.files) - 1)]["path"] if self.files else None)
        if not self.files:
            self._show(None)
        self._refresh()

    def _select(self, row, force=False):
        if self.current is not None:
            self._collect()
        f = self.files[row] if 0 <= row < len(self.files) else None
        if f is self.current and not force:
            return
        self.current = f
        self._show(f)

    # ---------- header editor ----------
    def _show(self, f):
        self.table.setRowCount(0)
        self.att_list.clear()
        self.title_edit.clear()
        if not f:
            self.file_label.setText("")
            self._refresh()
            return
        mf, st = f["mf"], f["state"]
        size = ""
        try:
            size = file_size_text(os.path.getsize(f["path"]))
        except OSError:
            pass
        self.file_label.setText(f"  {os.path.basename(f['path'])}  ·  {mf.duration_text()}  ·  {size}")
        self.title_edit.setText(st["title"])
        self.table.setRowCount(len(st["tracks"]))
        for r, (t, s) in enumerate(zip(mf.tracks, st["tracks"])):
            self.table.setItem(r, COL_NUM, QTableWidgetItem(str(t.number)))
            it = QTableWidgetItem(t.type.capitalize())
            it.setForeground(QColor(C.get(t.type, C["other"])))
            self.table.setItem(r, COL_TYPE, it)
            self.table.setItem(r, COL_CODEC, QTableWidgetItem(f"{t.codec}  {t.details()}"))
            self.table.setCellWidget(r, COL_LANG, LangCombo(s["language"]))
            self.table.setCellWidget(r, COL_NAME, QLineEdit(s["name"]))
            self.table.setCellWidget(r, COL_DEF, CheckCell(s["default"]))
            self.table.setCellWidget(r, COL_FORCED, CheckCell(s["forced"]))
            self.table.setCellWidget(r, COL_EN, CheckCell(s["enabled"]))
        for a in mf.attachments:
            it = QListWidgetItem(f"{a.file_name}    {a.mime}, {file_size_text(a.size)}")
            it.setData(Qt.UserRole, ("old", a.id))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if st["keep_att"].get(a.id, True) else Qt.Unchecked)
            self.att_list.addItem(it)
        for p in st["add_att"]:
            it = QListWidgetItem(f"{os.path.basename(p)}    (will be added)")
            it.setData(Qt.UserRole, ("new", p))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.att_list.addItem(it)
        self._refresh()

    def _collect(self):
        f = self.current
        if not f or self.table.rowCount() != len(f["state"]["tracks"]):
            return
        st = f["state"]
        st["title"] = self.title_edit.text()
        for r, s in enumerate(st["tracks"]):
            s["language"] = self.table.cellWidget(r, COL_LANG).code()
            s["name"] = self.table.cellWidget(r, COL_NAME).text()
            s["default"] = self.table.cellWidget(r, COL_DEF).isChecked()
            s["forced"] = self.table.cellWidget(r, COL_FORCED).isChecked()
            s["enabled"] = self.table.cellWidget(r, COL_EN).isChecked()
        new = []
        for i in range(self.att_list.count()):
            it = self.att_list.item(i)
            kind, val = it.data(Qt.UserRole)
            if kind == "old":
                st["keep_att"][val] = it.checkState() == Qt.Checked
            elif it.checkState() == Qt.Checked:
                new.append(val)
        st["add_att"] = new

    def _add_att(self):
        if not self.current:
            return
        self._collect()
        files = pick_files(self, self.ctx.settings, "Add attachment",
                           "Fonts and images (*.ttf *.otf *.ttc *.jpg *.jpeg *.png *.webp);;All files (*)")
        self.current["state"]["add_att"] += [f for f in files if f not in self.current["state"]["add_att"]]
        self._show(self.current)

    # ---------- apply ----------
    def _queue(self, f, spec):
        job = self.ctx.queue.add(Job("edit", "Edit " + os.path.basename(f["path"]), build_propedit_args(spec),
                                     output=f["path"]))
        self._job_paths[job.id] = f["path"]

    def apply_current(self):
        if not self.current:
            return
        self._collect()
        spec = diff_spec(self.current["path"], self.current["mf"], self.current["state"])
        if not spec:
            self.ctx.toast("Nothing changed")
            return
        self._queue(self.current, spec)
        self.ctx.toast(f"Saving changes to {os.path.basename(self.current['path'])}")

    def apply_all(self):
        if not self.current:
            return
        self._collect()
        src = self.current
        layout = src["mf"].layout()
        queued, skipped = 0, 0
        for f in self.files:
            if f["mf"].layout() != layout:
                skipped += 1
                continue
            if f is not src:
                st = f["state"]
                for mine, theirs in zip(src["state"]["tracks"], st["tracks"]):
                    for k in ("language", "name", "default", "forced", "enabled"):
                        theirs[k] = mine[k]
                if self.title_all.isChecked():
                    st["title"] = src["state"]["title"]
            spec = diff_spec(f["path"], f["mf"], f["state"], include_title=(f is src) or self.title_all.isChecked())
            if spec:
                self._queue(f, spec)
                queued += 1
        msg = f"Queued {queued} edit{'s' if queued != 1 else ''}"
        if skipped:
            msg += f", skipped {skipped} file(s) with a different track layout"
        self.ctx.toast(msg)

    def _job_finished(self, job_id):
        path = self._job_paths.pop(job_id, None)
        job = self.ctx.queue.get(job_id)
        if not path or not job or job.status not in (DONE, WARN):
            return
        mm = self.ctx.engine.tool("mkvmerge")
        run_async(lambda: identify(mm, path), lambda mf, err: self._reloaded(path, mf, err))

    def _reloaded(self, path, mf, err):
        if err:
            return
        for f in self.files:
            if f["path"] == path:
                f["mf"], f["state"] = mf, state_from(mf)
                if f is self.current:
                    self._show(f)

    def _refresh(self):
        has = bool(self.files)
        self.list.setVisible(has)
        self.hint.setVisible(not has)
        self.btn_apply.setEnabled(self.current is not None)
        same = 0
        if self.current:
            lay = self.current["mf"].layout()
            same = sum(1 for f in self.files if f["mf"].layout() == lay)
        self.btn_all.setEnabled(same > 1)
        self.btn_all.setText(f"Apply to all {same} matching files" if same > 1 else "Apply to all matching files")
        self.title_all.setEnabled(same > 1)
        self.summary.setText(f"Reading {self._pending} file(s)..." if self._pending else
                             (f"{len(self.files)} file(s) loaded" if has else ""))
