"""
Normal-mode animation as a small self-contained HTML page (3Dmol.js),
embedded in the viewer through an iframe.

3Dmol.js 2.5.4 (BSD-3-Clause, see static/3Dmol-LICENSE.txt) ships with the
package. `overtone-gui view` serves it from the local server, so the viewer works
offline. Where the app runs without that route (e.g. create_app in a
notebook), the page falls back to the same version on jsDelivr.
"""

from __future__ import annotations

import html
import json
from typing import Optional

import numpy as np

THREEDMOL_CDN = "https://cdn.jsdelivr.net/npm/3dmol@2.5.4/build/3Dmol-min.js"
#: route under which serve() publishes the bundled static folder
STATIC_ROUTE = "overtone-static"
THREEDMOL_LOCAL = f"/{STATIC_ROUTE}/3Dmol-min.js"

#: URL the mode pages load 3Dmol.js from; serve() switches it to THREEDMOL_LOCAL
script_url = THREEDMOL_CDN

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<script src="{url}"></script>
<style>html,body{{margin:0;height:100%;background:#F8F9FB}}#v{{position:absolute;inset:0}}
#msg{{font:14px system-ui,sans-serif;color:#55606C;padding:16px}}</style>
</head><body><div id="v"></div>
<script>
if (typeof $3Dmol === "undefined") {{
  document.body.innerHTML = '<p id="msg">The 3D viewer could not load 3Dmol.js.</p>';
}} else {{
  const viewer = $3Dmol.createViewer("v", {{backgroundColor: "#F8F9FB"}});
  viewer.addModelsAsFrames({xyz}, "xyz");
  viewer.setStyle({{}}, {{stick: {{radius: 0.13, colorscheme: "Jmol"}}, sphere: {{scale: 0.27, colorscheme: "Jmol"}}}});
  const arrows = {arrows};
  for (const a of arrows) {{
    viewer.addArrow({{start: {{x: a[0], y: a[1], z: a[2]}}, end: {{x: a[3], y: a[4], z: a[5]}},
                     radius: 0.05, color: "#1F5FAD"}});
  }}
  viewer.zoomTo();
  viewer.zoom(1.6);
  if ({animate}) {{ viewer.animate({{loop: "forward", interval: {interval}}}); }}
  viewer.render();
}}
</script></body></html>"""


def mode_page(
    xyz: str,
    positions: np.ndarray,
    displacement: np.ndarray,
    arrows: bool = True,
    animate: bool = True,
    arrow_length: float = 1.3,
    interval: int = 50,
    url: Optional[str] = None,
) -> str:
    """HTML page animating the frames in `xyz`, with optional displacement arrows."""
    arrow_list = []
    if arrows:
        for p, d in zip(np.asarray(positions), np.asarray(displacement)):
            if np.linalg.norm(d) > 0.05:
                e = p + arrow_length * d
                arrow_list.append([*map(float, p), *map(float, e)])
    return _PAGE.format(
        url=url or script_url,
        xyz=json.dumps(xyz),
        arrows=json.dumps(arrow_list),
        animate="true" if animate else "false",
        interval=int(interval),
    )


def iframe(page: str, height: int = 480) -> str:
    """Wrap a page in an iframe so its scripts run inside Panel's HTML pane."""
    return (
        f'<iframe title="Normal mode animation" srcdoc="{html.escape(page, quote=True)}" '
        f'style="width:100%;height:{height}px;border:0;border-radius:8px"></iframe>'
    )
