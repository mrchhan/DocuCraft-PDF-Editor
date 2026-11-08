# Contributing

1. Fork, create a branch, `pip install -r requirements-dev.txt`.
2. Make your change **with a test** - `QT_QPA_PLATFORM=offscreen python -m pytest -q` must pass.
3. Keep `core/` and `converters/` free of Qt imports, and keep PDF-library calls out of `ui/` (go through `DocumentSession.edit(...)`).
4. Use only synthetic documents in tests and screenshots - never real or private files.
5. By contributing you agree your work is licensed AGPL-3.0-or-later.
