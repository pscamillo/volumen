#!/usr/bin/env python3
"""
progress.py — where the work stands, scroll by scroll.

At the top, five figures: surfaces, fibre gate, ink judged, cut labels on the
way to the twenty the angle measure needs, and letters suspected.

Below, one card per scroll. The strip in each card is the scroll's height,
with a ruler in z. Every window the pipeline tried is a block on it:

    fill from below   share of its surfaces judged for ink
    teal band on top  at least one of them went through the fibre gate
    amber edge        at least one judged to have shapes that could be letters
    rust hatching     RUIM — tried, and the fit found no winding

RUIM MATTERS for reading the gaps. An empty stretch of the strip can be
height nobody has run, or height where the fit failed. The first asks for
the pipeline; the second is usually a geometry limit of the scroll and says
not to insist. Without the hatching the two looked the same.

Rest the pointer on a block for its numbers; click a card to open the
scroll's surface list.

Nothing here is stored. It is read each time the screen opens — from the
catalogue, my-findings.jsonl, the cuts on disk, cut_labels.jsonl and the
RUIM markers the pipeline leaves in its working folders.
"""
from __future__ import annotations

import glob
import json
import os
import re

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QToolTip,
                               QVBoxLayout, QWidget)

import core
import sources

INK = QColor("#e8a33d")
TRACK = QColor("#2c2920")
EDGE = QColor("#4a4436")
TEXT = QColor("#eee8d8")
MUTED = QColor("#9a9280")
GATE = QColor("#7fb0a0")
JUDGED = QColor("#b8ad94")
CUT = QColor("#8e8a9e")
RUIM = QColor("#a0523d")

HITS = ("shapes that could be letters", "clear letters")
CUTS_DIR = os.path.expanduser("~/.cache/volumen/cortes")
import config  # noqa: E402
CUT_LABELS = config.CUT_LABELS
LABELS_NEEDED = 20
WINDOW = 800
RE_WORK = re.compile(r"^work[A-Za-z]*_(?P<rolo>[0-9A-Za-z]+)_z(?P<z>\d+)$")


# ----------------------------------------------------------------- data ---
def _jsonl(path: str):
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                yield json.loads(ln)
            except json.JSONDecodeError:
                continue


def unit_state(cache: core.Cache) -> dict:
    """Last ink verdict, last surface verdict, gated — merged per unit.

    The gate writes surface only, the Explore writes both, the triage
    migration wrote both; last non-empty wins."""
    st: dict[str, dict] = {}
    for r in _jsonl(config.FINDINGS):
        u = r.get("unit")
        if not u:
            continue
        s = st.setdefault(u, {"ink": None, "surface": None, "gated": False})
        if r.get("verdict"):
            s["ink"] = r["verdict"]
        if r.get("surface"):
            s["surface"] = r["surface"]
        if r.get("origin") == "gate.py":
            s["gated"] = True
    return st


def cut_state() -> tuple[set, dict]:
    with_cut = set()
    for p in glob.glob(os.path.join(CUTS_DIR, "*_z*_w*_*.png")):
        base = os.path.basename(p).rsplit("_", 1)[0]
        parts = base.split("_")
        if len(parts) == 3:
            with_cut.add("/".join(parts))
    labels = {}
    for r in _jsonl(CUT_LABELS):
        if r.get("unit") and r.get("rotulo"):
            labels[(r["unit"], r.get("onde", ""))] = r["rotulo"]
    return with_cut, labels


def ruim_windows() -> dict[str, set]:
    """Windows the pipeline tried and marked RUIM, per scroll."""
    out: dict[str, set] = {}
    for root in sources.local_folders():
        for marker in glob.glob(os.path.join(root, "work*_*_z*", "RUIM")):
            m = RE_WORK.match(os.path.basename(os.path.dirname(marker)))
            if m:
                out.setdefault(m.group("rolo"), set()).add(int(m.group("z")))
    return out


# -------------------------------------------------------------- widgets ---
class MiniBar(QWidget):
    def __init__(self, frac: float, color: QColor, height: int = 6):
        super().__init__()
        self.frac = max(0.0, min(1.0, frac))
        self.color = color
        self.setFixedHeight(height)
        self.setMinimumWidth(60)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        rad = self.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(TRACK)
        p.drawRoundedRect(r, rad, rad)
        if self.frac > 0:
            p.setBrush(self.color)
            p.drawRoundedRect(QRectF(0, 0, max(self.height(),
                                               self.width() * self.frac),
                                     self.height()), rad, rad)
        p.end()


class Tile(QFrame):
    """One headline figure."""

    def __init__(self, big: str, caption: str, frac: float | None,
                 color: QColor, note: str = ""):
        super().__init__()
        self.setObjectName("tile")
        self.setStyleSheet(
            "QFrame#tile { background: #211f17; border: 1px solid #3a3529;"
            " border-radius: 14px; }"
            "QFrame#tile QLabel { background: transparent; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)
        b = QLabel(big)
        b.setStyleSheet(f"font-size: 30px; font-weight: 500; "
                        f"color: {color.name()};")
        lay.addWidget(b)
        c = QLabel(caption)
        c.setObjectName("muted")
        lay.addWidget(c)
        if frac is not None:
            lay.addWidget(MiniBar(frac, color, 5))
        if note:
            n = QLabel(note)
            n.setObjectName("muted")
            n.setStyleSheet("font-size: 11px;")
            n.setWordWrap(True)
            lay.addWidget(n)
        lay.addStretch()


class Swatch(QWidget):
    """A small painted sample of each mark, for the legend."""

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.setFixedSize(26, 16)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2, 2, 22, 12)
        p.setPen(QPen(EDGE, 1))
        p.setBrush(TRACK)
        p.drawRoundedRect(r, 3, 3)
        if self.kind == "fill":
            p.setPen(Qt.NoPen)
            p.setBrush(JUDGED)
            p.drawRoundedRect(QRectF(2, 7, 22, 7), 2, 2)
        elif self.kind == "gate":
            p.setPen(Qt.NoPen)
            p.setBrush(GATE)
            p.drawRect(QRectF(3, 3, 20, 3))
        elif self.kind == "hit":
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(INK, 2))
            p.drawRoundedRect(r, 3, 3)
        elif self.kind == "ruim":
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(RUIM, Qt.BDiagPattern))
            p.drawRoundedRect(r, 3, 3)
        p.end()


class Strip(QWidget):
    """One scroll along its height, windows as blocks, ruler below."""

    def __init__(self, windows: dict, ruins: set, zmin: int, zmax: int):
        super().__init__()
        self.windows = windows
        self.ruins = ruins
        self.zmin, self.zmax = zmin, zmax
        self.setMinimumHeight(64)
        self.setMouseTracking(True)
        self._boxes: list[tuple[QRectF, str]] = []

    def zx(self, z: float) -> float:
        span = max(1, self.zmax - self.zmin)
        return (z - self.zmin) / span * (self.width() - 2) + 1

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        top, bar = 6, 34
        self._boxes = []

        p.setPen(Qt.NoPen)
        p.setBrush(TRACK)
        p.drawRoundedRect(QRectF(0, top, w, bar), 7, 7)

        # RUIM first, underneath
        for z0 in sorted(self.ruins):
            r = QRectF(self.zx(z0) + 1, top + 3,
                       max(4.0, self.zx(z0 + WINDOW) - self.zx(z0) - 2),
                       bar - 6)
            p.setPen(QPen(RUIM, 1))
            p.setBrush(QBrush(RUIM, Qt.BDiagPattern))
            p.drawRoundedRect(r, 4, 4)
            self._boxes.append((r, f"z{z0}–{z0 + WINDOW}\nRUIM — the fit "
                                   f"found no winding here"))

        for z0, c in sorted(self.windows.items()):
            r = QRectF(self.zx(z0) + 1, top + 3,
                       max(4.0, self.zx(z0 + WINDOW) - self.zx(z0) - 2),
                       bar - 6)
            p.setPen(QPen(EDGE, 1))
            p.setBrush(QColor("#3a3529"))
            p.drawRoundedRect(r, 4, 4)
            frac = c["ink"] / c["units"] if c["units"] else 0.0
            if frac:
                fill = QColor(JUDGED)
                fill.setAlphaF(0.55 + 0.45 * frac)
                p.setPen(Qt.NoPen)
                p.setBrush(fill)
                h = r.height() * frac
                p.drawRoundedRect(QRectF(r.x(), r.bottom() - h,
                                         r.width(), h), 3, 3)
            if c["gated"]:
                p.setPen(Qt.NoPen)
                p.setBrush(GATE)
                p.drawRoundedRect(QRectF(r.x() + 1, r.y() + 1,
                                         r.width() - 2, 4), 2, 2)
            if c["hits"]:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(INK, 2))
                p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 5, 5)
            tip = (f"z{z0}–{z0 + WINDOW}\n"
                   f"{c['units']} surface{'s' if c['units'] != 1 else ''}"
                   f"  ·  {c['gated_n']} gated  ·  {c['ink']} judged"
                   + (f"\n{c['hits_n']} with shapes that could be letters"
                      if c["hits"] else "")
                   + (f"\n{c['cut']} with a cut" if c["cut"] else ""))
            self._boxes.append((r, tip))

        # ruler
        span = self.zmax - self.zmin
        step = 1000 if span <= 9000 else 2000
        first = (self.zmin // step + 1) * step
        p.setFont(QFont("", 8))
        for z in range(first, self.zmax, step):
            xx = self.zx(z)
            p.setPen(QPen(EDGE, 1))
            p.drawLine(QPointF(xx, top + bar + 2), QPointF(xx, top + bar + 6))
            p.setPen(MUTED)
            lbl = f"z{z}"
            tw = p.fontMetrics().horizontalAdvance(lbl)
            p.drawText(QPointF(xx - tw / 2, top + bar + 18), lbl)
        p.end()

    def mouseMoveEvent(self, e):
        pos = e.position()
        for r, tip in reversed(self._boxes):
            if r.contains(pos):
                QToolTip.showText(e.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()


class ScrollCard(QFrame):
    picked = Signal(str)

    def __init__(self, scroll: str, n: dict, windows: dict, ruins: set,
                 geometric: bool):
        super().__init__()
        self.scroll = scroll
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(22)

        left = QVBoxLayout()
        left.setSpacing(3)
        s = core.SCROLLS.get(scroll)
        name = QLabel(s.label if s else f"PHerc{scroll}")
        name.setObjectName("h2")
        left.addWidget(name)
        sub = QLabel((f"{s.voxel_um:g} µm" if s else "scale unknown")
                     + ("  ·  geometric" if geometric else "  ·  lasagna"))
        sub.setObjectName("muted")
        left.addWidget(sub)
        wins = QLabel(f"{len(windows)} window{'s' if len(windows) != 1 else ''}"
                      + (f"  ·  {len(ruins)} RUIM" if ruins else ""))
        wins.setObjectName("muted")
        wins.setStyleSheet("font-size: 12px;")
        left.addWidget(wins)
        left.addStretch()
        box = QWidget()
        box.setLayout(left)
        box.setFixedWidth(170)
        box.setStyleSheet("background: transparent;")
        lay.addWidget(box)

        zs = sorted(set(windows) | set(ruins))
        zmin = max(0, zs[0] - 400)
        zmax = zs[-1] + WINDOW + 400
        lay.addWidget(Strip(windows, ruins, zmin, zmax), 1)

        stats = QWidget()
        stats.setStyleSheet("background: transparent;")
        g = QGridLayout(stats)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(7)
        u = max(1, n["units"])
        rows = [("gate", n["gated"], GATE), ("ink", n["ink"], JUDGED),
                ("cut", n["cut"], CUT)]
        for i, (label, v, col) in enumerate(rows):
            a = QLabel(label)
            a.setObjectName("muted")
            a.setStyleSheet("font-size: 12px;")
            g.addWidget(a, i, 0)
            g.addWidget(MiniBar(v / u, col), i, 1)
            c = QLabel(f"{v}/{n['units']}")
            c.setObjectName("muted")
            c.setStyleSheet("font-size: 12px;")
            g.addWidget(c, i, 2)
        if n["hits"] or n["label"]:
            extra = []
            if n["hits"]:
                extra.append(f"<span style='color:#e8a33d'>{n['hits']} with "
                             f"shapes</span>")
            if n["label"]:
                extra.append(f"{n['label']} cut label"
                             f"{'s' if n['label'] != 1 else ''}")
            e = QLabel("  ·  ".join(extra))
            e.setObjectName("muted")
            e.setTextFormat(Qt.RichText)
            e.setStyleSheet("font-size: 12px;")
            g.addWidget(e, len(rows), 0, 1, 3)
        stats.setFixedWidth(250)
        lay.addWidget(stats)

    def mousePressEvent(self, _):
        self.picked.emit(self.scroll)


# ----------------------------------------------------------------- page ---
class ProgressPage(QWidget):
    back = Signal()
    picked = Signal(str)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 24, 40, 18)
        outer.setSpacing(14)

        top = QHBoxLayout()
        b = QPushButton("← Back")
        b.clicked.connect(self.back)
        top.addWidget(b)
        top.addStretch()
        t = QLabel("Progress")
        t.setObjectName("h1")
        top.addWidget(t)
        top.addStretch()
        top.addSpacing(b.sizeHint().width())
        outer.addLayout(top)

        self.tiles = QHBoxLayout()
        self.tiles.setSpacing(14)
        outer.addLayout(self.tiles)

        legend = QHBoxLayout()
        legend.setSpacing(8)
        for kind, text in (("fill", "judged for ink"),
                           ("gate", "through the fibre gate"),
                           ("hit", "shapes that could be letters"),
                           ("ruim", "RUIM — tried, no winding")):
            legend.addWidget(Swatch(kind))
            lb = QLabel(text)
            lb.setObjectName("muted")
            legend.addWidget(lb)
            legend.addSpacing(16)
        legend.addStretch()
        hint = QLabel("Rest on a block for its numbers · click a card to "
                      "open the scroll")
        hint.setObjectName("muted")
        legend.addWidget(hint)
        outer.addLayout(legend)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        outer.addWidget(self.area, 1)

    def _clear_tiles(self):
        while self.tiles.count():
            w = self.tiles.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

    def fill(self, catalog, cache: core.Cache) -> None:
        st = unit_state(cache)
        with_cut, labels = cut_state()
        labelled_units = {u for (u, _) in labels}
        ruins = ruim_windows()
        by = catalog.by_scroll()

        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setSpacing(12)
        lay.setContentsMargins(0, 4, 12, 4)

        tot = {"units": 0, "gated": 0, "ink": 0, "cut": 0, "label": 0,
               "hits": 0}
        for scroll in sorted(by, key=lambda k: -len(by[k])):
            units = by[scroll]
            if not units:
                continue
            windows: dict[int, dict] = {}
            n = {"units": 0, "gated": 0, "ink": 0, "cut": 0, "label": 0,
                 "hits": 0}
            geometric = False
            for u in units:
                s = st.get(u.id, {})
                c = windows.setdefault(u.window, {
                    "units": 0, "ink": 0, "gated": False, "gated_n": 0,
                    "hits": False, "hits_n": 0, "cut": 0})
                c["units"] += 1
                n["units"] += 1
                geometric = geometric or getattr(u, "geometric", False)
                if s.get("ink"):
                    c["ink"] += 1
                    n["ink"] += 1
                if s.get("gated"):
                    c["gated"] = True
                    c["gated_n"] += 1
                    n["gated"] += 1
                if s.get("ink") in HITS:
                    c["hits"] = True
                    c["hits_n"] += 1
                    n["hits"] += 1
                if u.id in with_cut:
                    c["cut"] += 1
                    n["cut"] += 1
                if u.id in labelled_units:
                    n["label"] += 1
            for k in tot:
                tot[k] += n[k]
            # a RUIM window that also produced surfaces is not a failure
            r = {z for z in ruins.get(scroll, set()) if z not in windows}
            card = ScrollCard(scroll, n, windows, r, geometric)
            card.picked.connect(self.picked)
            lay.addWidget(card)

        lay.addStretch()
        self.area.setWidget(holder)

        self._clear_tiles()
        u = max(1, tot["units"])
        decided = sum(1 for v in labels.values() if v in ("segue",
                                                          "atravessa"))
        unsure = sum(1 for v in labels.values() if v == "incerto")
        n_ruim = sum(len(v) for v in ruins.values())
        for tile in (
            Tile(f"{tot['units']}", f"surfaces in {len(by)} scrolls", None,
                 TEXT, f"{n_ruim} windows RUIM" if n_ruim else ""),
            Tile(f"{tot['gated']}", "through the fibre gate",
                 tot["gated"] / u, GATE,
                 f"{100 * tot['gated'] / u:.0f}% of all surfaces"),
            Tile(f"{tot['ink']}", "judged for ink", tot["ink"] / u, JUDGED,
                 f"{tot['cut']} with a cut"),
            Tile(f"{decided}/{LABELS_NEEDED}", "cut labels",
                 decided / LABELS_NEEDED, CUT,
                 f"{unsure} unsure — needed before the angle can be "
                 f"measured"),
            Tile(f"{tot['hits']}", "with shapes that could be letters",
                 None, INK if tot["hits"] else MUTED),
        ):
            self.tiles.addWidget(tile, 1)
