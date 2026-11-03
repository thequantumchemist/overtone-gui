import sys

import overtone

import overtone_gui
from overtone_gui.cli import STUDENT_HINT, main


def test_version_names_both_packages(capsys):
    assert main(["version"]) == 0
    out = capsys.readouterr().out
    assert f"overtone-gui {overtone_gui.__version__}" in out
    assert f"overtone-vpt2 {overtone.__version__}" in out


def test_view_rejects_missing_run_before_serving(tmp_path, capsys):
    assert main(["view", str(tmp_path / "missing")]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_student_without_extra_gives_install_hint(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "tblite.ase", None)
    assert main(["student"]) == 1
    assert STUDENT_HINT in capsys.readouterr().err


def test_package_version_matches_metadata():
    from importlib.metadata import version
    assert version("overtone-gui") == overtone_gui.__version__
