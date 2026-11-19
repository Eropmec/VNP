"""Запуск редактора из любой папки:  python editor/run.py [папка проекта]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.__main__ import main  # noqa: E402

sys.exit(main())
