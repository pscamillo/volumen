"""
core.py — engine for the scroll reading app.

UI-independent. Everything here is plain Python: scale tables, bucket paths,
volume access, local cache. The Qt layer (or a future web layer) sits on top
and never talks to S3 directly.

--------------------------------------------------------------------------
WHY THE FETCHING LOOKS LIKE THIS
--------------------------------------------------------------------------

The bottleneck is LATENCY, not bandwidth. Zarr chunks are small files; a
serial loop spends its life waiting on round trips. Measured on this
pipeline: fetching only the chunks a surface actually touches, in parallel,
did 1000 chunks in 60 s where asking for the bounding box took hours. A mesh
of one winding spans the whole scroll diameter, so its bounding box is
~200 x 2000 x 2000 voxels at level 2 — almost all of it air.

Anonymous S3 also throttles PER CONNECTION, not globally: measured at
~95 KB/s on one connection and ~57 MB/s across 32. So the worker count is
not a politeness dial — it is the bandwidth dial. Default 32.

So: never ask for a bounding box. Collect the sample points, deduplicate the
chunks they touch, fetch those in parallel.

MISSING CHUNKS ARE SILENT. Roughly 19% of chunks do not exist in the bucket
for some scrolls (measured: 2975 of 15772 on one volume), and zarr fills them
with zeros without raising. In-bounds zeros pass for valid data. Every fetch
here reports coverage so the UI can say "this region has no scan data"
instead of showing a black image.

THE SCALE TABLE COMES FROM THE PRIZE PAGE AND THE BUCKET, never from render
scripts: one local script still points at a volume name that no longer
exists, because the file was renamed in the bucket with the same timestamp.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable

import numpy as np

BUCKET = "s3://vesuvius-challenge-open-data"
HTTP = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"

DEFAULT_CACHE = os.path.expanduser("~/.cache/volumen")

# Anonymous S3 throttles per connection, so this is the
# bandwidth dial. Measured: ~95 KB/s at 1, ~57 MB/s at 32.
WORKERS = 32


@dataclass(frozen=True)
class Scroll:
    """One scroll the app can open."""
    name: str                 # "0175B"
    volume: str               # zarr directory name in volumes/
    voxel_um: float           # native voxel size of that volume
    eligible: bool            # First Letters eligible
    route: str                # "lasagna" | "no lasagna" | "no tracks" | "demo"
    note: str = ""

    @property
    def label(self) -> str:
        return f"PHerc{self.name}"

    @property
    def volume_url(self) -> str:
        return f"{BUCKET}/{self.label}/volumes/{self.volume}"


# The 23 First Letters eligible volumes, plus two already-read scrolls used
# for the demo. Voxel sizes verified against the bucket on 19/09/2026.
SCROLLS: dict[str, Scroll] = {
    s.name: s for s in [
        Scroll("0125", "20250821151825-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "lasagna"),
        Scroll("0175A", "20250521115057-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "no lasagna"),
        Scroll("0175B", "20250521125822-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "no lasagna"),
        Scroll("0191", "20250821151635-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "lasagna"),
        Scroll("0211", "20250821151803-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "lasagna"),
        Scroll("0257", "20250821151750-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "lasagna"),
        Scroll("0268", "20251110183117-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "lasagna"),
        Scroll("0306B", "20250521133212-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "no lasagna"),
        Scroll("0343", "20250521140437-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "lasagna"),
        Scroll("0358", "20250821151737-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "lasagna"),
        Scroll("0483A", "20250521140913-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "no lasagna"),
        Scroll("0483B", "20251124083638-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "no lasagna"),
        Scroll("0490A", "20250521151210-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "no lasagna"),
        Scroll("0490B", "20250521151215-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "no lasagna"),
        Scroll("0800", "20250521135224-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "lasagna"),
        Scroll("0813", "20250821151723-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "lasagna"),
        Scroll("0826", "20250821151701-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "lasagna"),
        Scroll("0846A", "20250728152254-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "no lasagna",
               "also scanned at 2.403 um — prize rules forbid using data "
               "derived from a higher-resolution scan of the same scroll"),
        Scroll("0846B", "20250804142305-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "no tracks",
               "no published tracks, so the minimal route cannot start here"),
        Scroll("1203", "20250820131727-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "lasagna",
               "also scanned at 2.403 um — same restriction as PHerc0846A"),
        Scroll("1218", "20250521120456-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "lasagna"),
        Scroll("1447", "20250521151220-8.640um-1.2m-116keV-masked.zarr",
               8.640, True, "lasagna"),
        Scroll("1545", "20250821151648-9.362um-1.2m-113keV-masked.zarr",
               9.362, True, "lasagna"),
        # already read — demo only, never prize targets
        Scroll("Paris4", "20260411134726-2.400um-0.2m-78keV-masked.zarr",
               2.400, False, "demo",
               "the scroll people have actually read; its 2.4 um scan is "
               "finer than anything the eligible volumes have"),
        Scroll("0139", "20250728140407-9.362um-1.2m-113keV-masked.zarr",
               9.362, False, "demo",
               "ink is annotated here; used to show what a positive looks "
               "like and to check the detector is working"),
    ]
}

ELIGIBLE = [s for s in SCROLLS.values() if s.eligible]
DEMO = [s for s in SCROLLS.values() if s.route == "demo"]


# ---- lasagna published in the open-data bucket (25/09) ------------------
# The team publishes lasagna when it is ready, so which scrolls have it is
# asked of the bucket, not written here: at most once a day, cached, and
# without the network the last answer (or the table above) stands.
_LAS_BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
LASAGNA_CACHE = os.path.expanduser("~/.cache/volumen/lasagna.json")


def _lasagna_id(name: str) -> str | None:
    """Newest lasagna directory for PHerc<name>, None if there is none.
    Network errors propagate: an unknown answer is not a "no"."""
    import re, urllib.request
    url = (f"{_LAS_BUCKET}/?list-type=2&prefix=PHerc{name}/representations/"
           "predictions/lasagna/&delimiter=/")
    with urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "Volumen"}), timeout=20) as r:
        xml = r.read().decode()
    ids = re.findall(r"lasagna/([0-9]+-lasagna-[0-9]+)/</Prefix>", xml)
    return sorted(ids)[-1] if ids else None


def lasagna_published(network: bool = True,
                      max_age_h: float = 24.0) -> dict[str, str] | None:
    """{scroll: lasagna id} for the eligible scrolls that have tracks.
    None when nothing is known yet (no cache and no network)."""
    import json, time
    cached = None
    try:
        with open(LASAGNA_CACHE, encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, ValueError):
        pass
    fresh = cached and time.time() - cached.get("checked", 0) < max_age_h * 3600
    if fresh or not network:
        return cached["scrolls"] if cached else None
    names = [s.name for s in ELIGIBLE if s.route in ("lasagna", "no lasagna")]
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            got = dict(zip(names, ex.map(_lasagna_id, names)))
    except Exception:
        return cached["scrolls"] if cached else None
    scrolls = {k: v for k, v in got.items() if v}
    try:
        os.makedirs(os.path.dirname(LASAGNA_CACHE), exist_ok=True)
        tmp = LASAGNA_CACHE + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"checked": time.time(), "scrolls": scrolls}, f, indent=1)
        os.replace(tmp, LASAGNA_CACHE)
    except OSError:
        pass
    return scrolls


def apply_lasagna(published: dict[str, str] | None) -> list[str]:
    """Reclassify scrolls by what the bucket says; returns the ones that
    gained lasagna. Scroll is frozen, so each is replaced by a copy, in
    place in ELIGIBLE and SCROLLS."""
    import dataclasses
    if published is None:
        return []
    gained = []
    for i, s in enumerate(ELIGIBLE):
        if s.route not in ("lasagna", "no lasagna"):
            continue
        r = "lasagna" if s.name in published else "no lasagna"
        if r != s.route:
            if r == "lasagna":
                gained.append(s.name)
            ns = dataclasses.replace(s, route=r)
            ELIGIBLE[i] = ns
            SCROLLS[s.name] = ns
    return gained


# at import: the cached answer only, never the network
apply_lasagna(lasagna_published(network=False))

# Typical Greek letter height in these scrolls, in micrometres. Used to draw
# a size reference: without one it is easy to call something a letter when it
# is off by a factor of five.
#
# Measured 23/09/2026 on the PHerc Paris 4 ink map, the one scroll that has
# been read: connected components of the bright marks, at three brightness
# thresholds, on the ds8 jpeg (19.2 um per pixel). Median 384-422 um (many
# components are fragments of a letter), third quartile 595-710, p90 920-1070
# (whole letters and letters stuck together). 700 sits in the third quartile.
# Repeated on PHerc0139 (also read, also ds8): median 365-461, third quartile
# 653-672, p90 979-1036. The two scrolls agree, which is what gives the number
# its weight — one measurement would only describe Paris 4.
#
# The 1500 inherited from juiz.py had no recorded source and drew a box above
# even the p90.
#
# Sanity check on an eligible scroll (0268 z3872 w060, 23/09): mask area
# 4.79 cm2 against 4.91 in the flatten meta.json, so the scale holds end to
# end. On that surface the bright blobs in the ink map run several mm — five
# to ten letters wide. That is the box doing its job.
LETTER_UM = 700.0

# Sheet spacing, micrometres. Physical invariant, independent of any config —
# useful as a sanity check on any coordinate scale.
SHEET_SPACING_UM = (120.0, 260.0)


# --------------------------------------------------------------- volumes --
_open_lock = threading.Lock()
_open_volumes: dict[tuple[str, int], object] = {}


def http_url(url: str) -> str:
    """s3:// to a plain https GET. The bucket is public, and s3fs costs
    dearly per access: measured 23/09 on 0800, 48 chunks with 32 threads,
    43 MB/s over https against 7 MB/s through s3fs."""
    if url.startswith("s3://"):
        bucket, rest = url[5:].split("/", 1)
        return f"https://{bucket}.s3.us-east-1.amazonaws.com/{rest}"
    return url


def open_volume(scroll: Scroll, level: int = 0):
    """Open one pyramid level of a scroll volume, read-only, anonymous.

    Level 0 is native. Each level halves each dimension, so level 1 is 8x
    less data. For anything that does not need native resolution, use a
    higher level — it is the single biggest saving available.
    """
    key = (scroll.name, level)
    with _open_lock:
        if key in _open_volumes:
            return _open_volumes[key]
    import zarr
    # https instead of s3fs: measured 23/09 on 0800, 48 chunks with 32
    # threads, 43 MB/s over https against 7 MB/s through s3fs. The bucket
    # is public and serves plain GET, so there is nothing s3fs buys here.
    arr = zarr.open(http_url(f"{scroll.volume_url}/{level}"), mode="r")
    with _open_lock:
        _open_volumes[key] = arr
    return arr


@dataclass
class Coverage:
    """What a fetch actually got. Missing chunks read as zeros in zarr."""
    chunks_asked: int = 0
    chunks_empty: int = 0
    seconds: float = 0.0

    @property
    def fraction_empty(self) -> float:
        return (self.chunks_empty / self.chunks_asked
                if self.chunks_asked else 0.0)

    @property
    def warning(self) -> str | None:
        f = self.fraction_empty
        if f > 0.5:
            return ("Most of this region has no scan data. What you see is "
                    "not a dark scroll — it is absence of data.")
        if f > 0.1:
            return (f"{f*100:.0f}% of this region has no scan data; those "
                    "parts read as black.")
        return None


def _chunk_bounds(arr, idx: tuple[int, ...]) -> tuple[slice, ...]:
    return tuple(slice(i * c, min((i + 1) * c, s))
                 for i, c, s in zip(idx, arr.chunks, arr.shape))


def fetch_chunks(arr, chunk_ids: Iterable[tuple[int, ...]], workers: int = WORKERS,
                 progress: Callable[[int, int], None] | None = None
                 ) -> tuple[dict, Coverage]:
    """Fetch the given chunks in parallel. Returns {chunk_id: ndarray}.

    Parallelism is the whole point: these are small files and the cost is
    round trips, not bytes.
    """
    import time
    ids = list(dict.fromkeys(chunk_ids))
    out: dict[tuple[int, ...], np.ndarray] = {}
    cov = Coverage(chunks_asked=len(ids))
    t0 = time.time()

    def one(idx):
        return idx, np.asarray(arr[_chunk_bounds(arr, idx)])

    done = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for idx, block in ex.map(one, ids):
            out[idx] = block
            if block.size and block.max() == 0:
                cov.chunks_empty += 1
            done += 1
            if progress and done % 25 == 0:
                progress(done, len(ids))
    cov.seconds = time.time() - t0
    if progress:
        progress(len(ids), len(ids))
    return out, cov


def chunks_for_points(arr, pts: np.ndarray) -> list[tuple[int, ...]]:
    """Chunk ids touched by a set of (z, y, x) points.

    This is the function that replaces asking for a bounding box.
    """
    c = np.asarray(arr.chunks)
    idx = np.floor_divide(np.asarray(pts), c).astype(np.int64)
    idx = np.unique(idx, axis=0)
    return [tuple(int(v) for v in row) for row in idx]


def sample_points(arr, pts: np.ndarray, workers: int = WORKERS,
                  progress: Callable[[int, int], None] | None = None
                  ) -> tuple[np.ndarray, Coverage]:
    """Value of the volume at each (z, y, x) point, nearest voxel.

    Fetches only the chunks those points touch.
    """
    pts = np.asarray(pts)
    ok = np.all((pts >= 0) & (pts < np.asarray(arr.shape)), axis=1)
    vals = np.zeros(len(pts), dtype=np.float32)
    if not ok.any():
        return vals, Coverage()
    good = pts[ok].astype(np.int64)
    ids = chunks_for_points(arr, good)
    blocks, cov = fetch_chunks(arr, ids, workers, progress)
    c = np.asarray(arr.chunks)
    base = np.floor_divide(good, c)
    local = good - base * c
    # one indexing call per chunk, not per point: the per-point loop cost
    # 118 s for 200k points (measured 23/09), the rest of the fetch 10 s
    got = np.zeros(len(good), dtype=np.float32)
    key = (base[:, 0].astype(np.int64) << 42
           | base[:, 1].astype(np.int64) << 21 | base[:, 2].astype(np.int64))
    ordem = np.argsort(key, kind="stable")
    key_ord = key[ordem]
    corte = np.flatnonzero(np.diff(key_ord)) + 1
    for grupo in np.split(ordem, corte):
        if not len(grupo):
            continue
        blk = blocks.get(tuple(int(v) for v in base[grupo[0]]))
        if blk is None:
            continue
        l = local[grupo]
        dentro = np.all(l < np.asarray(blk.shape), axis=1)
        g, l = grupo[dentro], l[dentro]
        if len(g):
            got[g] = blk[l[:, 0], l[:, 1], l[:, 2]]
    vals[ok] = got
    return vals, cov


def gera_mid(mesh_dir: str, scroll: "Scroll", workers: int = WORKERS,
             progress: Callable[[int, int], None] | None = None
             ) -> tuple[np.ndarray, Coverage]:
    """The flattened CT of a mesh, without VC3D. Same image it renders.

    Measured against vc_render_tifxyz on 0800 z10464 w060 (23/09): 99.7% of
    pixels identical, no pixel off by more than 1 level, identical mask.
    The rules were read from QuadSurface::gen, not guessed:
      - output pixel i samples the grid at (i + 0.5) / step
      - coordinates bilinear with replicated border
      - a point needs its +-1 neighbours: the normal is a central
        difference and without them it is NaN, and the pixel is dropped
        (vc_render_tifxyz.cpp line 208)
      - the four corners of the pixel's bilinear cell must be valid: the
        renderer turns the -1 sentinel into NaN before gen (lines
        1501-1505), so one bad corner makes the coordinate NaN and the
        pixel is skipped (line 201). Without this, 4000 pixels of the
        0800 z14672 w020 mesh were filled from stray coordinates (23/09)
      - truncate to uint8, do not round
    """
    import json
    pts, valid = read_tifxyz(mesh_dir)
    try:
        meta = json.load(open(f"{mesh_dir}/meta.json"))
        step = 1.0 / float(meta["scale"][0])
        # GrowPatch writes scale as float32 (0.05000000074505806, seen in
        # spiral-dataset auto_grown_20260416003400745 on 23/09): 1/scale is
        # 19.9999997, and (i + 0.5) / step drifts by a hundredth of a pixel
        # per row. The grid step is a whole number of voxels; snap to it.
        if abs(step - round(step)) < 1e-4:
            step = float(round(step))
    except Exception:
        step = round(mesh_step_voxels(pts, valid))
    viz = np.zeros_like(valid)
    viz[1:-1, 1:-1] = (valid[1:-1, 1:-1]
                       & valid[:-2, 1:-1] & valid[2:, 1:-1]
                       & valid[1:-1, :-2] & valid[1:-1, 2:])
    H, W = valid.shape
    OH, OW = int(round(H * step)), int(round(W * step))
    u = (np.arange(OH) + 0.5) / step
    v = (np.arange(OW) + 0.5) / step
    u0 = np.clip(np.floor(u).astype(int), 0, H - 2)
    v0 = np.clip(np.floor(v).astype(int), 0, W - 2)
    du = (u - u0)[:, None]
    dv = (v - v0)[None, :]
    coords = np.zeros((OH, OW, 3))
    for k in range(3):
        c = pts[..., k]
        coords[..., k] = (c[np.ix_(u0, v0)] * (1 - du) * (1 - dv)
                          + c[np.ix_(u0, v0 + 1)] * (1 - du) * dv
                          + c[np.ix_(u0 + 1, v0)] * du * (1 - dv)
                          + c[np.ix_(u0 + 1, v0 + 1)] * du * dv)
    un = np.clip(np.rint(u).astype(int), 0, H - 1)
    vn = np.clip(np.rint(v).astype(int), 0, W - 1)
    cantos_ok = (valid[np.ix_(u0, v0)] & valid[np.ix_(u0, v0 + 1)]
                 & valid[np.ix_(u0 + 1, v0)] & valid[np.ix_(u0 + 1, v0 + 1)])
    m = viz[np.ix_(un, vn)] & cantos_ok

    arr = open_volume(scroll, 0)
    img = np.zeros((OH, OW), dtype=np.uint8)
    if not m.any():
        return img, Coverage()
    p = coords[m]
    cantos = [(a_, b_, c_) for a_ in (0, 1) for b_ in (0, 1) for c_ in (0, 1)]
    # in slices, not in one block: numpy holds the GIL while it works, and a
    # single pass over 12 M points froze the window for minutes (23/09)
    FAIXA = 400_000
    out = np.zeros(len(p))
    cov = Coverage()
    for i0 in range(0, len(p), FAIXA):
        parte = p[i0:i0 + FAIXA]
        base = np.floor(parte).astype(np.int64)
        frac = parte - base
        todos = np.concatenate([base + np.array(o) for o in cantos])
        vals, c = sample_points(arr, todos, workers)
        vals = vals.reshape(8, -1)
        acc = np.zeros(len(parte))
        for k, (a_, b_, c_) in enumerate(cantos):
            w = ((frac[:, 0] if a_ else 1 - frac[:, 0])
                 * (frac[:, 1] if b_ else 1 - frac[:, 1])
                 * (frac[:, 2] if c_ else 1 - frac[:, 2]))
            acc += w * vals[k]
        out[i0:i0 + FAIXA] = acc
        cov.chunks_asked += c.chunks_asked
        cov.chunks_empty += c.chunks_empty
        cov.seconds += c.seconds
        if progress:
            progress(min(i0 + FAIXA, len(p)), len(p))
    img[m] = np.clip(np.floor(out), 0, 255).astype(np.uint8)
    return img, cov


def fetch_slice_window(arr, z: int, y0: int, y1: int, x0: int, x1: int,
                       workers: int = WORKERS,
                       progress: Callable[[int, int], None] | None = None
                       ) -> tuple[np.ndarray, Coverage]:
    """A 2D window of one z slice, fetched chunk-wise in parallel.

    Keep the window small. Chunks are 128^3 at level 0, so a 512x512 window
    touches 25 chunks (~4 s); a 2600x2600 window touches 441 (~72 s).
    """
    y0, y1 = max(0, y0), min(arr.shape[1], y1)
    x0, x1 = max(0, x0), min(arr.shape[2], x1)
    cz, cy, cx = arr.chunks
    ids = [(z // cz, yy // cy, xx // cx)
           for yy in range(y0, y1, cy) for xx in range(x0, x1, cx)]
    blocks, cov = fetch_chunks(arr, ids, workers, progress)
    out = np.zeros((y1 - y0, x1 - x0), dtype=np.float32)
    for (iz, iy, ix), blk in blocks.items():
        by, bx = iy * cy, ix * cx
        sub = blk[z - iz * cz]
        ty0, tx0 = max(y0, by), max(x0, bx)
        ty1 = min(y1, by + sub.shape[0])
        tx1 = min(x1, bx + sub.shape[1])
        if ty1 <= ty0 or tx1 <= tx0:
            continue
        out[ty0 - y0:ty1 - y0, tx0 - x0:tx1 - x0] = \
            sub[ty0 - by:ty1 - by, tx0 - bx:tx1 - bx]
    return out, cov


# ----------------------------------------------------------------- mesh --
def read_tifxyz(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Load a tifxyz mesh. Returns (points[h, w, 3] as z,y,x; valid[h, w]).

    The invalid-point sentinel is -1 and the mask must be (x > 0) & (y > 0).
    Testing only for "!= -1" once cost 27% of phantom mask escape here.
    """
    import tifffile
    x = tifffile.imread(f"{path}/x.tif")
    y = tifffile.imread(f"{path}/y.tif")
    z = tifffile.imread(f"{path}/z.tif")
    valid = (x > 0) & (y > 0)
    return np.stack([z, y, x], axis=-1).astype(np.float64), valid


def mesh_step_voxels(pts: np.ndarray, valid: np.ndarray) -> float:
    """Median spacing between neighbouring mesh samples, in voxels.

    Expect ~20: the fitter writes tifxyz with scale 0.05, i.e. one sample
    every 20 voxels. That is a property of the fitter, not a knob.
    """
    d = np.linalg.norm(np.diff(pts, axis=1), axis=-1)
    m = (valid[:, :-1] & valid[:, 1:])
    d = d[m]
    d = d[np.isfinite(d) & (d > 0) & (d < 500)]
    return float(np.median(d)) if d.size else float("nan")


# ---------------------------------------------------------------- cache --
@dataclass
class Cache:
    """Local store. Second look at the same thing must be instant."""
    root: str = DEFAULT_CACHE
    index: dict = field(default_factory=dict)

    def __post_init__(self):
        os.makedirs(self.root, exist_ok=True)
        p = f"{self.root}/index.json"
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    self.index = json.load(f)
            except json.JSONDecodeError:
                self.index = {}

    def path(self, *parts: str) -> str:
        p = os.path.join(self.root, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def note(self, key: str, value) -> None:
        self.index[key] = value
        with open(f"{self.root}/index.json", "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=1)

    def size_gb(self) -> float:
        total = 0
        for dirpath, _, files in os.walk(self.root):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, fn))
                except OSError:
                    pass
        return total / 1e9


# --------------------------------------------------------------- display --
def stretch(a: np.ndarray, lo_pct: float = 2.0, hi_pct: float = 99.0
            ) -> np.ndarray:
    """Percentile stretch to 0..255, ignoring zeros (which mean no data)."""
    a = np.asarray(a, dtype=np.float32)
    m = a > 0
    if m.sum() < 50:
        return np.zeros(a.shape, dtype=np.uint8)
    lo, hi = np.percentile(a[m], [lo_pct, hi_pct])
    if hi <= lo:
        hi = lo + 1.0
    g = np.clip((a - lo) / (hi - lo), 0, 1)
    g[~m] = 0
    return (g * 255).astype(np.uint8)


def letter_box_pixels(voxel_um: float, zoom: float = 1.0) -> float:
    """Screen size of a typical letter, for the on-screen size reference."""
    return (LETTER_UM / voxel_um) * zoom


def mm_bar_pixels(voxel_um: float, zoom: float = 1.0) -> float:
    return (1000.0 / voxel_um) * zoom
