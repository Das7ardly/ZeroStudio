"""Download-and-install dialog for MKVToolNix."""
from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QVBoxLayout

from .. import mkvsetup
from ..engine import DOWNLOAD_PAGE


class _Worker(QThread):
    status = Signal(str)
    progress = Signal(int, int)
    done = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            folder, version = mkvsetup.install(progress=lambda d, t: self.progress.emit(d, t),
                                               cancelled=lambda: self._cancel,
                                               status=lambda s: self.status.emit(s))
            self.done.emit(True, f"MKVToolNix {version} is ready.\n{folder}")
        except mkvsetup.SetupError as e:
            self.done.emit(False, str(e))
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, f"{type(e).__name__}: {e}")


class MkvSetupDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.ok = False
        self.setWindowTitle("Get MKVToolNix")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("ZeroStudio uses MKVToolNix (free, by Moritz Bunkus) for muxing and extracting.\n"
                             "This downloads the portable version (about 30 MB) into ZeroStudio's own folder.\n"
                             "No admin rights needed, nothing else on your PC changes."))
        self.label = QLabel("Starting...")
        lay.addWidget(self.label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        self.bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.bb.rejected.connect(self._cancel)
        row.addStretch(1)
        row.addWidget(self.bb)
        lay.addLayout(row)
        self.worker = _Worker(self)
        self.worker.status.connect(self.label.setText)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._done)
        self.worker.start()

    def _progress(self, done, total):
        mb = done / 1048576
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
            self.bar.setFormat(f"{mb:.1f} / {total / 1048576:.1f} MB")
        else:
            self.bar.setRange(0, 0)
            self.bar.setFormat(f"{mb:.1f} MB")

    def _cancel(self):
        if self.worker.isRunning():
            self.label.setText("Cancelling...")
            self.worker.cancel()
        else:
            self.reject()

    def _done(self, ok, msg):
        self.worker.wait(3000)
        if ok:
            self.ok = True
            self.ctx.settings.mkvtoolnix_dir = ""
            self.ctx.settings.save()
            self.ctx.engine.reload("")
            self.ctx.engine_changed()
            QMessageBox.information(self, "MKVToolNix", msg)
            self.accept()
            return
        if msg == "Cancelled":
            self.reject()
            return
        box = QMessageBox(QMessageBox.Warning, "MKVToolNix", "The automatic download did not work.\n\n" + msg +
                          "\n\nYou can install it yourself instead (free), then ZeroStudio finds it automatically.",
                          parent=self)
        b_page = box.addButton("Open download page", QMessageBox.AcceptRole)
        b_wg = box.addButton("Copy winget command", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() == b_page:
            QDesktopServices.openUrl(QUrl(DOWNLOAD_PAGE))
        elif box.clickedButton() == b_wg:
            QGuiApplication.clipboard().setText(mkvsetup.WINGET)
        self.reject()

    def closeEvent(self, e):
        if self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(e)
