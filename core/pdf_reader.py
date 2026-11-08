"""Thread-safe read access to a PDF: rendering, text, search, outline, info.

All access goes through `lock` because MuPDF documents are not thread-safe and the UI
renders pages on worker threads.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from . import pdf_security as sec


@dataclass
class DocumentInfo:
    path: str
    file_size: int
    page_count: int
    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    creator: str = ""
    producer: str = ""
    created: str = ""
    modified: str = ""
    pdf_version: str = ""
    encrypted: bool = False
    repaired: bool = False
    page_sizes: list[str] = field(default_factory=list)
    has_text: bool = True
    permissions: dict[str, bool] = field(default_factory=dict)


@dataclass
class SearchHit:
    page: int
    rect: tuple[float, float, float, float]


@dataclass
class OutlineItem:
    level: int
    title: str
    page: int


class PdfReader:
    def __init__(self, path, password: str | None = None):
        self.path = Path(path).resolve()
        self.password = password
        self.lock = threading.RLock()
        self.doc: pymupdf.Document = sec.open_pdf(self.path, password)
        self.revision = 0                    # bumped on every content change; UI caches key on it
        self._words_cache: dict[tuple[int, int], list] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- lifecycle ----
    def close(self) -> None:
        with self.lock:
            if self.doc is not None and not self.doc.is_closed:
                self.doc.close()

    def replace_document(self, doc: pymupdf.Document) -> None:
        with self.lock:
            old = self.doc
            self.doc = doc
            self.touch()
            if old is not None and not old.is_closed:
                old.close()

    def reopen(self, path=None, any_extension: bool = False) -> None:
        with self.lock:
            if path:
                self.path = Path(path).resolve()
            self.replace_document(sec.open_pdf(self.path, self.password, any_extension=any_extension))

    def touch(self) -> None:
        self.revision += 1
        self._words_cache.clear()

    # ---- basics ----
    @property
    def page_count(self) -> int:
        with self.lock:
            return self.doc.page_count

    @property
    def file_size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def page_size(self, index: int) -> tuple[float, float]:
        with self.lock:
            r = self.doc[index].rect
            return r.width, r.height

    def page_rotation(self, index: int) -> int:
        with self.lock:
            return self.doc[index].rotation

    # ---- rendering ----
    def render(self, index: int, zoom: float = 1.0, rotation: int = 0, clip=None, annots: bool = True) -> pymupdf.Pixmap:
        with self.lock:
            page = self.doc[index]
            z = sec.safe_zoom(page.rect, zoom)
            return page.get_pixmap(matrix=pymupdf.Matrix(z, z).prerotate(rotation), clip=clip, alpha=False, annots=annots)

    def render_png(self, index: int, zoom: float = 1.0) -> bytes:
        return self.render(index, zoom).tobytes("png")

    # ---- text ----
    def words(self, index: int) -> list[tuple]:
        key = (self.revision, index)
        with self.lock:
            cached = self._words_cache.get(key)
            if cached is None:
                cached = self.doc[index].get_text("words", sort=False)
                self._words_cache[key] = cached
            return cached

    def page_text(self, index: int) -> str:
        with self.lock:
            return self.doc[index].get_text("text", sort=True)

    def text_in_rect(self, index: int, rect) -> str:
        with self.lock:
            return self.doc[index].get_text("text", clip=pymupdf.Rect(rect), sort=True).strip()

    def full_text(self) -> str:
        with self.lock:
            return "\n\n".join(p.get_text("text", sort=True) for p in self.doc)

    def has_selectable_text(self, index: int) -> bool:
        with self.lock:
            return bool(self.doc[index].get_text("text").strip())

    def is_scanned_page(self, index: int) -> bool:
        """Almost no text, but images cover most of the page."""
        with self.lock:
            page = self.doc[index]
            if len(page.get_text("text").strip()) >= 20:
                return False
            area = (page.rect.width * page.rect.height) or 1.0
            covered = sum(pymupdf.Rect(i["bbox"]).intersect(page.rect).get_area() for i in page.get_image_info())
            return covered / area > 0.5

    def search(self, term: str, max_hits_per_page: int = 500) -> dict[int, list[pymupdf.Rect]]:
        results: dict[int, list[pymupdf.Rect]] = {}
        term = term.strip()
        if not term:
            return results
        with self.lock:
            for i, page in enumerate(self.doc):
                found = page.search_for(term)[:max_hits_per_page]
                if found:
                    results[i] = [pymupdf.Rect(r) for r in found]
        return results

    def search_hits(self, term: str, max_hits: int = 5000) -> list[SearchHit]:
        out: list[SearchHit] = []
        for page, rects in self.search(term).items():
            for r in rects:
                out.append(SearchHit(page, (r.x0, r.y0, r.x1, r.y1)))
                if len(out) >= max_hits:
                    return out
        return out

    # ---- outline & info ----
    def toc(self) -> list[tuple[int, str, int]]:
        with self.lock:
            return [(lvl, title, max(0, pg - 1)) for lvl, title, pg in self.doc.get_toc(simple=True)]

    def outline(self) -> list[OutlineItem]:
        return [OutlineItem(l, t, p) for l, t, p in self.toc()]

    def info(self) -> DocumentInfo:
        with self.lock:
            md = self.doc.metadata or {}
            sizes = sorted({f"{round(p.rect.width / 72 * 25.4)} × {round(p.rect.height / 72 * 25.4)} mm" for p in self.doc})
            perm = self.doc.permissions
            return DocumentInfo(
                path=str(self.path), file_size=self.file_size, page_count=self.doc.page_count,
                title=md.get("title", ""), author=md.get("author", ""), subject=md.get("subject", ""),
                keywords=md.get("keywords", ""), creator=md.get("creator", ""), producer=md.get("producer", ""),
                created=md.get("creationDate", ""), modified=md.get("modDate", ""), pdf_version=md.get("format", ""),
                encrypted=bool(self.doc.is_encrypted), repaired=bool(self.doc.is_repaired), page_sizes=sizes[:8],
                has_text=any(self.has_selectable_text(i) for i in range(min(5, self.doc.page_count))),
                permissions={"print": bool(perm & pymupdf.PDF_PERM_PRINT), "copy": bool(perm & pymupdf.PDF_PERM_COPY),
                             "modify": bool(perm & pymupdf.PDF_PERM_MODIFY),
                             "annotate": bool(perm & pymupdf.PDF_PERM_ANNOTATE)})


PDFReader = PdfReader


def format_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"
