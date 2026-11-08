"""Qt helpers for the embedded Shadow branding (see core/branding.py). Images always come from the program itself."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from app import theme
from core import branding


def _is_dark() -> bool:
    return theme.current() == "dark"


def pixmap(kind: str = "emblem", size: int = 64, dark: bool | None = None) -> QPixmap:
    """kind: 'emblem' (round face logo) or 'full' (complete logo artwork). Follows the theme unless `dark` is given."""
    dark = _is_dark() if dark is None else dark
    pm = QPixmap()
    pm.loadFromData(branding.asset(f"{kind}_{'dark' if dark else 'light'}"))
    if size and kind == "emblem":
        return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if size:
        return pm.scaledToWidth(size, Qt.SmoothTransformation)
    return pm


def window_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(pixmap("emblem", s, dark=True))
    return ic


def watermark_pixmap() -> QPixmap:
    pm = QPixmap()
    pm.loadFromData(branding.asset("watermark"))
    return pm


class WatermarkOverlay(QWidget):
    """Faint Shadow emblem over the whole work area. Ignores the mouse, so nothing underneath is affected."""
    OPACITY = 0.035

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._pm = watermark_pixmap()
        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self.raise_()

    def eventFilter(self, obj, ev):                                    # noqa: N802
        if ev.type() in (QEvent.Resize, QEvent.Show, QEvent.ChildAdded):
            self.setGeometry(obj.rect())
            self.raise_()
        return False

    def paintEvent(self, _ev) -> None:                                 # noqa: N802
        side = int(min(self.width(), self.height()) * 0.5)
        if side < 80:
            return
        p = QPainter(self)
        p.setOpacity(self.OPACITY)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap((self.width() - side) // 2, (self.height() - side) // 2, side, side, self._pm)
