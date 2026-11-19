"""python -m vnformat <папка проекта> [--json] [--min error|warning|info]"""
import sys

from .validate import main

sys.exit(main())
