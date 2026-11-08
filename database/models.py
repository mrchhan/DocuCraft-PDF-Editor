from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RecentDocument:
    path: str
    opened_at: float
    page: int = 0
    zoom: float = 1.0
    favorite: bool = False

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()


@dataclass(frozen=True)
class ConversionRecord:
    id: int
    source: str
    output: str
    kind: str
    status: str
    pages: int
    started_at: float
    detail: str = ""

    @property
    def name(self) -> str:
        return Path(self.source).name
