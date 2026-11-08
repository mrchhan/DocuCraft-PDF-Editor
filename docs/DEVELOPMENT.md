# Development and architecture

```
core/        PDF engine - reader, editor, security, organiser, annotations   (no Qt)
converters/  PDF->Word, Word->PDF, OCR, images                               (no Qt)
services/    history, files, logging, crash recovery
database/    SQLite (settings, recent, favourites, conversions)
app/         AppContext, DocumentSession, JobManager, theme, icons, main window
ui/          components (PdfView, DocumentTab, panels), dialogs, pages
tests/       pytest suites (engine + offscreen GUI)
scripts/     build_windows.py, make_branding.py (logo, icon, embedded branding), make_screenshots.py, make_portfolio_media.py, compose_portfolio.py
```

**Rules:** `core/` and `converters/` never import Qt. The UI never calls PDF libraries directly - it goes through `DocumentSession.edit(method, ...)` -> `PdfEditor`, which gives undo/redo, dirty tracking and recovery for free. Long work runs through `JobManager` (background thread, progress, cancel). Saves are atomic (temp file then replace) with a backup.

**Run tests:** `QT_QPA_PLATFORM=offscreen python -m pytest -q` (synthetic documents only).
**Self-test a build:** `DocuCraft --selftest --selftest-out report.txt` runs the real engines and prints PASS/FAIL per check.
**Screenshots and video:** `python scripts/make_portfolio_media.py <frames>` then `python scripts/compose_portfolio.py <frames>` (needs ffmpeg).
