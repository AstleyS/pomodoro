"""Draw the countdown ring and timer icon used by the desktop UI."""
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

COLORS = {"Focus": "#e5484d", "Short break": "#30a46c", "Long break": "#3e63dd"}


def make_icon(color, remaining):
    """Render a tray icon containing the current countdown value."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(3, 3, 58, 58, 10, 10)
    value = math.ceil(remaining / 60) if remaining >= 60 else remaining
    font = QFont()
    font.setBold(True)
    font.setPixelSize(31)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, str(value))
    painter.end()
    return QIcon(pixmap)


class Ring(QWidget):
    """Paint the scalable countdown ring and handle its compact-mode gesture."""

    def __init__(self, owner):
        super().__init__()
        self.o = owner
        self.setMinimumSize(90, 90)

    def mouseDoubleClickEvent(self, _):
        self.o.toggle_compact()

    def paintEvent(self, _):
        owner = self.o
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()
        size = min(width, height)
        pen_width = max(6, size * 0.06)
        bounds = QRectF(
            (width - size) / 2 + pen_width,
            (height - size) / 2 + pen_width,
            size - 2 * pen_width,
            size - 2 * pen_width,
        )
        painter.setPen(QPen(QColor("#34343a"), pen_width))
        painter.drawEllipse(bounds)
        fraction = owner.remaining / owner.total()
        if fraction > 0:
            pen = QPen(QColor(COLORS[owner.mode]), pen_width)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawArc(bounds, 90 * 16, int(-min(359.9, 360 * fraction) * 16))

        minutes, seconds = divmod(owner.remaining, 60)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(10, int(size * 0.2)))
        painter.setFont(font)
        painter.setPen(QColor("#ededed"))
        painter.drawText(self.rect(), Qt.AlignCenter, f"{minutes:02d}:{seconds:02d}")
        if size > 150:
            font.setBold(False)
            font.setPixelSize(int(size * 0.065))
            painter.setFont(font)
            painter.setPen(QColor(COLORS[owner.mode]))
            painter.drawText(
                QRectF(0, height / 2 + size * 0.13, width, size * 0.1),
                Qt.AlignCenter,
                owner.mode,
            )
