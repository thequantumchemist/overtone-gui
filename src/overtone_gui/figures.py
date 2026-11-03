"""
Spectrum figures for the viewer. The figure on screen is the figure that is
exported, so these functions use matplotlib only (no Panel).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
from matplotlib.figure import Figure

from overtone.anharmonics import VPT2Result
from overtone.spectrum import DEFAULT_FWHM, broaden, broaden_transitions

PRIMARY = "#1F5FAD"
COMPARE = [("#B5530A", "--"), ("#0F6E5C", "-."), ("#5B3FA8", ":")]
REFERENCE = "#8A96A3"

#: figure presets: size in inches and base font size
STYLES: Dict[str, dict] = {
    "Screen": {"size": (9.0, 4.2), "font": 10},
    "Single column": {"size": (3.35, 2.5), "font": 7.5},
    "Double column": {"size": (7.0, 3.0), "font": 8},
    "Slide": {"size": (10.0, 5.0), "font": 14},
}

UNITS = {"cm-1": "Wavenumber / cm$^{-1}$", "nm": "Wavelength / nm", "um": "Wavelength / µm"}


@dataclass
class SpectrumOptions:
    shape: str = "lorentzian"
    fwhm: Optional[float] = None
    kinds: Optional[Sequence[str]] = None
    xmin: Optional[float] = None
    xmax: Optional[float] = None
    log: bool = False
    unit: str = "cm-1"
    invert_x: bool = True
    sticks: bool = True
    peak_labels: bool = True
    show_harmonic: bool = False
    style: str = "Screen"
    highlight: Optional[float] = None
    labels: Dict[str, str] = field(default_factory=dict)


def nice_label(label: str, math: bool = True) -> str:
    """'v7+2v9' -> '$\\nu_{7}+2\\nu_{9}$' (matplotlib mathtext / LaTeX)."""
    body = re.sub(r"v(\d+)", r"\\nu_{\1}", label)
    if not math:
        return body
    return "$" + body.replace("+", "{+}") + "$"  # no binary-operator spacing


def _to_unit(x: np.ndarray, unit: str) -> np.ndarray:
    x = np.asarray(x, float)
    if unit == "nm":
        return 1e7 / x
    if unit == "um":
        return 1e4 / x
    return x


def _grid(results: Sequence[VPT2Result], opts: SpectrumOptions, fwhm: float) -> np.ndarray:
    bands = [
        t for r in results for t in r.transitions or []
        if t.intensity is not None and (opts.kinds is None or t.kind in opts.kinds)
    ]
    strongest = max((t.intensity for t in bands), default=0.0)
    # the automatic window ignores bands far below anything visible (exact
    # zeros and numerical noise of symmetry-forbidden bands)
    pos = [t.energy for t in bands if t.intensity > strongest * 1e-6]
    if not pos:
        raise ValueError(
            "No transitions with intensities. Run with intensities=True to plot spectra."
        )
    lo = opts.xmin if opts.xmin is not None else max(min(pos) - 6 * fwhm, 1.0)
    hi = opts.xmax if opts.xmax is not None else max(pos) + 6 * fwhm
    resolution = max(0.25, (hi - lo) / 8000)
    return np.arange(lo, hi + resolution, resolution)


def spectrum_figure(
    results: Dict[str, VPT2Result],
    opts: SpectrumOptions,
    reference: Optional[dict] = None,
) -> Figure:
    """
    Broadened spectra of one or more VPT2 results. The first entry is the
    primary result (solid line, sticks and peak labels); the others are drawn
    for comparison.
    """
    style = STYLES.get(opts.style, STYLES["Screen"])
    font = style["font"]
    fig = Figure(figsize=style["size"], layout="constrained")
    ax = fig.add_subplot()
    shape = opts.shape.lower()
    fwhm = opts.fwhm if opts.fwhm else DEFAULT_FWHM[shape]
    x = _grid(list(results.values()), opts, fwhm)
    xp = _to_unit(x, opts.unit)

    curves = {}
    for name, res in results.items():
        _, y = broaden_transitions(res.transitions, x=x, shape=shape, fwhm=fwhm, kinds=opts.kinds)
        curves[name] = y
    names = list(results)
    primary = names[0]
    top = max(float(curves[primary].max()), 1e-30)
    ymax = max(float(c.max()) for c in curves.values())
    lw = max(0.6, font / 10)  # thinner lines for small print figures

    if reference is not None:
        if reference["kind"] == "bands":
            _, yr = broaden(reference["x"], reference["y"], x=x, shape=shape, fwhm=fwhm)
            xr = xp
        else:
            order = np.argsort(reference["x"])
            xr = _to_unit(np.asarray(reference["x"])[order], opts.unit)
            yr = np.asarray(reference["y"], float)[order]
        if yr.max() > 0:
            yr = yr / yr.max() * top  # scaled to the primary curve
        ax.plot(xr, yr, color=REFERENCE, lw=2.4 * lw, alpha=0.75, zorder=1,
                label=reference.get("label", "experiment"))

    if opts.show_harmonic:
        fund = [t for t in results[primary].transitions
                if t.kind == "fundamental" and t.intensity is not None]
        if fund:
            _, yh = broaden_transitions(fund, x=x, shape=shape, fwhm=fwhm, use_harmonic=True)
            ax.plot(xp, yh, color="0.65", lw=lw, zorder=2, label="harmonic")

    for i, name in enumerate(names[1:]):
        color, ls = COMPARE[i % len(COMPARE)]
        ax.plot(xp, curves[name], color=color, ls=ls, lw=1.3 * lw, zorder=3,
                label=opts.labels.get(name, name))
    primary_line, = ax.plot(xp, curves[primary], color=PRIMARY, lw=1.6 * lw, zorder=4,
                            label=opts.labels.get(primary, primary))

    in_window = [
        t for t in results[primary].transitions
        if t.intensity is not None and x[0] <= t.energy <= x[-1]
        and (opts.kinds is None or t.kind in opts.kinds)
    ]
    floor = top * 1e-5 if opts.log else 0.0
    if opts.sticks and in_window:
        imax = max(t.intensity for t in in_window)
        for t in in_window:
            h = max(t.intensity / imax * top, floor * 1.01) if imax > 0 else floor
            ax.vlines(_to_unit(t.energy, opts.unit), floor, h, color=PRIMARY, lw=0.8 * lw,
                      alpha=0.5, ls=":" if t.resonance_affected else "-", zorder=2)

    if opts.highlight is not None:
        ax.axvline(_to_unit(opts.highlight, opts.unit), color=PRIMARY, lw=0.9, ls=(0, (2, 3)))

    if opts.log:
        ax.set_yscale("log")
        ax.set_ylim(top * 1e-5, ymax * 3)
    else:
        ax.set_ylim(0, ymax * 1.12)
    xlo, xhi = xp.min(), xp.max()
    if opts.unit == "cm-1" and opts.invert_x:
        ax.set_xlim(xhi, xlo)
    else:
        ax.set_xlim(xlo, xhi)
    if opts.peak_labels and in_window:
        _label_peaks(ax, in_window, x, curves[primary], top, opts, shape, fwhm, font)
    ax.set_xlabel(UNITS[opts.unit], fontsize=font)
    ax.set_ylabel("Intensity / km mol$^{-1}$ (cm$^{-1}$)$^{-1}$", fontsize=font)
    ax.tick_params(labelsize=font * 0.9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    handles, texts = ax.get_legend_handles_labels()
    order = [handles.index(primary_line)] + [i for i in range(len(handles))
                                             if handles[i] is not primary_line]
    ax.legend([handles[i] for i in order], [texts[i] for i in order],
              frameon=False, fontsize=font * 0.85)
    return fig


def _peak_height(intensity: float, shape: str, fwhm: float) -> float:
    """Height of a single area-normalised band of this intensity."""
    if shape == "gaussian":
        s = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
        return intensity / (s * np.sqrt(2.0 * np.pi))
    return intensity * 2.0 / (np.pi * fwhm)


def _label_peaks(ax, transitions, x, y, top, opts, shape, fwhm, font, max_labels=20):
    """
    Label the strongest bands that are visible as peaks of their own, skipping
    labels that would overlap one already placed.
    """
    threshold = top * (1e-4 if opts.log else 2e-2)
    to_axes = ax.transAxes.inverted()
    placed = []
    for t in sorted(transitions, key=lambda t: -t.intensity):
        if len(placed) >= max_labels:
            break
        yv = float(np.interp(t.energy, x, y))
        # degenerate or nearly coincident bands form one peak together
        together = sum(u.intensity for u in transitions if abs(u.energy - t.energy) < 0.25 * fwhm)
        if yv < threshold or _peak_height(together, shape, fwhm) < 0.5 * yv:
            continue  # too weak, or hidden under a stronger neighbour
        xv = float(_to_unit(t.energy, opts.unit))
        ax_x, ax_y = to_axes.transform(ax.transData.transform((xv, yv)))
        if any(abs(ax_x - px) < 0.06 and abs(ax_y - py) < 0.08 for px, py in placed):
            continue
        placed.append((ax_x, ax_y))
        ax.annotate(nice_label(t.label), (xv, yv), xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=font * 0.8, color="#16202A")


def figure_bytes(fig: Figure, fmt: str) -> io.BytesIO:
    """Serialise a figure for download ('svg', 'pdf' or 'png' at 600 dpi)."""
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, dpi=600 if fmt == "png" else None)
    buf.seek(0)
    return buf


def reproduce_script(run_path, method: str, max_quanta: int, opts: SpectrumOptions) -> str:
    """A short Python script that redraws the primary spectrum with OVERTONE's API."""
    fwhm = opts.fwhm if opts.fwhm else DEFAULT_FWHM[opts.shape]
    kinds = f"{list(opts.kinds)!r}" if opts.kinds else "None"
    unit = "nm" if opts.unit == "nm" else "cm-1"
    if str(run_path).endswith(".json"):  # a bare result file: stored method only
        load = f"from overtone import VPT2Result\n\nresult = VPT2Result.load({str(run_path)!r})"
    else:
        load = (f"from overtone import recompute_vpt2\n\nresult = recompute_vpt2("
                f"{str(run_path)!r}, method={method!r}, max_quanta={max_quanta})")
    return f'''"""Spectrum exported from the OVERTONE viewer."""
import matplotlib.pyplot as plt
{load}
ax = result.plot_spectrum(
    shape={opts.shape!r},
    fwhm={fwhm},
    kinds={kinds},
    xmin={opts.xmin!r},
    xmax={opts.xmax!r},
    log={opts.log},
    x_unit={unit!r},
    show_harmonic={opts.show_harmonic},
)
plt.tight_layout()
plt.savefig("spectrum.pdf")
'''
