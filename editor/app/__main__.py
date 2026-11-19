"""Запуск редактора:  python -m app [папка проекта]   (из папки editor)
или:  python editor/run.py [папка проекта]"""
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("VN Constructor")
    w = MainWindow()
    w.show()
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target is None:
        recent = QSettings("vn-constructor", "editor").value("recent", [], type=list)
        target = next((p for p in recent if (Path(p) / "project.json").is_file()), None)
    if target is None:
        demo = Path(__file__).resolve().parents[2] / "samples" / "demo"
        target = demo if (demo / "project.json").is_file() else None
    if target:
        w.open(target)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
