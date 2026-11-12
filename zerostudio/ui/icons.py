"""Tiny line icons drawn with QPainter (no image files, crisp on any DPI)."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _draw(name, p):
    P = QPointF
    if name == "mux":            # three lines merging into one arrow
        path = QPainterPath(P(3, 5))
        path.cubicTo(P(8, 5), P(9, 11), P(13, 11))
        path.moveTo(P(3, 11))
        path.lineTo(P(13, 11))
        path.moveTo(P(3, 17))
        path.cubicTo(P(8, 17), P(9, 11), P(13, 11))
        path.moveTo(P(13, 11))
        path.lineTo(P(19, 11))
        p.drawPath(path)
        p.drawPolyline([P(16, 8), P(19, 11), P(16, 14)])
    elif name == "extract":      # arrow down into a tray
        p.drawLine(P(11, 3), P(11, 13))
        p.drawPolyline([P(7, 9.5), P(11, 13.5), P(15, 9.5)])
        p.drawPolyline([P(3, 13), P(3, 18), P(19, 18), P(19, 13)])
    elif name == "edit":         # pencil
        p.drawPolygon([P(4, 18), P(5, 14), P(14.5, 4.5), P(17.5, 7.5), P(8, 17)])
        p.drawLine(P(12.5, 6.5), P(15.5, 9.5))
    elif name == "history":      # clock
        p.drawEllipse(QRectF(3, 3, 16, 16))
        p.drawPolyline([P(11, 7), P(11, 11), P(14, 13)])
    elif name == "settings":     # sliders
        for y, x in ((6, 8), (11, 14), (16, 6)):
            p.drawLine(P(3, y), P(19, y))
            p.setBrush(QColor(p.pen().color()))
            p.drawEllipse(P(x, y), 2.2, 2.2)
            p.setBrush(Qt.NoBrush)
    elif name == "subtitle":     # screen with two caption lines
        p.drawRoundedRect(QRectF(2.5, 4, 17, 14), 2.5, 2.5)
        p.drawLine(P(6, 11.5), P(16, 11.5))
        p.drawLine(P(8, 14.5), P(14, 14.5))
    elif name == "play":
        p.setBrush(QColor(p.pen().color()))
        p.drawPolygon([P(6, 4), P(17, 11), P(6, 18)])
    elif name == "up":
        p.drawLine(P(11, 18), P(11, 4))
        p.drawPolyline([P(6, 9), P(11, 4), P(16, 9)])
    elif name == "down":
        p.drawLine(P(11, 4), P(11, 18))
        p.drawPolyline([P(6, 13), P(11, 18), P(16, 13)])
    elif name == "plus":
        p.drawLine(P(11, 4), P(11, 18))
        p.drawLine(P(4, 11), P(18, 11))
    elif name == "folder":
        p.drawPolygon([P(3, 6), P(8.5, 6), P(10.5, 8.5), P(19, 8.5), P(19, 17.5), P(3, 17.5)])
    elif name == "new":          # blank page with a folded corner
        p.drawPolygon([P(5.5, 3), P(13, 3), P(17, 7), P(17, 19), P(5.5, 19)])
        p.drawPolyline([P(13, 3), P(13, 7), P(17, 7)])
    elif name == "chevron_right":
        p.drawPolyline([P(8, 5), P(14, 11), P(8, 17)])
    elif name == "chevron_down":
        p.drawPolyline([P(5, 8), P(11, 14), P(17, 8)])
    elif name == "save":
        p.drawPolyline([P(5, 11), P(9, 15), P(17, 6)])


def icon(name, color, size=22):
    out = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(size / 22, size / 22)
        p.setPen(QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        _draw(name, p)
        p.end()
        out.addPixmap(pm)
    return out


def nav_icon(name, normal, active):
    ic = QIcon()
    for col, state in ((normal, QIcon.Off), (active, QIcon.On)):
        ic.addPixmap(icon(name, col).pixmap(22, 22), QIcon.Normal, state)
    return ic
