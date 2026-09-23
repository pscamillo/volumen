#!/usr/bin/env python3
"""
sources.py — where the surfaces come from.

Four sources, one interface:

  public     the published package — 340 meshes across eight eligible
             scrolls, and the ink maps computed on them
  local      whatever is already on this machine
  produced   what the pipeline (esteira) left on this machine
  patch      a VC3D volume package: whatever the person grew in GrowPatch,
             traced, or exported, under <name>.volpkg/paths/

WHY ON-DEMAND IS CHEAP HERE. A tifxyz mesh is four small files (x, y, z and
meta.json), about 520 kB in total. Fetching one when the person opens it is
instant. The ink maps are the heavy part: 2.8 GB for 672 files, so those stay
on demand, one at a time, never in bulk.

SCOPE. Only the 23 volumes eligible for the First Letters prize, plus the one
scroll that has been read. This is a viewer for that set, not a general tool.

Run a check:
    uv run --with numpy sources.py --check
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import core

# the published package
GH_USER = "pscamillo"
GH_REPO = "vesuvius-eligible-meshes"
GH_RAW = f"https://raw.githubusercontent.com/{GH_USER}/{GH_REPO}/main"
GH_PAGE = f"https://github.com/{GH_USER}/{GH_REPO}"

# the ink maps that go with it
HF_DATASET = "pscamillo/vesuvius-eligible-meshes-ink9"
HF_RESOLVE = f"https://huggingface.co/datasets/{HF_DATASET}/resolve/main"
HF_API = f"https://huggingface.co/api/datasets/{HF_DATASET}"

MESH_FILES = ("meta.json", "x.tif", "y.tif", "z.tif")

# Folders on this machine come from the person's own settings, not from
# hard-coded paths: everyone organises their disk differently, and the app
# has to work for someone who has never seen this pipeline.
CONFIG_PATH = os.path.expanduser("~/.config/volumen/folders.json")


def local_folders() -> list[str]:
    """Read the settings file directly.

    This used to import folders.py, which imports PySide6 at module level —
    so any context without Qt silently got an empty list, and the except
    swallowed the reason. Configuration is data; it should not depend on a
    widget toolkit.
    """
    if not os.path.isfile(CONFIG_PATH):
        return []
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            got = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"sources: could not read {CONFIG_PATH}: {e}")
        return []
    if not isinstance(got, list):
        return []
    return [os.path.expanduser(str(p)) for p in got]


@dataclass
class Unit:
    """One surface someone can look at."""
    scroll: str
    window: int
    wrap: str
    origin: str                      # public | local | produced | patch
    mesh_dir: str | None = None      # local path, if it is here
    mesh_rel: str | None = None      # path inside the public package
    mid: str | None = None           # flattened CT, if it was rendered
    geometric: bool = False          # made without lasagna: experimental
    ink_forward: str | None = None   # local path or url
    ink_reverse: str | None = None
    area_cm2: float | None = None
    screened: str | None = None      # the package's own surface screen
    note: str = ""

    @property
    def id(self) -> str:
        return f"{self.scroll}/z{self.window}/{self.wrap}"

    @property
    def slug(self) -> str:
        return f"{self.scroll}_z{self.window}_{self.wrap}"

    @property
    def scale_um(self) -> float | None:
        s = core.SCROLLS.get(self.scroll)
        return s.voxel_um if s else None

    @property
    def here(self) -> bool:
        return bool(self.mesh_dir and os.path.isdir(self.mesh_dir))


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Volumen"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------------------------------------------------------- public --
def public_index(cache: core.Cache, refresh: bool = False) -> list[Unit]:
    """The package index, fetched once and kept.

    One small CSV describes all 340 meshes, so the catalogue costs a few
    kilobytes even when nothing has been downloaded.
    """
    path = cache.path("public", "index.csv")
    if refresh or not os.path.isfile(path):
        try:
            data = _get(f"{GH_RAW}/data/index.csv")
        except urllib.error.URLError as e:
            raise RuntimeError(f"could not reach the package index: {e}")
        with open(path, "wb") as f:
            f.write(data)
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    out = []
    for r in rows:
        scroll = r["scroll"].replace("PHerc", "")
        rel = r["path"]
        u = Unit(scroll=scroll, window=int(r["window_z"]), wrap=r["wrap"],
                 origin="public", mesh_rel=rel)
        try:
            u.area_cm2 = float(r["area_cm2"])
        except (TypeError, ValueError):
            pass
        v = (r.get("gate_verdict") or "").strip()
        # the package screened surfaces, not ink; keep the words plain
        u.screened = {"aprova": "looks clean", "parcial": "mixed",
                      "reprova": "poor"}.get(v)
        # layout on the hub mirrors the mesh package:
        #   PHerc<scroll>/z<window>_<wrap>.tif
        # and, as everywhere in this pipeline, the file named "_reverse" is
        # the team's forward direction, because no render here passes
        # --flip-normals.
        stem = f"{HF_RESOLVE}/PHerc{u.scroll}/z{u.window}_{u.wrap}"
        u.ink_forward = f"{stem}_reverse.tif"
        u.ink_reverse = f"{stem}.tif"
        out.append(u)
    return out


def fetch_mesh(u: Unit, cache: core.Cache,
               progress=None) -> str:
    """Bring one mesh down. Four files, about half a megabyte."""
    if u.here:
        return u.mesh_dir
    if not u.mesh_rel:
        raise RuntimeError(f"{u.id} has no published path")
    dest = cache.path("public", "meshes", u.slug, "meta.json")
    d = os.path.dirname(dest)
    for i, name in enumerate(MESH_FILES, 1):
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            continue
        data = _get(f"{GH_RAW}/{u.mesh_rel}/{name}")
        with open(p, "wb") as f:
            f.write(data)
        if progress:
            progress(i, len(MESH_FILES))
    u.mesh_dir = d
    return d


def fetch_ink(u: Unit, cache: core.Cache, direction: str = "forward",
              progress=None) -> str | None:
    """Bring one ink map down. These are the heavy files, so one at a time."""
    url = u.ink_forward if direction == "forward" else u.ink_reverse
    if not url:
        return None
    if not url.startswith("http"):
        return url if os.path.isfile(url) else None
    name = f"{u.slug}_{direction}.tif"
    p = cache.path("public", "ink", name)
    if os.path.isfile(p) and os.path.getsize(p) > 0:
        return p
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Volumen"})
        with urllib.request.urlopen(req, timeout=300) as r:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            with open(p, "wb") as f:
                while True:
                    block = r.read(1 << 18)
                    if not block:
                        break
                    f.write(block)
                    got += len(block)
                    if progress and total:
                        progress(got, total)
    except urllib.error.URLError:
        if os.path.isfile(p):
            os.remove(p)
        return None
    return p


# ----------------------------------------------------------------- local --
def local_units() -> list[Unit]:
    """Whatever the person has pointed at, in any of the four layouts."""
    out: dict[str, Unit] = {}
    for folder in local_folders():
        if not os.path.isdir(folder):
            continue
        # a volpkg itself, or a folder that holds volpkgs one level down
        if folder.endswith(".volpkg"):
            _scan_volpkg(folder, out)
            continue
        for name in sorted(os.listdir(folder)):
            if name.endswith(".volpkg"):
                _scan_volpkg(os.path.join(folder, name), out)
        if _looks_like_pipeline(folder):
            _scan_pipeline(folder, out)
            _scan_legacy(folder, out)
        else:
            _scan_folder(folder, out)
    return list(out.values())


def _looks_like_pipeline(root: str) -> bool:
    """A working directory of the minimal route, not a tidy package."""
    if not os.path.isdir(root):
        return False
    for name in os.listdir(root):
        if name.startswith("render_") or name.startswith("work"):
            return True
    return False


RE_REND = re.compile(r"^render_(?P<rolo>[A-Za-z0-9]+)_z(?P<z0>\d+)$")
RE_WRAP = re.compile(r"^w\d+$")


def _scan_pipeline(root: str, out: dict) -> None:
    """What the minimal route leaves on disk.

    render_<ROLO>_z<Z0>/w<NNN>/mid/mid.tif          the flattened CT
    render_<ROLO>_z<Z0>/w<NNN>/pred_ink9*.tif       the ink maps
    work*_<ROLO>_z<Z0>/out/*/meshes/fitted_*/w<NNN>_*   the mesh
    """
    for name in sorted(os.listdir(root)):
        m = RE_REND.match(name)
        if not m or not os.path.isdir(f"{root}/{name}"):
            continue
        rolo, z0 = m.group("rolo"), int(m.group("z0"))
        for w in sorted(os.listdir(f"{root}/{name}")):
            if not RE_WRAP.match(w):
                continue
            d = f"{root}/{name}/{w}"
            u = out.setdefault(f"{rolo}/z{z0}/{w}",
                               Unit(scroll=rolo, window=z0, wrap=w,
                                    origin="produced"))
            mid = f"{d}/mid/mid.tif"
            if os.path.isfile(mid):
                u.mid = mid
            # no --flip-normals here, so "_reverse" is the team's forward
            fwd, rev = f"{d}/pred_ink9_reverse.tif", f"{d}/pred_ink9.tif"
            if os.path.isfile(fwd):
                u.ink_forward = fwd
            if os.path.isfile(rev):
                u.ink_reverse = rev
            # esteira_via3 and posfit.sh write here instead; same convention,
            # no --flip-normals, so "_reverse" is still the team's forward
            pf = f"{d}/preds/s43_060000_reverse.tif"
            pr = f"{d}/preds/s43_060000.tif"
            if not u.ink_forward and os.path.isfile(pf):
                u.ink_forward = pf
            if not u.ink_reverse and os.path.isfile(pr):
                u.ink_reverse = pr
            if not u.mesh_dir:
                u.mesh_dir = _pipeline_mesh(root, rolo, z0, w)
            # the geometric route fits into workT_*, the lasagna one into work_*
            u.geometric = bool(u.mesh_dir and "/workT_" in u.mesh_dir)


RE_LEGACY = re.compile(r"^render_(?P<rolo>[0-9A-Za-z]+)$")
RE_FITDIR = re.compile(r"(work[A-Za-z0-9_]*)/out")
RE_SLICE = re.compile(r"slice-(\d+)-(\d+)")


def _scan_legacy(root: str, out: dict) -> None:
    """The first pass of August: render_<ROLO>/ with no window in the name.

    One per scroll, the window at the umbilicus median. The window is not in
    the folder name, but the fit folder is named in render_<ROLO>.sh (the
    FITDIR line), and that folder's output is named slice-A-B. For 0191 the
    fit lives in work_0191_tracks, because in August the fit with tracks was
    kept apart from the one without — which is why reading it from the
    script, rather than guessing work_<ROLO>, matters.
    """
    import glob as _g
    for name in sorted(os.listdir(root)):
        m = RE_LEGACY.match(name)
        d = f"{root}/{name}"
        if not m or not os.path.isdir(d):
            continue
        rolo = m.group("rolo")
        work = f"{root}/work_{rolo}"
        script = f"{root}/render_{rolo}.sh"
        if os.path.isfile(script):
            with open(script, encoding="utf-8", errors="replace") as f:
                mm = RE_FITDIR.search(f.read())
            if mm:
                work = f"{root}/{mm.group(1)}"
        z0 = None
        for o in sorted(_g.glob(f"{work}/out/*")):
            sm = RE_SLICE.search(os.path.basename(o))
            if sm:
                z0 = int(sm.group(1))
                break
        if z0 is None:
            continue
        for w in sorted(os.listdir(d)):
            if not RE_WRAP.match(w):
                continue
            dw = f"{d}/{w}"
            mid = f"{dw}/mid/mid.tif"
            if not os.path.isfile(mid):
                continue
            u = out.setdefault(f"{rolo}/z{z0}/{w}",
                               Unit(scroll=rolo, window=z0, wrap=w,
                                    origin="produced"))
            u.mid = u.mid or mid
            # no --flip-normals: "_reverse" is the team's forward
            for pf, pr in ((f"{dw}/pred_ink9_reverse.tif",
                            f"{dw}/pred_ink9.tif"),
                           (f"{dw}/preds/s43_060000_reverse.tif",
                            f"{dw}/preds/s43_060000.tif")):
                if not u.ink_forward and os.path.isfile(pf):
                    u.ink_forward = pf
                if not u.ink_reverse and os.path.isfile(pr):
                    u.ink_reverse = pr
            if not u.mesh_dir:
                for p in sorted(_g.glob(f"{work}/out/*/meshes/fitted_*/{w}_*")):
                    if "spliced" not in p and os.path.isfile(f"{p}/x.tif"):
                        u.mesh_dir = p
                        break


def _pipeline_mesh(root: str, rolo: str, z0: int, wrap: str) -> str | None:
    import glob as _g
    for pref in ("workT", "workGEO", "workREF", "work"):
        pat = f"{root}/{pref}_{rolo}_z{z0}/out/*/meshes/fitted_*/{wrap}_*"
        for p in sorted(_g.glob(pat)):
            if "spliced" in p:        # variante costurada, nao a do fit
                continue
            if os.path.isfile(f"{p}/x.tif"):
                return p
    return None


# ---------------------------------------------------------- volpkg --
RE_PHERC = re.compile(r"PHerc\s*([0-9]{4}[A-Za-z]?)", re.I)
# a segment this app (or the pipeline) exported keeps its own name
RE_OURS = re.compile(r"^(?P<rolo>[0-9A-Za-z]+)_z(?P<z0>\d+)_(?P<w>w\d+)$")


def _volpkg_scroll(vp: str) -> core.Scroll | None:
    """Which scroll a volpkg belongs to, read from volumes/*/meta.json.

    The patch's own meta.json does not say: auto_grown writes
    "scroll_source": "s1_2um_ds2", the team's jargon. The volume meta does.
    In teste.volpkg (23/09) the volume uuid 20250521135224 is the prefix of
    the zarr name in SCROLLS, and the name "PHerc0800 8.64um remoto" carries
    the label. The uuid is tried first, the name second, the folder last.
    """
    vols = os.path.join(vp, "volumes")
    if not os.path.isdir(vols):
        return None
    for vd in sorted(os.listdir(vols)):
        mp = os.path.join(vols, vd, "meta.json")
        if not os.path.isfile(mp):
            continue
        try:
            with open(mp, encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        uuid = str(meta.get("uuid", "")).strip()
        if uuid:
            for s in core.SCROLLS.values():
                if s.volume.startswith(uuid):
                    return s
        for text in (str(meta.get("name", "")), vd):
            m = RE_PHERC.search(text)
            if m and m.group(1) in core.SCROLLS:
                return core.SCROLLS[m.group(1)]
    return None


def _scan_volpkg(vp: str, out: dict) -> None:
    """A VC3D volume package: paths/<uuid>/ with x, y, z and meta.json.

    GrowPatch, point_strip and the segments the pipeline exports are all
    QuadSurface tifxyz with scale 0.05 — the same contract as the flattened
    meshes, so gera_mid reads them as they are (checked on 23/09 against
    teste.volpkg/paths/0800_z14672_w020 and spiral-dataset patches).

    A patch has no window or wrap in its name: the window is the z centre of
    its bbox, the wrap is its uuid. A segment named like ours
    (<rolo>_z<Z0>_w<NNN>) keeps that identity, so it merges with the
    pipeline's unit instead of showing up twice.
    """
    s = _volpkg_scroll(vp)
    if s is None:
        print(f"sources: {vp}: no known scroll in volumes/*/meta.json, skipped")
        return
    paths = os.path.join(vp, "paths")
    if not os.path.isdir(paths):
        return
    for name in sorted(os.listdir(paths)):
        d = os.path.join(paths, name)
        if not os.path.isfile(os.path.join(d, "x.tif")):
            continue
        meta: dict = {}
        mp = os.path.join(d, "meta.json")
        if os.path.isfile(mp):
            try:
                with open(mp, encoding="utf-8") as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, OSError):
                meta = {}
        uuid = str(meta.get("uuid") or name)
        m = RE_OURS.match(uuid)
        if m and m.group("rolo") == s.name:
            window, wrap = int(m.group("z0")), m.group("w")
        else:
            try:
                bb = meta["bbox"]
                window = int(round((float(bb[0][2]) + float(bb[1][2])) / 2))
            except (KeyError, IndexError, TypeError, ValueError):
                window = 0
            wrap = uuid
        area = meta.get("area_cm2")
        if area is None and meta.get("area_vx2") is not None:
            # area_vx2 is in volume voxels (the segment in teste.volpkg has
            # only this field); voxel_um / 10_000 is centimetres per voxel
            area = float(meta["area_vx2"]) * (s.voxel_um / 10_000.0) ** 2
        key = f"{s.name}/z{window}/{wrap}"
        u = out.get(key)
        if u is None:
            u = Unit(scroll=s.name, window=window, wrap=wrap, origin="patch",
                     note=str(meta.get("source", "")))
            out[key] = u
        if not u.mesh_dir:
            u.mesh_dir = d
        if u.area_cm2 is None and area is not None:
            u.area_cm2 = float(area)


def _scan_folder(root: str, out: dict) -> None:
    """One folder: meshes in PHerc*/z*_w*/ and ink maps in PHerc*/*.tif."""
    mesh_root = root
    if os.path.isdir(os.path.join(root, "meshes")):
        mesh_root = os.path.join(root, "meshes")
    ink = root

    if os.path.isdir(mesh_root):
        for sd in sorted(os.listdir(mesh_root)):
            if not sd.startswith("PHerc"):
                continue
            scroll = sd[5:]
            for md in sorted(os.listdir(f"{mesh_root}/{sd}")):
                if "_w" not in md or not md.startswith("z"):
                    continue
                z, w = md.split("_", 1)
                d = f"{mesh_root}/{sd}/{md}"
                if not os.path.isfile(f"{d}/x.tif"):
                    continue
                u = Unit(scroll=scroll, window=int(z[1:]), wrap=w,
                         origin="local", mesh_dir=d)
                out[u.id] = u

    if os.path.isdir(ink):
        for sd in sorted(os.listdir(ink)):
            if not sd.startswith("PHerc"):
                continue
            scroll = sd[5:]
            for fn in sorted(os.listdir(f"{ink}/{sd}")):
                if not fn.endswith(".tif"):
                    continue
                stem = fn[:-4]
                rev = stem.endswith("_reverse")
                if rev:
                    stem = stem[:-8]
                if "_w" not in stem:
                    continue
                z, w = stem.split("_", 1)
                key = f"{scroll}/z{int(z[1:])}/{w}"
                u = out.get(key)
                if u is None:
                    u = Unit(scroll=scroll, window=int(z[1:]), wrap=w,
                             origin="local")
                    out[key] = u
                # no --flip-normals in this pipeline, so the file named
                # "_reverse" is the team's forward direction
                p = f"{ink}/{sd}/{fn}"
                if rev:
                    u.ink_forward = p
                else:
                    u.ink_reverse = p


# --------------------------------------------------------------- merged --
@dataclass
class Catalog:
    cache: core.Cache = field(default_factory=core.Cache)
    units: dict[str, Unit] = field(default_factory=dict)

    def load(self, want_public: bool = True) -> "Catalog":
        # local first, so a mesh already here wins over the same one remote
        for u in local_units():
            self.units[u.id] = u
        if want_public:
            try:
                for u in public_index(self.cache):
                    got = self.units.get(u.id)
                    if got is None:
                        self.units[u.id] = u
                    else:
                        got.area_cm2 = got.area_cm2 or u.area_cm2
                        got.screened = got.screened or u.screened
                        got.mesh_rel = got.mesh_rel or u.mesh_rel
                        got.ink_forward = got.ink_forward or u.ink_forward
                        got.ink_reverse = got.ink_reverse or u.ink_reverse
            except RuntimeError:
                pass          # offline: local only, and the UI says so
        # flattened views this app made itself (flat.py), for meshes that
        # came without one — the package is meshes only
        d = self.cache.path("mid", "x")
        d = os.path.dirname(d)
        if os.path.isdir(d):
            for u in self.units.values():
                if u.mid:
                    continue
                p = os.path.join(d, f"{u.slug}.tif")
                if os.path.isfile(p):
                    u.mid = p
        return self

    def by_scroll(self) -> dict[str, list[Unit]]:
        out: dict[str, list[Unit]] = {}
        for u in self.units.values():
            out.setdefault(u.scroll, []).append(u)
        for v in out.values():
            v.sort(key=lambda u: (u.window, u.wrap))
        return out

    def summary(self) -> dict:
        here = sum(1 for u in self.units.values() if u.here)
        return {"units": len(self.units), "here": here,
                "scrolls": len(self.by_scroll())}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--fetch", metavar="ID", help="e.g. 0800/z5664/w020")
    a = ap.parse_args()

    cat = Catalog().load()
    s = cat.summary()
    print(f"{s['units']} units across {s['scrolls']} scrolls; "
          f"{s['here']} already on this machine")
    for scroll, us in sorted(cat.by_scroll().items()):
        here = sum(1 for u in us if u.here)
        ink = sum(1 for u in us if u.ink_forward or u.ink_reverse)
        print(f"  {scroll:7} {len(us):4d} units  {here:4d} local  "
              f"{ink:4d} with ink")

    if a.fetch:
        u = cat.units.get(a.fetch)
        if not u:
            raise SystemExit(f"no such unit: {a.fetch}")
        print(f"\nfetching {u.id}")
        d = fetch_mesh(u, cat.cache,
                       lambda i, n: print(f"  mesh {i}/{n}"))
        print("  mesh:", d)
        p = fetch_ink(u, cat.cache, "forward",
                      lambda g, t: print(f"\r  ink {100*g/t:.0f}%", end=""))
        print("\n  ink:", p)


if __name__ == "__main__":
    main()
