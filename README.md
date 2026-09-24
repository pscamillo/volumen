# Volumen

A desktop workbench for the Herculaneum scrolls eligible for the First
Letters prize. It opens a surface, shows the CT along it, cuts the raw CT
through it to check that it sits on one sheet, shows the ink map where one
exists, and keeps a record of every judgement — and, on a machine with an
NVIDIA GPU, it makes new surfaces with the same pipeline that produced the
published package.

Two tiers, one loop:

- **Reading — any computer with Python.** The 340 surfaces of
  [vesuvius-eligible-meshes](https://github.com/pscamillo/vesuvius-eligible-meshes)
  (eight scrolls), plus any surface of your own, grown in VC3D or fitted
  elsewhere. The flattened view is made here, from the CT, without VC3D.
  Everything arrives on demand over the network; nothing to download first.
- **Making surfaces — Linux or WSL with an NVIDIA GPU.** Spiral fit,
  flatten, render and ink model, window by window, into the same catalogue.
  Optional, and the app says exactly what it needs (see below).

## Run it

Install [uv](https://docs.astral.sh/uv/) once, then:

```bash
git clone https://github.com/pscamillo/volumen
cd volumen
uv run app.py
```

Linux: `./volumen.sh`, or `./install-desktop.sh` for a menu entry.
Windows: double-click `volumen.bat`.
The first run installs the dependencies (PySide6, zarr, numpy…) into a
local `.venv`; later runs start at once.

Python 3.11–3.13 (uv fetches one if needed). On Linux a normal desktop
install already has what PySide6 needs; on a minimal system add
`libxcb-cursor0 libxkbcommon-x11-0 libgl1` (Debian/Ubuntu names).

## What you can do

- **Scrolls** — the 23 First Letters volumes. The eight with published
  surfaces open; the others tell you how to bring your own, or to make them.
- **Explore** one surface: the flattened CT, the ink maps (forward and
  reverse, where published), three cuts through the raw CT with the
  surface drawn on them, a 1 mm bar and a letter-sized box for scale.
- **Judge** it on three axes — *what do you see* (ink), *surface* (fibre
  weave), *sheet* (does each cut follow one sheet) — and the app keeps
  your answers.
- **Bring your own surfaces**: point *Folders* at any tifxyz folder, or at
  a VC3D `.volpkg` — patches grown in GrowPatch show up alongside.
- **Make surfaces** (with the pipeline installed): pick a route, a scroll
  and how many windows; new surfaces join the catalogue as each window
  finishes, and the fibre gate queues their panels for judgement.

## How to judge

Look at the flattened CT first, not the ink. **Surface**: can you follow
fibres across it, horizontals crossing verticals? **Sheet**: make the cuts;
the amber line should run along one grey layer and bend with it — a V
across a straight stack, or a slide from one layer to the next, means the
surface crossed to a neighbouring sheet, and ink there may belong to that
sheet. **Ink**, last, only on surfaces that passed: zoom until the dashed
square is large and look for organisation — marks in rows, at regular
spacing, letter-sized — not for sharp strokes. Most maps at 9 µm show
nothing, and *nothing but texture* is a real answer: a surface judged sound
with nothing on it is one you will not open again. Verdicts stay on your
machine. *How this works*, inside the app, goes through each step with the
cases it was learned from.

<details>
<summary><b>How the flattened view is made without VC3D</b></summary>

The published surfaces are tifxyz grids (x, y, z per grid point, one point
per 20 voxels). `core.gera_mid` samples the CT along the grid exactly the
way `vc_render_tifxyz` does, with the rules read from the VC3D source rather
than guessed:

- output pixel *i* samples the grid at (*i* + 0.5) / step, bilinear with a
  replicated border;
- a pixel needs the four corners of its bilinear cell valid (the renderer
  turns the −1 sentinel into NaN before sampling), and its nearest grid
  point needs its ±1 neighbours (the normal is a central difference);
- values are truncated to uint8, not rounded.

Measured against `vc_render_tifxyz` on PHerc0800 z14672 w020: identical
mask, no pixel off by more than one level, 99.8 % identical. The CT is read
over plain https from the public bucket (about 43 MB/s), in slices so the
window stays responsive; a package surface takes ~30 s, a large one ~2 min.
</details>

<details>
<summary><b>Making surfaces: what the pipeline does and what it needs</b></summary>

*Make surfaces* runs the author's minimal-route pipeline — the one behind
the published package. For each window of a scroll it fits a spiral to the
sheet material, flattens one winding at a time, renders the CT along each
surface, runs the ink model in both directions, and files the results
where the rest of the app reads them. Two routes: **with lasagna** uses the
team's published sheet-direction volumes; **geometric** (experimental,
validated on one scroll) computes them from the raw CT instead.

It needs, on Linux or WSL2:

| what | why | size |
|---|---|---|
| NVIDIA GPU, driver with CUDA ≥ 12.8 | the fitter runs on Triton + CUDA (torch cu128) | 12 GB VRAM tested; 6 GB reported as very tight |
| RAM | the fitter and the render | 32 GB comfortable; 16 GB tight |
| the ScrollPrize [villa](https://github.com/ScrollPrize/villa) checkout at a pinned commit, with its spiral environment | `fit_spiral.py` | ~10 GB |
| `vc_render_tifxyz` from a [VC3D release](https://github.com/ScrollPrize/villa/releases) | the full multi-layer render the ink model reads | ~125 MB |
| the `ink-detection` package and the `ink_9um` checkpoint | the ink model | a few GB |
| per scroll: tracks (`.dbm`), an umbilicus, a render template | the fitter's inputs | 5–13 GB per scroll |

Setting this up is a manual step today: the *Make surfaces* screen lists
the four things it cannot find, and the pipeline is recognised as soon as
its folder is added in *Folders*. A guided installer — checks first, and
nothing downloaded until every check passes — is in progress. Windows
(native) and macOS cannot run the fitter; they can still do everything in
the reading tier.
</details>

<details>
<summary><b>Where things live on your machine</b></summary>

| what | where |
|---|---|
| settings (the folders you pointed at) | `~/.config/volumen/folders.json` |
| your verdicts and cut labels | `~/.local/share/volumen/` |
| flattened views, cuts, downloaded meshes and ink maps | `~/.cache/volumen/` |
| exports for VC3D | `~/Volumen exports/` |

The cache can be deleted at any time; it is rebuilt on demand. The data
folder holds what cannot be made again.
</details>

<details>
<summary><b>Development</b></summary>

Plain PySide6, one module per screen: `app.py` (shell and style),
`surfaces.py`, `explore.py`, `build.py`, `gate.py`, `progress.py`,
`folders.py`, `help.py`. `core.py` holds the scroll table, volume access and
the flattener; `sources.py` the four surface sources (package, local
folders, pipeline output, VC3D volpkg); `cuts.py` / `cortes.py` the cuts;
`flat.py` the background worker; `config.py` the data locations;
`export_vc3d.py` the *Open in VC3D* export.

Changes take effect on the next start.
</details>

## Data and credits

Scroll data: [Vesuvius Challenge](https://scrollprize.org) open data,
CC BY-NC 4.0. Surfaces: the
[vesuvius-eligible-meshes](https://github.com/pscamillo/vesuvius-eligible-meshes)
package. An independent project by Paulo Sergio Camillo (pscamillo),
implemented with Claude; not affiliated with the Scroll Prize.
Code: MIT.
