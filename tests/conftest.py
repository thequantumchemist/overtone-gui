"""A small finished run (GFN2-xTB water, intensities, saved results) for the GUI tests."""
import os

import pytest

# tblite on tiny molecules is faster single-threaded (as in the core test suite)
os.environ.setdefault("OMP_NUM_THREADS", "1")

tblite_ase = pytest.importorskip("tblite.ase")


@pytest.fixture(scope="session")
def water_run(tmp_path_factory):
    from ase.build import molecule
    from ase.optimize import BFGS

    from overtone import calculate_anharmonics

    def setup():
        return tblite_ase.TBLite(method="GFN2-xTB", verbosity=0, accuracy=0.01)

    atoms = molecule("H2O")
    atoms.calc = setup()
    BFGS(atoms, logfile=None).run(fmax=1e-4)
    directory = tmp_path_factory.mktemp("water")
    calculate_anharmonics(atoms, setup, directory, derivative_source="forces",
                          intensities=True, max_quanta=2, save_results=True)
    return directory
