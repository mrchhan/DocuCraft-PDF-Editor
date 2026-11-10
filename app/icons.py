"""Consistent stroke icons (24x24 grid, drawn as inline SVG so they recolour with the theme)."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "logo": '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": '<path d="M5 3h12l3 3v15H5z"/><path d="M8 3v6h8V3"/><path d="M8 21v-7h8v7"/>',
    "saveas": '<path d="M5 3h12l3 3v7"/><path d="M5 3v18h8"/><path d="M8 3v6h8V3"/><path d="M17 21l4-4-2-2-4 4v2z"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
    "zoom_in": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3M11 8v6M8 11h6"/>',
    "zoom_out": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3M8 11h6"/>',
    "fit_width": '<path d="M3 12h18M7 8l-4 4 4 4M17 8l4 4-4 4"/>',
    "fit_page": '<rect x="6" y="3" width="12" height="18" rx="1"/><path d="M3 8V3h5M21 8V3h-5M3 16v5h5M21 16v5h-5"/>',
    "rotate": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "highlight": '<path d="M9 11l6 6-4 4H6v-5z"/><path d="M14 6l4 4-3 3-4-4z"/>',
    "underline": '<path d="M7 4v7a5 5 0 0 0 10 0V4"/><path d="M5 21h14"/>',
    "strike": '<path d="M16 6a4 4 0 0 0-8 1c0 4 8 3 8 8a4 4 0 0 1-8 1"/><path d="M4 12h16"/>',
    "note": '<path d="M4 4h16v12h-6l-4 4v-4H4z"/>',
    "text": '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
    "pen": '<path d="M3 21l3-1 12-12-2-2L4 18z"/><path d="M14 6l2 2"/>',
    "line": '<path d="M4 20L20 4"/>',
    "arrow": '<path d="M4 20L20 4M10 4h10v10"/>',
    "rect": '<rect x="4" y="5" width="16" height="14" rx="1"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="9" ry="7"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-8 8"/>',
    "signature": '<path d="M3 17c3-6 5-9 6-9s0 6 2 6 3-4 4-4 1 3 3 3"/><path d="M3 21h18"/>',
    "redact": '<rect x="3" y="9" width="18" height="6" fill="currentColor"/><path d="M3 5h8M13 5h8M3 19h8M13 19h8"/>',
    "replace": '<path d="M4 7h12M4 7l3-3M4 7l3 3"/><path d="M20 17H8M20 17l-3-3M20 17l-3 3"/>',
    "page_add": '<path d="M6 3h8l5 5v13H6z"/><path d="M12 11v6M9 14h6"/>',
    "page_del": '<path d="M6 3h8l5 5v13H6z"/><path d="M9 14h6"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "merge": '<path d="M6 4v6a6 6 0 0 0 6 6h0a6 6 0 0 0 6-6V4M12 16v5"/>',
    "split": '<path d="M12 3v6M12 9L6 15v6M12 9l6 6v6"/>',
    "compress": '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M10 14l-7 7"/>',
    "convert": '<path d="M4 8h13l-3-3M20 16H7l3 3"/>',
    "word": '<path d="M6 3h8l5 5v13H6z"/><path d="M8.5 11l1.5 6 2-5 2 5 1.5-6"/>',
    "pdf": '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5"/><path d="M8 17v-4h2a1.5 1.5 0 0 1 0 3H8"/>',
    "ocr": '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path d="M8 12h8M8 9h8M8 15h5"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "unlock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "star": '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "home": '<path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"/>',
    "moon": '<path d="M20 14A8 8 0 0 1 10 4a8 8 0 1 0 10 10z"/>',
    "preview": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "print": '<path d="M7 9V3h10v6"/><rect x="4" y="9" width="16" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "prev": '<path d="M15 5l-7 7 7 7"/>',
    "next": '<path d="M9 5l7 7-7 7"/>',
    "first": '<path d="M18 5l-7 7 7 7M6 5v14"/>',
    "last": '<path d="M6 5l7 7-7 7M18 5v14"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "fullscreen": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "extract": '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14"/>',
    "cursor": '<path d="M5 3l14 8-6 2-2 6z"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "up": '<path d="M6 15l6-6 6 6"/>',
    "down": '<path d="M6 9l6 6 6-6"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14-4L4 9"/><path d="M4 4v5h5M4 13a8 8 0 0 0 14 4l2-2"/><path d="M20 20v-5h-5"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "grid": '<rect x="4" y="4" width="7" height="7"/><rect x="13" y="4" width="7" height="7"/><rect x="4" y="13" width="7" height="7"/><rect x="13" y="13" width="7" height="7"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.5M3 12h.5M3 18h.5"/>',
    "bookmark": '<path d="M6 3h12v18l-6-4-6 4z"/>',
    "twopage": '<rect x="3" y="5" width="8" height="14"/><rect x="13" y="5" width="8" height="14"/>',
    "onepage": '<rect x="7" y="4" width="10" height="16"/>',
    "scroll": '<rect x="7" y="2" width="10" height="9"/><rect x="7" y="13" width="10" height="9"/>',
    "wand": '<path d="M4 20L16 8M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM19 12l.7 1.3L21 14l-1.3.7L19 16l-.7-1.3L17 14l1.3-.7z"/>',
}

_cache: dict[tuple, QPixmap] = {}


def svg_for(name: str, color: str) -> bytes:
    body = _P.get(name, _P["info"]).replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def pixmap(name: str, color: str = "#334155", size: int = 20) -> QPixmap:
    key = (name, color, size)
    if key not in _cache:
        scale = 2
        img = QImage(size * scale, size * scale, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        QSvgRenderer(QByteArray(svg_for(name, color))).render(p)
        p.end()
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(scale)
        _cache[key] = pm
    return _cache[key]


def icon(name: str, color: str = "#334155", size: int = 20, disabled_color: str = "#9aa4b2",
         active_color: str | None = None) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, active_color or color, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(pixmap(name, disabled_color, size), QIcon.Disabled, QIcon.Off)
    return ic


def clear_cache() -> None:
    _cache.clear()


def names() -> list[str]:
    return sorted(_P)
