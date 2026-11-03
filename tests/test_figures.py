import pytest
from matplotlib.figure import Figure

from overtone_gui.figures import (
    SpectrumOptions,
    figure_bytes,
    nice_label,
    reproduce_script,
    spectrum_figure,
)
from overtone_gui.run_data import RunData


@pytest.fixture(scope="module")
def results(water_run):
    run = RunData.load(water_run)
    return {"GVPT2": run.result_for("gvpt2"), "DCPT2": run.result_for("dcpt2")}


@pytest.mark.parametrize("label, expected", [
    ("v7", r"$\nu_{7}$"),
    ("2v7", r"$2\nu_{7}$"),
    ("v7+2v9", r"$\nu_{7}{+}2\nu_{9}$"),
])
def test_nice_label(label, expected):
    assert nice_label(label) == expected


def test_comparison_draws_one_line_per_method(results):
    fig = spectrum_figure(results, SpectrumOptions(sticks=False, peak_labels=False))
    assert isinstance(fig, Figure)
    assert len(fig.axes[0].get_lines()) == 2


def test_log_axis(results):
    fig = spectrum_figure(results, SpectrumOptions(log=True))
    assert fig.axes[0].get_yscale() == "log"


def test_wavenumbers_run_from_high_to_low_by_default(results):
    lo, hi = spectrum_figure(results, SpectrumOptions()).axes[0].get_xlim()
    assert lo > hi


def test_wavelength_axis_increases(results):
    lo, hi = spectrum_figure(results, SpectrumOptions(unit="nm")).axes[0].get_xlim()
    assert lo < hi


def test_reference_is_drawn(results):
    ref = {"x": [1595.0, 3657.0, 3756.0], "y": [1.0, 0.1, 1.2], "kind": "bands", "label": "exp."}
    fig = spectrum_figure(results, SpectrumOptions(), reference=ref)
    assert "exp." in [t.get_text() for t in fig.axes[0].get_legend().get_texts()]


def test_publication_style_sets_figure_size(results):
    fig = spectrum_figure(results, SpectrumOptions(style="Single column"))
    assert tuple(fig.get_size_inches()) == pytest.approx((3.35, 2.5))


@pytest.mark.parametrize("fmt, magic", [("svg", b"<?xml"), ("pdf", b"%PDF"), ("png", b"\x89PNG")])
def test_export_formats(results, fmt, magic):
    data = figure_bytes(spectrum_figure(results, SpectrumOptions()), fmt).read()
    assert data.startswith(magic)


def test_no_intensities_is_explained(results):
    stripped = {k: v.model_copy(update={"transitions": [
        t.model_copy(update={"intensity": None}) for t in v.transitions]}) for k, v in results.items()}
    with pytest.raises(ValueError, match="intensities=True"):
        spectrum_figure(stripped, SpectrumOptions())


@pytest.mark.parametrize("path", ["runs/water", "runs/water/anharmonics/vpt2_result.json"])
def test_reproduce_script_is_valid_python(path):
    compile(reproduce_script(path, "gvpt2", 2, SpectrumOptions(log=True)), "spectrum.py", "exec")


def test_degenerate_bands_are_labelled():
    from overtone.anharmonics import VPT2Result
    from overtone.anharmonics.transitions import VPT2Transition
    import numpy as np
    bands = [VPT2Transition(quanta={i: 1}, kind="fundamental", label=f"v{i + 1}",
                            harmonic=3000.0, energy=2900.0, intensity=10.0) for i in (6, 7)]
    result = VPT2Result(X=np.zeros((8, 8)), anharm_freq=np.zeros(8), method="gvpt2",
                        transitions=bands)
    fig = spectrum_figure({"GVPT2": result}, SpectrumOptions())
    assert len(fig.axes[0].texts) == 1
