"""Merge, split, compress and extract. Pure functions, no UI; progress and cancel via callbacks."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import pymupdf

from . import pdf_security as sec
from . import watermark
from .errors import InvalidFileError, OperationCancelled

Progress = Callable[[int, str], None] | None
Cancel = Callable[[], bool] | None


class CancelToken:
    def __init__(self):
        self._ev = threading.Event()

    def cancel(self) -> None:
        self._ev.set()

    def cancelled(self) -> bool:
        return self._ev.is_set()

    __call__ = cancelled

    def check(self) -> None:
        if self._ev.is_set():
            raise OperationCancelled()


def _tick(progress: Progress, cancel: Cancel, pct: int, msg: str) -> None:
    if cancel and cancel():
        raise OperationCancelled()
    if progress:
        progress(pct, msg)


def parse_page_ranges(spec: str, page_count: int) -> list[int]:
    """'1-3, 5, 8-' -> zero-based page list, in the order given."""
    if not spec or not spec.strip():
        raise InvalidFileError("Enter a page range such as 1-3, 5, 8-")
    pages: list[int] = []
    for part in re.split(r"[,;\s]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m and (m.group(1) or m.group(2)):
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else page_count
            rng = list(range(a, b + (1 if a <= b else -1), 1 if a <= b else -1))
        elif part.isdigit():
            rng = [int(part)]
        else:
            raise InvalidFileError(f"'{part}' is not a valid page or range.")
        for n in rng:
            if n < 1 or n > page_count:
                raise InvalidFileError(f"Page {n} is outside this document (1–{page_count}).")
            pages.append(n - 1)
    if not pages:
        raise InvalidFileError("No pages selected.")
    return pages


def _runs(pages: Sequence[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for p in pages:
        if runs and runs[-1][1] == p - 1:
            runs[-1] = (runs[-1][0], p)
        else:
            runs.append((p, p))
    return runs


def _save_new(doc, dst: Path, overwrite: bool, **opts) -> Path:
    if dst.exists() and not overwrite:
        dst = sec.unique_path(dst)
    tmp = dst.with_name(f".{dst.stem}.dctmp")
    try:
        watermark.stamp_pdf(doc)
        doc.save(tmp, **{"garbage": 3, "deflate": True, **opts})
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return dst


def merge_pdfs(files: Sequence, dst, passwords: dict | None = None, overwrite: bool = False,
               progress: Progress = None, cancel: Cancel = None) -> Path:
    if len(files) < 2:
        raise InvalidFileError("Select at least two PDF files to merge.")
    passwords = passwords or {}
    out = pymupdf.open()
    try:
        for n, f in enumerate(files):
            _tick(progress, cancel, int(n / len(files) * 90), f"Adding {Path(f).name}")
            src = sec.open_pdf(f, passwords.get(str(f)))
            try:
                out.insert_pdf(src)
            finally:
                src.close()
        _tick(progress, cancel, 95, "Saving merged file")
        result = _save_new(out, Path(dst), overwrite)
    finally:
        out.close()
    _tick(progress, cancel, 100, "Done")
    return result


def _split(src_path, outdir, groups, stem, password, progress, cancel) -> list[Path]:
    outdir = sec.validate_output_dir(outdir)
    src = sec.open_pdf(src_path, password)
    results: list[Path] = []
    try:
        for n, pages in enumerate(groups):
            _tick(progress, cancel, int(n / len(groups) * 100), f"Writing part {n + 1} of {len(groups)}")
            part = pymupdf.open()
            try:
                for a, b in _runs(pages):
                    part.insert_pdf(src, from_page=a, to_page=b)
                label = f"{pages[0] + 1}" if len(pages) == 1 else f"{pages[0] + 1}-{pages[-1] + 1}"
                results.append(_save_new(part, outdir / f"{stem}_pages_{label}.pdf", False))
            finally:
                part.close()
    finally:
        src.close()
    _tick(progress, cancel, 100, "Done")
    return results


def _count(p, password) -> int:
    d = sec.open_pdf(p, password)
    try:
        return d.page_count
    finally:
        d.close()


def split_pdf(src, outdir, mode: str = "ranges", *, ranges: str = "", group_size: int = 1,
              password: str | None = None, progress: Progress = None, cancel: Cancel = None) -> list[Path]:
    """mode: 'ranges' ('1-3, 4-6, 9' -> 3 files) | 'every' (one file per page) | 'groups' (N pages each)."""
    p = sec.validate_input_file(src)
    count = _count(p, password)
    stem = sec.sanitize_filename(p.stem)
    if mode == "ranges":
        groups = [parse_page_ranges(part, count) for part in ranges.split(",") if part.strip()]
        if not groups:
            raise InvalidFileError("Enter at least one page range.")
    elif mode == "every":
        groups = [[i] for i in range(count)]
    elif mode == "groups":
        if group_size < 1:
            raise InvalidFileError("Group size must be at least 1.")
        groups = [list(range(i, min(i + group_size, count))) for i in range(0, count, group_size)]
    else:
        raise InvalidFileError(f"Unknown split mode '{mode}'.")
    return _split(p, outdir, groups, stem, password, progress, cancel)


@dataclass
class CompressResult:
    output: Path
    original_size: int
    new_size: int
    level: str
    kept_original_size: bool = False

    @property
    def saved_percent(self) -> float:
        return 0.0 if not self.original_size else (1 - self.new_size / self.original_size) * 100


COMPRESS_LEVELS = {"low": None, "balanced": (170, 130, 72), "high": (110, 80, 50)}


def compress_pdf(src, dst, level: str = "balanced", password: str | None = None, overwrite: bool = False,
                 progress: Progress = None, cancel: Cancel = None) -> CompressResult:
    """low = lossless structural clean-up; balanced/high also downsample and recompress images."""
    if level not in COMPRESS_LEVELS:
        raise InvalidFileError(f"Unknown compression level '{level}'.")
    p = sec.validate_input_file(src)
    original = p.stat().st_size
    doc = sec.open_pdf(p, password)
    try:
        _tick(progress, cancel, 10, "Analysing document")
        opts = COMPRESS_LEVELS[level]
        if opts:
            _tick(progress, cancel, 25, "Recompressing images")
            thr, target, quality = opts
            doc.rewrite_images(dpi_threshold=thr, dpi_target=target, quality=quality)
            try:
                doc.subset_fonts()
            except Exception:
                pass
        _tick(progress, cancel, 70, "Optimising structure")
        written = _save_new(doc, Path(dst), overwrite, garbage=4 if level != "low" else 3, deflate=True,
                            deflate_images=True, deflate_fonts=True, clean=True)
    finally:
        doc.close()
    new, kept = written.stat().st_size, False
    if new >= original:                                  # never hand back a bigger file
        shutil.copyfile(p, written)
        new, kept = original, True
    _tick(progress, cancel, 100, "Done")
    return CompressResult(written, original, new, level, kept)


def extract_pages(src, dst, pages_spec: str, password: str | None = None) -> Path:
    p = sec.validate_input_file(src)
    d = sec.open_pdf(p, password)
    try:
        pages = parse_page_ranges(pages_spec, d.page_count)
        new = pymupdf.open()
        try:
            for a, b in _runs(pages):
                new.insert_pdf(d, from_page=a, to_page=b)
            return _save_new(new, Path(dst), False)
        finally:
            new.close()
    finally:
        d.close()


def extract_text(src, dst, password: str | None = None, pages_spec: str | None = None,
                 progress: Progress = None, cancel: Cancel = None) -> Path:
    p = sec.validate_input_file(src)
    doc = sec.open_pdf(p, password)
    try:
        pages = parse_page_ranges(pages_spec, doc.page_count) if pages_spec else list(range(doc.page_count))
        parts = []
        for n, i in enumerate(pages):
            _tick(progress, cancel, int(n / len(pages) * 100), f"Page {i + 1}")
            parts.append(f"--- Page {i + 1} ---\n{doc[i].get_text('text', sort=True)}")
    finally:
        doc.close()
    out = sec.unique_path(Path(dst))
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def extract_images(src, outdir, password: str | None = None, min_size: int = 32,
                   progress: Progress = None, cancel: Cancel = None) -> list[Path]:
    p = sec.validate_input_file(src)
    outdir = sec.validate_output_dir(outdir)
    doc = sec.open_pdf(p, password)
    saved: list[Path] = []
    seen: set[int] = set()
    try:
        for i, page in enumerate(doc):
            _tick(progress, cancel, int(i / doc.page_count * 100), f"Page {i + 1}")
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen:
                    continue
                seen.add(xref)
                try:
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                if not info or info["width"] < min_size or info["height"] < min_size:
                    continue
                out = sec.unique_path(outdir / f"{sec.sanitize_filename(p.stem)}_p{i + 1}_{xref}.{info['ext']}")
                out.write_bytes(info["image"])
                saved.append(out)
    finally:
        doc.close()
    _tick(progress, cancel, 100, "Done")
    return saved


def export_metadata(src, dst, password: str | None = None) -> Path:
    p = sec.validate_input_file(src)
    doc = sec.open_pdf(p, password)
    try:
        data = {"file": p.name, "size_bytes": p.stat().st_size, "pages": doc.page_count, "encrypted": doc.is_encrypted,
                "metadata": doc.metadata,
                "bookmarks": [{"level": l, "title": t, "page": pg} for l, t, pg in doc.get_toc(simple=True)],
                "page_sizes_pt": sorted({(round(pg.rect.width), round(pg.rect.height)) for pg in doc})}
    finally:
        doc.close()
    out = sec.unique_path(Path(dst))
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
