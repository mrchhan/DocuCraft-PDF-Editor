"""Convert page: PDF -> Word (layout or editable, tables, images, OCR) and Word -> PDF (LibreOffice)."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QTabWidget, QVBoxLayout, QWidget, QButtonGroup)

from converters import ocr_engine, word_to_pdf
from converters.pdf_to_word import ConversionOptions, ConversionReport, convert_pdf_to_word
from core import pdf_security as sec
from core.errors import DocuCraftError, InvalidFileError, OperationCancelled
from ui.components.widgets import (FileList, file_list_with_buttons, icon, message, open_path, run_job, show_error)
from ui.dialogs.dialogs import ReportDialog, unlock
from ui.pages.tools_page import PathRow


class PdfToWordPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        s = ctx.settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 18)
        t = QLabel("PDF to Word")
        t.setObjectName("Title")
        d = QLabel("Create editable .docx files. Layout accuracy depends on the PDF — complex designs may need touching "
                   "up in Word, and a conversion report tells you what was and was not preserved.")
        d.setObjectName("Muted")
        d.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(d)
        self.files = FileList((".pdf",))
        self.files.setMinimumHeight(130)
        lay.addWidget(file_list_with_buttons(self.files, ctx, "PDF documents (*.pdf)", "open", self))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.pages = QLineEdit()
        self.pages.setPlaceholderText("Entire document — or e.g. 1-3, 7")
        form.addRow("Pages", self.pages)
        self.mode_layout = QRadioButton("Preserve original layout")
        self.mode_edit = QRadioButton("Editable text (clean flowing paragraphs, real headings and tables)")
        (self.mode_layout if s.get("conv_mode") == "layout" else self.mode_edit).setChecked(True)
        box = QVBoxLayout()
        box.addWidget(self.mode_layout)
        box.addWidget(self.mode_edit)
        form.addRow("Mode", box)
        self.images = QCheckBox("Include images")
        self.images.setChecked(bool(s.get("conv_images")))
        self.tables = QCheckBox("Detect tables")
        self.tables.setChecked(bool(s.get("conv_tables")))
        row = QHBoxLayout()
        row.addWidget(self.images)
        row.addWidget(self.tables)
        row.addStretch(1)
        form.addRow("Content", row)
        self.ocr = QComboBox()
        self.ocr.addItem("Automatic — only for scanned pages", "auto")
        self.ocr.addItem("Off", "off")
        self.ocr.addItem("Always (every page)", "force")
        self.ocr.setCurrentIndex(max(0, self.ocr.findData(s.get("ocr_mode"))))
        self.lang = QComboBox()
        self._fill_langs()
        orow = QHBoxLayout()
        orow.addWidget(self.ocr, 1)
        orow.addWidget(self.lang)
        form.addRow("OCR", orow)
        self.outdir = PathRow(ctx, "folder", key="output", placeholder="Default output folder / next to each PDF")
        form.addRow("Output folder", self.outdir)
        lay.addLayout(form)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("Muted")
        lay.addWidget(self.hint)
        row = QHBoxLayout()
        self.run_btn = QPushButton("Convert to Word")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setMinimumHeight(36)
        self.run_btn.clicked.connect(self.run)
        row.addWidget(self.run_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.files.changed.connect(self._scan_hint)

    def _fill_langs(self) -> None:
        names = getattr(ocr_engine, "LANGUAGE_NAMES", {})
        langs = ocr_engine.available_languages() if ocr_engine.is_available() else []
        for code in langs or ["eng"]:
            self.lang.addItem(names.get(code, code), code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(str(self.ctx.settings.get("ocr_language")))))

    def add_files(self, paths) -> None:
        self.files.add_paths(paths)

    def _scan_hint(self) -> None:
        """Tell the user when scanned (image-only) pages are present, so they know OCR will be used."""
        scanned = []
        for p in self.files.paths()[:20]:
            try:
                if sec.is_encrypted(p):
                    continue
                doc = sec.open_pdf(p)
                try:
                    if any(not doc[i].get_text("text").strip() and doc[i].get_images() for i in range(min(3, doc.page_count))):
                        scanned.append(Path(p).name)
                finally:
                    doc.close()
            except Exception:
                continue
        if scanned:
            ok = ocr_engine.is_available()
            self.hint.setText(f"Scanned pages detected in: {', '.join(scanned[:3])}"
                              f"{'…' if len(scanned) > 3 else ''}. " +
                              ("OCR will be used to recognise the text." if ok else ocr_engine.INSTALL_HINT))
        else:
            self.hint.setText("")

    def run(self) -> None:
        files = self.files.paths()
        if not files:
            message(self, "PDF to Word", "Add at least one PDF file first.", "warn")
            return
        try:
            pws = {f: unlock(self, f) for f in files}
        except OperationCancelled:
            return
        except DocuCraftError as exc:                      # e.g. a file that is not really a PDF
            show_error(self, exc, "PDF to Word")
            return
        opt = ConversionOptions(page_range=self.pages.text().strip(), mode="layout" if self.mode_layout.isChecked() else "editable",
                                extract_images=self.images.isChecked(), detect_tables=self.tables.isChecked(),
                                ocr=self.ocr.currentData(), ocr_language=self.lang.currentData() or "eng")
        outs = {}
        for f in files:
            try:
                outs[f] = Path(self.outdir.text()) if self.outdir.text() else self.ctx.output_dir_for(f, docx=True)
            except Exception as exc:
                show_error(self, exc)
                return

        def work(progress, cancel):
            reports: list[ConversionReport] = []
            n = len(files)
            for k, f in enumerate(files):
                base, span, name = int(k / n * 100), 100 / n, Path(f).name
                sub = lambda pct, msg, b=base, sp=span, nm=name: progress(int(b + pct * sp / 100), f"{nm}: {msg}")
                try:
                    reports.append(convert_pdf_to_word(f, outs[f], dataclasses.replace(opt, password=pws[f]), sub, cancel))
                except OperationCancelled:
                    raise
                except Exception as exc:
                    reports.append(ConversionReport(source=f, mode=opt.mode, error=getattr(exc, "user_message", None) or str(exc)))
            return reports

        self.run_btn.setEnabled(False)
        run_job(self, self.ctx, "Converting to Word", work, on_success=self._done,
                on_error=lambda e: (self.run_btn.setEnabled(True), show_error(self, e, "PDF to Word")))
        # the progress dialog handles cancel; re-enable button when finished
        self.ctx.jobs.jobsChanged.connect(self._reenable)

    def _reenable(self, n: int) -> None:
        if n == 0:
            self.run_btn.setEnabled(True)
            try:
                self.ctx.jobs.jobsChanged.disconnect(self._reenable)
            except (RuntimeError, TypeError):
                pass

    def _done(self, reports: list[ConversionReport]) -> None:
        self.run_btn.setEnabled(True)
        for r in reports:
            self.ctx.history.add_conversion(r.source, r.output, "pdf_to_word", "ok" if r.success else "error",
                                            r.pages_processed, r.error)
        ok = [r for r in reports if r.success]
        if len(reports) == 1:
            r = reports[0]
            ReportDialog(self, "Conversion report" if r.success else "Conversion failed", r.to_text(), r.output if r.success else None).exec()
            return
        text = f"{len(ok)} of {len(reports)} file(s) converted.\n\n" + "\n\n".join(
            ("✔ " if r.success else "✘ ") + Path(r.source).name + (f"\n   → {r.output}" if r.success else f"\n   {r.error}") for r in reports)
        folder = str(Path(ok[0].output).parent) if ok else None
        ReportDialog(self, "Batch conversion summary", text, ok[0].output if ok else None).exec()


class WordToPdfPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 18)
        t = QLabel("Word to PDF")
        t.setObjectName("Title")
        d = QLabel("Convert .docx (and .doc, .odt, .rtf) documents to PDF with the free LibreOffice engine installed on "
                   "this computer. Nothing is uploaded.")
        d.setObjectName("Muted")
        d.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(d)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.files = FileList((".docx", ".doc", ".odt", ".rtf"))
        self.files.setMinimumHeight(130)
        lay.addWidget(file_list_with_buttons(self.files, ctx, "Word documents (*.docx *.doc *.odt *.rtf)", "open", self))
        form = QFormLayout()
        self.outdir = PathRow(ctx, "folder", key="output", placeholder="Default output folder / next to each file")
        form.addRow("Output folder", self.outdir)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.run_btn = QPushButton("Convert to PDF")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setMinimumHeight(36)
        self.run_btn.clicked.connect(self.run)
        row.addWidget(self.run_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.refresh_status()

    def refresh_status(self) -> None:
        ok = word_to_pdf.is_available()
        self.status.setText("✔ LibreOffice found — ready." if ok else word_to_pdf.INSTALL_HINT)
        self.status.setStyleSheet("" if ok else "color:#d92d20;")

    def add_files(self, paths) -> None:
        self.files.add_paths(paths)

    def run(self) -> None:
        files = self.files.paths()
        if not files:
            message(self, "Word to PDF", "Add at least one Word document first.", "warn")
            return
        if not word_to_pdf.is_available():
            self.refresh_status()
            message(self, "LibreOffice needed", word_to_pdf.INSTALL_HINT, "warn")
            return
        out = Path(self.outdir.text()) if self.outdir.text() else None

        def work(progress, cancel):
            outputs, failures = [], []
            n = len(files)
            for k, f in enumerate(files):
                progress(int(k / n * 100), f"Converting {Path(f).name}")
                try:
                    outputs.append(word_to_pdf.convert_docx_to_pdf(f, out or self.ctx.output_dir_for(f), cancel=cancel))
                except OperationCancelled:
                    raise
                except DocuCraftError as exc:
                    failures.append((Path(f).name, exc.user_message))
            progress(100, "Done")
            return files, outputs, failures

        self.run_btn.setEnabled(False)
        run_job(self, self.ctx, "Converting to PDF", work, on_success=self._done,
                on_error=lambda e: (self.run_btn.setEnabled(True), show_error(self, e, "Word to PDF")))
        self.ctx.jobs.jobsChanged.connect(self._reenable)

    def _reenable(self, n: int) -> None:
        if n == 0:
            self.run_btn.setEnabled(True)
            try:
                self.ctx.jobs.jobsChanged.disconnect(self._reenable)
            except (RuntimeError, TypeError):
                pass

    def _done(self, result) -> None:
        self.run_btn.setEnabled(True)
        files, outputs, failures = result
        for src, o in zip(files, outputs):
            self.ctx.history.add_conversion(src, str(o), "word_to_pdf", "ok", 0, "")
        for name, why in failures:
            self.ctx.history.add_conversion(name, "", "word_to_pdf", "error", 0, why)
        text = f"{len(outputs)} of {len(files)} file(s) converted."
        if outputs:
            text += "\n\n" + "\n".join(f"✔ {o}" for o in outputs)
        if failures:
            text += "\n\n" + "\n".join(f"✘ {n}: {w}" for n, w in failures)
        ReportDialog(self, "Word to PDF", text, str(outputs[0]) if outputs else None).exec()


class ConvertPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.p2w = PdfToWordPanel(ctx)
        self.w2p = WordToPdfPanel(ctx)
        self.tabs.addTab(self.p2w, icon("word", 18), "PDF → Word")
        self.tabs.addTab(self.w2p, icon("pdf", 18), "Word → PDF")
        lay.addWidget(self.tabs)
        self.setAcceptDrops(True)

    def show_panel(self, which: str, files: list[str] | None = None) -> None:
        self.tabs.setCurrentIndex(0 if which == "pdf2word" else 1)
        if files:
            (self.p2w if which == "pdf2word" else self.w2p).add_files(files)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        pdfs = [p for p in paths if p.lower().endswith(".pdf")]
        docs = [p for p in paths if p.lower().endswith((".docx", ".doc", ".odt", ".rtf"))]
        if pdfs:
            self.show_panel("pdf2word", pdfs)
        elif docs:
            self.show_panel("word2pdf", docs)
        e.acceptProposedAction()

    def retheme(self) -> None:
        self.tabs.setTabIcon(0, icon("word", 18))
        self.tabs.setTabIcon(1, icon("pdf", 18))
