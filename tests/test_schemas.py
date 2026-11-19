import importlib.util
import json
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from conftest import ROOT


@pytest.mark.parametrize("path", sorted((ROOT / "schema").glob("*.schema.json")), ids=lambda p: p.name)
def test_schema_is_valid_draft_2020_12(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(doc)
    assert doc["$id"] == path.name
    assert doc["title"].isascii(), "title становится именем класса: только латиница"


@pytest.mark.skipif(importlib.util.find_spec("datamodel_code_generator") is None, reason="нет datamodel-code-generator")
def test_generated_models_are_up_to_date():
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "codegen" / "gen_models.py"), "--check"],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
