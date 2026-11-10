# Verification status (v0.1.5)

Honest record of what has been checked, where, and what has not.

## Verified (automated, Linux, Python 3.13, headless Qt)
- **120 tests pass**, including text replacement (font/size kept, neighbours intact, reflow): reader, editor (annotations, page ops, undo/redo incl. "back to saved state is clean", true redaction + verification, safe saving), organiser (merge/split/compress/extract), security (validation, passwords, encryption preserved), conversion (PDF->Word on text, tables, scans, columns, fonts, encrypted files), services/database, and offscreen GUI tests (viewer navigation/zoom/layouts/rotation, editing workflow through the document tab, main-window shell, tool panels producing real output files).
- **Packaged build (PyInstaller, Linux)** builds from `docucraft.spec`, its `--selftest` passes (render, redaction, text replacement, merge, PDF->Word, database) and the packaged GUI starts.
- **Packaged build on Windows (user-run):** the PyInstaller EXE passed its self-test (render, redact, merge, pdf_to_word, database). The `replace_text` check was added afterwards and has not been run on Windows.
- Branding: logo integrity, tamper rejection, PDF/Word/image watermark (idempotent, all four page rotations) are covered by `tests/test_branding.py`; the visual result was reviewed on rendered pages only, not in a real PDF viewer or on Windows.
- **Windows 10 (user-run, Python 3.12):** full build succeeded; the packaged EXE passed its self-test (render, redact, replace_text, branding, merge, pdf_to_word, database) and opened with the Shadow logo and contact footer. The test suite on Windows gave 112 passed, 1 skipped, 1 failed because `pypdf` was missing from `requirements-dev.txt` (fixed).
- Portfolio media (`marketing/media/`) is rendered from the real UI with a fictional document.
- Screenshots in `docs/screenshots/` are rendered from the real UI.

## NOT yet verified - needs a real Windows 10/11 machine
- [x] PyInstaller build on Windows (self-test passed)
- [ ] Inno Setup installer build (optional; the portable zip is the recommended download) (`python scripts/build_windows.py --installer`; Inno Setup was not installed on the test PC); CI workflow is written but has not run
- [ ] Installer install / launch / uninstall on a **clean** machine without Python
- [ ] PDF file association, shortcuts, per-user vs admin install
- [ ] OCR with a bundled Tesseract (`vendor/tesseract`) and Word->PDF with LibreOffice
- [ ] Print preview window opens, shows the pages, zooms and hands over to Print (File → Print preview…, Ctrl+Shift+P; **0.1.4's Qt preview crashed on the author's PC, 0.1.5 uses a custom one**); printing on a real printer; high-DPI and multi-monitor behaviour
- [ ] Antivirus / SmartScreen behaviour (the installer is unsigned)
- [ ] Performance on very large (500+ page / 100+ MB) real-world files and conversion quality on real-world documents

## Not claimed
No claim is made of 100% conversion accuracy, security certification, or commercial readiness. "Standalone / portable" should only be said once the packaged build has run on a clean Windows machine.

## Known gaps / roadmap
Cryptographic digital signatures, form-field designer, true in-place text editing, installer code signing, localisation beyond English, macOS/Linux packages.
