"""
Student mode: pick a small molecule, compute its anharmonic spectrum with
GFN2-xTB step by step, then open the result in the viewer.

    overtone-gui student

The calculation runs in a background thread. A ProgressEngine (a SerialEngine
that counts single points) reports progress and allows cancelling between two
single points; the session polls the shared Progress object and updates the
page, so widgets are only touched from the session's own thread.
"""

from __future__ import annotations

import html
import io
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import panel as pn
from ase import Atoms
from ase.collections import g2
from ase.io import read, write
from ase.optimize import BFGS

from overtone.engines import SerialEngine
from overtone_gui.modes import iframe, mode_page
from overtone_gui.run_data import METHODS, view_rotation
from overtone.workflow import calculate_anharmonics, estimate_cost

MAX_ATOMS = 8
SUGGESTED = ["H2O", "CO2", "NH3", "CH4", "H2CO", "HCN"]
FMAX = 1e-4  # eV/Angstrom, tight enough for finite differences

#: (key, title, what happens), in the order they run
STEPS = [
    ("optimize", "Geometry optimization",
     "Finds the minimum-energy structure. Vibrations are only defined around a minimum."),
    ("hessian", "Harmonic analysis",
     "The Hessian gives normal modes and harmonic frequencies: the parabola approximation."),
    ("qff", "Quartic force field",
     "Displaces the atoms along the normal modes to measure how the potential deviates "
     "from a parabola."),
    ("vpt2", "VPT2 and spectrum",
     "Perturbation theory turns the force field into anharmonic fundamentals, overtones "
     "and combination bands."),
]


def closed_shell(atoms: Atoms) -> bool:
    """Even electron count for a neutral molecule (GFN2-xTB runs closed shell here)."""
    return int(atoms.numbers.sum()) % 2 == 0


def molecule_choices() -> List[str]:
    """Closed-shell molecules from ASE's G2 collection with 2 to MAX_ATOMS atoms."""
    return sorted((n for n in g2.names
                   if 2 <= len(g2[n]) <= MAX_ATOMS and closed_shell(g2[n])), key=str.lower)


def read_xyz(data: bytes, filename: str = "molecule.xyz") -> Atoms:
    """First structure of an uploaded .xyz file, checked for student mode."""
    try:
        atoms = read(io.StringIO(data.decode("utf-8", errors="replace")), format="xyz", index=0)
    except Exception as err:
        raise ValueError(f"{filename} could not be read as an .xyz file ({err}).") from err
    if len(atoms) < 2:
        raise ValueError(f"{filename} contains fewer than two atoms.")
    if not closed_shell(atoms):
        raise ValueError(
            f"{filename} has an odd number of electrons (a radical). Student mode computes "
            "neutral closed-shell molecules only."
        )
    if len(atoms) > MAX_ATOMS:
        raise ValueError(
            f"{filename} has {len(atoms)} atoms. Student mode allows up to {MAX_ATOMS}, "
            "so the calculation finishes in a few minutes."
        )
    return atoms


def gfn2_xtb():
    """Fresh GFN2-xTB calculator, converged tightly as finite differences need."""
    from tblite.ase import TBLite
    return TBLite(method="GFN2-xTB", verbosity=0, accuracy=0.01)


def describe_duration(seconds: float) -> str:
    if seconds < 45:
        return "under a minute"
    minutes = max(1, round(seconds / 60))
    return f"about {minutes} minute{'s' if minutes > 1 else ''}"


# ======================================================================
# shared state between the worker thread and the page
# ======================================================================
class Cancelled(Exception):
    """The student cancelled the calculation."""


@dataclass
class Progress:
    states: Dict[str, str] = field(default_factory=lambda: {k: "pending" for k, *_ in STEPS})
    step: Optional[str] = None
    done: int = 0
    total: int = 0
    lines: List[str] = field(default_factory=list)
    error: Optional[str] = None
    cancelled: bool = False
    finished: bool = False
    result_dir: Optional[Path] = None
    started: float = field(default_factory=time.time)
    cancel: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def start_step(self, key: str, total: int = 0):
        with self._lock:
            self.step, self.done, self.total = key, 0, total
            self.states[key] = "running"

    def add_work(self, n: int):
        with self._lock:
            self.total += n

    def advance(self):
        with self._lock:
            self.done += 1

    def finish_step(self, key: str):
        with self._lock:
            self.states[key] = "done"
            self.done = self.total

    def log(self, text: str):
        with self._lock:
            self.lines.append(text)

    def fail(self, text: str, cancelled: bool = False):
        with self._lock:
            if self.step is not None and self.states.get(self.step) == "running":
                self.states[self.step] = "cancelled" if cancelled else "failed"
            self.error, self.cancelled = text, cancelled

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "states": dict(self.states), "step": self.step, "done": self.done,
                "total": self.total, "lines": list(self.lines), "error": self.error,
                "cancelled": self.cancelled, "finished": self.finished,
                "result_dir": self.result_dir, "elapsed": time.time() - self.started,
            }


class ProgressEngine(SerialEngine):
    """SerialEngine that reports each single point and can be cancelled."""

    def __init__(self, progress: Progress):
        super().__init__(restart=True)
        self.progress = progress

    def calculate_trajectory(self, trajectory, setup_calculator, properties=("energy",),
                             output_directory=None, **kwargs):
        stage = Path(output_directory).name if output_directory is not None else ""
        if stage == "harmonics":
            self.progress.start_step("hessian", len(trajectory))
        elif stage == "anharmonics":
            self.progress.start_step("qff", len(trajectory))
        else:  # e.g. dipole_extra, part of the last step
            self.progress.add_work(len(trajectory))

        def counted():
            if self.progress.cancel.is_set():
                raise Cancelled()
            self.progress.advance()
            return setup_calculator()

        result = super().calculate_trajectory(trajectory, counted, properties=properties,
                                              output_directory=output_directory, **kwargs)
        if stage == "harmonics":
            self.progress.finish_step("hessian")
            self.progress.log(f"Harmonic analysis: {len(trajectory)} single points.")
        elif stage == "anharmonics":
            self.progress.finish_step("qff")
            self.progress.log(f"Quartic force field: {len(trajectory)} single points "
                              "(analytic forces, 5-point stencil).")
            self.progress.start_step("vpt2")
        return result


@dataclass
class Settings:
    method: str = "gvpt2"
    max_quanta: int = 2
    intensities: bool = True


def run_calculation(atoms: Atoms, name: str, settings: Settings, runs_dir: Path,
                    progress: Progress, calculator: Callable = gfn2_xtb) -> None:
    """The whole student workflow; reports to `progress`, never raises."""
    atoms = atoms.copy()
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "molecule"
    directory = Path(runs_dir).expanduser() / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        progress.start_step("optimize")
        atoms.calc = calculator()
        opt = BFGS(atoms, logfile=None)
        steps = 0
        for _ in opt.irun(fmax=FMAX, steps=500):
            if progress.cancel.is_set():
                raise Cancelled()
            steps += 1
            progress.advance()
        fmax = float(np.linalg.norm(atoms.get_forces(), axis=1).max())
        if fmax > FMAX:
            raise RuntimeError(f"The optimization did not converge (largest force "
                               f"{fmax:.1e} eV/Å after {steps} steps).")
        progress.finish_step("optimize")
        progress.log(f"Optimized in {steps} steps (largest force below {FMAX:g} eV/Å).")
        directory.mkdir(parents=True, exist_ok=True)
        write(directory / "optimized.xyz", atoms)

        result = calculate_anharmonics(
            atoms, calculator, directory, engine=ProgressEngine(progress),
            derivative_source="forces", intensities=settings.intensities,
            method=settings.method, max_quanta=settings.max_quanta, save_results=True,
        )
        progress.finish_step("vpt2")
        n_fund = sum(t.kind == "fundamental" for t in result.transitions or [])
        n_other = len(result.transitions or []) - n_fund
        progress.log(f"{METHODS.get(settings.method, settings.method)}: {n_fund} fundamentals, "
                     f"{n_other} overtones and combination bands.")
        progress.log(f"Saved in {directory}")
        progress.result_dir = directory
        progress.finished = True
    except Cancelled:
        progress.fail("Calculation cancelled.", cancelled=True)
    except Exception as err:  # shown to the student instead of a traceback
        progress.fail(str(err) or type(err).__name__)


# ======================================================================
# page
# ======================================================================
CHIP = """
.bk-btn { border: 1px solid #C9D0D8 !important; border-radius: 999px !important;
          background: #fff !important; }
.bk-btn:hover { border-color: #1F5FAD !important; background: #E8F0FA !important; }
"""

CARD = {"background": "#fff", "border": "1px solid #DDE2E8", "border-radius": "10px",
        "padding": "8px 14px"}

_ICONS = {
    "done": '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" '
            'stroke="#0F6E5C" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="12" cy="12" r="10"/><polyline points="7.5 12.5 10.5 15.5 16.5 9"/></svg>',
    "running": '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" '
               'stroke="#1F5FAD" stroke-width="2.5"><circle cx="12" cy="12" r="10"/>'
               '<circle cx="12" cy="12" r="4" fill="#1F5FAD"/></svg>',
    "pending": '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" '
               'stroke="#A7B1BC" stroke-width="2.5"><circle cx="12" cy="12" r="10"/></svg>',
    "failed": '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" '
              'stroke="#B42318" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" '
              'r="10"/><line x1="8.5" y1="8.5" x2="15.5" y2="15.5"/><line x1="15.5" y1="8.5" '
              'x2="8.5" y2="15.5"/></svg>',
}
_ICONS["cancelled"] = _ICONS["failed"]
_STATE_TEXT = {"done": "done", "running": "running", "pending": "", "failed": "failed",
               "cancelled": "cancelled"}


def steps_html(states: Dict[str, str], step: Optional[str], done: int, total: int) -> str:
    rows = []
    for key, title, text in STEPS:
        state = states.get(key, "pending")
        status = _STATE_TEXT[state]
        if state == "running" and total:
            status = f"running, {done} of {total} single points"
        elif state == "running" and key == "optimize" and done:
            status = f"running, step {done}"
        colour = {"done": "#0F6E5C", "running": "#1F5FAD", "failed": "#B42318",
                  "cancelled": "#B42318"}.get(state, "#55606C")
        rows.append(
            f'<li style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #EEF1F4">'
            f'<span style="flex:none">{_ICONS[state]}</span><div>'
            f'<div style="font-weight:600">{title}'
            + (f' <span style="font-weight:400;color:{colour}">· {status}</span>' if status else "")
            + f'</div><div style="font-size:13px;color:#55606C">{text}</div></div></li>'
        )
    return f'<ol style="list-style:none;margin:0;padding:0">{"".join(rows)}</ol>'


class StudentView:
    """Molecule, settings and a live view of the running calculation."""

    def __init__(self, runs_dir: Path, on_open: Callable[[Path], None],
                 calculator: Callable = gfn2_xtb):
        self.runs_dir = Path(runs_dir).expanduser()
        self.on_open = on_open
        self.calculator = calculator
        self.progress: Optional[Progress] = None
        self.thread: Optional[threading.Thread] = None
        self._poll = None
        self._uploaded: Optional[Atoms] = None
        self._uploaded_name = ""
        self._timing: Dict[str, float] = {}

        self.name = pn.widgets.AutocompleteInput(
            label="Name or formula", options=molecule_choices(), value="H2O",
            case_sensitive=False, restrict=True, min_characters=1, search_strategy="includes",
            sizing_mode="stretch_width",
        )
        self.chips = pn.Row(*[self._chip(n) for n in SUGGESTED], styles={"flex-wrap": "wrap"})
        self.upload = pn.widgets.FileInput(accept=".xyz", multiple=False)
        self.molecule_note = pn.pane.HTML("")
        self.preview = pn.pane.HTML("", sizing_mode="stretch_width", height=230)
        self.method = pn.widgets.Select(
            label="VPT2 method", value="gvpt2",
            options={("GVPT2 (recommended)" if k == "gvpt2" else v): k for k, v in METHODS.items()},
        )
        self.max_quanta = pn.widgets.Select(
            label="Highest overtone",
            options={"Fundamentals only": 1, "2 quanta": 2, "3 quanta": 3}, value=2,
        )
        self.intensities = pn.widgets.Checkbox(label="IR intensities (needed for the spectrum)",
                                               value=True)
        self.cost = pn.pane.HTML("")
        self.run_button = pn.widgets.Button(label="Run calculation", color="primary",
                                            height=48, sizing_mode="stretch_width")
        self.cancel_button = pn.widgets.Button(label="Cancel", color="light", visible=False)
        self.open_button = pn.widgets.Button(label="Open results", color="primary",
                                             visible=False)
        self.status_title = pn.pane.HTML("<h3 style='margin:4px 0'>Ready</h3>")
        self.steps = pn.pane.HTML(steps_html({k: "pending" for k, *_ in STEPS}, None, 0, 0),
                                  sizing_mode="stretch_width")
        self.bar = pn.indicators.Progress(value=0, max=100, active=False, bar_color="primary",
                                          sizing_mode="stretch_width", height=10)
        self.log = pn.pane.HTML("", sizing_mode="stretch_width")
        self.message = pn.pane.Alert("", alert_type="danger", visible=False)

        self.name.param.watch(lambda e: self._molecule_changed(), "value")
        self.name.param.watch(self._typed, "value_input")
        self.upload.param.watch(self._uploaded_file, "value")
        for w in (self.max_quanta, self.intensities):
            w.param.watch(lambda e: self._update_cost(), "value")
        self.run_button.on_click(lambda e: self.start())
        self.cancel_button.on_click(lambda e: self.cancel())
        self.open_button.on_click(lambda e: self.on_open(self.progress.result_dir))

        self.layout = self._layout()
        self._molecule_changed()

    # ------------------------------------------------------------------
    def _chip(self, name):
        b = pn.widgets.Button(label=name, color="light", width=76, stylesheets=[CHIP])
        b.on_click(lambda e: self._pick(name))
        return b

    def _pick(self, name):
        self._uploaded = None
        self.name.value = name

    def _layout(self):
        def numbered(n, title, *objects):
            head = pn.pane.HTML(
                f'<div style="display:flex;align-items:center;gap:10px">'
                f'<span style="width:28px;height:28px;border-radius:999px;background:#1F5FAD;'
                f'color:#fff;display:flex;align-items:center;justify-content:center;'
                f'font-weight:600">{n}</span><h3 style="margin:0">{title}</h3></div>')
            return pn.Column(head, *objects, styles=CARD, sizing_mode="stretch_width")

        setup = pn.Column(
            numbered(1, "Choose a molecule", self.name, self.chips,
                     pn.Row(pn.pane.HTML("<span style='color:#55606C'>or upload</span>",
                                         margin=(14, 6)), self.upload),
                     self.molecule_note, self.preview),
            numbered(2, "Settings",
                     pn.pane.HTML('<div style="display:flex;justify-content:space-between;'
                                  'background:#EEF1F4;border-radius:6px;padding:8px 10px">'
                                  '<span>Calculator</span><span style="font-family:ui-monospace,'
                                  'monospace">GFN2-xTB</span></div>', sizing_mode="stretch_width"),
                     self.method, self.max_quanta, self.intensities, self.cost),
            self.run_button,
            width=470,
        )
        status = pn.Column(
            pn.Row(pn.pane.HTML(
                '<div style="display:flex;align-items:center;gap:10px"><span style="width:28px;'
                'height:28px;border-radius:999px;background:#1F5FAD;color:#fff;display:flex;'
                'align-items:center;justify-content:center;font-weight:600">3</span></div>'),
                self.status_title, pn.HSpacer(), self.cancel_button, self.open_button,
                sizing_mode="stretch_width"),
            self.message, self.bar, self.steps, self.log,
            styles=CARD, sizing_mode="stretch_width",
        )
        return pn.Row(setup, status, sizing_mode="stretch_width")

    # ------------------------------------------------------------------
    def current_molecule(self) -> tuple:
        if self._uploaded is not None:
            return self._uploaded.copy(), self._uploaded_name
        return g2[self.name.value].copy(), self.name.value

    def _uploaded_file(self, event):
        if not event.new:
            return
        try:
            atoms = read_xyz(event.new, self.upload.filename or "molecule.xyz")
        except ValueError as err:
            self._show_error(str(err))
            return
        self.message.visible = False
        self._uploaded = atoms
        self._uploaded_name = Path(self.upload.filename or "molecule").stem
        self._show_molecule()

    def _typed(self, event):
        text = (event.new or "").strip()
        if text and not any(text.lower() in n.lower() for n in molecule_choices()):
            self.molecule_note.object = (
                f"<p style='margin:6px 0;color:#B42318'>No molecule matches "
                f"“{html.escape(text)}”. Pick one from the list or upload an .xyz file.</p>")

    def _molecule_changed(self):
        if self.name.value in g2.names:
            self._uploaded = None
            self.message.visible = False
            self._show_molecule()

    def _show_molecule(self):
        atoms, name = self.current_molecule()
        self.molecule_note.object = (
            f"<p style='margin:6px 0'><strong>{html.escape(name)}</strong>, "
            f"{atoms.get_chemical_formula(mode='hill')}, {len(atoms)} atoms</p>")
        shown = atoms.copy()
        shown.positions = shown.positions @ view_rotation(shown.positions)
        buf = io.StringIO()
        write(buf, shown, format="xyz")
        page = mode_page(buf.getvalue(), shown.positions, np.zeros((len(shown), 3)),
                         arrows=False, animate=False)
        self.preview.object = iframe(page, height=220)
        self._update_cost()

    def _update_cost(self):
        atoms, name = self.current_molecule()
        try:
            cost = estimate_cost(atoms, derivative_source="forces")
        except Exception as err:  # unusual geometries
            self.cost.object = f"<p style='color:#B42318'>{html.escape(str(err))}</p>"
            return
        seconds = self._single_point_time(atoms, name) * (cost["total"] + 60)
        self.cost.object = (
            f"<p style='margin:8px 0 0'>Estimated cost: <strong>{cost['total']} single "
            f"points</strong> for {cost['n_modes']} vibrational modes, {describe_duration(seconds)} "
            "on this computer.</p>")

    def _single_point_time(self, atoms: Atoms, name: str) -> float:
        key = f"{name}:{atoms.get_chemical_formula()}"
        if key not in self._timing:
            try:
                probe = atoms.copy()
                probe.calc = self.calculator()
                probe.get_forces()  # first call includes setup
                probe.positions[0, 0] += 1e-3
                t0 = time.perf_counter()
                probe.get_forces()
                self._timing[key] = time.perf_counter() - t0
            except Exception:
                self._timing[key] = 0.05
        return self._timing[key]

    # ------------------------------------------------------------------
    def settings(self) -> Settings:
        return Settings(method=self.method.value, max_quanta=self.max_quanta.value,
                        intensities=self.intensities.value)

    def start(self, background: bool = True):
        if self.thread is not None and self.thread.is_alive():
            return
        atoms, name = self.current_molecule()
        self.progress = Progress()
        self.message.visible = False
        self.open_button.visible = False
        self.cancel_button.visible = True
        self.run_button.disabled = True
        self.status_title.object = f"<h3 style='margin:4px 0'>Running {html.escape(name)}</h3>"
        args = (atoms, name, self.settings(), self.runs_dir, self.progress, self.calculator)
        if background:
            self.thread = threading.Thread(target=run_calculation, args=args, daemon=True)
            self.thread.start()
            self._poll = pn.state.add_periodic_callback(self.refresh, period=400)
        else:  # tests: run in this thread
            run_calculation(*args)
            self.refresh()

    def cancel(self):
        if self.progress is not None:
            self.progress.cancel.set()
            self.cancel_button.disabled = True

    def refresh(self):
        if self.progress is None:
            return
        s = self.progress.snapshot()
        self.steps.object = steps_html(s["states"], s["step"], s["done"], s["total"])
        running = s["step"] is not None and s["states"].get(s["step"]) == "running"
        if running and s["total"]:
            self.bar.active, self.bar.value = False, int(100 * s["done"] / max(s["total"], 1))
        elif running:
            self.bar.active, self.bar.value = True, -1  # indeterminate
        lines = "".join(f"{html.escape(l)}\n" for l in s["lines"][-8:])
        self.log.object = (
            "<pre style='background:#16202A;color:#DDE2E8;border-radius:8px;padding:12px;"
            f"font-size:12px;white-space:pre-wrap;margin:8px 0 0'>{lines}"
            f"Elapsed: {s['elapsed']:.0f} s</pre>")
        if s["finished"] or s["error"]:
            self._stop_polling()
            self.bar.active = False
            self.cancel_button.visible = False
            self.cancel_button.disabled = False
            self.run_button.disabled = False
            if s["finished"]:
                self.bar.value = 100
                self.status_title.object = "<h3 style='margin:4px 0'>Finished</h3>"
                self.open_button.visible = True
            else:
                self.status_title.object = (
                    "<h3 style='margin:4px 0'>Cancelled</h3>" if s["cancelled"]
                    else "<h3 style='margin:4px 0'>Stopped</h3>")
                if not s["cancelled"]:
                    self._show_error(s["error"])

    def _stop_polling(self):
        if self._poll is not None:
            self._poll.stop()
            self._poll = None

    def _show_error(self, text: str):
        self.message.object = text
        self.message.visible = True
