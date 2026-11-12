"""History of finished jobs."""
import os
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QMenu, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .queue_panel import KIND_LABEL, STATUS_COLOR, LogDialog
from .widgets import card, open_path, page_header, show_in_folder


class HistoryPage(QWidget):
    def __init__(self, app_ctx, parent=None):
        super().__init__(parent)
        self.ctx = app_ctx
        self.rows = []
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 12)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addLayout(page_header("History", "Every finished job with its command and output. "
                                              "Double-click to see the log."), 1)
        self.btn_clear = QPushButton("Clear history")
        head.addWidget(self.btn_clear, 0, Qt.AlignTop)
        root.addLayout(head)
        c, cl = card()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["When", "Type", "Name", "Status", "Output"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Interactive)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setColumnWidth(3, 200)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(lambda i: self._log(i.row()))
        cl.addWidget(self.table)
        root.addWidget(c, 1)
        self.btn_clear.clicked.connect(self._clear)
        app_ctx.queue.job_finished.connect(lambda _id: self.reload() if self.isVisible() else None)

    def showEvent(self, e):
        self.reload()
        super().showEvent(e)

    def reload(self):
        self.rows = self.ctx.history.rows()
        t = self.table
        t.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            when = time.strftime("%d.%m.%Y %H:%M", time.localtime(row["finished"] or 0))
            vals = [when, KIND_LABEL.get(row["kind"], row["kind"]), row["title"],
                    row["status"] + (f": {row['message']}" if row["message"] else ""), row["output"]]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v or "")
                it.setToolTip(v or "")
                if c == 3:
                    it.setForeground(QColor(STATUS_COLOR.get(row["status"], "#ffffff")))
                t.setItem(r, c, it)

    def _log(self, r):
        if 0 <= r < len(self.rows):
            row = self.rows[r]
            LogDialog(row["title"], row["command"] or "", row["log"] or "", self).exec()

    def _menu(self, pos):
        r = self.table.indexAt(pos).row()
        if r < 0:
            return
        row = self.rows[r]
        m = QMenu(self)
        exists = bool(row["output"]) and os.path.exists(row["output"])
        a_open = m.addAction("Open output")
        a_show = m.addAction("Show in folder")
        a_log = m.addAction("View log and command")
        a_open.setEnabled(exists)
        a_show.setEnabled(exists)
        act = m.exec(self.table.viewport().mapToGlobal(pos))
        if act == a_open:
            open_path(row["output"])
        elif act == a_show:
            show_in_folder(row["output"])
        elif act == a_log:
            self._log(r)

    def _clear(self):
        if QMessageBox.question(self, "Clear history", "Remove all history entries?") == QMessageBox.Yes:
            self.ctx.history.clear()
            self.reload()
