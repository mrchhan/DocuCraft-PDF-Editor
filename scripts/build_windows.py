"""Build DocuCraft for Windows: tests -> PyInstaller -> (optional) Inno Setup installer.

    python scripts/build_windows.py [--skip-tests] [--installer]

Output: dist/DocuCraft/DocuCraft.exe (folder build) and, with --installer, dist/installer/DocuCraft-Setup-<version>.exe
Run this on Windows 10/11. It does not claim the result works until you have tested it on a clean machine.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], **kw) -> None:
    print(">", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def version() -> str:
    return re.search(r'APP_VERSION\s*=\s*"([^"]+)"', (ROOT / "app" / "settings.py").read_text()).group(1)


def find_iscc():
    """Look for ISCC.exe of Inno Setup 6 or 7, installed for all users or for the current user."""
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for root in filter(None, roots):
        for base in (Path(root), Path(root) / "Programs"):
            for d in sorted(base.glob("Inno Setup *"), reverse=True):      # newest version first
                if (d / "ISCC.exe").exists():
                    return str(d / "ISCC.exe")
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--installer", action="store_true", help="also build the Inno Setup installer (needs ISCC.exe)")
    a = ap.parse_args()
    if not a.skip_tests:
        run([sys.executable, "-m", "pytest", "-q", "tests"])
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    shutil.rmtree(ROOT / "dist" / "DocuCraft", ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "docucraft.spec", "--noconfirm", "--clean"])
    exe = ROOT / "dist" / "DocuCraft" / ("DocuCraft.exe" if sys.platform.startswith("win") else "DocuCraft")
    if not exe.exists():
        sys.exit("Build failed: executable not found.")
    report = ROOT / "build" / "selftest.txt"
    report.parent.mkdir(exist_ok=True)
    report.unlink(missing_ok=True)
    env = None if sys.platform.startswith("win") else {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    # the packaged app runs its real engines (render, redact, merge, PDF->Word, database) and reports PASS/FAIL per check
    rc = subprocess.run([str(exe), "--selftest", "--selftest-out", str(report)], cwd=ROOT, env=env).returncode
    text = report.read_text(encoding="utf-8") if report.exists() else "(no report written)"
    print(text)
    if rc != 0 or "FAIL" in text:
        sys.exit("Packaged self-test FAILED - do not ship this build.")
    print("Packaged self-test passed:", exe)
    # portable download: the whole app folder in one zip (no installer needed; unzip anywhere and run DocuCraft.exe)
    zip_base = ROOT / "dist" / f"DocuCraft-{version()}-windows-portable"
    shutil.make_archive(str(zip_base), "zip", ROOT / "dist", "DocuCraft")
    print("Portable zip written to", f"{zip_base}.zip")
    if a.installer:
        iscc = shutil.which("ISCC") or find_iscc()
        if not iscc:
            sys.exit("Inno Setup (ISCC.exe) not found. Install Inno Setup 6 or 7 from https://jrsoftware.org/isdl.php")
        run([iscc, f"/DAppVersion={version()}", "installer/DocuCraft.iss"])
        print("Installer written to dist/installer/")


if __name__ == "__main__":
    main()
