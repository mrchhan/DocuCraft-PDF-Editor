"""The DocuCraft main window: header, sidebar, document tabs, pages, status bar."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMenu, QProgressBar, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from app import brand, icons, theme
from app.document_session import DocumentSession
from app.navigation import Sidebar
from app.settings import APP_NAME, APP_VERSION
from core import branding
from ui.components.watermark import WatermarkOverlay
from core import pdf_security as sec
from core.errors import DocuCraftError, InvalidFileError, PasswordRequiredError, WrongPasswordError
from services.logging_service import get_logger
from ui.components.document_tab import DocumentTab
from ui.components.widgets import confirm, icon, message, retheme_buttons, show_error
from ui.dialogs.dialogs import PasswordDialog
from ui.pages.convert_page import ConvertPage
from ui.pages.home_page import HomePage
from ui.pages.library_page import HistoryPage, LibraryPage, MyDocumentsPage
from ui.pages.settings_page import SettingsPage
from ui.pages.tools_page import ORGANIZE, SECURITY, ToolsPage

log = get_logger("window")
SECTIONS = [("home", "Home"), ("edit", "Edit"), ("convert", "Convert"), ("organize", "Organize"),
            ("security", "Security"), ("settings", "Settings")]


class MainWindow(QMainWindow):
    def __init__(self, ctx, app: QApplication | None = None):
        super().__init__()
        self.ctx = ctx
        self.app = app or QApplication.instance()
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1360, 860)
        self.setMinimumSize(920, 600)
        self._fullscreen = False
        self._section = "home"
        self.setWindowIcon(brand.window_icon())

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = self._build_header()
        outer.addWidget(self.header)
        body = QHBoxLayout()
        body.setSpacing(0)
        self.sidebar = Sidebar()
        self.sidebar.navigate.connect(self.navigate)
        body.addWidget(self.sidebar)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        # ---- pages
        self.home = HomePage(ctx)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(False)      # custom themed close buttons are installed per tab
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.workspace = QStackedWidget()
        self.workspace.addWidget(self.home)
        self.workspace.addWidget(self.tabs)
        self.recent = LibraryPage(ctx, "recent")
        self.favorites = LibraryPage(ctx, "favorites")
        self.mydocs = MyDocumentsPage(ctx)
        self.tools = ToolsPage(ctx)
        self.convert = ConvertPage(ctx)
        self.history_page = HistoryPage(ctx)
        self.settings_page = SettingsPage(ctx)
        self.page_map = {"home": self.workspace, "recent": self.recent, "mydocs": self.mydocs, "favorites": self.favorites,
                         "tools": self.tools, "convert": self.convert, "history": self.history_page, "settings": self.settings_page}
        for w in self.page_map.values():
            self.pages.addWidget(w)
        self.watermark = brand.WatermarkOverlay(self.pages)          # faint Shadow emblem over every screen
        self.pages.currentChanged.connect(lambda *_: self.watermark.raise_())
        for p in (self.home, self.recent, self.favorites, self.mydocs, self.history_page):
            p.openPath.connect(self.open_path)
        self.home.openRequested.connect(self.open_dialog)
        self.home.toolRequested.connect(self.open_tool)

        self._build_status_bar()
        self._build_actions()
        ctx.themeChanged.connect(self._apply_theme)
        ctx.jobs.jobsChanged.connect(self._jobs_changed)
        self.workspace.setCurrentWidget(self.home)
        self.watermark = WatermarkOverlay(self.pages, self._watermark_active)
        self.pages.currentChanged.connect(self.watermark.update)
        self.workspace.currentChanged.connect(self.watermark.update)
        self.navigate("home")
        self._restore_geometry()

    # ================================================================== header / status / actions
    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setObjectName("Header")
        h.setFixedHeight(52)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(4)
        self.logo = QLabel()
        self.logo.setPixmap(brand.pixmap("emblem", 32))
        name = QLabel(APP_NAME)
        name.setObjectName("H2")
        lay.addWidget(self.logo)
        lay.addWidget(name)
        lay.addSpacing(14)
        self.file_btn = QToolButton()
        self.file_btn.setText("File")
        self.file_btn.setPopupMode(QToolButton.InstantPopup)
        self.file_btn.setObjectName("Tab")
        self.file_menu = QMenu(self.file_btn)
        self.file_btn.setMenu(self.file_menu)
        lay.addWidget(self.file_btn)
        self.section_group = QButtonGroup(self)
        self.section_btns: dict[str, QToolButton] = {}
        for key, label in SECTIONS:
            b = QToolButton()
            b.setObjectName("Tab")
            b.setText(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.section(k))
            self.section_group.addButton(b)
            self.section_btns[key] = b
            lay.addWidget(b)
        lay.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search in document…")
        self.search.setFixedWidth(250)
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._header_search)
        lay.addWidget(self.search)
        self.theme_btn = QToolButton()
        self.theme_btn.setAutoRaise(True)
        self.theme_btn.setIconSize(QSize(20, 20))
        self.theme_btn.setToolTip("Switch light / dark theme")
        self.theme_btn.clicked.connect(self._toggle_theme)
        lay.addWidget(self.theme_btn)
        self._update_theme_icon()
        return h

    def _build_status_bar(self) -> None:
        sb = self.statusBar()
        sb.setSizeGripEnabled(True)
        self.st_page, self.st_zoom, self.st_size = QLabel(""), QLabel(""), QLabel("")
        self.st_jobs = QLabel("")
        self.st_bar = QProgressBar()
        self.st_bar.setRange(0, 0)
        self.st_bar.setFixedWidth(90)
        self.st_bar.setFixedHeight(10)
        self.st_bar.hide()
        self.st_credit = QLabel(branding.CONTACT_LINE)
        self.st_credit.setObjectName("Muted")
        self.st_credit.setToolTip(f"{branding.STUDIO} \u00b7 {branding.APP_NAME}")
        for w in (self.st_credit, self.st_jobs, self.st_bar, self.st_page, self.st_zoom, self.st_size):
            sb.addPermanentWidget(w)
        sb.showMessage("Ready", 3000)

    def _act(self, text: str, slot, shortcut: str = "", icon_name: str = "") -> QAction:
        a = QAction(text, self)
        if icon_name:
            a.setIcon(icon(icon_name, 18))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.WindowShortcut)
        a.triggered.connect(lambda *_: slot())
        self.addAction(a)
        return a

    def _build_actions(self) -> None:
        m = self.file_menu
        self.a_open = self._act("Open…", self.open_dialog, "Ctrl+O", "open")
        self.recent_menu = QMenu("Open recent", m)
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        self.a_save = self._act("Save…", lambda: self._cur(lambda t: t.save()), "Ctrl+S", "save")
        self.a_saveas = self._act("Save As…", lambda: self._cur(lambda t: t.save_as()), "Ctrl+Shift+S", "saveas")
        self.a_copy = self._act("Save a copy…", lambda: self._cur(lambda t: t.save_copy()))
        self.a_flat = self._act("Export flattened PDF…", lambda: self._cur(lambda t: t.export_flattened("annotations")))
        self.a_print = self._act("Print…", lambda: self._cur(lambda t: t.print_document()))
        self.a_info = self._act("Document information…", lambda: self._cur(lambda t: t.show_info()))
        self.a_toword = self._act("Convert this document to Word…", self.convert_current)
        self.a_close = self._act("Close tab", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        self.a_quit = self._act("Exit", self.close, "Ctrl+Q")
        self._act("Next tab", lambda: self._step_tab(1), "Ctrl+Tab")
        self._act("Previous tab", lambda: self._step_tab(-1), "Ctrl+Shift+Tab")
        self._act("Find", lambda: self._cur(lambda t: t.open_find()), "")
        self._exit_fs = QShortcut(QKeySequence("Esc"), self)
        self._exit_fs.activated.connect(lambda: self.toggle_fullscreen() if self._fullscreen else None)
        for a in (self.a_open,):
            m.addAction(a)
        m.addMenu(self.recent_menu)
        m.addSeparator()
        for a in (self.a_save, self.a_saveas, self.a_copy, self.a_flat):
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_print, self.a_info, self.a_toword):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_close)
        m.addAction(self.a_quit)
        m.aboutToShow.connect(self._update_actions)

    def _update_actions(self) -> None:
        has = self.current_tab() is not None
        for a in (self.a_save, self.a_saveas, self.a_copy, self.a_flat, self.a_print, self.a_info, self.a_toword, self.a_close):
            a.setEnabled(has)

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        docs = [d for d in self.ctx.history.recent(limit=10) if d.exists]
        for d in docs:
            self.recent_menu.addAction(d.name, lambda _=False, p=d.path: self.open_path(p))
        if not docs:
            self.recent_menu.addAction("(none)").setEnabled(False)

    def flash(self, text: str, ms: int = 6000) -> None:
        self.statusBar().showMessage(text, ms)

    # ================================================================== navigation
    def current_tab(self) -> DocumentTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocumentTab) else None

    def _cur(self, fn) -> None:
        t = self.current_tab()
        if t:
            fn(t)

    def _watermark_active(self) -> bool:
        """Everywhere except an open document: the PDF viewer draws its own mark on each page."""
        return not (self.pages.currentWidget() is self.workspace and self.workspace.currentWidget() is self.tabs)

    def navigate(self, key: str) -> None:
        w = self.page_map.get(key)
        if w is None:
            return
        self.pages.setCurrentWidget(w)
        if key == "home":
            self.workspace.setCurrentWidget(self.tabs if self.tabs.count() else self.home)
        for p in (self.recent, self.favorites, self.history_page):
            if p is w:
                p.refresh()
        if w is self.home:
            self.home.refresh()
        self.sidebar.select(key)
        self._sync_header(key)
        self._update_status()

    def _sync_header(self, key: str) -> None:
        sec_key = {"home": "edit" if self._section == "edit" and self.tabs.count() else "home", "convert": "convert",
                   "settings": "settings"}.get(key)
        if key == "tools":
            sec_key = "security" if self.tools.current_key() in SECURITY else "organize"
        self.section_group.setExclusive(False)
        for k, b in self.section_btns.items():
            b.setChecked(k == sec_key)
        self.section_group.setExclusive(True)

    def section(self, key: str) -> None:
        if key == "home":
            self._section = "home"
            for i in range(self.tabs.count()):
                self.tabs.widget(i).set_ribbon("view")
            self.navigate("home")
        elif key == "edit":
            if not self.tabs.count():
                self.flash("Open a PDF to start editing.")
                self.open_dialog()
                if not self.tabs.count():
                    self._sync_header("home")
                    return
            self._section = "edit"
            for i in range(self.tabs.count()):
                self.tabs.widget(i).set_ribbon("edit")
            self.navigate("home")
        elif key == "convert":
            self.navigate("convert")
        elif key == "organize":
            if self.tools.current_key() not in ORGANIZE:
                self.tools.show_tool("merge")
            self.navigate("tools")
        elif key == "security":
            if self.tools.current_key() not in SECURITY:
                self.tools.show_tool("protect")
            self.navigate("tools")
        elif key == "settings":
            self.navigate("settings")

    def open_tool(self, key: str, files: list[str] | None = None) -> None:
        if key in ("pdf2word", "word2pdf"):
            self.convert.show_panel(key, files)
            self.navigate("convert")
        else:
            self.tools.show_tool(key, files)
            self.navigate("tools")

    def convert_current(self) -> None:
        t = self.current_tab()
        if not t:
            return
        if t.session.dirty:
            message(self, "Convert to Word", "The converter uses the saved file on disk. Save your changes first "
                    "(or use Save As…), then convert.", "warn")
            return
        self.open_tool("pdf2word", [str(t.session.path)])

    # ================================================================== documents
    def open_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Open PDF", str(self.ctx.files.last_dir("open")), "PDF documents (*.pdf);;All files (*)")
        for f in files:
            self.open_path(f)

    def open_path(self, path: str, password: str | None = None) -> DocumentTab | None:
        try:
            p = sec.validate_input_file(path)
        except DocuCraftError as exc:
            show_error(self, exc, "Cannot open file")
            return None
        for i in range(self.tabs.count()):
            if self.tabs.widget(i).session.path == p:
                self.tabs.setCurrentIndex(i)
                self.navigate("home")
                return self.tabs.widget(i)
        session = self._create_session(p, password)
        if session is None:
            return None
        self.ctx.files.remember_dir("open", p)
        tab = DocumentTab(self.ctx, session)
        tab.set_ribbon("edit" if self._section == "edit" else "view")
        pos = self.ctx.history.last_position(p) if self.ctx.history.enabled else None
        self.ctx.history.add_recent(p, pos[0] if pos else 0, pos[1] if pos else 1.0)
        idx = self.tabs.addTab(tab, icon("lock" if session.encrypted else "pdf", 18), session.name)
        self.tabs.setTabToolTip(idx, str(p))
        self._install_close_button(tab)
        tab.titleChanged.connect(self._tab_title)
        tab.statusChanged.connect(self._update_status)
        tab.fullscreenRequested.connect(self.toggle_fullscreen)
        self.tabs.setCurrentIndex(idx)
        self.navigate("home")
        if pos and pos[0] > 0:
            tab.view.go_to_page(min(pos[0], session.page_count - 1))
        self.flash(f"Opened {session.name}")
        return tab

    def _install_close_button(self, tab) -> None:
        """A themed close button (the platform default can render as a red box)."""
        i = self.tabs.indexOf(tab)
        b = QToolButton()
        b.setAutoRaise(True)
        b.setIcon(theme.ic("close", 14))
        b.setIconSize(QSize(14, 14))
        b.setToolTip("Close tab (Ctrl+W)")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda: self.close_tab(self.tabs.indexOf(tab)))
        self.tabs.tabBar().setTabButton(i, self.tabs.tabBar().ButtonPosition.RightSide, b)

    def _create_session(self, p: Path, password: str | None) -> DocumentSession | None:
        secs = int(self.ctx.settings.get("autosave_recovery_seconds"))
        for attempt in range(4):
            try:
                return DocumentSession(p, password, recovery=self.ctx.recovery, autosave_seconds=secs)
            except PasswordRequiredError:
                password = PasswordDialog.ask(self, p.name)
            except WrongPasswordError:
                password = PasswordDialog.ask(self, p.name, wrong=True)
            except DocuCraftError as exc:
                show_error(self, exc, "Cannot open document")
                return None
            except Exception as exc:
                log.exception("open failed")
                show_error(self, exc, "Cannot open document")
                return None
            if password is None:
                return None
        message(self, "Password required", "Too many incorrect passwords.", "warn")
        return None

    def _tab_title(self, tab) -> None:
        i = self.tabs.indexOf(tab)
        if i >= 0:
            self.tabs.setTabText(i, tab.title())
            self.tabs.setTabToolTip(i, str(tab.session.path))
        if tab is self.current_tab():
            self.setWindowTitle(f"{tab.title()} — {APP_NAME}")

    def _tab_changed(self, i: int) -> None:
        t = self.current_tab()
        self.setWindowTitle(f"{t.title()} — {APP_NAME}" if t else APP_NAME)
        self.search.setPlaceholderText("Search in document…" if t else "Search recent documents…")
        self._update_status()

    def close_tab(self, i: int) -> bool:
        if i < 0:
            return True
        tab = self.tabs.widget(i)
        if not tab.maybe_close():
            return False
        try:
            self.ctx.history.update_position(tab.session.path, tab.view.current_page, tab.view.zoom)
        except Exception:
            pass
        self.tabs.removeTab(i)
        tab.close_tab()
        tab.deleteLater()
        if not self.tabs.count():
            self._section = "home" if self._section == "edit" else self._section
            self.workspace.setCurrentWidget(self.home)
            self.home.refresh()
            self._sync_header("home")
        self._update_status()
        return True

    def _step_tab(self, d: int) -> None:
        n = self.tabs.count()
        if n:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + d) % n)

    def _update_status(self, *_) -> None:
        t = self.current_tab() if self.pages.currentWidget() is self.workspace else None
        if t:
            page, total, zoom, size = t.status_info()
            self.st_page.setText(f"Page {page} / {total}   ")
            self.st_zoom.setText(f"{zoom}%   ")
            self.st_size.setText(size + "   ")
        else:
            self.st_page.setText("")
            self.st_zoom.setText("")
            self.st_size.setText("")
        self.setWindowTitle(f"{t.title()} — {APP_NAME}" if t else APP_NAME)

    def _jobs_changed(self, n: int) -> None:
        self.st_bar.setVisible(n > 0)
        self.st_jobs.setText(f"Working on {n} task(s)…   " if n else "")

    # ================================================================== search / theme / fullscreen
    def _header_search(self) -> None:
        text = self.search.text().strip()
        t = self.current_tab()
        if t:
            self.navigate("home")
            t.find.open_bar(text)
        else:
            self.navigate("recent")
            self.recent.search.setText(text)

    def _toggle_theme(self) -> None:
        self.ctx.settings.set("theme", "light" if theme.current() == "dark" else "dark")

    def _update_theme_icon(self) -> None:
        self.theme_btn.setIcon(theme.ic("sun" if theme.current() == "dark" else "moon", 20))

    def _apply_theme(self, *_) -> None:
        s = self.ctx.settings
        theme.apply_theme(self.app, str(s.get("theme")), int(s.get("ui_scale")))
        self.logo.setPixmap(brand.pixmap("emblem", 32))
        self._update_theme_icon()
        retheme_buttons(self)
        self.sidebar.retheme()
        self.tools.retheme()
        self.convert.retheme()
        for i in range(self.tabs.count()):
            self.tabs.widget(i).retheme()
            self.tabs.setTabIcon(i, icon("lock" if self.tabs.widget(i).session.encrypted else "pdf", 18))
            self._install_close_button(self.tabs.widget(i))
        for p in (self.home, self.recent, self.favorites, self.history_page):
            p.retheme()

    def toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        for w in (self.header, self.sidebar, self.statusBar()):
            w.setVisible(not self._fullscreen)
        self.tabs.tabBar().setVisible(not self._fullscreen)
        t = self.current_tab()
        if t:
            t.ribbon.setVisible(not self._fullscreen)
            t.side.setVisible(not self._fullscreen and t.btn_side.isChecked())
        (self.showFullScreen if self._fullscreen else self.showNormal)()

    # ================================================================== drag & drop / recovery / close
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".pdf") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for u in e.mimeData().urls():
            f = u.toLocalFile()
            if f.lower().endswith(".pdf"):
                self.open_path(f)
        e.acceptProposedAction()

    def check_recovery(self) -> int:
        """Offer to restore documents from an interrupted session. Returns number restored."""
        restored = 0
        for item in self.ctx.recovery.pending():
            when = time.strftime("%d %b %Y %H:%M", time.localtime(item.saved_at))
            name = Path(item.original).name
            if confirm(self, "Recover unsaved work", f"DocuCraft closed unexpectedly while <b>{name}</b> had unsaved changes "
                       f"(recovery copy from {when}).\n\nRestore it as a new file? Your original is not changed.",
                       yes="Restore", no="Discard"):
                dst = Path(item.original).with_name(f"{Path(item.original).stem} (recovered).pdf")
                try:
                    out = self.ctx.recovery.restore(item, dst)
                    self.ctx.recovery.discard(item.original)
                    self.open_path(str(out))
                    restored += 1
                except Exception as exc:
                    show_error(self, exc, "Recovery")
            else:
                self.ctx.recovery.discard(item.original)
        return restored

    def restore_session(self) -> None:
        if not self.ctx.settings.get("restore_session"):
            return
        for f in self.ctx.db.get_setting("session_files", []) or []:
            if Path(f).exists():
                self.open_path(f)

    def _restore_geometry(self) -> None:
        g = self.ctx.db.get_setting("window_geometry", None)
        if g:
            try:
                self.restoreGeometry(QByteArray.fromBase64(str(g).encode()))
            except Exception:
                pass

    def closeEvent(self, e) -> None:
        if self.ctx.jobs.active_count:
            if not confirm(self, "Work in progress", "A conversion or other task is still running. Cancel it and exit?",
                           yes="Cancel task and exit", no="Keep working"):
                e.ignore()
                return
            self.ctx.jobs.cancel_all()
            self.ctx.jobs.wait(8000)
        paths = []
        for i in range(self.tabs.count() - 1, -1, -1):
            t = self.tabs.widget(i)
            self.tabs.setCurrentIndex(i)
            if not t.maybe_close():
                e.ignore()
                return
            if not t.session.encrypted:
                paths.append(str(t.session.path))
        self.ctx.db.set_setting("session_files", list(reversed(paths)))
        self.ctx.db.set_setting("window_geometry", bytes(self.saveGeometry().toBase64()).decode())
        for i in range(self.tabs.count() - 1, -1, -1):
            self.tabs.widget(i).close_tab()
        if self.ctx.settings.get("clean_temp_on_exit"):
            sec.cleanup_temp()
        e.accept()
