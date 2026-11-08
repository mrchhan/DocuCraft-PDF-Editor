"""Small reusable Qt building blocks: icon buttons, cards, file lists, and the progress runner."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from PySide6.QtCore import QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QToolButton, QVBoxLayout,
                               QWidget)

from app import theme
from core.errors import DocuCraftError, OperationCancelled


def icon(name: str, size: int = 20, active: bool = False) -> QIcon:
    return theme.ic(name, size, active=active)


def tool_button(icon_name: str, tip: str, *, checkable: bool = False, text: str = "", shortcut: str = "",
                size: int = 20, slot: Callable | None = None, object_name: str = "") -> QToolButton:
    b = QToolButton()
    b.setIcon(icon(icon_name, size))
    b.setIconSize(b.iconSize().__class__(size, size))
    b.setToolTip(f"{tip}  ({shortcut})" if shortcut else tip)
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setFocusPolicy(Qt.NoFocus)
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    if object_name:
        b.setObjectName(object_name)
    if slot:
        b.clicked.connect(lambda *_: slot())
    b.setProperty("icon_name", icon_name)
    return b


def retheme_buttons(root: QWidget) -> None:
    """Re-colour icons after a theme switch."""
    for b in root.findChildren(QToolButton):
        n = b.property("icon_name")
        if n:
            b.setIcon(icon(n, b.iconSize().width() or 20))


def separator(vertical: bool = True) -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.VLine if vertical else QFrame.HLine)
    f.setStyleSheet(f"color: {theme.palette()['border']};")
    return f


class Card(QFrame):
    clicked = Signal()

    def __init__(self, icon_name: str, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(190, 104)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        ic_lbl = QLabel()
        ic_lbl.setPixmap(icon(icon_name, 26, active=True).pixmap(26, 26))
        ic_lbl.setProperty("icon_name", icon_name)
        top.addWidget(ic_lbl)
        t = QLabel(title)
        t.setObjectName("H2")
        top.addWidget(t, 1)
        lay.addLayout(top)
        d = QLabel(text)
        d.setObjectName("Muted")
        d.setWordWrap(True)
        lay.addWidget(d, 1)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


def message(parent, title: str, text: str, kind: str = "info", detail: str = "") -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setDetailedText(detail)
    box.setIcon({"info": QMessageBox.Information, "warn": QMessageBox.Warning, "error": QMessageBox.Critical}[kind])
    box.exec()


def show_error(parent, exc: BaseException, title: str = "DocuCraft") -> None:
    """Friendly message for DocuCraftError, generic message (and details) for anything else."""
    if isinstance(exc, DocuCraftError):
        message(parent, title, exc.user_message, "error", getattr(exc, "detail", "") or "")
    else:
        message(parent, title, "Something unexpected went wrong. The details were written to the local log file.",
                "error", repr(exc))


def confirm(parent, title: str, text: str, yes: str = "Continue", no: str = "Cancel", danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    y = box.addButton(yes, QMessageBox.AcceptRole)
    box.addButton(no, QMessageBox.RejectRole)
    box.setDefaultButton(box.buttons()[-1])
    box.exec()
    return box.clickedButton() is y


def open_path(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def reveal(path) -> None:
    from services.file_manager import FileManager
    if not FileManager.reveal_in_folder(path):
        open_path(Path(path).parent)


class FileList(QListWidget):
    """A file list that accepts drag-and-drop, can be reordered, and exposes plain paths."""
    changed = Signal()

    def __init__(self, extensions: Iterable[str] = (".pdf",), parent=None):
        super().__init__(parent)
        self.extensions = tuple(e.lower() for e in extensions)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(False)
        self.model().rowsMoved.connect(lambda *_: self.changed.emit())

    def paths(self) -> list[str]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def add_paths(self, paths: Iterable) -> int:
        added = 0
        have = set(self.paths())
        for p in paths:
            p = str(p)
            if Path(p).suffix.lower() in self.extensions and p not in have and Path(p).is_file():
                it = QListWidgetItem(icon("pdf" if p.lower().endswith(".pdf") else "word", 18), Path(p).name)
                it.setToolTip(p)
                it.setData(Qt.UserRole, p)
                self.addItem(it)
                have.add(p)
                added += 1
        if added:
            self.changed.emit()
        return added

    def remove_selected(self) -> None:
        for it in self.selectedItems():
            self.takeItem(self.row(it))
        self.changed.emit()

    def move_selected(self, delta: int) -> None:
        rows = sorted((self.row(i) for i in self.selectedItems()), reverse=delta > 0)
        for r in rows:
            n = r + delta
            if 0 <= n < self.count():
                self.insertItem(n, self.takeItem(r))
                self.item(n).setSelected(True)
        self.changed.emit()

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            self.add_paths(u.toLocalFile() for u in e.mimeData().urls())
            e.acceptProposedAction()
        else:
            super().dropEvent(e)
            self.changed.emit()


def file_list_with_buttons(file_list: FileList, ctx, filter_text: str, key: str = "open",
                           parent: QWidget | None = None) -> QWidget:
    """File list + Add / Remove / Up / Down buttons."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(file_list, 1)
    col = QVBoxLayout()

    def add():
        files, _ = QFileDialog.getOpenFileNames(parent or w, "Add files", str(ctx.files.last_dir(key)), filter_text)
        if files:
            ctx.files.remember_dir(key, files[0])
            file_list.add_paths(files)
    for name, tip, slot in (("plus", "Add files", add), ("minus", "Remove selected", file_list.remove_selected),
                            ("up", "Move up", lambda: file_list.move_selected(-1)),
                            ("down", "Move down", lambda: file_list.move_selected(1))):
        col.addWidget(tool_button(name, tip, slot=slot))
    col.addStretch(1)
    lay.addLayout(col)
    return w


class ProgressDialog(QDialog):
    """Non-blocking-for-the-UI progress window with a Cancel button."""

    def __init__(self, parent, title: str, cancellable: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        lay = QVBoxLayout(self)
        self.label = QLabel("Starting…")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        lay.addWidget(self.label)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(cancellable)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)
        self.job = None
        self.cancel_btn.clicked.connect(self._cancel)

    def _cancel(self) -> None:
        self.cancel_btn.setEnabled(False)
        self.label.setText("Cancelling…")
        if self.job:
            self.job.cancel()

    def set_progress(self, pct: int, msg: str) -> None:
        self.bar.setValue(max(0, min(100, pct)))
        if msg:
            self.label.setText(msg)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(e)


def run_job(parent: QWidget, ctx, title: str, fn: Callable, on_success: Callable | None = None,
            on_error: Callable | None = None, cancellable: bool = True, show_dialog: bool = True):
    """Run `fn(progress, cancel)` on a worker thread with a progress dialog; callbacks run on the GUI thread."""
    dlg = ProgressDialog(parent, title, cancellable) if show_dialog else None

    def finished(result):
        if dlg:
            dlg.accept()
        if on_success:
            on_success(result)

    def failed(exc):
        if dlg:
            dlg.reject()
        if on_error:
            on_error(exc)
        else:
            show_error(parent, exc, title)

    def cancelled():
        if dlg:
            dlg.reject()

    job = ctx.jobs.submit(title, fn, on_progress=(dlg.set_progress if dlg else None), on_finished=finished,
                          on_failed=failed, on_cancelled=cancelled)
    if dlg:
        dlg.job = job
        dlg.show()
    return job


def open_file_dialog(parent, ctx, title: str, filter_text: str, key: str = "open", multiple: bool = False):
    start = str(ctx.files.last_dir(key))
    if multiple:
        files, _ = QFileDialog.getOpenFileNames(parent, title, start, filter_text)
        if files:
            ctx.files.remember_dir(key, files[0])
        return files
    f, _ = QFileDialog.getOpenFileName(parent, title, start, filter_text)
    if f:
        ctx.files.remember_dir(key, f)
    return f


def choose_dir(parent, ctx, title: str, key: str = "output") -> str:
    d = QFileDialog.getExistingDirectory(parent, title, str(ctx.files.last_dir(key)))
    if d:
        ctx.files.remember_dir(key, d)
    return d
