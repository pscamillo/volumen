#!/usr/bin/env python3
"""
config.py — where the Volumen keeps its own data, and how it finds the rest.

Three kinds of place, kept apart on purpose:

  ~/.config/volumen/     settings the person chose (folders.json)
  ~/.local/share/volumen what the person produced here and would not want to
                         lose: cut labels (verdicts live in the cache for
                         now; see migra_triagem.py)
  ~/.cache/volumen/      what can be made again: flattened views, cuts,
                         downloaded meshes

The pipeline (esteira) is optional. It is found the same way build.py always
found it: any folder in Folders that holds esteira_via3.sh. Without it the
app still reads, cuts and judges surfaces; only Make surfaces, the fibre
gate queue and the per-scroll pipeline CSVs are off.

First run on the author's machine (23/09/2026): the cut labels were in
~/challenges/vesuvius/triagem/rotulos_corte.jsonl and the umbilici in
~/challenges/vesuvius/umbilici_auto. Both are adopted if present, so that
installation keeps working with nothing to set.
"""
from __future__ import annotations

import os
import shutil

import sources

CONFIG_DIR = os.path.expanduser("~/.config/volumen")
DATA_DIR = os.environ.get("VOLUMEN_DATA") or os.path.expanduser(
    "~/.local/share/volumen")
CACHE_DIR = os.path.expanduser("~/.cache/volumen")

CUT_LABELS = os.path.join(DATA_DIR, "cut_labels.jsonl")
# verdicts (ink, surface, gate): one line each, the last one for a surface
# wins. Lived in the cache until 23/09; a verdict cannot be made again, so
# it belongs with the labels.
FINDINGS = os.path.join(DATA_DIR, "my-findings.jsonl")
_LEGACY_FINDINGS = os.path.join(CACHE_DIR, "my-findings.jsonl")

# the author's original locations, adopted once if they exist
_LEGACY_CUT_LABELS = os.path.expanduser(
    "~/challenges/vesuvius/triagem/rotulos_corte.jsonl")
_LEGACY_UMBILICI = os.path.expanduser("~/challenges/vesuvius/umbilici_auto")

# what Make surfaces needs, for the notice when the pipeline is not here
PIPELINE_NEEDS = (
    ("villa", "the ScrollPrize villa checkout, with the spiral environment "
              "(fit_spiral.py runs there; Triton + CUDA, so Linux or WSL "
              "with an NVIDIA GPU)"),
    ("vc_render_tifxyz", "from a VC3D release, for the full multi-layer "
                         "render the ink model reads"),
    ("ink-detection", "the team's ink model (koine_machines) and the "
                      "ink_9um checkpoint"),
    ("inputs per scroll", "tracks, umbilicus and a render template in the "
                          "pipeline folder"),
)


def migrate() -> None:
    """Adopt the author's files on first run. Never overwrites."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if (not os.path.isfile(CUT_LABELS)
            and os.path.isfile(_LEGACY_CUT_LABELS)):
        shutil.copy2(_LEGACY_CUT_LABELS, CUT_LABELS)
        print(f"config: cut labels adopted from {_LEGACY_CUT_LABELS}")
    if (not os.path.isfile(FINDINGS)
            and os.path.isfile(_LEGACY_FINDINGS)):
        shutil.copy2(_LEGACY_FINDINGS, FINDINGS)
        print(f"config: findings adopted from {_LEGACY_FINDINGS}")


def pipeline_roots() -> list[str]:
    """Every folder in Folders that holds esteira_via3.sh, in Folders order.
    The author's machine has two (rota_minima and the installed one, 24/09);
    a user's usually one."""
    return [p for p in sources.local_folders()
            if os.path.isfile(os.path.join(p, "esteira_via3.sh"))]


def pipeline_root() -> str:
    """The first pipeline folder, or "" when there is none (Make surfaces
    runs one pipeline; the gate and the catalogue read all of them)."""
    roots = pipeline_roots()
    return roots[0] if roots else ""


def pipeline_ok() -> bool:
    return bool(pipeline_root())


def umbilici_dir() -> str:
    """Where the per-scroll umbilicus JSONs are, or "" if nowhere."""
    root = pipeline_root()
    cands = []
    if root:
        cands += [os.path.join(root, "umbilici_auto"),
                  os.path.join(os.path.dirname(root.rstrip("/")),
                               "umbilici_auto")]
    cands.append(_LEGACY_UMBILICI)
    for p in cands:
        if os.path.isdir(p):
            return p
    return ""


migrate()
