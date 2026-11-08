"""Export PDF pages as PNG / JPG."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from core import pdf_security as sec
from core import watermark
from core.errors import InvalidFileError
from core.pdf_organizer import Cancel, Progress, _tick, parse_page_ranges

DPI_CHOICES = (72, 96, 150, 200, 300, 600)


def pdf_to_images(src, out_dir, *, fmt: str = "png", dpi: int = 150, pages: str = "", password: str | None = None,
                  jpg_quality: int = 90, progress: Progress = None, cancel: Cancel = None) -> list[Path]:
    fmt = fmt.lower().replace("jpeg", "jpg")
    if fmt not in ("png", "jpg"):
        raise InvalidFileError("Choose PNG or JPG.")
    if not 36 <= dpi <= 1200:
        raise InvalidFileError("Resolution must be between 36 and 1200 DPI.")
    p = sec.validate_input_file(src)
    out_dir = sec.validate_output_dir(out_dir)
    doc = sec.open_pdf(p, password)
    out: list[Path] = []
    try:
        idx = parse_page_ranges(pages, doc.page_count) if pages.strip() else list(range(doc.page_count))
        width, stem = len(str(doc.page_count)), sec.sanitize_filename(p.stem)
        for n, i in enumerate(idx):
            _tick(progress, cancel, int(n / len(idx) * 100), f"Exporting page {i + 1}")
            page = doc[i]
            z = sec.safe_zoom(page.rect, dpi / 72)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
            dst = sec.unique_path(out_dir / f"{stem}_page_{str(i + 1).zfill(width)}.{fmt}")
            pix.save(dst) if fmt == "png" else pix.save(dst, jpg_quality=jpg_quality)
            watermark.stamp_image(dst)
            out.append(dst)
    finally:
        doc.close()
    _tick(progress, cancel, 100, "Done")
    return out
