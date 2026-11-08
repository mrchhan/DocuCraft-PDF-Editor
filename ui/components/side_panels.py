"""Left-hand navigation panels: lazy thumbnails (with drag-reorder and page actions) and bookmarks."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QListView, QListWidget, QListWidgetItem, QMenu, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget, QLabel)

THUMB = 128


class ThumbnailPanel(QListWidget):
    """One entry per page. Thumbnails are rendered a few at a time, only for rows that are visible."""
    pageActivated = Signal(int)
    pagesAction = Signal(str, list)          # action name, page indexes
    reordered = Signal(list)                 # new order (list of old indexes)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self._done: set[int] = set()
        self._updating = False
        self.setViewMode(QListView.ListMode)
        self.setIconSize(QSize(THUMB, int(THUMB * 1.3)))
        self.setSpacing(4)
        self.setUniformItemSizes(False)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(lambda it: self.pageActivated.emit(it.data(Qt.UserRole)))
        self.model().rowsMoved.connect(self._moved)
        self.verticalScrollBar().valueChanged.connect(self._schedule)
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._render_batch)
        self.rebuild()

    # ---- content ----
    def rebuild(self) -> None:
        self._updating = True
        sel = [i.data(Qt.UserRole) for i in self.selectedItems()]
        self.clear()
        self._done.clear()
        r = self.session.reader
        for i in range(r.page_count):
            w, h = r.page_size(i)
            it = QListWidgetItem(f"{i + 1}")
            it.setData(Qt.UserRole, i)
            it.setTextAlignment(Qt.AlignHCenter)
            side = THUMB / max(w, h)
            it.setSizeHint(QSize(THUMB + 20, int(h * side) + 34))
            self.addItem(it)
            if i in sel:
                it.setSelected(True)
        self._updating = False
        self._schedule()

    def highlight(self, page: int) -> None:
        if 0 <= page < self.count():
            self.blockSignals(True)
            self.setCurrentRow(page)
            self.blockSignals(False)
            self.scrollToItem(self.item(page))

    def _schedule(self, *_) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._schedule()

    def _visible_rows(self) -> list[int]:
        out = []
        vp = self.viewport().rect()
        for i in range(self.count()):
            if self.visualItemRect(self.item(i)).intersects(vp):
                out.append(i)
        return out

    def _render_batch(self) -> None:
        todo = [i for i in self._visible_rows() if self.item(i).data(Qt.UserRole) not in self._done]
        if not todo:
            self._timer.stop()
            return
        r = self.session.reader
        for row in todo[:3]:
            it = self.item(row)
            idx = it.data(Qt.UserRole)
            try:
                w, h = r.page_size(idx)
                pix = r.render(idx, zoom=THUMB / max(w, h) * self.devicePixelRatioF())
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
                pm = QPixmap.fromImage(img)
                pm.setDevicePixelRatio(self.devicePixelRatioF())
                it.setIcon(QIcon(pm))
            except Exception:
                pass
            self._done.add(idx)

    # ---- interaction ----
    def selected_pages(self) -> list[int]:
        return sorted(i.data(Qt.UserRole) for i in self.selectedItems())

    def _moved(self, *_) -> None:
        if self._updating:
            return
        order = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        if order != sorted(order):
            self.reordered.emit(order)

    def _menu(self, pos) -> None:
        pages = self.selected_pages()
        if not pages:
            it = self.itemAt(pos)
            if it:
                pages = [it.data(Qt.UserRole)]
        if not pages:
            return
        m = QMenu(self)
        n = len(pages)
        for text, act in ((f"Rotate right (90°)", "rotate_cw"), ("Rotate left (90°)", "rotate_ccw"),
                          ("Duplicate", "duplicate"), ("Insert blank page after", "insert_blank"),
                          ("Extract to new PDF…", "extract"), ("Replace from another PDF…", "replace"),
                          (f"Delete {n} page(s)", "delete")):
            a = m.addAction(text)
            a.setData(act)
        chosen = m.exec(self.viewport().mapToGlobal(pos))
        if chosen:
            self.pagesAction.emit(chosen.data(), pages)


class OutlinePanel(QWidget):
    pageActivated = Signal(int)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(lambda it, _: self.pageActivated.emit(it.data(0, Qt.UserRole))
                                      if it.data(0, Qt.UserRole) >= 0 else None)
        self.empty = QLabel("This document has no bookmarks.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        lay.addWidget(self.tree)
        lay.addWidget(self.empty)
        self.fill(session)

    def fill(self, session) -> None:
        self.tree.clear()
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for o in session.reader.outline():
            it = QTreeWidgetItem([o.title or "(untitled)"])
            it.setData(0, Qt.UserRole, o.page)
            while stack and stack[-1][0] >= o.level:
                stack.pop()
            (stack[-1][1].addChild(it) if stack else self.tree.addTopLevelItem(it))
            stack.append((o.level, it))
        self.tree.expandToDepth(0)
        has = self.tree.topLevelItemCount() > 0
        self.tree.setVisible(has)
        self.empty.setVisible(not has)
