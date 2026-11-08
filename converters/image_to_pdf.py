"""Combine JPG / JPEG / PNG (also BMP, GIF, TIFF, WebP) images into one PDF."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pymupdf
from PIL import Image, ImageOps

from core import pdf_security as sec
from core.errors import InvalidFileError
from core.pdf_organizer import Cancel, Progress, _save_new, _tick

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp")
PAGE_SIZES = {"A4": (595.28, 841.89), "A5": (419.53, 595.28), "Letter": (612.0, 792.0), "Legal": (612.0, 1008.0)}
Image.MAX_IMAGE_PIXELS = 120_000_000           # decompression-bomb guard


def images_to_pdf(images: Sequence, dst, *, page_size: str = "A4", orientation: str = "auto", margin_mm: float = 10.0,
                  overwrite: bool = False, progress: Progress = None, cancel: Cancel = None) -> Path:
    """page_size: A4/A5/Letter/Legal or 'Fit'. orientation: auto/portrait/landscape."""
    if not images:
        raise InvalidFileError("Add at least one image.")
    if page_size not in PAGE_SIZES and page_size != "Fit":
        raise InvalidFileError(f"Unknown page size '{page_size}'.")
    margin = max(0.0, margin_mm) / 25.4 * 72
    out = pymupdf.open()
    try:
        with sec.SecureTempDir() as tmp:
            for n, f in enumerate(images):
                _tick(progress, cancel, int(n / len(images) * 95), f"Adding {Path(f).name}")
                p = sec.validate_input_file(f, extensions=IMAGE_EXTS, max_bytes=300 * 1024 * 1024)
                try:
                    with Image.open(p) as im:
                        fixed = ImageOps.exif_transpose(im)
                        w_px, h_px = fixed.size
                        use = p
                        if p.suffix.lower() not in (".jpg", ".jpeg", ".png") or fixed is not im \
                                or fixed.mode not in ("RGB", "L", "RGBA"):
                            use = tmp.file(".png")
                            fixed.convert("RGBA" if "A" in fixed.mode else "RGB").save(use)
                except (Image.DecompressionBombError, Image.UnidentifiedImageError, OSError) as exc:
                    raise InvalidFileError(f"'{p.name}' is not a readable image.", detail=str(exc)) from None
                if page_size == "Fit":
                    page = out.new_page(width=w_px * 72 / 96, height=h_px * 72 / 96)
                    page.insert_image(page.rect, filename=str(use))
                    continue
                pw, ph = PAGE_SIZES[page_size]
                if (w_px > h_px) if orientation == "auto" else orientation == "landscape":
                    pw, ph = ph, pw
                page = out.new_page(width=pw, height=ph)
                page.insert_image(pymupdf.Rect(margin, margin, pw - margin, ph - margin), filename=str(use),
                                  keep_proportion=True)
            _tick(progress, cancel, 97, "Saving")
            result = _save_new(out, Path(dst), overwrite)
    finally:
        out.close()
    _tick(progress, cancel, 100, "Done")
    return result
