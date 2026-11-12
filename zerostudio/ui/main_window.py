"""Main window: sidebar navigation, pages, and the job queue panel."""
import os
import time

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import APP_NAME, VERSION
from ..history import History
from ..jobs import JobQueue
from .edit_page import EditPage
from .extract_page import ExtractPage
from .history_page import HistoryPage
from .mux_page import MultiplexPage
from .queue_panel import QueuePanel
from .settings_page import SettingsPage
from .setup_dialog import MkvSetupDialog
from .. import mkvsetup
from .subconv_page import SubConvPage
from .theme import C
from .brand import LogoWidget, app_icon
from .icons import nav_icon


class MainWindow(QMainWindow):
    def __init__(self, settings, engine):
        super().__init__()
        self.settings = settings
        self.engine = engine
        self.history = History()
        self.queue = JobQueue(engine, settings, self.history, self)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        scr = QGuiApplication.primaryScreen()
        avail = scr.availableGeometry() if scr else None
        if avail and avail.width() > 0:
            self.resize(min(1320, int(avail.width() * 0.92)), min(980, int(avail.height() * 0.92)))
        else:
            self.resize(1280, 860)
        self.setMinimumSize(980, 660)

        central = QWidget()
        self.setCentralWidget(central)
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # Sidebar
        side = QFrame(objectName="Sidebar")
        side.setFixedWidth(196)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 18, 10, 12)
        sl.setSpacing(4)
        logo = LogoWidget()
        logo.setToolTip(f"{APP_NAME} {VERSION}")
        sl.addWidget(logo)
        sl.addSpacing(14)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.stack = QStackedWidget()
        self.pages = {}
        for key, label, icon, cls in (
                ("mux", "Multiplex", "mux", MultiplexPage),
                ("extract", "Extract", "extract", ExtractPage),
                ("edit", "Quick edit", "edit", EditPage),
                ("subconv", "Subtitles to UTF-8", "subtitle", SubConvPage),
                ("history", "History", "history", HistoryPage),
                ("settings", "Settings", "settings", SettingsPage)):
            page = cls(self)
            self.pages[key] = page
            idx = self.stack.addWidget(page)
            b = QPushButton(label)
            b.setIcon(nav_icon(icon, C["muted"], C["accent_hi"]))
            b.setIconSize(QSize(20, 20))
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav.addButton(b, idx)
            if key == "history":
                sl.addSpacing(14)
            sl.addWidget(b)
        sl.addStretch(1)
        self.engine_label = QLabel("", objectName="Muted")
        self.engine_label.setWordWrap(True)
        self.engine_label.setStyleSheet("font-size: 8pt; padding: 0 6px;")
        sl.addWidget(self.engine_label)
        ver = QLabel(f"v{VERSION}", objectName="Muted")
        ver.setStyleSheet("font-size: 8pt; padding: 0 6px;")
        sl.addWidget(ver)
        h.addWidget(side)
        self.nav.idClicked.connect(self.stack.setCurrentIndex)
        self.nav.button(0).setChecked(True)

        # Right side
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.banner = QFrame(objectName="Banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 10, 8)
        bl.addWidget(QLabel("MKVToolNix was not found. It is free and does the actual muxing and extracting."), 1)
        b_set = QPushButton("Set it up")
        b_set.clicked.connect(self.offer_engine)
        bl.addWidget(b_set)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(16, 12, 16, 0)
        wl.addWidget(self.banner)
        self.banner_wrap = wrap
        rl.addWidget(wrap)

        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self.stack)
        self.queue_panel = QueuePanel(self.queue)
        self.split.addWidget(self.queue_panel)
        self.split.setStretchFactor(0, 1)
        self.split.setSizes([620, max(120, int(settings.queue_panel_size or 170))])
        self.queue_panel.toggled.connect(self._queue_toggled)
        rl.addWidget(self.split, 1)
        h.addWidget(right, 1)

        self.toast_label = QLabel("")
        self.statusBar().addWidget(self.toast_label, 1)
        self.problems = []           # (time, text) of every error message, so none is lost when the next one shows
        self.problems_btn = QPushButton("", objectName="Problems")
        self.problems_btn.setCursor(Qt.PointingHandCursor)
        self.problems_btn.setToolTip("Skipped files and failed jobs since ZeroStudio started. Click to see them all.")
        self.problems_btn.clicked.connect(self.show_problems)
        self.problems_btn.hide()
        self.statusBar().addPermanentWidget(self.problems_btn)
        self.statusBar().setStyleSheet(f"QStatusBar {{ background: {C['surface']}; border-top: 1px solid {C['border']}; }}")
        self._toast_timer = QTimer(self, singleShot=True, timeout=lambda: self.toast_label.setText(""))

        self.queue.job_finished.connect(self._job_finished)
        self.queue.restore()
        if not self.queue.jobs:
            QTimer.singleShot(0, lambda: self.queue_panel.set_expanded(False))
        if settings.window_geometry:
            try:
                self.restoreGeometry(QByteArray.fromHex(settings.window_geometry.encode()))
            except Exception:
                pass
        self.engine_changed()
        if not engine.ok and not os.environ.get("ZEROSTUDIO_SELFTEST"):
            QTimer.singleShot(600, self.offer_engine)

    # ---------- context API used by pages ----------
    def go(self, key):
        idx = self.stack.indexOf(self.pages[key])
        self.stack.setCurrentIndex(idx)
        self.nav.button(idx).setChecked(True)

    def toast(self, text, error=False):
        self.toast_label.setStyleSheet(f"color: {C['bad'] if error else C['text']}; padding-left: 8px;")
        self.toast_label.setText(text)
        self._toast_timer.start(6000)
        if error:
            self.problems.append((time.strftime("%H:%M:%S"), text))
            del self.problems[:-200]
            self._update_problems()

    def _update_problems(self):
        n = len(self.problems)
        self.problems_btn.setText(f"{n} problem{'s' if n != 1 else ''}")
        self.problems_btn.setVisible(n > 0)

    def show_problems(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Problems")
        dlg.resize(760, 420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Files that were skipped and jobs that failed, newest last."))
        txt = QPlainTextEdit("\n".join(f"{t}   {m}" for t, m in self.problems))
        txt.setReadOnly(True)
        lay.addWidget(txt, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        clear = bb.addButton("Clear list", QDialogButtonBox.ActionRole)
        clear.clicked.connect(lambda: (self.problems.clear(), self._update_problems(), dlg.accept()))
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        txt.moveCursor(txt.textCursor().MoveOperation.End)
        dlg.exec()

    def need_engine(self):
        self.offer_engine()

    def offer_engine(self):
        """First run (or MKVToolNix missing): download it for the user, or let them point to it."""
        box = QMessageBox(QMessageBox.Information, APP_NAME,
                          "ZeroStudio needs MKVToolNix (free) to mux, extract and edit files.\n\n"
                          "It can download the portable version for you (about 30 MB, no admin rights), "
                          "or you can point to an MKVToolNix you already have.", parent=self)
        b_dl = box.addButton("Download it for me", QMessageBox.AcceptRole) if mkvsetup.supported() else None
        b_dir = box.addButton("I have it: choose folder", QMessageBox.ActionRole)
        box.addButton("Later", QMessageBox.RejectRole)
        if b_dl:
            box.setDefaultButton(b_dl)
        box.exec()
        if b_dl is not None and box.clickedButton() == b_dl:
            MkvSetupDialog(self, self).exec()
        elif box.clickedButton() == b_dir:
            self.go("settings")
            self.pages["settings"]._browse()

    def engine_changed(self):
        self.banner_wrap.setVisible(not self.engine.ok)
        if "settings" in getattr(self, "pages", {}):
            self.pages["settings"].dir_edit.setText(self.settings.mkvtoolnix_dir)
            self.pages["settings"]._update_status()
        v = self.engine.version()
        self.engine_label.setText(v.split("(")[0].strip() if v else "MKVToolNix: not found")

    def open_files(self, paths):
        self.go("mux")
        self.pages["mux"].add_files(paths)

    # ---------- events ----------
    def _queue_toggled(self, visible):
        if visible:
            hq = max(130, int(self.settings.queue_panel_size or 170))
            self.split.setSizes([self.split.height() - hq, hq])
        else:
            hh = self.queue_panel.sizeHint().height()
            self.split.setSizes([self.split.height() - hh, hh])

    def _job_finished(self, job_id):
        job = self.queue.get(job_id)
        if job and job.status == "Error":
            self.toast(f"{job.title}: {job.message}", error=True)
        elif job and not self.queue.busy():
            self.toast("All jobs finished")

    def closeEvent(self, e):
        if self.queue.busy():
            r = QMessageBox.question(self, APP_NAME, "Jobs are still running. Stop them and quit?\n"
                                                     "Unfinished jobs stay in the list and can be run again.")
            if r != QMessageBox.Yes:
                e.ignore()
                return
        self.queue.shutdown()
        s = self.settings
        s.window_geometry = bytes(self.saveGeometry().toHex()).decode()
        sizes = self.split.sizes()
        if len(sizes) == 2 and self.queue_panel.view.isVisible():
            s.queue_panel_size = sizes[1]
        try:
            s.save()
        except OSError:
            pass
        super().closeEvent(e)


def selftest(win, out_dir, files):
    """ZEROSTUDIO_SELFTEST=<dir>: load files, screenshot every page, then quit."""
    os.makedirs(out_dir, exist_ok=True)
    if files:
        win.pages["mux"].add_files(files[:1] + [f for f in files if f.lower().endswith(".srt")])
        mkvs = [f for f in files if f.lower().endswith(".mkv")]
        win.pages["extract"].add_files(mkvs)
        win.pages["edit"].add_files(mkvs)

    def shoot():
        for key in ("mux", "extract", "edit", "subconv", "history", "settings"):
            win.go(key)
            win.repaint()
            win.grab().save(os.path.join(out_dir, f"{key}.png"))
        win.queue.shutdown()
        os._exit(0)   # self-test only: skip normal shutdown (Qt's quit() deadlocks under Wine)

    QTimer.singleShot(int(os.environ.get("ZEROSTUDIO_SELFTEST_DELAY", "4000")), shoot)
