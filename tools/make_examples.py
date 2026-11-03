"""
Recompute the example runs bundled in src/overtone_gui/examples.

    pip install -e ".[student]"
    python tools/make_examples.py

Each example is a GFN2-xTB run (geometry optimised to fmax < 1e-4 eV/A,
analytic forces, IR intensities, GVPT2, up to 3 quanta) reduced to the six
JSON files the viewer needs.
"""

import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")

from ase.build import molecule  # noqa: E402
from ase.optimize import BFGS  # noqa: E402
from overtone import calculate_anharmonics  # noqa: E402
from tblite.ase import TBLite  # noqa: E402

EXAMPLES = {"water": "H2O", "formaldehyde": "H2CO", "carbon-dioxide": "CO2"}
KEEP = [
    "harmonics/harmonics_result.json",
    "anharmonics/vpt2_result.json",
    "anharmonics/vpt2_config.json",
    "anharmonics/derivatives_config.json",
    "anharmonics/derivatives_result.json",
    "anharmonics/dipole_derivatives.json",
]
TARGET = Path(__file__).resolve().parents[1] / "src" / "overtone_gui" / "examples"


def gfn2():
    return TBLite(method="GFN2-xTB", verbosity=0, accuracy=0.01)


for name, formula in EXAMPLES.items():
    atoms = molecule(formula)
    atoms.calc = gfn2()
    BFGS(atoms, logfile=None).run(fmax=1e-4)
    with tempfile.TemporaryDirectory() as tmp:
        calculate_anharmonics(atoms, gfn2, tmp, derivative_source="forces", intensities=True,
                              method="gvpt2", max_quanta=3, save_results=True)
        out = TARGET / name
        shutil.rmtree(out, ignore_errors=True)
        for rel in KEEP:
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(Path(tmp) / rel, out / rel)
    print(f"{name}: written to {out}")
