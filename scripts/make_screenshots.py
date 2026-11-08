"""Render real screenshots of the running DocuCraft UI (offscreen) from a synthetic demo document.

    python scripts/make_screenshots.py [output_dir]
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

DEMO = ("DocuCraft keeps every document on your computer. Open, read, annotate, convert and organise PDFs without "
        "uploading anything. This demonstration file is synthetic and contains no real data. ") * 4


def build_demo(path: Path) -> None:
    d = pymupdf.open()
    for i in range(1, 6):
        pg = d.new_page()
        pg.insert_text((72, 90), f"Quarterly Report - Section {i}", fontsize=24, fontname="hebo")
        pg.insert_textbox(pymupdf.Rect(72, 120, 523, 420), DEMO, fontsize=12)
        pg.draw_rect(pymupdf.Rect(72, 440, 523, 560), color=(0.3, 0.4, 0.8), fill=(0.93, 0.95, 1))
        pg.insert_text((90, 505), "Key figures are illustrative only.", fontsize=14)
    d.set_toc([[1, f"Section {i}", i] for i in range(1, 6)])
    d.set_metadata({"title": "Demo Report", "author": "DocuCraft"})
    d.save(path)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="dc_shots_"))
    os.environ["DOCUCRAFT_HOME"] = str(work / "home")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from app import theme
    from app.context import AppContext
    from app.main_window import MainWindow

    app = QApplication([])
    ctx = AppContext()
    ctx.settings.set("theme", "light")
    theme.apply_theme(app, "light", 100)
    pdf = work / "Demo Report.pdf"
    build_demo(pdf)
    ctx.history.add_recent(pdf)
    win = MainWindow(ctx, app)
    win._apply_theme()
    win.resize(1360, 860)
    win.show()

    def snap(name: str) -> None:
        for _ in range(6):
            app.processEvents()
        win.grab().save(str(out / name))
        print("saved", name)

    snap("01-home.png")
    tab = win.open_path(str(pdf))
    tab.view.go_to_page(0)
    snap("02-reader.png")
    win.section("edit")
    tab._tool_done("highlight", 0, [tuple(r) for r in tab.session.reader.doc[0].search_for("Quarterly")])
    tab._tool_done("rect", 0, (300, 600, 520, 700))
    snap("03-editor.png")
    win.section("convert")
    win.convert.show_panel("pdf2word", [str(pdf)])
    snap("04-convert.png")
    win.section("organize")
    snap("05-organize.png")
    win.section("settings")
    snap("06-settings.png")
    ctx.settings.set("theme", "dark")
    app.processEvents()
    win.section("home")
    win.tabs.setCurrentIndex(0)
    snap("07-dark-reader.png")
    tab.close_tab()
    ctx.db.close()


if __name__ == "__main__":
    main()
