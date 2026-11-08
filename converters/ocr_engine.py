"""OCR through the Tesseract command-line program (Apache-2.0), fully offline.

Tesseract is an external dependency: detected at runtime and bundled by the Windows installer
build. Language packs are plain `<lang>.traineddata` files, so adding Urdu (`urd`) or any other
language later needs no code change.
"""
from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from core.errors import ConversionError, DependencyMissingError, OperationCancelled
from core.fonts import is_latin1, unicode_font_file

_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0
INSTALL_HINT = ("Tesseract OCR was not found. Reinstall DocuCraft with the OCR component selected, or install "
                "Tesseract (https://github.com/UB-Mannheim/tesseract/wiki) and restart DocuCraft.")
LANGUAGE_NAMES = {"eng": "English", "urd": "Urdu", "ara": "Arabic", "hin": "Hindi", "fra": "French", "deu": "German",
                  "spa": "Spanish", "ita": "Italian", "por": "Portuguese", "rus": "Russian", "tur": "Turkish",
                  "chi_sim": "Chinese (Simplified)", "chi_tra": "Chinese (Traditional)", "jpn": "Japanese",
                  "kor": "Korean", "nld": "Dutch", "pol": "Polish", "ind": "Indonesian", "vie": "Vietnamese",
                  "tha": "Thai", "heb": "Hebrew"}


def _app_dirs() -> list[Path]:
    d = []
    if getattr(sys, "frozen", False):
        d += [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent]
    d.append(Path(__file__).resolve().parents[1])
    return d


def find_tesseract() -> Path | None:
    env = os.environ.get("DOCUCRAFT_TESSERACT")
    if env and Path(env).exists():
        return Path(env)
    exe = "tesseract.exe" if sys.platform.startswith("win") else "tesseract"
    for d in _app_dirs():
        if (d / "tesseract" / exe).exists():
            return d / "tesseract" / exe
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base and (Path(base) / "Tesseract-OCR" / exe).exists():
            return Path(base) / "Tesseract-OCR" / exe
    return None


def _env() -> dict[str, str]:
    env = dict(os.environ)
    exe = find_tesseract()
    if exe and (exe.parent / "tessdata").is_dir():
        env["TESSDATA_PREFIX"] = str(exe.parent / "tessdata")
    return env


def is_available() -> bool:
    return find_tesseract() is not None


def available_languages() -> list[str]:
    exe = find_tesseract()
    if not exe:
        return []
    try:
        out = subprocess.run([str(exe), "--list-langs"], capture_output=True, text=True, timeout=30, env=_env(),
                             creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [l.strip() for l in out.splitlines()[1:] if l.strip() and l.strip() != "osd"]


@dataclass
class OcrWord:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float


@dataclass
class OcrLine:
    words: list[OcrWord] = field(default_factory=list)
    block: int = 0
    par: int = 0

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def bbox(self):
        return (min(w.x0 for w in self.words), min(w.y0 for w in self.words),
                max(w.x1 for w in self.words), max(w.y1 for w in self.words))

    @property
    def height(self) -> float:
        b = self.bbox
        return b[3] - b[1]


@dataclass
class OcrPage:
    lines: list[OcrLine]
    width: float
    height: float

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    def paragraphs(self) -> list[list[OcrLine]]:
        out, key = [], None
        for l in self.lines:
            if (l.block, l.par) != key:
                out.append([])
                key = (l.block, l.par)
            out[-1].append(l)
        return out


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    exe = find_tesseract()
    if not exe:
        raise DependencyMissingError(INSTALL_HINT)
    try:
        return subprocess.run([str(exe), *args], capture_output=True, timeout=timeout, env=_env(), creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise ConversionError("OCR took too long on this page and was stopped.") from None
    except OSError as exc:
        raise DependencyMissingError(INSTALL_HINT, detail=str(exc)) from None


def ocr_pixmap(pix: pymupdf.Pixmap, lang: str = "eng", min_conf: float = 30.0, psm: int = 3, timeout: int = 180) -> OcrPage:
    """OCR a rendered page image; coordinates are in image pixels."""
    if not is_available():
        raise DependencyMissingError(INSTALL_HINT)
    langs = set(available_languages())
    for l in [x for x in lang.split("+") if x]:
        if langs and l not in langs:
            raise DependencyMissingError(f"The OCR language pack '{l}' is not installed.")
    with tempfile.TemporaryDirectory(prefix="docucraft_ocr_") as tmp:
        img = Path(tmp) / "page.png"
        pix.save(img)
        proc = _run([str(img), "stdout", "-l", lang, "--psm", str(psm), "tsv"], timeout)
    if proc.returncode != 0:
        raise ConversionError("OCR failed.", detail=proc.stderr.decode("utf-8", "replace")[:500])
    rows = csv.DictReader(io.StringIO(proc.stdout.decode("utf-8", "replace")), delimiter="\t", quoting=csv.QUOTE_NONE)
    lines: dict[tuple, OcrLine] = {}
    for r in rows:
        text = (r.get("text") or "").strip()
        try:
            conf = float(r["conf"])
        except (KeyError, ValueError, TypeError):
            continue
        if not text or conf < min_conf or r.get("level") != "5":
            continue
        key = (int(r["block_num"]), int(r["par_num"]), int(r["line_num"]))
        x, y, w, h = (float(r[k]) for k in ("left", "top", "width", "height"))
        lines.setdefault(key, OcrLine(block=key[0], par=key[1])).words.append(OcrWord(text, x, y, x + w, y + h, conf))
    return OcrPage([lines[k] for k in sorted(lines)], pix.width, pix.height)


def ocr_document_page(doc: pymupdf.Document, index: int, lang: str = "eng", dpi: int = 300) -> OcrPage:
    """OCR one page; returned coordinates are converted to PDF points."""
    page = doc[index]
    res = ocr_pixmap(page.get_pixmap(dpi=dpi, alpha=False, annots=False), lang)
    k = 72.0 / dpi
    for line in res.lines:
        for w in line.words:
            w.x0, w.y0, w.x1, w.y1 = w.x0 * k, w.y0 * k, w.x1 * k, w.y1 * k
    res.width, res.height = page.rect.width, page.rect.height
    return res


def _fit_size(font, text, width, height) -> float:
    natural = font.text_length(text, fontsize=1) or 1.0
    return max(2.0, min(height * 0.9, width / natural))


def _fonts(page):
    helv, path = pymupdf.Font("helv"), unicode_font_file()
    uni = pymupdf.Font(fontfile=path) if path else None
    if path:
        page.insert_font(fontname="dcuni", fontfile=path)
    return helv, uni


def add_invisible_text_layer(page: pymupdf.Page, ocr: OcrPage) -> int:
    """Make a scanned page searchable/selectable with an invisible text layer. Returns the word count."""
    helv, uni = _fonts(page)
    n = 0
    for line in ocr.lines:
        for w in line.words:
            font, name = (helv, "helv") if (is_latin1(w.text) or not uni) else (uni, "dcuni")
            size = _fit_size(font, w.text, w.x1 - w.x0, w.y1 - w.y0)
            page.insert_text(pymupdf.Point(w.x0, w.y1 - (w.y1 - w.y0) * 0.2), w.text, fontsize=size, fontname=name,
                             render_mode=3)
            n += 1
    return n


def make_searchable_pdf(doc: pymupdf.Document, pages=None, lang: str = "eng", progress=None, cancel=None) -> int:
    """Add an OCR text layer, in place, to the given pages. Returns the number processed."""
    targets = pages if pages is not None else list(range(doc.page_count))
    for n, i in enumerate(targets):
        if cancel and cancel():
            raise OperationCancelled()
        if progress:
            progress(int(n / max(1, len(targets)) * 100), f"OCR page {i + 1}")
        add_invisible_text_layer(doc[i], ocr_document_page(doc, i, lang))
    return len(targets)


def text_only_page(doc: pymupdf.Document, pno: int, ocr: OcrPage, width: float, height: float) -> None:
    """Insert a visible text-only page (feeds OCR results to the layout converter)."""
    page = doc.new_page(pno=pno, width=width, height=height)
    helv, uni = _fonts(page)
    for line in ocr.lines:
        text = line.text
        font, name = (helv, "helv") if (is_latin1(text) or not uni) else (uni, "dcuni")
        x0, y0, x1, y1 = line.bbox
        page.insert_text(pymupdf.Point(x0, y1 - (y1 - y0) * 0.2), text, fontsize=_fit_size(font, text, x1 - x0, y1 - y0) * 1.05,
                         fontname=name)
