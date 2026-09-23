#!/usr/bin/env python3
"""
flat.py — the flattened CT view of a mesh, on demand, without VC3D.

The 340 published meshes come flattened (meta.json has scale 0.05 and the
whole flatten fit_config) but no rendered image: the package is meshes only.
Until now, seeing one meant having VC3D installed and running
vc_render_tifxyz. This makes the same image from the mesh and the volume.

It is the same image, not an approximation. Measured against
vc_render_tifxyz on 0800 z10464 w060 (23/09/2026): 99.6% of pixels
identical, no pixel off by more than one level, identical mask. The rules
came from reading QuadSurface::gen, not from guessing — see core.gera_mid.

Output lands next to the other caches:
    ~/.cache/volumen/mid/<scroll>_z<window>_<wrap>.tif
"""
from __future__ import annotations

import os

import numpy as np
import tifffile
from PySide6.QtCore import QObject, QThread, Signal

import core
import sources

DEST = os.path.expanduser("~/.cache/volumen/mid")


def existing(u) -> str | None:
    p = os.path.join(DEST, f"{u.slug}.tif")
    return p if os.path.isfile(p) else None


def make(u, cache: core.Cache, progress=None) -> str:
    """The flattened view of one unit. Minutes, not seconds: it reads the
    volume at every point of the surface."""
    scroll = core.SCROLLS.get(u.scroll)
    if scroll is None:
        raise RuntimeError(f"no volume known for {u.scroll}")
    mesh = u.mesh_dir if u.here else sources.fetch_mesh(u, cache)
    if not mesh or not os.path.isfile(os.path.join(mesh, "x.tif")):
        raise RuntimeError("no mesh to render")
    img, cov = core.gera_mid(mesh, scroll, progress=progress)
    if not (img > 0).any():
        raise RuntimeError("the surface samples nothing inside the volume")
    os.makedirs(DEST, exist_ok=True)
    p = os.path.join(DEST, f"{u.slug}.tif")
    tifffile.imwrite(p, img, compression="zlib")
    return p


class _Sig(QObject):
    done = Signal(object)
    failed = Signal(str)
    step = Signal(int, int)


class FlatWorker(QThread):
    def __init__(self, unit, cache: core.Cache):
        super().__init__()
        self.unit = unit
        self.cache = cache
        self.sig = _Sig()

    def run(self):
        try:
            p = make(self.unit, self.cache,
                     progress=lambda j, n: self.sig.step.emit(j, n))
            self.sig.done.emit(p)
        except Exception as e:  # noqa: BLE001
            self.sig.failed.emit(f"{type(e).__name__}: {e}")
