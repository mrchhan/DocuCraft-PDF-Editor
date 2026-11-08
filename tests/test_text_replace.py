"""Existing-text replacement must keep the font, size, colour and baseline, and must not damage neighbouring text."""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from core.pdf_editor import PdfEditor
from core.pdf_reader import PdfReader

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
LINES = ["Create consistent recruitment content for Facebook and",
         "Make the next step clear with approved WhatsApp",
         "enquiry prompts. Turn approved vacancy information into posters"]


@pytest.fixture
def inter_pdf(tmp_path):
    """A design-style page: tinted background, Inter text as an embedded *subset*, tight line spacing."""
    d = pymupdf.open()
    pg = d.new_page(width=600, height=300)
    pg.draw_rect(pymupdf.Rect(0, 0, 600, 300), color=None, fill=(0.97, 0.96, 0.92))
    pg.insert_font(fontname="inter", fontfile=str(FONTS / "Inter-Regular.otf"))
    pg.insert_font(fontname="interb", fontfile=str(FONTS / "Inter-Bold.otf"))
    y = 100
    for ln in LINES:
        pg.insert_text((40, y), ln, fontname="inter", fontsize=11, color=(0.1, 0.1, 0.15))
        y += 14.5
    pg.insert_text((40, 200), "A Bold Heading here", fontname="interb", fontsize=16)
    d.subset_fonts()
    out = tmp_path / "inter.pdf"
    d.save(out)
    return out


def word(ed, text, nth=0):
    return [w for w in ed.reader.doc[0].get_text("words") if w[4] == text][nth]


def spans_of(ed, text):
    for b in ed.reader.doc[0].get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                if text in sp["text"]:
                    yield sp


def sloppy(w):
    return pymupdf.Rect(w[0] - 4, w[1] - 3, w[2] + 4, w[3] + 9)          # overlaps the line below, like a hand-drawn box


def test_longer_word_keeps_font_size_and_neighbours(inter_pdf):
    ed = PdfEditor(PdfReader(inter_pdf))
    r = sloppy(word(ed, "next"))
    assert ed.analyze_text(0, r).text == "next"                            # the line below is not picked up
    res = ed.replace_text(0, r, "following")
    text = ed.reader.page_text(0)
    assert "following" in text and "next" not in text
    assert LINES[0] in text and "enquiry prompts. Turn approved vacancy information into posters" in text   # neighbours intact
    sp = next(spans_of(ed, "following"))
    assert "Inter" in sp["font"] and sp["size"] == pytest.approx(11, abs=0.01) and res.fit_fontsize == pytest.approx(11, abs=0.01)
    new, step = word(ed, "following"), word(ed, "step")
    assert new[2] < step[0] - 1                                              # rest of the line moved: no overlap
    assert word(ed, "WhatsApp")[2] < 590                                     # still on the page


def test_shorter_word_pulls_line_in(inter_pdf):
    ed = PdfEditor(PdfReader(inter_pdf))
    old_step = word(ed, "step")[0]
    ed.replace_text(0, word(ed, "next")[:4], "so")
    new, step = word(ed, "so"), word(ed, "step")
    assert step[0] < old_step and 0 < step[0] - new[2] < 6                 # natural single space, no hole
    assert "so step clear" in ed.reader.page_text(0).replace("\n", " ")


def test_bold_text_stays_bold(inter_pdf):
    ed = PdfEditor(PdfReader(inter_pdf))
    ed.replace_text(0, word(ed, "Heading")[:4], "Title")
    sp = next(spans_of(ed, "Title"))
    assert "Bold" in sp["font"] and sp["size"] == pytest.approx(16, abs=0.01)


def test_original_text_really_removed(inter_pdf, tmp_path):
    ed = PdfEditor(PdfReader(inter_pdf))
    ed.replace_text(0, word(ed, "next")[:4], "following")
    out = ed.save_copy(tmp_path / "o.pdf")
    with pymupdf.open(out) as d:
        assert "next" not in d[0].get_text()


def test_undo_restores_original(inter_pdf):
    ed = PdfEditor(PdfReader(inter_pdf))
    ed.replace_text(0, word(ed, "next")[:4], "following")
    ed.undo()
    assert "next step" in ed.reader.page_text(0).replace("\n", " ") and not ed.dirty


def test_unusual_characters_do_not_crash(inter_pdf):
    ed = PdfEditor(PdfReader(inter_pdf))
    res = ed.replace_text(0, word(ed, "next")[:4], "Ünïcode ✓")
    assert res.ok and "Ünïcode" in ed.reader.page_text(0)


def test_multi_line_selection_replaced_as_block(inter_pdf):
    ed = PdfEditor(PdfReader(inter_pdf))
    a, b = word(ed, "Make"), word(ed, "enquiry")
    ed.replace_text(0, pymupdf.Rect(a[0] - 2, a[1] - 1, 300, b[3] + 1), "Replaced block of text")
    t = ed.reader.page_text(0)
    assert "Replaced block" in t and "Facebook and" in t and "Make the next" not in t


def test_preview_matches_result_and_leaves_document_untouched(inter_pdf):
    ed = PdfEditor(PdfReader(inter_pdf))
    before = ed.reader.page_text(0)
    png = ed.preview_replace(0, sloppy(word(ed, "next")), "following")
    assert png[:4] == b"\x89PNG" and ed.reader.page_text(0) == before and not ed.dirty
