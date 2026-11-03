"""
The OVERTONE viewer: a local Panel app that opens finished runs.

    overtone-gui view runs/water/

Start screen -> Spectrum (method comparison, figure and table export)
             -> Modes (3D animation, anharmonic constants, resonances)
"""

from __future__ import annotations

import html
import io
from pathlib import Path
from typing import Callable, Dict, Optional

import panel as pn
from bokeh.models.widgets.tables import NumberFormatter

import overtone

import overtone_gui
from overtone_gui.figures import (
    STYLES,
    SpectrumOptions,
    figure_bytes,
    reproduce_script,
    spectrum_figure,
)
from overtone_gui import modes
from overtone_gui.modes import iframe, mode_page
from overtone_gui.run_data import (
    EXAMPLES,
    METHODS,
    RunData,
    RunDirectoryError,
    example_path,
    mode_label,
    read_reference,
    recent_runs,
    remember_run,
)
from overtone_gui.tables import csv_bytes, latex_bytes, transitions_frame
from overtone.spectrum import DEFAULT_FWHM

STATIC = Path(__file__).parent / "static"
DOCS = "https://thequantumchemist.github.io/overtone/"
REPO = "https://github.com/thequantumchemist/overtone"
GUI_REPO = "https://github.com/thequantumchemist/overtone-gui"
CITATION = (
    "B. B. Pattani Ameerjan, M.-P. V. Christiansen, W. Dononelli, "
    "OVERTONE (in preparation)."
)
BIBTEX = """@misc{overtone,
  author = {Pattani Ameerjan, Basila Bhanu and Christiansen, Mads-Peter Verner and Dononelli, Wilke},
  title  = {{OVERTONE}: anharmonic vibrational spectra with {VPT2}},
  note   = {in preparation},
  url    = {https://github.com/thequantumchemist/overtone}
}"""

CSS = """
:root { --ot-ink:#16202A; --ot-muted:#55606C; --ot-line:#DDE2E8; --ot-ground:#F4F6F8;
        --ot-accent:#1F5FAD; --ot-flag:#FFF3E0; --ot-flag-ink:#7A3A06; }
body { background: var(--ot-ground); color: var(--ot-ink); }
.ot-header { background:#fff; border-bottom:1px solid var(--ot-line); }
.ot-card { background:#fff; border:1px solid var(--ot-line); border-radius:10px; }
.ot-muted { color: var(--ot-muted); }
.ot-wordmark { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight:600;
               letter-spacing:.12em; font-size:16px; }
.ot-path { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:13px;
           background:#EEF1F4; border-radius:6px; padding:3px 9px; }
.ot-help summary { cursor:pointer; list-style:none; border:1px solid #C9D0D8; border-radius:999px;
                   width:36px; height:36px; display:flex; align-items:center; justify-content:center;
                   font-weight:600; }
.ot-help summary::-webkit-details-marker { display:none; }
.ot-help[open] .ot-help-menu { display:flex; }
.ot-help-menu { display:none; flex-direction:column; position:absolute; right:0; top:44px; z-index:20;
                width:300px; background:#fff; border:1px solid var(--ot-line); border-radius:10px;
                box-shadow:0 12px 32px rgba(22,32,42,.14); padding:8px; }
.ot-help-menu a { padding:9px 12px; border-radius:6px; text-decoration:none; color:var(--ot-ink); }
.ot-help-menu a:hover { background:#EEF1F4; }
.ot-help-menu pre { white-space:pre-wrap; font-size:11px; background:#F4F6F8; padding:8px;
                    border-radius:6px; margin:6px 0 0; user-select:all; }
.ot-flag { background:var(--ot-flag); color:var(--ot-flag-ink); border-radius:999px;
           padding:2px 8px; font-size:12px; }
"""

RECENT_BUTTON = """
.bk-btn { text-align: left; justify-content: flex-start; font-family: ui-monospace, SFMono-Regular,
          Menlo, monospace; font-size: 13px; background: transparent; border: 0;
          border-bottom: 1px solid #EEF1F4; border-radius: 0; padding: 10px 6px; }
.bk-btn:hover { background: #EEF1F4; }
"""

MAX_RESONANCES = 6

CARD = {"background": "#fff", "border": "1px solid #DDE2E8", "border-radius": "10px",
        "padding": "6px 10px"}


def help_menu() -> pn.pane.HTML:
    links = [
        ("Documentation", DOCS),
        ("Tutorials", DOCS + "tutorials/"),
        ("Manual (PDF)", REPO + "/blob/main/docs/manual.pdf"),
        ("Report a GUI issue", GUI_REPO + "/issues"),
        ("OVERTONE on GitHub", REPO),
    ]
    items = "".join(
        f'<a href="{u}" target="_blank" rel="noopener">{t} ↗</a>' for t, u in links
    )
    return pn.pane.HTML(
        f"""<details class="ot-help" style="position:relative">
<summary aria-label="Help">?</summary>
<div class="ot-help-menu">{items}
<div style="border-top:1px solid #EEF1F4;margin:6px 4px"></div>
<div style="padding:8px 12px"><strong>How to cite</strong>
<div class="ot-muted" style="font-size:13px;margin-top:4px">{html.escape(CITATION)}</div>
<pre>{html.escape(BIBTEX)}</pre></div>
<div style="border-top:1px solid #EEF1F4;margin:6px 4px"></div>
<div class="ot-muted" style="padding:6px 12px;font-size:13px;display:flex;justify-content:space-between">
<span>GPL-3.0</span><span>overtone-vpt2 {overtone.__version__}<br>overtone-gui {overtone_gui.__version__}</span></div>
</div></details>""",
        margin=(4, 0),
    )


# ======================================================================
# Spectrum view
# ======================================================================
class SpectrumView:
    def __init__(self, run: RunData):
        self.run = run
        self.reference: Optional[dict] = None
        self.highlight: Optional[float] = None
        self.frame = None
        recompute = run.can_recompute
        methods = {label: key for key, label in METHODS.items()
                   if recompute or key == run.method}

        self.method = pn.widgets.RadioBoxGroup(options=methods, value=run.method, label="Method")
        self.compare = pn.widgets.CheckBoxGroup(
            options={label: key for label, key in methods.items()}, value=[],
            label="Overlay", disabled=not recompute,
        )
        self.max_quanta = pn.widgets.Select(
            label="Highest number of quanta",
            options=[1, 2, 3, 4] if recompute else [run.max_quanta],
            value=run.max_quanta, width=120,
        )
        self.shape = pn.widgets.RadioButtonGroup(
            options={"Lorentzian": "lorentzian", "Gaussian": "gaussian"}, value="lorentzian",
        )
        self.fwhm = pn.widgets.FloatInput(label="FWHM (cm⁻¹)", value=DEFAULT_FWHM["lorentzian"],
                                          start=0.5, step=1, width=120)
        self.kinds = pn.widgets.CheckBoxGroup(
            options={"Fundamentals": "fundamental", "Overtones": "overtone",
                     "Combinations": "combination"},
            value=["fundamental", "overtone", "combination"], inline=False,
        )
        self.unit = pn.widgets.RadioButtonGroup(
            options={"cm⁻¹": "cm-1", "nm": "nm", "µm": "um"}, value="cm-1",
        )
        self.xmin = pn.widgets.FloatInput(label="From (cm⁻¹)", value=None, placeholder="auto", width=110)
        self.xmax = pn.widgets.FloatInput(label="To (cm⁻¹)", value=None, placeholder="auto", width=110)
        self.log = pn.widgets.Checkbox(label="Logarithmic intensity (near-IR)", value=False)
        self.invert = pn.widgets.Checkbox(label="High wavenumbers left", value=True)
        self.sticks = pn.widgets.Checkbox(label="Sticks", value=True)
        self.labels = pn.widgets.Checkbox(label="Label peaks", value=True)
        self.harmonic = pn.widgets.Checkbox(label="Harmonic spectrum", value=False)
        self.style = pn.widgets.Select(label="Figure style", options=list(STYLES), value="Screen",
                                       width=200)
        self.ref_input = pn.widgets.FileInput(accept=".csv,.txt,.dat", multiple=False)
        self.ref_clear = pn.widgets.Button(label="Remove reference", color="light",
                                           visible=False)
        self.message = pn.pane.Alert("", alert_type="warning", visible=False)

        self.plot = pn.pane.Matplotlib(None, format="svg", tight=False, dpi=110,
                                       sizing_mode="stretch_width")
        self.table = pn.widgets.Tabulator(
            None, show_index=False, disabled=True, selectable=1, height=360,
            sizing_mode="stretch_width", layout="fit_data_stretch",
        )

        self.downloads = pn.Row(*[
            pn.widgets.FileDownload(callback=self._figure_callback(fmt), filename=f"spectrum.{fmt}",
                                    label=label, color="light", width=110)
            for fmt, label in (("svg", "SVG"), ("pdf", "PDF"), ("png", "PNG 600 dpi"))
        ], pn.widgets.FileDownload(callback=self._script, filename="spectrum.py",
                                   label="Python script", color="light", width=130))
        self.table_downloads = pn.Row(
            pn.widgets.FileDownload(callback=lambda: csv_bytes(self.frame),
                                    filename="transitions.csv", label="CSV",
                                    color="light", width=90),
            pn.widgets.FileDownload(callback=lambda: latex_bytes(self.frame),
                                    filename="transitions.tex", label="LaTeX",
                                    color="light", width=90),
        )

        self.shape.param.watch(self._shape_changed, "value")
        self.ref_input.param.watch(self._reference_loaded, "value")
        self.ref_clear.on_click(self._reference_cleared)
        self.table.param.watch(self._row_selected, "selection")
        for w in (self.method, self.compare, self.max_quanta, self.fwhm, self.kinds, self.unit,
                  self.xmin, self.xmax, self.log, self.invert, self.sticks, self.labels,
                  self.harmonic, self.style):
            w.param.watch(lambda event: self.update(), "value")

        self.layout = self._layout()
        self.update()

    # ------------------------------------------------------------------
    def _layout(self):
        def card(title, *objects):
            return pn.Column(pn.pane.Markdown(f"**{title}**", margin=(4, 6)), *objects,
                             styles=CARD, sizing_mode="stretch_width")

        note = "" if self.run.can_recompute else (
            "\n\nOnly the stored method is available: recomputing needs the full run directory."
        )
        controls = pn.Column(
            card("VPT2 method", self.method,
                 pn.pane.Markdown("Overlay for comparison", margin=(6, 6, 0, 6)), self.compare,
                 self.max_quanta,
                 pn.pane.Markdown("Switching method repeats only the VPT2 step on the stored "
                                  "force field." + note, styles={"font-size": "12px"},
                                  css_classes=["ot-muted"])),
            card("Line shape", self.shape, self.fwhm),
            card("Bands", self.kinds),
            card("Axis", self.unit, pn.Row(self.xmin, self.xmax), self.log, self.invert,
                 self.sticks, self.labels, self.harmonic),
            card("Experimental reference",
                 pn.pane.Markdown("Two columns: wavenumber (cm⁻¹), intensity.",
                                  styles={"font-size": "12px"}),
                 self.ref_input, self.ref_clear),
            width=310,
        )
        main = pn.Column(
            self.message,
            pn.Column(self.plot, pn.Row(self.style, pn.HSpacer(), self.downloads,
                                        align="center", sizing_mode="stretch_width"),
                      styles=CARD, sizing_mode="stretch_width"),
            pn.Column(pn.Row(pn.pane.Markdown("**Transitions**  \nSelect a row to mark the band "
                                              "in the spectrum."),
                             pn.HSpacer(), self.table_downloads, sizing_mode="stretch_width"),
                      self.table, styles=CARD, sizing_mode="stretch_width"),
            sizing_mode="stretch_width",
        )
        return pn.Row(controls, main, sizing_mode="stretch_width")

    # ------------------------------------------------------------------
    def results(self) -> Dict[str, object]:
        """{display label: VPT2Result}, primary first."""
        mq = self.max_quanta.value
        keys = [self.method.value] + [k for k in self.compare.value if k != self.method.value]
        return {METHODS[k]: self.run.result_for(k, mq) for k in keys}

    def options(self) -> SpectrumOptions:
        return SpectrumOptions(
            shape=self.shape.value, fwhm=self.fwhm.value, kinds=self.kinds.value or None,
            xmin=self.xmin.value, xmax=self.xmax.value, log=self.log.value,
            unit=self.unit.value, invert_x=self.invert.value, sticks=self.sticks.value,
            peak_labels=self.labels.value, show_harmonic=self.harmonic.value,
            style=self.style.value, highlight=self.highlight,
        )

    def _figure(self, style: Optional[str] = None):
        opts = self.options()
        if style:
            opts.style = style
        return spectrum_figure(self.results(), opts, self.reference)

    def update(self, table: bool = True):
        self.layout.loading = True
        try:
            results = self.results()
            if table:
                self.frame = transitions_frame(results)
                kinds = set(self.kinds.value)
                shown = self.frame[self.frame["Type"].isin(kinds)] if kinds else self.frame
                display = shown.copy()
                display["Intensity"] = [
                    "" if v is None or v != v else f"{v:.3g}" for v in display["Intensity"]
                ]
                self.table.formatters = {
                    col: NumberFormatter(format="0.0", text_align="right") for col in display.columns
                    if col in ("Harmonic", *METHODS.values())
                }
                self.table.value = display
            if self.run.has_intensities:
                self.plot.object = self._figure()
                self.message.visible = False
            else:
                self.plot.object = None
                self._warn("This run has no IR intensities, so there is no spectrum to draw. "
                           "Run with intensities=True; the table below still lists all bands.")
        except (RunDirectoryError, ValueError) as err:
            self._warn(str(err))
        finally:
            self.layout.loading = False

    def _warn(self, text: str):
        self.message.object = text
        self.message.visible = True

    # ------------------------------------------------------------------
    def _shape_changed(self, event):
        self.fwhm.value = DEFAULT_FWHM[event.new]  # triggers update

    def _reference_loaded(self, event):
        if not event.new:
            return
        try:
            self.reference = read_reference(event.new, self.ref_input.filename or "reference")
            self.ref_clear.visible = True
        except ValueError as err:
            self._warn(str(err))
            return
        self.update(table=False)

    def _reference_cleared(self, event):
        self.reference = None
        self.ref_clear.visible = False
        self.update(table=False)

    def _row_selected(self, event):
        if not event.new or self.table.value is None:
            self.highlight = None
        else:
            row = self.table.value.iloc[event.new[0]]
            self.highlight = float(row[METHODS[self.method.value]])
        self.update(table=False)

    def _figure_callback(self, fmt: str) -> Callable[[], io.BytesIO]:
        def callback():
            style = self.style.value if self.style.value != "Screen" else "Double column"
            return figure_bytes(self._figure(style), fmt)
        return callback

    def _script(self) -> io.BytesIO:
        text = reproduce_script(self.run.path, self.method.value, self.max_quanta.value,
                                self.options())
        return io.BytesIO(text.encode())


# ======================================================================
# Modes view
# ======================================================================
class ModesView:
    def __init__(self, run: RunData, method: pn.widgets.Widget):
        self.run = run
        self.method = method
        fundamentals = {
            m: next((t.energy for t in run.result.transitions or []
                     if t.kind == "fundamental" and m in t.quanta), float("nan"))
            for m in run.active_modes
        }
        self.mode = pn.widgets.Select(
            label="Normal mode",
            options={f"{mode_label(m)}   {fundamentals[m]:.0f} cm⁻¹": m for m in run.active_modes},
            width=260,
        )
        self.amplitude = pn.widgets.FloatSlider(label="Amplitude (Å)", start=0.1, end=0.8,
                                                step=0.05, value=0.35, width=260)
        self.arrows = pn.widgets.Checkbox(label="Displacement arrows", value=True)
        self.animate = pn.widgets.Checkbox(label="Animate", value=True)
        self.viewer = pn.pane.HTML("", sizing_mode="stretch_width", height=500)
        self.info = pn.pane.HTML("", width=320)
        self.download = pn.widgets.FileDownload(
            callback=self._xyz, filename="mode.xyz", label="XYZ trajectory",
            color="light", width=260,
        )
        for w in (self.mode, self.amplitude, self.arrows, self.animate):
            w.param.watch(lambda e: self.update(), "value")
        self.method.param.watch(lambda e: self.update_info(), "value")
        self.layout = pn.Row(
            pn.Column(self.mode, self.amplitude, self.arrows, self.animate, self.download,
                      styles=CARD, width=290),
            pn.Column(self.viewer, styles=CARD, sizing_mode="stretch_width"),
            pn.Column(self.info, styles=CARD, width=340),
            sizing_mode="stretch_width",
        )
        self.update()

    def update(self):
        m = self.mode.value
        rot = self.run.view_rotation()
        page = mode_page(
            self.run.mode_xyz(m, self.amplitude.value, rotation=rot),
            self.run.atoms.positions @ rot,
            self.run.mode_displacement(m) @ rot,
            arrows=self.arrows.value, animate=self.animate.value,
        )
        self.viewer.object = iframe(page, height=480)
        self.download.filename = f"{self.run.name}_{mode_label(m)}.xyz"
        self.update_info()

    def update_info(self):
        m, method = self.mode.value, self.method.value
        try:
            res = self.run.result_for(method)
        except RunDirectoryError:
            res, method = self.run.result, self.run.method
        fund = next((t for t in res.transitions or []
                     if t.kind == "fundamental" and m in t.quanta), None)
        rows = [("Harmonic", f"{self.run.harmonic_frequency(m):.1f}")]
        if fund is not None:
            rows.append((f"{METHODS.get(method, method)}", f"{fund.energy:.1f}"))
            rows.append(("Anharmonic shift", f"{fund.energy - fund.harmonic:+.1f}"))
            if fund.intensity is not None:
                rows.append(("Intensity (km/mol)", f"{fund.intensity:.3g}"))
        freq = "".join(f"<tr><td class='ot-muted'>{k}</td><td style='text-align:right'>{v}</td></tr>"
                       for k, v in rows)
        consts = "".join(
            f"<tr><td class='ot-muted'>X<sub>{m + 1},{j + 1}</sub></td>"
            f"<td style='text-align:right'>{x:.2f}</td></tr>"
            for j, x in self.run.anharmonic_constants(m, method).items()
        )
        resonant = sorted(self.run.resonances(m, method), key=lambda t: t.energy)
        res_items = "".join(
            f"<li><strong>{t.label}</strong> at {t.energy:.1f} cm⁻¹"
            + (": " + ", ".join(f"{k} {v:.0%}" for k, v in t.mixing.items()) if t.mixing else "")
            + "</li>"
            for t in resonant[:MAX_RESONANCES]
        ) or "<li class='ot-muted'>No Fermi resonance involves this mode.</li>"
        if len(resonant) > MAX_RESONANCES:
            res_items += (f"<li class='ot-muted'>{len(resonant) - MAX_RESONANCES} more bands; "
                          "filter the transitions table by Fermi to see all.</li>")
        self.info.object = f"""
<h3 style="margin:4px 0 8px">{mode_label(m)}</h3>
<p class="ot-muted" style="margin:0 0 6px">Wavenumbers in cm⁻¹</p>
<table style="width:100%">{freq}</table>
<h4 style="margin:14px 0 6px">Anharmonic constants</h4>
<table style="width:100%">{consts}</table>
<h4 style="margin:14px 0 6px">Resonances</h4>
<ul style="padding-left:18px;margin:0">{res_items}</ul>"""

    def _xyz(self) -> io.BytesIO:
        return io.BytesIO(self.run.mode_xyz(self.mode.value, self.amplitude.value).encode())


# ======================================================================
# Application shell
# ======================================================================
DEFAULT_RUNS_DIR = Path.home() / "overtone-runs"


class OvertoneApp:
    """
    The viewer shell. With student=True the start screen also offers new
    GFN2-xTB calculations (StudentView); start_compute opens that screen first.
    """

    def __init__(self, path=None, student: bool = False, runs_dir=None,
                 start_compute: bool = False):
        self.student = student
        self.runs_dir = Path(runs_dir) if runs_dir else DEFAULT_RUNS_DIR
        self.header = pn.Row(sizing_mode="stretch_width", css_classes=["ot-header"],
                             styles={"padding": "4px 16px"})
        self.body = pn.Column(sizing_mode="stretch_width", margin=(10, 10))
        self.root = pn.Column(self.header, self.body, sizing_mode="stretch_width")
        if path is not None:
            self.open_run(path)
        elif student and start_compute:
            self.show_compute()
        else:
            self.show_start()

    def show_compute(self):
        from overtone_gui.student import StudentView  # needs tblite only here
        self._set_header(badge="Student mode, GFN2-xTB")
        self.compute = StudentView(self.runs_dir, on_open=self.open_run)
        self.body.objects = [self.compute.layout]

    def _set_header(self, run: Optional[RunData] = None, badge: Optional[str] = None):
        logo = pn.pane.PNG(str(STATIC / "icon.png"), width=34, height=34, margin=(6, 4))
        items = [logo, pn.pane.HTML('<span class="ot-wordmark">OVERTONE</span>', margin=(14, 6))]
        if badge:
            items.append(pn.pane.HTML(
                f'<span style="font-size:12px;padding:4px 10px;border-radius:999px;'
                f'background:#E3F2EE;color:#0B4F45;font-weight:500">{html.escape(badge)}</span>',
                margin=(14, 6)))
            home = pn.widgets.Button(label="Start screen", color="light", margin=(8, 6),
                                     width=120, sizing_mode="fixed")
            home.on_click(lambda e: self.show_start())
            items += [pn.HSpacer(), home]
        if run is not None:
            items.append(pn.pane.HTML(
                f'<span class="ot-path">{html.escape(run.display_path)}</span>'
                f'<span class="ot-muted" style="margin-left:12px">{html.escape(run.describe())}</span>',
                margin=(14, 12)))
            home = pn.widgets.Button(label="Open run…", color="light", margin=(8, 6),
                                     width=110, sizing_mode="fixed")
            home.on_click(lambda e: self.show_start())
            items += [pn.HSpacer(), home]
        elif not badge:
            items.append(pn.HSpacer())
        items.append(help_menu())
        self.header.objects = items

    # ------------------------------------------------------------------
    def show_start(self, error: Optional[str] = None):
        self._set_header()
        path = pn.widgets.TextInput(label="Run directory or vpt2_result.json",
                                    placeholder="~/runs/water", sizing_mode="stretch_width")
        open_button = pn.widgets.Button(label="Open run", color="primary", width=120,
                                        align="end")
        open_button.on_click(lambda e: self.open_run(path.value))
        path.param.watch(lambda e: self.open_run(path.value), "enter_pressed")

        recent = []
        for p in recent_runs():
            b = pn.widgets.Button(label=str(p), color="light", sizing_mode="stretch_width",
                                  stylesheets=[RECENT_BUTTON])
            b.on_click(lambda e, p=p: self.open_run(p))
            recent.append(b)
        recent_block = pn.Column(
            pn.pane.Markdown("**Recent runs**"),
            *(recent or [pn.pane.Markdown("Runs you open appear here.", css_classes=["ot-muted"])]),
        )
        alert = pn.pane.Alert(error or "", alert_type="danger", visible=bool(error))
        side = []
        example_buttons = []
        for key, title in EXAMPLES.items():
            b = pn.widgets.Button(label=title, color="light", sizing_mode="stretch_width",
                                  stylesheets=[RECENT_BUTTON])
            b.on_click(lambda e, key=key: self.open_run(example_path(key)))
            example_buttons.append(b)
        examples_card = pn.Column(
            pn.pane.HTML("<p><strong>Examples</strong></p><p style='margin:0'>Finished "
                         "GFN2-xTB calculations to explore right away.</p>"),
            *example_buttons, styles=CARD, width=320)
        if self.student:
            new = pn.widgets.Button(label="Start a calculation", color="primary",
                                    sizing_mode="stretch_width")
            new.on_click(lambda e: self.show_compute())
            side.append(pn.Column(
                pn.pane.HTML("<p><strong>New calculation</strong></p><p style='margin:0'>Pick a "
                             "small molecule and compute its anharmonic spectrum with GFN2-xTB, "
                             "step by step.</p>"),
                new, styles=CARD, width=320))
        learn = pn.pane.HTML(
            f'<p><strong>Learn</strong></p><p><a href="{DOCS}tutorials/" target="_blank">Tutorials ↗</a><br>'
            f'<a href="{DOCS}" target="_blank">Documentation ↗</a><br>'
            f'<a href="{REPO}/blob/main/docs/manual.pdf" target="_blank">Manual (PDF) ↗</a></p>'
            '<p class="ot-muted" style="font-size:13px">The viewer opens runs computed with '
            '<code>save_results=True</code>.</p>'
        )
        self.body.objects = [
            pn.Column(
                pn.pane.JPG(str(STATIC / "banner.jpg"), sizing_mode="stretch_width",
                            styles={"border-radius": "14px", "overflow": "hidden"}),
                pn.Row(
                    pn.Column(pn.pane.Markdown("## Open a run"), alert,
                              pn.Row(path, open_button, sizing_mode="stretch_width"),
                              recent_block, styles=CARD, sizing_mode="stretch_width"),
                    pn.Column(*side, examples_card, pn.Column(learn, styles=CARD, width=320)),
                    sizing_mode="stretch_width",
                ),
                pn.pane.HTML(f'<p class="ot-muted" style="font-size:13px">overtone-vpt2 '
                             f'{overtone.__version__}, overtone-gui {overtone_gui.__version__}, GPL-3.0. '
                             'Please cite the OVERTONE paper '
                             'when you publish results.</p>'),
                max_width=1200, sizing_mode="stretch_width",
                styles={"margin-left": "auto", "margin-right": "auto"},
            )
        ]

    def open_run(self, path):
        if not path:
            return
        try:
            run = RunData.load(path)
        except (RunDirectoryError, OSError, ValueError) as err:
            self.show_start(error=str(err))
            return
        if run.example is None:  # examples live in the package, not in the history
            remember_run(run.path)
        self._set_header(run)
        spectrum = SpectrumView(run)
        tabs = [("Spectrum", spectrum.layout)]
        if run.atoms is not None:
            tabs.append(("Modes", ModesView(run, spectrum.method).layout))
        self.body.objects = [pn.Tabs(*tabs, dynamic=False, sizing_mode="stretch_width")]


def create_app(path=None):
    pn.extension("tabulator", raw_css=[CSS], notifications=True)
    return OvertoneApp(path).root


def serve(path=None, port: int = 0, show: bool = True, student: bool = False, runs_dir=None):
    """
    Start the local app; one fresh app per browser tab. Works offline.
    student=True opens the student mode (new GFN2-xTB calculations).
    """
    pn.extension("tabulator", raw_css=[CSS], notifications=True)
    modes.script_url = modes.THREEDMOL_LOCAL  # bundled 3Dmol.js, no CDN
    title = "OVERTONE student" if student else "OVERTONE"
    pn.serve(lambda: OvertoneApp(path, student=student, runs_dir=runs_dir,
                                 start_compute=student and path is None).root,
             port=port, show=show, title=title,
             address="localhost", static_dirs={modes.STATIC_ROUTE: str(STATIC)})
