"""The PDF canvas: lazy page rendering, zoom/fit/rotate, three layouts, text selection, search
highlights and all drawing tools.

COORDINATES. PyMuPDF text, search and annotation coordinates live in the *unrotated* page space
while `page.rect` and bitmaps are rotated. Everything this widget emits (`toolCompleted` payloads,
annotation rectangles) is in that unrotated "PDF space", ready to hand to the editor. Mapping to the
screen is  unrotated --page.rotation_matrix--> displayed page --view rotation--> scale --> pixels.
"""
from __future__ import annotations

from collections import OrderedDict

import pymupdf
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractScrollArea

from app import brand, theme
from core import pdf_annotations as ann
from core.errors import DocuCraftError
from core.pdf_reader import SearchHit

ZOOM_STEPS = [0.1, 0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.25, 1.5, 1.75, 2.0, 3.0, 4.0, 6.0, 8.0]
MIN_ZOOM, MAX_ZOOM = 0.1, 8.0
GAP, MARGIN = 14, 18
MARKUP_TOOLS = ("highlight", "underline", "strike")
DRAG_RECT_TOOLS = ("rect", "ellipse", "redact", "replace", "image", "text")
TOOLS = ("select", "highlight", "underline", "strike", "note", "text", "pen", "line", "arrow", "rect", "ellipse",
         "redact", "replace", "image")
MIN_DRAG = 4


def _view_matrix(rot: int, w: float, h: float) -> pymupdf.Matrix:
    """Rotation of the displayed page (size w x h) by the view rotation."""
    return {0: pymupdf.Matrix(1, 0, 0, 1, 0, 0), 90: pymupdf.Matrix(0, 1, -1, 0, h, 0),
            180: pymupdf.Matrix(-1, 0, 0, -1, w, h), 270: pymupdf.Matrix(0, -1, 1, 0, 0, w)}[rot % 360]


class PdfView(QAbstractScrollArea):
    pageChanged = Signal(int)
    zoomChanged = Signal(float)
    selectionChanged = Signal(str)
    toolCompleted = Signal(str, int, object)            # kind, page, payload (PDF space)
    annotationMoved = Signal(int, int, object)          # page, xref, rect
    annotationDeleteRequested = Signal(int, int)
    annotationSelected = Signal(int, int)               # page, xref (xref 0 = none)
    layoutChanged = Signal()

    def __init__(self, session, base_dpi: float = 96.0, cache_pages: int = 24, parent=None):
        super().__init__(parent)
        self.session = session
        self._wm = None
        self.base_dpi = base_dpi
        self.cache_pages = max(4, cache_pages)
        self._zoom = 1.0
        self._fit: str | None = None                    # "width" | "page" | None
        self._rot = 0
        self._layout = "continuous"
        self._current = 0
        self._rects: list[QRectF] = []
        self._content = (0.0, 0.0)
        self._cache: OrderedDict[tuple, QImage] = OrderedDict()
        self._tool = "select"
        self._hits: dict[int, list[pymupdf.Rect]] = {}
        self._hit_list: list[SearchHit] = []
        self._hit_idx = -1
        self._sel: tuple[int, int, int] | None = None   # page, first word, last word
        self._anchor: tuple[int, int] | None = None
        self._drag: dict | None = None
        self._annot_sel: tuple[int, int, pymupdf.Rect] | None = None
        self._rot_cache: dict = {}
        self._color, self._opacity, self._fontsize, self._stroke = ann.YELLOW, 0.5, 12.0, 2.0
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFrameShape(QAbstractScrollArea.NoFrame)
        self.horizontalScrollBar().valueChanged.connect(self._scrolled)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        session.changed.connect(self.refresh)
        self._relayout()

    # ------------------------------------------------------------------ properties
    @property
    def page_count(self) -> int:
        return self.session.page_count

    @property
    def current_page(self) -> int:
        return self._current

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def zoom_percent(self) -> int:
        return round(self._zoom * 100)

    @property
    def rotation(self) -> int:
        return self._rot

    @property
    def layout_mode(self) -> str:
        return self._layout

    @property
    def tool(self) -> str:
        return self._tool

    @property
    def fit_mode(self) -> str | None:
        return self._fit

    def set_style(self, color=None, opacity=None, fontsize=None, stroke=None) -> None:
        self._color = color or self._color
        self._opacity = self._opacity if opacity is None else opacity
        self._fontsize = fontsize or self._fontsize
        self._stroke = stroke or self._stroke

    @property
    def style(self) -> dict:
        return {"color": self._color, "opacity": self._opacity, "fontsize": self._fontsize, "stroke": self._stroke}

    # ------------------------------------------------------------------ geometry
    def _scale(self) -> float:
        return self._zoom * self.base_dpi / 72.0

    def _page_dims(self, i: int) -> tuple[float, float]:
        w, h = self.session.reader.page_size(i)           # displayed (page-rotated) size in points
        return (h, w) if self._rot in (90, 270) else (w, h)

    def _page_matrix(self, i: int) -> pymupdf.Matrix:
        """unrotated PDF space -> page-local pixels (view rotation and zoom applied)."""
        key = (self.session.reader.revision, i, self._rot, round(self._scale(), 4))
        m = self._rot_cache.get(key)
        if m is None:
            with self.session.reader.lock:
                pm = pymupdf.Matrix(self.session.doc[i].rotation_matrix)
                w, h = self.session.reader.page_size(i)
            s = self._scale()
            m = pm * _view_matrix(self._rot, w, h) * pymupdf.Matrix(s, s)
            if len(self._rot_cache) > 400:
                self._rot_cache.clear()
            self._rot_cache[key] = m
        return m

    def rect_pt_to_local(self, page: int, rect) -> QRectF:
        r = pymupdf.Rect(rect).transform(self._page_matrix(page))
        return QRectF(r.x0, r.y0, r.width, r.height)

    def point_pt_to_local(self, page: int, p) -> QPointF:
        q = pymupdf.Point(p).transform(self._page_matrix(page))
        return QPointF(q.x, q.y)

    def local_to_pt(self, page: int, p: QPointF) -> pymupdf.Point:
        return pymupdf.Point(p.x(), p.y()).transform(~self._page_matrix(page))

    def local_rect_to_pt(self, page: int, r: QRectF) -> pymupdf.Rect:
        return pymupdf.Rect(r.left(), r.top(), r.right(), r.bottom()).transform(~self._page_matrix(page))

    def _offset(self) -> tuple[int, int]:
        return self.horizontalScrollBar().value(), self.verticalScrollBar().value()

    def page_rect_in_view(self, page: int) -> QRect:
        ox, oy = self._offset()
        r = self._rects[page]
        return QRect(int(r.left() - ox), int(r.top() - oy), int(r.width()), int(r.height()))

    def page_at(self, pos) -> int | None:
        ox, oy = self._offset()
        p = QPointF(pos.x() + ox, pos.y() + oy)
        for i in self._visible_indexes():
            if self._rects[i].contains(p):
                return i
        best, bd = None, 1e18                                   # between pages: nearest vertically
        for i in self._visible_indexes():
            d = abs(self._rects[i].center().y() - p.y())
            if d < bd:
                best, bd = i, d
        return best

    def _visible_indexes(self) -> list[int]:
        if not self._rects:
            return []
        if self._layout == "single":
            return [self._current]
        ox, oy = self._offset()
        vp = self.viewport().rect()
        view = QRectF(ox, oy, vp.width(), vp.height())
        out = [i for i, r in enumerate(self._rects) if r.intersects(view)]
        return out or [self._current]

    def _relayout(self) -> None:
        n = self.page_count
        vw, vh = max(1, self.viewport().width()), max(1, self.viewport().height())
        dims = [self._page_dims(i) for i in range(n)]
        s = self._scale()
        sizes = [(w * s, h * s) for w, h in dims]
        if self._fit and n:
            ref = self._current if self._layout == "single" or self._fit == "page" else None
            if self._layout == "two":
                span = max(sizes[i][0] + (sizes[i + 1][0] if i + 1 < n else 0) + GAP for i in range(0, n, 2)) / s
                wpt = span
            else:
                wpt = max(d[0] for d in dims) if ref is None else dims[ref][0]
            avail_w = vw - 2 * MARGIN
            z = avail_w / (wpt * self.base_dpi / 72.0)
            if self._fit == "page":
                hpt = dims[self._current][1]
                z = min(z, (vh - 2 * MARGIN) / (hpt * self.base_dpi / 72.0))
            self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, z))
            s = self._scale()
            sizes = [(w * s, h * s) for w, h in dims]
        rects: list[QRectF] = []
        if self._layout == "single":
            rects = [QRectF(0, 0, 0, 0)] * n
            if n:
                w, h = sizes[self._current]
                total_w, total_h = max(vw, w + 2 * MARGIN), max(vh, h + 2 * MARGIN)
                rects[self._current] = QRectF((total_w - w) / 2, (total_h - h) / 2 if h + 2 * MARGIN < vh else MARGIN, w, h)
            else:
                total_w, total_h = vw, vh
        elif self._layout == "two":
            rows = [list(range(i, min(i + 2, n))) for i in range(0, n, 2)]
            row_w = [sum(sizes[i][0] for i in r) + GAP * (len(r) - 1) for r in rows]
            total_w = max([vw] + [w + 2 * MARGIN for w in row_w])
            y = MARGIN
            rects = [QRectF()] * n
            for r, rw in zip(rows, row_w):
                x, rh = (total_w - rw) / 2, max(sizes[i][1] for i in r)
                for i in r:
                    rects[i] = QRectF(x, y, *sizes[i])
                    x += sizes[i][0] + GAP
                y += rh + GAP
            total_h = max(vh, y - GAP + MARGIN)
        else:
            total_w = max([vw] + [w + 2 * MARGIN for w, _ in sizes])
            y = MARGIN
            for w, h in sizes:
                rects.append(QRectF((total_w - w) / 2, y, w, h))
                y += h + GAP
            total_h = max(vh, y - GAP + MARGIN)
        self._rects, self._content = rects, (total_w, total_h)
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        hb.setRange(0, max(0, int(total_w - vw))); hb.setPageStep(vw); hb.setSingleStep(40)
        vb.setRange(0, max(0, int(total_h - vh))); vb.setPageStep(int(vh * 0.9)); vb.setSingleStep(48)
        self.viewport().update()

    def resizeEvent(self, e) -> None:
        keep = self._current
        self._relayout()
        if self._fit:
            self.zoomChanged.emit(self._zoom)
        self._scroll_to_page(keep, emit=False)
        super().resizeEvent(e)

    # ------------------------------------------------------------------ navigation
    def _scrolled(self, *_):
        if self._layout != "single":
            self._update_current_from_scroll()
        self.viewport().update()

    def _update_current_from_scroll(self) -> None:
        if not self._rects:
            return
        ox, oy = self._offset()
        probe = oy + self.viewport().height() * 0.35
        best, bd = self._current, 1e18
        for i, r in enumerate(self._rects):
            if r.top() <= probe <= r.bottom() + GAP:
                best = i
                break
            d = abs(r.center().y() - probe)
            if d < bd:
                best, bd = i, d
        if best != self._current:
            self._current = best
            self.pageChanged.emit(best)

    def _scroll_to_page(self, i: int, emit: bool = True) -> None:
        if not self._rects:
            return
        i = max(0, min(self.page_count - 1, i))
        changed = i != self._current
        self._current = i
        if self._layout == "single":
            self._relayout()
            self.verticalScrollBar().setValue(0)
        else:
            self.verticalScrollBar().setValue(int(self._rects[i].top() - MARGIN))
            self._current = i
        if emit and changed:
            self.pageChanged.emit(i)
        self.viewport().update()

    def go_to_page(self, i: int) -> None:
        i = max(0, min(self.page_count - 1, int(i)))
        was = self._current
        self._scroll_to_page(i, emit=False)
        self._current = i
        if i != was:
            self.pageChanged.emit(i)
        elif self._layout != "single":
            self.pageChanged.emit(i)

    def next_page(self) -> None:
        self.go_to_page(self._current + (2 if self._layout == "two" else 1))

    def prev_page(self) -> None:
        self.go_to_page(self._current - (2 if self._layout == "two" else 1))

    def first_page(self) -> None:
        self.go_to_page(0)

    def last_page(self) -> None:
        self.go_to_page(self.page_count - 1)

    # ------------------------------------------------------------------ zoom / layout / rotate
    def set_zoom(self, z: float, *, keep_fit: bool = False) -> None:
        z = max(MIN_ZOOM, min(MAX_ZOOM, float(z)))
        if not keep_fit:
            self._fit = None
        if abs(z - self._zoom) < 1e-4 and not keep_fit:
            return
        keep = self._current
        oy = self.verticalScrollBar().value()
        ratio = z / self._zoom if self._zoom else 1.0
        self._zoom = z
        self._relayout()
        if self._layout != "single":
            self.verticalScrollBar().setValue(int(oy * ratio))
        self._current = keep
        self.zoomChanged.emit(self._zoom)

    def zoom_in(self) -> None:
        self.set_zoom(next((s for s in ZOOM_STEPS if s > self._zoom + 1e-3), MAX_ZOOM))

    def zoom_out(self) -> None:
        self.set_zoom(next((s for s in reversed(ZOOM_STEPS) if s < self._zoom - 1e-3), MIN_ZOOM))

    def fit_width(self) -> None:
        self._fit = "width"
        self._relayout()
        self.zoomChanged.emit(self._zoom)

    def fit_page(self) -> None:
        self._fit = "page"
        self._relayout()
        self.zoomChanged.emit(self._zoom)

    def apply_default_zoom(self, value) -> None:
        if value == "fit_width":
            self.fit_width()
        elif value == "fit_page":
            self.fit_page()
        else:
            try:
                self.set_zoom(float(value) / 100.0)
            except (TypeError, ValueError):
                self.fit_width()

    def set_layout(self, mode: str) -> None:
        if mode not in ("single", "continuous", "two"):
            return
        keep = self._current
        self._layout = mode
        self._relayout()
        self._scroll_to_page(keep, emit=False)
        self.layoutChanged.emit()

    def rotate_view(self, delta: int = 90) -> None:
        keep = self._current
        self._rot = (self._rot + delta) % 360
        self._cache.clear()
        self._relayout()
        self._scroll_to_page(keep, emit=False)

    # ------------------------------------------------------------------ refresh / search / tools
    def refresh(self) -> None:
        """Content changed (edit, undo, save): drop cached bitmaps and relayout."""
        self._cache.clear()
        self._rot_cache.clear()
        self._current = max(0, min(self._current, self.page_count - 1))
        self._sel = None
        self._annot_sel = None
        self._relayout()
        if self._layout == "single":
            self._scroll_to_page(self._current, emit=False)

    def set_tool(self, tool: str) -> None:
        self._tool = tool if tool in TOOLS else "select"
        self._drag = None
        self._anchor = None
        self.viewport().setCursor(Qt.IBeamCursor if self._tool in ("select",) + MARKUP_TOOLS else Qt.CrossCursor)
        self.viewport().update()

    def set_search(self, hits: list[SearchHit], current: int = -1) -> None:
        self._hit_list, self._hit_idx = list(hits), current
        self._hits = {}
        for h in hits:
            self._hits.setdefault(h.page, []).append(pymupdf.Rect(h.rect))
        self.viewport().update()
        if 0 <= current < len(hits):
            self.show_hit(current)

    def clear_search(self) -> None:
        self.set_search([], -1)

    def show_hit(self, idx: int) -> None:
        if not self._hit_list:
            return
        idx %= len(self._hit_list)
        self._hit_idx = idx
        h = self._hit_list[idx]
        if self._layout == "single" and h.page != self._current:
            self.go_to_page(h.page)
        r = self.rect_pt_to_local(h.page, h.rect)
        pr = self._rects[h.page]
        y = int(pr.top() + r.top() - self.viewport().height() / 3)
        self.verticalScrollBar().setValue(max(0, y))
        if h.page != self._current:
            self._current = h.page
            self.pageChanged.emit(h.page)
        self.viewport().update()

    @property
    def hit_index(self) -> int:
        return self._hit_idx

    # ------------------------------------------------------------------ rendering
    def _image_for(self, i: int) -> QImage:
        dpr = self.devicePixelRatioF()
        s = self._scale() * dpr
        key = (self.session.reader.revision, i, round(s, 3), self._rot)
        img = self._cache.get(key)
        if img is not None:
            self._cache.move_to_end(key)
            return img
        try:
            pix = self.session.reader.render(i, zoom=s, rotation=self._rot)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            img.setDevicePixelRatio(dpr)
        except Exception:                                    # a broken page must never crash the canvas
            img = QImage(10, 10, QImage.Format_RGB888)
            img.fill(QColor("#f8d7da"))
        self._cache[key] = img
        while len(self._cache) > self.cache_pages:
            self._cache.popitem(last=False)
        return img

    def paintEvent(self, e) -> None:
        c = theme.palette()
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)           # never drop pixel columns when a page is scaled slightly
        p.fillRect(self.viewport().rect(), QColor(c["canvas"]))
        ox, oy = self._offset()
        p.translate(-ox, -oy)
        for i in self._visible_indexes():
            r = self._rects[i]
            p.fillRect(r.adjusted(3, 4, 3, 4), QColor(0, 0, 0, 45))
            img = self._image_for(i)
            dpr = img.devicePixelRatio() or 1.0
            if abs(img.width() / dpr - r.width()) <= 2 and abs(img.height() / dpr - r.height()) <= 2:
                p.drawImage(r.topLeft(), img)                           # 1:1 - no resampling, so glyphs stay intact
            else:
                p.drawImage(r, img)
            self._paint_watermark(p, r)
            p.setPen(QPen(QColor(c["border"]), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.save()
            p.translate(r.topLeft())
            self._paint_overlays(p, i)
            p.restore()
        p.end()

    def _paint_watermark(self, p: QPainter, r) -> None:
        """Faint Shadow emblem on every page (display only; saved files get their own stamp)."""
        if self._wm is None:
            self._wm = brand.watermark_pixmap()
        side = int(min(r.width(), r.height()) * 0.34)
        if side < 40:
            return
        p.save()
        p.setOpacity(0.07)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(int(r.center().x() - side / 2), int(r.center().y() - side / 2), side, side, self._wm)
        p.restore()

    def _paint_overlays(self, p: QPainter, i: int) -> None:
        for k, rect in enumerate(self._hits.get(i, [])):
            cur = 0 <= self._hit_idx < len(self._hit_list) and self._hit_list[self._hit_idx].page == i and \
                  tuple(self._hit_list[self._hit_idx].rect) == tuple(rect)
            p.fillRect(self.rect_pt_to_local(i, rect), QColor(255, 140, 0, 130) if cur else QColor(255, 235, 0, 110))
        if self._sel and self._sel[0] == i:
            words = self.session.reader.words(i)
            for w in words[self._sel[1]:self._sel[2] + 1]:
                p.fillRect(self.rect_pt_to_local(i, w[:4]), QColor(60, 120, 255, 90))
        if self._annot_sel and self._annot_sel[0] == i:
            r = self.rect_pt_to_local(i, self._annot_sel[2])
            if self._drag and self._drag.get("kind") in ("move", "resize") and self._drag["page"] == i:
                r = self._drag["preview"]
            p.setPen(QPen(QColor(theme.palette()["accent"]), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.fillRect(QRectF(r.right() - 4, r.bottom() - 4, 8, 8), QColor(theme.palette()["accent"]))
        d = self._drag
        if d and d.get("page") == i and d["kind"] == "shape":
            pen = QPen(QColor(theme.palette()["accent"]), 1.5, Qt.DashLine)
            if self._tool == "redact":
                pen = QPen(QColor(0, 0, 0), 1.5)
                p.setBrush(QColor(0, 0, 0, 110))
            else:
                p.setBrush(Qt.NoBrush)
            p.setPen(pen)
            a, b = d["start"], d["pos"]
            if self._tool in ("line", "arrow"):
                p.drawLine(a, b)
            elif self._tool == "ellipse":
                p.drawEllipse(QRectF(a, b).normalized())
            else:
                p.drawRect(QRectF(a, b).normalized())
        if d and d.get("page") == i and d["kind"] == "pen":
            p.setPen(QPen(QColor(*[int(x * 255) for x in self._color]), self._stroke * self._scale() / 1.33, Qt.SolidLine,
                          Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(QPolygonF(d["points"]))

    # ------------------------------------------------------------------ text selection
    def _word_at(self, page: int, local: QPointF, strict: bool = False) -> int | None:
        words = self.session.reader.words(page)
        if not words:
            return None
        pt = self.local_to_pt(page, local)
        best, bd = None, 1e18
        for k, w in enumerate(words):
            r = pymupdf.Rect(w[:4])
            if (r + (-1.5, -1.5, 1.5, 1.5)).contains(pt):
                return k
            if not strict:
                dx = max(r.x0 - pt.x, 0, pt.x - r.x1)
                dy = max(r.y0 - pt.y, 0, pt.y - r.y1)
                d = dx * dx + dy * dy * 4
                if d < bd:
                    best, bd = k, d
        return best

    def selected_text(self) -> str:
        if not self._sel:
            return ""
        words = self.session.reader.words(self._sel[0])[self._sel[1]:self._sel[2] + 1]
        out, last = [], None
        for w in words:
            key = (w[5], w[6])
            out.append(("\n" if last is not None and key != last else " " if out else "") + w[4])
            last = key
        return "".join(out)

    def selected_word_rects(self) -> list[pymupdf.Rect]:
        if not self._sel:
            return []
        words = self.session.reader.words(self._sel[0])[self._sel[1]:self._sel[2] + 1]
        return ann.merge_word_rects(words)

    def clear_selection(self) -> None:
        if self._sel:
            self._sel = None
            self.selectionChanged.emit("")
            self.viewport().update()

    def copy_selection(self) -> bool:
        t = self.selected_text()
        if t:
            QGuiApplication.clipboard().setText(t)
        return bool(t)

    def select_all_on_page(self) -> None:
        n = len(self.session.reader.words(self._current))
        if n:
            self._sel = (self._current, 0, n - 1)
            self.selectionChanged.emit(self.selected_text())
            self.viewport().update()

    # ------------------------------------------------------------------ annotations
    def _annotation_at(self, page: int, local: QPointF):
        pt = self.local_to_pt(page, local)
        with self.session.reader.lock:
            a = ann.find_annotation_at(self.session.doc[page], (pt.x, pt.y), 3.0)
            return (a.xref, pymupdf.Rect(a.rect)) if a else None

    def selected_annotation(self) -> tuple[int, int] | None:
        return (self._annot_sel[0], self._annot_sel[1]) if self._annot_sel else None

    def select_annotation(self, page: int, xref: int) -> None:
        with self.session.reader.lock:
            for a in self.session.doc[page].annots() or []:
                if a.xref == xref:
                    self._annot_sel = (page, xref, pymupdf.Rect(a.rect))
                    break
        self.annotationSelected.emit(page, xref)
        self.viewport().update()

    def deselect_annotation(self) -> None:
        if self._annot_sel:
            self._annot_sel = None
            self.annotationSelected.emit(-1, 0)
            self.viewport().update()

    # ------------------------------------------------------------------ mouse
    def _local(self, page: int, pos) -> QPointF:
        ox, oy = self._offset()
        r = self._rects[page]
        return QPointF(pos.x() + ox - r.left(), pos.y() + oy - r.top())

    def _clamped(self, page: int, pos) -> QPointF:
        l = self._local(page, pos)
        r = self._rects[page]
        return QPointF(max(0, min(r.width(), l.x())), max(0, min(r.height(), l.y())))

    def mousePressEvent(self, e) -> None:
        self.setFocus()
        if e.button() != Qt.LeftButton or not self._rects:
            return
        page = self.page_at(e.position().toPoint())
        if page is None:
            return
        local = self._local(page, e.position())
        inside = self._rects[page].contains(QPointF(e.position().x() + self._offset()[0], e.position().y() + self._offset()[1]))
        if self._layout != "single" and page != self._current and inside:
            self._current = page
            self.pageChanged.emit(page)
        t = self._tool
        if t == "select":
            if self._annot_sel and self._annot_sel[0] == page:
                r = self.rect_pt_to_local(page, self._annot_sel[2])
                if abs(local.x() - r.right()) < 9 and abs(local.y() - r.bottom()) < 9:
                    self._drag = {"kind": "resize", "page": page, "start": local, "preview": QRectF(r), "orig": QRectF(r)}
                    return
            hit = self._annotation_at(page, local) if inside else None
            if hit:
                self._annot_sel = (page, hit[0], hit[1])
                self.annotationSelected.emit(page, hit[0])
                r = self.rect_pt_to_local(page, hit[1])
                self._drag = {"kind": "move", "page": page, "start": local, "preview": QRectF(r), "orig": QRectF(r)}
                self.clear_selection()
                self.viewport().update()
                return
            self.deselect_annotation()
        if t in ("select",) + MARKUP_TOOLS:
            k = self._word_at(page, local)
            if k is None or not inside and t != "select":
                self.clear_selection()
                return
            self._anchor = (page, k)
            self._sel = (page, k, k)
            self._drag = {"kind": "text", "page": page}
            self.selectionChanged.emit(self.selected_text())
        elif t == "note":
            if inside:
                self.toolCompleted.emit("note", page, self._pt(page, local))
        elif t == "pen":
            self._drag = {"kind": "pen", "page": page, "points": [self._clamped(page, e.position())]}
        elif t in ("line", "arrow") or t in DRAG_RECT_TOOLS:
            self._drag = {"kind": "shape", "page": page, "start": self._clamped(page, e.position()),
                          "pos": self._clamped(page, e.position()), "click": local}
        self.viewport().update()

    def _pt(self, page: int, local: QPointF) -> tuple[float, float]:
        p = self.local_to_pt(page, local)
        return (p.x, p.y)

    def mouseMoveEvent(self, e) -> None:
        d = self._drag
        if not d:
            if self._rects and self._tool == "select":
                page = self.page_at(e.position().toPoint())
                if page is not None and self._annotation_at(page, self._local(page, e.position())):
                    self.viewport().setCursor(Qt.SizeAllCursor)
                else:
                    self.viewport().setCursor(Qt.IBeamCursor)
            return
        page = d["page"]
        if d["kind"] == "text":
            k = self._word_at(page, self._clamped(page, e.position()))
            if k is not None and self._anchor:
                a = self._anchor[1]
                self._sel = (page, min(a, k), max(a, k))
                self.selectionChanged.emit(self.selected_text())
        elif d["kind"] == "pen":
            d["points"].append(self._clamped(page, e.position()))
        elif d["kind"] == "shape":
            d["pos"] = self._clamped(page, e.position())
        elif d["kind"] == "move":
            delta = self._local(page, e.position()) - d["start"]
            d["preview"] = d["orig"].translated(delta)
        elif d["kind"] == "resize":
            cur = self._local(page, e.position())
            o = d["orig"]
            d["preview"] = QRectF(o.topLeft(), QPointF(max(o.left() + 6, cur.x()), max(o.top() + 6, cur.y()))).normalized()
        self.viewport().update()

    def mouseReleaseEvent(self, e) -> None:
        d, self._drag = self._drag, None
        if not d or e.button() != Qt.LeftButton:
            return
        page, t = d["page"], self._tool
        if d["kind"] == "text":
            if t in MARKUP_TOOLS and self._sel:
                rects = [tuple(r) for r in self.selected_word_rects()]
                self.clear_selection()
                if rects:
                    self.toolCompleted.emit(t, page, rects)
        elif d["kind"] == "pen":
            pts = d["points"]
            if len(pts) >= 2 and (abs(pts[-1].x() - pts[0].x()) + abs(pts[-1].y() - pts[0].y()) >= MIN_DRAG or len(pts) > 4):
                self.toolCompleted.emit("pen", page, [[self._pt(page, p) for p in pts]])
        elif d["kind"] == "shape":
            a, b = d["start"], d["pos"]
            moved = abs(a.x() - b.x()) >= MIN_DRAG or abs(a.y() - b.y()) >= MIN_DRAG
            if t in ("line", "arrow"):
                if moved:
                    self.toolCompleted.emit(t, page, (self._pt(page, a), self._pt(page, b)))
            elif t == "text" and not moved:
                s = self._scale()
                r = QRectF(d["click"].x(), d["click"].y(), 170 * s, 34 * s)
                self.toolCompleted.emit("text", page, tuple(self.local_rect_to_pt(page, r)))
            elif moved:
                r = self.local_rect_to_pt(page, QRectF(a, b).normalized())
                self.toolCompleted.emit(t, page, tuple(r))
        elif d["kind"] in ("move", "resize"):
            if (d["preview"].topLeft() - d["orig"].topLeft()).manhattanLength() >= 2 or d["preview"].size() != d["orig"].size():
                self.annotationMoved.emit(page, self._annot_sel[1], tuple(self.local_rect_to_pt(page, d["preview"])))
        self.viewport().update()

    def mouseDoubleClickEvent(self, e) -> None:
        if self._tool != "select" or not self._rects:
            return
        page = self.page_at(e.position().toPoint())
        if page is None:
            return
        k = self._word_at(page, self._local(page, e.position()), strict=True)
        if k is not None:
            self._sel = (page, k, k)
            self.selectionChanged.emit(self.selected_text())
            self.viewport().update()

    def wheelEvent(self, e) -> None:
        if e.modifiers() & Qt.ControlModifier:
            (self.zoom_in if e.angleDelta().y() > 0 else self.zoom_out)()
            e.accept()
        elif self._layout == "single":
            vb = self.verticalScrollBar()
            if e.angleDelta().y() < 0 and vb.value() >= vb.maximum():
                self.next_page()
            elif e.angleDelta().y() > 0 and vb.value() <= vb.minimum():
                self.prev_page()
            else:
                super().wheelEvent(e)
        else:
            super().wheelEvent(e)

    def keyPressEvent(self, e) -> None:
        k, mod = e.key(), e.modifiers()
        if k in (Qt.Key_Delete, Qt.Key_Backspace) and self._annot_sel:
            self.annotationDeleteRequested.emit(self._annot_sel[0], self._annot_sel[1])
        elif k == Qt.Key_Escape:
            self.clear_selection(); self.deselect_annotation(); self._drag = None; self.viewport().update()
        elif mod & Qt.ControlModifier and k == Qt.Key_C:
            self.copy_selection()
        elif mod & Qt.ControlModifier and k == Qt.Key_A:
            self.select_all_on_page()
        elif k == Qt.Key_PageDown and self._layout == "single":
            self.next_page()
        elif k == Qt.Key_PageUp and self._layout == "single":
            self.prev_page()
        elif k == Qt.Key_Home and mod & Qt.ControlModifier:
            self.first_page()
        elif k == Qt.Key_End and mod & Qt.ControlModifier:
            self.last_page()
        else:
            super().keyPressEvent(e)
