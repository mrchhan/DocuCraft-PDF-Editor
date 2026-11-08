"""Settings: General, Appearance, PDF, Conversion, Performance, About. Every change is saved immediately."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from app import brand, theme
from app.settings import APP_NAME, APP_VERSION, DEVELOPER, LANGUAGES, LICENSE_NAME, REPO_URL, TAGLINE
from converters import ocr_engine, word_to_pdf
from core import branding
from core import pdf_security as sec
from services import logging_service
from ui.components.widgets import confirm, message, open_path
from ui.pages.tools_page import PathRow

THIRD_PARTY = """<h3>Third-party components</h3>
<table cellpadding="3">
<tr><td>PySide6 / Qt</td><td>LGPL-3.0</td></tr>
<tr><td>PyMuPDF (MuPDF)</td><td>AGPL-3.0 (this is why DocuCraft is AGPL-3.0-or-later)</td></tr>
<tr><td>pdf2docx</td><td>MIT</td></tr>
<tr><td>python-docx</td><td>MIT</td></tr>
<tr><td>Pillow</td><td>MIT-CMU</td></tr>
<tr><td>Tesseract OCR</td><td>Apache-2.0</td></tr>
<tr><td>LibreOffice (optional, installed separately)</td><td>MPL-2.0</td></tr>
</table>"""


def _form() -> tuple[QWidget, QFormLayout]:
    w = QWidget()
    f = QFormLayout(w)
    f.setContentsMargins(28, 22, 28, 22)
    f.setVerticalSpacing(12)
    f.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    return w, f


class SettingsPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.s = ctx.settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Settings")
        t.setObjectName("Title")
        t.setContentsMargins(28, 22, 28, 0)
        lay.addWidget(t)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self._general()
        self._appearance()
        self._pdf()
        self._conversion()
        self._performance()
        self._about()

    # ---- helpers ----
    def _combo(self, key: str, items: list[tuple[str, object]]) -> QComboBox:
        c = QComboBox()
        for label, val in items:
            c.addItem(label, val)
        i = c.findData(self.s.get(key))
        c.setCurrentIndex(max(0, i))
        c.currentIndexChanged.connect(lambda *_: self.s.set(key, c.currentData()))
        return c

    def _check(self, key: str, text: str) -> QCheckBox:
        c = QCheckBox(text)
        c.setChecked(bool(self.s.get(key)))
        c.toggled.connect(lambda v: self.s.set(key, bool(v)))
        return c

    def _spin(self, key: str, lo: int, hi: int, suffix: str = "") -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSuffix(suffix)
        sp.setValue(int(self.s.get(key)))
        sp.valueChanged.connect(lambda v: self.s.set(key, int(v)))
        return sp

    def _folder(self, key: str, placeholder: str) -> PathRow:
        r = PathRow(self.ctx, "folder", key="output", placeholder=placeholder)
        r.setText(str(self.s.get(key) or ""))
        r.edit.editingFinished.connect(lambda: self.s.set(key, r.text()))
        r.changed.connect(lambda: self.s.set(key, r.text()) if not r.edit.hasFocus() else None)
        return r

    # ---- tabs ----
    def _general(self) -> None:
        w, f = _form()
        f.addRow("Language", self._combo("language", [(l, l) for l in LANGUAGES]))
        f.addRow("Default output folder", self._folder("output_dir", "Next to the original file"))
        f.addRow("Startup", self._check("restore_session", "Reopen the documents from last time"))
        f.addRow("History", self._check("history_enabled", "Remember recent documents and conversions"))
        f.addRow("Keep up to", self._spin("recent_limit", 5, 200, " recent documents"))
        row = QHBoxLayout()
        b1 = QPushButton("Clear history now…")
        b1.clicked.connect(self._clear_history)
        b2 = QPushButton("Open log folder")
        b2.clicked.connect(lambda: open_path(logging_service.log_dir()))
        b3 = QPushButton("Clear log files")
        b3.clicked.connect(lambda: (logging_service.clear_logs(), message(self, "Logs", "Log files were cleared.")))
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch(1)
        f.addRow("Privacy", row)
        note = QLabel("Only file names, folders and page positions are stored, never document contents. "
                      "Logs stay on this computer and passwords are never written to them.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        f.addRow(note)
        self.tabs.addTab(w, "General")

    def _clear_history(self) -> None:
        if confirm(self, "Clear history", "Remove recent documents and conversion history? Favorites are kept.",
                   yes="Clear", danger=True):
            self.ctx.history.clear(keep_favorites=True)

    def _appearance(self) -> None:
        w, f = _form()
        f.addRow("Theme", self._combo("theme", [("Follow system", "system"), ("Light", "light"), ("Dark", "dark")]))
        row = QHBoxLayout()
        sl = QSlider()
        sl.setOrientation(sl.orientation().Horizontal)
        sl.setRange(80, 150)
        sl.setSingleStep(10)
        sl.setPageStep(10)
        sl.setValue(int(self.s.get("ui_scale")))
        lbl = QLabel(f"{sl.value()}%")
        sl.valueChanged.connect(lambda v: lbl.setText(f"{v}%"))
        sl.sliderReleased.connect(lambda: self.s.set("ui_scale", int(round(sl.value() / 10) * 10)))
        row.addWidget(sl, 1)
        row.addWidget(lbl)
        f.addRow("Interface scale", row)
        self.tabs.addTab(w, "Appearance")

    def _pdf(self) -> None:
        w, f = _form()
        f.addRow("Default zoom", self._combo("default_zoom", [("Fit width", "fit_width"), ("Fit page", "fit_page"),
                                                              ("100%", "100"), ("125%", "125"), ("150%", "150")]))
        f.addRow("Page layout", self._combo("page_layout", [("Continuous scroll", "continuous"), ("Single page", "single"),
                                                            ("Two pages", "two")]))
        f.addRow("Rendering quality", self._combo("render_quality", [("Fast (72 dpi)", "fast"), ("Balanced (96 dpi)", "balanced"),
                                                                     ("High (144 dpi)", "high")]))
        f.addRow("Autosave recovery copy", self._spin("autosave_recovery_seconds", 10, 600, " seconds"))
        n = QLabel("Applies to documents opened from now on.")
        n.setObjectName("Muted")
        f.addRow(n)
        self.tabs.addTab(w, "PDF")

    def _conversion(self) -> None:
        w, f = _form()
        f.addRow("Word output folder", self._folder("docx_output_dir", "Same as default output folder"))
        f.addRow("PDF to Word mode", self._combo("conv_mode", [("Preserve original layout", "layout"), ("Editable text", "editable")]))
        f.addRow("Include", self._check("conv_images", "Images"))
        f.addRow("", self._check("conv_tables", "Detect tables"))
        f.addRow("OCR", self._combo("ocr_mode", [("Automatic (scanned pages only)", "auto"), ("Off", "off"), ("Always", "force")]))
        langs = ocr_engine.available_languages() if ocr_engine.is_available() else ["eng"]
        names = getattr(ocr_engine, "LANGUAGE_NAMES", {})
        f.addRow("OCR language", self._combo("ocr_language", [(names.get(c, c), c) for c in langs]))
        f.addRow("Image export resolution", self._combo("image_dpi", [(f"{d} DPI", d) for d in (72, 96, 150, 200, 300, 600)]))
        f.addRow("JPG quality", self._spin("jpg_quality", 30, 100, " %"))
        st = QLabel(("✔ Tesseract OCR found. " if ocr_engine.is_available() else "✘ Tesseract OCR not found. ") +
                    ("✔ LibreOffice found." if word_to_pdf.is_available() else "✘ LibreOffice not found (needed only for Word → PDF)."))
        st.setObjectName("Muted")
        st.setWordWrap(True)
        f.addRow("Components", st)
        self.tabs.addTab(w, "Conversion")

    def _performance(self) -> None:
        w, f = _form()
        f.addRow("Page render cache", self._spin("render_cache_pages", 6, 120, " pages"))
        f.addRow("Concurrent jobs", self._spin("max_jobs", 1, 8))
        f.addRow("Temporary files", self._check("clean_temp_on_exit", "Delete temporary files when DocuCraft closes"))
        b = QPushButton("Clean temporary files now")
        b.clicked.connect(lambda: message(self, "Temporary files", f"Removed {sec.cleanup_stale_temp(0)} leftover temporary folder(s)."))
        f.addRow("", b)
        self.tabs.addTab(w, "Performance")

    def _about(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 22, 28, 22)
        h = QLabel(f"{APP_NAME} {APP_VERSION}")
        h.setObjectName("Title")
        lay.addWidget(h)
        lay.addWidget(QLabel(TAGLINE))
        art = QLabel()
        art.setPixmap(brand.pixmap("full", 460))
        art.setAlignment(Qt.AlignCenter)
        lay.addWidget(art)
        credit = QLabel(f"<b>{branding.STUDIO}</b><br>{branding.CONTACT_LINE.replace('  ', ' ')}")
        credit.setAlignment(Qt.AlignCenter)
        credit.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(credit)
        info = QTextBrowser()
        info.setOpenExternalLinks(True)
        info.setHtml(f"<p><b>Developer:</b> {DEVELOPER}<br><b>License:</b> {LICENSE_NAME}<br>"
                     f"<b>Source code:</b> <a href='{REPO_URL}'>{REPO_URL}</a></p>"
                     "<p>DocuCraft works offline. It has no accounts, no ads and no telemetry, and it never uploads your "
                     "documents. It only contacts the internet if <i>you</i> choose to open the project page.</p>"
                     f"{THIRD_PARTY}<p>This is a v0.1 release: conversion quality depends on the document and no "
                     "converter is perfect. See the README for known limitations.</p>")
        lay.addWidget(info, 1)
        row = QHBoxLayout()
        gh = QPushButton("Project page")
        gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        upd = QPushButton("Check for updates…")
        upd.clicked.connect(self._updates)
        reset = QPushButton("Reset settings")
        reset.clicked.connect(self._reset)
        wipe = QPushButton("Delete all local data…")
        wipe.setObjectName("Danger")
        wipe.clicked.connect(self._wipe)
        for b in (gh, upd, reset, wipe):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.tabs.addTab(w, "About")

    def _updates(self) -> None:
        if confirm(self, "Check for updates", "DocuCraft never checks for updates by itself. This will open the project's "
                   f"releases page in your web browser:\n\n{REPO_URL}/releases\n\nDocuCraft sends no information.",
                   yes="Open releases page"):
            QDesktopServices.openUrl(QUrl(REPO_URL + "/releases"))

    def _reset(self) -> None:
        if confirm(self, "Reset settings", "Restore all settings to their defaults? Your history is not affected.", yes="Reset"):
            self.s.reset()
            message(self, "Settings", "Settings were reset. Some changes apply the next time DocuCraft starts.")

    def _wipe(self) -> None:
        if confirm(self, "Delete all local data", "Delete settings, history, favorites and recovery copies stored by "
                   "DocuCraft? Your documents are not touched.", yes="Delete everything", danger=True):
            self.ctx.db.wipe_everything()
            self.ctx.recovery.discard_all()
            message(self, "Done", "All local DocuCraft data was deleted.")
