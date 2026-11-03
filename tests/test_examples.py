"""The example runs shipped with the package."""
import pytest

from overtone_gui.cli import main
from overtone_gui.run_data import (
    EXAMPLES,
    RunData,
    RunDirectoryError,
    example_name,
    example_path,
)


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_opens_with_everything_the_viewer_needs(name):
    run = RunData.load(example_path(name))
    assert run.can_recompute
    assert run.has_intensities
    assert run.atoms is not None


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_recomputes_other_methods(name):
    assert RunData.load(example_path(name)).result_for("dcpt2").method == "dcpt2"


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_modes_can_be_animated(name):
    run = RunData.load(example_path(name))
    assert len(run.mode_frames(run.active_modes[0], n_frames=4)) == 4


def test_formaldehyde_shows_a_fermi_resonance():
    run = RunData.load(example_path("formaldehyde"))
    assert any(t.resonance_affected for t in run.result.transitions)


def test_example_header_names_the_example():
    assert RunData.load(example_path("water")).display_path == "example: water"


def test_own_runs_are_not_examples(tmp_path):
    assert example_name(tmp_path) is None


def test_unknown_example_lists_available():
    with pytest.raises(RunDirectoryError, match="formaldehyde"):
        example_path("benzene")


def test_cli_lists_examples(capsys):
    assert main(["example"]) == 0
    out = capsys.readouterr().out
    assert all(name in out for name in EXAMPLES)


def test_cli_rejects_unknown_example(capsys):
    assert main(["example", "benzene"]) == 1
    assert "Unknown example" in capsys.readouterr().err


def test_start_screen_offers_examples(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from overtone_gui.app import OvertoneApp
    labels = [getattr(w, "label", None) for w in OvertoneApp().root.select()]
    assert all(title in labels for title in EXAMPLES.values())


def test_opening_an_example_keeps_history_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from overtone_gui.app import OvertoneApp
    from overtone_gui.run_data import recent_runs
    app = OvertoneApp()
    app.open_run(example_path("formaldehyde"))
    assert app.body.objects[0]._names == ["Spectrum", "Modes"]
    assert recent_runs() == []
