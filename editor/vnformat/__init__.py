"""Формат проекта конструктора визуальных новелл: модели, загрузка, сохранение, проверка."""
from .project import Project, ProjectLoadError, RawProject, dump, load_project, load_raw, save_project
from .validate import Issue, validate_project, validate_raw

FORMAT_VERSION = 1

__all__ = [
    "FORMAT_VERSION", "Issue", "Project", "ProjectLoadError", "RawProject", "dump",
    "load_project", "load_raw", "save_project", "validate_project", "validate_raw",
]
