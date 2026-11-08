"""Small modal dialogs: password, document info, redaction, text replacement, signature, conversion report."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from core.pdf_reader import format_size
from ui.components.widgets import open_path, reveal


# --------------------------------------------------------------------------- password
class PasswordDialog(QDialog):
    def __init__(self, parent, filename: str, wrong: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Password required")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{filename}</b> is password protected."))
        if wrong:
            err = QLabel("That password was not correct. Please try again.")
            err.setStyleSheet("color:#d92d20;")
            lay.addWidget(err)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText("Document password")
        lay.addWidget(self.edit)
        show = QCheckBox("Show password")
        show.toggled.connect(lambda on: self.edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        lay.addWidget(show)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.edit.setFocus()

    @staticmethod
    def ask(parent, filename: str, wrong: bool = False) -> str | None:
        d = PasswordDialog(parent, filename, wrong)
        return d.edit.text() if d.exec() == QDialog.Accepted else None


class NewPasswordDialog(QDialog):
    """Ask for a new password twice (used when protecting a PDF)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Protect with a password")
        self.setMinimumWidth(380)
        form = QFormLayout(self)
        self.a, self.b = QLineEdit(), QLineEdit()
        for e in (self.a, self.b):
            e.setEchoMode(QLineEdit.Password)
        form.addRow("Password", self.a)
        form.addRow("Repeat password", self.b)
        self.note = QLabel("The file is encrypted with AES-256. If you forget the password it cannot be recovered.")
        self.note.setWordWrap(True)
        self.note.setObjectName("Muted")
        form.addRow(self.note)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.accepted.connect(self._ok)
        self.bb.rejected.connect(self.reject)
        form.addRow(self.bb)

    def _ok(self) -> None:
        if not self.a.text():
            self.note.setText("Enter a password.")
        elif self.a.text() != self.b.text():
            self.note.setText("The two passwords do not match.")
        else:
            self.accept()

    @staticmethod
    def ask(parent) -> str | None:
        d = NewPasswordDialog(parent)
        return d.a.text() if d.exec() == QDialog.Accepted else None


# --------------------------------------------------------------------------- document info
class DocumentInfoDialog(QDialog):
    """Shows properties and lets the user edit the standard metadata fields."""
    FIELDS = (("title", "Title"), ("author", "Author"), ("subject", "Subject"), ("keywords", "Keywords"))

    def __init__(self, parent, info, editable: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Document information")
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        self.edits: dict[str, QLineEdit] = {}
        for key, label in self.FIELDS:
            e = QLineEdit(getattr(info, key, "") or "")
            e.setReadOnly(not editable)
            self.edits[key] = e
            form.addRow(label, e)
        rows = [("File", Path(info.path).name), ("Location", str(Path(info.path).parent)),
                ("File size", format_size(info.file_size)), ("Pages", str(info.page_count)),
                ("Page size", ", ".join(info.page_sizes) or "—"), ("PDF version", info.pdf_version or "—"),
                ("Created by", info.creator or "—"), ("Producer", info.producer or "—"),
                ("Encrypted", "Yes" if info.encrypted else "No"),
                ("Selectable text", "Yes" if info.has_text else "No (scanned/image only — use OCR)"),
                ("Repaired on open", "Yes" if info.repaired else "No")]
        for k, v in rows:
            lbl = QLabel(v)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lbl.setWordWrap(True)
            form.addRow(k, lbl)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel if editable else QDialogButtonBox.Close)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict[str, str]:
        return {k: e.text() for k, e in self.edits.items()}


# --------------------------------------------------------------------------- redaction
class RedactTextDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Redact text")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Enter the words or phrases to remove — one per line. Every match in the whole "
                             "document is <b>permanently deleted</b> (not just covered by a black box)."))
        lay.itemAt(0).widget().setWordWrap(True)
        self.terms = QPlainTextEdit()
        self.terms.setPlaceholderText("e.g.\n4111-2222-3333\njane.doe@example.com")
        lay.addWidget(self.terms)
        self.sanitize = QCheckBox("Also remove hidden data (metadata, embedded files, JavaScript)")
        self.sanitize.setChecked(True)
        lay.addWidget(self.sanitize)
        note = QLabel("You can undo until you save. After saving, the removed content cannot be recovered.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Redact permanently")
        bb.button(QDialogButtonBox.Ok).setObjectName("Danger")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> tuple[list[str], bool]:
        return [t.strip() for t in self.terms.toPlainText().splitlines() if t.strip()], self.sanitize.isChecked()


# --------------------------------------------------------------------------- replace text
class ReplaceTextDialog(QDialog):
    """Detect text in a region, enter replacement text, preview the result, then apply."""

    def __init__(self, parent, session, page: int, rect):
        super().__init__(parent)
        self.session, self.page, self.rect = session, page, rect
        self.setWindowTitle("Replace text")
        self.setMinimumSize(560, 520)
        self.style = session.editor.analyze_text(page, rect)
        lay = QVBoxLayout(self)
        warn = QLabel("<b>How this works:</b> the original words are permanently removed and your text is placed in "
                      "the same spot, using the document's own font when it can (otherwise the closest match), and the "
                      "rest of that line moves to follow it. This is <b>not</b> native PDF editing — paragraphs do not "
                      "re-wrap, so very different lengths may need a second look. Check the preview first.")
        warn.setWordWrap(True)
        warn.setStyleSheet("padding:8px; border:1px solid #f79009; border-radius:6px;")
        lay.addWidget(warn)
        self.has_text = bool(self.style.text.strip())
        if self.has_text:
            lay.addWidget(QLabel(f"Detected text (font: {self.style.font_name or 'unknown'}, "
                                 f"{self.style.fontsize:.1f} pt):"))
            orig = QPlainTextEdit(self.style.text)
            orig.setReadOnly(True)
            orig.setMaximumHeight(70)
            lay.addWidget(orig)
        else:
            lay.addWidget(QLabel("No selectable text was found in this area. If the page is a scan, run OCR first."))
        lay.addWidget(QLabel("Replacement text:"))
        self.new_text = QPlainTextEdit(self.style.text)
        self.new_text.setMaximumHeight(90)
        lay.addWidget(self.new_text)
        row = QHBoxLayout()
        self.size = QSpinBox()
        self.size.setRange(4, 200)
        self.size.setValue(int(round(self.style.fontsize)))
        row.addWidget(QLabel("Font size"))
        row.addWidget(self.size)
        row.addStretch(1)
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.clicked.connect(self.preview)
        row.addWidget(self.preview_btn)
        lay.addLayout(row)
        self.preview_lbl = QLabel("Click Preview to see the result before applying it.")
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setMinimumHeight(150)
        self.preview_lbl.setObjectName("Muted")
        lay.addWidget(self.preview_lbl, 1)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText("Apply replacement")
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        lay.addWidget(self.bb)

    def current_style(self):
        st = self.style
        st.fontsize = float(self.size.value())
        return st

    def preview(self) -> None:
        png = self.session.editor.preview_replace(self.page, self.rect, self.new_text.toPlainText(), self.current_style())
        pm = QPixmap()
        pm.loadFromData(png)
        self.preview_lbl.setPixmap(pm.scaled(self.preview_lbl.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def values(self):
        return self.new_text.toPlainText(), self.current_style()


# --------------------------------------------------------------------------- signature
class _SignaturePad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(460, 170)
        self.strokes: list[list[QPointF]] = []
        self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, e) -> None:
        self.strokes.append([e.position()])

    def mouseMoveEvent(self, e) -> None:
        if self.strokes:
            self.strokes[-1].append(e.position())
            self.update()

    def clear(self) -> None:
        self.strokes.clear()
        self.update()

    def _path(self, stroke) -> QPainterPath:
        p = QPainterPath(stroke[0])
        for pt in stroke[1:]:
            p.lineTo(pt)
        return p

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QPen(QColor("#c8ced9"), 1, Qt.DashLine))
        p.drawLine(16, self.height() - 38, self.width() - 16, self.height() - 38)
        p.setPen(QPen(QColor("#10243f"), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for s in self.strokes:
            if len(s) == 1:
                p.drawPoint(s[0])
            else:
                p.drawPath(self._path(s))

    def to_image(self) -> QImage | None:
        if not any(len(s) > 1 for s in self.strokes):
            return None
        img = QImage(self.size() * 2, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(2, 2)
        p.setPen(QPen(QColor("#10243f"), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for s in self.strokes:
            if len(s) > 1:
                p.drawPath(self._path(s))
        p.end()
        # crop to the ink
        xs = [pt.x() for s in self.strokes for pt in s]
        ys = [pt.y() for s in self.strokes for pt in s]
        x0, x1, y0, y1 = max(0, min(xs) - 6), min(self.width(), max(xs) + 6), max(0, min(ys) - 6), min(self.height(), max(ys) + 6)
        return img.copy(int(x0 * 2), int(y0 * 2), int((x1 - x0) * 2), int((y1 - y0) * 2))


class SignatureDialog(QDialog):
    """Draw a signature with the mouse; saved as a transparent PNG for placing on a page."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Draw your signature")
        lay = QVBoxLayout(self)
        self.pad = _SignaturePad()
        lay.addWidget(self.pad)
        hint = QLabel("This is an image of your handwriting, not a certificate-based digital signature.")
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        row = QHBoxLayout()
        clear = QPushButton("Clear")
        clear.clicked.connect(self.pad.clear)
        row.addWidget(clear)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)
        self.image: QImage | None = None

    def _ok(self) -> None:
        self.image = self.pad.to_image()
        if self.image is not None:
            self.accept()

    def save_to(self, path) -> Path:
        self.image.save(str(path), "PNG")
        return Path(path)


# --------------------------------------------------------------------------- conversion report
class ReportDialog(QDialog):
    def __init__(self, parent, title: str, text: str, output: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(560, 460)
        lay = QVBoxLayout(self)
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        box.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(box)
        row = QHBoxLayout()
        row.addStretch(1)
        if output and Path(output).exists():
            o = QPushButton("Open file")
            o.setObjectName("Primary")
            o.clicked.connect(lambda: open_path(output))
            f = QPushButton("Show in folder")
            f.clicked.connect(lambda: reveal(output))
            row.addWidget(f)
            row.addWidget(o)
        c = QPushButton("Close")
        c.clicked.connect(self.accept)
        row.addWidget(c)
        lay.addLayout(row)


# --------------------------------------------------------------------------- helper
def unlock(parent, path) -> str | None:
    """Return the password for an encrypted PDF (asking up to 3 times), or None if it is not encrypted.

    Raises OperationCancelled if the user cancels or fails three times."""
    from core import pdf_security as sec
    from core.errors import OperationCancelled
    p = Path(path)
    if not sec.is_encrypted(p):
        return None
    wrong = False
    for _ in range(3):
        pw = PasswordDialog.ask(parent, p.name, wrong)
        if pw is None:
            raise OperationCancelled()
        try:
            sec.open_pdf(p, pw).close()
            return pw
        except Exception:
            wrong = True
    raise OperationCancelled()
