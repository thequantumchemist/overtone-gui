import numpy as np
import pytest
from ase.io import read

from overtone_gui.run_data import (
    RunData,
    RunDirectoryError,
    read_reference,
    recent_runs,
    remember_run,
)


@pytest.fixture(scope="module")
def run(water_run):
    return RunData.load(water_run)


def test_describes_the_run(run):
    assert run.formula == "H2O"
    assert run.active_modes == [6, 7, 8]
    assert run.has_intensities
    assert run.describe() == "H2O, 3 active modes, IR intensities"


def test_full_directory_can_recompute(run):
    assert run.can_recompute


def test_missing_directory_is_reported(tmp_path):
    with pytest.raises(RunDirectoryError, match="does not exist"):
        RunData.load(tmp_path / "nothing")


def test_directory_without_results_names_save_results(tmp_path):
    with pytest.raises(RunDirectoryError, match="save_results=True"):
        RunData.load(tmp_path)


def test_stored_method_is_not_recomputed(run):
    assert run.result_for("gvpt2") is run.result


def test_other_method_is_recomputed_once(run):
    first = run.result_for("dcpt2")
    assert first.method == "dcpt2"
    assert run.result_for("dcpt2") is first


def test_bare_result_file_opens_without_recompute(water_run):
    run = RunData.load(water_run / "anharmonics" / "vpt2_result.json")
    assert not run.can_recompute
    assert run.atoms is None
    with pytest.raises(RunDirectoryError):
        run.result_for("dcpt2")


@pytest.mark.parametrize("mode", [6, 7, 8])
def test_mode_displacement_is_normalised(run, mode):
    disp = run.mode_displacement(mode)
    assert disp.shape == (3, 3)
    assert np.linalg.norm(disp, axis=1).max() == pytest.approx(1.0)


@pytest.mark.parametrize("mode", [6, 7, 8])
def test_mode_keeps_centre_of_mass(run, mode):
    masses = run.atoms.get_masses()
    assert np.allclose(masses @ run.mode_displacement(mode), 0.0, atol=1e-6)


def test_mode_frames_start_at_equilibrium(run):
    frames = run.mode_frames(6, amplitude=0.3, n_frames=12)
    assert len(frames) == 12
    assert np.allclose(frames[0].positions, run.atoms.positions)


def test_mode_xyz_has_every_frame(run, tmp_path):
    path = tmp_path / "mode.xyz"
    path.write_text(run.mode_xyz(7, n_frames=10))
    assert len(read(path, index=":")) == 10


def test_reference_with_few_rows_is_bands():
    ref = read_reference(b"# exp\nnu,I\n1595,1\n3657,0.1\n3756,1.2\n", "water.csv")
    assert ref["kind"] == "bands"
    assert ref["label"] == "water"
    assert list(ref["x"]) == [1595, 3657, 3756]


def test_reference_with_many_rows_is_spectrum():
    data = "\n".join(f"{1000 + i}\t{i % 7}" for i in range(500)).encode()
    assert read_reference(data)["kind"] == "spectrum"


def test_reference_without_numbers_is_rejected():
    with pytest.raises(ValueError, match="No numeric"):
        read_reference(b"just text\n")


def test_recent_runs_are_remembered_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    remember_run(a)
    remember_run(b)
    remember_run(a)
    assert recent_runs() == [a.resolve(), b.resolve()]
