"""Light/dark palettes and the application stylesheet (Windows-11 inspired)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

PALETTES = {
    "light": dict(bg="#f3f5f9", panel="#ffffff", surface="#eef1f6", border="#d9dee8", text="#1c2433", muted="#667085",
                  accent="#2f6df6", accent_hover="#2559d0", accent_text="#ffffff", hover="#e6ebf5", canvas="#dfe4ec",
                  icon="#334155", danger="#d92d20", ok="#12b76a", sel="#dbe7ff"),
    "dark": dict(bg="#14181f", panel="#1b212b", surface="#232b37", border="#2e3846", text="#e6eaf2", muted="#98a2b3",
                 accent="#5b8cff", accent_hover="#7aa0ff", accent_text="#0b1020", hover="#2a3342", canvas="#0f1319",
                 icon="#cbd5e1", danger="#f97066", ok="#32d583", sel="#26396b"),
}
_current = "light"
_FONT_CHOICES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", "Noto Sans", "DejaVu Sans"]


def resolve(name: str) -> str:
    if name == "system":
        try:
            scheme = QApplication.styleHints().colorScheme()
            from PySide6.QtCore import Qt
            return "dark" if scheme == Qt.ColorScheme.Dark else "light"
        except Exception:
            return "light"
    return name if name in PALETTES else "light"


def palette(name: str | None = None) -> dict:
    return PALETTES[name or _current]


def current() -> str:
    return _current


def pick_font(scale: int = 100) -> QFont:
    from PySide6.QtGui import QFontDatabase
    fams = set(QFontDatabase.families())
    f = QFont(next((c for c in _FONT_CHOICES if c in fams), QApplication.font().family()))
    f.setPointSizeF(9.5 * scale / 100)
    return f


def stylesheet(c: dict) -> str:
    return f"""
* {{ outline: 0; }}
QWidget {{ color: {c['text']}; }}
QMainWindow, QDialog, QStackedWidget, QScrollArea {{ background: {c['bg']}; }}
QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px 6px; }}
#Header {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
#Sidebar {{ background: {c['panel']}; border-right: 1px solid {c['border']}; }}
#Ribbon {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
#SidePanel {{ background: {c['panel']}; border-right: 1px solid {c['border']}; }}
#Card {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}
#Card:hover {{ border-color: {c['accent']}; }}
QLabel#Title {{ font-size: 20pt; font-weight: 600; }}
QLabel#H2 {{ font-size: 13pt; font-weight: 600; }}
QLabel#Muted {{ color: {c['muted']}; }}
QPushButton {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton#Primary {{ background: {c['accent']}; color: {c['accent_text']}; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {c['accent_hover']}; }}
QPushButton#Danger {{ background: {c['danger']}; color: white; border: none; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px 6px; }}
QToolButton:hover {{ background: {c['hover']}; }}
QToolButton:checked {{ background: {c['sel']}; border: 1px solid {c['accent']}; }}
QToolButton:disabled {{ color: {c['muted']}; }}
QToolButton#Nav {{ padding: 9px 12px; text-align: left; border-radius: 8px; }}
QToolButton#Nav:checked {{ background: {c['sel']}; color: {c['text']}; border: 1px solid transparent; font-weight: 600; }}
QToolButton#Tab {{ padding: 8px 16px; border-radius: 0; border-bottom: 2px solid transparent; }}
QToolButton#Tab:checked {{ background: transparent; border: none; border-bottom: 2px solid {c['accent']}; font-weight: 600; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {c['accent']}; selection-color: {c['accent_text']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {c['accent']}; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid {c['border']}; selection-background-color: {c['sel']}; selection-color: {c['text']}; }}
QListWidget, QTreeWidget, QTableWidget {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; }}
QListWidget::item, QTreeWidget::item {{ padding: 5px; border-radius: 5px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {c['hover']}; }}
QHeaderView::section {{ background: {c['surface']}; border: none; padding: 6px; }}
QTabBar::tab {{ background: transparent; padding: 7px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ border-bottom: 2px solid {c['accent']}; font-weight: 600; }}
QTabBar::tab:hover {{ background: {c['hover']}; }}
QTabWidget::pane {{ border: none; }}
QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['sel']}; color: {c['text']}; }}
QMenuBar {{ background: transparent; }} QMenuBar::item:selected {{ background: {c['hover']}; border-radius: 5px; }}
QStatusBar {{ background: {c['panel']}; border-top: 1px solid {c['border']}; color: {c['muted']}; }}
QProgressBar {{ background: {c['surface']}; border: none; border-radius: 5px; height: 10px; text-align: center; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
QGroupBox {{ border: 1px solid {c['border']}; border-radius: 8px; margin-top: 14px; padding: 12px 10px 8px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {c['muted']}; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle {{ background: {c['border']}; border-radius: 5px; min-height: 30px; min-width: 30px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {c['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSplitter::handle {{ background: {c['border']}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
"""


def apply_theme(app: QApplication, name: str, scale: int = 100) -> str:
    global _current
    _current = resolve(name)
    c = PALETTES[_current]
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "panel"), (QPalette.AlternateBase, "surface"),
                      (QPalette.Text, "text"), (QPalette.WindowText, "text"), (QPalette.Button, "surface"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"), (QPalette.HighlightedText, "accent_text"),
                      (QPalette.ToolTipBase, "panel"), (QPalette.ToolTipText, "text")):
        pal.setColor(role, QColor(c[key]))
    app.setStyle("Fusion")
    app.setPalette(pal)
    app.setFont(pick_font(scale))
    app.setStyleSheet(stylesheet(c))
    from app import icons
    icons.clear_cache()
    return _current


def ic(name: str, size: int = 20, color_key: str = "icon", active: bool = False):
    from app import icons
    return icons.icon(name, PALETTES[_current][color_key if not active else "accent"], size,
                      disabled_color=PALETTES[_current]["muted"])
