"""Welcome screen shown when no document is open."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from app import brand, icons, theme
from app.settings import APP_NAME, TAGLINE
from ui.components.widgets import Card, icon

CARDS = [
    ("pdf2word", "word", "PDF to Word", "Editable .docx with tables, images and OCR for scans"),
    ("word2pdf", "pdf", "Word to PDF", "Convert documents with LibreOffice, offline"),
    ("merge", "merge", "Merge PDF", "Combine several files into one"),
    ("split", "split", "Split PDF", "By range, every page or equal groups"),
    ("compress", "compress", "Compress PDF", "Low, balanced or high compression"),
    ("images2pdf", "image", "Images to PDF", "JPG and PNG pictures into one document"),
    ("ocr", "ocr", "Make searchable", "OCR for scanned documents"),
    ("protect", "lock", "Protect PDF", "AES-256 password protection"),
]


def ago(ts: float) -> str:
    d = max(0, time.time() - ts)
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return time.strftime("%d %b %Y", time.localtime(ts))


class HomePage(QScrollArea):
    openRequested = Signal()
    openPath = Signal(str)
    toolRequested = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        self.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(44, 34, 44, 30)
        lay.setSpacing(6)

        head = QHBoxLayout()
        self.logo = QLabel()
        head.addWidget(self.logo)
        col = QVBoxLayout()
        title = QLabel(f"Welcome to {APP_NAME}")
        title.setObjectName("Title")
        tag = QLabel(f"{TAGLINE}  Everything runs on this computer — nothing is uploaded.")
        tag.setObjectName("Muted")
        col.addWidget(title)
        col.addWidget(tag)
        head.addLayout(col, 1)
        self.open_btn = QPushButton("  Open PDF…")
        self.open_btn.setObjectName("Primary")
        self.open_btn.setMinimumHeight(40)
        self.open_btn.setMinimumWidth(150)
        self.open_btn.clicked.connect(self.openRequested.emit)
        head.addWidget(self.open_btn, 0, Qt.AlignTop)
        lay.addLayout(head)
        lay.addSpacing(14)

        h = QLabel("Tools")
        h.setObjectName("H2")
        lay.addWidget(h)
        grid = QGridLayout()
        grid.setSpacing(12)
        for n, (key, ic, t, d) in enumerate(CARDS):
            c = Card(ic, t, d)
            c.clicked.connect(lambda k=key: self.toolRequested.emit(k))
            grid.addWidget(c, n // 4, n % 4)
        for col_i in range(4):
            grid.setColumnStretch(col_i, 1)
        lay.addLayout(grid)
        lay.addSpacing(16)

        h2 = QLabel("Recent documents")
        h2.setObjectName("H2")
        lay.addWidget(h2)
        self.recent = QListWidget()
        self.recent.setMinimumHeight(180)
        self.recent.itemActivated.connect(self._open_item)
        self.recent.itemClicked.connect(self._open_item)
        self.recent.setContextMenuPolicy(Qt.CustomContextMenu)
        self.recent.customContextMenuRequested.connect(self._recent_menu)
        lay.addWidget(self.recent, 1)
        self.empty = QLabel("No recent documents yet. Open a PDF, or drag one onto this window.")
        self.recent.setToolTip("Right-click a document to remove it from this list. Use Recent Documents in the sidebar to select several.")
        self.empty.setObjectName("Muted")
        lay.addWidget(self.empty)
        self.refresh()

    def _recent_menu(self, pos) -> None:
        """Right-click a recent document to drop it from the list (the file itself is never touched)."""
        it = self.recent.itemAt(pos)
        path = it.data(Qt.UserRole + 1) if it else None
        if not path:
            return
        menu = QMenu(self)
        menu.addAction("Remove from list", lambda: (self.ctx.history.remove_recent(path), self.refresh()))
        menu.exec(self.recent.viewport().mapToGlobal(pos))

    def _open_item(self, it: QListWidgetItem) -> None:
        p = it.data(Qt.UserRole)
        if p:
            self.openPath.emit(p)

    def refresh(self) -> None:
        self.recent.clear()
        docs = [d for d in self.ctx.history.recent(limit=8)]
        for d in docs:
            it = QListWidgetItem(icon("pdf", 20), f"{d.name}\n{Path(d.path).parent}  ·  {ago(d.opened_at)}"
                                 + ("" if d.exists else "  ·  file not found"))
            it.setData(Qt.UserRole, d.path if d.exists else "")
            it.setData(Qt.UserRole + 1, d.path)
            self.recent.addItem(it)
        self.recent.setVisible(bool(docs))
        self.empty.setVisible(not docs)
        self.logo.setPixmap(brand.pixmap("emblem", 64))

    def retheme(self) -> None:
        self.refresh()
        for c in self.findChildren(Card):
            pass
