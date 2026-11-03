"""Student mode, driven without a browser (calculations run in the test thread)."""
import pytest

pytest.importorskip("panel")
pytest.importorskip("tblite.ase")

from ase.collections import g2  # noqa: E402

from overtone_gui.run_data import RunData  # noqa: E402
from overtone_gui.student import (  # noqa: E402
    MAX_ATOMS,
    STEPS,
    Progress,
    Settings,
    StudentView,
    describe_duration,
    molecule_choices,
    read_xyz,
    run_calculation,
)

WATER_XYZ = b"3\nwater\nO 0.0 0.0 0.119\nH 0.0 0.763 -0.477\nH 0.0 -0.763 -0.477\n"


@pytest.fixture
def view(tmp_path):
    opened = []
    v = StudentView(tmp_path / "runs", on_open=opened.append)
    v.opened = opened
    return v


@pytest.fixture(scope="module")
def water_progress(tmp_path_factory):
    progress = Progress()
    run_calculation(g2["H2O"], "H2O", Settings(max_quanta=2), tmp_path_factory.mktemp("runs"),
                    progress)
    return progress


def test_choices_are_small_closed_shell_molecules():
    names = molecule_choices()
    assert "H2O" in names
    assert all(2 <= len(g2[n]) <= MAX_ATOMS and sum(g2[n].numbers) % 2 == 0 for n in names)


@pytest.mark.parametrize("name", ["Al", "BeH"])
def test_atoms_and_radicals_are_not_offered(name):
    assert name not in molecule_choices()


def test_xyz_upload_is_read():
    assert read_xyz(WATER_XYZ).get_chemical_formula() == "H2O"


@pytest.mark.parametrize("data, message", [
    (b"9\n\n" + b"H 0 0 0\n" * 8 + b"He 0 0 0\n", "allows up to"),
    (b"2\n\nN 0 0 0\nO 0 0 1.15\n", "odd number of electrons"),
    (b"1\n\nHe 0 0 0\n", "fewer than two atoms"),
    (b"not an xyz file", "could not be read"),
])
def test_xyz_upload_is_checked(data, message):
    with pytest.raises(ValueError, match=message):
        read_xyz(data, "upload.xyz")


@pytest.mark.parametrize("seconds, text", [(10, "under a minute"), (100, "about 2 minutes")])
def test_duration_text(seconds, text):
    assert describe_duration(seconds) == text


def test_every_step_finishes(water_progress):
    assert water_progress.snapshot()["states"] == {k: "done" for k, *_ in STEPS}


def test_finished_run_opens_in_viewer(water_progress):
    run = RunData.load(water_progress.result_dir)
    assert run.formula == "H2O"
    assert run.has_intensities


def test_single_points_are_counted(water_progress):
    assert any("Quartic force field: 181 single points" in line
               for line in water_progress.snapshot()["lines"])


def test_cancel_stops_before_any_single_point(tmp_path):
    progress = Progress()
    progress.cancel.set()
    run_calculation(g2["NH3"], "NH3", Settings(), tmp_path, progress)
    s = progress.snapshot()
    assert s["cancelled"] and not s["finished"]
    assert s["states"]["optimize"] == "cancelled"


def test_errors_are_reported_not_raised(tmp_path):
    def broken():
        raise RuntimeError("calculator exploded")
    progress = Progress()
    run_calculation(g2["H2O"], "H2O", Settings(), tmp_path, progress, calculator=broken)
    assert progress.snapshot()["error"] == "calculator exploded"


def test_cost_is_estimated(view):
    assert "200 single points" in view.cost.object


def test_upload_replaces_named_molecule(view):
    view.upload.filename = "my_water.xyz"
    view.upload.value = WATER_XYZ
    atoms, name = view.current_molecule()
    assert name == "my_water"


def test_view_runs_and_offers_results(view):
    view.start(background=False)
    assert view.open_button.visible
    assert "Finished" in view.status_title.object


def test_open_results_hands_over_run_directory(view):
    view.start(background=False)
    view.open_button.clicks += 1
    assert view.opened == [view.progress.result_dir]


def test_student_start_screen_offers_new_calculation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from overtone_gui.app import OvertoneApp
    app = OvertoneApp(student=True, runs_dir=tmp_path)
    labels = [getattr(w, "label", None) for w in app.root.select()]
    assert "Start a calculation" in labels


def test_viewer_start_screen_has_no_calculation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from overtone_gui.app import OvertoneApp
    labels = [getattr(w, "label", None) for w in OvertoneApp().root.select()]
    assert "Start a calculation" not in labels


def test_student_app_can_open_compute_screen_directly(tmp_path):
    from overtone_gui.app import OvertoneApp
    app = OvertoneApp(student=True, runs_dir=tmp_path, start_compute=True)
    assert app.compute.layout in app.body.objects
