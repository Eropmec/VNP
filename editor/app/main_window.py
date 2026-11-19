"""Главное окно редактора."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QPushButton, QSizePolicy, QFileDialog, QInputDialog, QLabel, QMainWindow, QMessageBox, QTabBar, QTabWidget, QToolBar, QWidget,
)

from vnformat.template import create_project, slug

from .document import ProjectDocument
from .graph_view import GraphView
from .inspector import Inspector
from .playtest import PlaytestPanel
from .problems import ProblemsPanel
from .db_editors import AssetsEditor, CharactersEditor, VariablesEditor
from .scene_editor import SceneEditor

APP_TITLE = "Конструктор визуальных новелл"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("vn-constructor", "editor")
        self.doc = ProjectDocument(self)
        self.resize(1600, 950)

        self.graph = GraphView(self.doc)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.addTab(self.graph, "Сюжет")
        self.tabs.tabBar().setTabButton(0, QTabBar.RightSide, None)
        self.tabs.tabBar().setTabButton(0, QTabBar.LeftSide, None)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.setCentralWidget(self.tabs)
        self.scene_tabs: dict[str, SceneEditor] = {}
        self.db_tabs: dict[str, QWidget] = {}
        self.inspector = Inspector(self.doc)
        self.problems = ProblemsPanel(self.doc)
        self.playtest = PlaytestPanel(self.doc)
        self.docks = [self._dock("Свойства", self.inspector, Qt.RightDockWidgetArea),
                      self._dock("Игра", self.playtest, Qt.RightDockWidgetArea),
                      self._dock("Проблемы", self.problems, Qt.BottomDockWidgetArea)]
        self.default_layout()
        self._default_state = self.saveState()

        self.graph.selection_changed.connect(lambda ids: self.inspector.show_node(ids[0] if len(ids) == 1 else None))
        self.graph.node_activated.connect(self._activated)
        self.graph.container_changed.connect(self._update_crumbs)
        self.inspector.open_chapter.connect(self.graph.enter)
        self.inspector.open_scene.connect(self.open_scene)
        self.doc.changed.connect(self._sync_tabs)
        self.doc.reloaded.connect(self._close_scene_tabs)
        self.problems.goto_node.connect(self.graph.select)
        self.playtest.position.connect(self._follow)
        self.doc.undo.cleanChanged.connect(lambda _c: self._update_title())
        self.doc.reloaded.connect(self._update_title)

        self._menus()
        state = self.settings.value("window_state")
        if state is not None:
            self.restoreState(state)
        geom = self.settings.value("window_geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        self._update_title()
        self._update_crumbs(None)
        self.statusBar().showMessage("Открой проект: Файл → Открыть (Ctrl+O)")

    def default_layout(self):
        d1, d2, d3 = self.docks
        for d in self.docks:
            d.setFloating(False)
            d.show()
        self.addDockWidget(Qt.RightDockWidgetArea, d1)
        self.addDockWidget(Qt.RightDockWidgetArea, d2)
        self.addDockWidget(Qt.BottomDockWidgetArea, d3)
        self.resizeDocks([d1, d2], [430, 470], Qt.Vertical)
        self.resizeDocks([d1], [520], Qt.Horizontal)
        self.resizeDocks([d3], [150], Qt.Vertical)

    def _dock(self, title: str, widget: QWidget, area) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName(title)
        d.setWidget(widget)
        self.addDockWidget(area, d)
        return d

    # ----------------------------------------------------------- меню
    def _menus(self):
        def act(menu, text, slot, shortcut=None, tip=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setStatusTip(tip)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        m = self.menuBar().addMenu("&Файл")
        act(m, "Новый проект…", self.new_project, "Ctrl+N")
        act(m, "Открыть…", self.open_dialog, "Ctrl+O")
        self.recent_menu = m.addMenu("Недавние")
        self._fill_recent()
        m.addSeparator()
        act(m, "Сохранить", self.save, "Ctrl+S")
        act(m, "Сохранить как…", self.save_as, "Ctrl+Shift+S")
        m.addSeparator()
        act(m, "Выход", self.close, "Ctrl+Q")

        m = self.menuBar().addMenu("&Правка")
        undo = self.doc.undo.createUndoAction(self, "Отменить")
        undo.setShortcut(QKeySequence.Undo)
        redo = self.doc.undo.createRedoAction(self, "Повторить")
        redo.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Y")])
        m.addAction(undo)
        m.addAction(redo)
        m.addSeparator()
        act(m, "Удалить выбранное", self._delete_current)

        m = self.menuBar().addMenu("&Граф")
        act(m, "Наверх (к главам)", lambda: self.graph.enter(None), "Ctrl+Up")
        act(m, "Вписать в окно (F)", self.graph.fit)
        act(m, "Расставить узлы автоматически", self.graph.arrange, "Ctrl+L")
        m.addSeparator()
        for kind, text in (("scene", "Новая сцена"), ("branch", "Новое ветвление"),
                           ("ending", "Новая концовка"), ("chapter", "Новая глава")):
            act(m, text, lambda _=False, k=kind: self._create_center(k))

        m = self.menuBar().addMenu("&Проект")
        act(m, "Переменные", lambda: self.open_db("vars"), "Ctrl+Shift+V")
        act(m, "Персонажи", lambda: self.open_db("chars"), "Ctrl+Shift+C")
        act(m, "Ассеты (картинки и звук)", lambda: self.open_db("assets"), "Ctrl+Shift+A")
        m.addSeparator()
        act(m, "Настройки игры…", self._project_settings)

        m = self.menuBar().addMenu("&Окна")
        for d, key in zip(self.docks, ("Ctrl+1", "Ctrl+2", "Ctrl+3")):
            a = d.toggleViewAction()
            a.setShortcut(QKeySequence(key))
            m.addAction(a)
        m.addSeparator()
        act(m, "Вернуть панели на место", self.default_layout)

        m = self.menuBar().addMenu("&Игра")
        act(m, "Играть с начала", lambda: self.playtest.run(None), "F5")
        act(m, "Играть с выбранного узла", self._play_selected, "F6")
        act(m, "Играть в отдельном окне", self.playtest.detach, "F7")
        act(m, "Запустить как игрок (с главным меню)", self.playtest.run_as_player, "Ctrl+F5")
        act(m, "Остановить", self.playtest.stop, "Shift+F5")
        m.addSeparator()
        act(m, "Собрать игру (Windows, Linux, Android)…", self.build_game, "Ctrl+B")
        act(m, "Путь к Godot…", self.playtest.choose_godot)

        tb = QToolBar("Граф")
        tb.setObjectName("graph-toolbar")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.crumbs = QLabel()
        self.crumbs.setTextFormat(Qt.RichText)
        self.crumbs.linkActivated.connect(lambda link: self.graph.enter(None if link == "root" else link))
        tb.addWidget(self.crumbs)
        tb.addSeparator()
        for kind, text in (("scene", "+ Сцена"), ("branch", "+ Ветвление"), ("ending", "+ Концовка"), ("chapter", "+ Глава")):
            tb.addAction(text, lambda k=kind: self._create_center(k))
        tb.addSeparator()
        tb.addAction("Расставить", self.graph.arrange)
        tb.addAction("Вписать", self.graph.fit)
        tb.addSeparator()
        tb.addAction("Переменные", lambda: self.open_db("vars"))
        tb.addAction("Персонажи", lambda: self.open_db("chars"))
        tb.addAction("Ассеты", lambda: self.open_db("assets"))
        tb.addSeparator()
        tb.addAction("▶ Играть", lambda: self.playtest.run(None))
        # справа — переключатели панелей: закрытую панель видно и легко вернуть
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        tb.addWidget(QLabel("Панели: "))
        for d in self.docks:
            a = d.toggleViewAction()
            a.setToolTip(f"Показать / скрыть панель «{d.windowTitle()}»")
            tb.addAction(a)

        self.problem_badge = QPushButton("✔ проблем нет")
        self.problem_badge.setFlat(True)
        self.problem_badge.setToolTip("Открыть панель «Проблемы»")
        self.problem_badge.clicked.connect(self._show_problems)
        self.statusBar().addPermanentWidget(self.problem_badge)
        self.problems.counts_changed.connect(self._update_badge)

    def _project_settings(self):
        if self.doc.root is None:
            return
        from .project_settings import ProjectSettingsDialog
        if ProjectSettingsDialog(self.doc, self).exec():
            self._update_title()

    def _show_problems(self):
        d = self.docks[2]
        d.setFloating(False) if not d.isVisible() and d.isFloating() else None
        d.show()
        d.raise_()

    def _update_badge(self, errors: int, warnings: int):
        if errors or warnings:
            self.problem_badge.setText(f"✖ ошибок: {errors}   ⚠ предупреждений: {warnings}")
            self.problem_badge.setStyleSheet("color:#c62828; font-weight:bold" if errors else "color:#b26a00")
        else:
            self.problem_badge.setText("✔ проблем нет")
            self.problem_badge.setStyleSheet("color:#2e7d32")

    def _fill_recent(self):
        self.recent_menu.clear()
        for path in self.settings.value("recent", [], type=list):
            if (Path(path) / "project.json").is_file():
                self.recent_menu.addAction(path, lambda p=path: self.open(p))
        self.recent_menu.setEnabled(not self.recent_menu.isEmpty())

    # ----------------------------------------------------------- файлы
    def _confirm_discard(self) -> bool:
        if not self.doc.dirty:
            return True
        r = QMessageBox.question(self, APP_TITLE, "Сохранить изменения в проекте?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            self.save()
            return True
        return r == QMessageBox.Discard

    def open_dialog(self):
        path = QFileDialog.getExistingDirectory(self, "Папка проекта (где лежит project.json)",
                                                self.settings.value("last_dir", ""))
        if path:
            self.open(path)

    def open(self, path: str | Path) -> bool:
        path = Path(path)
        if not (path / "project.json").is_file():
            QMessageBox.warning(self, APP_TITLE, f"В папке нет project.json:\n{path}")
            return False
        if not self._confirm_discard():
            return False
        self.doc.load(path)
        self.settings.setValue("last_dir", str(path.parent))
        recent = [str(path)] + [p for p in self.settings.value("recent", [], type=list) if p != str(path)]
        self.settings.setValue("recent", recent[:8])
        self._fill_recent()
        problems = getattr(self.doc, "load_problems", [])
        if problems:
            QMessageBox.warning(self, APP_TITLE, "Часть файлов не прочиталась:\n\n" + "\n".join(problems))
        fixed = self.doc.repair_missing_texts()
        if fixed:
            self.statusBar().showMessage(f"Открыт {path}. Восстановлено пропавших текстов: {fixed} — "
                                         "они пустые, их видно в «Проблемах»; Ctrl+S сохранит", 12000)
            return True
        self.statusBar().showMessage(f"Открыт {path}", 4000)
        return True

    def new_project(self):
        if not self._confirm_discard():
            return
        title, ok = QInputDialog.getText(self, "Новый проект", "Название игры:")
        if not ok or not title.strip():
            return
        parent = QFileDialog.getExistingDirectory(self, "Где создать папку проекта", self.settings.value("last_dir", ""))
        if not parent:
            return
        root = Path(parent) / slug(title.strip())
        try:
            create_project(root, title.strip())
        except FileExistsError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        self.doc.undo.setClean()
        self.open(root)

    def save(self):
        if self.doc.root is None:
            return
        written = self.doc.save()
        self.statusBar().showMessage(f"Сохранено файлов: {len(written)}", 3000)
        self.playtest.reload()

    def build_game(self):
        if self.doc.root is None:
            return
        godot = self.playtest.godot_path()
        if not godot:
            return
        from .build_dialog import BuildDialog
        dlg = BuildDialog(self, self.doc, godot, self.save, self._show_problems)
        dlg.exec()

    def save_as(self):
        if self.doc.root is None:
            return
        path = QFileDialog.getExistingDirectory(self, "Пустая папка для копии проекта")
        if path:
            self.doc.save_as(path)
            self._update_title()

    # ----------------------------------------------------------- граф
    def _create_center(self, kind: str):
        if self.doc.root is None:
            return
        self.graph.create_node(kind, self.graph.mapToScene(self.graph.viewport().rect().center()))

    def _activated(self, nid: str):
        node = self.doc.node(nid)
        if node and node.get("type") == "chapter":
            self.graph.enter(nid)
        elif node and node.get("type") == "scene" and node.get("scene") in self.doc.scenes():
            self.open_scene(node["scene"])

    # ----------------------------------------------------------- вкладки сцен
    def open_scene(self, sid: str) -> SceneEditor | None:
        if sid not in self.doc.scenes():
            return None
        ed = self.scene_tabs.get(sid)
        if ed is None:
            ed = SceneEditor(self.doc, sid)
            ed.preview.connect(self._preview)
            ed.play_here.connect(lambda n, c: self.playtest.run(n, command=c))
            ed.open_node.connect(self._show_on_graph)
            self.scene_tabs[sid] = ed
            self.tabs.addTab(ed, self._tab_title(sid))
        ed.opening = True                       # открыть сцену ≠ перевести туда игру
        self.tabs.setCurrentWidget(ed)
        ed.tree.setFocus()
        QApplication.processEvents()
        ed.opening = False
        return ed

    DB_TABS = {"vars": ("Переменные", VariablesEditor), "chars": ("Персонажи", CharactersEditor),
               "assets": ("Ассеты", AssetsEditor)}

    def open_db(self, kind: str) -> QWidget | None:
        if self.doc.root is None:
            return None
        w = self.db_tabs.get(kind)
        if w is None:
            title, cls = self.DB_TABS[kind]
            w = cls(self.doc)
            w.goto_use.connect(self._goto_use)
            self.db_tabs[kind] = w
            self.tabs.addTab(w, "▤ " + title)
        self.tabs.setCurrentWidget(w)
        return w

    def _goto_use(self, use):
        if use.scene:
            ed = self.open_scene(use.scene)
            if ed and use.path is not None:
                ed.select(use.path)
        elif use.node:
            self._show_on_graph(use.node)

    def _tab_title(self, sid: str) -> str:
        node = next((n for n in self.doc.nodes() if n.get("type") == "scene" and n.get("scene") == sid), None)
        return "✎ " + (node.get("name", sid) if node else sid)

    def _close_tab(self, index: int):
        w = self.tabs.widget(index)
        if w is self.graph:
            return
        self.tabs.removeTab(index)
        for sid, ed in list(self.scene_tabs.items()):
            if ed is w:
                del self.scene_tabs[sid]
        for kind, ed in list(self.db_tabs.items()):
            if ed is w:
                del self.db_tabs[kind]
        w.deleteLater()

    def _sync_tabs(self, _keys):
        for sid, ed in list(self.scene_tabs.items()):
            i = self.tabs.indexOf(ed)
            if sid not in self.doc.scenes():
                self._close_tab(i)
            else:
                self.tabs.setTabText(i, self._tab_title(sid))

    def _close_scene_tabs(self):
        for ed in list(self.scene_tabs.values()) + list(self.db_tabs.values()):
            self._close_tab(self.tabs.indexOf(ed))

    def _show_on_graph(self, nid: str):
        self.tabs.setCurrentWidget(self.graph)
        self.graph.select(nid)

    def _preview(self, nid: str, cid: str):
        if self.playtest.running:
            self.playtest.link.call("play.goto", node=nid, command=cid)

    def _delete_current(self):
        w = self.tabs.currentWidget()
        if isinstance(w, SceneEditor):
            w.delete()
        else:
            self.graph.delete_selected()

    def _play_selected(self):
        w = self.tabs.currentWidget()
        if isinstance(w, SceneEditor):
            w.play_from_here()
            return
        sel = [i.nid for i in self.graph.scene().selectedItems() if hasattr(i, "nid")]
        self.playtest.run(sel[0] if sel else None)

    def _follow(self, node: str, command: str):
        if self.tabs.currentWidget() is not self.graph:
            ed = self.tabs.currentWidget()
            if isinstance(ed, SceneEditor) and ed.node_id() == node and command:
                from . import scene_ops
                for path, c in scene_ops.walk(ed.scene.get("commands", [])):
                    if c.get("id") == command and path != ed.path:
                        ed.tree.blockSignals(True)
                        ed.select(path)
                        ed.path = path
                        ed.tree.blockSignals(False)
                        ed._build_form()
            return
        if node and node not in [i.nid for i in self.graph.scene().selectedItems() if hasattr(i, "nid")]:
            self.graph.select(node)

    def _update_crumbs(self, container):
        parts = ["<a href='root'>Сюжет</a>"]
        chain = []
        cur = container
        while cur:
            n = self.doc.node(cur)
            if not n:
                break
            chain.append(n)
            cur = n.get("parent")
        for n in reversed(chain):
            parts.append(f"<a href='{n['id']}'>{n.get('name', n['id'])}</a>")
        self.crumbs.setText("  ›  ".join(parts) + "&nbsp;&nbsp;")

    def _update_title(self):
        if self.doc.root is None:
            self.setWindowTitle(APP_TITLE)
            return
        title = (self.doc.get("project") or {}).get("title", self.doc.root.name)
        self.setWindowTitle(f"{'● ' if self.doc.dirty else ''}{title} — {APP_TITLE}")

    def closeEvent(self, ev):
        if not self._confirm_discard():
            ev.ignore()
            return
        self.settings.setValue("window_state", self.saveState())
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.playtest.stop()
        if self.playtest.proc is not None:
            self.playtest.proc.waitForFinished(1500)
        super().closeEvent(ev)
