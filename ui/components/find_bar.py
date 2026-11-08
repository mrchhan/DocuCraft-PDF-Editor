"""Find-in-document bar (Ctrl+F)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QWidget

from ui.components.widgets import tool_button


class FindBar(QWidget):
    searchRequested = Signal(str, bool)       # text, case sensitive
    stepRequested = Signal(int)               # +1 / -1
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FindBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Find in document…")
        self.edit.setClearButtonEnabled(True)
        self.edit.setMinimumWidth(240)
        self.case = QCheckBox("Match case")
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        lay.addWidget(self.edit)
        lay.addWidget(tool_button("up", "Previous result", slot=lambda: self.stepRequested.emit(-1)))
        lay.addWidget(tool_button("down", "Next result", slot=lambda: self.stepRequested.emit(1)))
        lay.addWidget(self.case)
        lay.addWidget(self.count)
        lay.addStretch(1)
        lay.addWidget(tool_button("close", "Close find bar", slot=self.close_bar))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._emit)
        self.edit.textChanged.connect(lambda *_: self._timer.start())
        self.case.toggled.connect(lambda *_: self._emit())
        self.edit.returnPressed.connect(lambda: self.stepRequested.emit(1))
        self.hide()

    def _emit(self) -> None:
        self.searchRequested.emit(self.edit.text(), self.case.isChecked())

    def open_bar(self, text: str = "") -> None:
        self.show()
        if text:
            self.edit.setText(text)
        self.edit.setFocus()
        self.edit.selectAll()

    def close_bar(self) -> None:
        self.hide()
        self.closed.emit()

    def set_result(self, index: int, total: int, searching: bool = False) -> None:
        if searching:
            self.count.setText("Searching…")
        elif not self.edit.text().strip():
            self.count.setText("")
        elif total == 0:
            self.count.setText("No results")
        else:
            self.count.setText(f"{index + 1} of {total}")

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape:
            self.close_bar()
            return
        super().keyPressEvent(e)
