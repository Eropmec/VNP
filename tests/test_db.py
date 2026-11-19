"""Базы проекта: переменные, персонажи, ассеты (Qt offscreen)."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vnformat import validate_project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def doc(qapp, demo):
    from app.document import ProjectDocument
    d = ProjectDocument()
    d.load(demo.root)
    return d


def errors(d):
    return [str(i) for i in d.validate() if i.severity == "error"]


@pytest.fixture
def pngs(tmp_path):
    from PySide6.QtGui import QColor, QImage
    out = []
    for name in ("Борис-спокойный.png", "boris_angry.png"):
        img = QImage(40, 60, QImage.Format_ARGB32)
        img.fill(QColor("#884422"))
        p = tmp_path / name
        img.save(str(p))
        out.append(p)
    return out


def test_expression_names():
    from app.db_ops import expression_name
    assert expression_name(Path("anna_sad.png"), "ch_anna") == "sad"
    assert expression_name(Path("Анна-грустная.png")) == "грустная"
    assert expression_name(Path("smile.png")) == "smile"
    assert expression_name(Path("01.png")) == "e_01"


def test_import_files_copies_and_registers(doc, pngs, tmp_path):
    from app import db_ops as D
    (tmp_path / "notes.txt").write_text("x")
    ids = D.import_files(doc, pngs + [tmp_path / "notes.txt"], role="bg")
    assert len(ids) == 2
    paths = [a["path"] for a in D.asset_list(doc) if a["id"] in ids]
    assert all(p.startswith("bg/") and (doc.root / "assets" / p).is_file() for p in paths)
    again = D.import_files(doc, [doc.root / "assets" / paths[0]])          # уже в проекте — не дублируется
    assert again == [ids[0]] and len(D.asset_list(doc)) == 9
    assert errors(doc) == []


def test_new_character_with_images_and_placeholder(doc, pngs):
    from app import db_ops as D
    cid = D.new_character(doc, "Борис", images=pngs)
    ch = D.characters(doc)[cid]
    assert cid == "ch_boris" and set(ch["expressions"]) == {"спокойный", "angry"}
    assert doc.text(ch["name"]) == "Борис"
    ghost = D.new_character(doc, "Призрак")
    gch = D.characters(doc)[ghost]
    assert list(gch["expressions"]) == ["neutral"]
    assert D.asset_file(doc, gch["expressions"]["neutral"]).is_file()
    assert errors(doc) == []
    doc.undo.undo()
    assert ghost not in D.characters(doc), "персонаж с картинкой отменяется одним Ctrl+Z"
    doc.save()
    assert validate_project(doc.root) == [] or not [i for i in validate_project(doc.root) if i.severity == "error"]


def test_find_uses(doc):
    from app import db_ops as D
    assert len(D.find_uses(doc, "var", "v_sanity")) == 4      # вариант, set, if, ветвление
    assert {u.scene for u in D.find_uses(doc, "char", "ch_anna")} == {"sc_intro", "sc_cellar", "sc_hall"}
    assert any("эмоция" in u.where for u in D.find_uses(doc, "asset", "a_anna_sad"))
    assert D.find_uses(doc, "asset", "a_sfx_creak")[0].path == (1,)


def test_variables_editor(doc):
    from app.db_editors import VariablesEditor
    ed = VariablesEditor(doc)
    row = ed._ids().index("v_courage")
    ed.table.item(row, 1).setText("отвага")
    assert next(v for v in doc.get("variables")["variables"] if v["id"] == "v_courage")["name"] == "отвага"
    ed.table.item(row, 1).setText("рассудок")                     # занято — не применяется
    assert next(v for v in doc.get("variables")["variables"] if v["id"] == "v_courage")["name"] == "отвага"
    ed.refresh()
    row = ed._ids().index("v_sanity")
    ed.table.item(row, 3).setText("8")
    assert next(v for v in doc.get("variables")["variables"] if v["id"] == "v_sanity")["default"] == 8
    vid = __import__("app.db_ops", fromlist=["x"]).add_variable(doc)
    ed.refresh()
    ed._type(vid, "bool")
    v = next(v for v in doc.get("variables")["variables"] if v["id"] == vid)
    assert v["type"] == "bool" and v["default"] is False
    assert errors(doc) == []


def test_rename_expression_updates_scenes(doc):
    from app.db_editors import CharactersEditor
    ed = CharactersEditor(doc)
    ed.show_char("ch_anna")
    ed.rename_expression("sad", "грустная")
    assert "грустная" in doc.files[("character", "ch_anna")]["expressions"]
    assert doc.scenes()["sc_hall"]["commands"][1]["expr"] == "грустная"
    assert doc.scenes()["sc_intro"]["commands"][5]["expr"] == "грустная"
    assert errors(doc) == []
    doc.undo.undo()
    assert doc.scenes()["sc_hall"]["commands"][1]["expr"] == "sad"


def test_add_expressions_by_drop(doc, pngs):
    from app.db_editors import CharactersEditor
    ed = CharactersEditor(doc)
    ed.show_char("ch_anna")
    ed.add_expressions([str(p) for p in pngs])
    assert {"спокойный", "angry"} <= set(doc.files[("character", "ch_anna")]["expressions"])
    assert errors(doc) == []


def test_assets_editor_import_and_remove(doc, pngs, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.db_editors import AssetsEditor
    ed = AssetsEditor(doc)
    ed.role.setCurrentIndex(0)
    ids = ed.import_files([str(pngs[0])])
    assert ed.list.count() == 8 and ed._current == ids[0]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    for i in range(ed.list.count()):
        ed.list.item(i).setSelected(ed.list.item(i).data(0x0100) == ids[0])
    ed.remove()
    assert ids[0] not in {a["id"] for a in doc.get("assets")["assets"]}


def test_db_tabs_and_goto_use(qapp, demo):
    from app.main_window import MainWindow
    from app import db_ops as D
    w = MainWindow()
    w.open(demo.root)
    v = w.open_db("vars")
    assert w.tabs.currentWidget() is v and w.open_db("vars") is v
    use = next(u for u in D.find_uses(w.doc, "var", "v_saw_shadow") if u.scene)
    w._goto_use(use)
    ed = w.scene_tabs[use.scene]
    assert w.tabs.currentWidget() is ed and ed.path == use.path
    w.doc.undo.setClean()
    w.close()
