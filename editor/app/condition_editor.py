"""Конструктор условий и редактор эффектов.

Условие показывается двумя способами одновременно:
- блоками: группа «все условия (И)» / «любое (ИЛИ)», в ней строки «переменная · оператор · значение»,
  «уже был в узле …» и вложенные группы; у каждой строки галочка «не»;
- формулой текстом: рассудок > 3 и (флаг или смелость ≥ 1).
Правка в любом из видов сразу отражается в другом. Всё, что не укладывается в блоки, становится
строкой-формулой внутри группы — так в блоках можно показать любое выражение.
"""
from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from vnformat.expr import TYPE_TITLES, TypeChecker, fits, to_text
from vnformat.expr_parse import ParseError, parse

from .document import ProjectDocument

CMP_OPS = [("==", "="), ("!=", "≠"), ("<", "<"), ("<=", "≤"), (">", ">"), (">=", "≥")]
EFFECT_OPS = [("set", "станет"), ("add", "прибавить"), ("sub", "отнять"), ("mul", "умножить на"), ("toggle", "переключить")]
NEW_VAR = "__new__"


# ---------------------------------------------------------------- переменные

def variables(doc: ProjectDocument) -> list[dict]:
    return [v for v in (doc.get("variables") or {}).get("variables", []) if isinstance(v, dict) and "id" in v]


class NewVariableDialog(QDialog):
    """Быстрое создание переменной прямо из условия или эффекта."""

    def __init__(self, doc: ProjectDocument, parent=None):
        super().__init__(parent)
        self.doc, self.created = doc, None
        self.setWindowTitle("Новая переменная")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("например: смелость")
        self.kind = QComboBox()
        for k, t in (("int", "целое число"), ("bool", "да / нет"), ("float", "дробное число"), ("string", "текст")):
            self.kind.addItem(t, k)
        self.default = QLineEdit("0")
        self.kind.currentIndexChanged.connect(lambda _i: self.default.setText(
            {"int": "0", "bool": "нет", "float": "0", "string": ""}[self.kind.currentData()]))
        self.err = QLabel()
        self.err.setStyleSheet("color:#c62828")
        form.addRow("Имя", self.name)
        form.addRow("Тип", self.kind)
        form.addRow("Сначала", self.default)
        form.addRow(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _ok(self):
        import re
        name = self.name.text().strip().replace(" ", "_")
        if not re.fullmatch(r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*", name):
            self.err.setText("Имя: буквы, цифры и _, не с цифры")
            return
        if any(v["name"].lower() == name.lower() for v in variables(self.doc)):
            self.err.setText("Такая переменная уже есть")
            return
        kind = self.kind.currentData()
        raw = self.default.text().strip()
        try:
            value = {"int": lambda: int(raw or 0), "float": lambda: float(raw.replace(",", ".") or 0),
                     "bool": lambda: raw.lower() in ("да", "true", "1"), "string": lambda: raw}[kind]()
        except ValueError:
            self.err.setText("Значение не подходит к типу")
            return
        vid = self.doc.new_id("v")
        var = {"id": vid, "name": name, "title": name.replace("_", " ").capitalize(), "type": kind,
               "default": value, "scope": "playthrough"}
        def add(d):
            d = d or {"variables": []}
            d.setdefault("variables", []).append(var)
            return d
        self.doc.edit(f"Новая переменная {name}", {"variables": add})
        self.created = vid
        self.accept()


def var_combo(doc: ProjectDocument, current: str | None, parent=None, allow_new=True) -> QComboBox:
    combo = QComboBox(parent)
    for v in variables(doc):
        combo.addItem(f"{v.get('title') or v['name']}  ({v['name']})", v["id"])
    if allow_new:
        combo.addItem("＋ новая переменная…", NEW_VAR)
    i = combo.findData(current)
    combo.setCurrentIndex(i if i >= 0 else (0 if variables(doc) else -1))
    return combo


def ask_new_variable(doc: ProjectDocument, combo: QComboBox, fallback: str | None, parent) -> str | None:
    dlg = NewVariableDialog(doc, parent)
    if dlg.exec() and dlg.created:
        v = next(x for x in variables(doc) if x["id"] == dlg.created)
        combo.blockSignals(True)
        combo.insertItem(combo.count() - 1, f"{v.get('title') or v['name']}  ({v['name']})", v["id"])
        combo.setCurrentIndex(combo.findData(v["id"]))
        combo.blockSignals(False)
        return v["id"]
    combo.blockSignals(True)
    combo.setCurrentIndex(max(0, combo.findData(fallback)))
    combo.blockSignals(False)
    return None


# ---------------------------------------------------------------- модель блоков

def to_blocks(e: Any) -> dict:
    """Выражение → группа блоков {kind: group, op, neg, items}."""
    neg = False
    if isinstance(e, dict) and e.get("op") == "not" and isinstance(e.get("arg"), dict) and e["arg"].get("op") in ("and", "or"):
        neg, e = True, e["arg"]
    if isinstance(e, dict) and e.get("op") in ("and", "or"):
        return {"kind": "group", "op": e["op"], "neg": neg, "items": [_item(a) for a in e["args"]]}
    if e is True:
        return {"kind": "group", "op": "and", "neg": False, "items": []}
    return {"kind": "group", "op": "and", "neg": False, "items": [_item(e)]}


def _item(e: Any) -> dict:
    neg = False
    if isinstance(e, dict) and e.get("op") == "not":
        neg, e = True, e["arg"]
    if isinstance(e, dict) and e.get("op") in ("and", "or"):
        g = to_blocks(e)
        g["neg"] = neg
        return g
    if isinstance(e, dict) and e.get("op") in dict(CMP_OPS) and isinstance(e.get("l"), dict) and "var" in e["l"]:
        return {"kind": "cmp", "neg": neg, "var": e["l"]["var"], "op": e["op"], "value": e["r"]}
    if isinstance(e, dict) and e.get("op") == "call" and e.get("fn") == "visited" and \
            len(e.get("args", [])) == 1 and isinstance(e["args"][0], str):
        return {"kind": "visited", "neg": neg, "node": e["args"][0]}
    return {"kind": "formula", "neg": neg, "expr": e}


def from_blocks(b: dict) -> Any:
    if b["kind"] == "group":
        parts = [from_blocks(i) for i in b["items"]]
        e = True if not parts else parts[0] if len(parts) == 1 else {"op": b["op"], "args": parts}
    elif b["kind"] == "cmp":
        e = {"op": b["op"], "l": {"var": b["var"]}, "r": b["value"]}
    elif b["kind"] == "visited":
        e = {"op": "call", "fn": "visited", "args": [b["node"]]}
    else:
        e = b["expr"]
    return {"op": "not", "arg": e} if b.get("neg") else e


# ---------------------------------------------------------------- виджеты блоков

class _Row(QFrame):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, editor: "ConditionEditor", block: dict):
        super().__init__()
        self.editor, self.block = editor, block
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 2, 0, 2)
        self.neg = QCheckBox("не")
        self.neg.setChecked(block.get("neg", False))
        self.neg.setToolTip("Обратить: условие верно, когда это НЕ выполняется")
        self.neg.toggled.connect(self._neg)
        self.lay.addWidget(self.neg)

    def _neg(self, on):
        self.block["neg"] = on
        self.changed.emit()

    def finish(self):
        rm = QPushButton("✕")
        rm.setFixedWidth(26)
        rm.setToolTip("Убрать")
        rm.clicked.connect(lambda: self.removed.emit(self))
        self.lay.addWidget(rm)


class _CmpRow(_Row):
    def __init__(self, editor, block):
        super().__init__(editor, block)
        doc = editor.doc
        self.var = var_combo(doc, block["var"])
        self.var.currentIndexChanged.connect(self._var)
        self.op = QComboBox()
        for k, t in CMP_OPS:
            self.op.addItem(t, k)
        self.op.setCurrentIndex(max(0, self.op.findData(block["op"])))
        self.op.currentIndexChanged.connect(lambda _i: self._set("op", self.op.currentData()))
        self.value = QLineEdit(to_text(block["value"], editor.names()))
        self.value.setPlaceholderText("значение или формула")
        self.value.setToolTip("Число, да/нет, «текст» или формула: смелость + 1")
        self.value.editingFinished.connect(self._value)
        for w, stretch in ((self.var, 3), (self.op, 0), (self.value, 2)):
            self.lay.addWidget(w, stretch)
        self.finish()

    def _set(self, k, v):
        self.block[k] = v
        self.changed.emit()

    def _var(self, _i):
        vid = self.var.currentData()
        if vid == NEW_VAR:
            vid = ask_new_variable(self.editor.doc, self.var, self.block["var"], self)
            if vid is None:
                return
        self.block["var"] = vid
        t = next((v["type"] for v in variables(self.editor.doc) if v["id"] == vid), "int")
        if t == "bool" and not isinstance(self.block["value"], bool):
            self.block["value"] = True
            self.value.setText("да")
        self.changed.emit()

    def _value(self):
        try:
            self.block["value"] = parse(self.value.text() or "0", variables(self.editor.doc))
            self.value.setStyleSheet("")
            self.changed.emit()
        except ParseError as exc:
            self.value.setStyleSheet("background:#fdecea")
            self.value.setToolTip(str(exc))


class _VisitedRow(_Row):
    def __init__(self, editor, block):
        super().__init__(editor, block)
        self.lay.addWidget(QLabel("уже был в узле"))
        self.node = QComboBox()
        for n in editor.doc.nodes():
            if n.get("type") != "chapter":
                self.node.addItem(n.get("name", n["id"]), n["id"])
        self.node.setCurrentIndex(max(0, self.node.findData(block["node"])))
        self.node.currentIndexChanged.connect(lambda _i: (self.block.update(node=self.node.currentData()), self.changed.emit()))
        self.lay.addWidget(self.node, 1)
        self.finish()


class _FormulaRow(_Row):
    def __init__(self, editor, block):
        super().__init__(editor, block)
        self.edit = QLineEdit(to_text(block["expr"], editor.names()))
        self.edit.editingFinished.connect(self._edit)
        self.lay.addWidget(QLabel("формула"))
        self.lay.addWidget(self.edit, 1)
        self.finish()

    def _edit(self):
        try:
            self.block["expr"] = parse(self.edit.text(), variables(self.editor.doc))
            self.edit.setStyleSheet("")
            self.changed.emit()
        except ParseError as exc:
            self.edit.setStyleSheet("background:#fdecea")
            self.edit.setToolTip(str(exc))


class _GroupBox(QFrame):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, editor: "ConditionEditor", block: dict, nested: bool):
        super().__init__()
        self.editor, self.block = editor, block
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("_GroupBox { border-left: 3px solid #b8860b; }" if nested else "")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 6, 6)
        lay.setAlignment(Qt.AlignTop)
        head = QHBoxLayout()
        self.neg = QCheckBox("не")
        self.neg.setChecked(block.get("neg", False))
        self.neg.toggled.connect(lambda on: (block.update(neg=on), self.changed.emit()))
        self.op = QComboBox()
        self.op.addItem("выполнены ВСЕ условия (И)", "and")
        self.op.addItem("выполнено ЛЮБОЕ условие (ИЛИ)", "or")
        self.op.setCurrentIndex(0 if block["op"] == "and" else 1)
        self.op.currentIndexChanged.connect(lambda _i: (block.update(op=self.op.currentData()), self.changed.emit()))
        head.addWidget(self.neg)
        head.addWidget(self.op, 1)
        if nested:
            rm = QPushButton("✕")
            rm.setFixedWidth(26)
            rm.clicked.connect(lambda: self.removed.emit(self))
            head.addWidget(rm)
        lay.addLayout(head)
        self.rows = QVBoxLayout()
        lay.addLayout(self.rows)
        if not block["items"]:
            empty = QLabel("условий нет — значит «всегда»")
            empty.setStyleSheet("color:#888; margin:4px")
            self.rows.addWidget(empty)
        for item in block["items"]:
            self.rows.addWidget(self._row(item))
        add = QHBoxLayout()
        for text, maker in (("+ сравнение", self._new_cmp), ("+ был в узле", self._new_visited),
                            ("+ группа", self._new_group), ("+ формула", self._new_formula)):
            b = QPushButton(text)
            b.clicked.connect(maker)
            add.addWidget(b)
        add.addStretch(1)
        lay.addLayout(add)

    def _row(self, item):
        w = {"cmp": _CmpRow, "visited": _VisitedRow, "formula": _FormulaRow}.get(item["kind"])
        w = _GroupBox(self.editor, item, nested=True) if item["kind"] == "group" else w(self.editor, item)
        w.changed.connect(self.changed.emit)
        w.removed.connect(self._remove)
        return w

    def _remove(self, w):
        self.block["items"].remove(w.block)
        self.editor.rebuild_blocks()
        self.changed.emit()

    def _add(self, item):
        self.block["items"].append(item)
        self.editor.rebuild_blocks()
        self.changed.emit()

    def _new_cmp(self):
        vs = variables(self.editor.doc)
        if not vs:
            dummy = QComboBox()
            dummy.addItem("", NEW_VAR)
            vid = ask_new_variable(self.editor.doc, dummy, None, self)
            if vid is None:
                return
            vs = variables(self.editor.doc)
        v = vs[0]
        value = True if v["type"] == "bool" else (0 if v["type"] in ("int", "float") else "")
        self._add({"kind": "cmp", "neg": False, "var": v["id"], "op": "==" if v["type"] in ("bool", "string") else ">=",
                   "value": value})

    def _new_visited(self):
        node = next((n["id"] for n in self.editor.doc.nodes() if n.get("type") != "chapter"), "n_x")
        self._add({"kind": "visited", "neg": False, "node": node})

    def _new_group(self):
        self._add({"kind": "group", "op": "or", "neg": False, "items": []})

    def _new_formula(self):
        self._add({"kind": "formula", "neg": False, "expr": True})


class ConditionEditor(QWidget):
    """Условие: блоки + формула. value() — текущее дерево; ok() — без ошибок."""
    changed = Signal()

    def __init__(self, doc: ProjectDocument, value: Any = True, parent=None):
        super().__init__(parent)
        self.doc = doc
        self._value = copy.deepcopy(value)
        self._error = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Формула:"))
        self.formula = QLineEdit()
        f = self.formula.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        self.formula.setFont(f)
        self.formula.setPlaceholderText("например: рассудок > 3 и (флаг или смелость ≥ 1)")
        self.formula.textEdited.connect(lambda _t: self._typing.start())
        self.formula.editingFinished.connect(self._formula_done)
        lay.addWidget(self.formula)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addWidget(QLabel("Или собери из блоков:"))
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setMinimumHeight(220)
        lay.addWidget(self.area, 1)
        self._typing = QTimer(self, singleShot=True, interval=500)
        self._typing.timeout.connect(self._formula_done)
        self.blocks = to_blocks(self._value)
        self.rebuild_blocks()
        self._sync_formula()

    def names(self) -> dict[str, str]:
        return {v["id"]: v["name"] for v in variables(self.doc)}

    def value(self) -> Any:
        return copy.deepcopy(self._value)

    def ok(self) -> bool:
        return not self._error

    def rebuild_blocks(self):
        root = _GroupBox(self, self.blocks, nested=False)
        root.changed.connect(self._blocks_changed)
        old = self.area.takeWidget()
        self.area.setWidget(root)
        if old is not None:
            old.deleteLater()

    def _blocks_changed(self):
        self._value = from_blocks(self.blocks)
        self._sync_formula()
        self.changed.emit()

    def _sync_formula(self):
        self.formula.setText(to_text(self._value, self.names()) if self._value is not True else "да")
        self._check()

    def _formula_done(self):
        self._typing.stop()
        text = self.formula.text().strip() or "да"
        try:
            value = parse(text, variables(self.doc))
        except ParseError as exc:
            self._error = str(exc)
            self.status.setText(f"<span style='color:#c62828'>✖ {exc}</span>")
            self.formula.setStyleSheet("background:#fdecea")
            return
        self.formula.setStyleSheet("")
        if value != self._value:
            self._value = value
            self.blocks = to_blocks(value)
            self.rebuild_blocks()
            self.changed.emit()
        self._check()

    def _check(self):
        problems = []
        t = TypeChecker({v["id"]: v["type"] for v in variables(self.doc)}, {n["id"] for n in self.doc.nodes()},
                        lambda code, path, msg: problems.append(msg)).infer(self._value, "")
        if not problems and not fits("bool", t):
            problems.append(f"условие должно давать да/нет, а даёт {TYPE_TITLES.get(t, t)}")
        self._error = "; ".join(problems)
        if problems:
            self.status.setText("<span style='color:#c62828'>✖ " + "<br>✖ ".join(problems) + "</span>")
        else:
            self.status.setText("<span style='color:#2e7d32'>✔ условие в порядке</span>"
                                if self._value is not True else "<span style='color:#666'>всегда</span>")


# ---------------------------------------------------------------- эффекты

class EffectsEditor(QWidget):
    """Список эффектов: «переменная · действие · значение». value() — список эффектов формата."""
    changed = Signal()

    def __init__(self, doc: ProjectDocument, effects: list | None = None, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.effects = copy.deepcopy(effects or [])
        self._parse_errors: dict[int, str] = {}
        self._type_errors: list[str] = []
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.rows = QVBoxLayout()
        self.lay.addLayout(self.rows)
        add = QPushButton("+ изменить переменную")
        add.clicked.connect(self._add)
        self.lay.addWidget(add, 0, Qt.AlignLeft)
        self.status = QLabel()
        self.lay.addWidget(self.status)
        self._build()

    def value(self) -> list:
        return copy.deepcopy(self.effects)

    def ok(self) -> bool:
        return not self._parse_errors and not self._type_errors

    def problems(self) -> list[str]:
        return list(self._parse_errors.values()) + self._type_errors

    def _build(self):
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not self.effects:
            empty = QLabel("ничего не меняется")
            empty.setStyleSheet("color:#888")
            self.rows.addWidget(empty)
        for i, ef in enumerate(self.effects):
            self.rows.addWidget(self._row(i, ef))
        self._check()

    def _row(self, i, ef):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 2, 0, 2)
        if ef.get("op") == "call":
            lay.addWidget(QLabel(f"{ef.get('fn')}() — функция плагина"))
        else:
            var = var_combo(self.doc, ef.get("var"))
            op = QComboBox()
            for k, t in EFFECT_OPS:
                op.addItem(t, k)
            op.setCurrentIndex(max(0, op.findData(ef.get("op"))))
            value = QLineEdit(to_text(ef.get("value"), {v["id"]: v["name"] for v in variables(self.doc)})
                              if "value" in ef else "")
            value.setPlaceholderText("значение или формула")
            value.setEnabled(ef.get("op") != "toggle")

            def var_changed(_i, combo=var, i=i):
                vid = combo.currentData()
                if vid == NEW_VAR:
                    vid = ask_new_variable(self.doc, combo, self.effects[i].get("var"), self)
                    if vid is None:
                        return
                self.effects[i]["var"] = vid
                self._emit()

            def op_changed(_i, i=i, combo=op, value=value):
                self.effects[i]["op"] = combo.currentData()
                if combo.currentData() == "toggle":
                    self.effects[i].pop("value", None)
                else:
                    self.effects[i].setdefault("value", 1 if combo.currentData() in ("add", "sub", "mul") else 0)
                    value.setText(to_text(self.effects[i]["value"]))
                value.setEnabled(combo.currentData() != "toggle")
                self._emit()

            def value_done(i=i, edit=value):
                try:
                    self.effects[i]["value"] = parse(edit.text() or "0", variables(self.doc))
                    edit.setStyleSheet("")
                    self._parse_errors.pop(i, None)
                except ParseError as exc:
                    edit.setStyleSheet("background:#fdecea")
                    self._parse_errors[i] = str(exc)
                    self._check()
                    return
                self._emit()

            var.currentIndexChanged.connect(var_changed)
            op.currentIndexChanged.connect(op_changed)
            value.editingFinished.connect(value_done)
            lay.addWidget(var, 3)
            lay.addWidget(op)
            lay.addWidget(value, 2)
        rm = QPushButton("✕")
        rm.setFixedWidth(26)
        rm.clicked.connect(lambda _=False, i=i: (self.effects.pop(i), self._parse_errors.clear(), self._build(),
                                                 self.changed.emit()))
        lay.addWidget(rm)
        return w

    def _add(self):
        vs = variables(self.doc)
        if not vs:
            dummy = QComboBox()
            dummy.addItem("", NEW_VAR)
            if ask_new_variable(self.doc, dummy, None, self) is None:
                return
            vs = variables(self.doc)
        v = vs[0]
        self.effects.append({"op": "toggle", "var": v["id"]} if v["type"] == "bool" else
                            {"op": "add", "var": v["id"], "value": 1} if v["type"] in ("int", "float") else
                            {"op": "set", "var": v["id"], "value": ""})
        self._build()
        self.changed.emit()

    def _emit(self):
        self._check()
        self.changed.emit()

    def _check(self):
        from vnformat.validate import Validator
        v = Validator(self.doc.raw())
        v.var_types = {x["id"]: x["type"] for x in variables(self.doc)}
        v.var_names = {x["id"]: x["name"] for x in variables(self.doc)}
        v.effects(self.effects, "", "", "")
        self._type_errors = [i.message for i in v.issues]
        problems = self.problems()
        self.status.setText("<span style='color:#c62828'>✖ " + "<br>✖ ".join(problems) + "</span>" if problems else "")


# ---------------------------------------------------------------- диалоги

class ExprDialog(QDialog):
    """Диалог «Условие» или «Эффекты»; result() → новое значение (None — отмена)."""

    def __init__(self, doc: ProjectDocument, title: str, condition: Any = None, effects: list | None = None,
                 show_condition=True, show_effects=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 560 if show_condition else 320)
        lay = QVBoxLayout(self)
        self.cond = ConditionEditor(doc, True if condition is None else condition) if show_condition else None
        self.eff = EffectsEditor(doc, effects) if show_effects else None
        if self.cond:
            lay.addWidget(self.cond, 1)
        if self.eff:
            if self.cond:
                lay.addWidget(QLabel("<b>Что меняется при выборе</b>"))
            lay.addWidget(self.eff)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Готово")
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        if self.cond:
            self.cond._formula_done()
        problems = []
        if self.cond and not self.cond.ok():
            problems.append(self.cond._error)
        if self.eff and not self.eff.ok():
            problems += self.eff.problems()
        if problems:
            r = QMessageBox.question(self, "Есть ошибки", "Сохранить всё равно?\n\n" + "\n".join(problems))
            if r != QMessageBox.Yes:
                return
        self.accept()

    def condition(self) -> Any:
        return self.cond.value() if self.cond else None

    def effects(self) -> list:
        return self.eff.value() if self.eff else []


def describe_effects(effects: list, names: dict[str, str]) -> str:
    out = []
    for e in effects:
        n = names.get(e.get("var"), e.get("var", ""))
        op = e.get("op")
        if op == "toggle":
            out.append(f"переключить {n}")
        elif op == "call":
            out.append(f"{e.get('fn')}()")
        else:
            sym = {"set": "=", "add": "+", "sub": "−", "mul": "×"}[op]
            out.append(f"{n} {sym} {to_text(e.get('value'), names)}")
    return "; ".join(out)
