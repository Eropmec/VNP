"""Редакторы баз проекта: переменные, персонажи, ассеты. Открываются вкладками («Проект» в меню)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter,
    QStyle, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import db_ops as D
from .document import ProjectDocument

IMAGE_FILTER = "Картинки (*.png *.jpg *.jpeg *.webp)"
ALL_FILTER = "Картинки и звук (*.png *.jpg *.jpeg *.webp *.wav *.ogg *.mp3);;Все файлы (*)"
TYPE_TITLES = {"int": "целое", "float": "дробное", "bool": "да / нет", "string": "текст"}
SCOPE_TITLES = {"playthrough": "в сохранении", "persistent": "навсегда (между прохождениями)"}
NAME_RE = re.compile(r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*")


def _thumb(path: Path | None, size: int) -> QIcon | None:
    if path is None or not path.is_file() or D.KIND_BY_EXT.get(path.suffix.lower()) != "image":
        return None
    pm = QPixmap(str(path))
    return QIcon(pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)) if not pm.isNull() else None


def places(n: int) -> str:
    """1 место, 2 места, 5 мест."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} место"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} места"
    return f"{n} мест"


def _hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet("color:#777")
    lab.setWordWrap(True)
    return lab


def uses_menu(parent: QWidget, doc: ProjectDocument, kind: str, ident: str, goto: Signal, pos):
    uses = D.find_uses(doc, kind, ident)
    m = QMenu(parent)
    if not uses:
        m.addAction("нигде не используется").setEnabled(False)
    for u in uses:
        a = m.addAction(u.where)
        a.triggered.connect(lambda _=False, u=u: goto.emit(u))
    m.exec(pos)


class _DropList(QListWidget):
    """Список, принимающий файлы из Проводника."""
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


# ================================================================ переменные

class VariablesEditor(QWidget):
    goto_use = Signal(object)
    COLS = ["Название", "Имя в формулах", "Тип", "Сначала", "Мин", "Макс", "Хранится", "Категория", "Где"]

    def __init__(self, doc: ProjectDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self._building = False
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        add = QPushButton("+ Переменная")
        add.clicked.connect(self.add)
        rm = QPushButton("Удалить")
        rm.clicked.connect(self.delete)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("поиск…")
        self.filter.textChanged.connect(lambda _t: self.refresh())
        for w in (add, rm):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.filter)
        lay.addLayout(bar)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        for c, w in enumerate([170, 150, 100, 80, 60, 60, 190, 120, 90]):
            self.table.setColumnWidth(c, w)
        h.setStretchLastSection(True)
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellDoubleClicked.connect(self._cell_double)
        lay.addWidget(self.table, 1)
        self.status = QLabel()
        lay.addWidget(self.status)
        lay.addWidget(_hint("Имя в формулах — как переменная пишется в условиях: «смелость ≥ 1». Его можно менять: "
                            "условия хранят ID, а не имя. «Навсегда» — открытые концовки, достижения: не сбрасываются "
                            "новой игрой. Двойной клик по «Где» — список мест, где переменная используется."))
        self._later = QTimer(self, singleShot=True, interval=0)
        self._later.timeout.connect(self.refresh)
        doc.changed.connect(lambda keys: self._later.start() if "variables" in keys or
                            any(isinstance(k, tuple) and k[0] == "scene" for k in keys) or "graph" in keys else None)
        doc.reloaded.connect(self.refresh)
        self.refresh()

    def _ids(self) -> list[str]:
        return [self.table.item(r, 0).data(Qt.UserRole) for r in range(self.table.rowCount())]

    def refresh(self):
        cur = self.table.currentRow(), self.table.currentColumn()
        flt = self.filter.text().strip().lower()
        vs = [v for v in D.variables(self.doc)
              if not flt or flt in json.dumps(v, ensure_ascii=False).lower()]
        self._building = True
        self.table.setRowCount(len(vs))
        for r, v in enumerate(vs):
            def cell(c, text, editable=True, data=None):
                it = QTableWidgetItem("" if text is None else str(text))
                if not editable:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if data is not None:
                    it.setData(Qt.UserRole, data)
                self.table.setItem(r, c, it)
                return it
            cell(0, v.get("title") or v["name"], data=v["id"]).setToolTip(v["id"])
            cell(1, v["name"])
            cell(2, "", editable=False)
            d = v.get("default")
            cell(3, ("да" if d else "нет") if isinstance(d, bool) else d)
            cell(4, v.get("min"), editable=v["type"] in ("int", "float"))
            cell(5, v.get("max"), editable=v["type"] in ("int", "float"))
            cell(6, "", editable=False)
            cell(7, v.get("category", ""))
            n = len(D.find_uses(self.doc, "var", v["id"]))
            u = cell(8, places(n) if n else "не используется", editable=False)
            if not n:
                u.setForeground(QBrush(QColor("#999")))
            t = QComboBox()
            for k, title in TYPE_TITLES.items():
                t.addItem(title, k)
            t.setCurrentIndex(t.findData(v["type"]))
            t.currentIndexChanged.connect(lambda _i, vid=v["id"], t=t: self._type(vid, t.currentData()))
            self.table.setCellWidget(r, 2, t)
            s = QComboBox()
            for k, title in SCOPE_TITLES.items():
                s.addItem(title, k)
            s.setCurrentIndex(max(0, s.findData(v.get("scope", "playthrough"))))
            s.currentIndexChanged.connect(lambda _i, vid=v["id"], s=s: D.update_variable(
                self.doc, vid, "Хранение переменной", scope=s.currentData()))
            self.table.setCellWidget(r, 6, s)
        self._building = False
        if 0 <= cur[0] < self.table.rowCount():
            self.table.setCurrentCell(cur[0], max(0, cur[1]))
        self.status.setText(f"Переменных: {len(D.variables(self.doc))}")

    def _err(self, text):
        self.status.setText(f"<span style='color:#c62828'>✖ {text}</span>")
        self._later.start()

    def _item_changed(self, it: QTableWidgetItem):
        if self._building:
            return
        vid = self._ids()[it.row()]
        v = next(x for x in D.variables(self.doc) if x["id"] == vid)
        text = it.text().strip()
        c = it.column()
        if c == 0:
            D.update_variable(self.doc, vid, "Название переменной", title=text or None)
        elif c == 1:
            name = text.replace(" ", "_")
            if not NAME_RE.fullmatch(name):
                return self._err("имя: буквы, цифры и _, не с цифры")
            if any(x["name"].lower() == name.lower() and x["id"] != vid for x in D.variables(self.doc)):
                return self._err(f"имя «{name}» уже занято")
            D.update_variable(self.doc, vid, "Имя переменной", name=name)
        elif c == 3:
            try:
                value = self._parse(v["type"], text)
            except ValueError:
                return self._err(f"«{text}» не подходит к типу «{TYPE_TITLES[v['type']]}»")
            D.update_variable(self.doc, vid, "Начальное значение", default=value)
        elif c in (4, 5):
            try:
                value = None if text == "" else self._parse(v["type"], text)
            except ValueError:
                return self._err("нужно число")
            D.update_variable(self.doc, vid, "Диапазон", **{"min" if c == 4 else "max": value})
        elif c == 7:
            D.update_variable(self.doc, vid, "Категория", category=text or None)

    @staticmethod
    def _parse(kind: str, text: str):
        if kind == "int":
            return int(float(text.replace(",", ".")))
        if kind == "float":
            return float(text.replace(",", "."))
        if kind == "bool":
            if text.lower() in ("да", "true", "1", "yes"):
                return True
            if text.lower() in ("нет", "false", "0", "no", ""):
                return False
            raise ValueError(text)
        return text

    def _type(self, vid: str, kind: str):
        defaults = {"int": 0, "float": 0.0, "bool": False, "string": ""}
        D.update_variable(self.doc, vid, "Тип переменной", type=kind, default=defaults[kind],
                          **({"min": None, "max": None} if kind in ("bool", "string") else {}))

    def _cell_double(self, r, c):
        if c == 8:
            uses_menu(self, self.doc, "var", self._ids()[r], self.goto_use,
                      self.table.viewport().mapToGlobal(self.table.visualItemRect(self.table.item(r, c)).bottomLeft()))

    def add(self):
        vid = D.add_variable(self.doc)
        self.refresh()
        r = self._ids().index(vid)
        self.table.setCurrentCell(r, 0)
        self.table.editItem(self.table.item(r, 0))

    def delete(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        ids = {self._ids()[r] for r in rows}
        if not ids:
            return
        used = {vid: D.find_uses(self.doc, "var", vid) for vid in ids}
        used = {k: v for k, v in used.items() if v}
        if used:
            names = {v["id"]: v["name"] for v in D.variables(self.doc)}
            text = "\n".join(f"• {names[k]}: {places(len(v))}" for k, v in used.items())
            if QMessageBox.question(self, "Переменная используется",
                                    f"Эти переменные используются в сюжете:\n{text}\n\nУдалить всё равно? "
                                    "Условия с ними станут ошибками.") != QMessageBox.Yes:
                return
        D.delete_variables(self.doc, ids)


# ================================================================ персонажи

class CharactersEditor(QWidget):
    goto_use = Signal(object)

    def __init__(self, doc: ProjectDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.cid: str | None = None
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setIconSize(QSize(40, 56))
        self.list.currentItemChanged.connect(lambda cur, _p: self.show_char(cur.data(Qt.UserRole) if cur else None))
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton("+ Персонаж")
        add.clicked.connect(self.add)
        rm = QPushButton("Удалить")
        rm.clicked.connect(self.delete)
        row.addWidget(add)
        row.addWidget(rm)
        left.addLayout(row)
        lw = QWidget()
        lw.setLayout(left)
        lw.setMaximumWidth(300)
        lay.addWidget(lw)

        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._name)
        self.color = QPushButton()
        self.color.clicked.connect(self._pick_color)
        self.ident = QLabel()
        self.ident.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.used = QPushButton()
        self.used.clicked.connect(lambda: self.cid and uses_menu(self, doc, "char", self.cid, self.goto_use,
                                                                self.used.mapToGlobal(self.used.rect().bottomLeft())))
        form.addRow("Имя", self.name)
        form.addRow("Цвет имени", self.color)
        form.addRow("ID", self.ident)
        form.addRow("Используется", self.used)
        right.addLayout(form)
        right.addWidget(QLabel("<b>Эмоции</b> — перетащи сюда картинки из Проводника"))
        self.exprs = _DropList()
        self.exprs.setViewMode(QListWidget.IconMode)
        self.exprs.setIconSize(QSize(120, 170))
        self.exprs.setGridSize(QSize(150, 210))
        self.exprs.setResizeMode(QListWidget.Adjust)
        self.exprs.setMovement(QListWidget.Static)
        self.exprs.files_dropped.connect(self.add_expressions)
        self.exprs.itemDoubleClicked.connect(lambda _it: self._rename_expr())
        right.addWidget(self.exprs, 1)
        btns = QHBoxLayout()
        for text, slot in (("+ из файлов…", self._expr_files), ("Переименовать", self._rename_expr),
                           ("Заменить картинку…", self._replace_expr), ("★ Основная", self._default_expr),
                           ("Удалить эмоцию", self._delete_expr)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        right.addLayout(btns)
        right.addWidget(_hint("Имя эмоции выбирается в редакторе сцены. Имя берётся из файла: anna_sad.png → sad, "
                              "Анна-грустная.png → грустная. Основная (★) — эмоция, если в сцене не указана другая."))
        rw = QWidget()
        rw.setLayout(right)
        lay.addWidget(rw, 1)
        self._later = QTimer(self, singleShot=True, interval=0)
        self._later.timeout.connect(self.refresh)
        doc.changed.connect(lambda keys: self._later.start() if any(
            isinstance(k, tuple) and k[0] in ("character", "locale") for k in keys) or "assets" in keys else None)
        doc.reloaded.connect(self.refresh)
        self.refresh()

    def char(self) -> dict | None:
        return D.characters(self.doc).get(self.cid) if self.cid else None

    def refresh(self):
        chars = D.characters(self.doc)
        keep = self.cid if self.cid in chars else next(iter(chars), None)
        self.list.blockSignals(True)
        self.list.clear()
        for cid, ch in chars.items():
            it = QListWidgetItem(self.doc.text(ch.get("name")) or cid)
            it.setData(Qt.UserRole, cid)
            it.setForeground(QBrush(QColor(ch.get("color", "#333")).darker(140)))
            icon = _thumb(D.asset_file(self.doc, ch.get("expressions", {}).get(ch.get("default_expression"), "")), 64)
            if icon:
                it.setIcon(icon)
            self.list.addItem(it)
            if cid == keep:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        self.show_char(keep)

    def show_char(self, cid: str | None):
        self.cid = cid
        ch = self.char()
        for w in (self.name, self.color, self.used, self.exprs):
            w.setEnabled(ch is not None)
        self.exprs.clear()
        if ch is None:
            self.name.setText("")
            self.ident.setText("")
            return
        if not self.name.hasFocus():
            self.name.setText(self.doc.text(ch.get("name")))
        self.color.setText(ch.get("color", "#ffffff"))
        self.color.setStyleSheet(f"background:{ch.get('color', '#ffffff')}; padding:4px 16px;")
        self.ident.setText(cid)
        n = len(D.find_uses(self.doc, "char", cid))
        self.used.setText(f"{places(n)} ▾" if n else "нигде ▾")
        for e, aid in ch.get("expressions", {}).items():
            title = ("★ " if e == ch.get("default_expression") else "") + e
            it = QListWidgetItem(title)
            it.setData(Qt.UserRole, e)
            icon = _thumb(D.asset_file(self.doc, aid), 170)
            it.setIcon(icon or self.style().standardIcon(QStyle.SP_FileIcon))
            if icon is None:
                it.setToolTip(f"нет файла для {aid}")
                it.setForeground(QBrush(QColor("#c62828")))
            self.exprs.addItem(it)

    def _edit_char(self, text, fn):
        self.doc.edit(text, {("character", self.cid): fn})

    def _name(self):
        ch = self.char()
        if ch and self.name.text().strip() and self.name.text() != self.doc.text(ch.get("name")):
            key = ch["name"]
            self.doc.edit("Имя персонажа", {("locale", self.doc.language): lambda loc: {**loc, key: self.name.text().strip()}})

    def _pick_color(self):
        ch = self.char()
        if not ch:
            return
        c = QColorDialog.getColor(QColor(ch.get("color", "#ffffff")), self, "Цвет имени")
        if c.isValid():
            self._edit_char("Цвет персонажа", lambda d: d.update(color=c.name()))

    def add(self):
        if self.doc.root is None:
            return
        title, ok = QInputDialog.getText(self, "Новый персонаж", "Имя персонажа:")
        if not ok or not title.strip():
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Картинки эмоций (можно пропустить — будет силуэт)", "", IMAGE_FILTER)
        self.cid = D.new_character(self.doc, title.strip(), images=files)
        self.refresh()

    def delete(self):
        if not self.cid:
            return
        uses = D.find_uses(self.doc, "char", self.cid)
        msg = f"Удалить персонажа «{self.name.text()}»?"
        if uses:
            msg += f"\n\nОн встречается в сюжете {len(uses)} раз — эти строки станут ошибками."
        if QMessageBox.question(self, "Удалить персонажа", msg) == QMessageBox.Yes:
            D.delete_character(self.doc, self.cid)
            self.cid = None

    def add_expressions(self, files: list[str]):
        ch = self.char()
        if not ch:
            return
        files = [f for f in files if D.KIND_BY_EXT.get(Path(f).suffix.lower()) == "image"]
        if not files:
            return
        self.doc.undo.beginMacro("Добавить эмоции")
        ids = D.import_files(self.doc, files, role="sprite")
        names = {}
        for f, aid in zip(files, ids):
            name = D.expression_name(Path(f), self.cid)
            base, n = name, 2
            while name in ch["expressions"] or name in names:
                name = f"{base}_{n}"
                n += 1
            names[name] = aid
        self._edit_char("Добавить эмоции", lambda d: d["expressions"].update(names))
        self.doc.undo.endMacro()

    def _expr_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Картинки эмоций", "", IMAGE_FILTER)
        self.add_expressions(files)

    def _current_expr(self) -> str | None:
        it = self.exprs.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _rename_expr(self):
        old = self._current_expr()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Эмоция", "Новое имя эмоции:", text=old)
        new = new.strip().replace(" ", "_")
        if not ok or not new or new == old:
            return
        if not NAME_RE.fullmatch(new) or new in self.char()["expressions"]:
            QMessageBox.warning(self, "Эмоция", "Имя: буквы, цифры и _, не с цифры, и не повторяться")
            return
        self.rename_expression(old, new)

    def rename_expression(self, old: str, new: str):
        """Переименовать эмоцию и все её упоминания в сценах — одной правкой."""
        from . import scene_ops as S
        cid = self.cid
        changes = {("character", cid): lambda d: d.update(
            expressions={(new if k == old else k): v for k, v in d["expressions"].items()},
            default_expression=new if d["default_expression"] == old else d["default_expression"])}
        for sid, scene in self.doc.scenes().items():
            if any(c.get("char") == cid and c.get("expr") == old for _p, c in S.walk(scene.get("commands", []))):
                def fix(s):
                    for _p, c in S.walk(s["commands"]):
                        if c.get("char") == cid and c.get("expr") == old:
                            c["expr"] = new
                changes[("scene", sid)] = fix
        self.doc.edit(f"Переименовать эмоцию {old} → {new}", changes)

    def _replace_expr(self):
        e = self._current_expr()
        if not e:
            return
        f, _ = QFileDialog.getOpenFileName(self, f"Новая картинка для «{e}»", "", IMAGE_FILTER)
        if f:
            self.doc.undo.beginMacro("Заменить картинку эмоции")
            aid = D.import_files(self.doc, [f], role="sprite")[0]
            self._edit_char("Заменить картинку эмоции", lambda d: d["expressions"].update({e: aid}))
            self.doc.undo.endMacro()

    def _default_expr(self):
        e = self._current_expr()
        if e:
            self._edit_char("Основная эмоция", lambda d: d.update(default_expression=e))

    def _delete_expr(self):
        e = self._current_expr()
        ch = self.char()
        if not e or not ch:
            return
        if len(ch["expressions"]) <= 1:
            QMessageBox.information(self, "Эмоция", "У персонажа должна остаться хотя бы одна эмоция.")
            return

        def fn(d):
            d["expressions"].pop(e)
            if d["default_expression"] == e:
                d["default_expression"] = next(iter(d["expressions"]))
        self._edit_char("Удалить эмоцию", fn)


# ================================================================ ассеты

class AssetsEditor(QWidget):
    goto_use = Signal(object)
    KINDS = [("", "Все"), ("image", "Картинки"), ("audio", "Звук"), ("other", "Прочее")]

    def __init__(self, doc: ProjectDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self._player = None
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.kind = QComboBox()
        for k, t in self.KINDS:
            self.kind.addItem(t, k)
        self.kind.currentIndexChanged.connect(lambda _i: self.refresh())
        self.search = QLineEdit()
        self.search.setPlaceholderText("поиск по имени…")
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.unused = QCheckBox("только неиспользуемые")
        self.unused.toggled.connect(lambda _on: self.refresh())
        self.role = QComboBox()
        self.role.addItem("картинки как фоны", "bg")
        self.role.addItem("картинки как спрайты", "sprite")
        self.role.addItem("картинки — прочее", "image")
        add = QPushButton("+ Добавить файлы…")
        add.clicked.connect(self._add_dialog)
        rm = QPushButton("Убрать из проекта")
        rm.clicked.connect(self.remove)
        for w in (self.kind, self.search, self.unused):
            bar.addWidget(w)
        bar.addStretch(1)
        for w in (QLabel("Новые:"), self.role, add, rm):
            bar.addWidget(w)
        lay.addLayout(bar)
        split = QSplitter()
        self.list = _DropList()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(144, 96))
        self.list.setGridSize(QSize(170, 140))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.files_dropped.connect(lambda files: self.import_files(files))
        self.list.currentItemChanged.connect(lambda cur, _p: self.preview(cur.data(Qt.UserRole) if cur else None))
        split.addWidget(self.list)
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setAlignment(Qt.AlignTop)
        self.pic = QLabel()
        self.pic.setAlignment(Qt.AlignCenter)
        self.pic.setMinimumHeight(200)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.play = QPushButton("▶ Прослушать")
        self.play.clicked.connect(self._toggle_play)
        self.uses = QPushButton()
        self.uses.clicked.connect(self._uses)
        for w in (self.pic, self.info, self.play, self.uses):
            sl.addWidget(w)
        side.setMinimumWidth(320)
        split.addWidget(side)
        split.setSizes([900, 360])
        lay.addWidget(split, 1)
        lay.addWidget(_hint("Перетащи картинки и звуки из Проводника в список — они скопируются в папку assets "
                            "проекта. «Убрать из проекта» снимает файл с учёта, сам файл остаётся в папке."))
        self._current: str | None = None
        self._later = QTimer(self, singleShot=True, interval=0)
        self._later.timeout.connect(self.refresh)
        doc.changed.connect(lambda keys: self._later.start() if "assets" in keys else None)
        doc.reloaded.connect(self.refresh)
        self.refresh()

    def refresh(self):
        kind = self.kind.currentData()
        q = self.search.text().strip().lower()
        keep = self._current
        self.list.blockSignals(True)
        self.list.clear()
        for a in sorted(D.asset_list(self.doc), key=lambda a: a["path"]):
            if kind and (a["kind"] if kind != "other" else ("other" if a["kind"] not in ("image", "audio") else "")) != kind:
                continue
            if q and q not in a["path"].lower() and q not in a["id"]:
                continue
            used = bool(D.find_uses(self.doc, "asset", a["id"]))
            if self.unused.isChecked() and used:
                continue
            f = D.asset_file(self.doc, a["id"])
            it = QListWidgetItem(Path(a["path"]).name)
            it.setData(Qt.UserRole, a["id"])
            icon = _thumb(f, 144)
            if icon is None:
                icon = self.style().standardIcon(QStyle.SP_MediaVolume if a["kind"] == "audio" else QStyle.SP_FileIcon)
            it.setIcon(icon)
            it.setToolTip(f"{a['id']}\n{a['path']}" + ("" if used else "\nнигде не используется"))
            if f is None or not f.is_file():
                it.setForeground(QBrush(QColor("#c62828")))
                it.setText("⚠ " + it.text())
            elif not used:
                it.setForeground(QBrush(QColor("#999")))
            self.list.addItem(it)
            if a["id"] == keep:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        self.preview(keep if self.list.currentItem() else None)

    def preview(self, aid: str | None):
        self._current = aid
        self._stop()
        a = next((x for x in D.asset_list(self.doc) if x["id"] == aid), None)
        self.play.setVisible(bool(a and a["kind"] == "audio"))
        self.uses.setVisible(a is not None)
        if a is None:
            self.pic.clear()
            self.info.setText("Выбери файл слева.")
            return
        f = D.asset_file(self.doc, aid)
        size = f"{f.stat().st_size / 1024:.0f} КБ" if f and f.is_file() else "файла нет на диске"
        extra = ""
        if a["kind"] == "image" and f and f.is_file():
            pm = QPixmap(str(f))
            extra = f" · {pm.width()}×{pm.height()}"
            self.pic.setPixmap(pm.scaled(320, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.pic.clear()
        self.info.setText(f"<b>{Path(a['path']).name}</b><br>ID: {a['id']}<br>Путь: assets/{a['path']}<br>{size}{extra}")
        n = len(D.find_uses(self.doc, "asset", aid))
        self.uses.setText(f"Используется: {places(n)} ▾" if n else "Нигде не используется")

    def _uses(self):
        if self._current:
            uses_menu(self, self.doc, "asset", self._current, self.goto_use,
                      self.uses.mapToGlobal(self.uses.rect().bottomLeft()))

    def import_files(self, files: list[str]) -> list[str]:
        ids = D.import_files(self.doc, files, role=self.role.currentData())
        skipped = len(files) - len(ids)
        if skipped:
            QMessageBox.information(self, "Ассеты", f"Пропущено файлов: {skipped} — подходят картинки "
                                                    "(png, jpg, webp) и звук (wav, ogg, mp3).")
        if ids:
            self._current = ids[-1]
            self.refresh()
        return ids

    def _add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Добавить в проект", "", ALL_FILTER)
        if files:
            self.import_files(files)

    def remove(self):
        ids = {it.data(Qt.UserRole) for it in self.list.selectedItems()}
        if not ids:
            return
        used = [aid for aid in ids if D.find_uses(self.doc, "asset", aid)]
        msg = f"Убрать из проекта файлов: {len(ids)}? Сами файлы останутся в папке assets."
        if used:
            msg += f"\n\nИспользуются в сюжете: {len(used)} — эти места станут ошибками."
        if QMessageBox.question(self, "Убрать ассеты", msg) == QMessageBox.Yes:
            D.remove_assets(self.doc, ids)

    def _toggle_play(self):
        if self._player is not None and self._player.isPlaying():
            self._stop()
            return
        f = D.asset_file(self.doc, self._current) if self._current else None
        if not f or not f.is_file():
            return
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        self._player = QMediaPlayer(self)
        self._out = QAudioOutput(self)
        self._player.setAudioOutput(self._out)
        self._player.setSource(QUrl.fromLocalFile(str(f)))
        self._player.playbackStateChanged.connect(
            lambda st: self.play.setText("■ Стоп" if st == QMediaPlayer.PlayingState else "▶ Прослушать"))
        self._player.play()

    def _stop(self):
        if self._player is not None:
            self._player.stop()
