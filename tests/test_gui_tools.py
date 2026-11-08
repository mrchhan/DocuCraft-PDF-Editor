"""Run the tool panels end to end (panel -> job function -> real output file), with the job runner made synchronous."""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

import ui.pages.convert_page as cp
import ui.pages.tools_page as tp
from app import theme
from app.context import AppContext
from core.pdf_organizer import CancelToken


@pytest.fixture
def ctx(qapp, home):
    c = AppContext()
    theme.apply_theme(qapp, "light", 100)
    yield c
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():          # panels are created without a parent in these tests
        if isinstance(w, (tp.ToolPanel, cp.PdfToWordPanel, cp.WordToPdfPanel)):
            w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    c.db.close()


@pytest.fixture
def sync_jobs(monkeypatch):
    errors = []

    def fake(parent, ctx, title, fn, on_success=None, on_error=None, **kw):
        try:
            res = fn(lambda *a, **k: None, CancelToken())
        except Exception as exc:                      # mirror JobManager: failure goes to on_error
            errors.append(exc)
            if on_error:
                on_error(exc)
            return
        on_success and on_success(res)

    for mod in (tp, cp):
        monkeypatch.setattr(mod, "run_job", fake)
    monkeypatch.setattr(cp.ReportDialog, "exec", lambda self: 0)
    for mod in (tp, cp):
        monkeypatch.setattr(mod, "show_error", lambda *a, **k: errors.append(a))
    return errors


def test_merge_panel_produces_real_merged_pdf(ctx, multi_pdf, simple_pdf, tmp_path, sync_jobs):
    p = tp.MergePanel(ctx)
    p.add_files([str(multi_pdf), str(simple_pdf)])
    p.outdir.setText(str(tmp_path))
    p.name.setText("combined.pdf")
    p.run()
    assert not sync_jobs
    out = tmp_path / "combined.pdf"
    assert out.exists()
    with pymupdf.open(out) as d:
        assert d.page_count == 7


def test_merge_panel_needs_two_files(ctx, multi_pdf, sync_jobs):
    p = tp.MergePanel(ctx)
    p.add_files([str(multi_pdf)])
    p.run()
    assert sync_jobs                                  # user-facing error, no output


def test_compress_and_split_panels(ctx, multi_pdf, tmp_path, sync_jobs):
    s = tp.SplitPanel(ctx)
    s.add_files([str(multi_pdf)])
    s.outdir.setText(str(tmp_path / "split"))
    s.ranges.setText("1-2, 3-6")
    s.run()
    assert not sync_jobs
    outs = sorted((tmp_path / "split").glob("*.pdf"))
    assert len(outs) == 2
    with pymupdf.open(outs[0]) as d1, pymupdf.open(outs[1]) as d2:
        assert (d1.page_count, d2.page_count) == (2, 4)


def test_protect_panel_encrypts(ctx, simple_pdf, tmp_path, sync_jobs, monkeypatch):
    monkeypatch.setattr(tp.NewPasswordDialog, "ask", staticmethod(lambda *a, **k: "Correct-Horse-9"))
    p = tp.ProtectPanel(ctx)
    p.add_files([str(simple_pdf)])
    p.outdir.setText(str(tmp_path))
    p.run()
    outs = list(tmp_path.glob("*.pdf"))
    assert outs, sync_jobs
    with pymupdf.open(outs[0]) as d:
        assert d.needs_pass


def test_pdf_to_word_panel_creates_docx_and_logs_history(ctx, table_pdf, tmp_path, sync_jobs):
    p = cp.PdfToWordPanel(ctx)
    p.files.add_paths([str(table_pdf)])
    p.outdir.setText(str(tmp_path))
    p.run()
    docx = list(tmp_path.glob("*.docx"))
    assert docx, sync_jobs
    import docx as pydocx
    d = pydocx.Document(str(docx[0]))
    text = "\n".join(par.text for par in d.paragraphs) + " ".join(c.text for t in d.tables for r in t.rows for c in r.cells)
    assert "Invoice" in text and "Widget" in text
    assert ctx.history.conversions()[0].status == "ok"


def test_pdf_to_word_panel_reports_bad_file_without_crashing(ctx, tmp_path, sync_jobs):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    p = cp.PdfToWordPanel(ctx)
    p.files.add_paths([str(bad)])
    p.outdir.setText(str(tmp_path))
    p.run()
    assert sync_jobs                                  # a friendly error was shown, nothing crashed
    assert not list(tmp_path.glob("*.docx"))
