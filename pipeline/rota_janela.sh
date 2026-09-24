#!/usr/bin/env bash
# rota_janela.sh — the minimal-route fit in one shifted z window.
#   window = [median+OFFSET-400, median+OFFSET+400), aligned to 16
#   lasagna downloaded per window (lasagna_PHerc<R>_z<Z0>), tracks reused
# Usage: bash rota_janela.sh <ROLO> <VOLID> <umbilicus.json> <LASNAME> <VOX> <OFFSET>
set -e
ROLO="$1"; VOLID="$2"; UMB="$3"; LASNAME="$4"; VOX="$5"; OFF="$6"
[ -z "$OFF" ] && { echo "usage: rota_janela.sh ROLO VOLID UMB LASNAME VOX OFFSET"; exit 1; }
source "$(dirname "$(readlink -f "$0")")/../pipeline/env.sh"
R="$VOLUMEN_WORK"
cd "$R"
DBM="PHerc${ROLO}_${VOLID}_surface_m7_L0_th0.2.dbm"
T="$VOLUMEN_TRACKS/$DBM"
[ -s "$T" ] || { echo "ERROR: tracks missing: $T (setup_pipeline.py scroll)"; exit 1; }

read Z0 Z1 <<< $("$VOLUMEN_SPIRAL_PY" - "$UMB" "$OFF" <<'PY'
import json, sys, statistics
u = json.load(open(sys.argv[1]))["control_points"]
med = statistics.median(sorted(p["z"] for p in u)) + float(sys.argv[2])
z0 = int(round((med - 400) / 16) * 16)
print(z0, z0 + 800)
PY
)
W="work_${ROLO}_z${Z0}"
LAS="lasagna_PHerc${ROLO}_z${Z0}"
echo "=== PHerc${ROLO} | offset ${OFF} | window [$Z0, $Z1) | $(date +%H:%M) ==="

LASOK=1
for C in nx ny grad_mag; do
  [ -d "$LAS/PHerc${ROLO}_${C}.ome.zarr" ] || LASOK=0
done
if [ "$LASOK" = "0" ]; then
  echo "--- lasagna $LAS | $(date +%H:%M)"
  "$VOLUMEN_SPIRAL_PY" dl_lasagna.py --scroll "PHerc${ROLO}" --lasagna "$LASNAME" \
    --z-begin "$Z0" --z-end "$Z1" --out "$LAS"
else
  echo "--- lasagna already here, skipping"
fi

# fit: the spiral venv by path, never `uv run` (it would re-sync to the lock)
if [ ! -d "$W/out" ]; then
  echo "--- fit | $(date +%H:%M)"
  export VIRTUAL_ENV="$(dirname "$(dirname "$VOLUMEN_SPIRAL_PY")")"
  export PATH="$VIRTUAL_ENV/bin:$PATH"
  export FIT_SPIRAL_OUT_DIR="$R/spiral-runs"
  SCROLL="PHerc${ROLO}" VOXEL_UM="$VOX" \
  UMBILICUS="$UMB" \
  LASAGNA_DIR="$R/$LAS" \
  TRACKS_DBM="$T" \
  FIT_Z_BEGIN="$Z0" FIT_Z_END="$Z1" \
  FIT_WORK="$R/$W" \
  "$VOLUMEN_SPIRAL_PY" runner_minimal.py
else
  echo "--- fit already here, skipping"
fi
echo
echo "=== CHECK: winding range != [0,0); step 0 with dense_normals and umbilicus != 0 ==="
echo "=== PHerc${ROLO} z${Z0} done $(date +%H:%M) ==="
