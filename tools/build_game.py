"""
Собирает игру без редактора — то же, что «Игра → Собрать игру…».

    python tools/build_game.py --godot C:/Godot/Godot_v4.7.2-stable_win64.exe --target windows
    python tools/build_game.py путь/к/проекту --godot ... --target android --debug
    python tools/build_game.py --godot ... --target linux --out D:/сборки

Цели: windows, linux, android. Недостающие шаблоны экспорта Godot скачиваются сами
(только нужные файлы). Результат по умолчанию — в <проект>/build/<цель>/.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "editor"))

from app import builder as B  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Собрать игру")
    ap.add_argument("project", nargs="?", default=str(ROOT / "samples" / "demo"))
    ap.add_argument("--godot", required=True, help="путь к Godot 4.4+")
    ap.add_argument("--target", choices=list(B.TARGETS), default="windows")
    ap.add_argument("--debug", action="store_true", help="сборка для проверки (с консолью ошибок)")
    ap.add_argument("--out", help="папка для готовой игры")
    ap.add_argument("--android-sdk", default="")
    ap.add_argument("--java", default="")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    try:
        ver = B.godot_version(B.console_exe(a.godot))
        if B.missing_templates(ver, a.target):
            def progress(done, total):
                print(f"\r  {done / 2**20:.0f} / {total / 2**20:.0f} МБ", end="", flush=True)
            B.fetch_templates(ver, a.target, print, progress)
            print()
        out = B.build(project, a.target, a.out or project / "build" / a.target, a.godot, a.debug, print,
                      a.android_sdk, a.java)
    except B.BuildError as exc:
        print(f"\nНе собралось: {exc}")
        return 1
    print(f"\nИгра: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
