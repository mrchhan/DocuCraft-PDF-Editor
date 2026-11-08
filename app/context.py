"""Shared application services, created once and handed to the window and pages."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.settings import Settings
from app.workers import JobManager
from database.database import Database
from services.document_history import DocumentHistory
from services.file_manager import FileManager
from services.recovery_service import RecoveryService


class AppContext(QObject):
    themeChanged = Signal(str)

    def __init__(self, db: Database | None = None):
        super().__init__()
        self.db = db or Database()
        self.settings = Settings(self.db)
        self.history = DocumentHistory(self.db)
        self.files = FileManager(self.db)
        self.recovery = RecoveryService()
        self.jobs = JobManager(int(self.settings.get("max_jobs")))
        self.settings.changed.connect(self._on_setting)

    def _on_setting(self, key: str) -> None:
        if key == "max_jobs":
            self.jobs.set_max_jobs(int(self.settings.get("max_jobs")))
        elif key in ("theme", "ui_scale"):
            self.themeChanged.emit(str(self.settings.get("theme")))

    def output_dir_for(self, source, docx: bool = False):
        if docx and self.settings.get("docx_output_dir"):
            from pathlib import Path
            d = Path(self.settings.get("docx_output_dir"))
            d.mkdir(parents=True, exist_ok=True)
            return d
        return self.files.output_dir_for(source)
