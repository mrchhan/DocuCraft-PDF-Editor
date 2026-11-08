"""Left sidebar navigation."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QToolButton, QVBoxLayout

from ui.components.widgets import icon

ITEMS = [("home", "home", "Home"), ("recent", "clock", "Recent Documents"), ("mydocs", "folder", "My Documents"),
         ("favorites", "star", "Favorites"), ("tools", "layers", "PDF Tools"), ("history", "list", "Conversion History")]
BOTTOM = [("settings", "settings", "Settings")]


class Sidebar(QFrame):
    navigate = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(206)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 10, 12)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        for key, ic, label in ITEMS:
            lay.addWidget(self._btn(key, ic, label))
        lay.addStretch(1)
        for key, ic, label in BOTTOM:
            lay.addWidget(self._btn(key, ic, label))

    def _btn(self, key: str, ic: str, label: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("Nav")
        b.setText("  " + label)
        b.setIcon(icon(ic, 20))
        b.setIconSize(QSize(20, 20))
        b.setCheckable(True)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setSizePolicy(b.sizePolicy().horizontalPolicy().Expanding, b.sizePolicy().verticalPolicy())
        b.setProperty("icon_name", ic)
        b.setToolTip(label)
        b.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
        self.group.addButton(b)
        self.buttons[key] = b
        return b

    def select(self, key: str | None) -> None:
        self.group.setExclusive(False)
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        self.group.setExclusive(True)

    def retheme(self) -> None:
        for key, ic, _ in ITEMS + BOTTOM:
            self.buttons[key].setIcon(icon(ic, 20))
