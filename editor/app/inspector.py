"""Инспектор: свойства выбранного узла графа."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from vnformat.expr import to_text

from . import graph_ops
from .document import ProjectDocument
from .graph_view import ENDING_KIND, TYPE_STYLE, issue_nodes


class Inspector(QScrollArea):
    open_chapter = Signal(str)
    open_scene = Signal(str)

    def __init__(self, doc: ProjectDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.nid: str | None = None
        self.setWidgetResizable(True)
        self.setMinimumWidth(300)
        # перестраиваем форму отложенно: правка часто приходит из сигнала виджета этой же формы,
        # и удалить его прямо в обработчике — значит уронить программу
        self._later = QTimer(self, singleShot=True, interval=0)
        self._later.timeout.connect(self.refresh)
        doc.changed.connect(lambda _k: self._later.start())
        doc.reloaded.connect(lambda: self.show_node(None))
        doc.issues_changed.connect(lambda _i: self._later.start())
        self.show_node(None)

    def show_node(self, nid: str | None):
        self.nid = nid
        self.refresh(force=True)

    def refresh(self, force: bool = False):
        # не перестраивать форму, пока пользователь в ней печатает
        focus = QApplication.focusWidget()
        if not force and focus is not None and self.isAncestorOf(focus) and isinstance(focus, (QLineEdit, QPlainTextEdit)):
            return
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignTop)
        node = self.doc.node(self.nid) if self.nid else None
        if node is None:
            hint = QLabel("Выбери узел на графе.\n\nПравый клик по пустому месту — создать узел.\n"
                          "Потяни от кружка-выхода к другому узлу — связать.\n"
                          "Двойной клик по главе — войти внутрь.\nКолесо — масштаб, средняя кнопка — сдвиг, F — вписать.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #666;")
            lay.addWidget(hint)
            self._swap(w)
            return
        nid, kind = node["id"], node.get("type")
        color, title = TYPE_STYLE.get(kind, (None, kind))
        head = QLabel(f"<b style='color:{color.name() if color else '#333'}'>{title}</b> "
                      f"<span style='color:#888'>{nid}</span>")
        head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(head)
        form = QFormLayout()
        lay.addLayout(form)

        name = QLineEdit(node.get("name", ""))
        name.editingFinished.connect(lambda: name.text().strip() and name.text() != node.get("name") and
                                     graph_ops.update_node(self.doc, nid, "Переименовать узел", name=name.text().strip()))
        form.addRow("Название", name)
        key = QCheckBox("ключевая точка сюжета")
        key.setChecked(node.get("importance") == "key")
        key.toggled.connect(lambda on: graph_ops.update_node(self.doc, nid, "Ключевая точка", importance="key" if on else None))
        form.addRow("", key)

        if kind == "scene":
            scene = self.doc.scenes().get(node.get("scene"), {})
            lines = []
            chars = {k[1]: v for k, v in self.doc.files.items() if isinstance(k, tuple) and k[0] == "character"}
            for c in scene.get("commands", []):
                if c.get("cmd") == "say":
                    who = self.doc.text(chars.get(c.get("char"), {}).get("name")) or c.get("char")
                    lines.append(f"{who}: {self.doc.text(c.get('text'))}")
                elif c.get("cmd") == "narrate":
                    lines.append(self.doc.text(c.get("text")))
                elif c.get("cmd") == "choice":
                    for o in c.get("options", []):
                        lines.append(f"  ▸ {self.doc.text(o.get('text'))}")
            preview = QPlainTextEdit("\n".join(lines) or "(пусто)")
            preview.setReadOnly(True)
            preview.setMinimumHeight(160)
            go = QPushButton("✎ Открыть сцену (двойной клик по узлу)")
            go.clicked.connect(lambda: self.open_scene.emit(node.get("scene", "")))
            lay.addWidget(go)
            lay.addWidget(preview)
        elif kind == "branch":
            vars_ = {v["id"]: v["name"] for v in (self.doc.get("variables") or {}).get("variables", [])}
            lay.addWidget(QLabel("Условия проверяются по порядку, первое истинное выбирает выход:"))
            for i, case in enumerate(node.get("cases", [])):
                row = QHBoxLayout()
                label = QLineEdit(case.get("label", ""))
                label.setPlaceholderText("подпись выхода")
                label.editingFinished.connect(lambda i=i, le=label: self._case_label(nid, i, le.text()))
                row.addWidget(label, 1)
                rm = QPushButton("✕")
                rm.setFixedWidth(28)
                rm.setToolTip("Удалить условие")
                rm.setEnabled(len(node.get("cases", [])) > 1)
                rm.clicked.connect(lambda _=False, i=i: self._case_remove(nid, i))
                row.addWidget(rm)
                lay.addLayout(row)
                f = QPushButton("✎  если " + to_text(case.get("condition"), vars_))
                f.setStyleSheet("text-align:left; padding:4px 8px;")
                f.setToolTip("Изменить условие")
                f.clicked.connect(lambda _=False, i=i: self._case_condition(nid, i))
                lay.addWidget(f)
            add = QPushButton("+ условие")
            add.clicked.connect(lambda: self._case_add(nid))
            lay.addWidget(add)
            note = QLabel("Если ни одно условие не выполнено — выход «иначе».")
            note.setStyleSheet("color:#888;")
            lay.addWidget(note)
        elif kind == "ending":
            e = node.get("ending", {})
            title = QLineEdit(self.doc.text(e.get("title")))
            title.editingFinished.connect(lambda: title.text() != self.doc.text(e.get("title")) and
                                          graph_ops.set_text(self.doc, e["title"], title.text(), "Название концовки"))
            form.addRow("Заголовок", title)
            kinds = QComboBox()
            for k, label in ENDING_KIND.items():
                kinds.addItem(label, k)
            kinds.setCurrentIndex(max(0, kinds.findData(e.get("kind"))))
            kinds.currentIndexChanged.connect(lambda _i: graph_ops.update_node(
                self.doc, nid, "Тип концовки", ending={**e, "kind": kinds.currentData()}))
            form.addRow("Тип", kinds)
        elif kind == "chapter":
            children = [n for n in self.doc.nodes() if n.get("parent") == nid]
            entry = QComboBox()
            for c in children:
                entry.addItem(c.get("name", c["id"]), c["id"])
            entry.setCurrentIndex(max(0, entry.findData(node.get("entry"))))
            entry.currentIndexChanged.connect(lambda _i: graph_ops.update_node(
                self.doc, nid, "Первый узел главы", entry=entry.currentData()))
            form.addRow("Первый узел", entry)
            go = QPushButton("Открыть главу")
            go.clicked.connect(lambda: self.open_chapter.emit(nid))
            lay.addWidget(go)

        start = (self.doc.get("project") or {}).get("start")
        if start != nid:
            b = QPushButton("Начинать игру с этого узла")
            b.clicked.connect(lambda: graph_ops.set_start(self.doc, nid))
            lay.addWidget(b)
        else:
            lay.addWidget(QLabel("<span style='color:#2e7d32'>● Игра начинается здесь</span>"))

        problems = [i for i in self.doc.issues if i.severity != "info" and nid in issue_nodes(self.doc, i)]
        if problems:
            box = QLabel("<br>".join(f"<span style='color:{'#c62828' if i.severity == 'error' else '#b26a00'}'>"
                                     f"● {i.message}</span>" for i in problems))
            box.setWordWrap(True)
            box.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(QLabel("<b>Проблемы</b>"))
            lay.addWidget(box)
        self._swap(w)

    def _swap(self, w: QWidget):
        old = self.takeWidget()
        self.setWidget(w)
        if old is not None:
            old.deleteLater()

    # ----------------------------------------------------------- ветвления
    def _cases(self, nid: str) -> list:
        return [dict(c) for c in (self.doc.node(nid) or {}).get("cases", [])]

    def _case_label(self, nid: str, i: int, text: str):
        cases = self._cases(nid)
        if i < len(cases) and cases[i].get("label", "") != text:
            cases[i]["label"] = text
            graph_ops.update_node(self.doc, nid, "Подпись условия", cases=cases)

    def _case_condition(self, nid: str, i: int):
        from .condition_editor import ExprDialog
        cases = self._cases(nid)
        dlg = ExprDialog(self.doc, f"Условие: {cases[i].get('label') or 'случай ' + str(i + 1)}",
                         condition=cases[i].get("condition"), parent=self)
        if dlg.exec():
            cases = self._cases(nid)
            cases[i]["condition"] = dlg.condition()
            graph_ops.update_node(self.doc, nid, "Изменить условие", cases=cases)

    def _case_add(self, nid: str):
        cases = self._cases(nid)
        taken = {c["port"] for c in cases}
        n = 1
        while f"p_case{n}" in taken:
            n += 1
        cases.append({"port": f"p_case{n}", "label": f"условие {n}", "condition": True})
        graph_ops.update_node(self.doc, nid, "Добавить условие", cases=cases)

    def _case_remove(self, nid: str, i: int):
        cases = self._cases(nid)
        if len(cases) <= 1:
            return
        port = cases.pop(i)["port"]
        self.doc.edit("Удалить условие", {"graph": lambda g: self._drop_case(g, nid, cases, port)})

    @staticmethod
    def _drop_case(graph, nid, cases, port):
        for n in graph["nodes"]:
            if n.get("id") == nid:
                n["cases"] = cases
        graph["edges"] = [e for e in graph["edges"] if not (e["from"]["node"] == nid and e["from"]["port"] == port)]
