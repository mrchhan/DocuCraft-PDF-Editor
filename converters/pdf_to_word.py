"""PDF -> editable Word (.docx).

Two engines, chosen by ConversionOptions.mode:

* "layout"   - pdf2docx (MIT). Keeps positions, columns, text boxes and tables as closely as
               possible. Best for forms and designed documents; harder to edit afterwards.
* "editable" - DocuCraft's own builder on python-docx. Clean flowing paragraphs, real headings,
               lists, tables, real headers/footers and columns. Best for editing text.

Scanned (image-only) pages are detected and, if allowed, OCR'd with Tesseract. No PDF -> Word
converter is 100% accurate; the returned ConversionReport states what was and was not preserved.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Sequence

import pymupdf
from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from core import pdf_security as sec
from core import watermark
from core.errors import ConversionError, DependencyMissingError, DocuCraftError, OperationCancelled
from core.pdf_organizer import Cancel, Progress, parse_page_ranges
from . import ocr_engine


@dataclass
class ConversionOptions:
    page_range: str = ""                 # "" = whole document, else e.g. "1-3,7"
    mode: str = "layout"                 # "layout" | "editable"
    extract_images: bool = True
    detect_tables: bool = True
    ocr: str = "auto"                    # "off" | "auto" (scanned pages only) | "force" (all pages)
    ocr_language: str = "eng"
    password: str | None = None


@dataclass
class ConversionReport:
    source: str = ""
    output: str = ""
    mode: str = ""
    pages_total: int = 0
    pages_processed: int = 0
    text_characters: int = 0
    images_extracted: int = 0
    tables_detected: int = 0
    scanned_pages_detected: int = 0
    ocr_pages_processed: int = 0
    headers_footers_found: int = 0
    duration_seconds: float = 0.0
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    success: bool = False
    error: str = ""

    def to_text(self) -> str:
        eng = "Preserve layout (pdf2docx)" if self.mode == "layout" else "Editable text (flowing)"
        lines = [f"Source:  {Path(self.source).name}", f"Output:  {Path(self.output).name if self.output else '—'}",
                 f"Engine:  {eng}", f"Pages processed:  {self.pages_processed} of {self.pages_total}",
                 f"Text extracted:  {self.text_characters:,} characters", f"Images in output:  {self.images_extracted}",
                 f"Tables in output:  {self.tables_detected}", f"Scanned pages detected:  {self.scanned_pages_detected}",
                 f"OCR pages processed:  {self.ocr_pages_processed}", f"Time:  {self.duration_seconds:.1f} s"]
        if self.warnings:
            lines += ["", "Warnings:"] + [f"  • {w}" for w in self.warnings]
        lines += ["", "Formatting limitations (no PDF→Word conversion is 100% exact):"] + [f"  • {l}" for l in self.limitations]
        if self.error:
            lines += ["", f"Error: {self.error}"]
        return "\n".join(lines)

    summary = to_text


QualityReport = ConversionReport


class _Cancelled(BaseException):
    """BaseException so third-party `except Exception` blocks cannot swallow a cancel."""


def convert_pdf_to_word(src, out_dir=None, options: ConversionOptions | None = None, progress: Progress = None,
                        cancel: Cancel = None, output_name: str | None = None) -> ConversionReport:
    opt = options or ConversionOptions()
    t0 = time.perf_counter()
    p = sec.validate_input_file(src)
    out_dir = sec.validate_output_dir(out_dir or p.parent)
    report = ConversionReport(source=str(p), mode=opt.mode)

    def tick(pct: int, msg: str) -> None:
        if cancel and cancel():
            raise _Cancelled()
        if progress:
            progress(pct, msg)

    doc = sec.open_pdf(p, opt.password)
    out_path = sec.unique_path(out_dir / ((output_name or sec.sanitize_filename(p.stem)) + ".docx"))
    tmp_out = out_path.with_name(f".{out_path.stem}.dctmp")
    try:
        pages = parse_page_ranges(opt.page_range, doc.page_count) if opt.page_range.strip() else list(range(doc.page_count))
        report.pages_total, report.pages_processed = doc.page_count, len(pages)
        tick(3, "Analysing pages")
        scanned = [i for i in pages if _is_scanned(doc[i])]
        report.scanned_pages_detected = len(scanned)
        ocr_pages = list(pages) if opt.ocr == "force" else scanned if opt.ocr == "auto" else []
        if ocr_pages and not ocr_engine.is_available():
            raise DependencyMissingError(ocr_engine.INSTALL_HINT)
        if scanned and opt.ocr == "off":
            report.warnings.append(f"{len(scanned)} scanned page(s) have no text and OCR is off, so they will be empty or image-only.")
        ocr_results = {}
        for n, i in enumerate(ocr_pages):
            tick(5 + int(n / len(ocr_pages) * 30), f"OCR page {i + 1} ({n + 1}/{len(ocr_pages)})")
            ocr_results[i] = ocr_engine.ocr_document_page(doc, i, opt.ocr_language)
        report.ocr_pages_processed = len(ocr_results)
        tick(40, "Building Word document")
        build = _build_editable if opt.mode == "editable" else _build_layout
        build(doc, pages, ocr_results, opt, report, tmp_out, lambda f, m: tick(40 + int(f * 52), m))
        tick(94, "Checking result")
        _post_stats(tmp_out, report)
        os.replace(tmp_out, out_path)
        report.output, report.success = str(out_path), True
        _add_limitations(report, opt)
        tick(100, "Done")
    except _Cancelled:
        tmp_out.unlink(missing_ok=True)
        raise OperationCancelled("Conversion cancelled.") from None
    except BaseException as exc:
        tmp_out.unlink(missing_ok=True)
        report.error = getattr(exc, "user_message", str(exc))
        if isinstance(exc, (DocuCraftError, KeyboardInterrupt)):
            raise
        raise ConversionError("The document could not be converted. It may use features this converter does not "
                              "support.", detail=repr(exc)) from exc
    finally:
        doc.close()
        report.duration_seconds = time.perf_counter() - t0
    return report


def convert_batch(sources: Sequence, out_dir=None, options: ConversionOptions | None = None, progress: Progress = None,
                  cancel: Cancel = None) -> list[ConversionReport]:
    """A failure is recorded in that file's report; the remaining files continue."""
    reports: list[ConversionReport] = []
    n = len(sources)
    for k, f in enumerate(sources):
        base, span, name = int(k / n * 100), 100 / n, Path(f).name
        sub = (lambda pct, msg, b=base, s=span, nm=name: progress(int(b + pct * s / 100), f"{nm}: {msg}")) if progress else None
        try:
            reports.append(convert_pdf_to_word(f, out_dir, options, sub, cancel))
        except OperationCancelled:
            raise
        except Exception as exc:
            reports.append(ConversionReport(source=str(f), mode=(options or ConversionOptions()).mode,
                                            error=getattr(exc, "user_message", str(exc))))
    if progress:
        progress(100, "Done")
    return reports


# ---- helpers --------------------------------------------------------------------
def _is_scanned(page: pymupdf.Page) -> bool:
    if len(page.get_text("text").strip()) >= 20:
        return False
    area = (page.rect.width * page.rect.height) or 1
    return sum(pymupdf.Rect(i["bbox"]).intersect(page.rect).get_area() for i in page.get_image_info()) / area > 0.5


def _post_stats(path: Path, rep: ConversionReport) -> None:
    """Count what actually landed in the .docx - more honest than counting the source."""
    d = Document(str(path))
    rep.tables_detected = len(d.tables)
    rep.images_extracted = len(d.element.body.xpath(".//a:blip"))
    text = "\n".join(p.text for p in d.paragraphs)
    for t in d.tables:
        for row in t.rows:
            text += "\n" + " ".join(c.text for c in row.cells)
    rep.text_characters = len(text.replace("\n", ""))


def _add_limitations(rep: ConversionReport, opt: ConversionOptions) -> None:
    L = rep.limitations
    if opt.mode == "layout":
        L.append("Layout mode places some text in frames/text boxes to match positions; editing long passages can be awkward.")
        L.append("Headers/footers become normal page content in layout mode (use Editable mode for real Word headers/footers).")
    else:
        L.append("Editable mode reflows text: exact positions, wrapping around images and decorative layout are not kept.")
        L.append("Merged table cells are flattened; table styling (borders/shading) is simplified.")
    L.append("Vector graphics and charts drawn as lines are not converted (only embedded raster images are).")
    L.append("Fonts not installed on the computer opening the .docx are substituted by Word.")
    if rep.ocr_pages_processed:
        L.append("OCR text can contain recognition errors; proofread it. Scanned pages become text; the scan image itself is not included.")
    L.append("Form fields, comments, bookmarks and digital signatures are not carried over.")


# ---- layout engine (pdf2docx) ----------------------------------------------------
class _ProgressLog(logging.Handler):
    _re = re.compile(r"\((\d+)/(\d+)\)")

    def __init__(self, cb, cancel):
        super().__init__(level=logging.INFO)
        self.cb, self.cancel = cb, cancel

    def emit(self, record):
        if self.cancel and self.cancel():
            raise _Cancelled()
        m = self._re.search(record.getMessage())
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            self.cb(min(0.9, a / max(1, b)), f"Converting page {a} of {b}")


def _build_layout(doc, pages, ocr_results, opt, report, dst: Path, cb) -> None:
    from pdf2docx import Converter

    tmp_pdf = dst.with_suffix(".src.dctmp")
    try:
        if ocr_results or opt.password is not None or not doc.name or not Path(doc.name).exists():
            work = pymupdf.open("pdf", doc.tobytes(garbage=0, deflate=False))   # decrypted in-memory copy
            for i, res in ocr_results.items():
                rect = work[i].rect
                work.delete_page(i)
                ocr_engine.text_only_page(work, i, res, rect.width, rect.height)
            work.save(tmp_pdf)
            work.close()
            source = str(tmp_pdf)
        else:
            source = str(doc.name)
        handler, root = _ProgressLog(cb, None), logging.getLogger()
        old = root.level
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        cv = Converter(source)
        try:
            cv.convert(str(dst), pages=list(pages), multi_processing=False, ignore_page_error=True)
        finally:
            cv.close()
            root.removeHandler(handler)
            root.setLevel(old)
        if not dst.exists():
            raise ConversionError("The layout converter did not produce a document.")
        d = Document(str(dst))
        if not opt.extract_images:
            for el in d.element.body.xpath(".//w:drawing"):
                el.getparent().remove(el)
            report.warnings.append("Images were removed as requested.")
        watermark.stamp_word(d)
        d.save(str(dst))
    finally:
        tmp_pdf.unlink(missing_ok=True)


# ---- editable engine -------------------------------------------------------------
_KNOWN_FONTS = (("times", "Times New Roman"), ("arial", "Arial"), ("helvet", "Arial"), ("calibri", "Calibri"),
                ("cambria", "Cambria"), ("courier", "Courier New"), ("consolas", "Consolas"), ("georgia", "Georgia"),
                ("verdana", "Verdana"), ("tahoma", "Tahoma"), ("segoe", "Segoe UI"), ("garamond", "Garamond"),
                ("palatino", "Palatino Linotype"), ("symbol", "Symbol"))
_BULLET_RE = re.compile(r"^\s*([•●▪◦‣⁃\-\*·–])\s+(.*)$", re.S)
_NUM_RE = re.compile(r"^\s*(\(?\d{1,3}[\.\)]|\(?[a-zA-Z][\.\)])\s+(.*)$", re.S)


def clean_font_name(raw: str) -> str:
    name = re.sub(r"^[A-Z]{6}\+", "", raw or "")
    low = name.lower()
    for key, nice in _KNOWN_FONTS:
        if key in low:
            return nice
    name = re.sub(r"(MT|PS|Std|Pro)$", "", re.split(r"[-,]", name)[0])
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).strip() or "Calibri"


@dataclass
class _Span:
    text: str
    size: float
    font: str
    bold: bool
    italic: bool
    color: int


@dataclass
class _Para:
    spans: list
    bbox: pymupdf.Rect
    y: float
    kind: str = "text"                   # text | table | image
    table: list | None = None
    image: bytes | None = None
    n_lines: int = 1
    page_no: int = 0

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def max_size(self) -> float:
        return max((s.size for s in self.spans if s.text.strip()), default=0.0)


def _block_to_para(block: dict, page_no: int):
    spans: list[_Span] = []
    lines = block.get("lines", [])
    for li, line in enumerate(lines):
        for sp in line["spans"]:
            if not sp["text"]:
                continue
            flags, font = sp["flags"], sp["font"]
            s = _Span(sp["text"], round(sp["size"], 1), clean_font_name(font), bool(flags & 16) or "bold" in font.lower(),
                      bool(flags & 2) or "italic" in font.lower() or "oblique" in font.lower(), sp["color"])
            if spans and (spans[-1].size, spans[-1].font, spans[-1].bold, spans[-1].italic, spans[-1].color) == \
                    (s.size, s.font, s.bold, s.italic, s.color):
                spans[-1].text += s.text
            else:
                spans.append(s)
        if li < len(lines) - 1 and spans:                    # line break inside a paragraph
            last = spans[-1]
            if last.text.endswith("-") and len(last.text) > 1 and last.text[-2].isalpha():
                last.text = last.text[:-1]
            elif not last.text.endswith(" "):
                last.text += " "
    if not "".join(s.text for s in spans).strip():
        return None
    r = pymupdf.Rect(block["bbox"])
    return _Para(spans, r, r.y0, n_lines=len(lines), page_no=page_no)


def _cluster_columns(band, content_w):
    cols: list[list[_Para]] = []
    for p in sorted(band, key=lambda p: p.bbox.x0):
        for c in cols:
            cx0, cx1 = min(q.bbox.x0 for q in c), max(q.bbox.x1 for q in c)
            if p.bbox.x0 < cx1 - 2 and p.bbox.x1 > cx0 + 2 and abs(p.bbox.x0 - cx0) < 0.12 * content_w:
                c.append(p)
                break
        else:
            cols.append([p])
    if len(cols) < 2:
        return cols
    spans = [(min(q.y for q in c), max(q.bbox.y1 for q in c)) for c in cols]
    overlap = min(s[1] for s in spans) - max(s[0] for s in spans)
    shortest = min(s[1] - s[0] for s in spans)
    return [band] if shortest <= 0 or overlap / shortest < 0.5 else cols


def _order_text_blocks(paras, content_w):
    """Reading order with simple multi-column detection -> [(n_columns, paragraphs)]."""
    if not paras:
        return []
    full = sorted([p for p in paras if p.bbox.width > 0.62 * content_w], key=lambda p: p.y)
    narrow = [p for p in paras if p not in full]
    ys = [f.y for f in full]
    bands = [[] for _ in range(len(ys) + 1)]
    for p in narrow:
        bands[sum(1 for y in ys if y <= p.bbox.y0 + 1)].append(p)
    regions = []

    def emit(band):
        if band:
            cols = _cluster_columns(band, content_w)
            if len(cols) >= 2:
                regions.append((len(cols), [p for c in cols for p in sorted(c, key=lambda p: p.y)]))
            else:
                regions.append((1, sorted(band, key=lambda p: (p.y, p.bbox.x0))))
    emit(bands[0])
    for k, f in enumerate(full):
        regions.append((1, [f]))
        emit(bands[k + 1])
    return regions


def _mostly_inside(inner, outer) -> bool:
    inter = inner & outer
    return not inter.is_empty and inter.get_area() / max(inner.get_area(), 1) > 0.6


def _ocr_items(res, page_no):
    items = []
    heights = sorted(l.height for l in res.lines) or [10]
    body_h = heights[len(heights) // 2]
    for par in res.paragraphs():
        x0, y0 = min(l.bbox[0] for l in par), min(l.bbox[1] for l in par)
        x1, y1 = max(l.bbox[2] for l in par), max(l.bbox[3] for l in par)
        h = sum(l.height for l in par) / len(par)
        size = round(11 * h / body_h, 1) if body_h else 11.0
        items.append(_Para([_Span(" ".join(l.text for l in par), max(8.0, min(40.0, size)), "Calibri", False, False, 0)],
                           pymupdf.Rect(x0, y0, x1, y1), y0, n_lines=len(par), page_no=page_no))
    return items


def _extract_tables(pg, page_no):
    out = []
    try:
        found = pg.find_tables()
    except Exception:
        return out
    for t in found.tables:
        try:
            rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in t.extract()]
        except Exception:
            continue
        if len(rows) < 2 or max(len(r) for r in rows) < 2 or not any(any(r) for r in rows):
            continue
        out.append(_Para([], pymupdf.Rect(t.bbox), t.bbox[1], kind="table", table=rows, page_no=page_no))
    return out


def _extract_images(doc, pg, page_no):
    out, seen = [], set()
    for info in pg.get_image_info(xrefs=True):
        xref, bbox = info.get("xref") or 0, pymupdf.Rect(info["bbox"])
        if not xref or bbox.width < 12 or bbox.height < 12 or (xref, round(bbox.x0), round(bbox.y0)) in seen:
            continue
        seen.add((xref, round(bbox.x0), round(bbox.y0)))
        try:
            pix = pymupdf.Pixmap(doc, xref)
            if pix.colorspace and pix.colorspace.n > 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            smask = doc.extract_image(xref).get("smask", 0)
            if smask:
                pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, smask))
            data = pix.tobytes("png")
        except Exception:
            continue
        out.append(_Para([], bbox, bbox.y0, kind="image", image=data, page_no=page_no))
    return out


def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.strip().lower()))


def _detect_headers_footers(page_data):
    n = len(page_data)
    if n < 2:
        return "", ""
    top, bottom, sample = Counter(), Counter(), {}
    for pdx in page_data:
        h, seen_t, seen_b = pdx["rect"].height, set(), set()
        for p in pdx["text"]:
            t = _norm(p.text)
            if not t or len(p.text) > 160:
                continue
            if p.bbox.y1 < 0.09 * h and t not in seen_t:
                seen_t.add(t); top[t] += 1; sample.setdefault(("t", t), p.text.strip())
            elif p.bbox.y0 > 0.91 * h and t not in seen_b:
                seen_b.add(t); bottom[t] += 1; sample.setdefault(("b", t), p.text.strip())
    need = max(2, (n + 1) // 2)
    ht = [(k, v) for k, v in top.items() if v >= need]
    fb = [(k, v) for k, v in bottom.items() if v >= need]
    return (sample[("t", max(ht, key=lambda kv: kv[1])[0])] if ht else "",
            sample[("b", max(fb, key=lambda kv: kv[1])[0])] if fb else "")


def _is_hf(p, rect, header, footer) -> bool:
    t = _norm(p.text)
    if header and p.bbox.y1 < 0.09 * rect.height and t == _norm(header):
        return True
    return bool(footer and p.bbox.y0 > 0.91 * rect.height and t == _norm(footer))


def _add_field(paragraph, instr: str) -> None:
    run = paragraph.add_run()
    for kind, text in (("begin", None), (None, instr), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def _write_hf(paragraph, text: str, first_page_no: int) -> None:
    """A number equal to the page number becomes a live PAGE field."""
    for part in re.split(r"(\d+)", text):
        if part.isdigit() and int(part) == first_page_no:
            _add_field(paragraph, "PAGE")
        elif part:
            paragraph.add_run(part).font.size = Pt(9)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _set_page(section, size, margins) -> None:
    w, h = size
    section.orientation = WD_ORIENT.LANDSCAPE if w > h else WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Pt(w), Pt(h)
    section.left_margin, section.right_margin, section.top_margin, section.bottom_margin = (Pt(m) for m in margins)


def _set_columns(section, n: int) -> None:
    sect_pr = section._sectPr
    cols = sect_pr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sect_pr.append(cols)
    cols.set(qn("w:num"), str(n))
    cols.set(qn("w:space"), "360")


def _page_break_marker(d) -> None:
    """A 1-pt paragraph that starts a new page without leaving a visible blank line."""
    par = d.add_paragraph()
    pf = par.paragraph_format
    pf.page_break_before = True
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing = Pt(1)
    par.add_run().font.size = Pt(1)


def _style_run(run, s: _Span) -> None:
    run.font.size = Pt(max(4.0, min(s.size, 96)))
    run.font.bold = s.bold or None
    run.font.italic = s.italic or None
    if s.color:
        run.font.color.rgb = RGBColor((s.color >> 16) & 255, (s.color >> 8) & 255, s.color & 255)
    run.font.name = s.font
    rfonts = run._r.get_or_add_rPr().find(qn("w:rFonts"))
    if rfonts is not None:
        rfonts.set(qn("w:eastAsia"), s.font)
        rfonts.set(qn("w:cs"), s.font)


def _strip_prefix(spans, n):
    out, left = [], n
    for s in spans:
        if left <= 0:
            out.append(s)
        elif len(s.text) <= left:
            left -= len(s.text)
        else:
            out.append(_Span(s.text[left:], s.size, s.font, s.bold, s.italic, s.color))
            left = 0
    return out


def _align(par, bbox, rect, left, right) -> None:
    content_w = rect.width - left - right
    if abs((bbox.x0 + bbox.x1) / 2 - rect.width / 2) < 0.03 * rect.width and bbox.width < 0.85 * content_w:
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif abs((rect.width - right) - bbox.x1) < 6 and bbox.x0 - left > 0.25 * content_w:
        par.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _emit(d, p, body_size, margins, rect, prev_bottom) -> None:
    left, right = margins[0], margins[1]
    content_w = rect.width - left - right
    if p.kind == "table":
        rows = p.table or []
        ncols = max(len(r) for r in rows)
        t = d.add_table(rows=len(rows), cols=ncols)
        t.style = "Table Grid"
        for ri, row in enumerate(rows):
            for ci in range(ncols):
                cell = t.cell(ri, ci)
                cell.text = row[ci] if ci < len(row) else ""
                if ri == 0:
                    for run in cell.paragraphs[0].runs:
                        run.font.bold = True
        d.add_paragraph().paragraph_format.space_after = Pt(2)
        return
    if p.kind == "image":
        par = d.add_paragraph()
        par.add_run().add_picture(BytesIO(p.image), width=Pt(max(8, min(p.bbox.width, content_w))))
        _align(par, p.bbox, rect, left, right)
        return
    text, style = p.text, None
    ratio = (p.max_size or body_size) / body_size if body_size else 1.0
    bold_all = all(s.bold for s in p.spans if s.text.strip())
    short = len(text.strip()) < 120 and p.n_lines <= 2
    m = _BULLET_RE.match(text)
    n = _NUM_RE.match(text) if not m else None
    if short and ratio >= 1.5:
        style = "Heading 1"
    elif short and ratio >= 1.25:
        style = "Heading 2"
    elif short and bold_all and ratio >= 1.08:
        style = "Heading 3"
    elif m:
        style = "List Bullet"
    elif n and re.match(r"^\(?\d", n.group(1)):
        style = "List Number"
    par = d.add_paragraph(style=style) if style else d.add_paragraph()
    spans = p.spans
    if style in ("List Bullet", "List Number"):
        mm = m or n
        spans = _strip_prefix(spans, len(text) - len(mm.group(2)))
    for s in spans:
        _style_run(par.add_run(s.text), s)
    if style and style.startswith("Heading"):
        for r in par.runs:                                   # keep the PDF colour (Word headings default to blue)
            if r.font.color.rgb is None:
                r.font.color.rgb = RGBColor(0, 0, 0)
    pf = par.paragraph_format
    if style is None or style.startswith("Heading"):
        _align(par, p.bbox, rect, left, right)
        if par.alignment in (None, WD_ALIGN_PARAGRAPH.LEFT) and p.bbox.x0 - left > 12:
            pf.left_indent = Pt(min(p.bbox.x0 - left, content_w / 2))
    if prev_bottom is not None:
        pf.space_before = Pt(max(0.0, min(24.0, p.bbox.y0 - prev_bottom - 1)))
    pf.space_after = Pt(0)


def _build_editable(doc, pages, ocr_results, opt, report, dst: Path, cb) -> None:
    d = Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    page_data, sizes = [], Counter()
    for n, i in enumerate(pages):                            # pass 1: gather
        cb(n / len(pages) * 0.5, f"Reading page {i + 1}")
        pg = doc[i]
        items = []
        if i in ocr_results:
            items = _ocr_items(ocr_results[i], i)
        else:
            for b in pg.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]:
                if b["type"] == 0 and (para := _block_to_para(b, i)):
                    items.append(para)
        tables = _extract_tables(pg, i) if opt.detect_tables and i not in ocr_results else []
        if tables:
            items = [p for p in items if not any(_mostly_inside(p.bbox, t.bbox) for t in tables)]
        images = _extract_images(doc, pg, i) if opt.extract_images and i not in ocr_results else []
        for p in items:
            for s in p.spans:
                sizes[s.size] += len(s.text.strip())
        page_data.append({"index": i, "rect": pg.rect, "text": items, "tables": tables, "images": images,
                          "drawings": len(pg.get_drawings())})
    body_size = sizes.most_common(1)[0][0] if sizes else 11.0
    header, footer = _detect_headers_footers(page_data)
    report.headers_footers_found = int(bool(header)) + int(bool(footer))
    lefts, rights, tops, bottoms = [], [], [], []
    for pdx in page_data:
        for p in pdx["text"]:
            lefts.append(p.bbox.x0); rights.append(pdx["rect"].width - p.bbox.x1)
            tops.append(p.bbox.y0); bottoms.append(pdx["rect"].height - p.bbox.y1)
    med = lambda v: sorted(v)[len(v) // 2] if v else 72.0
    margins = tuple(max(36.0, min(108.0, med(v))) for v in (lefts, rights, tops, bottoms))
    prev_size = None
    for n, pdx in enumerate(page_data):                      # pass 2: write
        cb(0.5 + n / len(page_data) * 0.5, f"Writing page {pdx['index'] + 1}")
        rect = pdx["rect"]
        size = (rect.width, rect.height)
        if n == 0:
            sect = d.sections[0]
            _set_page(sect, size, margins)
            if header:
                _write_hf(sect.header.paragraphs[0], header, 1)
            if footer:
                _write_hf(sect.footer.paragraphs[0], footer, 1)
        elif size != prev_size:
            _set_page(d.add_section(WD_SECTION.NEW_PAGE), size, margins)
        else:
            _page_break_marker(d)
        prev_size = size
        content_w = rect.width - margins[0] - margins[1]
        text_paras = [p for p in pdx["text"] if not _is_hf(p, rect, header, footer)]
        flow = [(min(p.y for p in pl), nc, pl) for nc, pl in _order_text_blocks(text_paras, content_w)]
        flow += [(e.y, 1, [e]) for e in pdx["tables"] + pdx["images"]]
        flow.sort(key=lambda t: t[0])
        cols, prev_bottom = 1, None
        for _, nc, plist in flow:
            if nc != cols:
                s = d.add_section(WD_SECTION.CONTINUOUS)
                _set_page(s, size, margins)
                _set_columns(s, nc)
                cols = nc
            for p in plist:
                _emit(d, p, body_size, margins, rect, prev_bottom)
                prev_bottom = p.bbox.y1
        if cols != 1:
            s = d.add_section(WD_SECTION.CONTINUOUS)
            _set_page(s, size, margins)
            _set_columns(s, 1)
        if pdx["drawings"] > 40 and not pdx["tables"]:
            note = f"Page {pdx['index'] + 1} contains many vector drawings/charts that are not converted."
            if note not in report.warnings:
                report.warnings.append(note)
    watermark.stamp_word(d)
    d.save(str(dst))
