# Volumen

A desktop workbench for the Herculaneum scroll surfaces published in
[vesuvius-eligible-meshes](https://github.com/pscamillo/vesuvius-eligible-meshes)
— 340 surfaces across eight First Letters scrolls — and for any surface of
your own, grown in VC3D or fitted elsewhere.

It opens a surface, shows the CT along it (the flattened view, made here
without VC3D), lets you cut the raw CT through it to see whether it sits on
one sheet, shows the ink map where one exists, and records what you saw.
Everything arrives on demand over the network; nothing to download first.

**Needs only Python.** No VC3D, no GPU, no checkout of anything.

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
  surfaces open; the others tell you how to bring your own.
- **Explore** one surface: the flattened CT, the ink maps (forward and
  reverse, where published), three cuts through the raw CT with the
  surface drawn on them, a 1 mm bar and a letter-sized box for scale.
- **Judge** it on three axes — *what do you see* (ink), *surface* (fibre
  weave), *sheet* (does each cut follow one sheet) — and the app keeps
  your answers.
- **Bring your own surfaces**: point *Folders* at any tifxyz folder, or at
  a VC3D `.volpkg` — patches grown in GrowPatch show up alongside.

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
<summary><b>Making surfaces (optional, Linux + NVIDIA)</b></summary>

*Make surfaces* runs the author's pipeline — spiral fit, flatten, render,
ink model — for scrolls with published lasagna fields. It is not part of
this repository and needs the ScrollPrize `villa` checkout with its spiral
environment (Triton + CUDA), `vc_render_tifxyz` from a VC3D release, the
`villa_ink` checkout and its checkpoint, and per-scroll inputs. The app
says so on that screen; without it, surfaces come from the package, from
VC3D patches, or from any tifxyz folder.
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
