"""Word -> PDF through a locally installed LibreOffice in headless mode (offline)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Sequence

from core import pdf_security as sec
from core.errors import ConversionError, DependencyMissingError, InvalidFileError, OperationCancelled
from core.pdf_organizer import Cancel, Progress, _tick

WORD_EXTS = (".docx", ".doc", ".odt", ".rtf")
TIMEOUT_SECONDS = 240
INSTALL_HINT = ("Word to PDF conversion needs LibreOffice (free, offline). Install it from "
                "https://www.libreoffice.org/download and restart DocuCraft.")
_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0


def find_libreoffice() -> Path | None:
    env = os.environ.get("DOCUCRAFT_SOFFICE")
    if env and Path(env).exists():
        return Path(env)
    for name in ("soffice", "libreoffice", "soffice.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    cands = [Path(b) / "LibreOffice" / "program" / "soffice.exe"
             for b in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")) if b]
    cands.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    return next((c for c in cands if c.exists()), None)


def is_available() -> bool:
    return find_libreoffice() is not None


def _check_content(p: Path) -> None:
    """LibreOffice would happily open plain text renamed to .docx, so verify the real format."""
    with p.open("rb") as fh:
        head = fh.read(8)
    ext = p.suffix.lower()
    ok = {".docx": zipfile.is_zipfile(p), ".odt": zipfile.is_zipfile(p),
          ".doc": head.startswith(b"\xd0\xcf\x11\xe0"), ".rtf": head.startswith(b"{\\rtf")}[ext]
    if not ok:
        raise InvalidFileError(f"'{p.name}' is not a valid {ext.lstrip('.').upper()} document.")


def convert_docx_to_pdf(src, out_dir=None, overwrite: bool = False, timeout: int = TIMEOUT_SECONDS,
                        cancel: Cancel = None) -> Path:
    exe = find_libreoffice()
    if not exe:
        raise DependencyMissingError(INSTALL_HINT)
    p = sec.validate_input_file(src, extensions=WORD_EXTS, max_bytes=500 * 1024 * 1024)
    _check_content(p)
    out_dir = sec.validate_output_dir(out_dir or p.parent)
    with tempfile.TemporaryDirectory(prefix=sec.TEMP_PREFIX + "lo_") as tmp:
        tmp = Path(tmp)
        produced = tmp / "out"
        produced.mkdir()
        cmd = [str(exe), f"-env:UserInstallation={(tmp / 'profile').as_uri()}", "--headless", "--norestore",
               "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(produced), str(p)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
        waited = 0.0
        while True:
            try:
                proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                waited += 0.5
                if cancel and cancel():
                    proc.kill()
                    raise OperationCancelled() from None
                if waited > timeout:
                    proc.kill()
                    raise ConversionError(f"LibreOffice did not finish converting '{p.name}' in time.") from None
        result = produced / (p.stem + ".pdf")
        if proc.returncode != 0 or not result.exists():
            err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")[:500]
            raise ConversionError(f"'{p.name}' could not be converted. It may be damaged or password-protected.", detail=err)
        dst = out_dir / (sec.sanitize_filename(p.stem) + ".pdf")
        if dst.exists() and not overwrite:
            dst = sec.unique_path(dst)
        shutil.move(str(result), dst)
    return dst


convert_to_pdf = convert_docx_to_pdf


def convert_batch(sources: Sequence, out_dir=None, overwrite: bool = False, progress: Progress = None,
                  cancel: Cancel = None) -> tuple[list[Path], list[tuple[str, str]]]:
    """Returns (outputs, failures[(name, reason)]). One bad file never stops the batch."""
    outputs, failures = [], []
    for n, f in enumerate(sources):
        _tick(progress, cancel, int(n / len(sources) * 100), f"Converting {Path(f).name}")
        try:
            outputs.append(convert_docx_to_pdf(f, out_dir, overwrite, cancel=cancel))
        except OperationCancelled:
            raise
        except (InvalidFileError, ConversionError) as exc:
            failures.append((Path(f).name, exc.user_message))
    _tick(progress, cancel, 100, "Done")
    return outputs, failures


batch_convert = convert_batch
