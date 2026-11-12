"""ZeroStudio brand: line-drawn wordmark with a glowing ring as the zero, and the app icon.

Everything is drawn with QPainter so it is crisp at any DPI and needs no font or image files.
"""
import random

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import C

GLYPH_W = 0.66      # glyph width relative to cap height


def _glyph(ch, w=GLYPH_W):
    """Path for one capital letter in a 1-unit-high box (y down)."""
    p = QPainterPath()
    P = QPointF
    if ch == "Z":
        p.moveTo(P(0, 0)); p.lineTo(P(w, 0)); p.lineTo(P(0, 1)); p.lineTo(P(w, 1))
    elif ch == "E":
        p.moveTo(P(w, 0)); p.lineTo(P(0, 0)); p.lineTo(P(0, 1)); p.lineTo(P(w, 1))
        p.moveTo(P(0, 0.5)); p.lineTo(P(w * 0.8, 0.5))
    elif ch == "R":
        r = 0.25
        p.moveTo(P(0, 1)); p.lineTo(P(0, 0)); p.lineTo(P(w - r, 0))
        p.arcTo(QRectF(w - 2 * r, 0, 2 * r, 2 * r), 90, -180)
        p.lineTo(P(0, 0.5))
        p.moveTo(P(w * 0.42, 0.5)); p.lineTo(P(w, 1))
    elif ch == "S":
        r = 0.25
        p.moveTo(P(w, 0)); p.lineTo(P(r, 0))
        p.arcTo(QRectF(0, 0, 2 * r, 2 * r), 90, 180)
        p.lineTo(P(w - r, 0.5))
        p.arcTo(QRectF(w - 2 * r, 0.5, 2 * r, 2 * r), 90, -180)
        p.lineTo(P(0, 1))
    elif ch == "T":
        p.moveTo(P(0, 0)); p.lineTo(P(w, 0)); p.moveTo(P(w / 2, 0)); p.lineTo(P(w / 2, 1))
    elif ch == "U":
        p.moveTo(P(0, 0)); p.lineTo(P(0, 1 - w / 2))
        p.arcTo(QRectF(0, 1 - w, w, w), 180, 180)
        p.lineTo(P(w, 0))
    elif ch == "D":
        r = 0.5
        p.moveTo(P(0, 0)); p.lineTo(P(0, 1)); p.lineTo(P(w - r, 1))
        p.arcTo(QRectF(w - 2 * r, 0, 2 * r, 1), -90, 180)
        p.closeSubpath()
    elif ch == "I":
        p.moveTo(P(0, 0)); p.lineTo(P(0, 1))
    elif ch == "O":
        p.addEllipse(QRectF(0, 0, 1, 1))
    return p


def _glyph_width(ch):
    return 0.0 if ch == "I" else (1.0 if ch == "O" else GLYPH_W)


def draw_word(p, text, x, y, cap, tracking, color, stroke):
    """Draw text with line glyphs, top-left at (x, y). Returns the x after the last glyph."""
    pen = QPen(QColor(color), stroke, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    for i, ch in enumerate(text):
        if ch == " ":
            x += cap * 0.5
            continue
        p.save()
        p.translate(x, y)
        p.scale(cap, cap)
        p.setPen(QPen(QColor(color), stroke / cap, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
        p.drawPath(_glyph(ch))
        p.restore()
        x += _glyph_width(ch) * cap + (tracking if i < len(text) - 1 else 0)
    return x


def word_width(text, cap, tracking):
    w = 0.0
    for i, ch in enumerate(text):
        w += cap * 0.5 if ch == " " else _glyph_width(ch) * cap
        if i < len(text) - 1:
            w += tracking
    return w


def draw_ring(p, cx, cy, r, accent, intensity=1.0, small=False, weight=0.22):
    """The 'zero': a glowing ring with a thin horizontal light streak through it."""
    acc = QColor(accent)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(Qt.NoBrush)
    if not small:
        # soft outer glow: wide, faint rings
        for k in range(10, 0, -1):
            c = QColor(acc)
            c.setAlphaF(0.035 * intensity)
            p.setPen(QPen(c, r * 0.12 * k, Qt.SolidLine))
            p.drawEllipse(QPointF(cx, cy), r, r)
        # inner dark core so the ring reads as a hole
        g = QRadialGradient(QPointF(cx, cy), r * 0.9)
        g.setColorAt(0.0, QColor(0, 0, 0, 255))
        g.setColorAt(0.75, QColor(0, 0, 0, 230))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(cx, cy), r * 0.9, r * 0.9)
        p.setBrush(Qt.NoBrush)
    # main ring: accent with a lighter inner edge
    p.setPen(QPen(acc, r * (0.30 if small else weight)))
    p.drawEllipse(QPointF(cx, cy), r, r)
    hi = QColor(acc).lighter(165)
    hi.setAlphaF(0.95)
    p.setPen(QPen(hi, max(0.8, r * (0.10 if small else 0.07))))
    p.drawEllipse(QPointF(cx, cy), r * (0.96 if small else 0.95), r * (0.96 if small else 0.95))
    # offset secondary arc for the "lensed" look
    if not small:
        c2 = QColor(acc)
        c2.setAlphaF(0.55)
        p.setPen(QPen(c2, r * 0.06))
        p.drawEllipse(QPointF(cx, cy + r * 0.06), r * 1.16, r * 1.12)
    p.restore()


def draw_streak(p, x0, x1, y, thickness, accent, core="#ffffff"):
    """Horizontal light streak that fades out at both ends."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    for scale, alpha, col in ((5.0, 0.18, accent), (2.2, 0.45, accent), (1.0, 1.0, core)):
        g = QLinearGradient(QPointF(x0, y), QPointF(x1, y))
        c_mid = QColor(col)
        c_end = QColor(col)
        c_mid.setAlphaF(alpha)
        c_end.setAlphaF(0.0)
        g.setColorAt(0.0, c_end)
        g.setColorAt(0.45, c_mid)
        g.setColorAt(0.6, c_mid)
        g.setColorAt(1.0, c_end)
        p.setBrush(g)
        h = thickness * scale
        path = QPainterPath()
        # lens shape: thick in the middle, pointed at the ends
        mid = x0 + (x1 - x0) * 0.53
        path.moveTo(QPointF(x0, y))
        path.quadTo(QPointF(mid, y - h), QPointF(x1, y))
        path.quadTo(QPointF(mid, y + h), QPointF(x0, y))
        p.drawPath(path)
    p.restore()


def paint_wordmark(p, rect, accent=None, text_color=None, muted=None, sub="ASHKELAD TOOLKIT"):
    """ZER0 (big, ring as zero) / STUDIO (tracked) / sub line. Fits inside rect, left aligned."""
    accent = accent or C["accent"]
    text_color = text_color or C["text"]
    muted = muted or C["muted"]
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    W = rect.width()
    # Scale everything from the available width
    cap = W / 5.2
    track = cap * 0.42
    stroke = max(1.4, cap * 0.085)
    x = rect.x() + cap * 0.05
    y = rect.y() + cap * 0.35
    # draw letters on a layer so we can cut the slice line through them
    layer = QPixmap(int(rect.width() * 2), int(rect.height() * 2))
    layer.setDevicePixelRatio(2)
    layer.fill(Qt.transparent)
    lp = QPainter(layer)
    lp.setRenderHint(QPainter.Antialiasing)
    ox, oy = x - rect.x(), y - rect.y()
    end = draw_word(lp, "ZER", ox, oy, cap, track, text_color, stroke)
    r = cap * 0.52
    cx = end + track * 0.9 + r
    cy = oy + cap / 2
    # slice: a thin gap through the letters, slightly below the middle (like a horizon line)
    slice_y = cy + cap * 0.04
    lp.setCompositionMode(QPainter.CompositionMode_Clear)
    lp.fillRect(QRectF(ox + _glyph_width("Z") * cap * 0.55, slice_y - stroke * 0.55,
                       cx - ox, stroke * 1.1), Qt.transparent)
    lp.end()
    p.drawPixmap(rect.topLeft(), layer)
    abs_cx, abs_cy = rect.x() + cx, rect.y() + cy
    draw_ring(p, abs_cx, abs_cy, r, accent, weight=0.15)
    draw_streak(p, rect.x() + ox + cap * 0.9, min(rect.right(), abs_cx + r * 2.6), rect.y() + slice_y,
                max(0.9, stroke * 0.38), accent)
    # STUDIO line, tracked to the same width as ZER0
    full_w = (abs_cx + r) - x
    cap2 = cap * 0.34
    letters = "STUDIO"
    base_w = word_width(letters, cap2, 0)
    track2 = max(cap2 * 0.4, (full_w - base_w) / (len(letters) - 1))
    y2 = y + cap + cap * 0.48
    draw_word(p, letters, x, y2, cap2, track2, text_color, max(1.1, cap2 * 0.11))
    if sub:
        f = p.font()
        f.setPixelSize(max(8, int(cap * 0.26)))
        f.setLetterSpacing(QFont.PercentageSpacing, 135)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(muted))
        p.drawText(QRectF(x, y2 + cap2 + cap * 0.32, rect.width(), cap * 0.5),
                   Qt.AlignLeft | Qt.AlignTop, sub)
    p.restore()


def wordmark_height(width):
    cap = width / 5.2
    return int(cap * 0.35 + cap + cap * 0.48 + cap * 0.34 + cap * 0.32 + cap * 0.5 + 4)


class LogoWidget(QWidget):
    def __init__(self, parent=None, sub="ASHKELAD TOOLKIT"):
        super().__init__(parent)
        self.sub = sub
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(170, wordmark_height(170))

    def heightForWidth(self, w):
        return wordmark_height(w)

    def hasHeightForWidth(self):
        return True

    def resizeEvent(self, e):
        self.setFixedHeight(wordmark_height(min(self.width(), 190) - 8) + 8)
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        w = min(self.width(), 190) - 8
        paint_wordmark(p, QRectF(2, 8, w, self.height() - 8), sub=self.sub)
        p.end()


def icon_pixmap(size, accent=None):
    """App icon: black rounded square, faint stars, glowing green zero with a light streak."""
    accent = accent or C["accent"]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    small = size <= 32
    rad = size * 0.22
    bg = QRadialGradient(QPointF(size * 0.5, size * 0.45), size * 0.75)
    bg.setColorAt(0.0, QColor("#0b1210"))
    bg.setColorAt(1.0, QColor("#000000"))
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(0, 0, size, size), rad, rad)
    if size >= 64:
        rnd = random.Random(7)
        for _ in range(int(size * 0.35)):
            sx, sy = rnd.uniform(0.08, 0.92) * size, rnd.uniform(0.08, 0.92) * size
            a = rnd.uniform(0.15, 0.55)
            p.setBrush(QColor(255, 255, 255, int(255 * a)))
            d = rnd.choice((0.6, 0.8, 1.0)) * size / 256
            p.drawEllipse(QPointF(sx, sy), d, d)
    c = size / 2
    r = size * (0.27 if small else 0.25)
    draw_ring(p, c, c, r, accent, small=small)
    th = max(0.8, size * (0.022 if small else 0.012))
    draw_streak(p, size * (0.06 if small else 0.08), size * (0.94 if small else 0.92), c + r * 0.05, th, accent)
    p.end()
    return pm


def app_icon():
    ic = QIcon()
    for s in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        ic.addPixmap(icon_pixmap(s))
    return ic
