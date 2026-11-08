"""Shadow watermark for every file DocuCraft writes. Qt-free.

PDF pages get a faint emblem in the middle and a small footer line (maker + contact details). A page that
already carries the footer is left alone, so repeated saves never pile marks up."""
from __future__ import annotations

import io
import logging

import pymupdf
from PIL import Image

from core import branding

log = logging.getLogger("docucraft.watermark")
_MIN_PAGE = 120            # points; below this a page is too small to carry a mark
_faded: dict[float, bytes] = {}


def _faded_mark(opacity: float) -> bytes:
    if opacity not in _faded:
        im = Image.open(io.BytesIO(branding.asset("watermark"))).convert("RGBA")
        alpha = im.getchannel("A").point(lambda a: int(a * opacity))
        im.putalpha(alpha)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        _faded[opacity] = buf.getvalue()
    return _faded[opacity]


def is_stamped(page: pymupdf.Page) -> bool:
    return bool(page.search_for(branding.STAMP_TEXT))


def _to_page_space(page: pymupdf.Page, rect: pymupdf.Rect) -> pymupdf.Rect:
    """`rect` is in the page as the user sees it; content streams use the unrotated page."""
    return (rect * page.derotation_matrix).normalize()


def stamp_page(page: pymupdf.Page) -> bool:
    view = page.rect                                           # rotated (visible) coordinates
    w, h = view.width, view.height
    if min(w, h) < _MIN_PAGE or is_stamped(page):
        return False
    rot = page.rotation
    # faint centre emblem
    side = min(w, h) * 0.34
    centre = pymupdf.Rect(view.x0 + (w - side) / 2, view.y0 + (h - side) / 2, view.x0 + (w + side) / 2, view.y0 + (h + side) / 2)
    page.insert_image(_to_page_space(page, centre), stream=_faded_mark(0.10), overlay=True, rotate=rot)
    # footer: small emblem + line of text
    text = branding.STAMP_LINE if w >= 460 else branding.STAMP_SHORT
    size = 6.5 if w >= 460 else 6.0
    font = pymupdf.Font("helv")
    tw = font.text_length(text, fontsize=size)
    icon = 11.0
    total = icon + 4 + tw
    x = view.x0 + (w - total) / 2
    y = view.y1 - 12
    page.insert_image(_to_page_space(page, pymupdf.Rect(x, y - icon + 2, x + icon, y + 2)),
                      stream=_faded_mark(0.85), overlay=True, rotate=rot)
    start = _to_page_space(page, pymupdf.Rect(x + icon + 4, y - 8, x + icon + 4 + tw, y + 2))
    tr = pymupdf.TextWriter(page.rect)
    # text is written in unrotated page space; rotate the baseline origin and direction with the page
    origin = pymupdf.Point(x + icon + 4, y) * page.derotation_matrix
    tr.append(origin, text, font=font, fontsize=size)
    tr.write_text(page, color=(0.42, 0.45, 0.5), opacity=0.9, morph=(origin, pymupdf.Matrix(rot)) if rot else None)
    _ = start
    return True


def stamp_pdf(doc: pymupdf.Document) -> int:
    """Stamp every page of an open document. Returns how many pages were marked. Never raises."""
    n = 0
    try:
        for page in doc:
            try:
                n += int(stamp_page(page))
            except Exception:                                  # noqa: BLE001
                log.exception("watermark failed on page %s", page.number)
    except Exception:                                          # noqa: BLE001
        log.exception("watermark failed")
    return n


def stamp_word(document) -> None:
    """Footer for a python-docx Document: small emblem plus the contact line, on every section."""
    from docx.shared import Inches, Pt, RGBColor
    try:
        for sec in document.sections:
            sec.footer.is_linked_to_previous = False
            para = sec.footer.paragraphs[0] if sec.footer.paragraphs else sec.footer.add_paragraph()
            if branding.STAMP_TEXT in para.text:
                continue
            run = para.add_run()
            run.add_picture(io.BytesIO(branding.asset("emblem_light")), height=Inches(0.16))
            r2 = para.add_run(f"  {branding.STAMP_LINE}")
            r2.font.size = Pt(8)
            r2.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
    except Exception:                                          # noqa: BLE001
        log.exception("word footer failed")


def stamp_image(path) -> None:
    """Footer line plus faint emblem on an exported page image (PNG / JPEG). Never raises."""
    from PIL import ImageDraw, ImageFont
    try:
        im = Image.open(path).convert("RGB")
        w, h = im.size
        if min(w, h) < 200:
            return
        mark = Image.open(io.BytesIO(_faded_mark(0.10))).convert("RGBA")
        side = int(min(w, h) * 0.34)
        mark = mark.resize((side, side), Image.LANCZOS)
        base = im.convert("RGBA")
        base.alpha_composite(mark, ((w - side) // 2, (h - side) // 2))
        draw = ImageDraw.Draw(base)
        size = max(11, int(w / 90))
        font = ImageFont.load_default(size=size)
        text = branding.STAMP_LINE if w >= 700 else branding.STAMP_SHORT
        tw = draw.textlength(text, font=font)
        icon = int(size * 1.5)
        x = int((w - (tw + icon + 6)) / 2)
        y = h - int(size * 2.2)
        em = Image.open(io.BytesIO(branding.asset("emblem_light"))).convert("RGBA").resize((icon, icon), Image.LANCZOS)
        base.alpha_composite(em, (x, y - 2))
        draw.text((x + icon + 6, y), text, font=font, fill=(107, 114, 128, 255))
        out = base.convert("RGB")
        if str(path).lower().endswith((".jpg", ".jpeg")):
            out.save(path, quality=92)
        else:
            out.save(path)
    except Exception:                                          # noqa: BLE001
        log.exception("image watermark failed")
