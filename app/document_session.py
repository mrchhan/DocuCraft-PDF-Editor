"""One open document: reader + editor + dirty/undo state + crash-recovery snapshots (no widgets)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from core.pdf_editor import PdfEditor
from core.pdf_reader import PdfReader
from database.database import app_data_dir
from services.recovery_service import RecoveryService


class DocumentSession(QObject):
    changed = Signal()                 # content changed (edit/undo/redo/save) -> views must re-render
    dirtyChanged = Signal(bool)
    saved = Signal(str)

    def __init__(self, path, password: str | None = None, recovery: RecoveryService | None = None,
                 autosave_seconds: int = 30):
        super().__init__()
        self.reader = PdfReader(path, password)
        self.editor = PdfEditor(self.reader, backup_dir=app_data_dir() / "backups")
        self.recovery = recovery
        self._last_dirty = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(1, autosave_seconds) * 1000)
        self._timer.timeout.connect(self._write_snapshot)

    # ---- properties ----
    @property
    def path(self) -> Path:
        return self.reader.path

    @property
    def name(self) -> str:
        return self.reader.path.name

    @property
    def doc(self):
        return self.reader.doc

    @property
    def page_count(self) -> int:
        """0 once the document has been closed, so late UI events cannot crash."""
        d = self.reader.doc
        return 0 if d is None or d.is_closed else self.reader.page_count

    @property
    def dirty(self) -> bool:
        return self.editor.dirty

    @property
    def encrypted(self) -> bool:
        return self.reader.password is not None

    @property
    def file_size(self) -> int:
        return self.reader.file_size

    @property
    def page_sizes(self) -> list[tuple[float, float]]:
        return [self.reader.page_size(i) for i in range(self.reader.page_count)]

    # ---- editing ----
    def edit(self, method: str, *args, **kwargs):
        result = getattr(self.editor, method)(*args, **kwargs)
        self._after_change()
        return result

    def undo(self) -> bool:
        ok = self.editor.undo() is not None
        if ok:
            self._after_change()
        return ok

    def redo(self) -> bool:
        ok = self.editor.redo() is not None
        if ok:
            self._after_change()
        return ok

    def _after_change(self) -> None:
        self.changed.emit()
        self._emit_dirty()
        if self.editor.dirty and self.recovery and not self.encrypted:
            self._timer.start()

    def _emit_dirty(self) -> None:
        if self.editor.dirty != self._last_dirty:
            self._last_dirty = self.editor.dirty
            self.dirtyChanged.emit(self._last_dirty)

    def _write_snapshot(self) -> None:
        if self.recovery and self.editor.dirty and not self.encrypted:
            with self.reader.lock:
                data = self.reader.doc.tobytes(garbage=0, deflate=False)
            self.recovery.snapshot(self.path, data, self.encrypted)

    # ---- saving ----
    def save(self, *, confirm_overwrite: bool = False) -> Path:
        out = self.editor.save(confirm_overwrite=confirm_overwrite)
        self._mark_clean(out)
        return out

    def save_as(self, dst, *, overwrite: bool = False) -> Path:
        old = self.path
        out = self.editor.save_as(dst, confirm_overwrite=overwrite)
        if self.recovery:
            self.recovery.discard(old)
        self._mark_clean(out)
        return out

    def _mark_clean(self, out) -> None:
        self._timer.stop()
        if self.recovery:
            self.recovery.discard(self.path)
        self.changed.emit()
        self._emit_dirty()
        self.saved.emit(str(out))

    # ---- misc ----
    def search_sync(self, needle: str, case_sensitive: bool = False):
        hits = self.reader.search_hits(needle)
        if case_sensitive:
            hits = [h for h in hits if needle in self.reader.text_in_rect(h.page, h.rect)]
        return hits

    def close(self, discard_recovery: bool = True) -> None:
        self._timer.stop()
        if discard_recovery and self.recovery:
            self.recovery.discard(self.path)
        self.reader.close()
