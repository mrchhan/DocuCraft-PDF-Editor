"""PDF Tools page: merge, split, compress, images<->PDF, extract, password/sanitize and OCR.

Every panel validates in `prepare()` on the GUI thread (asking for passwords where needed) and returns a
function that does the real work on a background thread.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget, QCheckBox, QFileDialog)

from core import pdf_organizer as org
from core import pdf_security as sec
from core import watermark
from core.errors import DocuCraftError, InvalidFileError, OperationCancelled
from core.pdf_reader import format_size
from converters import image_to_pdf, ocr_engine, pdf_to_image
from ui.components.widgets import (FileList, choose_dir, file_list_with_buttons, icon, message, open_file_dialog,
                                   open_path, reveal, run_job, show_error)
from ui.dialogs.dialogs import NewPasswordDialog, unlock

PDF_FILTER = "PDF documents (*.pdf)"
IMG_FILTER = "Images (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp)"


class PathRow(QWidget):
    """A line edit with a Browse button for a file or a folder."""
    changed = Signal()

    def __init__(self, ctx, mode: str = "file", filter_text: str = PDF_FILTER, key: str = "open",
                 placeholder: str = "", parent=None):
        super().__init__(parent)
        self.ctx, self.mode, self.filter, self.key = ctx, mode, filter_text, key
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(lambda *_: self.changed.emit())
        b = QPushButton("Browse…")
        b.clicked.connect(self.browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(b)
        self.setAcceptDrops(True)

    def browse(self) -> None:
        if self.mode == "folder":
            d = choose_dir(self, self.ctx, "Choose a folder", self.key)
            if d:
                self.edit.setText(d)
        else:
            f = open_file_dialog(self, self.ctx, "Choose a file", self.filter, self.key)
            if f:
                self.edit.setText(f)

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, t: str) -> None:
        self.edit.setText(t)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        urls = e.mimeData().urls()
        if urls:
            self.edit.setText(urls[0].toLocalFile())


class ToolPanel(QWidget):
    title = ""
    description = ""
    run_text = "Run"
    kind = "tool"

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.output: Path | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        t = QLabel(self.title)
        t.setObjectName("Title")
        d = QLabel(self.description)
        d.setObjectName("Muted")
        d.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(d)
        lay.addSpacing(10)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignLeft)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        lay.addLayout(self.form)
        self.build()
        row = QHBoxLayout()
        self.run_btn = QPushButton(self.run_text)
        self.run_btn.setObjectName("Primary")
        self.run_btn.setMinimumHeight(36)
        self.run_btn.clicked.connect(self.run)
        row.addWidget(self.run_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.result)
        orow = QHBoxLayout()
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(lambda: self.output and open_path(self.output))
        self.folder_btn = QPushButton("Show in folder")
        self.folder_btn.clicked.connect(lambda: self.output and reveal(self.output))
        orow.addWidget(self.open_btn)
        orow.addWidget(self.folder_btn)
        orow.addStretch(1)
        self.result_btns = QWidget()
        self.result_btns.setLayout(orow)
        self.result_btns.hide()
        lay.addWidget(self.result_btns)
        lay.addStretch(1)

    # ---- hooks for subclasses ----
    def build(self) -> None: ...
    def prepare(self): raise NotImplementedError
    def finished(self, result) -> tuple[str, Path | None]: raise NotImplementedError
    def add_files(self, paths: list[str]) -> None: ...

    # ---- helpers ----
    def out_dir(self, row: PathRow, source: str | None) -> Path:
        if row.text():
            return sec.validate_output_dir(row.text())
        return sec.validate_output_dir(self.ctx.output_dir_for(source) if source else self.ctx.files.last_dir("save"))

    def require_file(self, row: PathRow) -> str:
        if not row.text():
            raise InvalidFileError("Choose a PDF file first.")
        return str(sec.validate_input_file(row.text()))

    def run(self) -> None:
        self.result_btns.hide()
        self.result.setText("")
        try:
            fn = self.prepare()
        except OperationCancelled:
            return
        except DocuCraftError as exc:
            show_error(self, exc, self.title)
            return
        self.run_btn.setEnabled(False)
        run_job(self, self.ctx, self.title, fn, on_success=self._ok,
                on_error=lambda e: (self.run_btn.setEnabled(True), show_error(self, e, self.title)))

    def _ok(self, result) -> None:
        self.run_btn.setEnabled(True)
        text, out = self.finished(result)
        self.output = out
        self.result.setText(text)
        self.result_btns.setVisible(out is not None)
        if out is not None:
            self.open_btn.setVisible(Path(out).is_file())
            try:
                self.ctx.history.add_conversion(self._source_for_history(), str(out), self.kind, "ok", 0, "")
            except Exception:
                pass

    def _source_for_history(self) -> str:
        return getattr(self, "_src", "")


# ----------------------------------------------------------------------------------------- merge
class MergePanel(ToolPanel):
    title, kind, run_text = "Merge PDF", "merge", "Merge files"
    description = "Combine several PDFs into one. Drag files in, drag rows to reorder them."

    def build(self) -> None:
        self.files = FileList((".pdf",))
        self.files.setMinimumHeight(180)
        self.form.addRow(file_list_with_buttons(self.files, self.ctx, PDF_FILTER, "open", self))
        self.name = QLineEdit("merged.pdf")
        self.outdir = PathRow(self.ctx, "folder", key="output", placeholder="Same folder as the first file")
        self.form.addRow("Output name", self.name)
        self.form.addRow("Output folder", self.outdir)
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        self.form.addRow(self.count)
        self.files.changed.connect(self._count)

    def add_files(self, paths) -> None:
        self.files.add_paths(paths)

    def _count(self) -> None:
        total, pages = 0, 0
        for p in self.files.paths():
            total += Path(p).stat().st_size
        self.count.setText(f"{self.files.count()} file(s), {format_size(total)}" if self.files.count() else "")

    def prepare(self):
        files = self.files.paths()
        if len(files) < 2:
            raise InvalidFileError("Add at least two PDF files to merge.")
        pws = {}
        for f in files:
            pw = unlock(self, f)
            if pw:
                pws[f] = pw
        name = sec.sanitize_filename(self.name.text() or "merged.pdf", "merged.pdf")
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        dst = self.out_dir(self.outdir, files[0]) / name
        self._src = files[0]
        return lambda progress, cancel: org.merge_pdfs(files, dst, passwords=pws, progress=progress, cancel=cancel)

    def finished(self, path):
        with pymupdf.open(path) as d:
            n = d.page_count
        return f"Merged {self.files.count()} files into {Path(path).name} ({n} pages, {format_size(Path(path).stat().st_size)}).", path


# ----------------------------------------------------------------------------------------- split
class SplitPanel(ToolPanel):
    title, kind, run_text = "Split PDF", "split", "Split"
    description = "Cut a PDF into several files by page range, into single pages, or into equal groups."

    def build(self) -> None:
        self.src = PathRow(self.ctx)
        self.form.addRow("PDF file", self.src)
        self.mode = QComboBox()
        self.mode.addItems(["By page ranges", "Every page", "Equal groups of pages"])
        self.form.addRow("Split", self.mode)
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText("e.g. 1-3, 4-6, 9   (each range becomes its own file)")
        self.group = QSpinBox()
        self.group.setRange(1, 10000)
        self.group.setValue(5)
        self.form.addRow("Ranges", self.ranges)
        self.form.addRow("Pages per file", self.group)
        self.outdir = PathRow(self.ctx, "folder", key="output", placeholder="Same folder as the PDF")
        self.form.addRow("Output folder", self.outdir)
        self.mode.currentIndexChanged.connect(self._mode)
        self._mode()

    def _mode(self) -> None:
        i = self.mode.currentIndex()
        self.ranges.setEnabled(i == 0)
        self.group.setEnabled(i == 2)

    def add_files(self, paths) -> None:
        if paths:
            self.src.setText(paths[0])

    def prepare(self):
        src = self.require_file(self.src)
        pw = unlock(self, src)
        i = self.mode.currentIndex()
        if i == 0 and not self.ranges.text().strip():
            raise InvalidFileError("Enter the page ranges to split on, for example 1-3, 4-6.")
        out = self.out_dir(self.outdir, src)
        self._src = src
        mode, ranges, size = ("ranges", "every", "groups")[i], self.ranges.text(), self.group.value()
        return lambda progress, cancel: org.split_pdf(src, out, mode, ranges=ranges, group_size=size, password=pw,
                                                      progress=progress, cancel=cancel)

    def finished(self, files):
        out = Path(files[0]).parent if files else None
        return f"Created {len(files)} file(s) in {out}.", out


# ----------------------------------------------------------------------------------------- compress
class CompressPanel(ToolPanel):
    title, kind, run_text = "Compress PDF", "compress", "Compress"
    description = "Make a PDF smaller. The original file is never changed; the result is saved as a new file."

    def build(self) -> None:
        self.src = PathRow(self.ctx)
        self.form.addRow("PDF file", self.src)
        self.level = QComboBox()
        self.level.addItem("Low — lossless clean-up only (best quality)", "low")
        self.level.addItem("Balanced — smaller images, good quality", "balanced")
        self.level.addItem("High — smallest file, lower image quality", "high")
        self.level.setCurrentIndex(1)
        self.form.addRow("Compression", self.level)
        self.outdir = PathRow(self.ctx, "folder", key="output", placeholder="Same folder as the PDF")
        self.form.addRow("Output folder", self.outdir)
        self.sizes = QLabel("")
        self.form.addRow(self.sizes)
        self.src.changed.connect(self._size)

    def _size(self) -> None:
        p = Path(self.src.text())
        self.sizes.setText(f"Current size: {format_size(p.stat().st_size)}" if p.is_file() else "")

    def add_files(self, paths) -> None:
        if paths:
            self.src.setText(paths[0])

    def prepare(self):
        src = self.require_file(self.src)
        pw = unlock(self, src)
        level = self.level.currentData()
        dst = self.out_dir(self.outdir, src) / f"{sec.sanitize_filename(Path(src).stem)} - compressed.pdf"
        self._src = src
        return lambda progress, cancel: org.compress_pdf(src, dst, level, pw, progress=progress, cancel=cancel)

    def finished(self, r):
        note = " The file could not be made smaller, so the original size was kept." if r.kept_original_size else ""
        return (f"Original: {format_size(r.original_size)}  →  Compressed: {format_size(r.new_size)}  "
                f"({r.saved_percent:.0f}% smaller).{note}"), r.output


# ----------------------------------------------------------------------------------------- images -> pdf
class ImagesToPdfPanel(ToolPanel):
    title, kind, run_text = "Images to PDF", "images_to_pdf", "Create PDF"
    description = "Turn JPG, JPEG and PNG pictures into one PDF, one image per page."

    def build(self) -> None:
        self.files = FileList((".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"))
        self.files.setMinimumHeight(170)
        self.form.addRow(file_list_with_buttons(self.files, self.ctx, IMG_FILTER, "image", self))
        self.size = QComboBox()
        self.size.addItems(["A4", "Letter", "A5", "Legal", "Fit"])
        self.size.setItemText(4, "Fit")
        self.orient = QComboBox()
        self.orient.addItems(["Auto", "Portrait", "Landscape"])
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 50)
        self.margin.setValue(10)
        self.margin.setSuffix(" mm")
        self.name = QLineEdit("images.pdf")
        self.outdir = PathRow(self.ctx, "folder", key="output", placeholder="Same folder as the first image")
        self.form.addRow("Page size", self.size)
        self.form.addRow("Orientation", self.orient)
        self.form.addRow("Margin", self.margin)
        self.form.addRow("Output name", self.name)
        self.form.addRow("Output folder", self.outdir)

    def add_files(self, paths) -> None:
        self.files.add_paths(paths)

    def prepare(self):
        files = self.files.paths()
        if not files:
            raise InvalidFileError("Add at least one image.")
        name = sec.sanitize_filename(self.name.text() or "images.pdf", "images.pdf")
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        dst = self.out_dir(self.outdir, files[0]) / name
        ps, ori, mg = self.size.currentText(), self.orient.currentText().lower(), self.margin.value()
        self._src = files[0]
        return lambda progress, cancel: image_to_pdf.images_to_pdf(files, dst, page_size=ps, orientation=ori,
                                                                   margin_mm=mg, progress=progress, cancel=cancel)

    def finished(self, path):
        return f"Created {Path(path).name} from {self.files.count()} image(s).", path


# ----------------------------------------------------------------------------------------- pdf -> images
class PdfToImagesPanel(ToolPanel):
    title, kind, run_text = "PDF to Images", "pdf_to_images", "Export images"
    description = "Save pages as PNG or JPG pictures. Leave the page range empty to export every page."

    def build(self) -> None:
        self.src = PathRow(self.ctx)
        self.fmt = QComboBox()
        self.fmt.addItems(["PNG", "JPG"])
        self.dpi = QComboBox()
        for d in pdf_to_image.DPI_CHOICES:
            self.dpi.addItem(f"{d} DPI", d)
        self.dpi.setCurrentIndex(pdf_to_image.DPI_CHOICES.index(150))
        self.pages = QLineEdit()
        self.pages.setPlaceholderText("All pages — or e.g. 1-3, 7")
        self.outdir = PathRow(self.ctx, "folder", key="output", placeholder="Same folder as the PDF")
        self.form.addRow("PDF file", self.src)
        self.form.addRow("Format", self.fmt)
        self.form.addRow("Resolution", self.dpi)
        self.form.addRow("Pages", self.pages)
        self.form.addRow("Output folder", self.outdir)

    def add_files(self, paths) -> None:
        if paths:
            self.src.setText(paths[0])

    def prepare(self):
        src = self.require_file(self.src)
        pw = unlock(self, src)
        out = self.out_dir(self.outdir, src)
        fmt, dpi, pages = self.fmt.currentText().lower(), self.dpi.currentData(), self.pages.text()
        q = int(self.ctx.settings.get("jpg_quality"))
        self._src = src
        return lambda progress, cancel: pdf_to_image.pdf_to_images(src, out, fmt=fmt, dpi=dpi, pages=pages, password=pw,
                                                                   jpg_quality=q, progress=progress, cancel=cancel)

    def finished(self, files):
        out = Path(files[0]).parent if files else None
        return f"Exported {len(files)} image(s) to {out}.", out


# ----------------------------------------------------------------------------------------- extract
class ExtractPanel(ToolPanel):
    title, kind, run_text = "Extract", "extract", "Extract"
    description = "Pull text, embedded images, selected pages or the document properties out of a PDF."

    def build(self) -> None:
        self.src = PathRow(self.ctx)
        self.what = QComboBox()
        for label, key in (("Text (.txt)", "text"), ("Embedded images", "images"), ("Selected pages (new PDF)", "pages"),
                           ("Document properties (.json)", "meta")):
            self.what.addItem(label, key)
        self.pages = QLineEdit()
        self.pages.setPlaceholderText("Pages, e.g. 1-3, 7 (empty = all pages for text)")
        self.outdir = PathRow(self.ctx, "folder", key="output", placeholder="Same folder as the PDF")
        self.form.addRow("PDF file", self.src)
        self.form.addRow("Extract", self.what)
        self.form.addRow("Pages", self.pages)
        self.form.addRow("Output folder", self.outdir)

    def add_files(self, paths) -> None:
        if paths:
            self.src.setText(paths[0])

    def prepare(self):
        src = self.require_file(self.src)
        pw = unlock(self, src)
        out = self.out_dir(self.outdir, src)
        stem = sec.sanitize_filename(Path(src).stem)
        what, pages = self.what.currentData(), self.pages.text().strip()
        self._src = src
        if what == "text":
            return lambda progress, cancel: org.extract_text(src, out / f"{stem}.txt", pw, pages or None, progress, cancel)
        if what == "images":
            return lambda progress, cancel: org.extract_images(src, out / f"{stem} images", pw, 32, progress, cancel)
        if what == "pages":
            if not pages:
                raise InvalidFileError("Enter the pages to extract, for example 1-3, 7.")
            return lambda progress, cancel: org.extract_pages(src, sec.unique_path(out / f"{stem} - extract.pdf"), pages, pw)
        return lambda progress, cancel: org.export_metadata(src, out / f"{stem}.json", pw)

    def finished(self, r):
        if isinstance(r, list):
            if not r:
                return "No embedded images were found in this document.", None
            return f"Saved {len(r)} image(s) to {Path(r[0]).parent}.", Path(r[0]).parent
        return f"Saved {Path(r).name}.", Path(r)


# ----------------------------------------------------------------------------------------- protect / unprotect
class ProtectPanel(ToolPanel):
    title, kind, run_text = "Password protection", "protect", "Create copy"
    description = "Add an AES-256 password to a PDF, or remove the password from a PDF you can open. A new copy is created."

    def build(self) -> None:
        self.src = PathRow(self.ctx)
        self.mode = QComboBox()
        self.mode.addItem("Add a password", "add")
        self.mode.addItem("Remove the password", "remove")
        self.outdir = PathRow(self.ctx, "folder", key="output", placeholder="Same folder as the PDF")
        self.form.addRow("PDF file", self.src)
        self.form.addRow("Action", self.mode)
        self.form.addRow("Output folder", self.outdir)

    def add_files(self, paths) -> None:
        if paths:
            self.src.setText(paths[0])

    def prepare(self):
        src = self.require_file(self.src)
        out = self.out_dir(self.outdir, src)
        stem = sec.sanitize_filename(Path(src).stem)
        self._src = src
        if self.mode.currentData() == "add":
            old = unlock(self, src)
            pw = NewPasswordDialog.ask(self)
            if not pw:
                raise OperationCancelled()
            dst = sec.unique_path(out / f"{stem} - protected.pdf")
            return lambda progress, cancel: sec.encrypt_pdf(src, dst, pw, src_password=old)
        if not sec.is_encrypted(src):
            raise InvalidFileError("This PDF is not password protected.")
        pw = unlock(self, src)
        dst = sec.unique_path(out / f"{stem} - unprotected.pdf")
        return lambda progress, cancel: sec.decrypt_pdf(src, dst, pw)

    def finished(self, path):
        return f"Saved {Path(path).name}. Your original file was not changed.", path


# ----------------------------------------------------------------------------------------- sanitize
class SanitizePanel(ToolPanel):
    title, kind, run_text = "Sanitize for sharing", "sanitize", "Create clean copy"
    description = ("Remove metadata (author, title…), embedded files, JavaScript and hidden text before you share a "
                   "PDF. A new copy is created.")

    def build(self) -> None:
        self.src = PathRow(self.ctx)
        self.outdir = PathRow(self.ctx, "folder", key="output", placeholder="Same folder as the PDF")
        self.form.addRow("PDF file", self.src)
        self.form.addRow("Output folder", self.outdir)

    def add_files(self, paths) -> None:
        if paths:
            self.src.setText(paths[0])

    def prepare(self):
        src = self.require_file(self.src)
        pw = unlock(self, src)
        dst = sec.unique_path(self.out_dir(self.outdir, src) / f"{sec.sanitize_filename(Path(src).stem)} - sanitized.pdf")
        self._src = src

        def work(progress, cancel):
            doc = sec.open_pdf(src, pw)
            try:
                sec.sanitize_document(doc)
                tmp = dst.with_name(f".{dst.stem}.dctmp")
                kw = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": pw, "owner_pw": pw} if pw else {}
                watermark.stamp_pdf(doc)
                doc.save(tmp, garbage=4, deflate=True, **kw)
                tmp.replace(dst)
            finally:
                doc.close()
            return dst
        return work

    def finished(self, path):
        return f"Saved {Path(path).name} without metadata, attachments or scripts.", path


# ----------------------------------------------------------------------------------------- OCR
class OcrPanel(ToolPanel):
    title, kind, run_text = "Make searchable (OCR)", "ocr", "Run OCR"
    description = ("Recognise the text in a scanned PDF and add an invisible text layer, so it can be searched and "
                   "copied. Works fully offline with Tesseract.")

    def build(self) -> None:
        self.src = PathRow(self.ctx)
        self.lang = QComboBox()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self._fill_langs()
        self.outdir = PathRow(self.ctx, "folder", key="output", placeholder="Same folder as the PDF")
        self.form.addRow("PDF file", self.src)
        self.form.addRow("Language", self.lang)
        self.form.addRow("Output folder", self.outdir)
        self.form.addRow(self.status)

    def _fill_langs(self) -> None:
        self.lang.clear()
        langs = ocr_engine.available_languages() if ocr_engine.is_available() else []
        names = getattr(ocr_engine, "LANGUAGE_NAMES", {})
        for code in langs or ["eng"]:
            self.lang.addItem(names.get(code, code), code)
        want = str(self.ctx.settings.get("ocr_language"))
        i = self.lang.findData(want)
        self.lang.setCurrentIndex(max(0, i))
        self.status.setText("" if langs else "Tesseract OCR was not found. Reinstall DocuCraft with the OCR "
                                              "component, or install Tesseract and restart.")

    def add_files(self, paths) -> None:
        if paths:
            self.src.setText(paths[0])

    def prepare(self):
        src = self.require_file(self.src)
        if not ocr_engine.is_available():
            raise DocuCraftError(ocr_engine.INSTALL_HINT)
        pw = unlock(self, src)
        lang = self.lang.currentData() or "eng"
        dst = sec.unique_path(self.out_dir(self.outdir, src) / f"{sec.sanitize_filename(Path(src).stem)} - searchable.pdf")
        self._src = src

        def work(progress, cancel):
            doc = sec.open_pdf(src, pw)
            try:
                todo = [i for i in range(doc.page_count) if not doc[i].get_text("text").strip()]
                if not todo:
                    raise InvalidFileError("Every page of this PDF already contains selectable text.")
                ocr_engine.make_searchable_pdf(doc, todo, lang, progress, cancel)
                tmp = dst.with_name(f".{dst.stem}.dctmp")
                watermark.stamp_pdf(doc)
                doc.save(tmp, garbage=3, deflate=True)
                tmp.replace(dst)
            finally:
                doc.close()
            return dst
        return work

    def finished(self, path):
        return f"Saved {Path(path).name}. Open it and use Find to search the recognised text.", path


# ----------------------------------------------------------------------------------------- page
TOOLS = [
    ("merge", "merge", "Merge PDF", MergePanel), ("split", "split", "Split PDF", SplitPanel),
    ("compress", "compress", "Compress PDF", CompressPanel), ("images2pdf", "image", "Images to PDF", ImagesToPdfPanel),
    ("pdf2images", "image", "PDF to Images", PdfToImagesPanel), ("extract", "extract", "Extract", ExtractPanel),
    ("ocr", "ocr", "Make searchable (OCR)", OcrPanel), ("protect", "lock", "Password protection", ProtectPanel),
    ("sanitize", "shield", "Sanitize for sharing", SanitizePanel),
]
ORGANIZE = ("merge", "split", "compress", "images2pdf", "pdf2images", "extract")
SECURITY = ("protect", "sanitize", "ocr")


class ToolsPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.list = QListWidget()
        self.list.setFixedWidth(230)
        self.list.setObjectName("SidePanel")
        self.stack = QStackedWidget()
        self.panels: dict[str, ToolPanel] = {}
        for key, ic, label, cls in TOOLS:
            it = QListWidgetItem(icon(ic, 20), label)
            it.setData(Qt.UserRole, key)
            self.list.addItem(it)
            p = cls(ctx)
            self.panels[key] = p
            self.stack.addWidget(p)
        self.list.currentRowChanged.connect(self.stack.setCurrentIndex)
        lay.addWidget(self.list)
        lay.addWidget(self.stack, 1)
        self.setAcceptDrops(True)
        self.list.setCurrentRow(0)

    def show_tool(self, key: str, files: list[str] | None = None) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == key:
                self.list.setCurrentRow(i)
                if files:
                    self.panels[key].add_files(files)
                return

    def current_key(self) -> str:
        return self.list.currentItem().data(Qt.UserRole)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        self.panels[self.current_key()].add_files(paths)
        e.acceptProposedAction()

    def retheme(self) -> None:
        for i in range(self.list.count()):
            key = self.list.item(i).data(Qt.UserRole)
            ic = next(t[1] for t in TOOLS if t[0] == key)
            self.list.item(i).setIcon(icon(ic, 20))
