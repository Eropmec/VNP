import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "editor"))
DEMO = ROOT / "samples" / "demo"


class ProjectCopy:
    """Копия демо-проекта во временной папке с удобной правкой файлов."""

    def __init__(self, root: Path):
        self.root = root

    def load(self, rel):
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def save(self, rel, data):
        (self.root / rel).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def edit(self, rel, fn):
        data = self.load(rel)
        fn(data)
        self.save(rel, data)

    def node(self, graph, nid):
        return next(n for n in graph["nodes"] if n["id"] == nid)

    def edge(self, graph, eid):
        return next(e for e in graph["edges"] if e["id"] == eid)

    def cmd(self, scene, cid):
        return next(c for c in scene["commands"] if c["id"] == cid)

    def issues(self):
        from vnformat import validate_project
        return validate_project(self.root)


@pytest.fixture
def demo(tmp_path) -> ProjectCopy:
    dst = tmp_path / "demo"
    shutil.copytree(DEMO, dst)
    return ProjectCopy(dst)


def codes(issues, severity=None):
    return {i.code for i in issues if severity is None or i.severity == severity}
