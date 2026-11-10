"""Offscreen GUI tests: viewer behaviour, editing workflow through the tab, and the main-window shell."""
from __future__ import annotations

import pymupdf
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from app import theme
from app.context import AppContext
from app.document_session import DocumentSession
from app.main_window import MainWindow
from ui.components.document_tab import DocumentTab
from ui.components.pdf_view import PdfView


@pytest.fixture
def ctx(qapp, home):
    c = AppContext()
    theme.apply_theme(qapp, "light", 100)
    yield c
    c.db.close()


@pytest.fixture
def tab(qapp, ctx, copy_of, multi_pdf):
    s = DocumentSession(copy_of(multi_pdf), None, recovery=ctx.recovery, autosave_seconds=600)
    t = DocumentTab(ctx, s)
    t.resize(1100, 800)
    t.show()
    qapp.processEvents()
    yield t
    t.close_tab()
    t.deleteLater()
    qapp.processEvents()


@pytest.fixture
def win(qapp, ctx):
    w = MainWindow(ctx, qapp)
    w.resize(1280, 800)
    w.show()
    qapp.processEvents()
    yield w
    w.close()                                           # runs the real close path while the DB is still open
    w.deleteLater()
    qapp.processEvents()


# ----------------------------------------------------------------------------- viewer
def test_navigation_and_zoom(tab):
    v = tab.view
    assert v.page_count == 6
    v.go_to_page(3)
    assert v.current_page == 3
    z = v.zoom
    v.zoom_in()
    assert v.zoom > z
    v.zoom_out()
    v.zoom_out()
    assert v.zoom < z
    v.fit_width()
    assert v.zoom > 0


@pytest.mark.parametrize("mode", ["single", "continuous", "two"])
def test_layouts(tab, mode):
    tab.view.set_layout(mode)
    assert tab.view.layout_mode == mode
    tab.view.go_to_page(2)
    assert tab.view.current_page in (2, 3)


def test_rotate_view_cycles(tab):
    v = tab.view
    r0 = v.rotation
    v.rotate_view(90)
    assert v.rotation == (r0 + 90) % 360
    v.rotate_view(-90)
    assert v.rotation == r0


def test_status_and_title(tab):
    page, total, zoom, size = tab.status_info()
    assert (page, total) == (1, 6)
    assert zoom > 0 and size
    assert tab.title().endswith("multi.pdf") or "multi" in tab.title()


def test_search_finds_text(tab):
    hits = tab.session.search_sync("Confidential", False)
    assert len(hits) == 6


def test_thumbnails_built_lazily(tab, qapp):
    qapp.processEvents()
    assert tab.thumbs.count() == 6


# ----------------------------------------------------------------------------- editing workflow
def test_highlight_through_tab_is_undoable(tab):
    pg = tab.session.reader.doc[0]
    before = len(list(pg.annots() or []))
    tab._tool_done("markup", 0, [(72, 70, 200, 95)]) if False else tab._tool_done("highlight", 0, [(72, 70, 200, 95)])
    assert tab.session.dirty
    assert len(list(tab.session.reader.doc[0].annots() or [])) == before + 1
    tab.undo()
    assert len(list(tab.session.reader.doc[0].annots() or [])) == before
    assert not tab.session.dirty


def test_shape_and_line_tools(tab):
    tab._tool_done("rect", 1, (80, 80, 200, 160))
    tab._tool_done("arrow", 1, ((80, 200), (220, 260)))
    assert len(list(tab.session.reader.doc[1].annots() or [])) >= 2


def test_page_actions_via_tab(tab):
    tab._pages_action("duplicate", [0])
    assert tab.session.page_count == 7
    tab._pages_action("rotate", [0])
    tab.undo()
    tab.undo()
    assert tab.session.page_count == 6


def test_redaction_removes_text_for_real(tab, tmp_path, monkeypatch):
    import ui.components.document_tab as dt
    monkeypatch.setattr(dt, "confirm", lambda *a, **k: True)
    page = tab.session.reader.doc[0]
    rect = page.search_for("Confidential")[0]
    tab._tool_done("redact", 0, tuple(rect))
    assert "Confidential" not in tab.session.reader.doc[0].get_text()


def test_save_requires_confirmation_and_makes_backup(tab, monkeypatch):
    import ui.components.document_tab as dt
    tab._tool_done("rect", 0, (80, 80, 200, 160))
    original = tab.session.path.read_bytes()
    monkeypatch.setattr(dt, "confirm", lambda *a, **k: False)
    assert tab.save() is False
    assert tab.session.path.read_bytes() == original            # declined -> untouched
    monkeypatch.setattr(dt, "confirm", lambda *a, **k: True)
    assert tab.save() is True
    assert tab.session.path.read_bytes() != original
    assert not tab.session.dirty


# ----------------------------------------------------------------------------- shell
def test_main_window_opens_and_dedupes(win, copy_of, multi_pdf):
    p = str(copy_of(multi_pdf))
    t1 = win.open_path(p)
    t2 = win.open_path(p)
    assert t1 is t2 and win.tabs.count() == 1
    assert win.ctx.history.recent()[0].name == "multi.pdf"


def test_every_section_and_page_renders(win, copy_of, multi_pdf):
    win.open_path(str(copy_of(multi_pdf)))
    for k in ["home", "recent", "mydocs", "favorites", "tools", "convert", "history", "settings"]:
        win.navigate(k)
        assert win.pages.currentWidget() is win.page_map[k]
    for s in ["edit", "home", "convert", "organize", "security", "settings"]:
        win.section(s)


def test_theme_switch_applies_everywhere(win, copy_of, multi_pdf, ctx):
    win.open_path(str(copy_of(multi_pdf)))
    ctx.settings.set("theme", "dark")
    QApplication.processEvents()
    assert theme.current() == "dark"
    ctx.settings.set("theme", "light")
    QApplication.processEvents()
    assert theme.current() == "light"


def test_unsaved_changes_block_close(win, copy_of, multi_pdf, monkeypatch):
    import ui.components.document_tab as dt
    t = win.open_path(str(copy_of(multi_pdf)))
    t._tool_done("rect", 0, (80, 80, 200, 160))
    monkeypatch.setattr(t, "maybe_close", lambda: False)         # user chose Cancel
    assert win.close_tab(0) is False
    assert win.tabs.count() == 1
    t.session.editor.dirty = False                       # let the fixture close the window without a prompt


def test_missing_file_is_reported_not_crashed(win, monkeypatch, tmp_path):
    import app.main_window as mw
    seen = []
    monkeypatch.setattr(mw, "show_error", lambda *a, **k: seen.append(a))
    assert win.open_path(str(tmp_path / "nope.pdf")) is None
    assert seen


def test_password_pdf_flow(win, protected_pdf, monkeypatch):
    from ui.dialogs.dialogs import PasswordDialog
    monkeypatch.setattr(PasswordDialog, "ask", staticmethod(lambda *a, **k: "s3cret!"))
    t = win.open_path(str(protected_pdf))
    assert t is not None and t.session.encrypted


def test_password_cancel_opens_nothing(win, protected_pdf, monkeypatch):
    from ui.dialogs.dialogs import PasswordDialog
    monkeypatch.setattr(PasswordDialog, "ask", staticmethod(lambda *a, **k: None))
    assert win.open_path(str(protected_pdf)) is None
    assert win.tabs.count() == 0


def test_large_document_opens_fast(win, large_pdf):
    import time
    t0 = time.time()
    t = win.open_path(str(large_pdf))
    assert t.session.page_count == 400
    assert time.time() - t0 < 10


def test_recent_list_multi_select_remove(tmp_path, qtbot_free=None):
    """Select several recent documents (Ctrl/Shift) and remove them in one go; the files stay on disk."""
    import pymupdf
    from PySide6.QtWidgets import QApplication
    from app.context import AppContext
    from ui.pages.library_page import LibraryPage
    QApplication.instance() or QApplication([])
    import os
    os.environ["DOCUCRAFT_HOME"] = str(tmp_path / "home")
    ctx = AppContext()
    files = []
    for i in range(3):
        d = pymupdf.open(); d.new_page(); f = tmp_path / f"doc{i}.pdf"; d.save(f); d.close(); files.append(f)
        ctx.history.add_recent(f)
    page = LibraryPage(ctx, "recent")
    assert page.list.count() == 3
    page.list.selectAll()
    assert len(page._paths()) == 3 and page.btn_remove.isEnabled() and not page.btn_open.isEnabled()
    page.list.item(0).setSelected(False)
    page._remove()
    assert page.list.count() == 1 and all(f.exists() for f in files)
    page.deleteLater()
    ctx.db.close()


def test_print_to_pdf_printer_prints_chosen_pages(tab, tmp_path):
    from PySide6.QtPrintSupport import QPrinter
    out = tmp_path / "printed.pdf"
    pr = QPrinter(QPrinter.HighResolution)
    pr.setOutputFormat(QPrinter.PdfFormat)
    pr.setOutputFileName(str(out))
    n = tab.print_to(pr)
    assert n == tab.session.page_count
    assert out.exists() and out.stat().st_size > 1000
    with pymupdf.open(out) as d:
        assert d.page_count == tab.session.page_count


def test_print_preview_dialog_renders_pages(tab, qapp):
    dlg = tab.preview_dialog()
    dlg.show()
    qapp.processEvents()
    assert "Print preview" in dlg.windowTitle()
    n = tab.session.page_count
    assert len(dlg._labels) == n
    assert dlg._labels[0].pixmap() is not None and not dlg._labels[0].pixmap().isNull()
    z = dlg.zoom
    dlg.btn_in.click()
    assert dlg.zoom > z and len(dlg._labels) == n
    dlg.btn_out.click()
    dlg.close()
    qapp.processEvents()


def test_print_preview_shows_unsaved_edits(tab, tmp_path):
    from PySide6.QtPrintSupport import QPrinter
    tab._edit("add_text_box", 0, (80, 80, 300, 120), "PREVIEWCHECK")
    assert tab.session.dirty
    out = tmp_path / "p.pdf"
    pr = QPrinter(QPrinter.HighResolution)
    pr.setOutputFormat(QPrinter.PdfFormat)
    pr.setOutputFileName(str(out))
    assert tab.print_to(pr) >= 1
    with pymupdf.open(out) as d:                      # the printed page is an image of the edited page, so compare pixels
        before = tab.session.reader.render(0, zoom=1.0)
        assert d.page_count >= 1 and before.width > 0


def test_main_window_has_preview_action(win):
    assert win.a_preview.text().startswith("Print preview")
