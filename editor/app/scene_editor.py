"""Редактор сцены: список команд как сценарий + форма выбранной команды.

Слева — сцена строка за строкой (вложенные условия — веткой дерева), справа — поля выбранной строки.
Ctrl+Enter в тексте — новая реплика того же персонажа ниже. Выбор строки при запущенной игре
показывает её в игре (превью).
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QMimeData, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from vnformat.expr import to_text

from . import scene_ops as S
from .document import ProjectDocument

PATH_ROLE = Qt.UserRole
BRANCH_ROLE = Qt.UserRole + 1          # строка-заголовок ветки «иначе» внутри условия
POSITIONS = {"far_left": "слева у края", "left": "слева", "center": "в центре", "right": "справа",
             "far_right": "справа у края"}
TRANSITIONS = {"none": "сразу", "dissolve": "растворение", "fade": "через затемнение",
               "slide_left": "сдвиг влево", "slide_right": "сдвиг вправо", "zoom": "приближение"}
CHANNELS = {"music": "музыка", "sfx": "звуки", "voice": "голос", "all": "всё"}
KIND_COLORS = {"say": "#2c5d8f", "narrate": "#555", "choice": "#8a6d0b", "bg": "#3d7a5a", "show": "#6a4c93",
               "hide": "#6a4c93", "music": "#a0522d", "sfx": "#a0522d", "stop_audio": "#a0522d",
               "wait": "#777", "jump": "#b03a2e", "if": "#8a6d0b", "set": "#8a6d0b"}
ADD_ORDER = ["say", "narrate", "choice", "set", "if", "bg", "show", "hide", "music", "sfx", "stop_audio", "wait", "jump"]


class SceneEditor(QWidget):
    preview = Signal(str, str)           # узел, команда — показать в игре
    play_here = Signal(str, str)         # узел, команда — запустить/перевести игру сюда
    open_node = Signal(str)              # перейти к узлу на графе

    def __init__(self, doc: ProjectDocument, sid: str, parent=None):
        super().__init__(parent)
        self.doc, self.sid = doc, sid
        self.path: tuple | None = None
        self._thumbs: dict[str, QIcon] = {}
        self._building = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setTextFormat(Qt.RichText)
        self.title.linkActivated.connect(self.open_node.emit)
        head.addWidget(self.title, 1)
        for kind in ("say", "narrate", "choice"):
            b = QPushButton("+ " + S.KINDS[kind])
            b.clicked.connect(lambda _=False, k=kind: self.add(k))
            head.addWidget(b)
        more = QToolButton()
        more.setText("+ Ещё…")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        for kind in ADD_ORDER[3:]:
            menu.addAction(S.KINDS[kind], lambda k=kind: self.add(k))
        more.setMenu(menu)
        head.addWidget(more)
        play = QPushButton("▶ Отсюда")
        play.setToolTip("Играть с выбранной строки (F6)")
        play.clicked.connect(self.play_from_here)
        head.addWidget(play)
        self.sync = QCheckBox("показывать в игре")
        self.sync.setToolTip("Если игра запущена — выбор строки сразу показывает её в игре")
        self.sync.setChecked(QSettings("vn-constructor", "editor").value("scene_sync", False, type=bool))
        self.sync.toggled.connect(lambda on: QSettings("vn-constructor", "editor").setValue("scene_sync", on))
        head.addWidget(self.sync)
        for text, tip, slot in (("↑", "Выше (Alt+↑)", lambda: self.move(-1)), ("↓", "Ниже (Alt+↓)", lambda: self.move(1)),
                                ("✕", "Удалить (Del)", self.delete)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(30)
            b.clicked.connect(slot)
            head.addWidget(b)
        lay.addLayout(head)

        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Кто / что", "Текст"])
        self.tree.setColumnWidth(0, 110)
        self.tree.setColumnWidth(1, 200)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.currentItemChanged.connect(self._current_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context)
        split.addWidget(self.tree)
        self.form_area = QScrollArea()
        self.form_area.setWidgetResizable(True)
        self.form_area.setMinimumWidth(340)
        split.addWidget(self.form_area)
        split.setSizes([640, 420])
        lay.addWidget(split, 1)

        for seq, slot in ((QKeySequence.Copy, self.copy), (QKeySequence.Paste, self.paste),
                          (QKeySequence("Ctrl+D"), self.duplicate), (QKeySequence.Delete, self.delete),
                          (QKeySequence("Alt+Up"), lambda: self.move(-1)), (QKeySequence("Alt+Down"), lambda: self.move(1)),
                          (QKeySequence("Ctrl+Return"), lambda: self.add_like_current())):
            sc = QShortcut(seq, self.tree)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(slot)

        self._later = QTimer(self, singleShot=True, interval=0)
        self._later.timeout.connect(self.refresh)
        doc.changed.connect(self._doc_changed)
        self.refresh()

    # ----------------------------------------------------------- данные
    @property
    def scene(self) -> dict | None:
        return self.doc.scenes().get(self.sid)

    def node_id(self) -> str | None:
        return next((n["id"] for n in self.doc.nodes() if n.get("type") == "scene" and n.get("scene") == self.sid), None)

    def _doc_changed(self, keys):
        if any(k in (("scene", self.sid), "graph", "assets") or (isinstance(k, tuple) and k[0] in ("locale", "character"))
               for k in keys):
            self._later.start()

    # ----------------------------------------------------------- список
    def refresh(self):
        scene = self.scene
        if scene is None:
            return
        nid = self.node_id()
        node = self.doc.node(nid) if nid else None
        name = node.get("name", nid) if node else "сцена не привязана к графу"
        self.title.setText(f"<b>{name}</b> <span style='color:#888'>{self.sid}</span>"
                           + (f" · <a href='{nid}'>показать на графе</a>" if nid else ""))
        keep = self.path
        self._building = True
        self.tree.clear()
        self._fill(self.tree.invisibleRootItem(), scene.get("commands", []), ())
        self.tree.expandAll()
        self._building = False
        item = self._item_for(keep) if keep is not None else None
        if item is None and self.tree.topLevelItemCount():
            item = None if keep is None else self.tree.topLevelItem(min(keep[0], self.tree.topLevelItemCount() - 1))
        if item is not None:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(item, 0, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            self.tree.blockSignals(False)
            self.path = item.data(0, PATH_ROLE)
        focus = QApplication.focusWidget()
        if not (focus and self.form_area.isAncestorOf(focus)):
            self._build_form()

    def _fill(self, parent, cmds, prefix):
        chars = S.characters(self.doc)
        vars_ = self._var_names()
        targets = self._port_targets()
        for i, c in enumerate(cmds):
            path = prefix + (i,)
            kind = c.get("cmd", "?")
            who, text = "", ""
            if kind == "say":
                who = self.doc.text(chars.get(c.get("char"), {}).get("name")) or c.get("char", "")
                if c.get("expr"):
                    who += f" · {c['expr']}"
                text = self.doc.text(c.get("text"))
            elif kind == "narrate":
                text = self.doc.text(c.get("text"))
            elif kind in ("show", "hide"):
                who = self.doc.text(chars.get(c.get("char"), {}).get("name")) or c.get("char", "")
                if kind == "show":
                    text = " · ".join(x for x in (c.get("expr", ""), POSITIONS.get(c.get("at"), "")) if x)
            elif kind in ("bg", "music", "sfx"):
                who = self._asset_name(c.get("asset"))
            elif kind == "choice":
                text = " / ".join(self.doc.text(o.get("text")) for o in c.get("options", []))
            elif kind == "jump":
                text = "→ " + targets.get(c.get("port"), "никуда (свяжи выход на графе)")
            elif kind == "wait":
                text = f"{c.get('seconds', 0)} с"
            elif kind == "stop_audio":
                who = CHANNELS.get(c.get("channel"), "")
            elif kind == "if":
                text = "если " + to_text(c.get("condition"), vars_)
            elif kind == "set":
                text = "; ".join(self._effect_text(e, vars_) for e in c.get("effects", []))
            it = QTreeWidgetItem(parent, [S.KINDS.get(kind, kind), who, text.replace("\n", " ⏎ ")])
            it.setData(0, PATH_ROLE, path)
            it.setForeground(0, QBrush(QColor(KIND_COLORS.get(kind, "#333"))))
            f = it.font(0)
            f.setBold(kind in ("say", "narrate", "choice"))
            it.setFont(0, f)
            if kind == "bg" or (kind == "show" and c.get("char") in chars):
                icon = self._icon(c.get("asset") if kind == "bg" else
                                  chars[c["char"]].get("expressions", {}).get(c.get("expr") or chars[c["char"]].get("default_expression")))
                if icon:
                    it.setIcon(1, icon)
            if kind == "say" and not text:
                it.setText(2, "(пустая реплика — впиши текст справа)")
                it.setForeground(2, QBrush(QColor("#b26a00")))
            if kind == "choice":
                for o in c.get("options", []):
                    sub = QTreeWidgetItem(it, ["  ▸ вариант", "", f"{self.doc.text(o.get('text'))}   → "
                                               f"{targets.get(o.get('port'), 'никуда')}"])
                    sub.setData(0, PATH_ROLE, path)
                    sub.setForeground(0, QBrush(QColor("#8a6d0b")))
                    sub.setForeground(2, QBrush(QColor("#666")))
            if kind == "if":
                self._fill(it, c.get("then", []), path + ("then",))
                if "else" in c:
                    other = QTreeWidgetItem(it, ["иначе", "", ""])
                    other.setData(0, PATH_ROLE, path)
                    other.setData(0, BRANCH_ROLE, "else")
                    other.setForeground(0, QBrush(QColor("#8a6d0b")))
                    self._fill(other, c["else"], path + ("else",))

    def _item_for(self, path):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop(0)
            if it.data(0, PATH_ROLE) == path and not it.data(0, BRANCH_ROLE) and not it.text(0).startswith("  ▸"):
                return it
            stack.extend(it.child(i) for i in range(it.childCount()))
        return None

    def _selected_paths(self) -> list[tuple]:
        paths = []
        for it in self.tree.selectedItems():
            p = it.data(0, PATH_ROLE)
            if p is not None and p not in paths and not it.data(0, BRANCH_ROLE):
                paths.append(p)
        return paths

    def _current_changed(self, cur, _prev):
        if self._building or cur is None:
            return
        self.path = cur.data(0, PATH_ROLE)
        self._build_form()
        if self.sync.isChecked() and self.tree.hasFocus() and not getattr(self, "opening", False):  # только по действию пользователя
            nid, cid = self.node_id(), self.current_command_id()
            if nid and cid:
                self.preview.emit(nid, cid)

    def current_command_id(self) -> str:
        c = S.get(self.scene, self.path) if self.scene and self.path is not None else None
        return c.get("id", "") if c else ""

    def play_from_here(self):
        nid = self.node_id()
        if nid:
            self.play_here.emit(nid, self.current_command_id())

    def select(self, path):
        it = self._item_for(path)
        if it is not None:
            self.tree.setCurrentItem(it, 0, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            self.tree.scrollToItem(it)

    # ----------------------------------------------------------- действия
    def add(self, kind: str):
        """Новая команда после выбранной; если выбрано условие — внутрь него (в «то»), «иначе» — в «иначе»."""
        cur = self.tree.currentItem()
        c = S.get(self.scene, self.path) if self.path is not None else None
        inside = None
        if cur is not None and cur.data(0, BRANCH_ROLE):
            inside = "else"
        elif c is not None and c.get("cmd") == "if" and cur is not None and not cur.text(0).startswith("  ▸"):
            inside = "then"
        if kind == "set" and not (self.doc.get("variables") or {}).get("variables"):
            from .condition_editor import NewVariableDialog
            if not NewVariableDialog(self.doc, self).exec():
                return
        new = S.insert(self.doc, self.sid, self.path, kind, inside=inside)
        self._go(new)
        self._focus_text()

    def _go(self, path):
        """Сделать строку текущей и показать её форму (даже если фокус был в старой форме)."""
        self.path = path
        self.refresh()
        self.select(path)
        self._build_form()

    def add_like_current(self):
        c = S.get(self.scene, self.path) if self.path else None
        self.add(c.get("cmd") if c and c.get("cmd") in ("say", "narrate") else "say")

    def delete(self):
        paths = self._selected_paths()
        if paths:
            S.delete(self.doc, self.sid, paths)
            self.path = paths[0] if S.get(self.scene, paths[0]) else (paths[0][:-1] + (max(0, paths[0][-1] - 1),)
                                                                      if paths[0][-1] > 0 else None)

    def move(self, delta: int):
        if self.path is not None:
            self._go(S.move(self.doc, self.sid, self.path, delta))

    def copy(self) -> bool:
        paths = self._selected_paths()
        if not paths:
            return False
        payload = S.copy_commands(self.doc, self.sid, paths)
        mime = QMimeData()
        data = json.dumps(payload, ensure_ascii=False)
        mime.setData(S.CLIP_MIME, data.encode("utf-8"))
        mime.setText("\n".join(t for t in payload["texts"].values() if t))
        QApplication.clipboard().setMimeData(mime)
        return True

    def paste(self):
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return
        if mime.hasFormat(S.CLIP_MIME):
            payload = json.loads(bytes(mime.data(S.CLIP_MIME)).decode("utf-8"))
            new = S.paste_commands(self.doc, self.sid, self.path, payload)
        elif mime.hasText() and mime.text().strip():
            # обычный текст: каждая непустая строка — реплика рассказчика («вставить сценарий из Word»)
            lines = [ln.strip() for ln in mime.text().splitlines() if ln.strip()]
            cmds, texts = [], {}
            for ln in lines:
                k = self.doc.new_id("str")
                texts[k] = ln
                cmds.append({"id": "c_tmp", "cmd": "narrate", "text": k})
            new = S.paste_commands(self.doc, self.sid, self.path, {"commands": cmds, "texts": texts})
        else:
            return
        if new:
            self._go(new[-1])

    def duplicate(self):
        if self.copy():
            self.paste()

    def _context(self, pos):
        m = QMenu(self)
        add = m.addMenu("Добавить ниже")
        for kind in ADD_ORDER:
            add.addAction(S.KINDS[kind], lambda k=kind: self.add(k))
        m.addAction("▶ Играть отсюда\tF6", self.play_from_here)
        m.addSeparator()
        m.addAction("Копировать\tCtrl+C", self.copy)
        m.addAction("Вставить\tCtrl+V", self.paste)
        m.addAction("Дублировать\tCtrl+D", self.duplicate)
        m.addAction("Удалить\tDel", self.delete)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # ----------------------------------------------------------- форма
    def _focus_text(self):
        w = self.form_area.widget()
        edit = w.findChild(QPlainTextEdit) if w else None
        if edit is not None:
            edit.setFocus()

    def _build_form(self):
        old = self.form_area.takeWidget()
        if old is not None:
            old.deleteLater()
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignTop)
        self.form_area.setWidget(w)
        c = S.get(self.scene, self.path) if self.scene and self.path is not None else None
        if c is None:
            hint = QLabel("Выбери строку слева или добавь новую кнопками сверху.\n\n"
                          "Ctrl+Enter — новая реплика ниже\nCtrl+C / Ctrl+V — копировать строки\n"
                          "Вставка обычного текста — каждая строка станет репликой рассказчика\n"
                          "Alt+↑/↓ — переставить, Del — удалить")
            hint.setStyleSheet("color:#666")
            hint.setWordWrap(True)
            lay.addWidget(hint)
            return
        kind = c.get("cmd")
        head = QLabel(f"<b style='color:{KIND_COLORS.get(kind, '#333')}'>{S.KINDS.get(kind, kind)}</b> "
                      f"<span style='color:#999'>{c.get('id')}</span>")
        lay.addWidget(head)
        form = QFormLayout()
        lay.addLayout(form)
        path = self.path
        builder = getattr(self, f"_form_{kind}", None)
        if builder:
            builder(c, path, form, lay)

    def _set(self, path, text, merge=None, **fields):
        S.set_fields(self.doc, self.sid, path, text, merge=merge, **fields)

    def _text_box(self, key: str, form, label="Текст"):
        box = QPlainTextEdit(self.doc.text(key))
        box.setMinimumHeight(110)
        box.setFont(QFont(box.font().family(), box.font().pointSize() + 2))
        box.textChanged.connect(lambda: S.set_text(self.doc, key, box.toPlainText()))
        box.installEventFilter(self)
        form.addRow(label, box)
        return box

    def eventFilter(self, obj, ev):
        # Ctrl+Enter в тексте — следующая реплика
        if isinstance(obj, QPlainTextEdit) and ev.type() == ev.Type.KeyPress and \
                ev.key() in (Qt.Key_Return, Qt.Key_Enter) and ev.modifiers() & Qt.ControlModifier:
            self.add_like_current()
            return True
        return super().eventFilter(obj, ev)

    def _char_combo(self, current, allow_none=False):
        combo = QComboBox()
        if allow_none:
            combo.addItem("—", None)
        for cid, ch in S.characters(self.doc).items():
            combo.addItem(self.doc.text(ch.get("name")) or cid, cid)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        return combo

    def _expr_combo(self, char_id, current, keep_label=None):
        combo = QComboBox()
        combo.setIconSize(QSize(28, 40))
        if keep_label:
            combo.addItem(keep_label, None)
        ch = S.characters(self.doc).get(char_id, {})
        for e, aid in ch.get("expressions", {}).items():
            combo.addItem(self._icon(aid) or QIcon(), e, e)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        return combo

    def _asset_combo(self, kind, current, none_label=None):
        combo = QComboBox()
        combo.setIconSize(QSize(48, 27))
        if none_label:
            combo.addItem(none_label, None)
        for a in S.assets(self.doc, kind):
            combo.addItem(self._icon(a["id"]) or QIcon(), a["path"], a["id"])
        i = combo.findData(current)
        if i < 0 and current:
            combo.addItem(f"⚠ {current} (нет в реестре)", current)
            i = combo.count() - 1
        combo.setCurrentIndex(max(0, i))
        return combo

    def _transition(self, c, path, form, field="transition"):
        tr = c.get(field) or {}
        row = QHBoxLayout()
        kind = QComboBox()
        for k, v in TRANSITIONS.items():
            kind.addItem(v, k)
        kind.setCurrentIndex(max(0, kind.findData(tr.get("type", "none"))))
        dur = QDoubleSpinBox()
        dur.setRange(0, 10)
        dur.setSingleStep(0.1)
        dur.setSuffix(" с")
        dur.setValue(float(tr.get("duration", 0.3)))
        dur.setEnabled(kind.currentData() != "none")

        def apply():
            t = kind.currentData()
            self._set(path, "Переход", **{field: {"type": t, "duration": dur.value()} if t != "none" else None})
        kind.currentIndexChanged.connect(lambda _i: apply())
        dur.editingFinished.connect(apply)
        row.addWidget(kind, 1)
        row.addWidget(dur)
        form.addRow("Переход", row)

    def _form_say(self, c, path, form, lay):
        who = self._char_combo(c.get("char"))
        who.currentIndexChanged.connect(lambda _i: self._set(path, "Кто говорит", char=who.currentData(), expr=None))
        form.addRow("Кто", who)
        expr = self._expr_combo(c.get("char"), c.get("expr"), keep_label="не менять")
        expr.currentIndexChanged.connect(lambda _i: self._set(path, "Эмоция", expr=expr.currentData()))
        form.addRow("Эмоция", expr)
        self._text_box(c["text"], form)
        voice = self._asset_combo("audio", c.get("voice"), none_label="без озвучки")
        voice.currentIndexChanged.connect(lambda _i: self._set(path, "Озвучка", voice=voice.currentData()))
        form.addRow("Голос", voice)
        tip = QLabel("Ctrl+Enter — следующая реплика")
        tip.setStyleSheet("color:#888")
        lay.addWidget(tip)

    def _form_narrate(self, c, path, form, lay):
        self._text_box(c["text"], form)
        voice = self._asset_combo("audio", c.get("voice"), none_label="без озвучки")
        voice.currentIndexChanged.connect(lambda _i: self._set(path, "Озвучка", voice=voice.currentData()))
        form.addRow("Голос", voice)

    def _form_show(self, c, path, form, lay):
        who = self._char_combo(c.get("char"))
        who.currentIndexChanged.connect(lambda _i: self._set(path, "Персонаж", char=who.currentData(), expr=None))
        form.addRow("Кто", who)
        expr = self._expr_combo(c.get("char"), c.get("expr"), keep_label="как был / по умолчанию")
        expr.currentIndexChanged.connect(lambda _i: self._set(path, "Эмоция", expr=expr.currentData()))
        form.addRow("Эмоция", expr)
        at = QComboBox()
        at.addItem("не двигать", None)
        for k, v in POSITIONS.items():
            at.addItem(v, k)
        at.setCurrentIndex(max(0, at.findData(c.get("at")) if isinstance(c.get("at"), str) else 0))
        at.currentIndexChanged.connect(lambda _i: self._set(path, "Позиция", at=at.currentData()))
        form.addRow("Где", at)
        self._transition(c, path, form)

    def _form_hide(self, c, path, form, lay):
        who = self._char_combo(c.get("char"))
        who.currentIndexChanged.connect(lambda _i: self._set(path, "Персонаж", char=who.currentData()))
        form.addRow("Кого", who)
        self._transition(c, path, form)

    def _form_bg(self, c, path, form, lay):
        asset = self._asset_combo("image", c.get("asset"))
        asset.currentIndexChanged.connect(lambda _i: asset.currentData() and self._set(path, "Фон", asset=asset.currentData()))
        form.addRow("Фон", asset)
        self._transition(c, path, form)
        pic = self._pixmap(c.get("asset"), 320)
        if pic:
            img = QLabel()
            img.setPixmap(pic)
            lay.addWidget(img)

    def _form_music(self, c, path, form, lay):
        asset = self._asset_combo("audio", c.get("asset"), none_label="тишина (выключить)")
        asset.currentIndexChanged.connect(lambda _i: self._set_raw(path, "Музыка", "asset", asset.currentData()))
        form.addRow("Трек", asset)
        fade = QDoubleSpinBox()
        fade.setRange(0, 30)
        fade.setSuffix(" с")
        fade.setValue(float(c.get("fade", 0)))
        fade.editingFinished.connect(lambda: self._set(path, "Плавность", fade=fade.value() or None))
        form.addRow("Нарастание", fade)
        loop = QCheckBox("по кругу")
        loop.setChecked(c.get("loop", True))
        loop.toggled.connect(lambda on: self._set(path, "Повтор", loop=on))
        form.addRow("", loop)

    def _set_raw(self, path, text, field, value):
        """Поле, которое может быть null по смыслу (музыка: null — тишина)."""
        def fn(scene):
            S.get(scene, path)[field] = value
        S.edit_scene(self.doc, self.sid, fn, text)

    def _form_sfx(self, c, path, form, lay):
        asset = self._asset_combo("audio", c.get("asset"))
        asset.currentIndexChanged.connect(lambda _i: asset.currentData() and self._set(path, "Звук", asset=asset.currentData()))
        form.addRow("Звук", asset)
        vol = QDoubleSpinBox()
        vol.setRange(0, 1)
        vol.setSingleStep(0.1)
        vol.setValue(float(c.get("volume", 1)))
        vol.editingFinished.connect(lambda: self._set(path, "Громкость", volume=vol.value() if vol.value() < 1 else None))
        form.addRow("Громкость", vol)

    def _form_stop_audio(self, c, path, form, lay):
        ch = QComboBox()
        for k, v in CHANNELS.items():
            ch.addItem(v, k)
        ch.setCurrentIndex(max(0, ch.findData(c.get("channel"))))
        ch.currentIndexChanged.connect(lambda _i: self._set(path, "Канал", channel=ch.currentData()))
        form.addRow("Что остановить", ch)
        fade = QDoubleSpinBox()
        fade.setRange(0, 30)
        fade.setSuffix(" с")
        fade.setValue(float(c.get("fade", 0)))
        fade.editingFinished.connect(lambda: self._set(path, "Затухание", fade=fade.value() or None))
        form.addRow("Затухание", fade)

    def _form_wait(self, c, path, form, lay):
        sec = QDoubleSpinBox()
        sec.setRange(0.1, 600)
        sec.setSuffix(" с")
        sec.setValue(float(c.get("seconds", 1)))
        sec.editingFinished.connect(lambda: self._set(path, "Пауза", seconds=sec.value()))
        form.addRow("Длительность", sec)

    def _form_jump(self, c, path, form, lay):
        target = self._port_targets().get(c.get("port"))
        form.addRow("Выход", QLabel(c.get("port", "")))
        form.addRow("Ведёт", QLabel(target or "<span style='color:#c62828'>никуда — протяни связь от этого выхода на графе</span>"))

    def _form_choice(self, c, path, form, lay):
        vars_ = self._var_names()
        targets = self._port_targets()
        for k, o in enumerate(c.get("options", [])):
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 6, 0, 6)
            row = QHBoxLayout()
            edit = QLineEdit(self.doc.text(o.get("text")))
            edit.setPlaceholderText("текст варианта")
            edit.textEdited.connect(lambda t, key=o["text"]: S.set_text(self.doc, key, t))
            row.addWidget(QLabel(f"{k + 1}."))
            row.addWidget(edit, 1)
            rm = QPushButton("✕")
            rm.setFixedWidth(28)
            rm.setEnabled(len(c["options"]) > 1)
            rm.setToolTip("Удалить вариант (и его связь на графе)")
            rm.clicked.connect(lambda _=False, k=k: self._remove_option(path, k))
            row.addWidget(rm)
            bl.addLayout(row)
            cond = "всегда" if "condition" not in o else "если " + to_text(o["condition"], vars_)
            cb = QPushButton(f"✎ доступен: {cond}")
            cb.setStyleSheet("text-align:left; padding:3px 8px;")
            cb.clicked.connect(lambda _=False, k=k: self._option_dialog(path, k, condition=True))
            bl.addWidget(cb)
            if "condition" in o:
                row2 = QHBoxLayout()
                row2.addWidget(QLabel("когда недоступен:"))
                wu = QComboBox()
                wu.addItem("скрыть", "hide")
                wu.addItem("показать серым", "disable")
                wu.setCurrentIndex(max(0, wu.findData(o.get("when_unavailable", "hide"))))
                wu.currentIndexChanged.connect(lambda _i, k=k, wu=wu: self._set_option(path, k, "Недоступный вариант",
                                                                                      when_unavailable=wu.currentData()))
                row2.addWidget(wu, 1)
                drop = QPushButton("убрать условие")
                drop.clicked.connect(lambda _=False, k=k: self._set_option(path, k, "Убрать условие",
                                                                            condition=None, when_unavailable=None))
                row2.addWidget(drop)
                bl.addLayout(row2)
            from .condition_editor import describe_effects
            eff = describe_effects(o.get("effects", []), vars_) or "ничего"
            eb = QPushButton(f"✎ при выборе: {eff}")
            eb.setStyleSheet("text-align:left; padding:3px 8px;")
            eb.clicked.connect(lambda _=False, k=k: self._option_dialog(path, k, condition=False))
            bl.addWidget(eb)
            info = QLabel(f"<span style='color:#666'>ведёт: "
                          f"{targets.get(o['port']) or '<span style=color:#c62828>никуда — свяжи выход на графе</span>'}</span>")
            info.setWordWrap(True)
            bl.addWidget(info)
            lay.addWidget(box)
        add = QPushButton("+ вариант")
        add.clicked.connect(lambda: self._add_option(path))
        lay.addWidget(add)
        note = QLabel("Куда ведёт вариант — связь от его выхода на графе.")
        note.setStyleSheet("color:#888")
        note.setWordWrap(True)
        lay.addWidget(note)

    def _set_option(self, path, k, text, **fields):
        def fn(scene):
            o = S.get(scene, path)["options"][k]
            for f, v in fields.items():
                if v is None:
                    o.pop(f, None)
                else:
                    o[f] = v
        S.edit_scene(self.doc, self.sid, fn, text)

    def _option_dialog(self, path, k, condition: bool):
        from .condition_editor import ExprDialog
        o = S.get(self.scene, path)["options"][k]
        label = self.doc.text(o.get("text")) or f"вариант {k + 1}"
        if condition:
            dlg = ExprDialog(self.doc, f"Когда доступен «{label}»", condition=o.get("condition"), parent=self)
            if dlg.exec():
                value = dlg.condition()
                self._set_option(path, k, "Условие варианта", condition=None if value is True else value,
                                 when_unavailable=None if value is True else o.get("when_unavailable", "hide"))
        else:
            dlg = ExprDialog(self.doc, f"Что меняется при выборе «{label}»", effects=o.get("effects", []),
                             show_condition=False, show_effects=True, parent=self)
            if dlg.exec():
                self._set_option(path, k, "Эффекты варианта", effects=dlg.effects() or None)

    def _add_option(self, path):
        key = self.doc.new_id("str")
        port = "p_" + self.doc.new_id("x")[2:]
        n = len(S.get(self.scene, path).get("options", [])) + 1

        def fn(scene):
            S.get(scene, path)["options"].append({"id": "o_" + self.doc.new_id("x")[2:], "text": key, "port": port})
        S.edit_scene(self.doc, self.sid, fn, "Добавить вариант", texts={key: f"Вариант {n}"})

    def _remove_option(self, path, k):
        S.edit_scene(self.doc, self.sid, lambda scene: S.get(scene, path)["options"].pop(k), "Удалить вариант")

    def _form_if(self, c, path, form, lay):
        cb = QPushButton("✎ " + to_text(c.get("condition"), self._var_names()))
        cb.setStyleSheet("text-align:left; padding:4px 8px;")

        def edit_cond():
            from .condition_editor import ExprDialog
            dlg = ExprDialog(self.doc, "Условие", condition=c.get("condition"), parent=self)
            if dlg.exec():
                self._set(path, "Изменить условие", condition=dlg.condition())
        cb.clicked.connect(edit_cond)
        form.addRow("Если", cb)
        other = QCheckBox("есть ветка «иначе»")
        other.setChecked("else" in c)

        def toggle(on):
            def fn(scene):
                cmd = S.get(scene, path)
                if on:
                    cmd.setdefault("else", [])
                else:
                    cmd.pop("else", None)
            S.edit_scene(self.doc, self.sid, fn, "Ветка «иначе»")
        other.toggled.connect(toggle)
        form.addRow("", other)
        note = QLabel("Чтобы добавить команду внутрь условия — выбери эту строку (или «иначе») и нажми «+».")
        note.setStyleSheet("color:#888")
        note.setWordWrap(True)
        lay.addWidget(note)

    def _form_set(self, c, path, form, lay):
        from .condition_editor import EffectsEditor
        ed = EffectsEditor(self.doc, c.get("effects", []))

        def apply():
            effects = ed.value()
            if effects:
                self._set(path, "Изменить переменные", merge=f"effects:{c['id']}", effects=effects)
        ed.changed.connect(apply)
        lay.addWidget(ed)
        note = QLabel("Значение — число, да/нет, «текст» или формула: смелость + 1")
        note.setStyleSheet("color:#888")
        lay.addWidget(note)

    # ----------------------------------------------------------- мелочи
    def _var_names(self):
        return {v["id"]: v["name"] for v in (self.doc.get("variables") or {}).get("variables", [])}

    @staticmethod
    def _effect_text(e, vars_):
        name = vars_.get(e.get("var"), e.get("var", ""))
        op = e.get("op")
        if op == "toggle":
            return f"переключить {name}"
        if op == "call":
            return f"{e.get('fn')}()"
        sym = {"set": "=", "add": "+=", "sub": "−=", "mul": "×="}.get(op, op)
        return f"{name} {sym} {to_text(e.get('value'), vars_)}"

    def _port_targets(self) -> dict[str, str]:
        nid = self.node_id()
        names = {n["id"]: n.get("name", n["id"]) for n in self.doc.nodes()}
        return {e["from"]["port"]: names.get(e["to"], e["to"]) for e in self.doc.edges() if e["from"]["node"] == nid}

    def _asset_name(self, aid):
        if aid is None:
            return "тишина"
        a = next((a for a in (self.doc.get("assets") or {}).get("assets", []) if a.get("id") == aid), None)
        return Path(a["path"]).stem if a else f"⚠ {aid}"

    def _asset_file(self, aid) -> Path | None:
        a = next((a for a in (self.doc.get("assets") or {}).get("assets", []) if a.get("id") == aid), None)
        if a and self.doc.root:
            p = self.doc.root / "assets" / a["path"]
            return p if p.is_file() else None
        return None

    def _pixmap(self, aid, width) -> QPixmap | None:
        f = self._asset_file(aid)
        if f is None or f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            return None
        pm = QPixmap(str(f))
        return pm.scaledToWidth(width, Qt.SmoothTransformation) if not pm.isNull() else None

    def _icon(self, aid) -> QIcon | None:
        if not aid:
            return None
        if aid not in self._thumbs:
            pm = self._pixmap(aid, 96)
            self._thumbs[aid] = QIcon(pm) if pm else None
        return self._thumbs[aid]
