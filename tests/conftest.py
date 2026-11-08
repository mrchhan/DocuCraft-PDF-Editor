"""Synthetic test documents only - nothing here contains private data."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LOREM = ("DocuCraft processes documents locally. Privacy is a design goal, not an afterthought. "
         "The quick brown fox jumps over the lazy dog. ") * 3


def _font_path():
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(p):
            return p
    return None


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("DOCUCRAFT_HOME", str(tmp_path_factory.mktemp("dc_home")))


@pytest.fixture
def home(tmp_path):
    return tmp_path


@pytest.fixture
def work(tmp_path):
    return tmp_path


@pytest.fixture
def copy_of(tmp_path):
    """Copy a fixture file into a private folder so tests may edit/save it."""
    def _copy(src):
        dst = tmp_path / "copies" / Path(src).name
        dst.parent.mkdir(exist_ok=True)
        shutil.copyfile(src, dst)
        return dst
    return _copy


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def tmp_docs(tmp_path_factory):
    return tmp_path_factory.mktemp("docs")


@pytest.fixture(scope="session")
def make_pdf(tmp_docs):
    def _make(name, pages=1, title="Document", password=None):
        d = pymupdf.open()
        for i in range(1, pages + 1):
            pg = d.new_page()
            pg.insert_text((72, 80), f"Heading page {i}", fontsize=22, fontname="hebo")
            pg.insert_textbox(pymupdf.Rect(72, 110, 520, 700), f"Page {i} body. " + LOREM, fontsize=11)
            pg.insert_text((72, 760), f"Confidential account 4111-2222-3333 on page {i}.", fontsize=10)
        d.set_metadata({"title": title, "author": "Test Author"})
        d.set_toc([[1, f"Heading page {i}", i] for i in range(1, pages + 1)])
        out = tmp_docs / name
        kw = dict(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password + "x") if password else {}
        d.save(out, **kw)
        return out
    return _make


@pytest.fixture(scope="session")
def simple_pdf(make_pdf):
    return make_pdf("simple.pdf", 1, "Simple Test")


@pytest.fixture(scope="session")
def multi_pdf(make_pdf):
    return make_pdf("multi.pdf", 6)


multipage_pdf = multi_pdf


@pytest.fixture(scope="session")
def protected_pdf(make_pdf):
    return make_pdf("locked.pdf", 2, password="s3cret!")


@pytest.fixture(scope="session")
def table_pdf(tmp_docs):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle
    p = tmp_docs / "table.pdf"
    st = getSampleStyleSheet()
    t = Table([["Item", "Qty", "Price"], ["Widget", "4", "10.00"], ["Gadget", "2", "25.50"], ["Gizmo", "7", "3.25"]],
              colWidths=[200, 80, 100])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, colors.black), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
    SimpleDocTemplate(str(p), pagesize=A4).build([Paragraph("Invoice summary", st["Title"]),
                                                   Paragraph("Items sold this quarter.", st["Normal"]), t])
    return p


@pytest.fixture(scope="session")
def image_pdf(tmp_docs):
    img = Image.new("RGB", (400, 300))
    px = img.load()
    for x in range(400):
        for y in range(300):
            px[x, y] = (x * 255 // 400, y * 255 // 300, (x * y) % 255)
    ip = tmp_docs / "pic.png"
    img.save(ip)
    p = tmp_docs / "image.pdf"
    d = pymupdf.open()
    pg = d.new_page()
    pg.insert_text((72, 70), "Figure below", fontsize=14)
    pg.insert_image(pymupdf.Rect(72, 100, 372, 325), filename=str(ip))
    d.save(p)
    return p


@pytest.fixture(scope="session")
def scanned_pdf(tmp_docs):
    img = Image.new("RGB", (1240, 1754), "white")
    dr = ImageDraw.Draw(img)
    fp = _font_path()
    font = ImageFont.truetype(fp, 44) if fp else ImageFont.load_default()
    for i, ln in enumerate(["SCANNED INVOICE 12345", "Customer: Alice Example", "Total due: 450 dollars",
                            "Payment due within thirty days"]):
        dr.text((120, 200 + i * 90), ln, fill="black", font=font)
    ip = tmp_docs / "scan.png"
    img.save(ip)
    p = tmp_docs / "scanned.pdf"
    d = pymupdf.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_image(pg.rect, filename=str(ip))
    d.save(p)
    return p


@pytest.fixture(scope="session")
def mixed_size_pdf(tmp_docs):
    p = tmp_docs / "sizes.pdf"
    d = pymupdf.open()
    for w, h, label in ((595, 842, "A4 portrait"), (612, 792, "Letter"), (1191, 842, "A3 landscape")):
        d.new_page(width=w, height=h).insert_text((50, 80), label, fontsize=20)
    d.save(p)
    return p


@pytest.fixture(scope="session")
def columns_pdf(tmp_docs):
    p = tmp_docs / "columns.pdf"
    d = pymupdf.open()
    pg = d.new_page()
    pg.insert_text((72, 70), "Two Column Article", fontsize=20, fontname="hebo")
    pg.insert_textbox(pymupdf.Rect(72, 100, 285, 700), "LEFT COLUMN. " + LOREM * 3, fontsize=10)
    pg.insert_textbox(pymupdf.Rect(310, 100, 523, 700), "RIGHT COLUMN. " + LOREM * 3, fontsize=10)
    d.save(p)
    return p


@pytest.fixture(scope="session")
def fonts_pdf(tmp_docs):
    p = tmp_docs / "fonts.pdf"
    d = pymupdf.open()
    pg = d.new_page()
    y = 80
    for fn in ("cour", "tiit", "hebi", "symb", "zadb"):
        pg.insert_text((72, y), f"Font {fn} sample text 123", fontsize=14, fontname=fn)
        y += 30
    fp = _font_path()
    if fp:
        pg.insert_font(fontname="uni", fontfile=fp)
        pg.insert_text((72, y), "Unicode: caf\u00e9 \u00fc\u00f1\u00ee \u03a9\u03b1\u03b2 \u0416\u0434", fontsize=14, fontname="uni")
    d.save(p)
    return p


@pytest.fixture(scope="session")
def large_pdf(tmp_docs):
    p = tmp_docs / "large.pdf"
    d = pymupdf.open()
    for i in range(400):
        pg = d.new_page()
        pg.insert_text((72, 80), f"Large doc page {i + 1}", fontsize=16)
        pg.insert_textbox(pymupdf.Rect(72, 100, 520, 700), LOREM * 4, fontsize=10)
    d.save(p, garbage=3, deflate=True)
    return p


@pytest.fixture(scope="session")
def png_files(tmp_docs):
    out = []
    for i in range(3):
        f = tmp_docs / f"img{i}.png"
        Image.new("RGB", (320 + i * 40, 200), (40 * i, 120, 200)).save(f)
        out.append(f)
    return out


@pytest.fixture(scope="session")
def corrupt_pdf(tmp_docs, simple_pdf):
    p = tmp_docs / "corrupt.pdf"
    p.write_bytes(simple_pdf.read_bytes()[:300])
    return p


@pytest.fixture(scope="session")
def fake_pdf(tmp_docs):
    p = tmp_docs / "fake.pdf"
    p.write_text("this is not a pdf at all")
    return p
