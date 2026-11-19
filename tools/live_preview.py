"""
Живое превью проекта: Godot-рантайм внутри окна PySide6 + перезагрузка при сохранении файлов.

    python tools/live_preview.py
    python tools/live_preview.py --project samples/demo --godot "C:/Godot/Godot_v4.7.2-stable_win64.exe"

Правишь JSON/CSV проекта в любом редакторе → сохраняешь → игра перезагружается
на той же реплике. Двойной клик по узлу или команде слева — перейти туда.
Значения переменных можно менять прямо в таблице. Это прообраз панели плейтеста редактора.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QProcess, QSettings, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QWindow
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
sys.path.insert(0, str(ROOT / "editor"))

from vnformat import load_raw, validate_raw  # noqa: E402
from app.runtime_link import RuntimeLink  # noqa: E402

NODE_ROLE = Qt.UserRole
CMD_ROLE = Qt.UserRole + 1


class Window(QMainWindow):
    def __init__(self, project: Path | None, godot: str | None):
        super().__init__()
        self.setWindowTitle("Живое превью")
        self.resize(1600, 900)
        self.settings = QSettings("vn-constructor", "live-preview")
        self.link = RuntimeLink(self)
        self.proc = None
        self.container = None
        self.raw = None
        self.var_ids = []
        self._filling_vars = False
        self.t_start = 0.0

        # --- верх
        self.godot = QLineEdit(godot or self.settings.value("godot", ""))
        self.godot.setPlaceholderText("Godot 4.4+ (…_win64.exe)")
        self.project = QLineEdit(str(project or self.settings.value("project", ROOT / "samples" / "demo")))
        self.embed_box = QCheckBox("Встроить окно")
        self.embed_box.setChecked(sys.platform == "win32")
        self.run_btn = QPushButton("Запустить")
        self.run_btn.clicked.connect(self.toggle_run)
        restart = QPushButton("Сначала")
        restart.clicked.connect(lambda: self.link.call("play.restart"))
        top = QHBoxLayout()
        top.addWidget(QLabel("Godot:"))
        top.addWidget(self.godot, 2)
        top.addWidget(self._browse(self.godot, file=True))
        top.addWidget(QLabel("Проект:"))
        top.addWidget(self.project, 2)
        top.addWidget(self._browse(self.project, file=False))
        top.addWidget(self.embed_box)
        top.addWidget(self.run_btn)
        top.addWidget(restart)

        # --- слева: сюжет и переменные
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Сюжет", "ID"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.itemDoubleClicked.connect(self.goto_item)
        self.vars = QTableWidget(0, 2)
        self.vars.setHorizontalHeaderLabels(["Переменная", "Значение"])
        self.vars.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.vars.verticalHeader().setVisible(False)
        self.vars.itemChanged.connect(self.var_edited)
        left = QSplitter(Qt.Vertical)
        left.addWidget(self.tree)
        left.addWidget(self.vars)
        left.setSizes([560, 240])

        # --- справа: игра и журнал
        self.game_host = QWidget()
        self.game_layout = QVBoxLayout(self.game_host)
        self.game_layout.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QLabel("Нажми «Запустить»")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.game_layout.addWidget(self.placeholder)
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setMaximumBlockCount(1000)
        right = QSplitter(Qt.Vertical)
        right.addWidget(self.game_host)
        right.addWidget(self.log)
        right.setSizes([680, 180])

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([420, 1180])
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        self.setCentralWidget(central)

        # --- слежение за файлами
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self.on_fs_change)
        self.watcher.directoryChanged.connect(self.on_fs_change)
        self.debounce = QTimer(self, singleShot=True, interval=200)
        self.debounce.timeout.connect(self.project_changed)

        self.link.connected.connect(lambda: self.say("рантайм подключился"))
        self.link.disconnected.connect(self.on_disconnected)
        self.link.notification.connect(self.on_note)
        self.link.response.connect(self.on_response)
        self.link.failed.connect(lambda m, e: self.say(f"ошибка {m}: {e}"))
        self.project.editingFinished.connect(self.load_project)
        self.load_project()

    def _browse(self, field, file):
        b = QPushButton("…")
        def pick():
            path = (QFileDialog.getOpenFileName(self, "Godot")[0] if file
                    else QFileDialog.getExistingDirectory(self, "Папка проекта", field.text()))
            if path:
                field.setText(path)
                if not file:
                    self.load_project()
        b.clicked.connect(pick)
        return b

    def say(self, text):
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    # ----------------------------------------------------------- проект
    def project_dir(self) -> Path:
        return Path(self.project.text().strip()).resolve()

    def load_project(self):
        root = self.project_dir()
        if not (root / "project.json").is_file():
            self.say(f"в {root} нет project.json")
            return
        self.settings.setValue("project", str(root))
        self.raw = load_raw(root)
        self.report(validate_raw(self.raw))
        self.fill_tree()
        self.rewatch()

    def report(self, issues):
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        for i in errors + warnings:
            self.say(str(i))
        self.statusBar().showMessage(f"Проверка: ошибок {len(errors)}, предупреждений {len(warnings)}")

    def rewatch(self):
        old = self.watcher.files() + self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        root = self.project_dir()
        paths = [str(root)]
        for p in root.rglob("*"):
            if p.name.startswith(".") or p.suffix == ".import":
                continue
            paths.append(str(p))
        self.watcher.addPaths(paths)

    def on_fs_change(self, _path):
        self.debounce.start()

    def project_changed(self):
        self.load_project()
        if self.link.sock is not None:
            self.link.call("project.reload")

    def fill_tree(self):
        self.tree.clear()
        self.items = {}
        g = self.raw.graph or {}
        ru = self.raw.locales.get((self.raw.project or {}).get("default_language", ""), {})
        scenes = {d["id"]: d for d in self.raw.scenes.values() if isinstance(d, dict) and "id" in d}
        nodes = {n["id"]: n for n in g.get("nodes", []) if isinstance(n, dict) and "id" in n}
        icons = {"chapter": "▣", "scene": "▶", "branch": "◆", "ending": "■"}

        def make(n, parent):
            it = QTreeWidgetItem(parent, [f"{icons.get(n.get('type'), '?')}  {n.get('name', n['id'])}", n["id"]])
            it.setData(0, NODE_ROLE, n["id"])
            if n.get("importance") == "key":
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            self.items[(n["id"], "")] = it
            if n.get("type") == "scene":
                for c in self._flat(scenes.get(n.get("scene"), {}).get("commands", [])):
                    text = ru.get(c.get("text", ""), "")
                    label = f"{c['cmd']}  {text[:48]}" if text else f"{c['cmd']}  {c.get('asset') or c.get('char') or ''}"
                    ci = QTreeWidgetItem(it, [label, c.get("id", "")])
                    ci.setData(0, NODE_ROLE, n["id"])
                    ci.setData(0, CMD_ROLE, c.get("id", ""))
                    ci.setForeground(0, QBrush(QColor("#888")) if c["cmd"] not in ("say", "narrate", "choice") else QBrush())
                    self.items[(n["id"], c.get("id", ""))] = ci
            return it

        children = {}
        for n in nodes.values():
            children.setdefault(n.get("parent"), []).append(n)

        def build(parent_id, parent_item):
            for n in children.get(parent_id, []):
                it = make(n, parent_item)
                build(n["id"], it)
        build(None, self.tree)
        self.tree.expandToDepth(0)

    @staticmethod
    def _flat(cmds):
        for c in cmds:
            if isinstance(c, dict):
                yield c
                if c.get("cmd") == "if":
                    yield from Window._flat(c.get("then", []))
                    yield from Window._flat(c.get("else", []))

    def goto_item(self, item, _col):
        node, cmd = item.data(0, NODE_ROLE), item.data(0, CMD_ROLE) or ""
        if node:
            self.link.call("play.goto", node=node, command=cmd)

    # ----------------------------------------------------------- переменные
    def fill_vars(self, values: dict):
        defs = {v["id"]: v for v in (self.raw.variables or {}).get("variables", [])} if self.raw else {}
        self._filling_vars = True
        self.var_ids = list(values)
        self.vars.setRowCount(len(values))
        for row, vid in enumerate(values):
            name = QTableWidgetItem(defs.get(vid, {}).get("title") or defs.get(vid, {}).get("name") or vid)
            name.setFlags(name.flags() & ~Qt.ItemIsEditable)
            name.setToolTip(vid)
            val = values[vid]
            self.vars.setItem(row, 0, name)
            self.vars.setItem(row, 1, QTableWidgetItem(json.dumps(val, ensure_ascii=False)))
        self._filling_vars = False

    def var_edited(self, item):
        if self._filling_vars or item.column() != 1:
            return
        text = item.text().strip().lower()
        text = {"да": "true", "нет": "false"}.get(text, text)
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = item.text()
        self.link.call("state.set", var=self.var_ids[item.row()], value=value)

    # ----------------------------------------------------------- процесс
    def toggle_run(self):
        if self.proc is not None:
            proc = self.proc
            self.link.call("app.quit")
            QTimer.singleShot(1500, lambda: proc.state() != QProcess.NotRunning and proc.kill())
            return
        exe = self.godot.text().strip()
        if not os.path.isfile(exe):
            self.say("укажи путь к Godot 4.4+")
            return
        self.settings.setValue("godot", exe)
        args = ["--path", str(RUNTIME), "--", f"--project={self.project_dir().as_posix()}",
                f"--editor-port={self.link.port}"]
        if self.embed_box.isChecked():
            args.append("--embed")
        if os.environ.get("VN_GODOT_HEADLESS"):
            args.insert(0, "--headless")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._godot_output)
        self.proc.finished.connect(self.on_finished)
        self.t_start = time.perf_counter()
        self.proc.start(exe, args)
        self.run_btn.setText("Остановить")

    def _godot_output(self):
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            if line.strip() and not line.startswith(("Godot Engine", "ALSA")):
                self.say("godot> " + line)

    def on_finished(self, code, _status):
        if self.sender() is not self.proc:
            return
        self.say(f"Godot завершился, код {code}")
        self.proc = None
        self.run_btn.setText("Запустить")
        self.unembed()

    def on_disconnected(self):
        self.say("рантайм отключился")
        self.unembed()

    def embed(self, hwnd):
        try:
            win = QWindow.fromWinId(int(hwnd))
            self.container = QWidget.createWindowContainer(win, self.game_host)
            self.container.setFocusPolicy(Qt.StrongFocus)
            self.placeholder.hide()
            self.game_layout.addWidget(self.container)
        except Exception as exc:  # noqa: BLE001
            self.say(f"встроить окно не удалось: {exc}")

    def unembed(self):
        if self.container is not None:
            self.container.setParent(None)
            self.container.deleteLater()
            self.container = None
        self.placeholder.show()

    # ----------------------------------------------------------- протокол
    def on_note(self, method, params):
        if method == "hello":
            self.say(f"Godot {params.get('godot')} на {params.get('platform')}, старт "
                     f"{(time.perf_counter() - self.t_start) * 1000:.0f} мс")
            if self.embed_box.isChecked() and params.get("hwnd"):
                self.embed(params["hwnd"])
        elif method == "play.position":
            it = self.items.get((params.get("node"), params.get("command", ""))) or self.items.get((params.get("node"), ""))
            if it is not None:
                self.tree.setCurrentItem(it)
            self.link.call("state.get")
        elif method == "play.ended":
            self.say(f"концовка: {params.get('node')}")
            self.link.call("state.get")
        elif method == "runtime.error":
            self.say("ОШИБКА В ИГРЕ: " + params.get("message", ""))

    def on_response(self, method, ms, result):
        if method in ("state.get", "state.set"):
            self.fill_vars(result.get("vars", {}))
        elif method in ("project.reload", "play.goto"):
            self.statusBar().showMessage(f"{method}: {ms:.0f} мс → {result.get('node')} / {result.get('command')}")
            self.link.call("state.get")

    def closeEvent(self, ev):
        if self.proc is not None:
            self.link.call("app.quit")
            self.proc.waitForFinished(1500)
            if self.proc is not None and self.proc.state() != QProcess.NotRunning:
                self.proc.kill()
        super().closeEvent(ev)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path)
    ap.add_argument("--godot")
    args = ap.parse_args()
    app = QApplication(sys.argv)
    w = Window(args.project, args.godot)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
