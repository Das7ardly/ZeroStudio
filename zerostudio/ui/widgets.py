"""Small shared widgets and helpers."""
import os
import subprocess
import sys

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QVBoxLayout, QWidget)

from ..languages import LANGS, display, is_known, normalize, parse_list

MEDIA_EXTS = ("mkv mka mks mk3d webm mp4 m4v m4a mov avi ts m2ts mts mpg mpeg vob ogg ogm ogv opus flac wav "
              "aac ac3 eac3 dts thd mp3 mp2 h264 264 avc h265 265 hevc ivf obu srt ass ssa sub idx sup vtt usf "
              "textst xml txt").split()
MEDIA_FILTER = "Media files (" + " ".join("*." + e for e in MEDIA_EXTS) + ");;All files (*)"
MKV_FILTER = "Matroska files (*.mkv *.mka *.mks *.mk3d *.webm);;All files (*)"
# Containers the Extract page accepts: Matroska directly, everything else mkvmerge can read is remuxed to a temp MKV first
EXTRACT_EXTS = ("mkv mka mks mk3d webm mp4 m4v m4a mov qt 3gp 3g2 f4v flv avi divx ts m2ts mts m2t tp trp mpg mpeg mpe "
                "m1v m2v vob evo ogm ogv ogg rm rmvb wav flac").split()
EXTRACT_FILTER = ("Video files (" + " ".join("*." + e for e in EXTRACT_EXTS) + ");;"
                  "Matroska files (*.mkv *.mka *.mks *.mk3d *.webm);;All files (*)")


def card(title=None, hint=None):
    frame = QFrame(objectName="Card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
    if title:
        row = QHBoxLayout()
        row.addWidget(QLabel(title, objectName="CardTitle"))
        if hint:
            h = QLabel(hint, objectName="Muted")
            row.addWidget(h)
        row.addStretch(1)
        lay.addLayout(row)
        frame.title_row = row
    return frame, lay


def tinted_icon(widget, sp, color, size=18):
    """Standard Qt icon recoloured to one flat colour (the stock ones are black on a dark theme)."""
    src = widget.style().standardIcon(sp).pixmap(size, size)
    pm = QPixmap(src.size())
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.drawPixmap(0, 0, src)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(pm.rect(), QColor(color))
    p.end()
    return QIcon(pm)


def page_header(title, hint=""):
    box = QVBoxLayout()
    box.setSpacing(2)
    box.addWidget(QLabel(title, objectName="PageTitle"))
    if hint:
        h = QLabel(hint, objectName="PageHint")
        h.setWordWrap(True)
        box.addWidget(h)
    return box


class LangCombo(QComboBox):
    """Editable language picker. Items carry the 3-letter code in UserRole; typing any code also works."""

    def __init__(self, code="und", parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(18)
        for c3, _, name in LANGS:
            self.addItem(f"{c3} - {name}", c3)
        self.set_code(code)

    def set_code(self, code):
        code = normalize(code)
        i = self.findData(code)
        if i >= 0:
            self.setCurrentIndex(i)
        else:
            self.setEditText(code)
        self.lineEdit().setCursorPosition(0)

    def code(self):
        text = self.currentText().strip()
        i = self.currentIndex()
        if i >= 0 and self.itemText(i) == text:
            return self.itemData(i)
        return normalize(text.split(" ")[0]) if text else "und"


class LangListEdit(QLineEdit):
    """'bul, eng' field. A code ZeroStudio doesn't know (usually a typo) turns the border amber and is named
    in the tooltip, because a mistyped language silently matches nothing."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._tip = ""
        self.textChanged.connect(self._check)
        self._check()

    def setToolTip(self, tip):
        self._tip = tip
        self._check()

    def unknown(self):
        return [c for c in parse_list(self.text()) if not is_known(c)]

    def _check(self, *_):
        bad = self.unknown()
        warn = ("Not a language ZeroStudio knows: " + ", ".join(bad) + ". Use codes like bul, eng, rus "
                "(bg, en, Bulgarian also work).") if bad else ""
        QLineEdit.setToolTip(self, (warn + "\n\n" + self._tip).strip() if warn else self._tip)
        if bool(self.property("langWarn")) != bool(bad):
            self.setProperty("langWarn", bool(bad))
            self.style().unpolish(self)
            self.style().polish(self)


def add_shortcuts(page, add=None, start=None, remove=None):
    """Ctrl+O = add files, Ctrl+Enter = start, Delete = remove the selection (remove = (list widget, function)).
    They only fire while the keyboard focus is inside this page."""
    made = []
    for keys, fn, owner in ((["Ctrl+O"], add, page), (["Ctrl+Return", "Ctrl+Enter"], start, page),
                            ([QKeySequence.Delete], remove[1] if remove else None, remove[0] if remove else None)):
        for k in keys:
            if fn:
                sc = QShortcut(QKeySequence(k), owner)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                sc.activated.connect(fn)
                made.append(sc)
    return made


class CheckCell(QWidget):
    """Centered checkbox for table cells."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        self.box = QCheckBox()
        self.box.setChecked(checked)
        lay.addWidget(self.box)

    def isChecked(self):
        return self.box.isChecked()

    def setChecked(self, v):
        self.box.setChecked(v)


class DropFilter(QObject):
    """Event filter that accepts file drops on any widget and calls back with local paths."""

    def __init__(self, widget, callback):
        super().__init__(widget)
        self.callback = callback
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)
        vp = getattr(widget, "viewport", None)
        if vp:
            vp().setAcceptDrops(True)
            vp().installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (ev.Type.DragEnter, ev.Type.DragMove):
            if ev.mimeData().hasUrls():
                ev.acceptProposedAction()
                return True
        elif t == ev.Type.Drop and ev.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
            ev.acceptProposedAction()
            if paths:
                self.callback(paths)
            return True
        return False


def expand_paths(paths, exts=None):
    """Files stay files; folders are walked (one level deep is enough for seasons, but go recursive)."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in sorted(files):
                    if exts is None or os.path.splitext(f)[1].lower().lstrip(".") in exts:
                        out.append(os.path.join(root, f))
        elif os.path.isfile(p):
            out.append(p)
    return out


class _Signals(QObject):
    done = Signal(object, object)   # result, error


class _Task(QRunnable):
    def __init__(self, fn, signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            res, err = self.fn(), None
        except Exception as e:  # noqa: BLE001 - report any engine failure to UI
            res, err = None, e
        self.signals.done.emit(res, err)


_alive = set()


def run_async(fn, callback):
    """Run fn() on the thread pool; callback(result, error) on the GUI thread."""
    sig = _Signals()
    _alive.add(sig)

    def finish(res, err):
        _alive.discard(sig)
        callback(res, err)

    sig.done.connect(finish, Qt.QueuedConnection)
    QThreadPool.globalInstance().start(_Task(fn, sig))


def open_path(path):
    if path and os.path.exists(path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def show_in_folder(path):
    if not path:
        return
    if sys.platform == "win32" and os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin" and os.path.exists(path):
        subprocess.Popen(["open", "-R", path])
    else:
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        open_path(folder)


def pick_files(parent, settings, title, filt=MEDIA_FILTER):
    files, _ = QFileDialog.getOpenFileNames(parent, title, settings.last_dir, filt)
    if files:
        settings.last_dir = os.path.dirname(files[0])
    return files


def pick_folder(parent, settings, title):
    d = QFileDialog.getExistingDirectory(parent, title, settings.last_dir)
    if d:
        settings.last_dir = d
    return d


def lang_label(code):
    return display(code)
