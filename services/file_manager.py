"""Default output folder and remembered directories."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from database.database import Database


class FileManager:
    def __init__(self, db: Database):
        self.db = db

    def default_output_dir(self) -> Path | None:
        v = self.db.get_setting("output_dir", "")
        return Path(v) if v else None

    def set_default_output_dir(self, path) -> None:
        self.db.set_setting("output_dir", str(path) if path else "")

    def last_dir(self, key: str = "open") -> Path:
        v = self.db.get_setting(f"last_dir_{key}", "")
        if v and Path(v).is_dir():
            return Path(v)
        docs = Path.home() / "Documents"
        return docs if docs.is_dir() else Path.home()

    def remember_dir(self, key: str, file_or_dir) -> None:
        p = Path(file_or_dir)
        self.db.set_setting(f"last_dir_{key}", str(p if p.is_dir() else p.parent))

    def output_dir_for(self, source) -> Path:
        """Configured default folder (created on demand) or, by default, next to the source."""
        d = self.default_output_dir()
        if d:
            d.mkdir(parents=True, exist_ok=True)
            return d
        return Path(source).resolve().parent

    @staticmethod
    def reveal_in_folder(path) -> bool:
        p = Path(path)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", f"/select,{p}"] if p.is_file() else ["explorer", str(p)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])
            return True
        except OSError:
            return False
