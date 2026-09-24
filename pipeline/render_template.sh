#!/bin/bash
# render___ROLO__.sh — flatten + render + central slice of the fitted wraps
# of PHerc__ROLO__. Written by setup_pipeline.py scroll; posfit.sh copies it
# per window (work___ROLO__ -> work___ROLO___z<Z0>, render likewise).
set -u
source "$(dirname "$(readlink -f "$0")")/../pipeline/env.sh"
R="$VOLUMEN_WORK"
LAS="$VOLUMEN_VILLA/lasagna"
PY="$VOLUMEN_SPIRAL_PY"
VOL=__VOL__
PX=__PX__
OUT=$R/render___ROLO__

FITDIR=$(ls -d $R/work___ROLO__/out/*/ 2>/dev/null | head -1)
[ -z "$FITDIR" ] && { echo "no fit output in $R/work___ROLO__/out"; exit 1; }
MESHROOT=$(ls -d ${FITDIR}meshes/fitted_* 2>/dev/null | head -1)
[ -z "$MESHROOT" ] && { echo "no meshes/fitted_* in $FITDIR"; exit 1; }
TAG=$(basename "$MESHROOT" | sed 's/^fitted_//')
echo "fit    : $FITDIR"
echo "meshes : $MESHROOT"
echo "tag    : $TAG"
echo "wraps  : $(ls "$MESHROOT" | grep -c '^w[0-9]')"
echo
mkdir -p "$OUT"
WRAPS=${@:-"020 040 060"}

for W in $WRAPS; do
  M="$MESHROOT/w${W}_${TAG}"
  D="$OUT/w$W"
  echo "##################### wrap w$W"
  if [ ! -d "$M" ]; then echo "  NO MESH: $M"; continue; fi
  mkdir -p "$D"
  if [ ! -d "$D/flat/tifxyz/flatten.tifxyz" ]; then
    cat > "$D/flat_in.json" <<EOF
{ "external_surfaces": [ { "path": "$M" } ] }
EOF
    echo "-- flatten"
    (cd "$LAS" && $PY fit.py configs/flatten_fast_nofilter.json \
       "$D/flat_in.json" --out-dir "$D/flat" --device cuda 2>&1 \
       | grep -E "stage2 1000|area_vx2|total optimize" | sed 's/^/   /')
  else
    echo "-- flatten already here"
  fi
  if [ ! -d "$D/render.zarr" ]; then
    echo "-- render"
    "$VOLUMEN_VC3D" vc_render_tifxyz --volume "$R/cache___ROLO__" --remote-url "$VOL" \
      --prefetch-remote --group-idx 0 --scale 1 \
      --segmentation "$D/flat/tifxyz/flatten.tifxyz" \
      --num-slices 31 --slice-step 1 --cache-gb 16 \
      --zarr-output "$D/render.zarr" 2>&1 \
      | grep -E "rendering|Prefetch:" | sed 's/^/   /'
  else
    echo "-- render already here"
  fi
  $PY - "$D" "$PX" <<'PYEOF'
import sys, os
import numpy as np, zarr, tifffile
d, px = sys.argv[1], float(sys.argv[2])
try:
    a = zarr.open(f'{d}/render.zarr', mode='r')
    n = a['0'] if hasattr(a, 'keys') and '0' in a else a
except Exception as e:
    print('   no render:', e); sys.exit()
z = n.shape[0] // 2
sl = np.asarray(n[z])
m = sl > 0
H, W = m.shape
print(f'   flat {W}x{H} = {W*px*10:.0f}x{H*px*10:.0f} mm  '
      f'area {m.sum()*px*px:.2f} cm²  coverage {m.mean():.1%}')
os.makedirs(f'{d}/mid', exist_ok=True)
tifffile.imwrite(f'{d}/mid/mid.tif', sl, compression='zlib')
PYEOF
  echo
done
echo "renders in $OUT"
