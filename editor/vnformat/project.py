"""Загрузка и сохранение проекта.

Два уровня:
- RawProject — файлы как прочитанный JSON (dict/list). С ним работает валидатор:
  ему нужны точные типы значений и путь к каждому полю.
- Project — те же данные в pydantic-моделях из models/. С ним работает редактор.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from . import io
from .models import (
    assets_schema, character_schema, graph_schema, layout_schema, project_schema, scene_schema,
    variables_schema,
)

PROJECT_FILE = "project.json"
GRAPH_FILE = "story/graph.json"
LAYOUT_FILE = "story/layout.json"
SCENES_DIR = "story/scenes"
VARIABLES_FILE = "db/variables.json"
CHARACTERS_DIR = "db/characters"
ASSETS_DIR = "assets"
ASSETS_FILE = "assets/registry.json"
LOCALE_DIR = "locale"


@dataclass
class RawProject:
    root: Path
    project: Any = None
    graph: Any = None
    layout: Any = None
    variables: Any = None
    assets: Any = None
    scenes: dict[str, Any] = field(default_factory=dict)        # относительный путь → JSON
    characters: dict[str, Any] = field(default_factory=dict)
    locales: dict[str, dict[str, str]] = field(default_factory=dict)
    locale_duplicates: dict[str, list[str]] = field(default_factory=dict)
    read_errors: list[tuple[str, str]] = field(default_factory=list)  # (файл, сообщение)
    missing: list[str] = field(default_factory=list)                   # обязательные файлы, которых нет


def _read(root: Path, rel: str, raw: RawProject, required: bool = True) -> Any:
    path = root / rel
    if not path.exists():
        if required:
            raw.missing.append(rel)
        return None
    try:
        return io.read_json(path)
    except json.JSONDecodeError as exc:
        raw.read_errors.append((rel, f"ошибка JSON в строке {exc.lineno}, столбце {exc.colno}: {exc.msg}"))
    except OSError as exc:
        raw.read_errors.append((rel, f"не удалось прочитать: {exc}"))
    return None


def load_raw(root: str | Path) -> RawProject:
    root = Path(root)
    raw = RawProject(root=root)
    raw.project = _read(root, PROJECT_FILE, raw)
    raw.graph = _read(root, GRAPH_FILE, raw)
    raw.layout = _read(root, LAYOUT_FILE, raw, required=False)
    raw.variables = _read(root, VARIABLES_FILE, raw)
    raw.assets = _read(root, ASSETS_FILE, raw)
    for path in sorted((root / SCENES_DIR).glob("*.json")):
        rel = path.relative_to(root).as_posix()
        data = _read(root, rel, raw)
        if data is not None:
            raw.scenes[rel] = data
    for path in sorted((root / CHARACTERS_DIR).glob("*.json")):
        rel = path.relative_to(root).as_posix()
        data = _read(root, rel, raw)
        if data is not None:
            raw.characters[rel] = data
    for path in sorted((root / LOCALE_DIR).glob("*.csv")):
        rel = path.relative_to(root).as_posix()
        try:
            strings, dups = io.read_locale(path)
        except (io.LocaleError, OSError, UnicodeDecodeError) as exc:
            raw.read_errors.append((rel, str(exc)))
            continue
        raw.locales[path.stem] = strings
        raw.locale_duplicates[path.stem] = dups
    return raw


# ---------------------------------------------------------------- модели

@dataclass
class Project:
    root: Path
    project: project_schema.Project
    graph: graph_schema.Graph
    layout: layout_schema.Layout
    variables: variables_schema.Variables
    assets: assets_schema.AssetRegistry
    scenes: dict[str, scene_schema.Scene]               # id сцены → модель
    characters: dict[str, character_schema.Character]   # id персонажа → модель
    locales: dict[str, dict[str, str]]


class ProjectLoadError(Exception):
    def __init__(self, issues):
        self.issues = issues
        super().__init__(f"проект содержит ошибки: {len([i for i in issues if i.severity == 'error'])}")


def load_project(root: str | Path, *, check: bool = True) -> Project:
    """Загрузить проект в модели. По умолчанию сначала валидирует и не грузит проект с ошибками."""
    raw = load_raw(root)
    if check:
        from .validate import validate_raw
        issues = validate_raw(raw)
        if any(i.severity == "error" for i in issues):
            raise ProjectLoadError(issues)
    return Project(
        root=raw.root,
        project=project_schema.Project.model_validate(raw.project),
        graph=graph_schema.Graph.model_validate(raw.graph),
        layout=layout_schema.Layout.model_validate(raw.layout or {"positions": {}}),
        variables=variables_schema.Variables.model_validate(raw.variables),
        assets=assets_schema.AssetRegistry.model_validate(raw.assets),
        scenes={d["id"]: scene_schema.Scene.model_validate(d) for d in raw.scenes.values()},
        characters={d["id"]: character_schema.Character.model_validate(d) for d in raw.characters.values()},
        locales=raw.locales,
    )


def dump(model: BaseModel) -> Any:
    """Модель → JSON-совместимые данные, ровно с теми полями, что заданы (без null по умолчанию)."""
    return model.model_dump(mode="json", by_alias=True, exclude_unset=True)


def save_project(p: Project, root: str | Path | None = None) -> None:
    root = Path(root) if root is not None else p.root
    io.write_json(root / PROJECT_FILE, dump(p.project))
    io.write_json(root / GRAPH_FILE, dump(p.graph))
    io.write_json(root / LAYOUT_FILE, dump(p.layout))
    io.write_json(root / VARIABLES_FILE, dump(p.variables))
    io.write_json(root / ASSETS_FILE, dump(p.assets))
    for sid, scene in p.scenes.items():
        io.write_json(root / SCENES_DIR / f"{sid}.json", dump(scene))
    for cid, ch in p.characters.items():
        io.write_json(root / CHARACTERS_DIR / f"{cid}.json", dump(ch))
    for lang, strings in p.locales.items():
        io.write_locale(root / LOCALE_DIR / f"{lang}.csv", strings)
