"""Shadow branding is embedded in the program and every file DocuCraft writes carries the watermark."""
from __future__ import annotations

import docx
import pymupdf
import pytest

from core import branding, watermark
from core.pdf_editor import PdfEditor
from core.pdf_organizer import merge_pdfs
from core.pdf_reader import PdfReader


def make_pdf(path, pages=2, rotation=0):
    d = pymupdf.open()
    for i in range(pages):
        p = d.new_page()
        p.insert_text((72, 100), f"Page {i + 1} body text", fontsize=14)
        if rotation:
            p.set_rotation(rotation)
    d.save(path)
    d.close()
    return path


def test_assets_are_embedded_and_verified():
    assert branding.verify()
    for name in ("emblem_dark", "emblem_light", "full_dark", "full_light", "watermark"):
        assert len(branding.asset(name)) > 1000


def test_tampered_asset_is_rejected(monkeypatch):
    monkeypatch.setitem(branding._ASSETS, "emblem_dark", (branding._EMBLEM_LIGHT, branding._EMBLEM_DARK_SHA))
    with pytest.raises(RuntimeError):
        branding.asset("emblem_dark")


def test_contact_details():
    assert "Hassan Malik" in branding.CONTACT_LINE and "+923363330884" in branding.CONTACT_LINE
    assert "hassanmalik.net@gmail.com" in branding.CONTACT_LINE


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_stamp_is_idempotent_and_handles_rotation(tmp_path, rot):
    d = pymupdf.open(make_pdf(tmp_path / "a.pdf", 2, rot))
    assert watermark.stamp_pdf(d) == 2
    assert watermark.stamp_pdf(d) == 0
    assert all(branding.STAMP_TEXT in p.get_text() for p in d)
    assert all(p.get_images() for p in d)


def test_save_as_and_copy_are_stamped_once(tmp_path):
    src = make_pdf(tmp_path / "s.pdf")
    ed = PdfEditor(PdfReader(src))
    out = ed.save_as(tmp_path / "out.pdf")
    ed.save_as(tmp_path / "out2.pdf")                       # saving again must not double the mark
    with pymupdf.open(out) as r:
        assert all(p.get_text().count(branding.STAMP_TEXT) == 1 for p in r)
    cp = ed.save_copy(tmp_path / "copy.pdf")
    with pymupdf.open(cp) as r:
        assert all(p.get_text().count(branding.STAMP_TEXT) == 1 for p in r)


def test_merge_is_stamped(tmp_path):
    a = make_pdf(tmp_path / "a.pdf")
    out = merge_pdfs([a, a], tmp_path / "m.pdf")
    with pymupdf.open(out) as r:
        assert r.page_count == 4 and all(branding.STAMP_TEXT in p.get_text() for p in r)


def test_word_footer(tmp_path):
    d = docx.Document()
    d.add_paragraph("hello")
    watermark.stamp_word(d)
    watermark.stamp_word(d)
    text = "\n".join(p.text for p in d.sections[0].footer.paragraphs)
    assert text.count(branding.STAMP_TEXT) == 1 and branding.EMAIL in text


def test_image_export_is_stamped(tmp_path):
    from PIL import Image
    p = tmp_path / "x.png"
    Image.new("RGB", (900, 1200), "white").save(p)
    watermark.stamp_image(p)
    im = Image.open(p).convert("RGB")
    assert im.getbbox() and any(px != (255, 255, 255) for px in im.crop((0, 1130, 900, 1200)).getdata())


def test_app_window_has_watermark_overlay(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    monkeypatch.setenv("DOCUCRAFT_HOME", str(tmp_path / "home"))
    app = QApplication.instance() or QApplication([])
    from app.context import AppContext
    from app.main_window import MainWindow
    ctx = AppContext()
    win = MainWindow(ctx, app)
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    wm = win.watermark
    assert wm.geometry() == win.pages.rect() and wm.testAttribute(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WA_TransparentForMouseEvents)
    assert "+923363330884" in win.st_credit.text()
    win.navigate("tools")
    app.processEvents()
    assert wm.geometry() == win.pages.rect()
    win.close()
    ctx.db.close()
