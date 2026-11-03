"""
Everything the viewer needs from a finished run directory, without Panel.

A run directory is the `directory` given to calculate_anharmonics with
save_results=True:

    run/
      harmonics/harmonics_result.json
      anharmonics/derivatives_config.json   (equilibrium atoms, modes, masses)
      anharmonics/derivatives_result.json   (needed to recompute VPT2)
      anharmonics/dipole_derivatives.json   (only with intensities=True)
      anharmonics/vpt2_config.json
      anharmonics/vpt2_result.json

A bare vpt2_result.json can be opened too; the viewer then shows the spectrum
and table of the stored method only (no recomputation, no mode animation).
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from ase import Atoms
from ase.io import write

from overtone.anharmonics import AnharmonicDerivativesConfig, VPT2Config, VPT2Result
from overtone.anharmonics.transitions import VPT2Transition
from overtone.workflow import recompute_vpt2

#: VPT2 variants offered in the viewer, in display order
METHODS: Dict[str, str] = {
    "gvpt2": "GVPT2",
    "standard": "Standard VPT2",
    "deperturbed": "Deperturbed VPT2",
    "dcpt2": "DCPT2",
}


class RunDirectoryError(ValueError):
    """The path is not a run directory the viewer can open."""


#: finished GFN2-xTB runs shipped with the package (see tools/make_examples.py)
EXAMPLES_DIR = Path(__file__).parent / "examples"
EXAMPLES: Dict[str, str] = {
    "water": "Water (H₂O)",
    "formaldehyde": "Formaldehyde (H₂CO)",
    "carbon-dioxide": "Carbon dioxide (CO₂)",
}


def example_path(name: str) -> Path:
    """Run directory of a bundled example."""
    if name not in EXAMPLES:
        raise RunDirectoryError(
            f"Unknown example '{name}'. Available: {', '.join(EXAMPLES)}."
        )
    return EXAMPLES_DIR / name


def example_name(path) -> Optional[str]:
    """Name of the bundled example at `path`, or None for the user's own runs."""
    try:
        rel = Path(path).resolve().relative_to(EXAMPLES_DIR.resolve())
    except ValueError:
        return None
    return rel.parts[0] if rel.parts and rel.parts[0] in EXAMPLES else None


@dataclass
class RunData:
    """
    A loaded run: the stored VPT2 result plus what is needed to recompute it
    with another method and to animate the normal modes.
    """

    path: Path
    result: VPT2Result
    vpt2_config: Optional[VPT2Config] = None
    derivatives_config: Optional[AnharmonicDerivativesConfig] = None
    _cache: Dict[Tuple[str, int], VPT2Result] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path) -> "RunData":
        path = Path(path).expanduser().resolve()
        if path.is_file() and path.suffix == ".json":
            return cls(path=path, result=VPT2Result.load(path))
        anh = path / "anharmonics"
        result_file = anh / "vpt2_result.json"
        if not path.is_dir():
            raise RunDirectoryError(f"{path} does not exist or is not a directory.")
        if not result_file.exists():
            raise RunDirectoryError(
                f"No anharmonics/vpt2_result.json in {path}. The viewer needs a run "
                "computed with calculate_anharmonics(..., save_results=True)."
            )
        result = VPT2Result.load(result_file)
        vpt2_config = (
            VPT2Config.load(anh / "vpt2_config.json")
            if (anh / "vpt2_config.json").exists() else None
        )
        derivatives_config = (
            AnharmonicDerivativesConfig.load(anh / "derivatives_config.json")
            if (anh / "derivatives_config.json").exists() else None
        )
        run = cls(path=path, result=result, vpt2_config=vpt2_config,
                  derivatives_config=derivatives_config)
        run._cache[(result.method, run.max_quanta)] = result
        return run

    # ------------------------------------------------------------------
    # metadata
    # ------------------------------------------------------------------
    @property
    def example(self) -> Optional[str]:
        return example_name(self.path)

    @property
    def display_path(self) -> str:
        """What the header shows: the path, or 'example: <name>'."""
        return f"example: {self.example}" if self.example else str(self.path)

    @property
    def name(self) -> str:
        return self.path.stem if self.path.is_file() else self.path.name

    @property
    def method(self) -> str:
        return self.result.method

    @property
    def max_quanta(self) -> int:
        if self.vpt2_config is not None:
            return self.vpt2_config.max_quanta
        return max((t.total_quanta for t in self.result.transitions or []), default=1)

    @property
    def can_recompute(self) -> bool:
        anh = self.path / "anharmonics"
        return (
            self.path.is_dir()
            and (anh / "vpt2_config.json").exists()
            and (anh / "derivatives_result.json").exists()
        )

    @property
    def atoms(self) -> Optional[Atoms]:
        return None if self.derivatives_config is None else self.derivatives_config.atoms

    @property
    def formula(self) -> str:
        if self.atoms is not None:
            return self.atoms.get_chemical_formula(mode="hill")
        return ""

    @property
    def active_modes(self) -> List[int]:
        if self.derivatives_config is not None:
            return list(self.derivatives_config.active_modes)
        modes = sorted({m for t in self.result.transitions or [] for m in t.quanta})
        return modes

    @property
    def has_intensities(self) -> bool:
        return self.result.has_intensities

    def describe(self) -> str:
        """One line for the header, e.g. 'H2O, 3 active modes, intensities'."""
        parts = [self.formula] if self.formula else []
        parts.append(f"{len(self.active_modes)} active modes")
        parts.append("IR intensities" if self.has_intensities else "no intensities")
        return ", ".join(parts)

    # ------------------------------------------------------------------
    # VPT2 variants (only the cheap VPT2 step is repeated)
    # ------------------------------------------------------------------
    def result_for(self, method: str, max_quanta: Optional[int] = None) -> VPT2Result:
        max_quanta = max_quanta or self.max_quanta
        key = (method, max_quanta)
        if key not in self._cache:
            if not self.can_recompute:
                raise RunDirectoryError(
                    "Recomputing needs the full run directory "
                    "(vpt2_config.json and derivatives_result.json)."
                )
            self._cache[key] = recompute_vpt2(
                self.path, method=method, max_quanta=max_quanta
            )
        return self._cache[key]

    # ------------------------------------------------------------------
    # normal modes
    # ------------------------------------------------------------------
    def harmonic_frequency(self, mode: int) -> float:
        for t in self.result.transitions or []:
            if t.kind == "fundamental" and mode in t.quanta:
                return t.harmonic
        return float("nan")

    def mode_displacement(self, mode: int) -> np.ndarray:
        """
        Cartesian displacement (n_atoms, 3) of a normal mode, zero for
        constrained atoms, scaled so that the largest atomic displacement is 1.
        """
        cfg = self.derivatives_config
        if cfg is None:
            raise RunDirectoryError("Mode animation needs anharmonics/derivatives_config.json.")
        # cfg.masses holds sqrt(mass) per Cartesian coordinate, so this undoes
        # the mass weighting of the eigenvector
        vec = np.asarray(cfg.modes)[:, mode] / np.asarray(cfg.masses).ravel()
        vec = vec.reshape(-1, 3)
        disp = np.zeros((len(cfg.atoms), 3))
        disp[cfg.unconstrained_index] = vec
        largest = np.linalg.norm(disp, axis=1).max()
        return disp / largest if largest > 0 else disp

    def view_rotation(self) -> np.ndarray:
        """Rotation for displaying this run's molecule face on (see view_rotation)."""
        return view_rotation(self.atoms.positions)

    def mode_frames(self, mode: int, amplitude: float = 0.4, n_frames: int = 24,
                    rotation: Optional[np.ndarray] = None) -> List[Atoms]:
        """
        One period of the mode; amplitude = largest atomic displacement
        (Angstrom). `rotation` (from view_rotation) reorients the frames for
        display; exports keep the original coordinates.
        """
        disp = self.mode_displacement(mode)
        base = self.atoms.copy()
        base.calc = None
        if rotation is not None:
            base.positions = base.positions @ rotation
            disp = disp @ rotation
        frames = []
        for k in range(n_frames):
            frame = base.copy()
            frame.positions += amplitude * np.sin(2 * np.pi * k / n_frames) * disp
            frames.append(frame)
        return frames

    def mode_xyz(self, mode: int, amplitude: float = 0.4, n_frames: int = 24,
                 rotation: Optional[np.ndarray] = None) -> str:
        buf = io.StringIO()
        write(buf, self.mode_frames(mode, amplitude, n_frames, rotation), format="xyz")
        return buf.getvalue()

    def anharmonic_constants(self, mode: int, method: Optional[str] = None) -> Dict[int, float]:
        """Row X[mode, j] for the active modes j (cm^-1)."""
        X = self.result_for(method or self.method).X
        return {j: float(X[mode, j]) for j in self.active_modes}

    def resonances(self, mode: int, method: Optional[str] = None) -> List[VPT2Transition]:
        """Resonance-affected transitions in which this mode is excited."""
        res = self.result_for(method or self.method)
        return [t for t in res.transitions or [] if t.resonance_affected and mode in t.quanta]


def view_rotation(positions: np.ndarray) -> np.ndarray:
    """
    Rotation (3x3, applied as positions @ R) into the principal axes of the
    geometry, largest extent along x and smallest along z, so that a viewer
    looking down z sees a planar molecule face on.
    """
    pos = np.asarray(positions, float)
    pos = pos - pos.mean(axis=0)
    _, vecs = np.linalg.eigh(pos.T @ pos)  # ascending variance
    rot = vecs[:, ::-1].copy()
    if np.linalg.det(rot) < 0:
        rot[:, 2] *= -1
    return rot


def mode_label(mode: int) -> str:
    """Mode label as in OVERTONE's tables (mode index + 1)."""
    return f"v{mode + 1}"


# ----------------------------------------------------------------------
# experimental reference
# ----------------------------------------------------------------------
def read_reference(data: bytes, name: str = "reference") -> dict:
    """
    Experimental reference from a two-column text/CSV file
    (wavenumber in cm^-1, intensity). Lines starting with '#' and a header
    line are skipped. Up to 200 rows are treated as band positions with
    intensities (broadened like the calculation), longer files as a
    measured spectrum drawn as is.
    """
    text = data.decode("utf-8", errors="replace")
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cells = line.replace(";", ",").replace("\t", ",").replace(" ", ",").split(",")
        cells = [c for c in cells if c]
        try:
            rows.append((float(cells[0]), float(cells[1])))
        except (ValueError, IndexError):
            continue  # header or malformed line
    if not rows:
        raise ValueError(f"No numeric two-column data found in {name}.")
    arr = np.array(rows)
    kind = "bands" if len(arr) <= 200 else "spectrum"
    return {"x": arr[:, 0], "y": arr[:, 1], "kind": kind, "label": Path(name).stem}


# ----------------------------------------------------------------------
# recent runs
# ----------------------------------------------------------------------
def _history_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "overtone" / "recent_runs.json"


def recent_runs(limit: int = 8) -> List[Path]:
    try:
        paths = json.loads(_history_file().read_text())
    except (OSError, ValueError):
        return []
    return [Path(p) for p in paths if Path(p).exists()][:limit]


def remember_run(path: Path, limit: int = 20) -> None:
    path = str(Path(path).resolve())
    paths = [str(p) for p in recent_runs(limit) if str(p) != path]
    file = _history_file()
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps([path] + paths[: limit - 1], indent=1))
    except OSError:
        pass  # history is a convenience; never fail the viewer over it
