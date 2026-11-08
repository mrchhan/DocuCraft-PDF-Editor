"""Recent documents, favourites and conversion history (paths + metadata only)."""
from __future__ import annotations

from pathlib import Path

from database.database import Database
from database.models import ConversionRecord, RecentDocument

MAX_RECENT = 50


def _key(path) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


class DocumentHistory:
    def __init__(self, db: Database):
        self.db = db

    @property
    def enabled(self) -> bool:
        return bool(self.db.get_setting("history_enabled", True))

    @property
    def limit(self) -> int:
        return int(self.db.get_setting("recent_limit", MAX_RECENT))

    def add_recent(self, path, page: int = 0, zoom: float = 1.0) -> None:
        if not self.enabled:
            return
        self.db.execute("INSERT INTO recent_documents(path,opened_at,page,zoom) VALUES(?,?,?,?) "
                        "ON CONFLICT(path) DO UPDATE SET opened_at=excluded.opened_at,page=excluded.page,zoom=excluded.zoom",
                        (_key(path), self.db.now(), page, zoom))
        self.db.execute("DELETE FROM recent_documents WHERE path NOT IN "
                        "(SELECT path FROM recent_documents ORDER BY opened_at DESC LIMIT ?)", (self.limit,))

    def update_position(self, path, page: int, zoom: float) -> None:
        if self.enabled:
            self.db.execute("UPDATE recent_documents SET page=?, zoom=? WHERE path=?", (page, zoom, _key(path)))

    def _rows(self, rows) -> list[RecentDocument]:
        favs = {r["path"] for r in self.db.query("SELECT path FROM favorites")}
        return [RecentDocument(r["path"], r["opened_at"], r["page"], r["zoom"], r["path"] in favs) for r in rows]

    def recent(self, search: str = "", limit: int | None = None) -> list[RecentDocument]:
        rows = self.db.query("SELECT * FROM recent_documents WHERE path LIKE ? ESCAPE '\\' ORDER BY opened_at DESC LIMIT ?",
                             (f"%{_like(search)}%", limit or self.limit))
        return self._rows(rows)

    def last_position(self, path):
        rows = self.db.query("SELECT page,zoom FROM recent_documents WHERE path=?", (_key(path),))
        return (rows[0]["page"], rows[0]["zoom"]) if rows else None

    def remove_recent(self, path) -> None:
        self.db.execute("DELETE FROM recent_documents WHERE path=?", (_key(path),))

    def add_favorite(self, path) -> None:
        self.db.execute("INSERT OR IGNORE INTO favorites(path,added_at) VALUES(?,?)", (_key(path), self.db.now()))

    def remove_favorite(self, path) -> None:
        self.db.execute("DELETE FROM favorites WHERE path=?", (_key(path),))

    def is_favorite(self, path) -> bool:
        return bool(self.db.query("SELECT 1 FROM favorites WHERE path=?", (_key(path),)))

    def favorites(self, search: str = "") -> list[RecentDocument]:
        rows = self.db.query("SELECT path, added_at AS opened_at, 0 AS page, 1.0 AS zoom FROM favorites "
                             "WHERE path LIKE ? ESCAPE '\\' ORDER BY added_at DESC", (f"%{_like(search)}%",))
        return self._rows(rows)

    def add_conversion(self, source, output, kind: str, status: str, pages: int = 0, detail: str = "") -> int:
        if not self.enabled:
            return 0
        cur = self.db.execute("INSERT INTO conversions(source,output,kind,status,pages,started_at,detail) VALUES(?,?,?,?,?,?,?)",
                              (str(source), str(output), kind, status, pages, self.db.now(), detail))
        return cur.lastrowid

    def conversions(self, search: str = "", limit: int = 200) -> list[ConversionRecord]:
        s = f"%{_like(search)}%"
        rows = self.db.query("SELECT * FROM conversions WHERE source LIKE ? ESCAPE '\\' OR output LIKE ? ESCAPE '\\' "
                             "OR kind LIKE ? ESCAPE '\\' ORDER BY started_at DESC, id DESC LIMIT ?", (s, s, s, limit))
        return [ConversionRecord(r["id"], r["source"], r["output"], r["kind"], r["status"], r["pages"], r["started_at"],
                                 r["detail"]) for r in rows]

    def clear(self, *, keep_favorites: bool = True) -> None:
        self.db.clear_history(keep_favorites=keep_favorites)


def _like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
