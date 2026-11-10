"""Print preview built from DocuCraft's own page renderer.

Qt's stock QPrintPreviewDialog crashed the whole app on some Windows machines, and a crash inside Qt cannot be
caught from Python, so the preview is drawn here from plain page images instead. It shows the pages exactly as
the reader renders them (unsaved edits included) and hands over to the normal Print dialog.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

ZOOMS = (0.4, 0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0)


class PrintPreviewDialog(QDialog):
    def __init__(self, parent, session, on_print):
        super().__init__(parent)
        self.session = session
        self._on_print = on_print
        self._zoom_i = 3          # 0.8 of the screen size to start with
        self._labels: list[QLabel] = []
        self._drawn: dict[int, float] = {}
        self.setWindowTitle(f"Print preview - {session.name}")
        self.resize(900, 760)

        top = QHBoxLayout()
        self.btn_print = QPushButton("Print…")
        self.btn_print.setDefault(True)
        self.btn_print.clicked.connect(self._print)
        self.btn_out = QPushButton("Zoom out")
        self.btn_out.clicked.connect(lambda: self._set_zoom(self._zoom_i - 1))
        self.btn_in = QPushButton("Zoom in")
        self.btn_in.clicked.connect(lambda: self._set_zoom(self._zoom_i + 1))
        self.lbl = QLabel()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        for w in (self.btn_print, self.btn_out, self.btn_in):
            top.addWidget(w)
        top.addWidget(self.lbl, 1)
        top.addWidget(self.btn_close)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.holder = QWidget()
        self.col = QVBoxLayout(self.holder)
        self.col.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.col.setSpacing(14)
        self.scroll.setWidget(self.holder)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda *_: self._draw_visible())

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.scroll, 1)

        self._build()

    # ------------------------------------------------------------------ pages
    @property
    def zoom(self) -> float:
        return ZOOMS[self._zoom_i]

    def _build(self) -> None:
        for lb in self._labels:
            lb.deleteLater()
        self._labels.clear()
        self._drawn.clear()
        n = self.session.page_count
        reader = self.session.reader
        for i in range(n):
            w, h = reader.page_size(i)
            lb = QLabel(f"Page {i + 1}")
            lb.setAlignment(Qt.AlignCenter)
            lb.setStyleSheet("background:#ffffff; color:#999999; border:1px solid #bbbbbb;")
            lb.setFixedSize(max(40, int(w * self.zoom * 1.33)), max(40, int(h * self.zoom * 1.33)))
            self.col.addWidget(lb, 0, Qt.AlignHCenter)
            self._labels.append(lb)
        self.lbl.setText(f"{n} page{'s' if n != 1 else ''} · zoom {int(self.zoom * 100)}%")
        self.btn_out.setEnabled(self._zoom_i > 0)
        self.btn_in.setEnabled(self._zoom_i < len(ZOOMS) - 1)
        self.draw_page(0)
        QTimer.singleShot(0, self._draw_visible)

    def draw_page(self, i: int) -> None:
        """Render one page into its label (skipped when it is already drawn at this zoom)."""
        if not (0 <= i < len(self._labels)) or self._drawn.get(i) == self.zoom:
            return
        lb = self._labels[i]
        pix = self.session.reader.render(i, zoom=self.zoom * 1.33)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        lb.setPixmap(QPixmap.fromImage(img))
        lb.setFixedSize(img.size())
        self._drawn[i] = self.zoom

    def _draw_visible(self) -> None:
        bar = self.scroll.verticalScrollBar()
        top, bottom = bar.value(), bar.value() + self.scroll.viewport().height()
        for i, lb in enumerate(self._labels):
            y = lb.y()
            if y + lb.height() >= top - 200 and y <= bottom + 200:
                self.draw_page(i)

    def _set_zoom(self, i: int) -> None:
        i = max(0, min(len(ZOOMS) - 1, i))
        if i != self._zoom_i:
            self._zoom_i = i
            self._build()

    def _print(self) -> None:
        self._on_print()
