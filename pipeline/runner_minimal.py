#!/usr/bin/env python3
"""
runner_minimal.py — fit_spiral na ROTA MINIMA: umbilicus + lasagna, sem
patches, sem constraints (PCLs), sem tracks.

E' a rota que o post de Paul Henderson (18/08) apresenta como primeiro passo,
e a unica disponivel para os onze elegiveis sem pack. O codigo prevê este caso
explicitamente (`losses.py:573-575`):

    if len(patches) == 0:
        # supervision-free (disable_patches) fits: the umbilicus and shell
        # anchors still apply; the patch radius/DT terms are inert zeros

Amarracoes ativas: **umbilicus** (loss_weight_umbilicus 1.25) e **normais
densas** (loss_weight_dense_normals 1.e2, dense_spacing 12.).

TRES CORRECOES AO MATERIAL PUBLICADO — todas verificadas no codigo e no bucket
-----------------------------------------------------------------------------
1. `lasagna_scale = 4`, nao 2. Os grupos 0 e 1 nao existem no bucket; o nivel
   publicado e' o 2, a 1/4 do volume. Medido em PHerc1218 (23247/5812) e
   PHerc0125 (20840/5210). Com 2, o fit dispara RuntimeError de z-ROI vazio.

2. A flag e' `disable_patches`, nao `input_disable_patches` como no post.
   `fit_spiral.py:206` define `disable_patches`; `input_disable_patches` nao
   existe no codigo. Passar o nome errado deixa os patches HABILITADOS e o fit
   morre com `RuntimeError: No patches could be loaded` — porque nao ha
   patches nestes rolos.

3. `shell_outer_winding_idx` precisa ser fixado, e no pin 61bd95c ele so e'
   resolvido dentro do bloco de shell. Sem isso, SETE perdas ficam inertes em
   silencio, incluindo as normais densas (`losses.py:1237`). Requer o patch
   `patch_D1v2.py`. O upstream @ main ja corrigiu, com aviso explicito.

INCERTEZA DECLARADA
-------------------
`initial_dr_per_winding` fica no default 16.0. No PHerc1218 usamos 20.0, vindo
do pitch medido (173 um / 8.64 um). Para outros rolos NAO TEMOS pitch medido.
Este valor define a escala de quantas voltas o modelo ve, e um valor errado
pode produzir espiral geometricamente plausivel e globalmente deslocada.
Registrar; nao ajustar depois de ver o resultado.

USO
---
  SCROLL=PHerc0125 VOXEL_UM=9.362 \\
  UMBILICUS=/caminho/PHerc0125_umbilicus.json \\
  LASAGNA_DIR=/caminho/lasagna_PHerc0125 \\
  FIT_Z_BEGIN=10000 FIT_Z_END=10800 \\
  FIT_WORK=./work_0125 \\
  python runner_minimal.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

T0 = time.time()

VILLA_COMMIT = "61bd95c75e91b082f8de6964f5edbc5bc6a54eb7"
VILLA_RAW = ("https://raw.githubusercontent.com/IyanDopico/villa/"
             f"{VILLA_COMMIT}/volume-cartographer/scripts/spiral")

SCROLL = os.environ["SCROLL"]
VOXEL_UM = float(os.environ["VOXEL_UM"])
UMBILICUS = os.path.abspath(os.environ["UMBILICUS"])
LASAGNA_DIR = os.path.abspath(os.environ["LASAGNA_DIR"])
LASAGNA_SCALE = int(os.environ.get("LASAGNA_SCALE", "4"))
SPIRAL_SENSE = os.environ.get("SPIRAL_SENSE", "CW")
TRACKS_DBM = os.environ.get("TRACKS_DBM")   # opcional; None = sem tracks
if TRACKS_DBM:
    TRACKS_DBM = os.path.abspath(TRACKS_DBM)
    if not os.path.isfile(TRACKS_DBM):
        sys.exit(f"ERRO: nao existe {TRACKS_DBM}")

Z_BEGIN = int(os.environ["FIT_Z_BEGIN"])
Z_END = int(os.environ["FIT_Z_END"])
STEPS = int(os.environ.get("FIT_STEPS", "30000"))
SEED = int(os.environ.get("FIT_SEED", "1"))
WORK = os.path.abspath(os.environ.get("FIT_WORK", f"./work_{SCROLL}"))
SHELL_IDX = int(os.environ.get("SHELL_OUTER_WINDING_IDX", "127"))
GAP_WINDINGS = int(os.environ.get("GAP_EXPANDER_NUM_WINDINGS", "130"))

NX = f"{LASAGNA_DIR}/{SCROLL}_nx.ome.zarr"
NY = f"{LASAGNA_DIR}/{SCROLL}_ny.ome.zarr"
GM = f"{LASAGNA_DIR}/{SCROLL}_grad_mag.ome.zarr"
for p in (NX, NY, GM, UMBILICUS):
    if not os.path.exists(p):
        sys.exit(f"ERRO: nao existe {p}")

SPIRAL_DIR = f"{WORK}/spiral"
DATASET_DIR = f"{WORK}/dataset"
OUT_DIR = f"{WORK}/out"

CONFIG_OVERRIDES = {
    "random_seed": SEED,
    "num_training_steps": STEPS,
    "disable_patches": True,              # CORRECAO 2
    "shell_outer_winding_idx": SHELL_IDX,  # CORRECAO 3
    "gap_expander_num_windings": GAP_WINDINGS,
    "output_first_winding": 0,          # default e 10; sem isto o range sai vazio
    "loss_weight_shell_outer": 0.0,
    "loss_weight_shell_patch_radius": 0.0,
    "unattached_pcl_num_per_step": 800,
    "stratified_pcl_sampling": False,
    "dt_target_mode": "strip_median",
    "save_png_visualizations": True,
    # loss_weight_dense_normals e dense_spacing ficam nos defaults (1.e2, 12.)
    # initial_dr_per_winding fica no default 16.0 — ver INCERTEZA no cabecalho
}

VILLA_FILES = [
    "fit_spiral.py", "spiral_helpers.py", "losses.py", "point_collection.py",
    "tifxyz.py", "umbilicus.py", "tracks.py", "transforms.py", "geom_utils.py",
    "ddp_helpers.py", "lasagna_data.py", "flow_fields.py", "sample_spiral.py",
    "satisfaction_metrics.py", "visualization.py", "checkpoint_io.py",
    "influence.py", "native_spiral.py", "dt_targets.py", "loss_maps.py",
    "sdt_losses.py", "soft_alignment.py", "prefetch.py", "strip_path_pools.py",
    "strip_paths.py", "gap_triton.py", "flow_triton.py", "lasagna_mmap.py",
    "geometry_snapshot.py",
]

HEADER = f"""
# {SCROLL} — MINIMAL ROUTE (umbilicus + lasagna, supervision-free)
dataset_path = {DATASET_DIR!r}
scroll_zarr_path = None
normal_nx_zarr_path = {NX!r}
normal_ny_zarr_path = {NY!r}
grad_mag_zarr_path = {GM!r}
normal_zarr_group = '2'
pcl_json_paths = []
fibers_path = None
verified_patches_path = None
unverified_patches_path = None
run_tag = os.environ.get('FIT_SPIRAL_RUN_TAG')
shell_path = None
tracks_dbm_path = {TRACKS_DBM!r}
spiral_outward_sense = {SPIRAL_SENSE!r}
umbilicus_z_to_yx = lambda: json_umbilicus_z_to_yx({UMBILICUS!r}, coordinate_scale=1.0)
scroll_name = {SCROLL.lower()!r}
z_begin, z_end = {Z_BEGIN}, {Z_END}
voxel_size_um = {VOXEL_UM}
cache_path = os.environ.get('FIT_SPIRAL_CACHE_DIR', {WORK + '/cache'!r})
lasagna_scale = {LASAGNA_SCALE}
render_volume_scale = int(os.environ.get('FIT_SPIRAL_RENDER_VOLUME_SCALE', '16'))
pcl_input_specs = None
lasagna_storage_backend = 'auto'
surf_sdt_zarr_path = None
surf_sdt_zarr_group = '1'

"""

PATCH_ANCORA = "    shell_map = None\n    shell_outer_winding_idx = None\n"
PATCH_NOVO = """    shell_map = None
    # --- PATCH: resolve o indice do config fora do bloco de shell, como
    # resolve_outer_winding_idx_and_notes() no upstream @ main.
    _cfg_outer = cfg['shell_outer_winding_idx']
    if _cfg_outer is None:
        shell_outer_winding_idx = None
    else:
        shell_outer_winding_idx = int(_cfg_outer)
        if shell_outer_winding_idx < 2:
            raise ValueError('shell_outer_winding_idx must be >= 2 or None')
        print('no outer-shell losses; using configured '
              f'shell_outer_winding_idx = {shell_outer_winding_idx} '
              'for the dense and regularisation losses')
    # --- fim do patch
"""


def fetch(url, dst, attempts=5):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    # cache local: VILLA_COMMIT e' fixo, entao um arquivo ja baixado nunca
    # muda. evita depender do CDN a cada execucao (503 recorrente em 12/09).
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return
    for i in range(attempts):
        try:
            urllib.request.urlretrieve(url, dst)
            return
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            print(f"retry {i+1} for {url}: {e}", flush=True)
            time.sleep(2 ** i)


def main():
    print(f"MINIMAL ROUTE — {SCROLL}")
    print(f"  umbilicus : {UMBILICUS}")
    print(f"  lasagna   : {LASAGNA_DIR}  (scale {LASAGNA_SCALE})")
    print(f"  window    : z {Z_BEGIN}-{Z_END}  voxel {VOXEL_UM} um")
    print(f"  sense     : {SPIRAL_SENSE}   shell_outer_idx: {SHELL_IDX}")
    print(f"  tracks    : {TRACKS_DBM or 'NONE'}")
    print(f"  no patches, no PCLs")
    print()

    print(f"[{time.time()-T0:6.1f}s] fetching villa spiral @ {VILLA_COMMIT[:9]}",
          flush=True)
    for f in VILLA_FILES:
        fetch(f"{VILLA_RAW}/{f}", f"{SPIRAL_DIR}/{f}")
    os.makedirs(DATASET_DIR, exist_ok=True)

    print(f"[{time.time()-T0:6.1f}s] patching header + shell_outer_winding_idx",
          flush=True)
    src_path = f"{SPIRAL_DIR}/fit_spiral.py"
    txt = open(src_path, encoding="utf-8").read()
    lines = txt.splitlines(keepends=True)
    i_hdr = next(i for i, l in enumerate(lines) if l.startswith("# PHercParis4"))
    i_cfg = next(i for i, l in enumerate(lines) if l.startswith("default_config"))
    txt = "".join(lines[:i_hdr] + [HEADER] + lines[i_cfg:])
    if txt.count(PATCH_ANCORA) != 1:
        sys.exit("ERRO: ancora do patch nao encontrada exatamente 1x")
    txt = txt.replace(PATCH_ANCORA, PATCH_NOVO)
    open(src_path, "w", encoding="utf-8").write(txt)

    env = dict(os.environ)
    env.update({
        "WANDB_MODE": "disabled",
        "FIT_SPIRAL_OUT_DIR": OUT_DIR,
        "FIT_SPIRAL_CACHE_DIR": f"{WORK}/cache",
        "FIT_SPIRAL_RUN_TAG": f"minimal-z{Z_BEGIN}-{Z_END}-s{SEED}",
        "FIT_SPIRAL_CONFIG_OVERRIDES": json.dumps(CONFIG_OVERRIDES),
    })
    print(f"[{time.time()-T0:6.1f}s] running fit_spiral ({STEPS} steps)",
          flush=True)
    log = open(f"{WORK}/fit_run.log", "a", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "fit_spiral.py"], cwd=SPIRAL_DIR,
                            env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        print(line, end="", flush=True)
        log.write(line)
    proc.wait()
    log.close()
    print(f"[{time.time()-T0:6.1f}s] exit {proc.returncode}; outputs in {OUT_DIR}")
    print()
    print("CHECK THE LOG before any render:")
    print("  1. 'no outer-shell losses; using configured shell_outer_winding_idx'")
    print("  2. 'loading lasagna zarrs group 2'")
    print("  3. step 0 with dense_normals != 0.0 and umbilicus != 0.0")
    print("  If (3) fails, the arm is null — do not render.")
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
