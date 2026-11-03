"""The Panel app, driven without a browser."""
import pytest

pytest.importorskip("panel")

from overtone_gui.app import ModesView, OvertoneApp, SpectrumView  # noqa: E402
from overtone_gui.run_data import RunData  # noqa: E402


@pytest.fixture
def no_history(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@pytest.fixture
def spectrum(water_run):
    return SpectrumView(RunData.load(water_run))


def test_run_opens_with_spectrum_and_modes(water_run, no_history):
    tabs = OvertoneApp(water_run).body.objects[0]
    assert tabs._names == ["Spectrum", "Modes"]


def test_result_file_opens_spectrum_only(water_run, no_history):
    tabs = OvertoneApp(water_run / "anharmonics" / "vpt2_result.json").body.objects[0]
    assert tabs._names == ["Spectrum"]


def test_bad_path_returns_to_start_screen_with_message(tmp_path, no_history):
    app = OvertoneApp()
    app.open_run(tmp_path / "missing")
    texts = [o.object for o in app.body.select() if type(o).__name__ == "Alert" and o.visible]
    assert any("does not exist" in t for t in texts)


def test_switching_method_updates_table(spectrum):
    spectrum.method.value = "dcpt2"
    assert "DCPT2" in spectrum.table.value.columns


def test_overlay_adds_columns(spectrum):
    spectrum.compare.value = ["standard"]
    assert {"GVPT2", "Standard VPT2"} <= set(spectrum.table.value.columns)


def test_gaussian_resets_width(spectrum):
    spectrum.shape.value = "gaussian"
    assert spectrum.fwhm.value == 20.0


def test_selected_row_is_marked(spectrum):
    spectrum.table.selection = [0]
    assert spectrum.highlight == pytest.approx(spectrum.table.value.iloc[0]["GVPT2"])


def test_kind_filter_applies_to_table(spectrum):
    spectrum.kinds.value = ["overtone"]
    assert set(spectrum.table.value["Type"]) == {"overtone"}


@pytest.mark.parametrize("index", range(4))
def test_figure_downloads(spectrum, index):
    assert spectrum.downloads.objects[index].callback().read()


def test_modes_follow_spectrum_method(water_run):
    run = RunData.load(water_run)
    spectrum = SpectrumView(run)
    modes = ModesView(run, spectrum.method)
    spectrum.method.value = "dcpt2"
    assert "DCPT2" in modes.info.object


def test_mode_page_is_embedded(water_run):
    run = RunData.load(water_run)
    modes = ModesView(run, SpectrumView(run).method)
    assert modes.viewer.object.startswith("<iframe")


def test_3dmol_is_bundled():
    from overtone_gui.app import STATIC
    assert (STATIC / "3Dmol-min.js").stat().st_size > 100_000
    assert (STATIC / "3Dmol-LICENSE.txt").exists()


def test_mode_page_uses_given_script_url(water_run):
    from overtone_gui.modes import THREEDMOL_LOCAL, mode_page
    run = RunData.load(water_run)
    page = mode_page(run.mode_xyz(6), run.atoms.positions, run.mode_displacement(6),
                     url=THREEDMOL_LOCAL)
    assert f'src="{THREEDMOL_LOCAL}"' in page
    assert "jsdelivr" not in page
