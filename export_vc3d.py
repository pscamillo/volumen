#!/usr/bin/env python3
"""
export_vc3d.py — hand one surface over to VC3D.

VC3D opens projects, not loose meshes, so this builds the small folder it
expects and drops the mesh in. Three clicks are left for the person, and the
volume URL is right there to paste.

    <folder>/
      config.json      {"name": ..., "version": 1}
      volumes/
      paths/<mesh>/    x.tif, y.tif, z.tif, meta.json

WHY THIS BUTTON EXISTS. Volumen shows surfaces; it does not trace or edit
them. When someone finds one worth working on, the useful next move is to
leave. Making that easy is the difference between a viewer that feeds the
real tool and one that competes with it.

A note on --flip-normals, if the person renders instead of opening VC3D: the
flag puts the layers in the team's order, and it is what reproduces the
team's published surface volume. The ink maps in this package were rendered
WITHOUT it, which is why the file named "_reverse" there is the team's
forward direction. Anyone rendering fresh today should pass the flag.
"""
from __future__ import annotations

import json
import os
import shutil

import core
import sources

VOLUME_PREFIX = ("https://vesuvius-challenge-open-data.s3.us-east-1."
                 "amazonaws.com")

STEPS = [
    ("Open the project",
     "In VC3D: File → Open Project…. In the file dialog press Ctrl+L and "
     "paste the folder path, then pick the folder. VC3D offers to convert "
     "it to .volpkg.json — accept, and give it any name."),
    ("Attach the volume",
     "File → Attach Remote Zarr…, and paste the URL above."),
    ("Pick both",
     "In the Volume Package panel, choose the volume in the Volume "
     "dropdown and the mesh in the surface list."),
]


def volume_url(scroll: str) -> str | None:
    s = core.SCROLLS.get(scroll)
    if s is None:
        return None
    return f"{VOLUME_PREFIX}/{s.label}/volumes/{s.volume}"


def render_command(scroll: str, mesh_dir: str) -> str:
    """The command line, for people who would rather render than click."""
    url = volume_url(scroll) or "<scroll volume URL>"
    return (f"vc_render_tifxyz \\\n"
            f"  --remote-url {url} \\\n"
            f"  --segmentation {mesh_dir} \\\n"
            f"  --group-idx 0 --scale 1 \\\n"
            f"  --num-slices 31 --slice-step 1 --cache-gb 16 \\\n"
            f"  --flip-normals \\\n"
            f"  --zarr-output out.zarr")


def export(unit: sources.Unit, cache: core.Cache,
           dest_root: str | None = None) -> dict:
    """Build the project folder. Returns what the UI needs to show."""
    mesh = unit.mesh_dir
    if not mesh or not os.path.isdir(mesh):
        mesh = sources.fetch_mesh(unit, cache)

    root = dest_root or os.path.expanduser("~/Volumen exports")
    folder = os.path.join(root, unit.slug)
    paths = os.path.join(folder, "paths", unit.slug)
    os.makedirs(os.path.join(folder, "volumes"), exist_ok=True)
    os.makedirs(paths, exist_ok=True)

    for name in ("meta.json", "x.tif", "y.tif", "z.tif"):
        src = os.path.join(mesh, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(paths, name))

    # the package's meta.json carries area_vx2 but not area_cm2, and VC3D
    # shows -1.000 in the surface list when it is missing. The index knows
    # the real number, so write it in on the way out.
    meta_p = os.path.join(paths, "meta.json")
    if unit.area_cm2 and os.path.isfile(meta_p):
        try:
            with open(meta_p, encoding="utf-8") as f:
                meta = json.load(f)
            if not meta.get("area_cm2"):
                meta["area_cm2"] = unit.area_cm2
                with open(meta_p, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=1)
        except (json.JSONDecodeError, OSError):
            pass

    with open(os.path.join(folder, "config.json"), "w",
              encoding="utf-8") as f:
        json.dump({"name": unit.slug, "version": 1}, f, indent=1)

    # a plain-language note next to the files, for whoever opens the folder
    # later without the app in front of them
    with open(os.path.join(folder, "README.txt"), "w",
              encoding="utf-8") as f:
        f.write(f"""{unit.id} — prepared for VC3D by Volumen

Volume to attach:
  {volume_url(unit.scroll)}

In VC3D:
""")
        for i, (head, body) in enumerate(STEPS, 1):
            f.write(f"  {i}. {head}. {body}\n")
        f.write(f"""
Or render it from the command line instead:

{render_command(unit.scroll, os.path.join('paths', unit.slug))}

The mesh came from https://github.com/pscamillo/vesuvius-eligible-meshes
(MIT). Scroll data: Vesuvius Challenge open data, CC BY-NC 4.0.
""")

    return {
        "folder": folder,
        "volume_url": volume_url(unit.scroll) or "",
        "steps": STEPS,
        "command": render_command(unit.scroll,
                                  os.path.join("paths", unit.slug)),
    }
