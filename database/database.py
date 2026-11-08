"""Local SQLite store. Holds preferences, recent/favourite paths and conversion history only -
never document contents. Location can be redirected with DOCUCRAFT_HOME."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

APP_NAME = "DocuCraft"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recent_documents (
    path TEXT PRIMARY KEY, opened_at REAL NOT NULL, page INTEGER NOT NULL DEFAULT 0, zoom REAL NOT NULL DEFAULT 1.0);
CREATE TABLE IF NOT EXISTS favorites (path TEXT PRIMARY KEY, added_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS conversions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, output TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
    status TEXT NOT NULL, pages INTEGER NOT NULL DEFAULT 0, started_at REAL NOT NULL, detail TEXT NOT NULL DEFAULT '');
"""


def app_data_dir() -> Path:
    env = os.environ.get("DOCUCRAFT_HOME")
    if env:
        base = Path(env)
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else app_data_dir() / "docucraft.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def get_setting(self, key: str, default=None):
        rows = self.query("SELECT value FROM settings WHERE key=?", (key,))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["value"])
        except ValueError:
            return default

    def set_setting(self, key: str, value) -> None:
        self.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, json.dumps(value)))

    def all_settings(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.query("SELECT key,value FROM settings")}

    def clear_history(self, *, keep_favorites: bool = True) -> None:
        self.execute("DELETE FROM recent_documents")
        self.execute("DELETE FROM conversions")
        if not keep_favorites:
            self.execute("DELETE FROM favorites")

    def wipe_everything(self) -> None:
        for t in ("settings", "recent_documents", "favorites", "conversions"):
            self.execute(f"DELETE FROM {t}")

    @staticmethod
    def now() -> float:
        return time.time()
