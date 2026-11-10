"""One open PDF: side panels + canvas + ribbons. Translates canvas gestures into editor operations."""
from __future__ import annotations

import time
from pathlib import Path

import pymupdf
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QImage, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QMenu, QMessageBox, QSlider, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from app import theme
from core import pdf_security as sec
from core.errors import DocuCraftError, OverwriteNotConfirmed
from core.pdf_reader import format_size
from ui.components.find_bar import FindBar
from ui.components.pdf_view import PdfView
from ui.components.side_panels import OutlinePanel, ThumbnailPanel
from ui.components.widgets import (confirm, icon, message, retheme_buttons, separator, show_error, tool_button)
from ui.dialogs.dialogs import (DocumentInfoDialog, RedactTextDialog, ReplaceTextDialog, SignatureDialog)

MARKUP_TO_EDITOR = {"highlight": "highlight", "underline": "underline", "strike": "strikeout"}
TOOL_DEFAULTS = {            # colour (0-1 RGB), opacity
    "highlight": ((1.0, 0.92, 0.0), 0.5), "underline": ((0.10, 0.35, 0.85), 1.0), "strike": ((0.86, 0.12, 0.12), 1.0),
    "note": ((1.0, 0.85, 0.0), 1.0), "text": ((0.0, 0.0, 0.0), 1.0), "pen": ((0.86, 0.12, 0.12), 1.0),
    "line": ((0.86, 0.12, 0.12), 1.0), "arrow": ((0.86, 0.12, 0.12), 1.0), "rect": ((0.86, 0.12, 0.12), 1.0),
    "ellipse": ((0.86, 0.12, 0.12), 1.0),
}
PALETTE = [("Yellow", (1.0, 0.92, 0.0)), ("Green", (0.2, 0.75, 0.35)), ("Blue", (0.1, 0.35, 0.85)),
           ("Red", (0.86, 0.12, 0.12)), ("Orange", (1.0, 0.55, 0.0)), ("Black", (0.0, 0.0, 0.0))]
EDIT_TOOLS = [("select", "cursor", "Select / move objects"), ("highlight", "highlight", "Highlight text"),
              ("underline", "underline", "Underline text"), ("strike", "strike", "Strike through text"),
              ("note", "note", "Sticky note / comment"), ("text", "text", "Text box"), ("pen", "pen", "Freehand draw"),
              ("line", "line", "Line"), ("arrow", "arrow", "Arrow"), ("rect", "rect", "Rectangle"),
              ("ellipse", "ellipse", "Circle / ellipse")]


def _rgb_qcolor(c) -> QColor:
    return QColor.fromRgbF(*c)


def _swatch(c) -> QImage:
    from PySide6.QtGui import QPixmap
    pm = QPixmap(18, 18)
    pm.fill(_rgb_qcolor(c))
    return pm


class DocumentTab(QWidget):
    statusChanged = Signal()
    titleChanged = Signal(object)
    fullscreenRequested = Signal()

    def __init__(self, ctx, session, parent=None):
        super().__init__(parent)
        self.ctx, self.session = ctx, session
        self._pending_image: str | None = None
        self._updating = False
        self._search_seq = 0
        self._ribbon_mode = "view"
        s = ctx.settings
        self.view = PdfView(session, base_dpi=s.render_dpi, cache_pages=int(s.get("render_cache_pages")))
        self.view.set_layout(str(s.get("page_layout")))
        self.thumbs = ThumbnailPanel(session)
        self.outline = OutlinePanel(session)
        self.find = FindBar()

        self.side = QTabWidget()
        self.side.setObjectName("SidePanel")
        self.side.addTab(self.thumbs, "Pages")
        self.side.addTab(self.outline, "Bookmarks")
        self.side.setMinimumWidth(200)
        self.side.setMaximumWidth(340)

        self.ribbon = QStackedWidget()
        self.ribbon.setObjectName("Ribbon")
        self.ribbon.addWidget(self._build_view_ribbon())
        self.ribbon.addWidget(self._build_edit_ribbon())

        self.split = QSplitter(Qt.Horizontal)
        self.split.addWidget(self.side)
        self.split.addWidget(self.view)
        self.split.setSizes([200, 900])
        self.split.setStretchFactor(1, 1)
        self.split.setChildrenCollapsible(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.ribbon)
        lay.addWidget(self.find)
        lay.addWidget(self.split, 1)

        self._wire()
        self._shortcuts()
        self.view.apply_default_zoom(s.get("default_zoom"))
        self.set_tool("select")
        self._sync_all()

    # ------------------------------------------------------------------ ribbons
    def _build_view_ribbon(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Ribbon")
        h = QHBoxLayout(w)
        h.setContentsMargins(10, 4, 10, 4)
        h.setSpacing(2)
        v = self.view
        self.btn_side = tool_button("sidebar", "Show / hide page panel", checkable=True, shortcut="F4")
        self.btn_side.setChecked(True)
        self.btn_side.toggled.connect(self.side.setVisible)
        h.addWidget(self.btn_side)
        h.addWidget(separator())
        h.addWidget(tool_button("first", "First page", shortcut="Ctrl+Home", slot=v.first_page))
        h.addWidget(tool_button("prev", "Previous page", slot=v.prev_page))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setFixedWidth(64)
        self.page_spin.setToolTip("Go to page")
        h.addWidget(self.page_spin)
        self.page_total = QLabel("/ 1")
        self.page_total.setObjectName("Muted")
        h.addWidget(self.page_total)
        h.addWidget(tool_button("next", "Next page", slot=v.next_page))
        h.addWidget(tool_button("last", "Last page", shortcut="Ctrl+End", slot=v.last_page))
        h.addWidget(separator())
        h.addWidget(tool_button("zoom_out", "Zoom out", shortcut="Ctrl+-", slot=v.zoom_out))
        self.zoom_box = QComboBox()
        self.zoom_box.setEditable(True)
        self.zoom_box.setFixedWidth(98)
        self.zoom_box.addItems(["Fit width", "Fit page", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"])
        self.zoom_box.setToolTip("Zoom")
        h.addWidget(self.zoom_box)
        h.addWidget(tool_button("zoom_in", "Zoom in", shortcut="Ctrl++", slot=v.zoom_in))
        h.addWidget(tool_button("fit_width", "Fit width", shortcut="Ctrl+1", slot=v.fit_width))
        h.addWidget(tool_button("fit_page", "Fit page", shortcut="Ctrl+0", slot=v.fit_page))
        h.addWidget(separator())
        h.addWidget(tool_button("rotate", "Rotate view", shortcut="Ctrl+R", slot=v.rotate_view))
        lay_btn = tool_button("scroll", "Page layout")
        lay_btn.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(lay_btn)
        for label, mode, ic in (("Single page", "single", "onepage"), ("Continuous scroll", "continuous", "scroll"),
                                ("Two pages", "two", "twopage")):
            a = m.addAction(icon(ic, 18), label)
            a.triggered.connect(lambda _=False, md=mode: v.set_layout(md))
        lay_btn.setMenu(m)
        h.addWidget(lay_btn)
        h.addWidget(tool_button("fullscreen", "Full screen", shortcut="F11", slot=self.fullscreenRequested.emit))
        h.addWidget(separator())
        h.addWidget(tool_button("search", "Find in document", shortcut="Ctrl+F", slot=self.open_find))
        h.addWidget(tool_button("print", "Print", shortcut="Ctrl+P", slot=self.print_document))
        h.addWidget(tool_button("preview", "Print preview", shortcut="Ctrl+Shift+P", slot=self.print_preview))
        h.addWidget(tool_button("info", "Document information", shortcut="Ctrl+D", slot=self.show_info))
        h.addStretch(1)
        return w

    def _build_edit_ribbon(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Ribbon")
        h = QHBoxLayout(w)
        h.setContentsMargins(10, 4, 10, 4)
        h.setSpacing(2)
        self.btn_undo = tool_button("undo", "Undo", shortcut="Ctrl+Z", slot=self.undo)
        self.btn_redo = tool_button("redo", "Redo", shortcut="Ctrl+Y", slot=self.redo)
        h.addWidget(self.btn_undo)
        h.addWidget(self.btn_redo)
        h.addWidget(separator())
        self.tool_btns: dict[str, QToolButton] = {}
        for name, ic, tip in EDIT_TOOLS:
            b = tool_button(ic, tip, checkable=True)
            b.clicked.connect(lambda _=False, n=name: self.set_tool(n))
            self.tool_btns[name] = b
            h.addWidget(b)
        h.addWidget(separator())
        h.addWidget(tool_button("image", "Insert image", slot=self.insert_image))
        h.addWidget(tool_button("signature", "Add signature image", slot=self.add_signature))
        rep = tool_button("replace", "Replace existing text (redact + overlay)", checkable=True)
        rep.clicked.connect(lambda: self.set_tool("replace"))
        red = tool_button("redact", "Redact area (permanent removal)", checkable=True)
        red.clicked.connect(lambda: self.set_tool("redact"))
        self.tool_btns["replace"], self.tool_btns["redact"] = rep, red
        h.addWidget(rep)
        h.addWidget(red)
        h.addWidget(separator())
        self.color_btn = QToolButton()
        self.color_btn.setToolTip("Colour")
        self.color_btn.setPopupMode(QToolButton.InstantPopup)
        cm = QMenu(self.color_btn)
        for label, c in PALETTE:
            a = cm.addAction(icon_from_pix(_swatch(c)), label)
            a.triggered.connect(lambda _=False, col=c: self._user_color(col))
        cm.addSeparator()
        cm.addAction("More colours…").triggered.connect(self._pick_color)
        self.color_btn.setMenu(cm)
        h.addWidget(self.color_btn)
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(10, 100)
        self.opacity.setFixedWidth(84)
        self.opacity.setToolTip("Opacity")
        h.addWidget(self.opacity)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 96)
        self.size_spin.setSuffix(" pt")
        self.size_spin.setToolTip("Font size (text box) / line width")
        self.size_spin.setFixedWidth(78)
        h.addWidget(self.size_spin)
        h.addWidget(separator())
        pg = tool_button("layers", "Page tools", text="Pages")
        pg.setPopupMode(QToolButton.InstantPopup)
        pm = QMenu(pg)
        for text, act in (("Insert blank page", "insert_blank"), ("Duplicate page", "duplicate"),
                          ("Rotate page right", "rotate_cw"), ("Rotate page left", "rotate_ccw"),
                          ("Extract page(s)…", "extract"), ("Replace page(s) from another PDF…", "replace"),
                          ("Delete page", "delete")):
            pm.addAction(text).triggered.connect(lambda _=False, a=act: self._pages_action(a, self._target_pages()))
        pg.setMenu(pm)
        h.addWidget(pg)
        sv = tool_button("save", "Save / export", text="Save")
        sv.setPopupMode(QToolButton.MenuButtonPopup)
        sv.clicked.connect(lambda: self.save())
        sm = QMenu(sv)
        sm.addAction("Save (replace original)…", lambda: self.save())
        sm.addAction("Save As…", lambda: self.save_as())
        sm.addAction("Save a copy…", lambda: self.save_copy())
        sm.addSeparator()
        sm.addAction("Export flattened PDF (keep text)…", lambda: self.export_flattened("annotations"))
        sm.addAction("Export as image-only PDF…", lambda: self.export_flattened("image"))
        sv.setMenu(sm)
        h.addWidget(sv)
        h.addStretch(1)
        return w

    # ------------------------------------------------------------------ wiring
    def _wire(self) -> None:
        v, s = self.view, self.session
        v.pageChanged.connect(self._on_page)
        v.zoomChanged.connect(self._on_zoom)
        v.toolCompleted.connect(self._tool_done)
        v.annotationMoved.connect(lambda p, x, r: self._edit("move_annotation", p, x, pymupdf.Rect(r)))
        v.annotationDeleteRequested.connect(lambda p, x: self._edit("delete_annotation", p, x))
        v.annotationSelected.connect(lambda *_: self._sync_style_from_selection())
        v.layoutChanged.connect(self.statusChanged.emit)
        v.setContextMenuPolicy(Qt.CustomContextMenu)
        v.customContextMenuRequested.connect(self._context_menu)
        s.changed.connect(self._on_changed)
        s.dirtyChanged.connect(lambda _: self.titleChanged.emit(self))
        s.saved.connect(lambda _: self.titleChanged.emit(self))
        self.thumbs.pageActivated.connect(v.go_to_page)
        self.thumbs.pagesAction.connect(self._pages_action)
        self.thumbs.reordered.connect(lambda order: self._edit("reorder", order))
        self.outline.pageActivated.connect(v.go_to_page)
        self.page_spin.valueChanged.connect(lambda n: None if self._updating else v.go_to_page(n - 1))
        self.zoom_box.activated.connect(lambda *_: self._zoom_text(self.zoom_box.currentText()))
        self.zoom_box.lineEdit().returnPressed.connect(lambda: self._zoom_text(self.zoom_box.currentText()))
        self.find.searchRequested.connect(self._do_search)
        self.find.stepRequested.connect(self._step_search)
        self.find.closed.connect(lambda: (v.clear_search(), v.setFocus()))
        self.opacity.valueChanged.connect(self._user_style)
        self.size_spin.valueChanged.connect(self._user_style)

    def _shortcuts(self) -> None:
        """Registered on the tab (not on buttons) so they work whichever ribbon is showing."""
        v = self.view
        table = [("Ctrl+Home", v.first_page), ("Ctrl+End", v.last_page), ("Ctrl+-", v.zoom_out), ("Ctrl++", v.zoom_in),
                 ("Ctrl+=", v.zoom_in), ("Ctrl+1", v.fit_width), ("Ctrl+0", v.fit_page), ("Ctrl+R", v.rotate_view),
                 ("F11", self.fullscreenRequested.emit), ("Ctrl+F", self.open_find), ("Ctrl+P", self.print_document), ("Ctrl+Shift+P", self.print_preview),
                 ("Ctrl+D", self.show_info), ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                 ("F3", lambda: self._step_search(1)), ("Shift+F3", lambda: self._step_search(-1)),
                 ("F4", lambda: self.btn_side.toggle())]
        self._sc = []
        for keys, fn in table:
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            self._sc.append(sc)

    def set_ribbon(self, mode: str) -> None:
        self._ribbon_mode = mode
        self.ribbon.setCurrentIndex(1 if mode == "edit" else 0)
        if mode != "edit":
            self.set_tool("select")

    # ------------------------------------------------------------------ status sync
    def _sync_all(self) -> None:
        n = self.session.page_count
        self._updating = True
        self.page_spin.setMaximum(max(1, n))
        self.page_spin.setValue(self.view.current_page + 1)
        self.page_total.setText(f"/ {n}")
        self._updating = False
        self._on_zoom(self.view.zoom)
        self.btn_undo.setEnabled(self.session.editor.can_undo)
        self.btn_redo.setEnabled(self.session.editor.can_redo)
        self.btn_undo.setToolTip(f"Undo {self.session.editor.undo_label}".strip() + "  (Ctrl+Z)")
        self.statusChanged.emit()

    def _on_changed(self) -> None:
        self.thumbs.rebuild()
        self.outline.fill(self.session)
        self._sync_all()

    def _on_page(self, i: int) -> None:
        self._updating = True
        self.page_spin.setValue(i + 1)
        self._updating = False
        self.thumbs.highlight(i)
        self.statusChanged.emit()

    def _on_zoom(self, z: float) -> None:
        txt = {"width": "Fit width", "page": "Fit page"}.get(self.view.fit_mode or "", f"{round(z * 100)}%")
        self.zoom_box.blockSignals(True)
        self.zoom_box.setCurrentText(txt)
        self.zoom_box.blockSignals(False)
        self.statusChanged.emit()

    def _zoom_text(self, text: str) -> None:
        t = text.strip().lower().replace("%", "")
        if t.startswith("fit w") or t == "fit width":
            self.view.fit_width()
        elif t.startswith("fit p") or t == "fit page":
            self.view.fit_page()
        else:
            try:
                self.view.set_zoom(float(t) / 100.0)
            except ValueError:
                self._on_zoom(self.view.zoom)
        self.view.setFocus()

    def status_info(self) -> tuple[int, int, int, str]:
        return (self.view.current_page + 1, self.session.page_count, self.view.zoom_percent,
                format_size(self.session.file_size))

    def title(self) -> str:
        return ("• " if self.session.dirty else "") + self.session.name

    # ------------------------------------------------------------------ tools
    def set_tool(self, name: str) -> None:
        if name not in self.tool_btns:
            name = "select"
        for n, b in self.tool_btns.items():
            b.setChecked(n == name)
        self.view.set_tool(name)
        if name in TOOL_DEFAULTS:
            col, op = TOOL_DEFAULTS[name]
            self.view.set_style(color=col, opacity=op)
        elif name in ("replace", "redact"):
            self.view.set_style(color=(0.0, 0.0, 0.0), opacity=1.0)
        self._refresh_style_controls()

    def _refresh_style_controls(self) -> None:
        st = self.view.style
        self._updating = True
        self.color_btn.setIcon(icon_from_pix(_swatch(st["color"])))
        self.opacity.setValue(int(st["opacity"] * 100))
        self.size_spin.setValue(int(st["fontsize"] if self.view.tool == "text" else st["stroke"]))
        self._updating = False

    def _user_color(self, col) -> None:
        self.view.set_style(color=col)
        self._refresh_style_controls()
        self._restyle_selected(color=col)

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(_rgb_qcolor(self.view.style["color"]), self, "Choose colour")
        if c.isValid():
            self._user_color((c.redF(), c.greenF(), c.blueF()))

    def _user_style(self, *_) -> None:
        if self._updating:
            return
        op = self.opacity.value() / 100.0
        if self.view.tool == "text":
            self.view.set_style(opacity=op, fontsize=float(self.size_spin.value()))
        else:
            self.view.set_style(opacity=op, stroke=float(self.size_spin.value()))
        self._restyle_selected(opacity=op)

    def _restyle_selected(self, **kw) -> None:
        sel = self.view.selected_annotation()
        if sel:
            self._edit("restyle_annotation", sel[0], sel[1], **kw)
            self.view.select_annotation(*sel)

    def _sync_style_from_selection(self) -> None:
        sel = self.view.selected_annotation()
        if not sel:
            return
        with self.session.reader.lock:
            for a in self.session.doc[sel[0]].annots() or []:
                if a.xref == sel[1]:
                    self._updating = True
                    self.opacity.setValue(int(round(a.opacity * 100)) if a.opacity >= 0 else 100)
                    self._updating = False
                    break

    # ------------------------------------------------------------------ editing
    def _edit(self, method: str, *args, **kwargs):
        """Run an editor operation; show a friendly error instead of raising into Qt."""
        try:
            return self.session.edit(method, *args, **kwargs)
        except DocuCraftError as exc:
            show_error(self, exc)
        except Exception as exc:                                            # pragma: no cover - defensive
            show_error(self, exc)
        return None

    def undo(self) -> None:
        self.session.undo()

    def redo(self) -> None:
        self.session.redo()

    def _tool_done(self, kind: str, page: int, payload) -> None:
        st = self.view.style
        col, op = st["color"], st["opacity"]
        if kind in MARKUP_TO_EDITOR:
            self._edit("add_markup", page, MARKUP_TO_EDITOR[kind], [pymupdf.Rect(r) for r in payload], color=col, opacity=op)
        elif kind == "note":
            text, ok = QInputDialog.getMultiLineText(self, "Sticky note", "Comment:")
            if ok and text.strip():
                self._edit("add_note", page, payload, text, author="")
        elif kind == "text":
            text, ok = QInputDialog.getMultiLineText(self, "Text box", "Text:")
            if ok and text.strip():
                self._edit("add_text_box", page, payload, text, fontsize=st["fontsize"], color=col, opacity=op)
        elif kind == "pen":
            self._edit("add_freehand", page, payload, color=col, width=st["stroke"], opacity=op)
        elif kind in ("line", "arrow"):
            self._edit("add_line", page, payload[0], payload[1], color=col, width=st["stroke"], arrow=kind == "arrow", opacity=op)
        elif kind in ("rect", "ellipse"):
            self._edit("add_shape", page, kind, payload, color=col, width=st["stroke"], opacity=op)
        elif kind == "image":
            path = self._pending_image
            if not path:
                return
            self._pending_image = None
            self._edit("add_image", page, payload, path, name=self._pending_name)
            self.set_tool("select")
        elif kind == "redact":
            if confirm(self, "Redact area",
                       "Everything inside this area (text, images and drawings) will be <b>permanently removed</b> "
                       "from the document.\n\nYou can undo until you save.", yes="Redact permanently", danger=True):
                self._edit("redact_regions", [(page, tuple(payload))])
        elif kind == "replace":
            self._replace_text(page, pymupdf.Rect(payload))

    _pending_name = "Image"

    def insert_image(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose an image", str(self.ctx.files.last_dir("image")),
                                           "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)")
        if f:
            self.ctx.files.remember_dir("image", f)
            self._pending_image, self._pending_name = f, "Image"
            self.set_ribbon("edit")
            for b in self.tool_btns.values():
                b.setChecked(False)
            self.view.set_tool("image")
            message(self, "Insert image", "Drag a rectangle on the page where the image should go. "
                                          "You can move and resize it afterwards with the Select tool.")

    def add_signature(self) -> None:
        d = SignatureDialog(self)
        if d.exec() and d.image is not None:
            p = d.save_to(sec.temp_dir() / f"signature_{int(time.time() * 1000)}.png")
            self._pending_image, self._pending_name = str(p), "Signature"
            self.set_ribbon("edit")
            for b in self.tool_btns.values():
                b.setChecked(False)
            self.view.set_tool("image")
            message(self, "Place signature", "Drag a rectangle on the page where the signature should go.")

    def _replace_text(self, page: int, rect: pymupdf.Rect) -> None:
        try:
            dlg = ReplaceTextDialog(self, self.session, page, rect)
        except DocuCraftError as exc:
            show_error(self, exc)
            return
        if dlg.exec():
            new_text, style = dlg.values()
            if not new_text.strip() and not confirm(self, "Replace text", "The replacement text is empty, so the "
                                                    "selected text will simply be removed. Continue?", yes="Remove text"):
                return
            res = self._edit("replace_text", page, rect, new_text, style)
            if res is not None:
                self.ctx_status(f"Text replaced using {res.font_used} at {res.fit_fontsize:.1f} pt (overlay, not native editing).")

    def ctx_status(self, text: str) -> None:
        w = self.window()
        if hasattr(w, "flash"):
            w.flash(text)

    def redact_text_dialog(self) -> None:
        d = RedactTextDialog(self)
        if not d.exec():
            return
        terms, sanitize = d.values()
        if not terms:
            return
        rep = self._edit("redact_text", terms, sanitize=sanitize)
        if rep is None:
            return
        leftovers = [t for t in terms if not self.session.editor.verify_removed(t)]
        if rep.terms_found == 0:
            message(self, "Redaction", "None of those terms were found in this document.")
        elif leftovers:
            message(self, "Redaction check", "Redacted, but these terms can still be found by text extraction "
                    "(they may be inside images or split across lines):\n\n• " + "\n• ".join(leftovers), "warn")
        else:
            message(self, "Redaction complete", f"{rep.terms_found} match(es) on {len(set(rep.pages))} page(s) were "
                    "permanently removed and verified: the text can no longer be found by ordinary text extraction.\n\n"
                    "Save the document to make this permanent.")

    def sanitize_document(self) -> None:
        if confirm(self, "Sanitize document", "Remove metadata, embedded files, JavaScript and hidden text from this "
                   "document? You can undo until you save.", yes="Sanitize"):
            self._edit("sanitize")

    # ------------------------------------------------------------------ pages
    def _target_pages(self) -> list[int]:
        return self.thumbs.selected_pages() or [self.view.current_page]

    def _pages_action(self, action: str, pages: list[int]) -> None:
        if not pages:
            return
        pages = sorted(pages)
        if action == "rotate_cw":
            self._edit("rotate_pages", pages, 90)
        elif action == "rotate_ccw":
            self._edit("rotate_pages", pages, -90)
        elif action == "duplicate":
            for p in reversed(pages):
                self._edit("duplicate_page", p)
        elif action == "insert_blank":
            self._edit("insert_blank_page", after=pages[-1])
        elif action == "delete":
            if len(pages) >= self.session.page_count:
                message(self, "Delete pages", "A PDF must keep at least one page.", "warn")
            elif confirm(self, "Delete pages", f"Delete {len(pages)} page(s)? You can undo until you save.",
                         yes="Delete", danger=True):
                self._edit("delete_pages", pages)
        elif action == "extract":
            f, _ = QFileDialog.getSaveFileName(self, "Extract pages to…", str(self.ctx.files.last_dir("save") / (self.session.path.stem + "_extract.pdf")), "PDF (*.pdf)")
            if f:
                try:
                    self.session.editor.extract_pages(pages, f, overwrite=True)
                    self.ctx.files.remember_dir("save", f)
                    self.ctx_status(f"Extracted {len(pages)} page(s) to {Path(f).name}")
                except DocuCraftError as exc:
                    show_error(self, exc)
        elif action == "replace":
            self._replace_pages(pages)

    def _replace_pages(self, pages: list[int]) -> None:
        if pages != list(range(pages[0], pages[0] + len(pages))):
            message(self, "Replace pages", "Select a block of consecutive pages to replace.", "warn")
            return
        f, _ = QFileDialog.getOpenFileName(self, "Take replacement pages from…", str(self.ctx.files.last_dir("open")), "PDF (*.pdf)")
        if not f:
            return
        start, ok = QInputDialog.getInt(self, "Replace pages", f"First page to copy from {Path(f).name}:", 1, 1, 100000)
        if ok:
            self._edit("replace_pages", pages[0], len(pages), f, source_pages=list(range(start - 1, start - 1 + len(pages))))

    # ------------------------------------------------------------------ search
    def open_find(self) -> None:
        self.find.open_bar(self.view.selected_text().split("\n")[0][:80])

    def _do_search(self, text: str, case: bool) -> None:
        self._search_seq += 1
        seq = self._search_seq
        if not text.strip():
            self.view.clear_search()
            self.find.set_result(-1, 0)
            return
        if self.session.page_count <= 60:
            self._show_hits(seq, self.session.search_sync(text, case))
            return
        self.find.set_result(-1, 0, searching=True)
        self.ctx.jobs.submit("search", lambda progress, cancel: self.session.search_sync(text, case),
                             on_finished=lambda hits, s=seq: self._show_hits(s, hits), on_failed=lambda e: None)

    def _show_hits(self, seq: int, hits) -> None:
        if seq != self._search_seq:
            return
        self.view.set_search(hits, 0 if hits else -1)
        self.find.set_result(0 if hits else -1, len(hits))

    def _step_search(self, d: int) -> None:
        n = len(self.view._hit_list)
        if n:
            self.view.show_hit(self.view.hit_index + d)
            self.find.set_result(self.view.hit_index, n)

    # ------------------------------------------------------------------ info / print / context menu
    def show_info(self) -> None:
        info = self.session.reader.info()
        d = DocumentInfoDialog(self, info)
        if d.exec():
            vals = d.values()
            old = {k: getattr(info, k, "") or "" for k in vals}
            if vals != old:
                self._edit("set_metadata", **vals)

    def _context_menu(self, pos) -> None:
        m = QMenu(self)
        txt = self.view.selected_text()
        a = m.addAction("Copy", self.view.copy_selection)
        a.setEnabled(bool(txt))
        m.addAction("Select all on page", self.view.select_all_on_page)
        sel = self.view.selected_annotation()
        if sel:
            m.addSeparator()
            m.addAction("Delete annotation", lambda: self._edit("delete_annotation", sel[0], sel[1]))
        m.exec(self.view.viewport().mapToGlobal(pos))

    def print_document(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setOption(QPrintDialog.PrintPageRange, True)
        dlg.setMinMax(1, self.session.page_count)
        if dlg.exec():
            self._print_safely(printer)

    def preview_dialog(self):
        """Build (without showing) the print preview of the document as it is now, edits included."""
        from ui.dialogs.print_preview import PrintPreviewDialog
        return PrintPreviewDialog(self, self.session, self.print_document)

    def print_preview(self) -> None:
        try:
            self.preview_dialog().exec()
        except Exception as e:  # never let a printing problem take the app down
            show_error(self, e, "Print preview")

    def _print_safely(self, printer) -> None:
        try:
            self.print_to(printer)
        except Exception as e:  # a printer problem must never close the app
            show_error(self, e, "Print")

    def print_to(self, printer) -> int:
        """Render the chosen pages onto `printer`. Returns pages printed."""
        from PySide6.QtCore import QRect
        n = self.session.page_count
        first, last = (printer.fromPage(), printer.toPage()) if printer.fromPage() else (1, n)
        last = min(last or n, n)
        painter = QPainter()
        if not painter.begin(printer):
            raise DocuCraftError("The printer could not be started.")
        done = 0
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i in range(first - 1, last):
                if done:
                    printer.newPage()
                dpi = min(300, max(150, printer.resolution()))
                pix = self.session.reader.render(i, zoom=dpi / 72.0)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
                target = painter.viewport()
                scaled = img.size().scaled(target.size(), Qt.KeepAspectRatio)
                painter.drawImage(QRect(target.x() + (target.width() - scaled.width()) // 2,
                                        target.y() + (target.height() - scaled.height()) // 2,
                                        scaled.width(), scaled.height()), img)
                done += 1
                QApplication.processEvents()
        finally:
            painter.end()
            QApplication.restoreOverrideCursor()
        return done

    # ------------------------------------------------------------------ saving
    def save(self) -> bool:
        s = self.session
        if not s.dirty:
            return True
        if not confirm(self, "Save changes", f"Replace the original file <b>{s.name}</b> with the edited version?\n\n"
                       "A backup of the previous version is kept.", yes="Replace original", no="Cancel"):
            return False
        try:
            s.save(confirm_overwrite=True)
            self.ctx.history.update_position(s.path, self.view.current_page, self.view.zoom)
            return True
        except DocuCraftError as exc:
            show_error(self, exc)
        return False

    def save_as(self) -> bool:
        s = self.session
        f, _ = QFileDialog.getSaveFileName(self, "Save As", str(self.ctx.files.last_dir("save") / s.name), "PDF (*.pdf)")
        if not f:
            return False
        try:
            out = s.save_as(f, overwrite=True)
            self.ctx.files.remember_dir("save", out)
            self.ctx.history.add_recent(out, self.view.current_page, self.view.zoom)
            return True
        except DocuCraftError as exc:
            show_error(self, exc)
        return False

    def save_copy(self) -> bool:
        s = self.session
        f, _ = QFileDialog.getSaveFileName(self, "Save a copy", str(self.ctx.files.last_dir("save") / (s.path.stem + " - copy.pdf")), "PDF (*.pdf)")
        if not f:
            return False
        try:
            s.editor.save_copy(f, confirm_overwrite=True)
            self.ctx.files.remember_dir("save", f)
            self.ctx_status(f"Saved a copy: {Path(f).name}")
            return True
        except DocuCraftError as exc:
            show_error(self, exc)
        return False

    def export_flattened(self, mode: str) -> bool:
        s = self.session
        tag = "flattened" if mode == "annotations" else "image-only"
        f, _ = QFileDialog.getSaveFileName(self, "Export", str(self.ctx.files.last_dir("save") / f"{s.path.stem} - {tag}.pdf"), "PDF (*.pdf)")
        if not f:
            return False
        try:
            s.editor.export_flattened(f, mode, confirm_overwrite=True)
            self.ctx_status(f"Exported {Path(f).name}")
            return True
        except DocuCraftError as exc:
            show_error(self, exc)
        return False

    def maybe_close(self) -> bool:
        """Ask what to do with unsaved edits. True = it is fine to close."""
        s = self.session
        if not s.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"<b>{s.name}</b> has unsaved changes.")
        box.setInformativeText("Your original file is untouched until you choose to replace it.")
        rep = box.addButton("Replace original", QMessageBox.AcceptRole)
        sa = box.addButton("Save As…", QMessageBox.AcceptRole)
        dis = box.addButton("Discard changes", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(sa)
        box.exec()
        c = box.clickedButton()
        if c is rep:
            return self.save()
        if c is sa:
            return self.save_as()
        return c is dis

    def close_tab(self) -> None:
        self.hide()
        self.session.close()

    def retheme(self) -> None:
        retheme_buttons(self)
        self.view.viewport().update()
        self._refresh_style_controls()


def icon_from_pix(pm):
    from PySide6.QtGui import QIcon
    return QIcon(pm)
