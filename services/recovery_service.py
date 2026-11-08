"""Crash recovery: unsaved edits are snapshotted to a private folder and offered after an interrupted session.
Snapshots of password-protected documents are never written (they would expose the content unencrypted)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from database.database import app_data_dir
from core import pdf_security as sec


@dataclass
class RecoveryItem:
    original: str
    snapshot: Path
    saved_at: float


def recovery_dir() -> Path:
    d = app_data_dir() / "recovery"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(original) -> str:
    return hashlib.sha1(str(Path(original).resolve()).encode()).hexdigest()[:16]


class RecoveryService:
    def snapshot(self, original, data: bytes, encrypted: bool = False) -> Path | None:
        if encrypted:
            return None
        k, d = _key(original), recovery_dir()
        pdf, meta = d / f"{k}.pdf", d / f"{k}.json"
        tmp = pdf.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, pdf)
        meta.write_text(json.dumps({"original": str(original), "saved_at": time.time()}), encoding="utf-8")
        return pdf

    def discard(self, original) -> None:
        k, d = _key(original), recovery_dir()
        for ext in (".pdf", ".json", ".tmp"):
            (d / f"{k}{ext}").unlink(missing_ok=True)

    def pending(self) -> list[RecoveryItem]:
        items = []
        for meta in recovery_dir().glob("*.json"):
            pdf = meta.with_suffix(".pdf")
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                if pdf.exists() and isinstance(m.get("original"), str):
                    items.append(RecoveryItem(m["original"], pdf, float(m.get("saved_at", 0))))
            except (ValueError, OSError):
                continue                                         # corrupt metadata is ignored, never fatal
        return sorted(items, key=lambda i: -i.saved_at)

    def restore(self, item: RecoveryItem, dst) -> Path:
        out = sec.unique_path(Path(dst))                         # never overwrites an existing file
        shutil.copyfile(item.snapshot, out)
        return out

    def discard_all(self) -> None:
        for f in recovery_dir().glob("*"):
            f.unlink(missing_ok=True)
