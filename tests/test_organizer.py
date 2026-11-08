import json
import pymupdf
import pytest
from PIL import Image
from core import pdf_organizer as org
from core.errors import InvalidFileError, OperationCancelled


def test_parse_ranges():
    assert org.parse_page_ranges("1-3,5", 10) == [0, 1, 2, 4] and org.parse_page_ranges("8-", 10) == [7, 8, 9]
    assert org.parse_page_ranges("3-1", 5) == [2, 1, 0]
    for bad in ("0", "11", "a-b", "", "1-99"):
        with pytest.raises(InvalidFileError): org.parse_page_ranges(bad, 10)


def test_merge(multi_pdf, simple_pdf, mixed_size_pdf, protected_pdf, work):
    out = org.merge_pdfs([simple_pdf, multi_pdf, mixed_size_pdf], work / "m.pdf")
    d = pymupdf.open(out); assert d.page_count == 10 and "Heading page 1" in d[1].get_text()
    pw = org.merge_pdfs([protected_pdf, simple_pdf], work / "p.pdf", passwords={str(protected_pdf): "s3cret!"})
    assert pymupdf.open(pw).page_count == 3
    assert org.merge_pdfs([simple_pdf, simple_pdf], work / "m.pdf") != out         # never overwrites
    with pytest.raises(InvalidFileError): org.merge_pdfs([simple_pdf], work / "x.pdf")
    with pytest.raises(OperationCancelled): org.merge_pdfs([simple_pdf, simple_pdf], work / "n.pdf", cancel=lambda: True)
    assert not (work / "n.pdf").exists() and not list(work.glob(".*dctmp"))


def test_split_modes(multi_pdf, work):
    r = org.split_pdf(multi_pdf, work / "a", "ranges", ranges="1-3, 5")
    assert [pymupdf.open(p).page_count for p in r] == [3, 1]
    assert len(org.split_pdf(multi_pdf, work / "b", "every")) == 6
    g = org.split_pdf(multi_pdf, work / "c", "groups", group_size=4)
    assert [pymupdf.open(p).page_count for p in g] == [4, 2]
    with pytest.raises(InvalidFileError): org.split_pdf(multi_pdf, work, "bogus")


def test_compress(work, simple_pdf):
    ip = work / "n.jpg"; Image.effect_noise((1800, 1800), 60).convert("RGB").save(ip, quality=95)
    d = pymupdf.open()
    for _ in range(3):
        pg = d.new_page(); pg.insert_image(pg.rect, filename=str(ip))
    big = work / "big.pdf"; d.save(big)
    sizes = {l: org.compress_pdf(big, work / f"{l}.pdf", l).new_size for l in ("low", "balanced", "high")}
    assert sizes["high"] <= sizes["balanced"] < big.stat().st_size
    r = org.compress_pdf(simple_pdf, work / "c.pdf", "high")
    assert r.new_size <= r.original_size and pymupdf.open(r.output)[0].get_text().strip()


def test_extract(image_pdf, multi_pdf, simple_pdf, work):
    t = org.extract_text(multi_pdf, work / "t.txt", pages_spec="2-3").read_text(encoding="utf-8")
    assert "Page 2 body" in t and "Page 4 body" not in t
    imgs = org.extract_images(image_pdf, work / "i"); assert len(imgs) == 1 and Image.open(imgs[0]).size == (400, 300)
    assert json.loads(org.export_metadata(simple_pdf, work / "m.json").read_text())["metadata"]["author"] == "Test Author"
    assert pymupdf.open(org.extract_pages(multi_pdf, work / "e.pdf", "2,4")).page_count == 2
