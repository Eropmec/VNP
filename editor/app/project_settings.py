"""Диалог «Проект → Настройки игры»: название, версия, разрешение, главное меню."""
from __future__ import annotations

import re

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
)

from . import db_ops as D
from .document import ProjectDocument


class ProjectSettingsDialog(QDialog):
    def __init__(self, doc: ProjectDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        p = doc.get("project") or {}
        self.setWindowTitle("Настройки игры")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)
        self.title = QLineEdit(p.get("title", ""))
        self.version = QLineEdit(p.get("version", "0.1.0"))
        self.version.setPlaceholderText("1.0.0")
        res = p.get("resolution", {"width": 1280, "height": 720})
        self.w, self.h = QSpinBox(), QSpinBox()
        for sb, v in ((self.w, res.get("width", 1280)), (self.h, res.get("height", 720))):
            sb.setRange(320, 7680)
            sb.setValue(int(v))
        row = QHBoxLayout()
        row.addWidget(self.w)
        row.addWidget(QLabel("×"))
        row.addWidget(self.h)
        menu = p.get("menu", {})
        self.bg = self._assets("image", menu.get("background"), "авто — первый фон проекта")
        self.music = self._assets("audio", menu.get("music"), "без музыки")
        form.addRow("Название", self.title)
        form.addRow("Версия", self.version)
        form.addRow("Разрешение", row)
        form.addRow(QLabel("<b>Главное меню</b>"))
        form.addRow("Фон", self.bg)
        form.addRow("Музыка", self.music)
        form.addRow("Языки", QLabel(", ".join(p.get("languages", []))))
        self.err = QLabel()
        self.err.setStyleSheet("color:#c62828")
        lay.addWidget(self.err)
        note = QLabel("Меню видит игрок; при запуске из редактора (F5/F6) игра начинается сразу. "
                      "Посмотреть меню — «Игра → Запустить как игрок».")
        note.setWordWrap(True)
        note.setStyleSheet("color:#777")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _assets(self, kind: str, current, none_label: str) -> QComboBox:
        combo = QComboBox()
        combo.setIconSize(QSize(64, 36))
        combo.addItem(none_label, None)
        for a in D.asset_list(self.doc):
            if a.get("kind") == kind:
                f = D.asset_file(self.doc, a["id"])
                icon = QIcon(str(f)) if kind == "image" and f and f.is_file() else QIcon()
                combo.addItem(icon, a["path"], a["id"])
        combo.setCurrentIndex(max(0, combo.findData(current)))
        return combo

    def _ok(self):
        if not self.title.text().strip():
            self.err.setText("Название не может быть пустым")
            return
        if not re.fullmatch(r"\d+\.\d+\.\d+", self.version.text().strip()):
            self.err.setText("Версия — три числа через точку: 1.0.0")
            return
        menu = {k: v for k, v in (("background", self.bg.currentData()), ("music", self.music.currentData())) if v}

        def fn(p):
            p["title"] = self.title.text().strip()
            p["version"] = self.version.text().strip()
            p["resolution"] = {"width": self.w.value(), "height": self.h.value()}
            if menu:
                p["menu"] = menu
            else:
                p.pop("menu", None)
        self.doc.edit("Настройки игры", {"project": fn})
        self.accept()
