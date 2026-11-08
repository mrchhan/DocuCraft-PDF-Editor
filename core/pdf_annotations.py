"""Annotation helpers. All functions operate on a pymupdf.Page and return the annotation.

Colours are RGB tuples in 0..1. Annotations stay real PDF annotations, so they remain
selectable, movable and deletable here and in other PDF readers.
"""
from __future__ import annotations

from typing import Sequence

import pymupdf

from .fonts import unicode_font_file, is_latin1

Color = tuple[float, float, float]
Point = tuple[float, float]

YELLOW: Color = (1.0, 0.92, 0.0)
RED: Color = (0.86, 0.12, 0.12)
BLACK: Color = (0.0, 0.0, 0.0)
BLUE: Color = (0.1, 0.35, 0.85)


def hex_to_rgb(value: str) -> Color:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def merge_word_rects(words: Sequence[tuple], tolerance: float = 3.0) -> list[pymupdf.Rect]:
    """Merge selected words ('words' tuples) into one rectangle per text line."""
    rects: list[pymupdf.Rect] = []
    for w in sorted(words, key=lambda w: (round(w[3] / tolerance), w[0])):
        r = pymupdf.Rect(w[:4])
        if rects and abs(rects[-1].y1 - r.y1) <= tolerance and r.x0 - rects[-1].x1 < 12:
            rects[-1] |= r
        else:
            rects.append(r)
    return rects


def _finish(annot, color, opacity, content="", width=None, fill=None):
    if color is not None or fill is not None:
        annot.set_colors(stroke=color, fill=fill)
    if width is not None:
        annot.set_border(width=width)
    annot.set_opacity(max(0.05, min(1.0, opacity)))
    if content:
        annot.set_info(content=content)
    annot.update()
    return annot


def add_text_markup(page, kind: str, rects, color: Color = YELLOW, opacity: float = 0.5, comment: str = ""):
    """kind: 'highlight' | 'underline' | 'strikeout'. `comment` becomes the popup note."""
    quads = [pymupdf.Rect(r).quad for r in rects]
    fn = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
          "strikeout": page.add_strikeout_annot}[kind]
    return _finish(fn(quads=quads), color, opacity if kind == "highlight" else max(opacity, 0.8), comment)


def add_sticky_note(page, point: Point, text: str, color: Color = YELLOW, author: str = ""):
    annot = page.add_text_annot(pymupdf.Point(point), text, icon="Note")
    annot.set_colors(stroke=color)
    if author:
        annot.set_info(title=author)
    annot.update()
    return annot


def add_text_box(page, rect, text: str, fontsize: float = 12, color: Color = BLACK, fill=None, border=None,
                 opacity: float = 1.0):
    kwargs = dict(fontsize=fontsize, text_color=color, fill_color=fill, border_color=border, align=0)
    if not is_latin1(text) and unicode_font_file():
        page.insert_font(fontname="dcfont", fontfile=unicode_font_file())
        kwargs["fontname"] = "dcfont"
    annot = page.add_freetext_annot(pymupdf.Rect(rect), text, **kwargs)
    annot.set_opacity(max(0.05, min(1.0, opacity)))
    annot.update()
    return annot


def add_freehand(page, strokes, color: Color = RED, width: float = 2.0, opacity: float = 1.0):
    strokes = [[tuple(p) for p in s] for s in strokes if len(s) >= 2]
    return _finish(page.add_ink_annot(strokes), color, opacity, width=width)


def add_line(page, p1: Point, p2: Point, color: Color = RED, width: float = 2.0, arrow: bool = False,
             opacity: float = 1.0):
    annot = page.add_line_annot(pymupdf.Point(p1), pymupdf.Point(p2))
    if arrow:
        annot.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_CLOSED_ARROW)
    return _finish(annot, color, opacity, width=width)


def add_shape(page, kind: str, rect, color: Color = RED, width: float = 2.0, fill=None, opacity: float = 1.0):
    """kind: 'rect' | 'ellipse'."""
    r = pymupdf.Rect(rect)
    annot = page.add_rect_annot(r) if kind == "rect" else page.add_circle_annot(r)
    return _finish(annot, color, opacity, width=width, fill=fill)


def add_image_stamp(page, rect, image_path: str, name: str = "Image"):
    """Image/signature as a stamp annotation, so it can be moved and resized later."""
    annot = page.add_stamp_annot(pymupdf.Rect(rect), stamp=str(image_path))
    annot.set_info(title="DocuCraft", subject=name)
    annot.update()
    return annot


def list_annotations(doc: pymupdf.Document, page_index: int | None = None) -> list[dict]:
    out: list[dict] = []
    for i in ([page_index] if page_index is not None else range(doc.page_count)):
        for a in doc[i].annots() or []:
            info = a.info or {}
            out.append({"page": i, "xref": a.xref, "type": a.type[1], "rect": pymupdf.Rect(a.rect),
                        "content": info.get("content", ""), "author": info.get("title", ""), "opacity": a.opacity})
    return out


def find_annotation_at(page, point: Point, pad: float = 3.0):
    p = pymupdf.Point(point)
    hit = None
    for a in page.annots() or []:
        if (pymupdf.Rect(a.rect) + (-pad, -pad, pad, pad)).contains(p):
            hit = a
    return hit


def move_annotation(page, xref: int, new_rect) -> None:
    for a in page.annots() or []:
        if a.xref == xref:
            a.set_rect(pymupdf.Rect(new_rect))
            a.update()
            return


def delete_annotation(page, xref: int) -> bool:
    for a in page.annots() or []:
        if a.xref == xref:
            page.delete_annot(a)
            return True
    return False


def restyle_annotation(page, xref: int, *, color=None, opacity=None, content=None) -> bool:
    for a in page.annots() or []:
        if a.xref == xref:
            if color is not None:
                a.set_colors(stroke=color)
            if opacity is not None:
                a.set_opacity(opacity)
            if content is not None:
                a.set_info(content=content)
            a.update()
            return True
    return False
