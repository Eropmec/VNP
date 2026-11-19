"""Окно «Собрать игру»: Windows / Linux / Android, проверка проекта, шаблоны Godot, журнал."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
                               QVBoxLayout, QWidget)

from . import builder as B


class BuildWorker(QThread):
    message = Signal(str)
    progress = Signal(int, int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, root, target, out_dir, godot, debug, sdk="", java=""):
        super().__init__()
        self.args = (root, target, out_dir, godot, debug, sdk, java)

    def run(self):
        root, target, out_dir, godot, debug, sdk, java = self.args
        try:
            ver = B.godot_version(B.console_exe(godot))
            if B.missing_templates(ver, target):
                B.fetch_templates(ver, target, self.message.emit, lambda d, t: self.progress.emit(d, t))
            self.progress.emit(0, 0)
            out = B.build(root, target, out_dir, godot, debug, self.message.emit, sdk, java)
            self.finished_ok.emit(str(out))
        except B.BuildError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # сеть, диск — всё показываем в журнале, а не роняем редактор
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def _path_row(edit: QLineEdit, title: str, parent) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(edit, 1)
    b = QPushButton("…")
    b.setFixedWidth(32)

    def pick():
        d = QFileDialog.getExistingDirectory(parent, title, edit.text())
        if d:
            edit.setText(d)
    b.clicked.connect(pick)
    h.addWidget(b)
    return w


class BuildDialog(QDialog):
    def __init__(self, parent, doc, godot: str, save_cb, problems_cb=None):
        super().__init__(parent)
        self.doc, self.godot, self.save_cb, self.problems_cb = doc, godot, save_cb, problems_cb
        self.settings = QSettings("vn-constructor", "editor")
        self.worker: BuildWorker | None = None
        self.result_path: str | None = None
        self.setWindowTitle("Собрать игру")
        self.resize(720, 620)
        try:
            self.version = B.godot_version(B.console_exe(godot))
        except B.BuildError as exc:
            self.version = ""
            self._version_error = str(exc)

        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        self.targets = QButtonGroup(self)
        row = QHBoxLayout()
        for i, (key, t) in enumerate(B.TARGETS.items()):
            r = QRadioButton(t["title"])
            r.setProperty("key", key)
            self.targets.addButton(r, i)
            row.addWidget(r)
        row.addStretch()
        form.addRow("Для чего:", row)
        saved = self.settings.value("build/target", "windows")
        for b in self.targets.buttons():
            b.setChecked(b.property("key") == saved)

        self.modes = QButtonGroup(self)
        mrow = QHBoxLayout()
        self.release = QRadioButton("Для игроков")
        self.debug = QRadioButton("Для проверки (с консолью ошибок)")
        for i, r in enumerate((self.release, self.debug)):
            self.modes.addButton(r, i)
            mrow.addWidget(r)
        mrow.addStretch()
        (self.debug if self.settings.value("build/debug", "false") == "true" else self.release).setChecked(True)
        form.addRow("Сборка:", mrow)

        self.out = QLineEdit()
        form.addRow("Куда положить:", _path_row(self.out, "Папка для готовой игры", self))

        self.android = QGroupBox("Android")
        af = QFormLayout(self.android)
        self.sdk = QLineEdit(self.settings.value("build/android_sdk", ""))
        self.java = QLineEdit(self.settings.value("build/android_java", ""))
        self.sdk.setPlaceholderText("найдётся сам, если стоит Android Studio")
        self.java.setPlaceholderText("найдётся сам, если стоит Android Studio")
        af.addRow("Android SDK:", _path_row(self.sdk, "Папка Android SDK", self))
        af.addRow("Java (JDK 17+):", _path_row(self.java, "Папка JDK", self))
        self.android_status = QLabel()
        self.android_status.setWordWrap(True)
        self.android_status.setOpenExternalLinks(True)
        af.addRow(self.android_status)
        lay.addWidget(self.android)

        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.hide()
        lay.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        lay.addWidget(self.log, 1)

        buttons = QHBoxLayout()
        self.problems_btn = QPushButton("Показать проблемы")
        self.problems_btn.hide()
        self.problems_btn.clicked.connect(self._show_problems)
        buttons.addWidget(self.problems_btn)
        buttons.addStretch()
        self.open_btn = QPushButton("Открыть папку")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_folder)
        self.build_btn = QPushButton("Собрать")
        self.build_btn.setDefault(True)
        self.build_btn.clicked.connect(self.start)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        for b in (self.open_btn, self.build_btn, close):
            buttons.addWidget(b)
        lay.addLayout(buttons)

        self.targets.idToggled.connect(lambda _i, on: on and self._target_changed())
        self.sdk.editingFinished.connect(self._refresh)
        self.java.editingFinished.connect(self._refresh)
        self._target_changed()

    # ------------------------------------------------------------ состояние
    def target(self) -> str:
        return self.targets.checkedButton().property("key")

    def _target_changed(self):
        self.out.setText(str(self.doc.root / "build" / self.target()))
        self._refresh()

    def _refresh(self):
        t = self.target()
        self.android.setVisible(t == "android")
        if not self.version:
            self.status.setText(f"⚠ {getattr(self, '_version_error', 'Godot не найден')}")
            self.build_btn.setEnabled(False)
            return
        missing = B.missing_templates(self.version, t)
        tv = B.template_version(self.version)
        self.status.setText(f"Godot {tv}. " + (
            f"Шаблоны экспорта для {B.TARGETS[t]['title']} скачаются при сборке (только нужные, около 30–100 МБ)."
            if missing else "Шаблоны экспорта на месте."))
        ok = True
        if t == "android":
            a = B.android_setup(self.version, self.sdk.text().strip(), self.java.text().strip())
            if a.problems:
                ok = False
                self.android_status.setText(
                    "⚠ " + "; ".join(a.problems) + ".<br>Проще всего поставить "
                    "<a href='https://developer.android.com/studio'>Android Studio</a> и один раз открыть её — "
                    "SDK и Java придут вместе с ней, тогда пути найдутся сами.")
            else:
                self.android_status.setText(f"✔ SDK: {a.sdk}<br>✔ Java: {a.java}")
        self.build_btn.setEnabled(ok and self.worker is None)

    # ------------------------------------------------------------ сборка
    def start(self):
        if self.worker is not None:
            return
        self.log.clear()
        self.problems_btn.hide()
        self.open_btn.setEnabled(False)
        fixed = self.doc.repair_missing_texts()
        if fixed:
            self.log.appendPlainText(f"Восстановлено пропавших текстов: {fixed} (пустые — допиши их, см. «Проблемы»).")
        if self.doc.dirty:
            self.save_cb()
            self.log.appendPlainText("Проект сохранён.")
        t = self.target()
        self.settings.setValue("build/target", t)
        self.settings.setValue("build/debug", "true" if self.debug.isChecked() else "false")
        self.settings.setValue("build/android_sdk", self.sdk.text().strip())
        self.settings.setValue("build/android_java", self.java.text().strip())
        self.worker = BuildWorker(str(self.doc.root), t, self.out.text().strip() or str(self.doc.root / "build" / t),
                                  self.godot, self.debug.isChecked(), self.sdk.text().strip(), self.java.text().strip())
        self.worker.message.connect(self.log.appendPlainText)
        self.worker.progress.connect(self._progress)
        self.worker.finished_ok.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._worker_gone)
        self.build_btn.setEnabled(False)
        self.build_btn.setText("Собираю…")
        self.bar.show()
        self.bar.setRange(0, 0)
        self.worker.start()

    def _progress(self, done: int, total: int):
        if total <= 0:
            self.bar.setRange(0, 0)
            self.bar.setFormat("")
        else:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.bar.setFormat(f"шаблоны: {done / 2**20:.0f} из {total / 2**20:.0f} МБ")

    def _done(self, path: str):
        self.result_path = path
        self.log.appendPlainText(f"\n✔ Игра собрана: {path}")
        self.open_btn.setEnabled(True)
        self.status.setText(f"✔ Готово: <b>{Path(path).name}</b>")

    def _failed(self, msg: str):
        self.log.appendPlainText(f"\n✖ Не собралось: {msg}")
        self.status.setText("✖ Не собралось — причина в журнале.")
        if "ошибки" in msg and self.problems_cb:
            self.problems_btn.show()

    def _worker_gone(self):
        self.worker = None
        self.bar.hide()
        self.build_btn.setText("Собрать")
        self._refresh()

    def _open_folder(self):
        folder = Path(self.result_path).parent if self.result_path else Path(self.out.text())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _show_problems(self):
        if self.problems_cb:
            self.problems_cb()

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            self.log.appendPlainText("Дождись окончания сборки.")
            e.ignore()
            return
        super().closeEvent(e)

    def reject(self):  # Esc
        if self.worker is not None and self.worker.isRunning():
            return
        super().reject()
