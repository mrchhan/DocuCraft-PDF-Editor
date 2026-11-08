"""DocuCraft entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make `python main.py` work from any directory (and inside a PyInstaller bundle).
sys.path.insert(0, str(Path(__file__).resolve().parent))


def selftest() -> int:
    """Exercise the real engines headlessly (used to verify a packaged build). Prints one line per check."""
    import tempfile
    import traceback

    import pymupdf

    tmp = Path(tempfile.mkdtemp(prefix="dc_selftest_"))
    os.environ["DOCUCRAFT_HOME"] = str(tmp / "home")
    results: list[tuple[str, bool, str]] = []

    def check(name, fn):
        try:
            fn()
            results.append((name, True, ""))
        except Exception as exc:                                     # noqa: BLE001
            results.append((name, False, f"{exc}\n{traceback.format_exc()}"))

    src = tmp / "in.pdf"
    d = pymupdf.open()
    for i in range(3):
        d.new_page().insert_text((72, 100), f"Selftest page {i + 1} SECRET-TOKEN", fontsize=14)
    d.save(src)
    d.close()

    def t_render():
        from core.pdf_reader import PdfReader
        r = PdfReader(src)
        assert r.page_count == 3 and r.render(0, 1.0).width > 0
        r.close()

    def t_redact():
        from core.pdf_editor import PdfEditor
        from core.pdf_reader import PdfReader
        ed = PdfEditor(PdfReader(src))
        ed.redact_text(["SECRET-TOKEN"])
        out = ed.save_as(tmp / "red.pdf")
        with pymupdf.open(out) as r:
            assert all("SECRET-TOKEN" not in p.get_text() for p in r)

    def t_replace():
        from core import fonts
        from core.pdf_editor import PdfEditor
        from core.pdf_reader import PdfReader
        assert any(fonts.find_font_file(n, False, False) for n in ("Inter", "LiberationSans")), "bundled fonts missing"
        ed = PdfEditor(PdfReader(src))
        w = [w for w in ed.reader.doc[0].get_text("words") if w[4] == "Selftest"][0]
        ed.replace_text(0, pymupdf.Rect(w[:4]), "Retest")
        t = ed.reader.page_text(0)
        assert "Retest" in t and "Selftest page 1" not in t

    def t_brand():
        from core import branding, watermark
        assert branding.verify()
        doc = pymupdf.open(src)
        assert watermark.stamp_pdf(doc) == 3 and branding.STAMP_TEXT in doc[0].get_text()
        doc.close()

    def t_merge():
        from core.pdf_organizer import merge_pdfs
        out = merge_pdfs([src, src], tmp / "m.pdf")
        with pymupdf.open(out) as r:
            assert r.page_count == 6

    def t_word():
        import docx

        from converters.pdf_to_word import ConversionOptions, convert_pdf_to_word
        rep = convert_pdf_to_word(src, tmp, ConversionOptions(), lambda *a: None, None)
        assert rep.success, rep.error
        assert "Selftest" in "\n".join(p.text for p in docx.Document(rep.output).paragraphs)

    def t_db():
        from app.context import AppContext
        ctx = AppContext()
        ctx.history.add_recent(src)
        assert ctx.history.recent()
        ctx.db.close()

    for name, fn in (("render", t_render), ("redact", t_redact), ("replace_text", t_replace), ("branding", t_brand), ("merge", t_merge), ("pdf_to_word", t_word), ("database", t_db)):
        check(name, fn)
    lines = [("PASS " if ok else "FAIL ") + name + ("" if ok else "\n" + err) for name, ok, err in results]
    report = "\n".join(lines) + "\n"
    if "--selftest-out" in sys.argv:                               # a windowed exe has no console: write a file
        Path(sys.argv[sys.argv.index("--selftest-out") + 1]).write_text(report, encoding="utf-8")
    print(report)
    return 0 if all(ok for _, ok, _ in results) else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    for stream in ("stdout", "stderr"):                            # windowed (no console) builds have no std streams
        if getattr(sys, stream) is None:
            setattr(sys, stream, open(os.devnull, "w"))
    if "--selftest" in argv:
        return selftest()
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    from app import theme
    from app.context import AppContext
    from app.main_window import MainWindow
    from app.settings import APP_NAME, APP_VERSION
    from services import logging_service

    log = logging_service.setup_logging()
    log.info("Starting %s %s", APP_NAME, APP_VERSION)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Shadow Creative Studio")
    ctx = AppContext()
    theme.apply_theme(app, str(ctx.settings.get("theme")), int(ctx.settings.get("ui_scale")))
    win = MainWindow(ctx, app)
    win._apply_theme()
    win.show()

    files = [a for a in argv[1:] if a.lower().endswith(".pdf") and Path(a).exists()]
    smoke = "--smoke-test" in argv

    def after_show() -> None:
        win.check_recovery()
        win.restore_session()
        for f in files:
            win.open_path(f)
        if smoke:
            QTimer.singleShot(400, app.quit)

    QTimer.singleShot(0, after_show)
    code = app.exec()
    ctx.db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
