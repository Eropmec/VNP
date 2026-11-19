"""Панель проблем: результаты проверки проекта, обновляются на лету."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .document import ProjectDocument
from .graph_view import issue_nodes

COLORS = {"error": "#c62828", "warning": "#b26a00", "info": "#607d8b"}
TITLES = {"error": "Ошибка", "warning": "Внимание", "info": "Подсказка"}


class ProblemsPanel(QWidget):
    goto_node = Signal(str)
    counts_changed = Signal(int, int)

    def __init__(self, doc: ProjectDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        self.summary = QLabel()
        self.show_info = QCheckBox("подсказки")
        self.show_info.toggled.connect(lambda _on: self.fill(self.doc.issues))
        top.addWidget(self.summary, 1)
        top.addWidget(self.show_info)
        lay.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Где", "Что не так"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 90)
        self.tree.setColumnWidth(1, 330)
        self.tree.itemActivated.connect(self._activate)
        lay.addWidget(self.tree)
        doc.issues_changed.connect(self.fill)

    def fill(self, issues):
        self.tree.clear()
        errors = sum(i.severity == "error" for i in issues)
        warnings = sum(i.severity == "warning" for i in issues)
        for i in issues:
            if i.severity == "info" and not self.show_info.isChecked():
                continue
            where = f"{i.file} · {i.where}" if i.where else i.file
            it = QTreeWidgetItem(["● " + TITLES[i.severity], where, i.message])
            it.setForeground(0, QBrush(QColor(COLORS[i.severity])))
            it.setToolTip(2, i.message)
            nodes = issue_nodes(self.doc, i)
            it.setData(0, Qt.UserRole, nodes[0] if nodes else None)
            self.tree.addTopLevelItem(it)
        if errors or warnings:
            self.summary.setText(f"<b style='color:{COLORS['error']}'>Ошибок: {errors}</b> · "
                                 f"<span style='color:{COLORS['warning']}'>предупреждений: {warnings}</span>")
        else:
            self.summary.setText("<span style='color:#2e7d32'>✔ Проблем нет</span>")
        self.counts_changed.emit(errors, warnings)

    def _activate(self, item, _col):
        nid = item.data(0, Qt.UserRole)
        if nid:
            self.goto_node.emit(nid)
