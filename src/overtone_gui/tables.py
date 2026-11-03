"""Transition tables for the viewer and for export (CSV, LaTeX)."""

from __future__ import annotations

import io
from typing import Dict, Optional

import pandas as pd

from overtone.anharmonics import VPT2Result
from overtone_gui.figures import nice_label


def transitions_frame(
    results: Dict[str, VPT2Result],
    reference: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """
    One row per band of the primary (first) result, one wavenumber column per
    method. Intensity, Fermi flag and mixing refer to the primary result.
    `reference` optionally maps band labels to experimental wavenumbers.
    """
    names = list(results)
    primary = results[names[0]]
    rows = []
    others = {
        name: {t.label: t for t in results[name].transitions or []} for name in names[1:]
    }
    for t in primary.transitions or []:
        row = {
            "Band": t.label,
            "Type": t.kind,
            "Quanta": t.total_quanta,
            "Harmonic": round(t.harmonic, 1),
            names[0]: round(t.energy, 1),
        }
        for name in names[1:]:
            other = others[name].get(t.label)
            row[name] = round(other.energy, 1) if other is not None else None
        if reference is not None:
            exp = reference.get(t.label)
            row["Exp."] = exp
            row["Δ"] = round(t.energy - exp, 1) if exp is not None else None
        row["Intensity"] = t.intensity
        row["Fermi"] = "yes" if t.resonance_affected else ""
        row["Mixing"] = (
            ", ".join(f"{k} {v:.0%}" for k, v in sorted(t.mixing.items(), key=lambda kv: -kv[1]))
            if t.mixing else ""
        )
        rows.append(row)
    return pd.DataFrame(rows)


def csv_bytes(df: pd.DataFrame) -> io.BytesIO:
    return io.BytesIO(df.to_csv(index=False).encode())


def latex_bytes(df: pd.DataFrame, method_labels: Optional[Dict[str, str]] = None) -> io.BytesIO:
    """booktabs table for a manuscript or SI; band labels as \\nu_{i}."""
    out = df.drop(columns=["Mixing"], errors="ignore").copy()
    out["Band"] = [nice_label(b) for b in out["Band"]]
    out = out.rename(columns={"Δ": r"$\Delta$", **(method_labels or {})})
    if "Intensity" in out:
        out["Intensity"] = [
            "--" if v is None or pd.isna(v) else f"{v:.3g}" for v in out["Intensity"]
        ]
    tex = out.to_latex(index=False, float_format="%.1f", na_rep="--", escape=False)
    return io.BytesIO(tex.encode())
