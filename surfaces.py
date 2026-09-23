#!/usr/bin/env python3
"""
surfaces.py — the list of surfaces inside one scroll.

One row per surface, with what is known about it before anything is
downloaded: the window, the wrap, its area, whether the package's own screen
liked the surface, and whether this person has looked at it.

WHY A LIST AND NOT A GRID OF THUMBNAILS. A thumbnail costs an ink map, and an
ink map is 2 s. A scroll with 95 surfaces would take three minutes to open.
The list opens instantly from the index; the preview loads when the pointer
rests on a row.

WHAT THE ROWS SAY. The package screened surfaces for shape, not for ink — so
"looks clean" means the sheet looked continuous, never that there is writing.
Keeping those two apart is the whole point of the two-axis verdicts.

The wrap number is the winding, counted outward from the middle. Measured
across 71 windows of eight scrolls: w020 sits about 400 voxels from the axis
and w100 about 1900, and the share of surfaces that look clean falls from
83% at w020 to 33% at w100. Outer wraps are harder; the list says so.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

import config
import core
import sources

INK = "#e8a33d"
MUTED = "#9a9280"

SEEN_MARK = {
    "nothing but texture": "· nothing",
    "marks, but no shapes": "· marks",
    "shapes that could be letters": "· shapes",
    "clear letters": "· LETTERS",
}


def read_findings(cache: core.Cache) -> dict[str, str]:
    """What this person has already said about each surface."""
    p = config.FINDINGS
    out: dict[str, str] = {}
    if not os.path.isfile(p):
        return out
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            key = r.get("unit") or f"{r.get('scroll')}/{r.get('segment')}"
            if r.get("verdict"):
                out[key] = r["verdict"]
    return out


# ------------------------------------------------------------- preview ----
class PreviewSignals(QObject):
    ready = Signal(str, object)
    failed = Signal(str)


class PreviewLoader(QThread):
    """Fetches one ink map so the row can show what is on it."""

    def __init__(self, unit: sources.Unit, cache: core.Cache):
        super().__init__()
        self.unit = unit
        self.cache = cache
        self.sig = PreviewSignals()

    def run(self):
        try:
            p = sources.fetch_ink(self.unit, self.cache, "forward")
            if not p:
                self.sig.failed.emit(self.unit.id)
                return
            import tifffile
            a = tifffile.imread(p)
            if a.ndim == 3:
                a = a[a.shape[0] // 2]
            # a preview is for deciding whether to open, never for judging:
            # a flat-looking map at low zoom is not evidence of absence
            step = max(1, max(a.shape) // 420)
            self.sig.ready.emit(self.unit.id, a[::step, ::step])
        except Exception:  # noqa: BLE001
            self.sig.failed.emit(self.unit.id)


# ---------------------------------------------------------------- page ----
class SurfacesPage(QWidget):
    back = Signal()
    opened = Signal(object)           # a sources.Unit

    def __init__(self, cache: core.Cache | None = None):
        super().__init__()
        self.cache = cache or core.Cache()
        self.scroll_name = ""
        self.units: list[sources.Unit] = []
        self.findings: dict[str, str] = {}
        self.loader: PreviewLoader | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 22, 34, 18)
        outer.setSpacing(10)

        top = QHBoxLayout()
        b = QPushButton("← Scrolls")
        b.clicked.connect(self.back)
        top.addWidget(b)
        top.addSpacing(12)
        self.title = QLabel()
        self.title.setObjectName("h1")
        top.addWidget(self.title)
        top.addStretch()
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        top.addWidget(self.progress)
        outer.addLayout(top)

        self.blurb = QLabel()
        self.blurb.setObjectName("muted")
        self.blurb.setWordWrap(True)
        outer.addWidget(self.blurb)

        body = QHBoxLayout()
        body.setSpacing(16)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["window", "wrap", "area",
                                   "surface shape", "you"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setMouseTracking(True)
        self.tree.itemEntered.connect(self.hovered)
        self.tree.itemActivated.connect(self.activated)
        self.tree.itemDoubleClicked.connect(self.activated)
        # um clique abre: pousar o ponteiro ja carrega a previa, entao
        # exigir um segundo clique noutro canto da tela e' atrito a toa
        self.tree.itemClicked.connect(self.activated)
        h: QHeaderView = self.tree.header()
        h.setStretchLastSection(True)
        for i, w in enumerate((110, 90, 90, 150)):
            self.tree.setColumnWidth(i, w)
        body.addWidget(self.tree, 3)

        side = QVBoxLayout()
        side.setSpacing(8)
        self.preview = QLabel("Rest on a row to see it")
        self.preview.setObjectName("muted")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(430, 430)
        self.preview.setFrameShape(QFrame.StyledPanel)
        side.addWidget(self.preview)
        self.caption = QLabel("")
        self.caption.setObjectName("muted")
        self.caption.setWordWrap(True)
        self.caption.setMinimumHeight(64)
        side.addWidget(self.caption)
        side.addStretch()
        body.addLayout(side, 2)
        outer.addLayout(body)

    # -- filling -------------------------------------------------------
    def show_scroll(self, name: str, units: list[sources.Unit]) -> None:
        self.scroll_name = name
        self.units = sorted(units, key=lambda u: (u.window, u.wrap))
        self.findings = read_findings(self.cache)
        s = core.SCROLLS.get(name)
        self.title.setText(s.label if s else f"PHerc{name}")

        seen = sum(1 for u in self.units if u.id in self.findings)
        self.progress.setText(f"{len(self.units)} surfaces · "
                              f"{seen} looked at")

        bits = []
        if s:
            bits.append(f"{s.voxel_um:g} µm per voxel.")
        else:
            bits.append("This scroll is not in the First Letters set, and "
                        "Volumen does not know its voxel size — distances "
                        "and the letter-size box are not shown for it.")
        bits.append("The wrap number counts outward from the middle of the "
                    "scroll. Inner wraps are usually cleaner: across eight "
                    "scrolls, 83% of surfaces looked clean at w020 and 33% "
                    "at w100.")
        self.blurb.setText(" ".join(bits))

        self.tree.clear()
        for u in self.units:
            verdict = self.findings.get(u.id)
            it = QTreeWidgetItem([
                f"z{u.window}",
                u.wrap,
                f"{u.area_cm2:.2f} cm²" if u.area_cm2 else "—",
                u.screened or "—",
                SEEN_MARK.get(verdict, "") if verdict else "",
            ])
            it.setData(0, Qt.UserRole, u.id)
            if verdict in ("shapes that could be letters", "clear letters"):
                it.setForeground(4, Qt.GlobalColor.yellow)
            elif verdict:
                it.setForeground(4, Qt.GlobalColor.gray)
            self.tree.addTopLevelItem(it)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
    
    def unit_of(self, item: QTreeWidgetItem | None) -> sources.Unit | None:
        if item is None:
            return None
        uid = item.data(0, Qt.UserRole)
        return next((u for u in self.units if u.id == uid), None)

    # -- interaction ---------------------------------------------------
    def hovered(self, item: QTreeWidgetItem, _col: int) -> None:
        u = self.unit_of(item)
        if u is None:
            return
        self.tree.setCurrentItem(item)
        self.describe(u)
        self.preview.setPixmap(QPixmap())
        if self.loader is not None and self.loader.isRunning():
            return
        self.preview.setText("loading…")
        self.loader = PreviewLoader(u, self.cache)
        self.loader.sig.ready.connect(self.show_preview)
        self.loader.sig.failed.connect(
            lambda _id: self.preview.setText("no ink map for this one"))
        self.loader.start()

    def describe(self, u: sources.Unit) -> None:
        bits = [f"{u.id}"]
        if u.screened:
            bits.append(f"the package screen called the shape "
                        f"{u.screened}; that is about the sheet, not ink")
        v = self.findings.get(u.id)
        if v:
            bits.append(f"you said: {v}")
        self.caption.setText(".  ".join(bits) + ".")

    def show_preview(self, uid: str, arr) -> None:
        cur = self.unit_of(self.tree.currentItem())
        if cur is None or cur.id != uid:
            return
        g = np.clip(np.asarray(arr), 0, 255).astype(np.uint8)
        h, w = g.shape
        img = QImage(g.tobytes(), w, h, w, QImage.Format_Grayscale8).copy()
        pm = QPixmap.fromImage(img).scaled(
            self.preview.width() - 8, self.preview.height() - 8,
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(pm)

    def activated(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        u = self.unit_of(item)
        if u is not None:
            self.opened.emit(u)
