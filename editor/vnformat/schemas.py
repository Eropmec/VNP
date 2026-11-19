"""Доступ к JSON Schema формата: реестр ссылок и валидаторы по видам файлов."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"

#: вид файла → имя схемы
FILE_KINDS = {
    "project": "project.schema.json",
    "graph": "graph.schema.json",
    "layout": "layout.schema.json",
    "scene": "scene.schema.json",
    "variables": "variables.schema.json",
    "character": "character.schema.json",
    "assets": "assets.schema.json",
}


@lru_cache(maxsize=1)
def registry() -> Registry:
    resources = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


@lru_cache(maxsize=None)
def validator(kind: str) -> Draft202012Validator:
    """Валидатор целого файла заданного вида."""
    schema = registry().contents(FILE_KINDS[kind])
    return Draft202012Validator(schema, registry=registry())


@lru_cache(maxsize=None)
def def_validator(schema_id: str, def_name: str) -> Draft202012Validator:
    """Валидатор отдельного определения, например scene.schema.json → SayCommand.

    Нужен, чтобы проверять элемент по схеме ЕГО типа: ошибка «в say нет поля text»
    понятнее, чем «не подходит ни под один из 13 вариантов oneOf»."""
    return Draft202012Validator({"$ref": f"{schema_id}#/$defs/{def_name}"}, registry=registry())


#: значение дискриминатора → имя определения в схеме
NODE_DEFS = {"chapter": "ChapterNode", "scene": "SceneNode", "branch": "BranchNode", "ending": "EndingNode"}
COMMAND_DEFS = {
    "bg": "BgCommand", "show": "ShowCommand", "hide": "HideCommand", "say": "SayCommand",
    "narrate": "NarrateCommand", "choice": "ChoiceCommand", "jump": "JumpCommand", "set": "SetCommand",
    "if": "IfCommand", "wait": "WaitCommand", "music": "MusicCommand", "sfx": "SfxCommand",
    "stop_audio": "StopAudioCommand",
}
