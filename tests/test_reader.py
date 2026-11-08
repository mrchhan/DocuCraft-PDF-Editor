import time
import pymupdf
import pytest
from core.pdf_reader import PdfReader


def test_toc_and_pages(multi_pdf):
    r = PdfReader(multi_pdf); assert r.page_count == 6 and r.toc()[0] == (1, "Heading page 1", 0); r.close()


def test_render_zoom_rotation_png(simple_pdf):
    r = PdfReader(simple_pdf)
    a, b = r.render(0, 1.0), r.render(0, 2.0)
    assert b.width == pytest.approx(a.width * 2, abs=2)
    p = r.render(0, 1.0, rotation=90); assert (p.width, p.height) == (a.height, a.width)
    assert r.render_png(0)[:8] == b"\x89PNG\r\n\x1a\n"; r.close()


def test_search_and_words(multi_pdf):
    r = PdfReader(multi_pdf)
    hits = r.search("heading page 4"); assert 3 in hits
    assert r.search("zzzz") == {} and r.search("  ") == {}
    w = next(x for x in r.words(0) if x[4] == "Heading")
    assert "Heading" in r.text_in_rect(0, pymupdf.Rect(w[:4]) + (-2, -2, 2, 2)); r.close()


def test_mixed_sizes(mixed_size_pdf):
    r = PdfReader(mixed_size_pdf); s = r.page_size(2); assert s[0] > s[1] and len(r.info().page_sizes) == 3; r.close()


def test_large_pdf_is_lazy_and_fast(large_pdf):
    t = time.perf_counter(); r = PdfReader(large_pdf); r.render(250, 1.0)
    assert r.page_count == 400 and time.perf_counter() - t < 3; r.close()


def test_scanned_detection(scanned_pdf, simple_pdf):
    s, n = PdfReader(scanned_pdf), PdfReader(simple_pdf)
    assert s.is_scanned_page(0) and not n.is_scanned_page(0); s.close(); n.close()


def test_fonts_and_columns(fonts_pdf, columns_pdf):
    r = PdfReader(fonts_pdf); assert "Font cour" in r.page_text(0) and r.render(0).width > 0; r.close()
    c = PdfReader(columns_pdf); t = c.page_text(0); assert t.index("LEFT COLUMN") < t.index("RIGHT COLUMN"); c.close()


def test_info(simple_pdf):
    r = PdfReader(simple_pdf); i = r.info(); assert i.title == "Simple Test" and i.has_text and i.page_count == 1; r.close()
