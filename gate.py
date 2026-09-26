#!/usr/bin/env python3
"""
gate.py — the fibre gate.

The pipeline renders a surface, builds a panel comparing it against a scroll
that has been read, and then runs ink inference. It does the last two in that
order, which is backwards, and the script says so in its own header: a
prediction on an ungated wrap is provisional. The queue shows it — 374 panels
waiting against 558 ink maps already computed.

So this screen exists to drain that queue. One panel at a time, the physical
measurements the pipeline recorded beside it, four buttons, next.

WHAT TO JUDGE, and it is the prize's criterion rather than ours:
  can you follow horizontal fibres across the page?
  expect wide bands, not fine striation
  expect weave — horizontals crossing verticals
  reject: closed swirls, wavy cross-section lines, rectangular blocks,
  fibre running diagonally

The question is always the same: does the right-hand side look like the left?

A NOTE ON THE OLDER PANELS. Until 20/09/2026 the header drawn inside the
image said "REFERENCIA PHercParis4 w00" and "ALVO PHerc1447". Both were stale
text. The reference has been PHerc1667 w013 for a long time, and the target
is whatever the filename says. The scale was never wrong — UM_REF matched the
real reference — so the panels are valid; only the labels lied. This screen
prints the truth underneath regardless of what the image says.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

import core

import config  # noqa: E402
# "" when there is no pipeline here; every use below checks the file exists
PIPELINE = config.pipeline_root()          # kept for callers that want one
QUEUES = [(r, os.path.join(r, "fila_gate")) for r in config.pipeline_roots()]

RE_PANEL = re.compile(r"^painel_(?P<rolo>[0-9A-Za-z]+)z(?P<z0>\d+)_"
                      r"(?P<wrap>w\d+)\.png$")

VERDICTS = [
    ("good", "Weave across the panel, like the reference."),
    ("partial", "Weave in places, melted or swirled in others."),
    ("poor", "Swirls, blocks, or fibre running diagonally."),
    ("unreadable", "Too little surface to judge."),
]

CRITERION = (
    "Can you follow horizontal fibres across the page? Expect wide bands "
    "and weave — horizontals crossing verticals. Reject closed swirls, "
    "wavy lines, rectangular blocks, fibre running diagonally. "
    "The question is whether the right looks like the left."
)

NOTE_LABELS = (
    "Panels made before 20/09/2026 have stale text drawn inside them: the "
    "reference is PHerc1667 w013, a scroll that has been read, and the "
    "target is the one named here. The scale was always right."
)


def panels() -> list[dict]:
    """Every panel in the queue, newest scroll first."""
    out = []
    for root, queue in QUEUES:
      if not os.path.isdir(queue):
        continue
      for fn in sorted(os.listdir(queue)):
        m = RE_PANEL.match(fn)
        if not m:
            continue
        out.append({
            "root": root,
            "file": os.path.join(queue, fn),
            "scroll": m.group("rolo"),
            "window": int(m.group("z0")),
            "wrap": m.group("wrap"),
            "id": f"{m.group('rolo')}/z{int(m.group('z0'))}/{m.group('wrap')}",
        })
    return out


def metrics(scroll: str, window: int, wrap: str, root: str = "") -> list[dict]:
    """The four rows the pipeline wrote for this wrap.

    One per direction and polarity. n_comp is connected components, n_void
    holes, n_sinal how many survive the signal test, pitch_p the line pitch
    where it could be measured, row_org whether rows looked organised, and
    px_surv the surviving pixel count.
    """
    # the CSV of the pipeline the panel came from; without a root, the
    # first pipeline that has one for this scroll
    roots = [root] if root else [r for r, _ in QUEUES]
    p = ""
    for r in roots:
        c = os.path.join(r, f"esteira_{scroll}.csv")
        if os.path.isfile(c):
            p = c
            break
    if not p:
        return []
    w = wrap[1:]                       # "w020" -> "020"
    out = []
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r.setdefault("dir_equipe", r.get("dir"))  # esteira_via3 writes 'dir'
            if (r.get("rolo") == scroll and r.get("z0") == str(window)
                    and r.get("wrap") == w):
                out.append(r)
    # deduplica por (direcao, polaridade), mantendo a ultima medida
    # direction in the team's terms. Migrated CSVs carry dir_equipe; an
    # old one still says "dir", named after the prediction FILE, which is
    # the other way round (no --flip-normals in this pipeline)
    ultimo = {}
    for r in out:
        if not r.get("dir_equipe"):
            r["dir_equipe"] = {"fwd": "rev", "rev": "fwd"}.get(
                r.get("dir"), r.get("dir"))
        ultimo[(r["dir_equipe"], r.get("pol"))] = r
    return list(ultimo.values())


class GatePage(QWidget):
    back = Signal()

    def __init__(self, cache: core.Cache | None = None):
        super().__init__()
        self.cache = cache or core.Cache()
        self.queue = panels()
        self.i = 0
        self.judged = self.load_judged()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(22, 14, 22, 8)
        b = QPushButton("← Back")
        b.clicked.connect(self.back)
        top.addWidget(b)
        top.addSpacing(12)
        self.title = QLabel()
        self.title.setObjectName("h2")
        top.addWidget(self.title)
        top.addStretch()
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        top.addWidget(self.progress)
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setContentsMargins(22, 0, 22, 0)
        body.setSpacing(18)

        self.panel = QLabel()
        self.panel.setAlignment(Qt.AlignCenter)
        self.panel.setMinimumHeight(520)
        body.addWidget(self.panel, 4)

        side = QVBoxLayout()
        side.setSpacing(10)
        mt = QLabel("What the pipeline measured")
        mt.setObjectName("h2")
        side.addWidget(mt)
        self.metrics = QLabel()
        self.metrics.setObjectName("muted")
        self.metrics.setTextFormat(Qt.RichText)
        self.metrics.setWordWrap(True)
        self.metrics.setAlignment(Qt.AlignTop)
        side.addWidget(self.metrics)
        side.addSpacing(8)
        crit = QLabel(CRITERION)
        crit.setObjectName("muted")
        crit.setWordWrap(True)
        side.addWidget(crit)
        note = QLabel(NOTE_LABELS)
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 12px;")
        side.addWidget(note)
        side.addStretch()
        body.addLayout(side, 2)
        outer.addLayout(body, 1)

        row = QHBoxLayout()
        row.setContentsMargins(22, 12, 22, 16)
        row.setSpacing(10)
        row.addWidget(QLabel("Does the right look like the left?"))
        self.group = QButtonGroup(self)
        self.buttons = {}
        for name, hint in VERDICTS:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setToolTip(hint)
            btn.clicked.connect(lambda _=False, n=name: self.record(n))
            self.group.addButton(btn)
            self.buttons[name] = btn
            row.addWidget(btn)
        row.addStretch()
        skip = QPushButton("skip")
        skip.clicked.connect(self.advance)
        row.addWidget(skip)
        outer.addLayout(row)

        kl = QLabel("Keys:  z good  ·  x partial  ·  c poor  ·  "
                    "v unreadable  —  each judges and moves on  ·  "
                    "s skip  ·  b back  ·  Esc")
        kl.setObjectName("muted")
        kl.setContentsMargins(22, 0, 22, 12)
        outer.addWidget(kl)

        # the triage tool's surface keys: judge and move on
        self._shortcuts = []
        for seq, fn in {
            "Z": lambda: self._judge(0), "X": lambda: self._judge(1),
            "C": lambda: self._judge(2), "V": lambda: self._judge(3),
            "S": self.advance, "Return": self.advance, "Enter": self.advance,
            "B": self.go_back, "Escape": self.back.emit,
        }.items():
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WindowShortcut)
            sc.setEnabled(False)
            sc.activated.connect(fn)
            self._shortcuts.append(sc)

        self.show_current()

    # -- state ---------------------------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        for sc in self._shortcuts:
            sc.setEnabled(True)

    def hideEvent(self, e):
        super().hideEvent(e)
        for sc in self._shortcuts:
            sc.setEnabled(False)

    def _judge(self, i: int) -> None:
        if self.current is not None:
            self.buttons[VERDICTS[i][0]].click()

    def go_back(self) -> None:
        if self.i > 0:
            self.i -= 1
            self.show_current()

    def path(self) -> str:
        return config.FINDINGS

    def load_judged(self) -> dict:
        out = {}
        p = self.path()
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
                if (r.get("unit") and r.get("surface")
                        and r.get("origin") == "gate.py"):
                    out[r["unit"]] = config.surface_en(r["surface"])
        return out

    @property
    def current(self):
        return self.queue[self.i] if 0 <= self.i < len(self.queue) else None

    def show_current(self) -> None:
        c = self.current
        if c is None:
            self.title.setText("Queue done")
            self.panel.setText("Nothing left in the gate queue.")
            self.metrics.setText("")
            return

        self.title.setText(c["id"].replace("/", " · "))
        done = sum(1 for q in self.queue if q["id"] in self.judged)
        self.progress.setText(f"{self.i + 1} of {len(self.queue)} · "
                              f"{done} judged")

        pm = QPixmap(c["file"])
        if pm.isNull():
            self.panel.setText("Could not open this panel.")
        else:
            self.panel.setPixmap(pm.scaled(
                max(400, self.panel.width()), max(400, self.panel.height()),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))

        rows = metrics(c["scroll"], c["window"], c["wrap"], c.get("root", ""))
        if rows:
            html = ["<table cellpadding='3'>"
                    "<tr><td><b>direction</b></td><td><b>pol</b></td>"
                    "<td><b>comp</b></td><td><b>void</b></td>"
                    "<td><b>signal</b></td>"
                    "<td><b>px</b></td></tr>"]
            for r in rows:
                html.append(
                    f"<tr><td>{ {'fwd': 'forward', 'rev': 'reverse'}.get(r['dir_equipe'], r['dir_equipe'])}</td>"
                    f"<td>{ {'escura': 'dark', 'clara': 'light'}.get(r.get('pol'), r.get('pol') or '—') }</td>"
                    f"<td>{r['n_comp']}</td><td>{r['n_void']}</td>"
                    f"<td>{r['n_sinal']}</td>"
                    f"<td>{r['px_surv']}</td></tr>")
            html.append("</table>")
            if any(str(r.get("row_org")).lower() == "true" for r in rows):
                html.append("<p><b>row_org</b> flagged: the pipeline thought "
                            "the rows looked organised.</p>")
            self.metrics.setText("".join(html))
        else:
            self.metrics.setText("No measurements recorded for this wrap.")

        prev = self.judged.get(c["id"])
        self.group.setExclusive(False)
        for name, btn in self.buttons.items():
            btn.setChecked(name == prev)
        self.group.setExclusive(True)

    def record(self, name: str) -> None:
        c = self.current
        if c is None:
            return
        rec = {
            "unit": c["id"],
            "surface": name,
            "verdict": None,
            "layers_seen": ["fibre gate panel"],
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "origin": "gate.py",
        }
        p = self.path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.judged[c["id"]] = name
        self.advance()

    def advance(self) -> None:
        if self.i + 1 < len(self.queue):
            self.i += 1
        self.show_current()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.current:
            pm = QPixmap(self.current["file"])
            if not pm.isNull():
                self.panel.setPixmap(pm.scaled(
                    self.panel.width(), self.panel.height(),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
