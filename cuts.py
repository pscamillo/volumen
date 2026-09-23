#!/usr/bin/env python3
"""
cuts.py — cross-sections on demand.

The flattened render shows whether there is fibre weave; mask escape shows
whether the surface stays inside the scroll. Neither says whether the
surface is sitting ON ONE SHEET or wandering across several, and on 18/09 a
geometric surface of 0175B did exactly that with 0.00% escape. The team's
own criterion has two halves — weave in the flat view AND the curve
following the sheets in a cut — and only the first was being judged.

The 506 cuts that exist were made in a batch by the triage tool, for units
that existed then. Anything made since has none, and the experimental
warning tells you to look at a cut that is not there. This makes them for
one unit, when asked, or automatically when a verdict says there might be
letters.

NOTHING IS COPIED. The hard parts live in cortes.py, next to this file:
the volume table (from the prize page, never from render scripts, one of
which names a volume that no longer exists), the -1 sentinel, the ordered
curve interpolated per column, and fetching only the chunks a 512x512 window
touches — about 4 s per window against 72 s for a whole slice. This module
imports those and only redoes the per-unit loop.

Output lands where the Explore already looks:
    ~/.cache/volumen/cortes/<scroll>_z<window>_<wrap>_<n>.png
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

import core
import sources

DEST = os.path.expanduser("~/.cache/volumen/cortes")


def existing(u) -> list[str]:
    return sorted(glob.glob(os.path.join(
        DEST, f"{u.scroll}_z{u.window}_{u.wrap}_*.png")))


def _cortes():
    # cortes.py moved into app/ on 23/09 (it was the triage tool's module,
    # reached through sys.path); same file, no longer a path outside the app
    import cortes
    return cortes


def make(u, cache: core.Cache, n: int = 3, tam: int = 512,
         progress=None) -> list[str]:
    """The same three windows the triage tool makes, for one unit."""
    C = _cortes()
    mesh = u.mesh_dir if u.here else sources.fetch_mesh(u, cache)
    vol = C.volume(u.scroll)
    if vol is None:
        raise RuntimeError(f"no volume known for {u.scroll} in the triage "
                           f"table — add it to VOLUMES in cortes.py")
    x, y, z, m = C.le_malha(mesh)
    zs = z[m]
    if zs.size == 0:
        raise RuntimeError("the mesh has no valid points")
    z_alvo = float(np.median(zs))
    pts = C.curva_na_fatia(x, y, z, m, z_alvo)
    if pts is None:
        raise RuntimeError("too few points where the mesh crosses its "
                           "median slice")
    os.makedirs(DEST, exist_ok=True)
    slug = f"{u.scroll}_z{u.window}_{u.wrap}"
    idx = np.linspace(0, len(pts) - 1, n + 2)[1:-1].astype(int)
    out = []
    for j, i in enumerate(idx, 1):
        if progress:
            progress(j, n)
        cx, cy = pts[i]
        p = os.path.join(DEST, f"{slug}_{j}.png")
        if C.salva_corte(vol, z_alvo, cx, cy, pts, tam, p,
                         f"{u.id}  cut {j}/{n}"):
            out.append(p)
    if not out:
        raise RuntimeError("no window could be cut")
    return out


class _Sig(QObject):
    done = Signal(object)
    failed = Signal(str)
    step = Signal(int, int)


class CutWorker(QThread):
    def __init__(self, unit, cache: core.Cache):
        super().__init__()
        self.unit = unit
        self.cache = cache
        self.sig = _Sig()

    def run(self):
        try:
            paths = make(self.unit, self.cache,
                         progress=lambda j, n: self.sig.step.emit(j, n))
            self.sig.done.emit(paths)
        except Exception as e:  # noqa: BLE001
            self.sig.failed.emit(f"{type(e).__name__}: {e}")
