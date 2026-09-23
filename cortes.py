#!/usr/bin/env python3
"""
cortes.py — cuts through the raw CT with the surface drawn on them.

Three windows per surface, 512 px each, at the z of a mesh point: the CT slice
in grey and the mesh points within tolerance as an orange curve. A curve that
follows the layering is a surface sitting on a sheet; one that cuts
across it is crossing between sheets. Used by cuts.py; the volume is
opened through core (https, shared cache).
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

SUSPEITAS = {"textura suspeita", "possivel letra", "letra clara"}

# nome do volume no bucket, por rolo. Fonte: pagina do First Letters.
# NAO tirar dos scripts de render — render_0800.sh aponta para um nome que
# nao existe mais no bucket (medido 18/09/2026).
VOLUMES = {
    "0125": "20250821151825-9.362um-1.2m-113keV-masked.zarr",
    "0175A": "20250521115057-8.640um-1.2m-116keV-masked.zarr",
    "0175B": "20250521125822-8.640um-1.2m-116keV-masked.zarr",
    "0191": "20250821151635-9.362um-1.2m-113keV-masked.zarr",
    "0211": "20250821151803-9.362um-1.2m-113keV-masked.zarr",
    "0257": "20250821151750-9.362um-1.2m-113keV-masked.zarr",
    "0268": "20251110183117-8.640um-1.2m-116keV-masked.zarr",
    "0343": "20250521140437-8.640um-1.2m-116keV-masked.zarr",
    "0358": "20250821151737-9.362um-1.2m-113keV-masked.zarr",
    "0800": "20250521135224-8.640um-1.2m-116keV-masked.zarr",
    "0813": "20250821151723-9.362um-1.2m-113keV-masked.zarr",
    "0826": "20250821151701-9.362um-1.2m-113keV-masked.zarr",
}
S3 = "s3://vesuvius-challenge-open-data"

_abertos = {}


def volume(rolo):
    if rolo in _abertos:
        return _abertos[rolo]
    nome = VOLUMES.get(rolo)
    if not nome:
        _abertos[rolo] = None
        return None
    # through core: https instead of s3fs (43 vs 7 MB/s, 23/09), the
    # SCROLLS table checked against the bucket, and one open volume per
    # scroll shared with the flattened view. The local VOLUMES table above
    # is kept only for scrolls core does not know.
    import core
    try:
        s = core.SCROLLS.get(rolo)
        if s is not None:
            z = core.open_volume(s, 0)
        else:
            import zarr
            z = zarr.open(core.http_url(
                f"{S3}/PHerc{rolo}/volumes/{nome}/0"), mode="r")
    except Exception as e:  # noqa: BLE001
        print(f"  ! nao abriu o volume de {rolo}: {e}")
        z = None
    _abertos[rolo] = z
    return z


def le_malha(p):
    import tifffile
    x = tifffile.imread(f"{p}/x.tif")
    y = tifffile.imread(f"{p}/y.tif")
    z = tifffile.imread(f"{p}/z.tif")
    m = (x > 0) & (y > 0)          # sentinela -1
    return x, y, z, m


def curva_na_fatia(x, y, z, m, z_alvo, tol=None):
    """curva ORDENADA onde a malha cruza a fatia z_alvo.

    Percorre a grade por coluna e interpola o cruzamento entre linhas
    vizinhas. Ordenar por x embaralharia a ordem ao longo da folha, e pegar
    so os pontos dentro de uma tolerancia daria 15 pontos soltos em vez de
    uma curva (o passo da grade e' ~22 voxels).
    """
    H, W = z.shape
    saida = []
    for j in range(W):
        col_z, col_m = z[:, j], m[:, j]
        for i in range(H - 1):
            if not (col_m[i] and col_m[i + 1]):
                continue
            a0, a1 = col_z[i], col_z[i + 1]
            if (a0 - z_alvo) * (a1 - z_alvo) > 0:
                continue                      # nao cruza entre i e i+1
            d = a1 - a0
            t = 0.0 if abs(d) < 1e-6 else (z_alvo - a0) / d
            saida.append((x[i, j] + t * (x[i + 1, j] - x[i, j]),
                          y[i, j] + t * (y[i + 1, j] - y[i, j])))
            break                             # um cruzamento por coluna
    if len(saida) < 10:
        return None
    return np.asarray(saida, dtype=np.float64)


def salva_corte(vol, zi, cx, cy, pts, tam, saida, titulo):
    h = tam // 2
    y0, y1 = int(cy) - h, int(cy) + h
    x0, x1 = int(cx) - h, int(cx) + h
    Y, X = vol.shape[1], vol.shape[2]
    y0, y1 = max(0, y0), min(Y, y1)
    x0, x1 = max(0, x0), min(X, x1)
    if y1 - y0 < 64 or x1 - x0 < 64:
        return False
    a = np.asarray(vol[int(zi), y0:y1, x0:x1]).astype(np.float32)
    if a.max() <= 0:
        return False
    lo, hi = np.percentile(a[a > 0], [2, 99])
    g = np.clip((a - lo) / max(hi - lo, 1), 0, 1)
    img = Image.fromarray((g * 255).astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(img)
    # segmentos consecutivos da curva que caem na janela — linha, nao pontos
    uv = np.stack([pts[:, 0] - x0, pts[:, 1] - y0], -1)
    n_d = 0
    for k in range(len(uv) - 1):
        u0, v0 = uv[k]
        u1, v1 = uv[k + 1]
        if not (min(u0, u1) < x1 - x0 and max(u0, u1) >= 0
                and min(v0, v1) < y1 - y0 and max(v0, v1) >= 0):
            continue
        if abs(u1 - u0) > 60 or abs(v1 - v0) > 60:
            continue                 # salto grande: buraco na malha
        d.line([u0, v0, u1, v1], fill=(255, 150, 20), width=2)
        n_d += 1
    dentro = uv[(uv[:, 0] >= 0) & (uv[:, 0] < x1 - x0)
                & (uv[:, 1] >= 0) & (uv[:, 1] < y1 - y0)]
    d.text((6, 6), titulo, fill=(255, 255, 255))
    d.text((6, img.size[1] - 16),
           f"z={int(zi)}  x={x0}..{x1}  y={y0}..{y1}  "
           f"{len(dentro)} mesh points", fill=(255, 255, 255))
    img.save(saida)
    return True
