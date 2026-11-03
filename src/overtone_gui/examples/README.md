# Example runs

Finished OVERTONE calculations that open in the viewer without computing
anything:

    overtone-gui example                # list them
    overtone-gui example formaldehyde   # open one

All three use GFN2-xTB (tblite): geometry optimised to a largest force below
1e-4 eV/Å, analytic forces for the quartic force field, IR intensities,
GVPT2 with up to 3 quanta. Switching to standard VPT2, deperturbed VPT2 or
DCPT2 in the viewer recomputes only the VPT2 step from these files.

| Example | What it shows |
|---|---|
| `water` | The smallest case: three modes, fundamentals, overtones and combination bands into the near-IR. |
| `formaldehyde` | A Fermi resonance: the CH stretch ν₁₁ mixes with ν₈+ν₉ (about 71 % / 29 %). Compare GVPT2 with DCPT2 to see how the methods treat it. |
| `carbon-dioxide` | A linear molecule with a doubly degenerate bend. GFN2-xTB places 2ν₂ about 230 cm⁻¹ below ν₁, so the well-known ν₁ / 2ν₂ Fermi resonance of CO₂ does not appear at this level of theory: a reminder that resonances depend on the method. |

Each folder holds only the six JSON files the viewer needs; the full run
directory also contains trajectories and a restart cache. Regenerate them with
`python tools/make_examples.py`.
