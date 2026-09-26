#!/usr/bin/env bash
# posfit.sh — everything after a fit with a valid winding, shared by both
# routes: flatten + render (render_<ROLO>.sh), direct render of missing
# wraps, mid, fibre panel for the gate queue, ink inference fwd/rev, vetoes.
# Usage: bash posfit.sh <ROLO> <Z0> <VOX> <VOL> [WRAPS...]
set -u
ROLO="$1"; Z0="$2"; VOX="$3"; VOL="$4"; shift 4
WRAPS_ARG="$*"
DIRECT="${WRAPS_ARG:-020 040 060}"
source "$(dirname "$(readlink -f "$0")")/../pipeline/env.sh"
R="$VOLUMEN_WORK"
cd "$R" || exit 1
D=render_${ROLO}_z${Z0}

# 1. flatten + render by the scroll's template (written by `scroll`)
TPL=render_${ROLO}.sh
[ -f "$TPL" ] || { echo "!! no render template for $ROLO ($TPL): setup_pipeline.py scroll"; exit 2; }
sed -e "s/work_${ROLO}\b/work_${ROLO}_z${Z0}/g" \
    -e "s#render_${ROLO}\b#render_${ROLO}_z${Z0}#g" "$TPL" > render_${ROLO}_z${Z0}.sh
echo "--- flatten and render (${WRAPS_ARG:-template wraps}) | $(date +%H:%M)"
bash render_${ROLO}_z${Z0}.sh $WRAPS_ARG > log_est_${ROLO}_z${Z0}_render.txt 2>&1

# 2. direct render of wraps still missing (clean cache per wrap)
for WR in $DIRECT; do
  DW=$D/w$WR
  [ -d "$DW/flat/tifxyz" ] || continue
  [ -d "$DW/render.zarr" ] && continue
  rm -rf cache_est_$ROLO
  "$VOLUMEN_VC3D" vc_render_tifxyz --volume "$PWD/cache_est_$ROLO" --remote-url "$VOL" \
    --prefetch-remote --group-idx 0 --scale 1 \
    --segmentation "$PWD/$DW/flat/tifxyz/flatten.tifxyz" \
    --num-slices 31 --slice-step 1 --cache-gb 16 \
    --zarr-output "$PWD/$DW/render.zarr" >> log_est_${ROLO}_z${Z0}_render.txt 2>&1
done

# 3. mid + panel (gate queue) + inference + vetoes
echo "--- mid, panel, inference | $(date +%H:%M)"
"$VOLUMEN_SPIRAL_PY" - "$ROLO" "$Z0" "$VOX" <<'PYEOF'
import sys, os, subprocess, csv
import numpy as np, zarr, tifffile
R = os.environ['VOLUMEN_WORK']
sys.path.insert(0, R)
import vetoes
ROLO, Z0, VOX = sys.argv[1], sys.argv[2], sys.argv[3]
D = f'{R}/render_{ROLO}_z{Z0}'
CK = os.environ['VOLUMEN_CKPT']
IN = os.environ['VOLUMEN_INK']
REF = os.environ['VOLUMEN_REF']
PY = os.environ['VOLUMEN_SPIRAL_PY']
linhas = []
for WR in ['020','040','060','080','100']:
    dw = f'{D}/w{WR}'
    if not os.path.isdir(f'{dw}/render.zarr'): continue
    z = zarr.open(f'{dw}/render.zarr', mode='r')
    a = z['0'] if hasattr(z,'keys') and '0' in z else z
    st = np.asarray(a, dtype=np.float32); st = st[0] if st.ndim==4 else st
    os.makedirs(f'{dw}/mid', exist_ok=True)
    tifffile.imwrite(f'{dw}/mid/mid.tif', st[15])
    os.makedirs(f'{R}/alvo{ROLO}z{Z0}_w{WR}', exist_ok=True)
    tifffile.imwrite(f'{R}/alvo{ROLO}z{Z0}_w{WR}/w{WR}_mid15.tif', st[15])
    subprocess.run(f'cd {R} && sed -i "s/^UM_ALVO = .*/UM_ALVO = {VOX}      # PHerc{ROLO}/" painel_fibras.py && '
                   f'{PY} painel_fibras.py --base {R} --win 1024 --ref {REF} '
                   f'--alvo alvo{ROLO}z{Z0}_w{WR} --passo 256 --out fila_gate/painel_{ROLO}z{Z0}_w{WR}.png',
                   shell=True, capture_output=True)
    pp = f'{R}/fila_gate/painel_{ROLO}z{Z0}_w{WR}.png'
    if os.path.isfile(pp):
        print(f'{ROLO} z{Z0} w{WR}: panel queued for the gate', flush=True)
    else:
        print(f'WARNING {ROLO} z{Z0} w{WR}: the panel was NOT made', flush=True)
    os.makedirs(f'{dw}/preds', exist_ok=True)
    # the ink venv is uv's own project env: `uv run` there is the right call
    subprocess.run(f'cd {IN} && uv run --no-sync python -m koine_machines.inference.infer '
                   f'{dw}/render.zarr {CK} {dw}/preds/s43_060000.tif '
                   f'--model-type auto --resolution 0 --layer-start 7 --layer-end 24 '
                   f'--overlap 0.50 --blend-mode hann --direction both '
                   f'--batch-size 4 --num-workers 4 --no-compile', shell=True, capture_output=True)
    from scipy import ndimage as ndi
    raw = st[8:20].mean(axis=0)
    valid = ndi.binary_erosion(st.max(axis=0) > 0, structure=np.ones((3,3),bool), iterations=40)
    for suf, dn in [('','rev'), ('_reverse','fwd')]:   # team's direction: without --flip-normals, _reverse is forward
        f = f'{dw}/preds/s43_060000{suf}.tif'
        if not os.path.exists(f): continue
        p = tifffile.imread(f).astype(np.float32)
        if p.max() > 1.5: p /= 255.0
        os.makedirs(f'{R}/fila_olho', exist_ok=True)
        e = (np.clip((p-0.25)/0.5, 0, 1)*255).astype(np.uint8)
        tifffile.imwrite(f'{R}/fila_olho/{ROLO}_z{Z0}_w{WR}_{dn}.tif', e)
        for pol, r in [('dark', raw), ('light', raw.max()-raw)]:
            mask, rep = vetoes.apply_vetoes(p, st, th=0.60, min_area=300,
                                            valid=valid, raw=r, mid=(8,20), voxel_um=float(VOX))
            row = [ROLO, Z0, WR, dn, pol, rep.get('n_components'), rep.get('n_after_void_veto'),
                   rep.get('n_after_darkness_veto'), rep.get('line_pitch_p'),
                   rep.get('row_organized'), int(np.count_nonzero(mask))]
            linhas.append(row)
            print(f'{ROLO} z{Z0} w{WR} {dn} {pol}: comps {row[5]}->{row[6]}->{row[7]}', flush=True)
    del st
csvp = f'{R}/esteira_{ROLO}.csv'
novo = not os.path.exists(csvp)
with open(csvp, 'a', newline='') as fh:
    w = csv.writer(fh)
    if novo:
        w.writerow(['rolo','z0','wrap','dir_equipe','pol','n_comp','n_void','n_sinal',
                    'pitch_p','row_org','px_surv'])
    w.writerows(linhas)
PYEOF
