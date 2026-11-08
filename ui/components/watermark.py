"""Faint Shadow emblem painted over the application's content area (display only)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from app import brand


class WatermarkOverlay(QWidget):
    """Transparent, click-through layer that sits on top of `host` and draws the Shadow emblem in its middle.

    `active` decides whether it paints (the PDF viewer draws its own per-page mark, so it is switched off there)."""

    def __init__(self, host: QWidget, active=lambda: True, opacity: float = 0.06):
        super().__init__(host)
        self._host, self._active, self._opacity = host, active, opacity
        self._pm = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self.raise_()

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if obj is self._host and ev.type() in (QEvent.Resize, QEvent.ChildAdded, QEvent.Show, QEvent.LayoutRequest):
            self.setGeometry(self._host.rect())
            self.raise_()
        return False

    def paintEvent(self, _ev) -> None:
        if not self._active():
            return
        if self._pm is None:
            self._pm = brand.watermark_pixmap()
        side = int(min(self.width(), self.height()) * 0.55)
        if side < 80:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setOpacity(self._opacity)
        p.drawPixmap((self.width() - side) // 2, (self.height() - side) // 2, side, side, self._pm)
        p.end()
