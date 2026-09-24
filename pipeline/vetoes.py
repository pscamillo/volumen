#!/usr/bin/env python3
"""Physics-based false-positive filters for ink probability maps.

Ink detectors trained on texture are fooled by things that are not ink:
compression folds, delamination gaps, void shadows, surface damage. These
filters check each detection against the physics of what carbon ink must
look like in the CT data itself, independent of any model:

1. CT-void veto (needs the surface volume): real ink sits ON papyrus. A
   detection whose mid-depth CT intensity is much darker than its immediate
   surroundings is sitting over a void or damage shadow, not on substrate.
   Component is vetoed when (component mean - annulus mean) <= -void_delta
   in the mid-depth CT average.

2. Raw-darkness sign test (needs a raw intensity composite): carbon ink is
   DARKER than clean papyrus in these scans. Each surviving component's mean
   raw intensity is compared against a wide elliptical annulus (201 px
   kernel) from which ALL detected pixels are excluded, so one detection
   cannot serve as another's "background". Components not significantly
   darker than their annulus (sigma >= sigma_max, default -0.05) are vetoed.
   The large ellipse matters: small square rings can land entirely inside a
   fold's shadow moat and make a bright artifact look "dark".

3. Line-pitch test (report only, never vetoes): written text is organized
   in rows at a regular pitch (2.0-4.5 mm in Herculaneum papyri). The test
   grid-fits surviving component centroids over angle x pitch and compares
   the best residual against a Monte-Carlo null of uniformly random points.
   Low p = row-organized = more likely text. The evidence is one-sided:
   few components cannot pass, and real text mixed with scattered false
   positives dilutes the fit — so a high p argues against text while the
   absence of a low p proves nothing. That is why it reports, never vetoes.

4. Depth-band gate (concept, not implemented here): ink lives in a narrow
   band of layers at the papyrus surface. With a per-layer prediction stack
   (or per-layer raw composites) a detection whose response peaks far from
   the surface band, or is spread evenly over all depths, can be rejected.
   This needs the full layer stack per prediction, which this single-map
   tool does not require; the three filters above run from one probability
   map, one surface volume, and one composite.

Inputs are plain arrays; nothing here depends on which model produced the
probability map.

Usage:
  vetoes.py apply --prob PROB.npy --stack STACK --out PREFIX
      [--th 0.30] [--min-area 300] [--valid VALID.npy]
      [--void-delta 8.0] [--mid 8 20]
      [--raw RAW.png|--raw-from-stack] [--sigma-max -0.05]
      [--voxel-um 9.362] [--n-mc 2000]

  PROB.npy   float (H, W) ink probability map in [0, 1]
  STACK      CT surface volume as (D, H, W): .npy (memmap ok) or a zarr
             directory (first array found)
  VALID.npy  optional bool (H, W); default: max over z of stack > 0
  RAW        optional raw composite image for the darkness test;
             --raw-from-stack uses the mean of the --mid CT window

Writes PREFIX_mask.npy (surviving detection mask), PREFIX_report.json
(fractions and per-stage counts), and prints the report.

Requires: numpy, opencv-python; zarr only when STACK is a zarr.
"""
import argparse
import json
import os

import cv2
import numpy as np


# ---------------------------------------------------------------- components

def components(mask, min_area=300):
    """8-connected components of a boolean mask, keeping those >= min_area px.
    Returns (labels, kept_indices, stats, centroids)."""
    n, lab, stats, cent = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), 8)
    keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_area]
    return lab, keep, stats, cent


# ---------------------------------------------------------------- veto 1: CT void

def ct_void_deltas(lab, keep, stats, stack, mid=(8, 20), pad=60):
    """Per component: mid-depth CT contrast vs a local annulus.

    delta = mean(CT_mid inside component) - mean(CT_mid in annulus).
    Strongly negative = the component is darker than its surroundings in the
    substrate itself = void / damage shadow, not ink on papyrus.
    """
    ctmid = np.asarray(stack[mid[0]:mid[1]], dtype=np.float32).mean(axis=0)
    out = {}
    for i in keep:
        x, y = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1 = min(lab.shape[1], x + w + pad)
        y1 = min(lab.shape[0], y + h + pad)
        sub = lab[y0:y1, x0:x1] == i
        ann = cv2.dilate(sub.astype(np.uint8),
                         np.ones((41, 41), np.uint8)).astype(bool) & ~sub
        if ann.sum() == 0:
            out[i] = 0.0
            continue
        c = ctmid[y0:y1, x0:x1]
        out[i] = float(c[sub].mean() - c[ann].mean())
    return out


# ---------------------------------------------------------------- veto 2: raw darkness

def raw_sigma(comp_mask, raw, all_flagged=None, pad=130):
    """Darkness of a component vs an uncontaminated local background, in annulus sigmas.

    The background is a wide elliptical annulus (201 px kernel) around the
    component, with every flagged pixel (any component's) excluded so that
    detections cannot inflate each other's background. A 41-81 px square
    ring is exploitable: a fold's shadow moat can fill the whole ring and
    make a bright artifact score as "dark". Returns
    (comp mean - annulus mean) / annulus std; ink should be clearly negative.
    """
    ys, xs = np.where(comp_mask)
    y0, y1 = max(0, ys.min() - pad), min(raw.shape[0], ys.max() + pad)
    x0, x1 = max(0, xs.min() - pad), min(raw.shape[1], xs.max() + pad)
    sub = comp_mask[y0:y1, x0:x1]
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (201, 201))
    ann = cv2.dilate(sub.astype(np.uint8), k).astype(bool) & ~sub
    if all_flagged is not None:
        ann &= ~all_flagged[y0:y1, x0:x1]
    if ann.sum() < 50:
        return 0.0
    r = raw[y0:y1, x0:x1].astype(np.float32)
    mu, sd = float(r[ann].mean()), float(r[ann].std() + 1e-6)
    return (float(r[sub].mean()) - mu) / sd


# ---------------------------------------------------------------- test 3: line pitch

def line_pitch_p(cents, voxel_um=9.362, pitch_mm=(2.0, 4.6, 0.25),
                 n_mc=2000, rng_seed=7):
    """Monte-Carlo p-value for row organization of component centroids.

    Projects centroids onto directions 0..180 deg (7.5 deg steps), fits the
    best regular line pitch in [pitch_mm), and compares the residual against
    n_mc uniform-random point sets in the same bounding box. p < 0.05 means
    the detections align in rows like text. Needs >= 4 centroids.
    """
    if len(cents) < 4:
        return None
    vox_mm = voxel_um * 1e-3
    pts = np.array(cents, float)
    rng = np.random.default_rng(rng_seed)

    def best_resid(p):
        best = np.inf
        for ang in np.deg2rad(np.arange(0, 180, 7.5)):
            proj = p[:, 0] * np.sin(ang) + p[:, 1] * np.cos(ang)
            for mm in np.arange(*pitch_mm):
                pitch = mm / vox_mm
                ph = np.mod(proj, pitch) / pitch
                d = np.minimum(ph, 1 - ph)   # distance to nearest line
                best = min(best, float(np.sqrt((d ** 2).mean())))
        return best

    obs = best_resid(pts)
    y0, y1 = pts[:, 0].min(), pts[:, 0].max()
    x0, x1 = pts[:, 1].min(), pts[:, 1].max()
    null = [best_resid(np.column_stack([rng.uniform(y0, y1, len(pts)),
                                        rng.uniform(x0, x1, len(pts))]))
            for _ in range(n_mc)]
    return float((np.array(null) <= obs).mean())


# ---------------------------------------------------------------- pipeline

def apply_vetoes(prob, stack, th=0.30, min_area=300, valid=None,
                 void_delta=8.0, mid=(8, 20), raw=None, sigma_max=-0.05,
                 voxel_um=9.362, n_mc=2000):
    """Threshold -> min-area components -> CT-void veto -> raw-darkness veto
    -> line-pitch report. Returns (surviving_mask, report_dict)."""
    if valid is None:
        valid = np.zeros(prob.shape, bool)
        step = 512
        for y in range(0, prob.shape[0], step):
            valid[y:y + step] = np.asarray(
                stack[:, y:y + step, :]).max(axis=0) > 0
    nval = max(int(valid.sum()), 1)
    m0 = (prob >= th) & valid
    rep = {"th": th, "min_area": min_area, "void_delta": void_delta,
           "mid": list(mid), "sigma_max": sigma_max,
           "valid_px": int(valid.sum()),
           "flagged_frac_raw": float(m0.sum() / nval)}

    lab, keep, stats, cent = components(m0, min_area)
    m1 = np.isin(lab, keep) if keep else np.zeros_like(m0)
    rep["n_components"] = len(keep)
    rep["flagged_frac_minarea"] = float(m1.sum() / nval)

    deltas = ct_void_deltas(lab, keep, stats, stack, mid=mid)
    keep2 = [i for i in keep if deltas[i] > -void_delta]
    m2 = np.isin(lab, keep2) if keep2 else np.zeros_like(m0)
    rep["n_after_void_veto"] = len(keep2)
    rep["flagged_frac_void_veto"] = float(m2.sum() / nval)

    keep3 = keep2
    if raw is not None:
        sig = {i: raw_sigma(lab == i, raw, all_flagged=m1) for i in keep2}
        keep3 = [i for i in keep2 if sig[i] < sigma_max]
        rep["n_after_darkness_veto"] = len(keep3)
        m3 = np.isin(lab, keep3) if keep3 else np.zeros_like(m0)
        rep["flagged_frac_darkness_veto"] = float(m3.sum() / nval)
    else:
        m3 = m2

    cents = [(cent[i][1], cent[i][0]) for i in keep3]
    p = line_pitch_p(cents, voxel_um=voxel_um, n_mc=n_mc)
    rep["line_pitch_p"] = p
    rep["row_organized"] = bool(p is not None and p < 0.05)
    return m3, rep


# ---------------------------------------------------------------- IO + CLI

def load_stack(path):
    if path.endswith(".npy"):
        return np.load(path, mmap_mode="r")
    import zarr
    z = zarr.open(path, mode="r")
    if hasattr(z, "keys"):
        z = z[sorted(z.keys())[0]]
    return z


def load_image(path):
    if path.endswith(".npy"):
        return np.load(path)
    a = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if a is None:
        import tifffile
        a = tifffile.imread(path)
    if a.ndim == 3:
        a = a[..., 0]
    return a


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply", help="run the veto chain on one probability map")
    p.add_argument("--prob", required=True)
    p.add_argument("--stack", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--th", type=float, default=0.30)
    p.add_argument("--min-area", type=int, default=300)
    p.add_argument("--valid", default=None)
    p.add_argument("--void-delta", type=float, default=8.0)
    p.add_argument("--mid", type=int, nargs=2, default=(8, 20))
    p.add_argument("--raw", default=None)
    p.add_argument("--raw-from-stack", action="store_true")
    p.add_argument("--sigma-max", type=float, default=-0.05)
    p.add_argument("--voxel-um", type=float, default=9.362)
    p.add_argument("--n-mc", type=int, default=2000)
    a = ap.parse_args()

    prob = np.load(a.prob)
    stack = load_stack(a.stack)
    valid = np.load(a.valid) > 0 if a.valid else None
    raw = None
    if a.raw:
        raw = load_image(a.raw).astype(np.float32)
    elif a.raw_from_stack:
        raw = np.asarray(stack[a.mid[0]:a.mid[1]],
                         dtype=np.float32).mean(axis=0)
    mask, rep = apply_vetoes(prob, stack, th=a.th, min_area=a.min_area,
                             valid=valid, void_delta=a.void_delta,
                             mid=tuple(a.mid), raw=raw, sigma_max=a.sigma_max,
                             voxel_um=a.voxel_um, n_mc=a.n_mc)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    np.save(a.out + "_mask.npy", mask)
    with open(a.out + "_report.json", "w") as f:
        json.dump(rep, f, indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
