"""
Генерирует pydantic-модели редактора из JSON Schema.

    python tools/codegen/gen_models.py          # перегенерировать
    python tools/codegen/gen_models.py --check  # упасть, если модели устарели (для CI)

Единственный источник правды — папка schema/. Файлы в editor/vnformat/models
руками не правятся: любое изменение формата начинается со схемы.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schema"
TARGET = ROOT / "editor" / "vnformat" / "models"

ARGS = [
    "--input-file-type", "jsonschema",
    "--output-model-type", "pydantic_v2.BaseModel",
    "--target-python-version", "3.11",
    "--use-annotated",
    "--field-constraints",
    "--use-standard-collections",
    "--use-union-operator",
    "--use-title-as-name",
    "--collapse-root-models",
    "--disable-timestamp",
    "--formatters", "black", "isort",
]


def generate(out: Path) -> None:
    cmd = [sys.executable, "-m", "datamodel_code_generator", "--input", str(SCHEMA), "--output", str(out), *ARGS]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        raise SystemExit("Кодогенерация не удалась")
    (out / "__init__.py").write_text(
        '"""Сгенерировано tools/codegen/gen_models.py из schema/. Не править руками."""\n',
        encoding="utf-8",
    )


def _files(root: Path) -> dict[str, str]:
    """Содержимое .py-файлов с переводами строк, приведёнными к \\n (Windows пишет \\r\\n)."""
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8").replace("\r\n", "\n")
            for p in root.rglob("*.py") if "__pycache__" not in p.parts}


def diff_files(a: Path, b: Path) -> list[str]:
    fa, fb = _files(a), _files(b)
    return sorted(k for k in fa.keys() | fb.keys() if fa.get(k) != fb.get(k))


def normalize_newlines(root: Path) -> None:
    for p in root.rglob("*.py"):
        p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "models"
        generate(out)
        normalize_newlines(out)
        if args.check:
            diff = diff_files(out, TARGET) if TARGET.exists() else ["(папки models нет)"]
            if not diff:
                print("Модели актуальны")
                return 0
            print("Модели устарели: запусти tools/codegen/gen_models.py")
            print("Отличаются: " + ", ".join(diff))
            return 1
        if TARGET.exists():
            shutil.rmtree(TARGET)
        shutil.copytree(out, TARGET)
    print(f"Модели записаны в {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
