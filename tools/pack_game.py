"""
Упаковывает проект в рантайм: копирует его в runtime/game, чтобы Godot собрал игру
(Windows, Android). Перед упаковкой проект проверяется; с ошибками не пакуется.

    python tools/pack_game.py                    # samples/demo → runtime/game
    python tools/pack_game.py путь/к/проекту

Таблицы строк превращаются из CSV в JSON: Godot импортирует *.csv как свои переводы
и в сборку исходный файл не попадает.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "editor"))

from vnformat import validate_project  # noqa: E402
from vnformat.pack import pack  # noqa: E402

TARGET = ROOT / "runtime" / "game"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", nargs="?", default=str(ROOT / "samples" / "demo"))
    args = ap.parse_args()
    src = Path(args.project).resolve()

    issues = validate_project(src)
    errors = [i for i in issues if i.severity == "error"]
    for i in issues:
        if i.severity != "info":
            print(i)
    if errors:
        print(f"\nПроект не упакован: ошибок {len(errors)}")
        return 1

    files = pack(src, TARGET)
    print(f"Упаковано в {TARGET.relative_to(ROOT)}: файлов {files}")
    print("Дальше: открой runtime/ в Godot и нажми F5, либо Проект → Экспорт.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
