import pymupdf
import pytest
from core import pdf_annotations as ann
from core import pdf_security as sec
from core.errors import DocuCraftError, OverwriteNotConfirmed
from core.pdf_editor import PdfEditor
from core.pdf_reader import PdfReader

SECRET = "4111-2222-3333"


@pytest.fixture
def ed(simple_pdf, work):
    p = work / "doc.pdf"; p.write_bytes(simple_pdf.read_bytes())
    r = PdfReader(p); yield PdfEditor(r, backup_dir=work / "bak"); r.close()


@pytest.fixture
def multi(multi_pdf, work):
    p = work / "m.pdf"; p.write_bytes(multi_pdf.read_bytes())
    r = PdfReader(p); yield PdfEditor(r); r.close()


def find(e, t):
    return e.reader.doc[0].search_for(t)[0]


def test_markup_shapes_and_notes(ed, image_pdf, tmp_docs):
    r = find(ed, "Heading page 1")
    for k in ("highlight", "underline", "strikeout"):
        ed.add_markup(0, k, [r], opacity=0.4, comment="check")
    ed.add_note(0, (400, 100), "sticky"); ed.add_text_box(0, (300, 450, 500, 500), "café Ω", 14)
    ed.add_freehand(0, [[(100, 500), (120, 520), (150, 505)]]); ed.add_line(0, (100, 600), (300, 600), arrow=True)
    ed.add_shape(0, "rect", (100, 650, 200, 700)); ed.add_shape(0, "ellipse", (220, 650, 320, 700), fill=(1, 1, .6))
    xref = ed.add_image(0, (100, 450, 200, 520), tmp_docs / "pic.png")
    kinds = {a["type"] for a in ann.list_annotations(ed.reader.doc)}
    assert {"Highlight", "Underline", "StrikeOut", "Text", "FreeText", "Ink", "Line", "Square", "Circle", "Stamp"} <= kinds
    ed.move_annotation(0, xref, (150, 460, 350, 600))
    assert next(a for a in ann.list_annotations(ed.reader.doc) if a["xref"] == xref)["rect"].width == pytest.approx(200, abs=1)
    hl = next(a for a in ann.list_annotations(ed.reader.doc) if a["type"] == "Highlight")
    assert hl["content"] == "check" and hl["opacity"] == pytest.approx(0.4, abs=.01)
    assert ed.restyle_annotation(0, hl["xref"], opacity=0.2) and ed.delete_annotation(0, hl["xref"])


def test_annotation_persists(ed):
    ed.add_markup(0, "highlight", [find(ed, "Heading")]); ed.save(confirm_overwrite=True)
    a = PdfReader(ed.reader.path); assert any(x["type"] == "Highlight" for x in ann.list_annotations(a.doc)); a.close()


def test_add_text_shrinks(ed):
    assert ed.add_text_to_page(0, (72, 600, 150, 620), "A rather long sentence that cannot fit", 14) < 14
    assert "rather long" in ed.reader.page_text(0)


def test_page_operations(multi):
    multi.insert_blank_page(after=0); assert multi.reader.page_count == 7 and not multi.reader.page_text(1).strip()
    multi.duplicate_page(2); multi.delete_pages([1]); multi.rotate_pages([0], 90)
    assert multi.reader.page_count == 7 and multi.reader.page_rotation(0) == 90
    multi.move_page(0, 3); assert "page 1" in multi.reader.page_text(3)
    multi.reorder(list(reversed(range(7)))); assert multi.reader.page_count == 7
    with pytest.raises(DocuCraftError): multi.delete_pages(range(7))
    assert multi.reader.page_count == 7


def test_extract_replace_pages(multi, work, simple_pdf):
    out = multi.extract_pages([2, 3], work / "ex.pdf"); assert pymupdf.open(out).page_count == 2
    with pytest.raises(OverwriteNotConfirmed): multi.extract_pages([0], out)
    multi.replace_pages(0, 2, simple_pdf); assert multi.reader.page_count == 5


def test_undo_redo(multi):
    multi.delete_pages([0]); multi.rotate_pages([0], 90)
    multi.undo(); assert multi.reader.page_rotation(0) == 0
    multi.undo(); assert multi.reader.page_count == 6
    multi.redo(); assert multi.reader.page_count == 5 and multi.can_redo
    multi.rotate_pages([0], 90); assert not multi.can_redo


def test_save_rules(ed, work):
    orig = ed.reader.path.read_bytes(); ed.add_note(0, (100, 100), "n")
    with pytest.raises(OverwriteNotConfirmed): ed.save()
    assert ed.reader.path.read_bytes() == orig and ed.dirty
    c = ed.save_copy(work / "copy.pdf"); assert c.exists() and ed.dirty
    n = ed.save_as(work / "renamed.pdf"); assert ed.reader.path == n.resolve() and not ed.dirty
    with pytest.raises(OverwriteNotConfirmed): ed.save_as(work / "renamed.pdf")
    ed.add_note(0, (120, 120), "n2"); ed.save(confirm_overwrite=True)
    assert list((work / "bak").glob("renamed-*.pdf")) and not list(work.glob(".*dctmp"))


def test_encryption_kept_through_undo_save_export(protected_pdf, work):
    p = work / "enc.pdf"; p.write_bytes(protected_pdf.read_bytes())
    r = PdfReader(p, password="s3cret!"); e = PdfEditor(r)
    e.add_note(0, (100, 100), "a"); e.add_note(0, (120, 120), "b"); e.undo(); e.save(confirm_overwrite=True)
    for f in (p, e.export_flattened(work / "f1.pdf", "annotations"), e.export_flattened(work / "f2.pdf", "image")):
        with pytest.raises(Exception): sec.open_pdf(f)
    assert len(ann.list_annotations(sec.open_pdf(p, "s3cret!"))) == 1; r.close()


def test_export_flattened(ed, work):
    ed.add_markup(0, "highlight", [find(ed, "Heading")])
    d = pymupdf.open(ed.export_flattened(work / "a.pdf")); assert not list(d[0].annots() or []) and "Heading" in d[0].get_text()
    d2 = pymupdf.open(ed.export_flattened(work / "b.pdf", "image")); assert not d2[0].get_text().strip() and d2[0].get_images()


def test_text_replacement_is_honest_and_removes_original(ed, work):
    r = find(ed, "Heading page 1"); st = ed.analyze_text(0, r)
    assert "Heading page 1" in st.text and st.fontsize == pytest.approx(22, abs=.6) and st.bold
    before = ed.reader.page_text(0)
    assert ed.preview_replace(0, r, "Preview")[:4] == b"\x89PNG" and ed.reader.page_text(0) == before and not ed.dirty
    res = ed.replace_text(0, r + (-1, -1, 60, 1), "Brand New Title")
    assert "not native" in res.message and "Brand New Title" in ed.reader.page_text(0)
    ed.replace_text(0, find(ed, SECRET), "REDACTED-ID"); ed.replace_text(0, find(ed, "Brand"), "Héllo Über")
    assert sec.verify_redaction(ed.save_copy(work / "rep.pdf"), [SECRET]) == []


def test_redaction_removes_text_everywhere(ed, work):
    ed.add_text_box(0, (72, 500, 400, 530), f"{SECRET} copied in a comment")
    rep = ed.redact_regions([(0, tuple(find(ed, SECRET))), (0, (60, 490, 420, 540))])
    assert rep.regions == 2
    out = ed.save_copy(work / "red.pdf")
    assert sec.verify_redaction(out, [SECRET]) == [] and SECRET.encode() not in out.read_bytes()
    from pypdf import PdfReader as PR
    assert SECRET not in PR(str(out)).pages[0].extract_text()          # independent parser
    assert ed.verify_removed(SECRET)
    ed.undo(); assert SECRET in ed.reader.page_text(0)                  # undoable in session only


def test_redact_text_across_document(multi, work):
    rep = multi.redact_text("Heading page 5"); assert rep.terms_found >= 1
    out = multi.save_copy(work / "r.pdf")
    assert sec.verify_redaction(out, ["Heading page 5"]) == [] and sec.verify_redaction(out, ["Heading page 6"]) != []


def test_undo_back_to_saved_state_is_clean(multi_pdf, copy_of):
    from core.pdf_editor import PdfEditor
    from core.pdf_reader import PdfReader
    ed = PdfEditor(PdfReader(copy_of(multi_pdf)))
    ed.add_shape(0, "rect", (80, 80, 200, 160))
    assert ed.dirty
    ed.undo()
    assert not ed.dirty
    ed.redo()
    assert ed.dirty
    ed.undo()
    ed.add_shape(0, "ellipse", (80, 80, 200, 160))
    ed.undo()
    assert not ed.dirty                                  # back at the original, unsaved-free state


def test_redaction_keeps_page_background_but_removes_text(tmp_path):
    """A full-page background shape touching the redaction box must survive; the text under the box must not."""
    d = pymupdf.open()
    pg = d.new_page()
    pg.draw_rect(pg.rect, color=None, fill=(0.97, 0.96, 0.9))
    pg.insert_text((72, 100), "Keep me. Account 4417-2290-8811 here.", fontsize=12)
    src = tmp_path / "bg.pdf"
    d.save(src)
    from core.pdf_editor import PdfEditor
    from core.pdf_reader import PdfReader
    ed = PdfEditor(PdfReader(src))
    ed.redact_regions([(0, tuple(ed.reader.doc[0].search_for("4417-2290-8811")[0]))])
    page = ed.reader.doc[0]
    assert "4417" not in page.get_text() and "Keep me" in page.get_text()
    px = page.get_pixmap(clip=pymupdf.Rect(400, 400, 410, 410))                 # far from the box
    assert px.pixel(2, 2) != (255, 255, 255)                                    # background still there
    assert ed.verify_removed("4417-2290-8811")
