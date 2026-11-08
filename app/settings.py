"""Application constants and the user-settings facade over the local SQLite database."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from database.database import Database

APP_VERSION = "0.1.3"
APP_NAME = "DocuCraft"
TAGLINE = "Your Documents. Your Control."
DEVELOPER = "Hassan Malik (Shadow Creative Studio)"
REPO_URL = "https://github.com/mrchhan/DocuCraft-PDF-Editor"      # replace before publishing
LICENSE_NAME = "AGPL-3.0-or-later"

DEFAULTS: dict = {
    "language": "English",
    "theme": "system",                 # light | dark | system
    "ui_scale": 100,                   # percent
    "default_zoom": "fit_width",       # fit_width | fit_page | 100 | 125 ...
    "page_layout": "continuous",       # single | continuous | two
    "render_quality": "balanced",      # fast | balanced | high
    "render_cache_pages": 24,
    "restore_session": False,
    "history_enabled": True,
    "recent_limit": 50,
    "output_dir": "",
    "docx_output_dir": "",
    "conv_mode": "layout",             # layout | editable
    "conv_images": True,
    "conv_tables": True,
    "ocr_mode": "auto",                # off | auto | force
    "ocr_language": "eng",
    "image_dpi": 150,
    "jpg_quality": 90,
    "max_jobs": 2,
    "clean_temp_on_exit": True,
    "update_check_consent": False,
    "autosave_recovery_seconds": 30,
}

RENDER_DPI = {"fast": 72.0, "balanced": 96.0, "high": 144.0}
LANGUAGES = ["English"]                # UI strings are English for v0.1; structure is ready for more


class Settings(QObject):
    changed = Signal(str)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    def get(self, key: str):
        return self.db.get_setting(key, DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        if self.get(key) != value:
            self.db.set_setting(key, value)
            self.changed.emit(key)
        elif key not in self.db.all_settings():
            self.db.set_setting(key, value)

    def reset(self) -> None:
        for k in list(self.db.all_settings()):
            if k in DEFAULTS:
                self.db.execute("DELETE FROM settings WHERE key=?", (k,))
                self.changed.emit(k)

    @property
    def render_dpi(self) -> float:
        return RENDER_DPI.get(self.get("render_quality"), 96.0)
