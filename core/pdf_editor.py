"""PDF editing with undo/redo, safe saving, text replacement and true redaction.

HONESTY RULE: PDF has no reflowable text model, so "replace text" is implemented as true
redaction of the old text plus a new text overlay. ReplaceResult says so explicitly; it is
NOT native PDF text editing.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import pymupdf

from . import pdf_annotations as ann
from . import pdf_security as sec
from . import watermark
from .errors import DocuCraftError, InvalidFileError, OverwriteNotConfirmed
from . import fonts as _fonts
from .fonts import classify_font, resolve_font
from .pdf_reader import PdfReader

MAX_UNDO_STATES = 30
MAX_UNDO_BYTES = 400 * 1024 * 1024
REPLACEMENT_NOTICE = ("This is a redaction + overlay replacement, not native PDF text editing: the original words were "
                      "permanently removed and the new text was placed in the same spot, in the same font where possible.")


@dataclass
class TextStyle:
    text: str = ""
    fontsize: float = 11.0
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    font_name: str = ""
    family: str = "sans"
    bold: bool = False
    italic: bool = False
    flags: int = 0


@dataclass
class ReplaceResult:
    ok: bool
    font_used: str
    original_font: str
    substituted: bool
    fit_fontsize: float
    message: str = REPLACEMENT_NOTICE


@dataclass
class RedactionReport:
    regions: int = 0
    pages: list[int] = field(default_factory=list)
    terms_found: int = 0
    sanitized: bool = False


class PdfEditor:
    """Mutating operations on a PdfReader's document. UI code never touches pymupdf directly."""

    def __init__(self, reader: PdfReader, backup_dir=None):
        self.reader = reader
        self.backup_dir = Path(backup_dir) if backup_dir else None
        self._undo: list[tuple[str, bytes]] = []
        self._redo: list[tuple[str, bytes]] = []
        self._undo_bytes = 0
        self.dirty = False
        self._clean_len: int | None = 0      # undo-stack depth that equals the saved file (None = unreachable)
        self.undo_enabled = reader.file_size <= 150 * 1024 * 1024

    # ---- encryption must be asked for explicitly: PyMuPDF silently drops it on save ----
    def _enc_keep(self) -> dict:
        return {"encryption": pymupdf.PDF_ENCRYPT_KEEP} if self.reader.password else {}

    def _enc_new(self) -> dict:
        pw = self.reader.password
        return {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": pw, "owner_pw": pw} if pw else {}

    # ---- undo / redo ----
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str:
        return self._undo[-1][0] if self._undo else ""

    def _snapshot(self) -> bytes:
        return self.reader.doc.tobytes(garbage=0, deflate=False, **self._enc_keep())

    def _restore(self, data: bytes) -> None:
        self.reader.replace_document(sec.open_pdf_bytes(data, self.reader.password))

    def _push_undo(self, label: str) -> bytes | None:
        if not self.undo_enabled:
            return None
        snap = self._snapshot()
        self._undo.append((label, snap))
        self._undo_bytes += len(snap)
        while self._undo and (len(self._undo) > MAX_UNDO_STATES or self._undo_bytes > MAX_UNDO_BYTES):
            _, old = self._undo.pop(0)
            if self._clean_len is not None:
                self._clean_len = self._clean_len - 1 if self._clean_len > 0 else None
            self._undo_bytes -= len(old)
        return snap

    @contextmanager
    def _edit(self, label: str):
        with self.reader.lock:
            snap = self._push_undo(label)
            try:
                yield self.reader.doc
            except BaseException:
                if snap is not None:                       # roll back partial changes
                    self._restore(snap)
                    self._undo.pop()
                    self._undo_bytes -= len(snap)
                raise
            self._redo.clear()
            if self._clean_len is not None and len(self._undo) - 1 < self._clean_len:
                self._clean_len = None
            self.reader.touch()
            self.dirty = True

    def undo(self) -> str | None:
        with self.reader.lock:
            if not self._undo:
                return None
            label, snap = self._undo.pop()
            self._undo_bytes -= len(snap)
            self._redo.append((label, self._snapshot()))
            self._restore(snap)
            self.dirty = self._clean_len != len(self._undo)
            return label

    def redo(self) -> str | None:
        with self.reader.lock:
            if not self._redo:
                return None
            label, snap = self._redo.pop()
            cur = self._snapshot()
            self._undo.append((label, cur))
            self._undo_bytes += len(cur)
            self._restore(snap)
            self.dirty = self._clean_len != len(self._undo)
            return label

    # ---- annotations ----
    def add_markup(self, page, kind, rects, color=ann.YELLOW, opacity=0.5, comment=""):
        with self._edit(f"Add {kind}") as doc:
            return ann.add_text_markup(doc[page], kind, rects, color, opacity, comment).xref

    def add_note(self, page, point, text, author=""):
        with self._edit("Add note") as doc:
            return ann.add_sticky_note(doc[page], point, text, author=author).xref

    def add_text_box(self, page, rect, text, fontsize=12, color=ann.BLACK, opacity=1.0):
        with self._edit("Add text box") as doc:
            return ann.add_text_box(doc[page], rect, text, fontsize, color, opacity=opacity).xref

    def add_freehand(self, page, strokes, color=ann.RED, width=2.0, opacity=1.0):
        with self._edit("Draw") as doc:
            return ann.add_freehand(doc[page], strokes, color, width, opacity).xref

    def add_line(self, page, p1, p2, color=ann.RED, width=2.0, arrow=False, opacity=1.0):
        with self._edit("Add arrow" if arrow else "Add line") as doc:
            return ann.add_line(doc[page], p1, p2, color, width, arrow, opacity).xref

    def add_shape(self, page, kind, rect, color=ann.RED, width=2.0, fill=None, opacity=1.0):
        with self._edit(f"Add {kind}") as doc:
            return ann.add_shape(doc[page], kind, rect, color, width, fill, opacity).xref

    def add_image(self, page, rect, image_path, name="Image"):
        p = sec.validate_input_file(image_path, extensions=(".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"),
                                    max_bytes=100 * 1024 * 1024)
        with self._edit(f"Insert {name.lower()}") as doc:
            return ann.add_image_stamp(doc[page], rect, str(p), name).xref

    def move_annotation(self, page, xref, rect):
        with self._edit("Move / resize object") as doc:
            ann.move_annotation(doc[page], xref, rect)

    def delete_annotation(self, page, xref) -> bool:
        with self._edit("Delete annotation") as doc:
            return ann.delete_annotation(doc[page], xref)

    def restyle_annotation(self, page, xref, **kw) -> bool:
        with self._edit("Change annotation") as doc:
            return ann.restyle_annotation(doc[page], xref, **kw)

    def add_text_to_page(self, page, rect, text, fontsize=12, color=ann.BLACK) -> float:
        """Draw plain text into the page content (not an annotation). Shrinks to fit; returns the size used."""
        with self._edit("Add text") as doc:
            pg = doc[page]
            rf = resolve_font(doc, pg, "Helvetica", 0, text)
            rf.register(pg)
            return self._draw_text(pg, pymupdf.Rect(rect), text, fontsize, color, rf)

    # ---- pages ----
    def insert_blank_page(self, after: int = -1, size=None) -> int:
        with self._edit("Insert blank page") as doc:
            ref = doc[max(0, min(after, doc.page_count - 1))]
            w, h = size or (ref.rect.width, ref.rect.height)
            doc.new_page(pno=after + 1, width=w, height=h)
            return after + 1

    def delete_pages(self, pages: Iterable[int]) -> None:
        pages = sorted(set(pages))
        with self._edit(f"Delete {len(pages)} page(s)") as doc:
            if len(pages) >= doc.page_count:
                raise DocuCraftError("A PDF must keep at least one page.")
            doc.delete_pages(pages)

    def duplicate_page(self, page: int) -> int:
        with self._edit("Duplicate page") as doc:
            doc.fullcopy_page(page, page + 1)
            return page + 1

    def rotate_pages(self, pages: Iterable[int], degrees: int = 90) -> None:
        if degrees % 90:
            raise InvalidFileError("Rotation must be a multiple of 90 degrees.")
        with self._edit("Rotate pages") as doc:
            for p in set(pages):
                doc[p].set_rotation((doc[p].rotation + degrees) % 360)

    def reorder(self, new_order: Sequence[int]) -> None:
        with self._edit("Reorder pages") as doc:
            if sorted(new_order) != list(range(doc.page_count)):
                raise DocuCraftError("The new page order must include every page exactly once.")
            doc.select(list(new_order))

    def move_page(self, src: int, dst: int) -> None:
        with self._edit("Move page") as doc:
            order = list(range(doc.page_count))
            order.insert(dst, order.pop(src))
            doc.select(order)

    def extract_pages(self, pages: Sequence[int], dst, overwrite: bool = False) -> Path:
        dst = Path(dst)
        if dst.exists() and not overwrite:
            raise OverwriteNotConfirmed(f"'{dst.name}' already exists.")
        with self.reader.lock:
            new = pymupdf.open()
            try:
                for p in pages:
                    new.insert_pdf(self.reader.doc, from_page=p, to_page=p)
                watermark.stamp_pdf(new)
                new.save(dst, garbage=3, deflate=True)
            finally:
                new.close()
        return dst

    def replace_pages(self, start: int, count: int, source_pdf, source_pages=None, source_password=None) -> None:
        """Replace `count` pages starting at `start` with pages from another PDF."""
        src = sec.open_pdf(source_pdf, source_password)
        try:
            idx = list(source_pages) if source_pages is not None else list(range(src.page_count))
            with self._edit("Replace pages") as doc:
                if start < 0 or start + count > doc.page_count:
                    raise DocuCraftError("The page range to replace is outside the document.")
                doc.delete_pages(list(range(start, start + count)))
                for off, p in enumerate(idx):
                    doc.insert_pdf(src, from_page=p, to_page=p, start_at=start + off)
        finally:
            src.close()

    # ---- existing text ----
    @staticmethod
    def _words_in(pg, r, min_overlap: float = 0.4):
        """Words (x0, y0, x1, y1, text, block, line, wordno) that the drag rectangle covers (centre inside, or mostly covered)."""
        out = []
        for w in pg.get_text("words"):
            wr = pymupdf.Rect(w[:4])
            if wr.is_empty:
                continue
            inter = wr & r
            if inter.is_empty:
                continue
            v_cover = inter.height / wr.height              # a sloppy box that clips the line below must not select it
            h_cover = inter.width / wr.width
            if v_cover >= 0.75 and (h_cover >= min_overlap or r.contains(pymupdf.Point((wr.x0 + wr.x1) / 2, (wr.y0 + wr.y1) / 2))):
                out.append(w)
        return sorted(out, key=lambda w: (w[5], w[6], w[7]))

    @staticmethod
    def _spans_near(pg, rect):
        data = pg.get_text("dict", clip=pymupdf.Rect(pg.rect.x0, rect.y0 - 2, pg.rect.x1, rect.y1 + 2))
        spans = []
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                for sp in line["spans"]:
                    spans.append((block["bbox"], sp))
        return spans

    @staticmethod
    def _span_for(spans, word):
        c = pymupdf.Point((word[0] + word[2]) / 2, (word[1] + word[3]) / 2)
        for _bb, sp in spans:
            if pymupdf.Rect(sp["bbox"]).contains(c):
                return sp
        return spans[0][1] if spans else None

    def analyze_text(self, page: int, rect) -> TextStyle:
        """Find the words inside `rect` and the font characteristics of the first one."""
        r = pymupdf.Rect(rect)
        with self.reader.lock:
            pg = self.reader.doc[page]
            words = self._words_in(pg, r)
            st = TextStyle()
            if not words:
                return st
            lines: dict[tuple, list[str]] = {}
            for w in words:
                lines.setdefault((w[5], w[6]), []).append(w[4])
            st.text = "\n".join(" ".join(v) for v in lines.values())
            sp = self._span_for(self._spans_near(pg, pymupdf.Rect(words[0][:4])), words[0])
        if sp:
            st.fontsize, st.font_name = round(sp["size"], 2), sp["font"]
            st.family, st.bold, st.italic = classify_font(sp["font"], sp["flags"])
            c = sp["color"]
            st.color = ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)
            st.flags = sp["flags"]
        return st

    def replace_text(self, page: int, rect, new_text: str, style: TextStyle | None = None) -> ReplaceResult:
        r = pymupdf.Rect(rect)
        with self._edit("Replace text") as doc:
            return self._replace_on_page(doc[page], r, new_text, style)

    def preview_replace(self, page: int, rect, new_text: str, style: TextStyle | None = None,
                        zoom: float = 2.0, margin: float = 24.0) -> bytes:
        """PNG of the area after replacement, computed on a throw-away copy. The document is untouched."""
        r = pymupdf.Rect(rect)
        with self.reader.lock:
            tmp = pymupdf.open("pdf", self.reader.doc.tobytes(garbage=0, deflate=False))   # plain, memory-only copy
        try:
            pg = tmp[page]
            self._replace_on_page(pg, r, new_text, style)
            clip = (r + (-margin, -margin * 1.5, margin * 6, margin * 1.5)) & pg.rect
            return pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip).tobytes("png")
        finally:
            tmp.close()

    def _replace_on_page(self, pg, r, new_text, st: TextStyle | None) -> ReplaceResult:
        """Replace the words under `r`, keeping the original font, size, colour and baseline.

        Only the replaced words (and the rest of the same line, which is moved along) are removed - never the lines above
        or below. If the text is not selectable (scans) the area is simply covered and the text is drawn on top.
        """
        doc = pg.parent
        _fonts.clear_glyph_cache()                                       # page text changes between edits
        self._remove_overlapping_annots(pg, r)
        words = self._words_in(pg, r)
        if not words:                                                   # nothing selectable: cover + draw
            pg.add_redact_annot(r, fill=False)
            pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
            kind, bold, italic = classify_font((st.font_name if st else ""), 0)
            size = st.fontsize if st else 11.0
            rf = resolve_font(doc, pg, st.font_name if st else "", 0, new_text)
            rf.register(pg)
            used = self._draw_text(pg, r, new_text, size, st.color if st else (0, 0, 0), rf)
            return ReplaceResult(True, rf.label, "unknown", not rf.faithful, used)

        spans = self._spans_near(pg, pymupdf.Rect(words[0][:4]) | pymupdf.Rect(words[-1][:4]))
        sp0 = self._span_for(spans, words[0])
        size = float(sp0["size"])
        if st and st.fontsize and abs(st.fontsize - size) > 0.6:      # the user changed the size in the dialog
            size = float(st.fontsize)
        color = tuple(((sp0["color"] >> s) & 255) / 255 for s in (16, 8, 0))
        base = sp0["origin"][1]
        font0 = resolve_font(doc, pg, sp0["font"], sp0["flags"], new_text)
        single_line = len({(w[5], w[6]) for w in words}) == 1

        if not single_line:                                             # multi-line selection: redraw as a text block
            union = pymupdf.Rect(words[0][:4])
            for w in words:
                union |= pymupdf.Rect(w[:4])
                pg.add_redact_annot(self._band(w, size, base if w is words[0] else w[3] - 0.22 * size), fill=False)
            pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
            font0.register(pg)
            used = self._draw_text(pg, union, new_text, size, color, font0)
            return ReplaceResult(True, font0.label, sp0["font"], not font0.faithful, used)

        first, last = words[0], words[-1]
        old_x0, old_x1 = first[0], last[2]
        block_x1 = max((bb[2] for bb, _sp in spans), default=old_x1)
        trailing = [w for w in pg.get_text("words") if (w[5], w[6]) == (first[5], first[6]) and w[7] > last[7]]
        trailing.sort(key=lambda w: w[0])
        trail_x1 = trailing[-1][2] if trailing else old_x1

        # can the rest of the line be re-drawn faithfully (same font)?  If not, leave it alone and fit the new word instead.
        tr_fonts = {}
        reflow = bool(trailing)
        for w in trailing:
            sp = self._span_for(spans, w)
            rf = resolve_font(doc, pg, sp["font"], sp["flags"], w[4]) if sp else None
            if rf is None or not rf.faithful:
                reflow = False
                break
            tr_fonts[id(w)] = (sp, rf)

        width = font0.measure(new_text, size)
        old_w = old_x1 - old_x0
        # how far the line may grow to the right: up to ~4 em beyond the paragraph edge, but never into other text on this
        # line, nor past the page margin
        y_band = (base - 0.8 * size, base + 0.25 * size)
        obstacles = [w[0] for w in pg.get_text("words") if w[0] >= trail_x1 + 1 and w[1] < y_band[1] and w[3] > y_band[0]
                     and (w[5], w[6]) != (first[5], first[6])]
        hard = min(block_x1 + 4.0 * size, pg.rect.x1 - 24, (min(obstacles) - 8) if obstacles else 1e9)
        slack = max(0.0, max(block_x1 + 0.4 * size, hard) - trail_x1)
        gap_after = (trailing[0][0] - old_x1) if trailing else 0.0
        if reflow:
            room = old_w + slack
        else:
            room = old_w + max(0.0, gap_after - 0.25 * size)
        fit = size
        if width > room and width > 0:
            fit = max(size * 0.7, size * room / width)
            width = font0.measure(new_text, fit)
        shift = (width - old_w) if reflow else 0.0
        to_clear = [first[:4], last[:4]] + ([t[:4] for t in trailing] if reflow else [])
        x0c = min(c[0] for c in to_clear)
        x1c = max(c[2] for c in to_clear)
        pg.add_redact_annot(pymupdf.Rect(x0c + 0.4, base - 0.74 * size, x1c - 0.4, base + 0.16 * size), fill=False)
        pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        font0.register(pg)
        pg.insert_text(pymupdf.Point(old_x0, base), new_text, fontsize=fit, color=color, **font0.kwargs)
        if reflow:
            for w in trailing:
                sp, rf = tr_fonts[id(w)]
                tcol = tuple(((sp["color"] >> s) & 255) / 255 for s in (16, 8, 0))
                rf.register(pg)
                pg.insert_text(pymupdf.Point(w[0] + shift, sp["origin"][1]), w[4], fontsize=sp["size"], color=tcol, **rf.kwargs)
        msg = REPLACEMENT_NOTICE
        if not font0.faithful:
            msg += f" The original font ({sp0['font'].split('+')[-1]}) is not available, so {font0.label} was used."
        if fit < size - 0.05:
            msg += " The new text is longer than the space available, so it was made slightly smaller."
        return ReplaceResult(True, font0.label, sp0["font"], not font0.faithful, fit, msg)

    @staticmethod
    def _band(word, size, baseline):
        """A thin horizontal band through the x-height of a word: it removes the word without touching neighbouring lines."""
        return pymupdf.Rect(word[0] + 0.4, baseline - 0.74 * size, word[2] - 0.4, baseline + 0.16 * size)

    def _draw_text(self, pg, r, text, fontsize, color, font) -> float:
        size = max(4.0, fontsize)
        box = pymupdf.Rect(r.x0, r.y0, max(r.x1, r.x0 + 4), max(r.y1, r.y0 + size * 1.3))
        while size >= 4.0:
            if pg.insert_textbox(box, text, fontsize=size, color=color, align=0, **font.kwargs) >= 0:
                return size
            size -= 0.5
        pg.insert_text(pymupdf.Point(r.x0, r.y0 + 4), text, fontsize=4.0, color=color, **font.kwargs)
        return 4.0

    @staticmethod
    def _remove_overlapping_annots(pg, r) -> int:
        """Annotations (comments, text boxes) can keep copies of text; delete those under `r`."""
        n = 0
        for a in list(pg.annots() or []):
            if a.type[0] != pymupdf.PDF_ANNOT_REDACT and pymupdf.Rect(a.rect).intersects(r):
                pg.delete_annot(a)
                n += 1
        return n

    # ---- redaction ----
    def redact_regions(self, regions, fill=(0, 0, 0), sanitize: bool = True) -> RedactionReport:
        """Permanently remove content under each (page, rect): text, image pixels and vector art.
        MuPDF deletes the underlying data; the black box is only the visual marker."""
        report = RedactionReport()
        by_page: dict[int, list[pymupdf.Rect]] = {}
        for page, rect in regions:
            by_page.setdefault(page, []).append(pymupdf.Rect(rect))
        with self._edit("Redact") as doc:
            for p, rects in by_page.items():
                pg = doc[p]
                for r in rects:
                    self._remove_overlapping_annots(pg, r)
                    pg.add_redact_annot(r, fill=fill)
                pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                                    graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED)
                report.regions += len(rects)
                report.pages.append(p)
            if sanitize:
                sec.sanitize_document(doc, metadata=False)
                report.sanitized = True
        return report

    def redact_text(self, terms: Iterable[str], fill=(0, 0, 0), sanitize: bool = True) -> RedactionReport:
        if isinstance(terms, str):
            terms = [terms]
        regions, found = [], 0
        with self.reader.lock:
            for term in terms:
                term = term.strip()
                if not term:
                    continue
                for i, pg in enumerate(self.reader.doc):
                    for hit in pg.search_for(term):
                        regions.append((i, tuple(hit)))
                        found += 1
        if not regions:
            return RedactionReport()
        rep = self.redact_regions(regions, fill, sanitize)
        rep.terms_found = found
        return rep

    def verify_removed(self, needle: str) -> bool:
        """True if `needle` can no longer be found, checked on a save/reload round trip of the current document."""
        with self.reader.lock:
            data = self.reader.doc.tobytes(garbage=4, clean=True, **self._enc_keep())
        d = sec.open_pdf_bytes(data, self.reader.password)
        try:
            return not any(needle.lower() in pg.get_text("text").lower() for pg in d)
        finally:
            d.close()

    # ---- metadata / sanitise ----
    def set_metadata(self, **fields: str) -> None:
        with self._edit("Edit metadata") as doc:
            md = dict(doc.metadata or {})
            md.update({k: v for k, v in fields.items() if k in md})
            doc.set_metadata(md)

    def sanitize(self, **kw) -> None:
        with self._edit("Sanitize document") as doc:
            sec.sanitize_document(doc, **kw)

    # ---- saving ----
    def _write_atomic(self, dst: Path, **opts) -> Path:
        """Write to a temp file next to `dst` and validate it; the caller moves it into place."""
        tmp = dst.with_name(f".{dst.stem}.{secrets.token_hex(4)}.dctmp")
        try:
            with self.reader.lock:
                watermark.stamp_pdf(self.reader.doc)
                self.reader.doc.save(tmp, **{"garbage": 3, "deflate": True, **self._enc_keep(), **opts})
            sec.open_pdf(tmp, self.reader.password, any_extension=True).close()   # never install an unreadable file
            return tmp
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _backup(self, path: Path) -> None:
        if not self.backup_dir or not path.exists():
            return
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        tag = hashlib.sha1(str(path).encode()).hexdigest()[:8]
        shutil.copy2(path, self.backup_dir / f"{path.stem}-{tag}-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}")
        for stale in sorted(self.backup_dir.glob(f"{path.stem}-{tag}-*"))[:-3]:
            stale.unlink(missing_ok=True)

    def save(self, confirm_overwrite: bool = False) -> Path:
        """Save over the original file. Requires explicit confirmation."""
        if not confirm_overwrite:
            raise OverwriteNotConfirmed(f"Saving will replace '{self.reader.path.name}'. Please confirm.")
        return self._commit(self.reader.path)

    def save_as(self, dst, confirm_overwrite: bool = False) -> Path:
        dst = Path(dst)
        if dst.suffix.lower() != ".pdf":
            dst = dst.with_suffix(".pdf")
        if dst.exists() and not confirm_overwrite:
            raise OverwriteNotConfirmed(f"'{dst.name}' already exists. Please confirm replacing it.")
        return self._commit(dst)

    def _commit(self, dst: Path) -> Path:
        """Windows cannot replace a file that is still open, so the document is closed first and,
        if the move fails, re-opened from the temp file so the user's edits are never lost."""
        dst = dst.resolve()
        tmp = self._write_atomic(dst)
        self._backup(dst)
        with self.reader.lock:
            self.reader.doc.close()
            try:
                os.replace(tmp, dst)
            except OSError as exc:
                self.reader.reopen(tmp, any_extension=True)
                raise DocuCraftError(f"Could not write '{dst.name}'. Your changes are safe in a temporary file:\n{tmp}",
                                     detail=str(exc)) from None
            self.reader.reopen(dst)
        self.dirty = False
        self._clean_len = len(self._undo)
        return dst

    def save_copy(self, dst, confirm_overwrite: bool = False) -> Path:
        """Write a copy without changing which file this document is bound to."""
        dst = Path(dst)
        if dst.exists() and not confirm_overwrite:
            raise OverwriteNotConfirmed(f"'{dst.name}' already exists. Please confirm replacing it.")
        if dst.exists() and dst.resolve() == self.reader.path:
            raise InvalidFileError("Use Save to replace the original, or pick another name for the copy.")
        tmp = self._write_atomic(dst)
        os.replace(tmp, dst)
        return dst

    def export_flattened(self, dst, mode: str = "annotations", dpi: int = 150, confirm_overwrite: bool = False) -> Path:
        """mode='annotations': bake annotations/forms into content, text stays selectable.
        mode='image': rasterise every page (maximum flattening; text is no longer selectable)."""
        dst = Path(dst)
        if dst.exists() and not confirm_overwrite:
            raise OverwriteNotConfirmed(f"'{dst.name}' already exists. Please confirm replacing it.")
        with self.reader.lock:
            copy = pymupdf.open("pdf", self.reader.doc.tobytes(garbage=0, deflate=False))
        tmp = dst.with_name(f".{dst.stem}.{secrets.token_hex(4)}.dctmp")
        try:
            watermark.stamp_pdf(copy)                      # in image mode the mark is rasterised with the page
            if mode == "image":
                out = pymupdf.open()
                try:
                    for pg in copy:
                        pix = pg.get_pixmap(dpi=dpi, annots=True)
                        out.new_page(width=pg.rect.width, height=pg.rect.height).insert_image(pg.rect, pixmap=pix)
                    out.save(tmp, garbage=3, deflate=True, **self._enc_new())
                finally:
                    out.close()
            else:
                copy.bake(annots=True, widgets=True)
                copy.save(tmp, garbage=3, deflate=True, **self._enc_new())
            os.replace(tmp, dst)
        finally:
            copy.close()
            tmp.unlink(missing_ok=True)
        return dst


PDFEditor = PdfEditor
