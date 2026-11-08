import time
import pymupdf
import pytest
from docx import Document
from PIL import Image
from converters import ocr_engine, pdf_to_word as p2w, pdf_to_image, image_to_pdf, word_to_pdf
from converters.pdf_to_word import ConversionOptions
from core.errors import (DependencyMissingError, InvalidFileError, OperationCancelled, PasswordRequiredError)

needs_tesseract = pytest.mark.skipif(not ocr_engine.is_available(), reason="Tesseract not installed")
needs_lo = pytest.mark.skipif(not word_to_pdf.is_available(), reason="LibreOffice not installed")
MODES = ["layout", "editable"]


def doc_text(path):
    d = Document(str(path))
    t = "\n".join(p.text for p in d.paragraphs)
    for tb in d.tables:
        for r in tb.rows:
            t += "\n" + " | ".join(c.text for c in r.cells)
    return t


@pytest.mark.parametrize("mode", MODES)
def test_simple_text(simple_pdf, work, mode):
    rep = p2w.convert_pdf_to_word(simple_pdf, work, ConversionOptions(mode=mode))
    assert rep.success and rep.pages_processed == 1 and rep.text_characters > 100 and rep.limitations
    t = doc_text(rep.output)
    assert "Heading page 1" in t and "4111-2222-3333" in t


def test_editable_real_headings(simple_pdf, work):
    d = Document(p2w.convert_pdf_to_word(simple_pdf, work, ConversionOptions(mode="editable")).output)
    assert any(p.style.name.startswith("Heading") and "Heading page 1" in p.text for p in d.paragraphs)


@pytest.mark.parametrize("mode", MODES)
def test_tables(table_pdf, work, mode):
    rep = p2w.convert_pdf_to_word(table_pdf, work, ConversionOptions(mode=mode))
    cells = [c.text.strip() for t in Document(rep.output).tables for r in t.rows for c in r.cells]
    assert rep.tables_detected >= 1 and "Widget" in cells and "25.50" in cells


@pytest.mark.parametrize("mode", MODES)
def test_images(image_pdf, work, mode):
    assert p2w.convert_pdf_to_word(image_pdf, work, ConversionOptions(mode=mode)).images_extracted >= 1
    assert p2w.convert_pdf_to_word(image_pdf, work, ConversionOptions(mode=mode, extract_images=False)).images_extracted == 0


def test_page_range_and_breaks(multi_pdf, work):
    rep = p2w.convert_pdf_to_word(multi_pdf, work, ConversionOptions(mode="editable", page_range="2-4"))
    t = doc_text(rep.output)
    assert rep.pages_processed == 3 and "page 2" in t and "page 4" in t and "page 5" not in t
    assert "w:pageBreakBefore" in Document(rep.output).element.xml


def test_headers_footers(work):
    src = work / "hf.pdf"
    d = pymupdf.open()
    for i in range(4):
        pg = d.new_page()
        pg.insert_text((72, 40), "ACME Confidential Report", fontsize=9)
        pg.insert_text((72, 120), f"Body text of page {i + 1} " * 3, fontsize=11)
        pg.insert_text((290, 810), f"{i + 1}", fontsize=9)
    d.save(src)
    rep = p2w.convert_pdf_to_word(src, work, ConversionOptions(mode="editable"))
    docx = Document(rep.output)
    assert "ACME Confidential Report" in docx.sections[0].header.paragraphs[0].text
    assert "PAGE" in docx.sections[0].footer._element.xml and rep.headers_footers_found == 2
    assert "ACME Confidential" not in "\n".join(p.text for p in docx.paragraphs)


def test_columns_orientation_sizes(columns_pdf, mixed_size_pdf, work):
    c = p2w.convert_pdf_to_word(columns_pdf, work, ConversionOptions(mode="editable"))
    t = doc_text(c.output)
    assert 'w:num="2"' in Document(c.output).element.xml and t.index("LEFT COLUMN") < t.index("RIGHT COLUMN")
    secs = Document(p2w.convert_pdf_to_word(mixed_size_pdf, work, ConversionOptions(mode="editable")).output).sections
    assert len(secs) == 3 and secs[2].page_width > secs[2].page_height


@pytest.mark.parametrize("mode", MODES)
def test_fonts(fonts_pdf, work, mode):
    assert "Font cour" in doc_text(p2w.convert_pdf_to_word(fonts_pdf, work, ConversionOptions(mode=mode)).output)


def test_font_name_cleanup():
    assert p2w.clean_font_name("ABCDEF+TimesNewRomanPS-BoldMT") == "Times New Roman" and p2w.clean_font_name("") == "Calibri"


@pytest.mark.parametrize("mode", MODES)
def test_password(protected_pdf, work, mode):
    with pytest.raises(PasswordRequiredError): p2w.convert_pdf_to_word(protected_pdf, work)
    rep = p2w.convert_pdf_to_word(protected_pdf, work, ConversionOptions(mode=mode, password="s3cret!"))
    assert "Heading page 1" in doc_text(rep.output)


def test_cancel_leaves_nothing(multi_pdf, work):
    with pytest.raises(OperationCancelled):
        p2w.convert_pdf_to_word(multi_pdf, work / "o", ConversionOptions(mode="editable"), cancel=lambda: True)
    assert not list((work / "o").glob("*")) and not list((work / "o").glob(".*"))
    n = {"c": 0}
    def cancel():
        n["c"] += 1; return n["c"] > 6
    with pytest.raises(OperationCancelled):
        p2w.convert_pdf_to_word(multi_pdf, work / "o2", ConversionOptions(mode="layout"), cancel=cancel)
    assert not list((work / "o2").glob("*.docx"))


def test_batch_and_no_overwrite_and_progress(simple_pdf, fake_pdf, table_pdf, work):
    reps = p2w.convert_batch([simple_pdf, fake_pdf, table_pdf], work, ConversionOptions(mode="editable"))
    assert [r.success for r in reps] == [True, False, True] and reps[1].error
    seen = []
    a = p2w.convert_pdf_to_word(simple_pdf, work, ConversionOptions(mode="editable"), progress=lambda p, m: seen.append(p))
    assert a.output != reps[0].output and seen[-1] == 100 and seen == sorted(seen)


def test_large_pdf_range_quick(large_pdf, work):
    t = time.perf_counter()
    assert p2w.convert_pdf_to_word(large_pdf, work, ConversionOptions(mode="editable", page_range="1-20")).pages_processed == 20
    assert time.perf_counter() - t < 30


@needs_tesseract
@pytest.mark.parametrize("mode", MODES)
def test_scanned_ocr(scanned_pdf, work, mode):
    rep = p2w.convert_pdf_to_word(scanned_pdf, work, ConversionOptions(mode=mode, ocr="auto"))
    low = doc_text(rep.output).lower()
    assert rep.scanned_pages_detected == 1 and rep.ocr_pages_processed == 1 and "invoice" in low and "alice" in low and "450" in low


@needs_tesseract
def test_ocr_off_searchable_languages(scanned_pdf, work):
    rep = p2w.convert_pdf_to_word(scanned_pdf, work, ConversionOptions(mode="editable", ocr="off"))
    assert rep.ocr_pages_processed == 0 and rep.warnings
    d = pymupdf.open(scanned_pdf); ocr_engine.make_searchable_pdf(d)
    assert "invoice" in d[0].get_text().lower() and d[0].search_for("Alice")
    assert "eng" in ocr_engine.available_languages()
    with pytest.raises(DependencyMissingError):
        p2w.convert_pdf_to_word(scanned_pdf, work, ConversionOptions(ocr="auto", ocr_language="xxx"))


def test_ocr_missing_dependency(scanned_pdf, work, monkeypatch):
    monkeypatch.setattr(ocr_engine, "find_tesseract", lambda: None)
    with pytest.raises(DependencyMissingError) as e:
        p2w.convert_pdf_to_word(scanned_pdf, work, ConversionOptions(ocr="auto"))
    assert "Tesseract" in e.value.user_message


def test_pdf_to_images(multi_pdf, work):
    r = pdf_to_image.pdf_to_images(multi_pdf, work / "png", fmt="png", dpi=72, pages="1-3")
    assert len(r) == 3 and r[0].name.endswith("_page_1.png")
    j = pdf_to_image.pdf_to_images(multi_pdf, work / "jpg", fmt="jpeg", dpi=100, pages="5"); assert j[0].suffix == ".jpg"
    hi = pdf_to_image.pdf_to_images(multi_pdf, work / "hi", dpi=144, pages="1")
    assert Image.open(hi[0]).size[0] == pytest.approx(Image.open(r[0]).size[0] * 2, abs=3)
    with pytest.raises(InvalidFileError): pdf_to_image.pdf_to_images(multi_pdf, work, fmt="gif")


def test_images_to_pdf(png_files, work):
    tall = work / "tall.png"; Image.new("RGB", (300, 900), "red").save(tall)
    d = pymupdf.open(image_to_pdf.images_to_pdf([*png_files, tall], work / "i.pdf"))
    assert d.page_count == 4 and d[0].rect.width > d[0].rect.height and d[3].rect.height > d[3].rect.width
    lt = pymupdf.open(image_to_pdf.images_to_pdf(png_files[:1], work / "l.pdf", page_size="Letter", orientation="landscape", margin_mm=0))
    assert (lt[0].rect.width, lt[0].rect.height) == (792, 612)
    bad = work / "bad.png"; bad.write_bytes(b"nope")
    with pytest.raises(InvalidFileError): image_to_pdf.images_to_pdf([bad], work / "x.pdf")
    with pytest.raises(InvalidFileError): image_to_pdf.images_to_pdf([], work / "x.pdf")


def _docx(path):
    d = Document(); d.add_heading("Quarterly Plan", 1); d.add_paragraph("Body paragraph for conversion.")
    t = d.add_table(rows=2, cols=2); t.style = "Table Grid"
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "A", "B", "C", "D"
    d.add_page_break(); d.add_paragraph("Second page text.")
    d.sections[0].header.paragraphs[0].text = "HEADER-TEXT"; d.sections[0].footer.paragraphs[0].text = "FOOTER-TEXT"
    d.save(path)


@needs_lo
def test_word_to_pdf(work, simple_pdf):
    src = work / "in.docx"; _docx(src)
    d = pymupdf.open(word_to_pdf.convert_docx_to_pdf(src, work / "o"))
    assert d.page_count == 2 and all(s in d[0].get_text() for s in ("Quarterly Plan", "HEADER-TEXT", "FOOTER-TEXT"))
    assert d[0].find_tables().tables and "Second page" in d[1].get_text()
    bad = work / "bad.docx"; bad.write_text("not a docx")
    outs, fails = word_to_pdf.convert_batch([src, bad], work / "o2")
    assert len(outs) == 1 and fails[0][0] == "bad.docx"
    rt = p2w.convert_pdf_to_word(simple_pdf, work, ConversionOptions(mode="editable"))
    assert "Heading page 1" in pymupdf.open(word_to_pdf.convert_docx_to_pdf(rt.output, work / "rt"))[0].get_text()


def test_word_to_pdf_errors(work, simple_pdf, monkeypatch):
    f = work / "x.docx"; _docx(f)
    monkeypatch.setattr(word_to_pdf, "find_libreoffice", lambda: None)
    with pytest.raises(DependencyMissingError) as e: word_to_pdf.convert_docx_to_pdf(f, work)
    assert "LibreOffice" in e.value.user_message
    monkeypatch.undo()
    if word_to_pdf.is_available():
        with pytest.raises(InvalidFileError): word_to_pdf.convert_docx_to_pdf(simple_pdf, work)
