#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "zarr<3", "s3fs", "scipy"]
# ///
"""
gera_umbilicus.py — the scroll axis, from the CT

WHAT IT DOES
Estimates an umbilicus (the scroll's winding axis) directly from the raw CT,
with no annotation and no learned model. Sheet normals come from the structure
tensor; the centre of each slice is the point that minimises squared distance
to those normal lines, solved with Huber IRLS.

Output is the same JSON the spiral fit reads: control points {x, y, z, score}.

HOW GOOD IT IS
Median error against human annotation, same parameters on every scroll:

    PHerc0125     314 vox  (2.94 mm at 9.362 um)
    PHercParis4   133 vox  (0.32 mm at 2.400 um)

It does NOT match a careful manual annotation, and it does not pass the
community's polar-coherence ruler (it beats the best vertical in 3 of 18
slices, against 62% for a manual one). What it does is converge: in seven
windows of PHerc0125 the spiral fit gave the same winding range from this axis
as from the annotated one, with equal or lower mask escape.

Those are different questions. This file answers the second.

THE score FIELD
Carries the anisotropy of that slice's normal matrix, 0-1. It is NOT the flat
100 that human annotations stamp. Low-score slices are the first suspects if
something fails downstream — and the median score appears to anticipate how
good the resulting surface will be, which is useful because it takes minutes
and the surface takes hours.

    PHerc0175B  score 0.897  ->  mask escape ~0.00%
    PHerc0175A  score 0.710  ->  mask escape 3.08%

THE PYRAMID LEVEL IS NOT log2 OF THE SCALE
The factor between the level you read and the scroll's coordinate system is
not always 2**level. PHercParis4's level 0 has 75,784 slices, but its
umbilicus only goes to z=18,240 — which fits level 2. Read the table below,
and for a new scroll check where the umbilicus z ends and which level has that
many slices before assuming.

ADDING A SCROLL
Add an entry to ROLOS with its zarr path, voxel size, the pyramid level to
read, and the scale between that level and the scroll's coordinate system.
Only scrolls actually tested are listed; the rest of the eligible set has
published tracks and would presumably work, but has not been run.

Usage:
    uv run gera_umbilicus.py --rolo 0175B --z0 4600 --z1 11000
    uv run gera_umbilicus.py --rolo Paris4 --z0 7200 --z1 12000 --passo 200
    uv run gera_umbilicus.py --rolo 0125 --z0 5800 --z1 18000 --humano <path>
"""

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone

import numpy as np
import s3fs
import zarr
from scipy import ndimage as ndi

BUCKET = "vesuvius-challenge-open-data"

# nivel:  pyramid level the tensor runs on
# escala: factor between that level and the scroll's coordinate system.
#         NOT 2**nivel — see the note above.
ROLOS = {
    "0125": dict(
        nome="PHerc0125", um=9.362, nivel=2, escala=4,
        zarr="PHerc0125/volumes/20250821151825-9.362um-1.2m-113keV-masked.zarr"),
    "0175A": dict(
        nome="PHerc0175A", um=8.640, nivel=2, escala=4,
        zarr="PHerc0175A/volumes/20250521115057-8.640um-1.2m-116keV-masked.zarr"),
    "0175B": dict(
        nome="PHerc0175B", um=8.640, nivel=2, escala=4,
        zarr="PHerc0175B/volumes/20250521125822-8.640um-1.2m-116keV-masked.zarr"),
    "0343": dict(
        nome="PHerc0343", um=8.640, nivel=2, escala=4,
        zarr="PHerc0343/volumes/20250521140437-8.640um-1.2m-116keV-masked.zarr"),
    "Paris4": dict(
        nome="PHercParis4", um=2.400, nivel=4, escala=4,
        zarr="PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr"),
}

MASK_THR = 10.0
COER_MIN = 0.2          # low cutoff wins: many mediocre normals beat few great ones
SIGMA_TENSOR = 2.0      # small window wins, for the same reason
MAX_PONTOS = 60000


def normais_tensor(img, sigma_grad=1.0, sigma_ten=SIGMA_TENSOR,
                   coer_min=COER_MIN, max_pontos=MAX_PONTOS, rng=None):
    """2D sheet normals on one slice, from the structure tensor."""
    im = ndi.gaussian_filter(img.astype(np.float32), sigma_grad)
    gy, gx = np.gradient(im)
    Jxx = ndi.gaussian_filter(gx * gx, sigma_ten)
    Jxy = ndi.gaussian_filter(gx * gy, sigma_ten)
    Jyy = ndi.gaussian_filter(gy * gy, sigma_ten)

    tr = Jxx + Jyy
    dif = np.sqrt(np.maximum(0.0, (Jxx - Jyy) ** 2 + 4.0 * Jxy ** 2))
    l1 = 0.5 * (tr + dif)
    coer = np.where(tr > 1e-12, dif / np.maximum(tr, 1e-12), 0.0)

    nx = Jxy
    ny = l1 - Jxx
    norma = np.hypot(nx, ny)
    degen = norma < 1e-9
    nx = np.where(degen, 1.0, nx / np.maximum(norma, 1e-12))
    ny = np.where(degen, 0.0, ny / np.maximum(norma, 1e-12))

    bom = (img > MASK_THR) & (coer >= coer_min) & (l1 > 1e-6)
    ys, xs = np.nonzero(bom)
    if len(xs) < 500:
        return None, None, None
    if len(xs) > max_pontos:
        rng = rng or np.random.default_rng(12345)
        idx = rng.choice(len(xs), max_pontos, replace=False)
        ys, xs = ys[idx], xs[idx]

    P = np.stack([xs.astype(np.float64), ys.astype(np.float64)], 1)
    N = np.stack([nx[ys, xs], ny[ys, xs]], 1).astype(np.float64)
    W = coer[ys, xs].astype(np.float64)
    return P, N, W


def resolve_lsq(P, N, W):
    """Point minimising weighted squared distance to the normal lines."""
    a = 1.0 - N[:, 0] ** 2
    b = -N[:, 0] * N[:, 1]
    c = 1.0 - N[:, 1] ** 2
    A11 = np.sum(W * a); A12 = np.sum(W * b); A22 = np.sum(W * c)
    B1 = np.sum(W * (a * P[:, 0] + b * P[:, 1]))
    B2 = np.sum(W * (b * P[:, 0] + c * P[:, 1]))
    det = A11 * A22 - A12 * A12
    if abs(det) < 1e-9:
        return None, 0.0
    cx = (B1 * A22 - B2 * A12) / det
    cy = (A11 * B2 - A12 * B1) / det
    tr = A11 + A22
    dif = math.sqrt(max(0.0, (A11 - A22) ** 2 + 4 * A12 * A12))
    lmax = 0.5 * (tr + dif); lmin = 0.5 * (tr - dif)
    return np.array([cx, cy]), (lmin / lmax if lmax > 0 else 0.0)


def dist_retas(P, N, c):
    d = c[None, :] - P
    along = np.sum(d * N, 1)
    perp = d - along[:, None] * N
    return np.hypot(perp[:, 0], perp[:, 1])


def resolve_robusto(P, N, W, iters=12):
    """Same solve, reweighted by Huber on distance to the lines."""
    c, cond = resolve_lsq(P, N, W)
    if c is None:
        return None, 0.0, np.nan
    for _ in range(iters):
        d = dist_retas(P, N, c)
        k = 1.5 * max(1.0, float(np.median(d)))
        w = W * np.where(d <= k, 1.0, k / np.maximum(d, 1e-9))
        cn, cond = resolve_lsq(P, N, w)
        if cn is None:
            break
        if np.hypot(*(cn - c)) < 0.05:
            c = cn
            break
        c = cn
    rms = float(np.sqrt(np.mean(dist_retas(P, N, c) ** 2)))
    return c, cond, rms


def mediana_movel(vals, jan=5):
    out, n = [], len(vals)
    for i in range(n):
        a = max(0, i - jan // 2)
        b = min(n, i + jan // 2 + 1)
        out.append(float(np.median(vals[a:b])))
    return out


def interp_humano(cp, z):
    """Linear interpolation of a reference umbilicus at height z."""
    zs = [p["z"] for p in cp]
    if z < zs[0] or z > zs[-1]:
        return None
    for i in range(len(cp) - 1):
        if cp[i]["z"] <= z <= cp[i + 1]["z"]:
            a, b = cp[i], cp[i + 1]
            if b["z"] == a["z"]:
                return float(a["x"]), float(a["y"])
            t = (z - a["z"]) / (b["z"] - a["z"])
            return (a["x"] + t * (b["x"] - a["x"]),
                    a["y"] + t * (b["y"] - a["y"]))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rolo", required=True,
                    help="one of " + ", ".join(sorted(ROLOS)) + ", or any "
                         "scroll id with --zarr and --um (Volumen pipeline)")
    ap.add_argument("--zarr", default=None,
                    help="bucket path of the volume, e.g. PHerc0826/volumes/<id>.zarr")
    ap.add_argument("--um", type=float, default=None, help="voxel size in um")
    ap.add_argument("--z0", type=int, required=True)
    ap.add_argument("--z1", type=int, required=True)
    ap.add_argument("--passo", type=int, default=100)
    ap.add_argument("--coer", type=float, default=COER_MIN)
    ap.add_argument("--sigma", type=float, default=SIGMA_TENSOR)
    ap.add_argument("--humano", default=None,
                    help="reference umbilicus JSON, to report per-slice error")
    ap.add_argument("--saida", default=None)
    args = ap.parse_args()

    if args.rolo in ROLOS:
        cfg = ROLOS[args.rolo]
    elif args.zarr and args.um:
        # ~9 um scrolls: level 2 (as the four eligible entries above)
        cfg = dict(nome=f"PHerc{args.rolo}", um=args.um, nivel=2, escala=4,
                   zarr=args.zarr)
    else:
        ap.error(f"{args.rolo} is not in ROLOS; pass --zarr and --um")
    nome, escala, nivel = cfg["nome"], cfg["escala"], cfg["nivel"]
    saida = args.saida or f"umbilici_auto/{nome}_umbilicus_auto.json"

    fs = s3fs.S3FileSystem(anon=True)
    arr = zarr.open(s3fs.S3Map(root=f"{BUCKET}/{cfg['zarr']}/{nivel}", s3=fs,
                               check=False), mode="r")

    cp_hum = None
    if args.humano and os.path.exists(args.humano):
        cp_hum = json.load(open(args.humano))["control_points"]

    print(f"{nome}  voxel {cfg['um']} um  level {nivel} (scale {escala}x)")
    print(f"  CT {arr.shape}   z [{args.z0}, {args.z1}) step {args.passo}")
    print(f"  coherence >= {args.coer}  sigma {args.sigma}")
    cab = f"  {'z':>6} {'x':>7} {'y':>7} {'score':>6} {'rms px':>7}"
    print(cab + (f" {'err ref':>8}" if cp_hum else ""))

    zs, xs, ys, conds, erros = [], [], [], [], []
    t0 = time.time()
    for z in range(args.z0, args.z1 + 1, args.passo):
        zl = int(round(z / escala))
        if zl >= arr.shape[0]:
            continue
        img = np.asarray(arr[zl], dtype=np.float32)
        P, N, W = normais_tensor(img, sigma_ten=args.sigma, coer_min=args.coer)
        if P is None:
            print(f"  {z:6}  too little tissue — skipped")
            continue
        c, cond, rms = resolve_robusto(P, N, W)
        if c is None:
            print(f"  {z:6}  singular — skipped")
            continue
        x0, y0 = float(c[0]) * escala, float(c[1]) * escala
        if not (0 <= x0 < arr.shape[2] * escala and
                0 <= y0 < arr.shape[1] * escala):
            print(f"  {z:6}  centre outside the volume — skipped")
            continue
        zs.append(z); xs.append(x0); ys.append(y0); conds.append(cond)

        e = ""
        if cp_hum:
            h = interp_humano(cp_hum, z)
            if h:
                d = math.hypot(x0 - h[0], y0 - h[1])
                erros.append(d)
                e = f"{d:8.0f}"
        print(f"  {z:6} {x0:7.0f} {y0:7.0f} {cond:6.3f} {rms:7.0f} {e:>8}",
              flush=True)

    if not zs:
        print("no slice estimated")
        return

    sx = mediana_movel(xs, 5)
    sy = mediana_movel(ys, 5)
    desv = [math.hypot(a - b, c - d) for a, b, c, d in zip(xs, sx, ys, sy)]
    cps = [{"x": int(round(x)), "y": int(round(y)), "z": int(z),
            "score": round(float(cd), 4)}
           for z, x, y, cd in zip(zs, sx, sy, conds)]

    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {
        "control_points": cps,
        "metadata": {
            "z_grid_spacing": args.passo,
            "min_score_threshold": 0.75,
            "high_score_threshold": 0.75,
            "total_points": len(cps),
            "timestamp": agora, "created": agora, "modified": agora,
            "source_volume": cfg["zarr"],
            "voxelsize_um": cfg["um"],
            "annotator_note": (
                "AUTOMATIC, NOT HAND-ANNOTATED. Structure-tensor sheet normals "
                f"from raw CT (pyramid level {nivel}); centre by least squares "
                "over the normal lines with Huber IRLS. Same parameters on "
                "every scroll, none tuned per scroll. score = anisotropy of "
                "the fit's normal matrix, not a human confidence."
            ),
        },
    }
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    json.dump(doc, open(saida, "w"), indent=1)

    zz = sorted(zs)
    sc = sorted(conds)
    print(f"\n  smoothing (5-point median): median shift {np.median(desv):.0f} "
          f"vox, max {max(desv):.0f}")
    print(f"  {len(cps)} points -> {saida}  ({time.time()-t0:.0f}s)")
    print(f"  median z = {zz[len(zz)//2]}")
    print(f"  score: min {sc[0]:.3f}  median {sc[len(sc)//2]:.3f}  "
          f"max {sc[-1]:.3f}")
    if erros:
        es = sorted(erros)
        n = len(es)
        m = es[n // 2] if n % 2 else (es[n // 2 - 1] + es[n // 2]) / 2
        print(f"  error vs reference: median {m:.0f} vox "
              f"({m * cfg['um'] / 1000:.2f} mm), min {es[0]:.0f}, "
              f"max {es[-1]:.0f}")
    print("\n  low-score slices are the first suspects if the fit misbehaves.")


if __name__ == "__main__":
    main()
