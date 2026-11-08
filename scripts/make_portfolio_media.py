"""Capture portfolio frames from the REAL DocuCraft UI (offscreen) using a synthetic demo document.

    python scripts/make_portfolio_media.py <frames_dir>

Writes numbered PNGs (the app window, dialogs and before/after crops). The video / images are composed from these.
Nothing here uses private data: the demo document is generated and fictional.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402

FONTS = ROOT / "assets" / "fonts"
INK, MUTED, ACCENT = (0.11, 0.13, 0.2), (0.4, 0.43, 0.5), (0.15, 0.39, 0.92)


def build_demo(path: Path) -> None:
    """A fictional 4-page design-style report: tinted pages, Inter text (embedded subset), cards, a bookmark outline."""
    d = pymupdf.open()
    titles = ["Hiring Plan", "Content Strategy", "Budget Overview", "Timeline"]
    for n, title in enumerate(titles, 1):
        pg = d.new_page(width=595, height=842)
        pg.draw_rect(pg.rect, color=None, fill=(0.973, 0.961, 0.925))
        pg.insert_font(fontname="in", fontfile=str(FONTS / "Inter-Regular.otf"))
        pg.insert_font(fontname="inb", fontfile=str(FONTS / "Inter-Bold.otf"))
        pg.insert_text((48, 58), f"NORTHWIND STUDIO  ·  Q3 REPORT  ·  {n}/4", fontname="inb", fontsize=8, color=ACCENT)
        pg.insert_text((48, 108), title, fontname="inb", fontsize=30, color=INK)
        y = 150
        for ln in ("A practical plan to attract strong candidates and keep every",
                   "step transparent. Review the draft report before the deadline",
                   "and confirm the budget with the finance team this week.",
                   "All figures in this demonstration document are fictional."):
            pg.insert_text((48, y), ln, fontname="in", fontsize=12, color=INK)
            y += 18.5
        for i, (head, body) in enumerate((("Outreach", "Job posts, referrals and partner boards"),
                                         ("Screening", "Short call, skills task, team interview"),
                                         ("Onboarding", "Welcome pack and a 30-60-90 day plan"))):
            top = 262 + i * 92
            pg.draw_rect(pymupdf.Rect(48, top, 547, top + 76), color=(0.88, 0.85, 0.78), fill=(1, 1, 1), radius=0.08, width=0.8)
            pg.insert_text((68, top + 30), head, fontname="inb", fontsize=13, color=INK)
            pg.insert_text((68, top + 52), body, fontname="in", fontsize=11, color=MUTED)
        pg.insert_text((48, 590), "Client reference: 4417-2290-8811  ·  Contact: alice@example.com", fontname="in", fontsize=11, color=INK)
        pg.insert_text((48, 800), "Northwind Studio  ·  fictional demo content", fontname="in", fontsize=8, color=MUTED)
    d.subset_fonts()
    d.set_toc([[1, t, i + 1] for i, t in enumerate(titles)])
    d.set_metadata({"title": "Northwind Studio Q3 Report (demo)", "author": "DocuCraft demo"})
    d.save(path)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "marketing" / "media" / "frames"
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="dc_media_"))
    os.environ["DOCUCRAFT_HOME"] = str(work / "home")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from app import theme
    from app.context import AppContext
    from app.main_window import MainWindow
    from converters.pdf_to_word import ConversionOptions, convert_pdf_to_word
    from ui.dialogs.dialogs import ReportDialog, ReplaceTextDialog

    app = QApplication([])
    ctx = AppContext()
    ctx.settings.set("theme", "light")
    theme.apply_theme(app, "light", 100)
    pdf = work / "Q3 Report.pdf"
    build_demo(pdf)
    ctx.history.add_recent(pdf)
    ctx.history.add_recent(work / "Q3 Report.pdf")
    win = MainWindow(ctx, app)
    win._apply_theme()
    win.resize(1600, 900)
    win.show()

    def settle(ms: int = 250) -> None:
        QTest.qWait(ms)
        for _ in range(4):
            app.processEvents()

    def snap(name: str, widget=None) -> None:
        settle()
        (widget or win).grab().save(str(out / name))
        print("frame", name)

    # 01 home
    snap("01-home.png")
    # 02 reader (thumbnails + bookmarks)
    tab = win.open_path(str(pdf))
    tab.view.go_to_page(0)
    tab.side.setCurrentIndex(1)
    snap("02-reader-bookmarks.png")
    tab.side.setCurrentIndex(0)
    # 03 search
    tab.find.open_bar("budget")
    settle(700)
    snap("03-search.png")
    tab.find.close_bar()
    # 04 annotations
    win.section("edit")
    pg = tab.session.reader.doc[0]
    tab._tool_done("highlight", 0, [tuple(r) for r in pg.search_for("strong candidates")])
    tab._tool_done("rect", 0, (44, 255, 551, 346))
    tab._tool_done("arrow", 0, ((470, 560), (400, 612)))
    tab.view.fit_page()
    snap("04-annotate.png")
    # 05 replace text: dialog + before/after crops
    w = [w for w in tab.session.reader.doc[0].get_text("words") if w[4] == "draft"][0]
    rect = pymupdf.Rect(w[0] - 3, w[1] - 2, w[2] + 3, w[3] + 7)           # a deliberately sloppy selection
    clip = pymupdf.Rect(36, 138, 400, 196)      # the paragraph lines around the changed word
    before = tab.session.reader.doc[0].get_pixmap(matrix=pymupdf.Matrix(4, 4), clip=clip)
    before.save(str(out / "replace-before.png"))
    dlg = ReplaceTextDialog(win, tab.session, 0, rect)
    dlg.resize(620, 560)
    dlg.new_text.setPlainText("final")
    dlg.preview()
    dlg.show()
    snap("05-replace-dialog.png", dlg)
    dlg.close()
    tab._edit("replace_text", 0, rect, "final", dlg.current_style())
    after = tab.session.reader.doc[0].get_pixmap(matrix=pymupdf.Matrix(4, 4), clip=clip)
    after.save(str(out / "replace-after.png"))
    tab.view.go_to_page(0)
    snap("06-after-replace.png")
    # 07 redaction
    ref = tab.session.reader.doc[0].search_for("4417-2290-8811")[0]
    tab._edit("redact_regions", [(0, tuple(ref))])
    tab.view.fit_page()
    snap("07-redacted.png")
    tab.view.fit_width()
    # 08 convert
    rep = convert_pdf_to_word(pdf, work, ConversionOptions(), lambda *a: None, None)
    win.section("convert")
    win.convert.show_panel("pdf2word", [str(pdf)])
    snap("08-convert.png")
    rd = ReportDialog(win, "Conversion report", rep.to_text(), rep.output)
    rd.resize(1000, 520)
    rd.show()
    snap("09-conversion-report.png", rd)
    rd.close()
    # 10 organize / 11 security
    win.section("organize")
    snap("10-organize.png")
    win.section("security")
    snap("11-security.png")
    # 12 dark theme reader
    ctx.settings.set("theme", "dark")
    settle()
    win.section("home")
    win.tabs.setCurrentIndex(0)
    tab.view.go_to_page(0)
    snap("12-dark.png")
    win.close() if False else None
    print("done ->", out)
    os._exit(0)


if __name__ == "__main__":
    main()
