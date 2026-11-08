import pymupdf
import pytest

from core import pdf_security as sec
from core.errors import InvalidFileError, InvalidPdfError, PasswordRequiredError, WrongPasswordError


def test_open_valid(simple_pdf):
    d = sec.open_pdf(simple_pdf); assert d.page_count == 1; d.close()


def test_missing_wrong_type_empty_fake_corrupt(tmp_path, fake_pdf, corrupt_pdf):
    with pytest.raises(InvalidFileError): sec.open_pdf("/nonexistent/file.pdf")
    t = tmp_path / "a.txt"; t.write_text("x")
    with pytest.raises(InvalidFileError): sec.validate_input_file(t)
    e = tmp_path / "e.pdf"; e.write_bytes(b"")
    with pytest.raises(InvalidFileError): sec.validate_input_file(e)
    with pytest.raises(InvalidPdfError): sec.open_pdf(fake_pdf)
    with pytest.raises(InvalidPdfError) as ex: sec.open_pdf(corrupt_pdf)
    assert ex.value.user_message


def test_password_flow(protected_pdf):
    with pytest.raises(PasswordRequiredError): sec.open_pdf(protected_pdf)
    with pytest.raises(WrongPasswordError): sec.open_pdf(protected_pdf, "nope")
    d = sec.open_pdf(protected_pdf, "s3cret!"); assert "Heading page 1" in d[0].get_text(); d.close()
    assert sec.is_encrypted(protected_pdf)


def test_encrypt_decrypt_roundtrip(simple_pdf, tmp_path):
    enc = sec.encrypt_pdf(simple_pdf, tmp_path / "enc.pdf", "abc")
    with pytest.raises(PasswordRequiredError): sec.open_pdf(enc)
    sec.open_pdf(sec.decrypt_pdf(enc, tmp_path / "dec.pdf", "abc")).close()
    with pytest.raises(InvalidFileError): sec.encrypt_pdf(simple_pdf, simple_pdf, "x")


def test_filenames_and_unique_paths(tmp_path):
    assert sec.sanitize_filename('a<b>:c?.pdf') == "a_b__c_.pdf" and sec.sanitize_filename("CON") == "document"
    f = tmp_path / "x.pdf"; f.write_text("1")
    assert sec.unique_path(f).name == "x (2).pdf"


def test_secure_temp_cleanup():
    with sec.SecureTempDir() as t:
        t.file(".bin").write_bytes(b"secret"); d = t.path; assert d.exists()
    assert not d.exists()


def test_safe_zoom_clamps_huge_render():
    z = sec.safe_zoom(pymupdf.Rect(0, 0, 10000, 10000), 20)
    assert 10000 * 10000 * z * z <= sec.MAX_RENDER_PIXELS * 1.01


def test_sanitize_removes_metadata(simple_pdf, tmp_path):
    d = pymupdf.open(simple_pdf); sec.sanitize_document(d)
    out = tmp_path / "clean.pdf"; d.save(out, garbage=4)
    assert not pymupdf.open(out).metadata.get("author") and b"Test Author" not in out.read_bytes()
