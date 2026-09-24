#!/usr/bin/env bash
# esteira_via3.sh — the pipeline, window by window, with the team's lasagna.
#
# For each new z window (offsets in multiples of 1200 around the umbilicus
# median, drawn without replacement) it runs:
#   fit (rota_janela.sh) -> post-fit (posfit.sh: flatten, render, mid, panel,
#   ink inference forward/reverse, physical vetoes -> CSV + flags).
# Panels queue in fila_gate/ for the human fibre gate; flags only point.
#
# Usage: bash esteira_via3.sh <ROLO> <N_WINDOWS>
# Every path comes from pipeline/env.sh (written by setup_pipeline.py) and
# every per-scroll value from rolos.sh (VOLID, VOX, VOL, LAS).
set -u
ROLO="$1"; N="$2"
source "$(dirname "$(readlink -f "$0")")/../pipeline/env.sh"
R="$VOLUMEN_WORK"
cd "$R"
source "$R/rolos.sh"
rolo_config "$ROLO" || { echo "scroll $ROLO not in rolos.sh"; exit 1; }
UMB="$VOLUMEN_UMBILICI/PHerc${ROLO}_umbilicus.json"
[ -s "$UMB" ] || { echo "no umbilicus for $ROLO: $UMB (setup_pipeline.py scroll)"; exit 1; }
[ "$LAS" = "SEM-LASAGNA" ] && { echo "$ROLO has no published lasagna; the geometric route is not in this build"; exit 1; }
mkdir -p fila_gate
CSV=esteira_${ROLO}.csv
[ -f "$CSV" ] || echo "rolo,z0,wrap,dir,pol,n_comp,n_void,n_sinal,pitch_p,row_org,px_surv" > "$CSV"

GRID="+1200 -1200 +2400 -2400 +3600 -3600 +4800 -4800 +6000 -6000 +600 -600 +1800 -1800 +3000 -3000 +4200 -4200 +5400 -5400"
FEITAS=0
for OFF in $(echo $GRID | tr ' ' '\n' | shuf); do
  # stop asked by Volumen: leave BETWEEN windows, never inside one
  if [ -f "$R/.volumen_stop" ]; then
    echo "== stop requested by Volumen, leaving between windows"
    rm -f "$R/.volumen_stop"; exit 0
  fi
  [ "$FEITAS" -ge "$N" ] && break
  Z0=$("$VOLUMEN_SPIRAL_PY" - "$UMB" "$OFF" <<'PY'
import json, sys, statistics
u = json.load(open(sys.argv[1]))["control_points"]
med = statistics.median(sorted(p["z"] for p in u)) + float(sys.argv[2])
print(int(round((med - 400) / 16) * 16))
PY
)
  W=work_${ROLO}_z${Z0}
  D=render_${ROLO}_z${Z0}
  if [ -d "$W/out" ] && [ -d "$D" ]; then echo "== z$Z0 already done, skipping"; continue; fi
  echo "================ PHerc$ROLO offset $OFF (z$Z0) | $(date +%H:%M) ================"

  # 1. FIT
  bash "$R/rota_janela.sh" "$ROLO" "$VOLID" "$UMB" "$LAS" "$VOX" "$OFF" > log_est_${ROLO}_z${Z0}_fit.txt 2>&1
  if ! grep -q "winding range \[0, [1-9]" log_est_${ROLO}_z${Z0}_fit.txt; then
    echo "!! fit z$Z0 found no winding — marked as tried, on to the next"
    mkdir -p "$W" && touch "$W/RUIM"
    rm -rf "lasagna_PHerc${ROLO}_z${Z0}"
    continue
  fi
  LASDIR="lasagna_PHerc${ROLO}_z${Z0}"
  if [ -d "$LASDIR" ]; then
    echo "--- cleaning $LASDIR ($(du -sh "$LASDIR" | cut -f1))"
    rm -rf "$LASDIR"
  fi

  # 2-6. post-fit shared by both routes
  bash "$R/posfit.sh" "$ROLO" "$Z0" "$VOX" "$VOL"
  FEITAS=$((FEITAS+1))
done
echo "================ PIPELINE $ROLO: $FEITAS window(s) | $(date +%H:%M) ================"
echo "Gate queue: $R/fila_gate/ | flags: grep FLAG in the log | CSV: $CSV"
