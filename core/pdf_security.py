"""File validation, password handling, secure temp files, encryption, sanitising and
redaction verification. Local-only; no document content is ever logged or transmitted."""
from __future__ import annotations

import atexit
import os
import re
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from typing import Iterable, Sequence

import pymupdf

from . import watermark
from .errors import (InvalidFileError, InvalidPdfError, PasswordRequiredError, ResourceLimitError,
                     WrongPasswordError)

pymupdf.TOOLS.mupdf_display_errors(False)

MAX_FILE_BYTES = 2 * 1024**3          # 2 GiB
MAX_PAGES = 50_000
MAX_PAGE_POINTS = 14_400              # 200 inches per side
MAX_RENDER_PIXELS = 80_000_000
TEMP_PREFIX = "docucraft_"
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


# ---- validation ---------------------------------------------------------------
def has_pdf_header(path: Path) -> bool:
    with open(path, "rb") as fh:
        return b"%PDF-" in fh.read(1024)          # the spec allows the header within the first 1 KiB


def validate_input_file(path, *, extensions: Sequence[str] | None = (".pdf",),
                        max_bytes: int = MAX_FILE_BYTES) -> Path:
    """Return a resolved Path or raise InvalidFileError with a human-readable reason."""
    if path is None or str(path).strip() == "" or "\x00" in str(path):
        raise InvalidFileError("No valid file was selected.")
    try:
        p = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise InvalidFileError(f"The file could not be found:\n{path}") from None
    if not p.is_file():
        raise InvalidFileError(f"This is not a regular file:\n{p.name}")
    if extensions is not None and p.suffix.lower() not in [e.lower() for e in extensions]:
        raise InvalidFileError(f"Unsupported file type '{p.suffix}'. Expected: {', '.join(extensions)}")
    size = p.stat().st_size
    if size == 0:
        raise InvalidFileError(f"'{p.name}' is empty (0 bytes).")
    if size > max_bytes:
        raise ResourceLimitError(f"'{p.name}' is {size / 1024**3:.1f} GB, above the {max_bytes / 1024**3:.0f} GB safety limit.")
    if (extensions is None or ".pdf" in extensions) and (extensions is None or p.suffix.lower() == ".pdf") \
            and not has_pdf_header(p):
        raise InvalidPdfError(f"'{p.name}' has a .pdf extension but is not a PDF document.")
    return p


validate_pdf = validate_input_file


def sanitize_filename(name: str, fallback: str = "document") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name or name.upper().split(".")[0] in _WIN_RESERVED:
        name = fallback
    return name[:150]


def unique_path(path) -> Path:
    """Return `path`, or 'name (2).ext' etc., so nothing is ever silently overwritten."""
    p = Path(path)
    if not p.exists():
        return p
    for i in range(2, 10_000):
        cand = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not cand.exists():
            return cand
    raise InvalidFileError("Could not find a free output file name.")


safe_output_path = unique_path


def validate_output_dir(path, create: bool = True) -> Path:
    p = Path(path).expanduser()
    try:
        if create:
            p.mkdir(parents=True, exist_ok=True)
        p = p.resolve(strict=True)
    except OSError as exc:
        raise InvalidFileError(f"The output folder is not available:\n{path}", detail=str(exc)) from None
    if not os.access(p, os.W_OK):
        raise InvalidFileError(f"Cannot write to the folder:\n{p}")
    return p


# ---- secure temp files --------------------------------------------------------
class SecureTempDir:
    """Private (0700) temp directory that is always removed, even on errors."""

    def __init__(self, prefix: str = TEMP_PREFIX):
        self.path = Path(tempfile.mkdtemp(prefix=prefix))
        try:
            os.chmod(self.path, 0o700)
        except OSError:
            pass

    def file(self, suffix: str = "") -> Path:
        return self.path / f"{secrets.token_hex(6)}{suffix}"

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> "SecureTempDir":
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()


_TEMP_ROOT: Path | None = None


def temp_dir() -> Path:
    """Per-process private temp directory, removed at exit."""
    global _TEMP_ROOT
    if _TEMP_ROOT is None or not _TEMP_ROOT.exists():
        _TEMP_ROOT = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
        try:
            os.chmod(_TEMP_ROOT, 0o700)
        except OSError:
            pass
        atexit.register(cleanup_temp)
    return _TEMP_ROOT


def cleanup_temp() -> None:
    global _TEMP_ROOT
    if _TEMP_ROOT and _TEMP_ROOT.exists():
        shutil.rmtree(_TEMP_ROOT, ignore_errors=True)
    _TEMP_ROOT = None


def cleanup_stale_temp(max_age_hours: float = 0.0) -> int:
    """Remove leftover DocuCraft temp folders older than `max_age_hours`. Returns how many."""
    root = Path(tempfile.gettempdir())
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for d in root.glob(f"{TEMP_PREFIX}*"):
        try:
            if d.is_dir() and d != _TEMP_ROOT and d.stat().st_mtime <= cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


# ---- opening documents ----------------------------------------------------------
def open_pdf(path, password: str | None = None, *, any_extension: bool = False) -> pymupdf.Document:
    """Validate and open a PDF. `any_extension` is for our own temp files (.dctmp); content is still checked."""
    p = validate_input_file(path, extensions=None if any_extension else (".pdf",))
    try:
        doc = pymupdf.open(p)
    except Exception as exc:
        raise InvalidPdfError(f"'{p.name}' could not be opened. The file may be damaged or is not a valid PDF.",
                              detail=str(exc)) from None
    return _finish_open(doc, p.name, password)


def open_pdf_bytes(data: bytes, password: str | None = None, name: str = "document") -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise InvalidPdfError(f"'{name}' could not be opened.", detail=str(exc)) from None
    return _finish_open(doc, name, password)


def _finish_open(doc: pymupdf.Document, name: str, password: str | None) -> pymupdf.Document:
    if doc.needs_pass:
        if not password:
            doc.close()
            raise PasswordRequiredError(f"'{name}' is password protected.")
        if not doc.authenticate(password):
            doc.close()
            raise WrongPasswordError("The password is incorrect.")
    if not doc.is_pdf:
        doc.close()
        raise InvalidPdfError(f"'{name}' is not a PDF document.")
    if doc.page_count == 0:
        doc.close()
        raise InvalidPdfError(f"'{name}' contains no readable pages. The file is damaged or incomplete.")
    if doc.page_count > MAX_PAGES:
        n = doc.page_count
        doc.close()
        raise ResourceLimitError(f"'{name}' has {n:,} pages, above the {MAX_PAGES:,} page safety limit.")
    return doc


def is_encrypted(path) -> bool:
    p = validate_input_file(path)
    try:
        with pymupdf.open(str(p)) as d:
            return bool(d.needs_pass)
    except Exception:
        return False


def safe_zoom(page_rect: pymupdf.Rect, zoom: float) -> float:
    """Clamp a zoom so the rendered bitmap never exceeds MAX_RENDER_PIXELS."""
    w, h = max(page_rect.width, 1.0), max(page_rect.height, 1.0)
    if w > MAX_PAGE_POINTS or h > MAX_PAGE_POINTS:
        raise ResourceLimitError("This page is larger than the safe rendering limit.")
    return max(0.05, min(zoom, (MAX_RENDER_PIXELS / (w * h)) ** 0.5))


# ---- encryption / sanitising -----------------------------------------------------
def encrypt_pdf(src, dst, user_password: str, owner_password: str | None = None, src_password: str | None = None) -> Path:
    """Write an AES-256 encrypted copy of `src` to `dst` (never the same file)."""
    if not user_password:
        raise InvalidFileError("A password is required to protect a PDF.")
    dst = Path(dst)
    if dst.exists() and dst.resolve() == Path(src).resolve():
        raise InvalidFileError("Choose a different file name for the protected copy.")
    doc = open_pdf(src, src_password)
    tmp = dst.with_name(f".{dst.stem}.dctmp")
    try:
        watermark.stamp_pdf(doc)
        doc.save(tmp, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_password,
                 owner_pw=owner_password or user_password, garbage=3, deflate=True)
        os.replace(tmp, dst)
    finally:
        doc.close()
        tmp.unlink(missing_ok=True)
    return dst


def decrypt_pdf(src, dst, password: str) -> Path:
    dst = Path(dst)
    if dst.exists() and dst.resolve() == Path(src).resolve():
        raise InvalidFileError("Choose a different file name for the unprotected copy.")
    doc = open_pdf(src, password)
    tmp = dst.with_name(f".{dst.stem}.dctmp")
    try:
        watermark.stamp_pdf(doc)
        doc.save(tmp, encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
        os.replace(tmp, dst)
    finally:
        doc.close()
        tmp.unlink(missing_ok=True)
    return dst


def sanitize_document(doc: pymupdf.Document, *, metadata: bool = True, javascript: bool = True,
                      embedded_files: bool = True, hidden_text: bool = True, thumbnails: bool = True) -> None:
    """Remove metadata, JavaScript, attachments, hidden text and stale data, in place."""
    if metadata:
        doc.set_metadata({})
        try:
            doc.del_xml_metadata()
        except Exception:
            pass
    if embedded_files:
        for name in list(doc.embfile_names()):
            doc.embfile_del(name)
    doc.scrub(metadata=metadata, javascript=javascript, embedded_files=embedded_files,
              hidden_text=hidden_text, thumbnails=thumbnails, attached_files=embedded_files,
              redact_images=0, reset_fields=False, reset_responses=False, clean_pages=True,
              remove_links=False, xml_metadata=metadata)


def verify_redaction(path, terms: Iterable[str], password: str | None = None) -> list[str]:
    """Return the terms that can STILL be found by ordinary text extraction (empty list = clean)."""
    doc = open_pdf(path, password)
    try:
        blob = re.sub(r"\s+", " ", " ".join(p.get_text("text") for p in doc)).lower()
    finally:
        doc.close()
    squashed = re.sub(r"\s+", "", blob)
    left = []
    for term in terms:
        t = re.sub(r"\s+", " ", term).strip().lower()
        if t and (t in blob or re.sub(r"\s+", "", t) in squashed):
            left.append(term)
    return left
