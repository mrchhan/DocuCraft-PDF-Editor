"""Recent documents, favourites, My Documents browser and conversion history."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QDir, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileSystemModel, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem, QTreeView,
                               QVBoxLayout, QWidget)

from ui.components.widgets import confirm, icon, open_path, reveal
from ui.pages.home_page import ago

KIND_LABELS = {"pdf_to_word": "PDF → Word", "word_to_pdf": "Word → PDF", "merge": "Merge", "split": "Split",
               "compress": "Compress", "images_to_pdf": "Images → PDF", "pdf_to_images": "PDF → Images",
               "extract": "Extract", "protect": "Password", "sanitize": "Sanitize", "ocr": "OCR"}


class LibraryPage(QWidget):
    """kind: 'recent' | 'favorites'."""
    openPath = Signal(str)

    def __init__(self, ctx, kind: str, parent=None):
        super().__init__(parent)
        self.ctx, self.kind = ctx, kind
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        t = QLabel("Recent Documents" if kind == "recent" else "Favorites")
        t.setObjectName("Title")
        lay.addWidget(t)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by file name or folder…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self.refresh())
        row.addWidget(self.search, 1)
        self.btn_open = QPushButton("Open")
        self.btn_open.setObjectName("Primary")
        self.btn_fav = QPushButton("Favorite")
        self.btn_folder = QPushButton("Open containing folder")
        self.btn_remove = QPushButton("Remove selected")
        self.btn_all = QPushButton("Select all")
        for b in (self.btn_open, self.btn_fav, self.btn_folder, self.btn_remove, self.btn_all):
            row.addWidget(b)
        if kind == "recent":
            self.btn_clear = QPushButton("Clear history…")
            self.btn_clear.clicked.connect(self.clear_history)
            row.addWidget(self.btn_clear)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)    # Ctrl / Shift to pick several
        self.list.itemDoubleClicked.connect(lambda *_: self._open())
        self.list.itemSelectionChanged.connect(self._sel)
        lay.addWidget(self.list, 1)
        self.note = QLabel("")
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.btn_open.clicked.connect(self._open)
        self.btn_fav.clicked.connect(self._toggle_fav)
        self.btn_folder.clicked.connect(lambda: self._path() and reveal(self._path()))
        self.btn_remove.clicked.connect(self._remove)
        self.btn_all.clicked.connect(self.list.selectAll)
        self.refresh()

    def _paths(self) -> list[str]:
        return [it.data(Qt.UserRole) for it in self.list.selectedItems() if it.data(Qt.UserRole)]

    def _path(self) -> str | None:
        """The single selected document, or None when nothing or several are selected."""
        p = self._paths()
        return p[0] if len(p) == 1 else None

    def refresh(self) -> None:
        h = self.ctx.history
        docs = h.recent(self.search.text()) if self.kind == "recent" else h.favorites(self.search.text())
        self.list.clear()
        for d in docs:
            star = "★ " if (d.favorite or h.is_favorite(d.path)) else ""
            it = QListWidgetItem(icon("pdf", 22), f"{star}{d.name}\n{Path(d.path).parent}  ·  {ago(d.opened_at)}"
                                 + ("" if d.exists else "  ·  file not found"))
            it.setData(Qt.UserRole, d.path)
            self.list.addItem(it)
        if not h.enabled and self.kind == "recent":
            self.note.setText("Document history is turned off in Settings → General. Nothing is being recorded.")
        elif not docs:
            self.note.setText("Nothing here yet." if not self.search.text() else "No documents match your search.")
        else:
            self.note.setText(f"{len(docs)} document(s). Only file names and locations are stored — never document contents.")
        self._sel()

    def _sel(self) -> None:
        p, many = self._path(), self._paths()
        for b in (self.btn_open, self.btn_fav, self.btn_folder):
            b.setEnabled(bool(p))
        self.btn_remove.setEnabled(bool(many))
        self.btn_remove.setText(f"Remove selected ({len(many)})" if len(many) > 1 else "Remove selected")
        self.btn_all.setEnabled(self.list.count() > 0)
        if p:
            self.btn_fav.setText("Remove favorite" if self.ctx.history.is_favorite(p) else "Add to favorites")
            self.btn_open.setEnabled(Path(p).exists())

    def _open(self) -> None:
        p = self._path()
        if p and Path(p).exists():
            self.openPath.emit(p)

    def _toggle_fav(self) -> None:
        p = self._path()
        if p:
            (self.ctx.history.remove_favorite if self.ctx.history.is_favorite(p) else self.ctx.history.add_favorite)(p)
            self.refresh()

    def _remove(self) -> None:
        for p in self._paths():
            if self.kind == "favorites":
                self.ctx.history.remove_favorite(p)
            else:
                self.ctx.history.remove_recent(p)
        self.refresh()

    def clear_history(self) -> None:
        if confirm(self, "Clear history", "Remove all recent documents and conversion history? Your favorites are "
                   "kept. Your files are not touched.", yes="Clear history", danger=True):
            self.ctx.history.clear(keep_favorites=True)
            self.refresh()

    def retheme(self) -> None:
        self.refresh()


class MyDocumentsPage(QWidget):
    openPath = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        t = QLabel("My Documents")
        t.setObjectName("Title")
        lay.addWidget(t)
        row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        change = QPushButton("Change folder…")
        change.clicked.connect(self._choose)
        up = QPushButton("Open containing folder")
        up.clicked.connect(lambda: reveal(self.folder.text()))
        row.addWidget(self.folder, 1)
        row.addWidget(change)
        row.addWidget(up)
        lay.addLayout(row)
        self.model = QFileSystemModel()
        self.model.setNameFilters(["*.pdf"])
        self.model.setNameFilterDisables(False)
        self.model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Files)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        self.tree.setColumnWidth(0, 420)
        self.tree.setAlternatingRowColors(False)
        self.tree.doubleClicked.connect(self._dbl)
        lay.addWidget(self.tree, 1)
        hint = QLabel("Double-click a PDF to open it. Shows PDF files in the chosen folder and its sub-folders.")
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        start = self.ctx.files.default_output_dir() or Path.home() / "Documents"
        self.set_root(start if Path(start).is_dir() else Path.home())

    def set_root(self, path) -> None:
        p = str(path)
        self.folder.setText(p)
        self.tree.setRootIndex(self.model.setRootPath(p))

    def _choose(self) -> None:
        from ui.components.widgets import choose_dir
        d = choose_dir(self, self.ctx, "Choose a folder to browse", "mydocs")
        if d:
            self.set_root(d)

    def _dbl(self, idx) -> None:
        p = self.model.filePath(idx)
        if Path(p).is_file():
            self.openPath.emit(p)


class HistoryPage(QWidget):
    openPath = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        t = QLabel("Conversion History")
        t.setObjectName("Title")
        lay.addWidget(t)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search conversions…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self.refresh())
        row.addWidget(self.search, 1)
        self.b_open = QPushButton("Open result")
        self.b_open.setObjectName("Primary")
        self.b_folder = QPushButton("Show in folder")
        self.b_clear = QPushButton("Clear history…")
        for b in (self.b_open, self.b_folder, self.b_clear):
            row.addWidget(b)
        lay.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["When", "Type", "Source", "Result", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._sel)
        self.table.cellDoubleClicked.connect(lambda *_: self._open())
        lay.addWidget(self.table, 1)
        self.note = QLabel("")
        self.note.setObjectName("Muted")
        lay.addWidget(self.note)
        self.b_open.clicked.connect(self._open)
        self.b_folder.clicked.connect(lambda: self._out() and reveal(self._out()))
        self.b_clear.clicked.connect(self._clear)
        self.refresh()

    def _out(self) -> str | None:
        r = self.table.currentRow()
        it = self.table.item(r, 3) if r >= 0 else None
        return it.data(Qt.UserRole) if it and it.data(Qt.UserRole) else None

    def refresh(self) -> None:
        recs = self.ctx.history.conversions(self.search.text())
        self.table.setRowCount(len(recs))
        for r, c in enumerate(recs):
            vals = [time.strftime("%d %b %Y  %H:%M", time.localtime(c.started_at)), KIND_LABELS.get(c.kind, c.kind),
                    c.name, Path(c.output).name if c.output else "—", "Done" if c.status == "ok" else f"Failed — {c.detail}"[:80]]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if col == 3 and c.output:
                    it.setData(Qt.UserRole, c.output)
                    it.setToolTip(c.output)
                if col == 4 and c.status != "ok":
                    it.setForeground(Qt.red)
                self.table.setItem(r, col, it)
        self.note.setText(f"{len(recs)} entr{'y' if len(recs) == 1 else 'ies'}. Stored locally; file names only." if recs
                          else "No conversions yet.")
        self._sel()

    def _sel(self) -> None:
        o = self._out()
        for b in (self.b_open, self.b_folder):
            b.setEnabled(bool(o))
        if o:
            self.b_open.setEnabled(Path(o).exists())

    def _open(self) -> None:
        o = self._out()
        if o and Path(o).exists():
            (self.openPath.emit(o) if o.lower().endswith(".pdf") else open_path(o))

    def _clear(self) -> None:
        if confirm(self, "Clear history", "Remove the entire conversion history? Your converted files are not deleted.",
                   yes="Clear history", danger=True):
            self.ctx.history.clear(keep_favorites=True)
            self.refresh()

    def retheme(self) -> None:
        self.refresh()
