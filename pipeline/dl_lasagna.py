#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
dl_lasagna.py — baixa a faixa z dos canais de lasagna de QUALQUER rolo, e
monta zarrs locais parciais que o fit_spiral consegue ler.

Generalizacao do dl_lasagna_1218.py, com a escala VERIFICADA por rolo em vez
de assumida.

LASAGNA_SCALE — a armadilha
---------------------------
O runner do Iyan e o post do Paul (18/08) usam `lasagna_scale = 2`. Medido em
dois rolos (PHerc1218 e PHerc0125), o valor correto e' **4**:
  - os grupos 0 e 1 NAO EXISTEM no bucket; o nivel publicado e' o 2
  - PHerc1218: base z=23247, grupo 2 z=5812 = 23247/4
  - PHerc0125: base z=20840, grupo 2 z=5210 = 20840/4
Com scale 2 o fit dispara RuntimeError de z-ROI vazio
(`lasagna_data.py:293-297`). A checagem interna que pegaria a inconsistencia
e' pulada quando o header tem `scroll_zarr_path = None`.

Este script CALCULA a escala do shape real e avisa se nao for inteira.

USO
---
  uv run dl_lasagna.py --scroll PHerc0125 \\
     --lasagna 20250821151825-lasagna-20260419180421 \\
     --z-begin 10000 --z-end 10800 --dry-run
"""

import argparse
import json
import pathlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
CANAIS = ("nx", "ny", "grad_mag")
GRUPO = "2"

_local = threading.local()


def sess():
    if not hasattr(_local, "s"):
        s = requests.Session()
        s.mount("https://", requests.adapters.HTTPAdapter(
            pool_connections=4, pool_maxsize=4, max_retries=3))
        _local.s = s
    return _local.s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scroll", required=True)
    ap.add_argument("--lasagna", required=True, help="nome do diretorio de lasagna")
    ap.add_argument("--z-begin", type=int, required=True)
    ap.add_argument("--z-end", type=int, required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    base_path = f"{args.scroll}/representations/predictions/lasagna/{args.lasagna}"
    out = pathlib.Path(args.out or f"./lasagna_{args.scroll}")

    # ---- base_shape do proprio manifesto da lasagna
    r = sess().get(f"{BUCKET}/{base_path}/{args.scroll}.lasagna.json", timeout=30)
    r.raise_for_status()
    man = r.json()
    base_z = man["base_shape_zyx"][0]
    print(f"{args.scroll}: base_shape_zyx = {man['base_shape_zyx']}")
    print(f"  umbilicus_json no manifesto: {man.get('umbilicus_json', '')!r} "
          f"(vazio e' o padrao do catalogo)")

    planos = {}
    total = 0
    escala = None
    for canal in CANAIS:
        u = f"{BUCKET}/{base_path}/{args.scroll}_{canal}.ome.zarr/{GRUPO}/.zarray"
        rr = sess().get(u, timeout=30)
        if rr.status_code != 200:
            sys.exit(f"ERRO: sem .zarray para {canal} no grupo {GRUPO}")
        za = rr.json()
        zs, ys, xs = za["shape"]
        cz, cy, cx = za["chunks"]
        sep = za.get("dimension_separator", ".")

        s = base_z / zs
        if escala is None:
            escala = round(s)
            print(f"\nLASAGNA_SCALE = {escala}   (base_z {base_z} / grupo2 z {zs} "
                  f"= {s:.3f})")
            if abs(s - escala) > 0.01:
                print(f"  AVISO: razao nao inteira ({s:.4f}). Verificar antes de usar.",
                      file=sys.stderr)
            if escala != 4:
                print(f"  NOTA: escala {escala}, diferente do 4 medido em "
                      f"PHerc1218 e PHerc0125.", file=sys.stderr)

        z_lo = max(0, args.z_begin // escala)
        z_hi = min(zs, -(-args.z_end // escala))
        if z_hi <= z_lo:
            sys.exit(f"ERRO {canal}: z-ROI [{z_lo},{z_hi}) vazio (z_size={zs})")

        kz0, kz1 = z_lo // cz, (z_hi - 1) // cz
        gy, gx = -(-ys // cy), -(-xs // cx)
        n = (kz1 - kz0 + 1) * gy * gx
        total += n
        planos[canal] = (za, sep, kz0, kz1, gy, gx)
        print(f"  {canal:>9}: shape={za['shape']} chunks={za['chunks']} sep='{sep}'")
        print(f"             z-ROI [{z_lo},{z_hi}) = {z_hi-z_lo} planos  "
              f"chunks z {kz0}..{kz1}  grid {gy}x{gx}  {n} chunks  "
              f"~{(z_hi-z_lo)*ys*xs/1e6:.0f} MB")

    print(f"\ntotal: {total} chunks   destino: {out}")
    if args.dry_run:
        return

    for canal in CANAIS:
        za, sep, kz0, kz1, gy, gx = planos[canal]
        dst_root = out / f"{args.scroll}_{canal}.ome.zarr"
        (dst_root / GRUPO).mkdir(parents=True, exist_ok=True)
        (dst_root / GRUPO / ".zarray").write_text(json.dumps(za))
        for f in (".zattrs", ".zgroup"):
            rr = sess().get(f"{BUCKET}/{base_path}/{args.scroll}_{canal}.ome.zarr/{f}",
                            timeout=30)
            if rr.status_code == 200:
                (dst_root / f).write_text(rr.text)

        src = f"{BUCKET}/{base_path}/{args.scroll}_{canal}.ome.zarr/{GRUPO}"
        keys = [(k, j, i) for k in range(kz0, kz1 + 1)
                for j in range(gy) for i in range(gx)]
        st = {"n": 0, "b": 0, "vazio": 0}
        lock = threading.Lock()
        t0 = time.time()

        def fetch(idx):
            k, j, i = idx
            name = sep.join(str(v) for v in (k, j, i))
            dst = dst_root / GRUPO / name
            if dst.exists():
                with lock:
                    st["n"] += 1
                return
            try:
                rr = sess().get(f"{src}/{name}", timeout=120)
            except requests.RequestException as e:
                print(f"  ERRO {name}: {e}", file=sys.stderr)
                return
            with lock:
                st["n"] += 1
                if rr.status_code == 200:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(rr.content)
                    st["b"] += len(rr.content)
                elif rr.status_code == 404:
                    st["vazio"] += 1
                if st["n"] % 4000 == 0 or st["n"] == len(keys):
                    dt = time.time() - t0
                    mb = st["b"] / 1e6
                    print(f"  {canal} {st['n']}/{len(keys)}  {mb:6.0f} MB  "
                          f"{mb/max(dt,1e-9):4.1f} MB/s  vazios={st['vazio']}")

        print(f"\nbaixando {canal} ({len(keys)} chunks)...")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(fetch, keys))
        print(f"  {canal}: {st['b']/1e9:.2f} GB, {st['vazio']} vazios, "
              f"{time.time()-t0:.0f}s")

    print(f"\nPRONTO. Para o header do fit:")
    print(f"  normal_zarr_group = '{GRUPO}'")
    print(f"  lasagna_scale = {escala}")
    for canal in CANAIS:
        print(f"  {canal}: {(out / f'{args.scroll}_{canal}.ome.zarr').resolve()}")


if __name__ == "__main__":
    main()
