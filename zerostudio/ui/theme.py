"""Dark theme: Fusion palette + one QSS string driven by colour tokens."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap

from ..paths import sub_dir

C = {
    "bg": "#15171c", "surface": "#1c1f26", "surface2": "#232731", "surface3": "#2c313d",
    "border": "#353b49", "text": "#e6e9ef", "muted": "#9aa3b5", "accent": "#3fb6a8",
    "accent_hi": "#56cbbd", "ok": "#5cc98a", "warn": "#e9b44c", "bad": "#ef6b6b", "on_accent": "#0e1a18",
    "video": "#7aa2f7", "audio": "#e0af68", "subtitles": "#bb9af7", "other": "#9aa3b5",
}


def _lum(hex_):
    c = QColor(hex_)
    out = []
    for v in (c.redF(), c.greenF(), c.blueF()):
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# White text on the accent fails WCAG AA here, so on_accent is dark; assert it stays readable.
assert contrast(C["on_accent"], C["accent"]) >= 4.5


def _dash_png():
    path = sub_dir("res") / "dash.png"
    if not path.exists():
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(C["on_accent"]), 4.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(9, 16), QPointF(23, 16))
        p.end()
        pm.save(str(path))
    return str(path).replace("\\", "/")


def _check_png():
    path = sub_dir("res") / "check.png"
    if not path.exists():
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(C["on_accent"]), 4.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(8, 17), QPointF(14, 23), QPointF(25, 10)])
        p.end()
        pm.save(str(path))
    return str(path).replace("\\", "/")


def apply(app):
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.Window: C["bg"], QPalette.WindowText: C["text"], QPalette.Base: C["surface"],
        QPalette.AlternateBase: C["surface2"], QPalette.Text: C["text"], QPalette.Button: C["surface2"],
        QPalette.ButtonText: C["text"], QPalette.Highlight: C["accent"], QPalette.HighlightedText: C["on_accent"],
        QPalette.ToolTipBase: C["surface3"], QPalette.ToolTipText: C["text"], QPalette.PlaceholderText: C["muted"],
        QPalette.Link: C["accent_hi"],
    }
    for role, col in roles.items():
        pal.setColor(role, QColor(col))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(C["muted"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(C["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(QSS.format(check=_check_png(), dash=_dash_png(), **C))


QSS = """
QWidget {{ font-size: 10pt; }}
QToolTip {{ background: {surface3}; color: {text}; border: 1px solid {border}; padding: 4px; }}
#Sidebar {{ background: {surface}; border-right: 1px solid {border}; }}
#Sidebar QPushButton {{ text-align: left; padding: 9px 14px; border: none; border-radius: 6px;
    background: transparent; color: {muted}; font-weight: 600; }}
#Sidebar QPushButton:hover {{ background: {surface2}; color: {text}; }}
#Sidebar QPushButton:checked {{ background: {surface3}; color: {accent_hi}; }}
#AppTitle {{ font-size: 15pt; font-weight: 700; color: {text}; padding: 6px 8px 2px 8px; }}
#AppSub {{ color: {muted}; padding: 0 8px 10px 8px; font-size: 9pt; }}
#PageTitle {{ font-size: 16pt; font-weight: 700; }}
#PageHint {{ color: {muted}; }}
#Muted {{ color: {muted}; }}
#Card {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
#CardTitle {{ font-weight: 700; color: {text}; }}
#Banner {{ background: #3a2f17; border: 1px solid {warn}; border-radius: 8px; }}
#Banner QLabel {{ color: {text}; }}
#DropHint {{ color: {muted}; font-size: 11pt; }}
QPushButton {{ background: {surface2}; border: 1px solid {border}; border-radius: 6px; padding: 6px 12px; color: {text}; }}
QPushButton:hover {{ background: {surface3}; }}
QPushButton:pressed {{ background: {border}; }}
QPushButton:disabled {{ color: {muted}; background: {surface}; }}
QPushButton#Primary {{ background: {accent}; color: {on_accent}; border: 1px solid {accent}; font-weight: 700; padding: 7px 18px; }}
QPushButton#Primary:hover {{ background: {accent_hi}; }}
QPushButton#Primary:disabled {{ background: {surface3}; color: {muted}; border-color: {border}; }}
QPushButton#Flat {{ background: transparent; border: none; color: {muted}; padding: 4px 8px; }}
QPushButton#Flat:hover {{ color: {text}; }}
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {{ background: {surface2}; border: 1px solid {border}; border-radius: 6px;
    padding: 4px 8px; color: {text}; selection-background-color: {accent}; selection-color: {on_accent}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {surface2}; border: 1px solid {border}; selection-background-color: {accent};
    selection-color: {on_accent}; outline: 0; }}
QTableView, QTreeView, QListView {{ background: {surface}; alternate-background-color: {surface2}; border: 1px solid {border};
    border-radius: 6px; gridline-color: {border}; selection-background-color: {surface3}; selection-color: {text}; outline: 0; }}
QTableView::item, QTreeView::item {{ padding: 2px 4px; }}
QListView::item {{ padding: 4px 6px; }}
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{ background: {surface3}; color: {text}; }}
QHeaderView::section {{ background: {surface2}; color: {muted}; border: none; border-bottom: 1px solid {border};
    padding: 5px 6px; font-weight: 600; }}
QCheckBox, QRadioButton {{ spacing: 7px; }}
QCheckBox::indicator, QTreeView::indicator, QListView::indicator, QTableView::indicator {{ width: 15px; height: 15px;
    border: 1px solid {border}; border-radius: 4px; background: {surface2}; }}
QCheckBox::indicator:hover, QTreeView::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked, QTreeView::indicator:checked, QListView::indicator:checked, QTableView::indicator:checked {{
    background: {accent}; border-color: {accent}; image: url({check}); }}
QTreeView::indicator:indeterminate, QCheckBox::indicator:indeterminate {{ background: {accent}; border-color: {accent}; image: url({dash}); }}
QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {border}; border-radius: 8px; background: {surface2}; }}
QRadioButton::indicator:hover {{ border-color: {accent}; }}
QRadioButton::indicator:checked {{ width: 6px; height: 6px; border: 5px solid {accent}; background: {on_accent}; }}
QLineEdit[langWarn="true"] {{ border-color: {warn}; }}
QPushButton#Expander {{ background: transparent; border: none; color: {text}; font-weight: 600; padding: 4px 6px 4px 0; text-align: left; }}
QPushButton#Expander:hover {{ color: {accent_hi}; }}
QPushButton#Problems {{ background: transparent; border: none; color: {warn}; padding: 2px 12px; font-weight: 600; }}
QPushButton#Problems:hover {{ color: {text}; }}
QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; top: -1px; background: {surface}; }}
QTabBar::tab {{ background: transparent; color: {muted}; padding: 7px 14px; border: none; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {accent}; }}
QTabBar::tab:hover {{ color: {text}; }}
QSplitter::handle {{ background: {bg}; }}
QSplitter::handle:vertical {{ height: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {surface3}; border-radius: 4px; min-height: 24px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {surface3}; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QMenu {{ background: {surface2}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent}; color: {on_accent}; }}
QMenu::item:disabled {{ color: {muted}; }}
QProgressBar {{ background: {surface2}; border: 1px solid {border}; border-radius: 5px; text-align: center; color: {text}; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
QPushButton#SegLeft, QPushButton#SegRight {{ background: {surface}; color: {muted}; padding: 5px 16px; font-weight: 600; }}
QPushButton#SegLeft {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
QPushButton#SegRight {{ border-top-left-radius: 0; border-bottom-left-radius: 0; border-left: none; }}
QPushButton#SegLeft:checked, QPushButton#SegRight:checked {{ background: {surface3}; color: {accent_hi}; }}
#QueueHeader {{ background: {surface}; border-top: 1px solid {border}; }}
"""
