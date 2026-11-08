import logging
import time
import pytest
from database.database import Database
from services import logging_service
from services.document_history import DocumentHistory
from services.file_manager import FileManager
from services.recovery_service import RecoveryService, recovery_dir


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db"); yield d; d.close()


def test_settings(db, tmp_path):
    assert db.get_setting("theme", "light") == "light"
    db.set_setting("theme", "dark"); db.set_setting("flags", {"a": [1, 2]}); db.set_setting("theme", "system")
    assert db.get_setting("theme") == "system" and db.get_setting("flags") == {"a": [1, 2]}
    db.close(); b = Database(tmp_path / "t.db"); assert b.get_setting("theme") == "system"; b.close()


def test_recent_order_dedupe_limit_search(db, simple_pdf, multi_pdf, mixed_size_pdf):
    h = DocumentHistory(db)
    h.add_recent(simple_pdf); time.sleep(.01); h.add_recent(multi_pdf); time.sleep(.01); h.add_recent(simple_pdf, page=3, zoom=1.5)
    assert [r.name for r in h.recent()] == ["simple.pdf", "multi.pdf"] and h.last_position(simple_pdf) == (3, 1.5)
    db.set_setting("recent_limit", 2); h.add_recent(mixed_size_pdf); assert len(h.recent()) == 2
    assert [r.name for r in h.recent("sizes")] == ["sizes.pdf"] and h.recent("100%_") == []


def test_favorites_disable_clear(db, simple_pdf):
    h = DocumentHistory(db)
    h.add_recent(simple_pdf); h.add_favorite(simple_pdf); h.add_favorite(simple_pdf); h.add_conversion(simple_pdf, "o.docx", "pdf_to_word", "ok", 1)
    assert len(h.favorites()) == 1 and h.recent()[0].favorite
    h.clear(); assert h.recent() == [] and h.conversions() == [] and h.is_favorite(simple_pdf)
    h.clear(keep_favorites=False); assert not h.is_favorite(simple_pdf)
    db.set_setting("history_enabled", False); h.add_recent(simple_pdf); h.add_conversion("a", "b", "k", "ok")
    assert h.recent() == [] and h.conversions() == []


def test_conversion_history_and_wipe(db):
    h = DocumentHistory(db)
    h.add_conversion("/a/report.pdf", "/a/report.docx", "pdf_to_word", "ok", 3)
    h.add_conversion("/a/memo.docx", "", "word_to_pdf", "error", 0, "boom")
    assert [c.name for c in h.conversions("memo")] == ["memo.docx"] and len(h.conversions()) == 2
    db.set_setting("x", 1); db.wipe_everything(); assert h.conversions() == [] and db.all_settings() == {}


def test_file_manager(db, tmp_path, simple_pdf):
    fm = FileManager(db)
    assert fm.output_dir_for(simple_pdf) == simple_pdf.parent
    out = tmp_path / "out" / "sub"; fm.set_default_output_dir(out)
    assert fm.output_dir_for(simple_pdf) == out and out.is_dir()
    fm.remember_dir("open", simple_pdf); assert fm.last_dir("open") == simple_pdf.parent


def test_recovery(tmp_path):
    r, orig = RecoveryService(), tmp_path / "doc.pdf"
    assert r.snapshot(orig, b"%PDF-1.4 data") and r.snapshot(orig, b"%PDF-1.4 newer")
    item = r.pending()[0]; assert item.original == str(orig)
    dst = tmp_path / "restored.pdf"; dst.write_bytes(b"keep me")
    out = r.restore(item, dst); assert out != dst and dst.read_bytes() == b"keep me" and out.read_bytes().endswith(b"newer")
    assert r.snapshot(tmp_path / "enc.pdf", b"secret", encrypted=True) is None
    (recovery_dir() / "junk.json").write_text("{not json"); assert len(r.pending()) == 1
    r.discard(orig); assert r.pending() == []
    r.snapshot(orig, b"x"); r.discard_all(); assert r.pending() == []


def test_log_redacts_passwords():
    lg = logging_service.setup_logging(); lg.info("opening with password=hunter2 and token: abc123")
    for h in lg.handlers: h.flush()
    text = (logging_service.log_dir() / "docucraft.log").read_text()
    assert "hunter2" not in text and "abc123" not in text and "***" in text
    logging_service.clear_logs(); assert (logging_service.log_dir() / "docucraft.log").read_text() == ""
