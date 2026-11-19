"""Плейтест: рантайм Godot внутри редактора. Сохранение проекта → игра перезагружается на той же реплике."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from .document import ProjectDocument
from .runtime_link import RuntimeLink

RUNTIME = Path(__file__).resolve().parents[2] / "runtime"


class PlaytestPanel(QWidget):
    position = Signal(str, str)        # узел, команда — где сейчас игра

    def __init__(self, doc: ProjectDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.settings = QSettings("vn-constructor", "editor")
        self.link = RuntimeLink(self)
        self.proc: QProcess | None = None
        self.container = None
        self._t0 = 0.0
        self._pending_start: str | None = None
        self._last_node = ""
        self._embedded_run = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.run_btn = QPushButton("▶ С начала")
        self.run_btn.setToolTip("F5")
        self.run_btn.clicked.connect(lambda: self.run(None))
        self.big_btn = QPushButton("⛶ Отдельное окно")
        self.big_btn.setToolTip("Играть в отдельном большом окне с текущего места (F7). В игре F11 — во весь экран")
        self.big_btn.clicked.connect(self.detach)
        self.stop_btn = QPushButton("■")
        self.stop_btn.setToolTip("Остановить (Shift+F5)")
        self.stop_btn.setFixedWidth(32)
        self.stop_btn.clicked.connect(self.stop)
        self.embed_box = QCheckBox("в окне редактора")
        self.embed_box.setChecked(self.settings.value("embed", sys.platform == "win32", type=bool))
        self.embed_box.toggled.connect(lambda on: self.settings.setValue("embed", on))
        self.follow = QCheckBox("следить")
        self.follow.setToolTip("Выделять на графе узел, который сейчас играется")
        self.follow.setChecked(True)
        bar.addWidget(self.run_btn)
        bar.addWidget(self.stop_btn)
        bar.addWidget(self.big_btn)
        bar.addStretch(1)
        bar.addWidget(self.follow)
        bar.addWidget(self.embed_box)
        lay.addLayout(bar)

        self.host = QWidget()
        self.host.setMinimumHeight(240)
        self.host_lay = QVBoxLayout(self.host)
        self.host_lay.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QLabel("F5 — играть с начала\nF6 — с выбранного узла\n\nСохранение (Ctrl+S) перезагружает игру")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("color:#777; background:#1c1c22; color:#aaa;")
        self.host_lay.addWidget(self.placeholder)
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(500)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.host)
        split.addWidget(self.log)
        split.setSizes([360, 90])
        lay.addWidget(split, 1)

        self.link.connected.connect(lambda: self.say("игра подключилась"))
        self.link.disconnected.connect(self._unembed)
        self.link.notification.connect(self._note)
        self.link.response.connect(self._response)
        self.link.failed.connect(lambda m, e: self.say(f"ошибка {m}: {e}"))

    def say(self, text: str):
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    @property
    def running(self) -> bool:
        return self.proc is not None

    def godot_path(self) -> str | None:
        path = self.settings.value("godot", "")
        if path and os.path.isfile(path):
            return path
        return self.choose_godot()

    def choose_godot(self) -> str | None:
        path, _ = QFileDialog.getOpenFileName(self, "Где лежит Godot 4.4+ (…_win64.exe)?")
        if path:
            self.settings.setValue("godot", path)
            return path
        return None

    # ----------------------------------------------------------- запуск
    def detach(self):
        """Перезапустить игру в отдельном большом окне с того узла, где она сейчас."""
        start = self._last_node or None
        if self.running:
            if not self._embedded_run:
                return
            proc = self.proc
            self.proc = None
            self._unembed()
            self.link.call("app.quit")
            QTimer.singleShot(1500, lambda: proc.state() != QProcess.NotRunning and proc.kill())
            QTimer.singleShot(400, lambda: self.run(start, embed=False))
        else:
            self.run(start, embed=False)

    def run_as_player(self):
        """Как увидит игрок: главное меню, сохранения, настройки. Всегда в отдельном окне."""
        if self.running:
            self.stop()
            QTimer.singleShot(1300, lambda: self.run(None, embed=False, extra=["--menu"]))
        else:
            self.run(None, embed=False, extra=["--menu"])

    def run(self, start_node: str | None, embed: bool | None = None, command: str | None = None,
            extra: list[str] | None = None):
        if self.doc.root is None:
            return
        if self.doc.dirty:
            self.doc.save()
        if self.running:                          # уже играет — просто перейти
            if start_node:
                self.link.call("play.goto", node=start_node, command=command or "", keep_vars=False)
            else:
                self.link.call("play.restart")
            return
        exe = self.godot_path()
        if not exe:
            self.say("не указан путь к Godot")
            return
        args = ["--path", str(RUNTIME), "--", f"--project={self.doc.root.as_posix()}",
                f"--editor-port={self.link.port}"]
        if start_node:
            args.append(f"--start={start_node}")
            if command:
                args.append(f"--command={command}")
        args += extra or []
        self._embedded_run = self.embed_box.isChecked() if embed is None else embed
        if self._embedded_run:
            args.append("--embed")
        if os.environ.get("VN_GODOT_HEADLESS"):
            args.insert(0, "--headless")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._output)
        self.proc.finished.connect(self._finished)
        self._t0 = time.perf_counter()
        self.proc.start(exe, args)
        self.say("запуск игры…")

    def stop(self):
        if not self.running:
            return
        proc = self.proc
        self.link.call("app.quit")
        QTimer.singleShot(1500, lambda: proc.state() != QProcess.NotRunning and proc.kill())

    def reload(self):
        if self.running:
            self.link.call("project.reload")

    def _output(self):
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            if line.strip() and not line.startswith(("Godot Engine", "ALSA", "OpenGL API")):
                self.say("godot> " + line)

    def _finished(self, code, _status):
        if self.sender() is not self.proc:
            return
        self.proc = None
        self._unembed()
        self.say(f"игра закрыта (код {code})")

    # ----------------------------------------------------------- встраивание
    def _embed(self, hwnd):
        try:
            win = QWindow.fromWinId(int(hwnd))
            self.container = QWidget.createWindowContainer(win, self.host)
            self.container.setFocusPolicy(Qt.StrongFocus)
            self.placeholder.hide()
            self.host_lay.addWidget(self.container)
        except Exception as exc:  # noqa: BLE001
            self.say(f"встроить окно не удалось: {exc}")

    def _unembed(self):
        if self.container is not None:
            self.container.setParent(None)
            self.container.deleteLater()
            self.container = None
        self.placeholder.show()

    # ----------------------------------------------------------- протокол
    def _note(self, method, params):
        if method == "hello":
            self.say(f"Godot {params.get('godot')}, старт {(time.perf_counter() - self._t0) * 1000:.0f} мс")
            if self._embedded_run and params.get("hwnd"):
                self._embed(params["hwnd"])
        elif method == "play.position":
            self._last_node = params.get("node", "")
            if self.follow.isChecked():
                self.position.emit(params.get("node", ""), params.get("command", ""))
        elif method == "play.ended":
            self.say(f"концовка: {(self.doc.node(params.get('node')) or {}).get('name', params.get('node'))}")
        elif method == "runtime.error":
            self.say("ОШИБКА В ИГРЕ: " + params.get("message", ""))

    def _response(self, method, ms, result):
        if method == "project.reload":
            self.say(f"перезагружено за {ms:.0f} мс")
