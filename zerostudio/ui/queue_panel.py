"""Job queue table shown at the bottom of every page."""
import os

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
                               QLabel, QMenu, QPlainTextEdit, QPushButton, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget)

from ..jobs import DONE, ERROR, QUEUED, RUNNING, STOPPED, WARN
from .theme import C
from .widgets import open_path, show_in_folder

COLS = ("Type", "Name", "Status", "Progress", "Output")
KIND_LABEL = {"mux": "Mux", "extract": "Extract", "edit": "Edit"}
STATUS_COLOR = {DONE: C["ok"], WARN: C["warn"], ERROR: C["bad"], STOPPED: C["muted"], RUNNING: C["accent_hi"],
                QUEUED: C["muted"]}


class QueueModel(QAbstractTableModel):
    def __init__(self, queue, parent=None):
        super().__init__(parent)
        self.q = queue
        queue.job_added.connect(self._added)
        queue.job_removed.connect(lambda _id: self.beginResetModel() or self.endResetModel())
        queue.job_changed.connect(self._changed)

    def _added(self, job_id):
        n = len(self.q.jobs) - 1
        self.beginInsertRows(QModelIndex(), n, n)
        self.endInsertRows()

    def _changed(self, job_id):
        i = self.q.index_of(job_id)
        if i >= 0:
            self.dataChanged.emit(self.index(i, 0), self.index(i, len(COLS) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.q.jobs)

    def columnCount(self, parent=QModelIndex()):
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLS[section]
        return None

    def job(self, row):
        return self.q.jobs[row] if 0 <= row < len(self.q.jobs) else None

    def data(self, index, role=Qt.DisplayRole):
        job = self.job(index.row())
        if not job:
            return None
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return KIND_LABEL.get(job.kind, job.kind)
            if col == 1:
                return job.title
            if col == 2:
                return job.status + (f": {job.message}" if job.message and job.status in (ERROR, WARN) else "")
            if col == 3:
                return job.progress
            if col == 4:
                return job.output
        if role == Qt.ForegroundRole and col == 2:
            return QColor(STATUS_COLOR.get(job.status, C["text"]))
        if role == Qt.ToolTipRole:
            if col == 2 and job.message:
                return job.message
            if col in (1, 4):
                return job.output
        return None


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        value = int(index.data() or 0)
        r = option.rect.adjusted(6, 7, -6, -7)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(C["surface3"]))
        painter.drawRoundedRect(r, 4, 4)
        if value > 0:
            painter.setBrush(QColor(C["accent"]))
            painter.drawRoundedRect(QRect(r.x(), r.y(), max(8, int(r.width() * value / 100)), r.height()), 4, 4)
        painter.setPen(QColor(C["text"]))
        painter.drawText(option.rect, Qt.AlignCenter, f"{value}%")
        painter.restore()


class LogDialog(QDialog):
    def __init__(self, title, command, log, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 480)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Command"))
        cmd = QPlainTextEdit(command)
        cmd.setReadOnly(True)
        cmd.setMaximumHeight(90)
        lay.addWidget(cmd)
        lay.addWidget(QLabel("Output"))
        out = QPlainTextEdit(log)
        out.setReadOnly(True)
        out.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(out, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        copy = bb.addButton("Copy command", QDialogButtonBox.ActionRole)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(command))
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        out.moveCursor(out.textCursor().End)


class QueuePanel(QWidget):
    toggled = Signal(bool)

    def __init__(self, queue, parent=None):
        super().__init__(parent)
        self.q = queue
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QWidget(objectName="QueueHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 6, 12, 6)
        self.title = QLabel("Jobs", objectName="CardTitle")
        self.counts = QLabel("", objectName="Muted")
        hl.addWidget(self.title)
        hl.addWidget(self.counts)
        hl.addStretch(1)
        self.btn_clear = QPushButton("Clear finished", objectName="Flat")
        self.btn_stop = QPushButton("Stop all", objectName="Flat")
        self.btn_toggle = QPushButton("Hide", objectName="Flat")
        for b in (self.btn_clear, self.btn_stop, self.btn_toggle):
            hl.addWidget(b)
        lay.addWidget(head)

        self.model = QueueModel(queue, self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setItemDelegateForColumn(3, ProgressDelegate(self.view))
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.verticalHeader().hide()
        self.view.verticalHeader().setDefaultSectionSize(28)
        self.view.setWordWrap(False)
        self.view.setTextElideMode(Qt.ElideMiddle)
        h = self.view.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.setSectionResizeMode(3, QHeaderView.Fixed)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        self.view.setColumnWidth(2, 220)
        self.view.setColumnWidth(3, 140)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.doubleClicked.connect(self._double)
        self.view.setStyleSheet("QTableView { border-radius: 0; border-left: none; border-right: none; }")
        lay.addWidget(self.view, 1)

        self.btn_clear.clicked.connect(queue.clear_finished)
        self.btn_stop.clicked.connect(queue.stop_all)
        self.btn_toggle.clicked.connect(self._toggle)
        queue.counts_changed.connect(self._update_counts)
        queue.job_added.connect(lambda _id: self.set_expanded(True))
        self._update_counts()

    def _toggle(self):
        vis = not self.view.isVisible()
        self.view.setVisible(vis)
        self.btn_toggle.setText("Hide" if vis else "Show")
        self.toggled.emit(vis)

    def set_expanded(self, vis):
        if self.view.isVisible() != vis:
            self._toggle()

    def _update_counts(self):
        r, q, e = self.q.counts()
        bits = []
        if r:
            bits.append(f"{r} running")
        if q:
            bits.append(f"{q} queued")
        if e:
            bits.append(f"{e} failed")
        total = len(self.q.jobs)
        self.counts.setText("  " + (", ".join(bits) if bits else (f"{total} finished" if total else "idle")))
        self.btn_stop.setEnabled(bool(r or q))

    def selected_jobs(self):
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows()})
        return [self.model.job(r) for r in rows if self.model.job(r)]

    def _menu(self, pos):
        idx = self.view.indexAt(pos)
        if idx.isValid() and not self.view.selectionModel().isRowSelected(idx.row(), QModelIndex()):
            self.view.selectRow(idx.row())
        jobs = self.selected_jobs()
        if not jobs:
            return
        one = jobs[0]
        m = QMenu(self)
        a_stop = m.addAction("Stop")
        a_retry = m.addAction("Run again")
        m.addSeparator()
        a_open = m.addAction("Open output")
        a_show = m.addAction("Show in folder")
        a_log = m.addAction("View log and command")
        a_copy = m.addAction("Copy command")
        m.addSeparator()
        a_remove = m.addAction("Remove from list")
        a_stop.setEnabled(any(j.status in (QUEUED, RUNNING) for j in jobs))
        a_retry.setEnabled(any(j.status in (ERROR, STOPPED, WARN, DONE) for j in jobs))
        exists = bool(one.output) and os.path.exists(one.output)
        a_open.setEnabled(exists)
        a_show.setEnabled(exists)
        act = m.exec(self.view.viewport().mapToGlobal(pos))
        if act == a_stop:
            for j in jobs:
                self.q.stop(j.id)
        elif act == a_retry:
            for j in jobs:
                self.q.retry(j.id)
        elif act == a_open:
            open_path(one.output)
        elif act == a_show:
            show_in_folder(one.output)
        elif act == a_log:
            self.show_log(one)
        elif act == a_copy:
            QGuiApplication.clipboard().setText(self.q.command_line(one))
        elif act == a_remove:
            for j in jobs:
                self.q.remove(j.id)

    def _double(self, idx):
        job = self.model.job(idx.row())
        if not job:
            return
        if job.status in (DONE, WARN) and job.output and os.path.exists(job.output):
            show_in_folder(job.output)
        else:
            self.show_log(job)

    def show_log(self, job):
        LogDialog(job.title, self.q.command_line(job), "\n".join(job.log), self).exec()
