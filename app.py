#!/usr/bin/env python3
"""
app.py — Volumen.

A viewer for the Herculaneum scrolls, for people who have never opened a CT
volume. Four screens:

  Splash    the mark, then Begin
  Intro     what this is, shown once
  Scrolls   the First Letters volumes, plus the one that has been read
  Surfaces  what there is to look at inside one scroll
  Explore   one surface, full resolution, and the question

WHAT IT IS NOT. It does not trace, fit or edit anything. The Vesuvius
Challenge team makes VC3D for that, and it is better at it than anything
built here could be. This is the door: it shows what already exists and lets
someone look for writing on it.

EVERYTHING IS ON DEMAND. Measured: a mesh is four small files, 0.7 s; an ink
map is 1.5 to 6 MB, about 2 s. So there is no download step and no question
to ask — things arrive when opened.

Run:
    uv run app.py            # inside the repository: pyproject.toml
                             # carries the dependencies
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout,
                               QWidget)

import build as build_page
import progress as progress_page
import config
import core
import explore
import gate as gate_page
import folders as folders_page
import help as help_page
import sources
import surfaces

APP_NAME = "Volumen"
TAGLINE = "Read a scroll that has not been opened in two thousand years"

INK = "#e8a33d"
BG = "#16150f"
SURFACE = "#211f17"
SURFACE_HI = "#2c2920"
LINE = "#3a3529"
TEXT = "#eee8d8"
MUTED = "#9a9280"

STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT};
           font-family: "Inter", "Segoe UI", sans-serif; font-size: 14px; }}
QLabel#h1 {{ font-size: 30px; font-weight: 500; }}
QLabel#h2 {{ font-size: 19px; font-weight: 500; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#body {{ font-size: 16px; line-height: 150%; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {LINE};
               border-radius: 14px; }}
QFrame#card:hover {{ background: {SURFACE_HI}; border: 1px solid {INK}; }}
QFrame#empty:hover, QFrame#empty2:hover, QFrame#empty3:hover
    {{ border: 1px dashed {MUTED}; }}
QFrame#demo {{ background: {SURFACE}; border: 1px solid {INK};
               border-radius: 14px; }}
QFrame#empty {{ background: transparent; border: 1px dashed {LINE};
                border-radius: 14px; }}
QFrame#empty2 {{ background: transparent; border: 1px dashed #2b2721;
                 border-radius: 14px; }}
QFrame#empty3 {{ background: transparent; border: 1px dashed #241f1a;
                 border-radius: 14px; }}
QFrame#empty QLabel {{ color: #7d7666; background: transparent; }}
QFrame#empty2 QLabel {{ color: #625c50; background: transparent; }}
QFrame#empty3 QLabel {{ color: #4e483f; background: transparent; }}
QFrame#empty QLabel#h2 {{ color: #9a9280; }}
QFrame#empty2 QLabel#h2 {{ color: #7a7364; }}
QFrame#empty3 QLabel#h2 {{ color: #5e584d; }}
QFrame#card QLabel, QFrame#demo QLabel, QFrame#empty QLabel
    {{ background: transparent; }}
QPushButton {{ background: {SURFACE_HI}; border: 1px solid {LINE};
               border-radius: 8px; padding: 9px 18px; }}
QPushButton:hover {{ border: 1px solid {INK}; }}
QPushButton:disabled {{ color: #5a5449; border: 1px solid #2a2820;
                        background: transparent; }}
QPushButton:checked {{ background: {INK}; color: #1a1408;
                       border: 1px solid {INK}; }}
QPushButton#primary {{ background: {INK}; color: #1a1408; border: none;
                       font-weight: 500; }}
QPushButton#primary:hover {{ background: #f4bc5e; }}
QPushButton#primary:disabled {{ background: #2a2820; color: #5a5449; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 5px;
                               min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QLabel#badge {{ color: {MUTED}; border: 1px solid {LINE};
                border-radius: 9px; padding: 2px 9px; font-size: 12px; }}
QTreeWidget {{ background: {SURFACE}; border: 1px solid {LINE};
               border-radius: 10px; }}
QTreeWidget::item {{ padding: 5px 2px; }}
QTreeWidget::item:selected {{ background: {SURFACE_HI}; color: {INK}; }}
QHeaderView::section {{ background: {BG}; border: none;
                        border-bottom: 1px solid {LINE}; padding: 7px; }}
QProgressBar {{ background: {BG}; border: none; }}
QProgressBar::chunk {{ background: {INK}; }}
"""


# ------------------------------------------------------------------ mark --
class Mark(QWidget):
    """The V, drawn rather than loaded, so it is crisp at any size."""

    def __init__(self, size: int = 48, parent=None):
        super().__init__(parent)
        self._s = size
        self._progress = 1.0
        self.setFixedSize(size, size)

    def set_progress(self, v: float) -> None:
        self._progress = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        u = self._s / 48.0
        for x0, x1, w, alpha, start in ((8, 40, 4.2, 1.0, 0.00),
                                        (15, 33, 3.0, 0.58, 0.25),
                                        (20.5, 27.5, 2.1, 0.32, 0.50)):
            t = max(0.0, min(1.0, (self._progress - start) / 0.5))
            if t <= 0:
                continue
            c = QColor(INK)
            c.setAlphaF(alpha * t)
            p.setPen(QPen(c, w * u, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            apex = 9 + (42 - 9) * ((24 - x0) / (24 - 8))
            mid = 9 + (apex - 9) * t
            p.drawLine(int(x0 * u), int(9 * u),
                       int((x0 + (24 - x0) * t) * u), int(mid * u))
            p.drawLine(int(x1 * u), int(9 * u),
                       int((x1 - (x1 - 24) * t) * u), int(mid * u))
        p.end()


# ---------------------------------------------------------------- splash --
class Splash(QWidget):
    done = Signal()

    def __init__(self, footer: bool = True):
        super().__init__()
        # the same footer as every other screen; off when this screen is
        # reused as About inside the main window, which already has one
        self.foot = None
        if footer:
            self.foot = QLabel(FOOTER, self)
            self.foot.setObjectName("muted")
            self.foot.setAlignment(Qt.AlignCenter)
            self.foot.setStyleSheet(
                f"border-top: 1px solid {LINE}; font-size: 12px;")
        # the signature: one quiet line above the footer, on the opening
        # screen and in About alike; the full credits are in How this works
        self.credit = QLabel(
            "by pscamillo - <a href='https://github.com/pscamillo/volumen' "
            "style='color:#e8a33d; text-decoration:none'>"
            "https://github.com/pscamillo/volumen</a>", self)
        self.credit.setObjectName("muted")
        self.credit.setAlignment(Qt.AlignCenter)
        self.credit.setTextFormat(Qt.RichText)
        self.credit.setOpenExternalLinks(True)
        self.credit.setStyleSheet("font-size: 12px;")
        self.setStyleSheet(STYLE)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(18)
        # centred, so a margin below lifts the whole block (~ one line per
        # 48 px of margin)
        lay.setContentsMargins(0, 0, 0, 48)

        # opening screen / About: sizes in one place (24/09: 132 / h1 / 6)
        SPLASH_MARK, SPLASH_NAME_PX, SPLASH_SPACING = 176, 46, 9
        self.mark = Mark(SPLASH_MARK)
        lay.addWidget(self.mark, alignment=Qt.AlignHCenter)

        self.name = QLabel(APP_NAME)
        self.name.setObjectName("h1")
        self.name.setStyleSheet(f"font-size: {SPLASH_NAME_PX}px;")
        self.name.setAlignment(Qt.AlignCenter)
        f: QFont = self.name.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, SPLASH_SPACING)
        self.name.setFont(f)

        lay.addWidget(self.name)

        self.tag = QLabel("scroll workbench")
        self.tag.setObjectName("muted")
        self.tag.setAlignment(Qt.AlignCenter)
        # not shown since 24/09: the first paragraph already says it

        lay.addSpacing(14)
        self.blurbs = []
        for text in INTRO:
            t = QLabel(text)
            t.setObjectName("body")
            # a touch below the body text, so the mark and the name lead
            t.setStyleSheet("color: #c9c1b2;")
            t.setWordWrap(True)
            t.setTextFormat(Qt.RichText)
            t.setAlignment(Qt.AlignCenter)
            # largura fixa: com maximumWidth num layout centralizado o
            # rotulo encolhe ao minimo e o texto sai cortado
            t.setFixedWidth(820)
            lay.addWidget(t, alignment=Qt.AlignHCenter)
            self.blurbs.append(t)

        lay.addSpacing(22)
        for t_ in self.blurbs:
            t_.setOpenExternalLinks(True)
        self.begin = QPushButton("Begin")
        self.begin.setObjectName("primary")
        self.begin.setFixedWidth(180)
        self.begin.clicked.connect(self.finish)
        lay.addWidget(self.begin, alignment=Qt.AlignHCenter)

        for w in (self.name, self.tag, *self.blurbs, self.begin):
            e = QGraphicsOpacityEffect(w)
            w.setGraphicsEffect(e)
            e.setOpacity(0.0)

        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._t += 0.016
        self.mark.set_progress(min(1.0, self._t / 1.4))
        steps = [(self.name, 0.9), (self.tag, 1.3)]
        steps += [(w, 1.7 + 0.35 * i) for i, w in enumerate(self.blurbs)]
        steps.append((self.begin, 1.7 + 0.35 * len(self.blurbs) + 0.3))
        for w, start in steps:
            e = w.graphicsEffect()
            if e:
                e.setOpacity(max(0.0, min(1.0, (self._t - start) / 0.6)))
        if self._t > steps[-1][1] + 0.9:
            self._timer.stop()

    def finish(self):
        self._timer.stop()
        self.done.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.foot is not None:
            self.foot.setGeometry(0, self.height() - 42, self.width(), 42)
        # two lines above the footer (or above the bottom edge, in About)
        base = self.height() - (42 if self.foot is not None else 0)
        self.credit.setGeometry(0, base - 40, self.width(), 24)

    def show_at_once(self) -> None:
        """Sem animacao: e' assim que o About reusa esta tela."""
        self._timer.stop()
        self.mark.set_progress(1.0)
        for w in (self.name, self.tag, *self.blurbs, self.begin):
            e = w.graphicsEffect()
            if e:
                e.setOpacity(1.0)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space,
                       Qt.Key_Escape):
            self.finish()


# ----------------------------------------------------------------- intro --
INTRO = [
    "A workbench for the scrolls eligible for the Vesuvius Challenge's "
    "<a href='https://scrollprize.org/prizes' style='color:#e8a33d; text-decoration:none'>First Letters prize</a>: "
    "make surfaces with the minimal route, gate them, check the cuts, and "
    "look for writing.",

    "Surfaces are fitted, never traced by hand. For that, and much more, "
    "there is <a href='https://github.com/ScrollPrize/villa/tree/main/volume-cartographer' style='color:#e8a33d; text-decoration:none'>VC3D</a>, the Vesuvius Challenge's own "
    "tool — any surface here can be exported to it as a ready-made project.",
]

def _version() -> str:
    """From pyproject.toml beside this file (the repo); "dev" elsewhere."""
    import re
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyproject.toml")
    try:
        m = re.search(r'^version\s*=\s*"([^"]+)"', open(p, encoding="utf-8").read(), re.M)
        return m.group(1) if m else "dev"
    except OSError:
        return "dev"


# what serves the person on every screen: version (for bug reports), the
# data's origin and licence (a CC BY-NC condition), and non-affiliation.
# Credits live in About, the README and LICENSE.
FOOTER = (f"Volumen {_version()}  ·  "
          "Data: Vesuvius Challenge open data, CC BY-NC 4.0  ·  "
          "An independent project, not affiliated with the Scroll Prize")


class IntroPage(QWidget):
    done = Signal()

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(22)
        lay.setContentsMargins(140, 40, 140, 40)

        m = Mark(72)
        lay.addWidget(m, alignment=Qt.AlignHCenter)

        for lead, rest in INTRO:
            t = QLabel(f"<b>{lead}</b> {rest}")
            t.setObjectName("body")
            t.setWordWrap(True)
            t.setAlignment(Qt.AlignCenter)
            # largura FIXA: com maximumWidth num layout centralizado o
            # rotulo encolhe ao minimo e o texto sai cortado
            t.setFixedWidth(900)
            lay.addWidget(t, alignment=Qt.AlignHCenter)

        lay.addSpacing(10)
        b = QPushButton("Show me the scrolls")
        b.setObjectName("primary")
        b.setFixedWidth(260)
        b.clicked.connect(self.done)
        lay.addWidget(b, alignment=Qt.AlignHCenter)


# ----------------------------------------------------------------- cards --
# What a card says when a scroll has nothing prepared. The words avoid the
# community's jargon: someone arriving here has never heard of lasagna.
# What a card says when a scroll has nothing prepared. No jargon, and no
# offer of a workaround: fitting without lasagna was tried and dropped on
# 25/09 — it crossed sheets on 0175B and put the axis on the edge of 0826.
ROUTE_TEXT = {
    # what the app can know is what is on THIS machine, not what anyone
    # else has run — so no "nobody has run it"
    "lasagna": "Everything the fitter needs is published — not run on "
               "this machine yet",
    "no lasagna": "No lasagna published yet — grow a patch in VC3D and "
                  "add its .volpkg in Folders",
    "no tracks": "Scanned, but no tracks published — nothing to fit yet",
    "demo": "Already read — use it to calibrate your eye",
}
# without a pipeline on this machine the route texts above describe work
# the person cannot do here; say what they can do instead (23/09)
NO_PIPELINE_TEXT = ("No surfaces for this scroll yet — grow a patch in "
                    "VC3D and add its .volpkg in Folders")


class OtherCard(QFrame):
    """A scroll outside the prize set, from the person's own folders."""
    picked = Signal(str)

    def __init__(self, name: str, n_units: int, n_seen: int):
        super().__init__()
        self.scroll_name = name
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(120)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)

        title = QLabel(f"PHerc{name}")
        title.setObjectName("h2")
        lay.addWidget(title)

        sub = QLabel("not in the prize set · scale unknown")
        sub.setObjectName("muted")
        lay.addWidget(sub)

        body = QLabel(f"{n_units} surface{'s' if n_units != 1 else ''} "
                      f"from your folders"
                      + (f" · {n_seen} looked at" if n_seen else ""))
        body.setObjectName("muted")
        lay.addWidget(body)
        lay.addStretch()

    def mousePressEvent(self, _):
        self.picked.emit(self.scroll_name)


class ScrollCard(QFrame):
    picked = Signal(str)

    def __init__(self, s: core.Scroll, n_units: int, n_seen: int,
                 n_gate: int = 0, n_ruim: int = 0):
        super().__init__()
        self.scroll_name = s.name
        withdrawn = (not s.eligible) and s.route != "demo" and bool(s.note)
        # dois niveis de apagado nos vazios: com lasanha e' so' rodar; sem
        # lasanha (ou sem tracks) a superficie vem de um patch do VC3D
        if s.route == "demo":
            name = "demo"
        elif withdrawn:
            name = "empty3"           # dimmed like the others; the badge says it
        elif n_units:
            name = "card"
        elif s.route == "lasagna":
            name = "empty"
        else:
            name = "empty3"
        self.setObjectName(name)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(152)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(6)

        top = QHBoxLayout()
        title = QLabel(s.label)
        title.setObjectName("h2")
        top.addWidget(title)
        top.addStretch()
        if s.route == "demo" or withdrawn:
            tag = QLabel("letters found" if withdrawn else "demo")
            tag.setObjectName("badge")
            tag.setStyleSheet(f"color:{INK}; border-color:{INK};")
            top.addWidget(tag)
        lay.addLayout(top)

        sub = QLabel(f"{s.voxel_um:g} µm per voxel")
        sub.setObjectName("muted")
        lay.addWidget(sub)

        if withdrawn:
            body = s.note + " — still in the Grand Prize"
        elif s.route == "demo":
            body = ROUTE_TEXT["demo"]
        elif n_units:
            # tres julgamentos, tres contagens: somar tinta, superficie e
            # gate numa so' fazia um rolo parecer pronto quando nenhum
            # painel tinha passado pelo gate de fibras
            bits = [f"{n_units} surface{'s' if n_units != 1 else ''}"]
            if n_seen:
                bits.append(f"{n_seen} judged for ink")
            if n_gate:
                bits.append(f"{n_gate} through the gate")
            body = " · ".join(bits)
        elif n_ruim:
            # run here, and every window failed to fit: a different
            # situation from never having been run
            body = (f"Run here — all {n_ruim} window"
                    f"{'s' if n_ruim != 1 else ''} were tried, "
                    f"the fit found no winding")
        elif not config.pipeline_ok():
            body = NO_PIPELINE_TEXT
        else:
            body = ROUTE_TEXT.get(s.route, "Nothing prepared yet")
        b = QLabel(body)
        b.setObjectName("muted")
        b.setWordWrap(True)
        lay.addWidget(b)
        lay.addStretch()

    def mousePressEvent(self, _):
        self.picked.emit(self.scroll_name)


class ScrollsPage(QWidget):
    picked = Signal(str)
    quit_asked = Signal()
    help_asked = Signal()
    build_asked = Signal()
    progress_asked = Signal()
    gate_asked = Signal()
    folders_asked = Signal()
    about_asked = Signal()

    def __init__(self):
        super().__init__()
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(40, 24, 40, 18)
        self.outer.setSpacing(6)

        head = QHBoxLayout()
        # um espacador da largura dos botoes da direita, senao o titulo fica
        # centrado no que sobra em vez de na janela
        self.head_pad = QWidget()
        head.addWidget(self.head_pad)
        head.addStretch()
        m = Mark(34)
        m.set_progress(1.0)
        head.addWidget(m)
        t = QLabel(APP_NAME)
        t.setObjectName("h1")
        head.addWidget(t)
        head.addStretch()
        ab = QPushButton("About")
        ab.clicked.connect(self.about_asked)
        pb = QPushButton("Progress")
        pb.clicked.connect(self.progress_asked)
        head.addWidget(pb)
        mb = QPushButton("Make surfaces")
        mb.clicked.connect(self.build_asked)
        head.addWidget(mb)
        gb = QPushButton("Fibre gate")
        gb.clicked.connect(self.gate_asked)
        head.addWidget(gb)
        fb = QPushButton("Folders")
        fb.clicked.connect(self.folders_asked)
        head.addWidget(fb)
        hb = QPushButton("How this works")
        # until the person has opened it once, a slow pulse says "start
        # here" — the same breath as Make flattened view; gone after the
        # first click, for good (25/09). Aliased imports: a plain one here
        # would make the names local to the whole function.
        import config as _cfg
        if not _cfg.help_seen():
            from PySide6 import QtCore as _QtCore
            # the amber breathes in and out of the button's own colour, slowly

            def _mix(a, b, t):
                return "#%02x%02x%02x" % tuple(
                    round(a[k] + (b[k] - a[k]) * t) for k in range(3))
            _amb, _bg = (232, 163, 61), (38, 35, 29)
            _an = _QtCore.QVariantAnimation(hb)
            _an.setStartValue(0.06)
            _an.setKeyValueAt(0.5, 1.0)
            _an.setEndValue(0.06)
            _an.setDuration(3200)
            _an.setEasingCurve(_QtCore.QEasingCurve.InOutSine)
            _an.setLoopCount(-1)

            def _paint(t, b=hb):
                # only the background breathes; the text stays as on every
                # other button
                b.setStyleSheet(f"background:{_mix(_bg, _amb, float(t))};")
            _an.valueChanged.connect(_paint)
            _an.start()
            self._help_pulse = _an

            def _seen(*_a, b=hb, an=_an):
                _cfg.mark_help_seen()
                an.stop()
                b.setStyleSheet("")
            hb.clicked.connect(_seen)
        hb.clicked.connect(self.help_asked)
        head.addWidget(hb)
        q = QPushButton("Exit")
        q.clicked.connect(self.quit_asked)
        head.addWidget(ab)
        head.addWidget(q)
        # o Fibre gate faltava aqui, e o titulo ficava deslocado pela
        # largura dele desde que o gate entrou no cabecalho
        # the actions move to a bar under the grid, where the space is;
        # only Exit stays in the corner
        for b_ in (pb, mb, gb, fb, hb, ab):
            head.removeWidget(b_)
        self.buttons_row = (q,)
        bar = QHBoxLayout()
        bar.setSpacing(12)
        bar.addStretch()
        # the working cycle, in the order it happens
        for b_ in (mb, gb, pb):
            b_.setStyleSheet("padding: 12px 30px; font-size: 15px;")
            bar.addWidget(b_)
        bar.addSpacing(36)
        for b_ in (fb, hb, ab):
            bar.addWidget(b_)
        bar.addStretch()
        self._action_bar = bar
        self.outer.addLayout(head)

        self.sub = QLabel()
        self.sub.setObjectName("muted")
        self.sub.setAlignment(Qt.AlignCenter)
        self.sub.setWordWrap(True)
        self.outer.addWidget(self.sub)
        self.outer.addSpacing(30)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.outer.addWidget(self.area)
        self.outer.addSpacing(8)
        self.outer.addLayout(self._action_bar)
        self.outer.addSpacing(34)

    def showEvent(self, e):
        super().showEvent(e)
        w = sum(b.width() for b in self.buttons_row) + 6 * len(
            self.buttons_row)
        self.head_pad.setFixedWidth(w)

    def fill(self, catalog: sources.Catalog, seen: dict,
             gated: dict | None = None) -> None:
        by = catalog.by_scroll()
        ready = sum(len(v) for v in by.values())
        n_gate = len(gated or {})
        ruins = progress_page.ruim_windows()
        self.sub.setText(
            f"{ready} surfaces across {len(by)} of the {len(core.ELIGIBLE)} eligible volumes. "
            f"{len(seen)} judged for ink, {n_gate} through the fibre gate. "
            f"The remaining scrolls have nothing prepared yet.")

        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setSpacing(14)
        grid.setContentsMargins(0, 0, 8, 0)

        order = [s for s in core.DEMO if s.name == "Paris4"]
        order += sorted(core.ELIGIBLE, key=lambda x: (-len(by.get(x.name, [])),
                                                      x.name))
        # scrolls withdrawn from the prize keep a card: where they went is
        # news the person needs (1447, letters found, 24 Sep 2026)
        order += sorted((s for s in core.SCROLLS.values()
                         if not s.eligible and s.route != "demo" and s.note),
                        key=lambda x: x.name)
        row = col = 0
        for s in order:
            us = by.get(s.name, [])
            n_seen = sum(1 for u in us if u.id in seen)
            n_gate = sum(1 for u in us if u.id in (gated or {}))
            c = ScrollCard(s, len(us), n_seen, n_gate,
                           len(ruins.get(s.name, ())))
            c.picked.connect(self.picked)
            grid.addWidget(c, row, col)
            col += 1
            if col >= 4:
                col, row = 0, row + 1
        # rolos fora dos 23, vindos das pastas da pessoa
        extras = sorted(k for k in by
                        if k not in core.SCROLLS)
        if extras:
            row += 1
            head = QLabel("Also on this machine")
            head.setObjectName("h2")
            head.setContentsMargins(4, 22, 0, 2)
            grid.addWidget(head, row, 0, 1, 4)
            note = QLabel("Scrolls outside the First Letters set, found in "
                          "your folders. Volumen does not know the voxel "
                          "size for these, so there is no scale bar.")
            note.setObjectName("muted")
            note.setWordWrap(True)
            note.setContentsMargins(4, 0, 0, 8)
            grid.addWidget(note, row + 1, 0, 1, 4)
            row += 2
            col = 0
            for k in extras:
                us = by[k]
                n_seen = sum(1 for u in us if u.id in seen)
                c = OtherCard(k, len(us), n_seen)
                c.picked.connect(self.picked)
                grid.addWidget(c, row, col)
                col += 1
                if col >= 4:
                    col, row = 0, row + 1

        grid.setRowStretch(row + 1, 1)
        self.area.setWidget(holder)


# ------------------------------------------------------------------ main --
class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)
        self.setStyleSheet(STYLE)

        self.cache = core.Cache()
        self.catalog = sources.Catalog(cache=self.cache).load()

        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.stack)

        foot = QLabel(FOOTER)
        foot.setObjectName("muted")
        foot.setAlignment(Qt.AlignCenter)
        foot.setContentsMargins(0, 8, 0, 10)
        foot.setStyleSheet(f"border-top: 1px solid {LINE}; font-size: 12px;")
        lay.addWidget(foot)

        # o About reusa a tela de abertura, parada
        self.intro = Splash(footer=False)
        self.intro.begin.setText("Back to the scrolls")
        self.intro.done.connect(self.to_scrolls)
        self.stack.addWidget(self.intro)

        self.scrolls = ScrollsPage()
        self.scrolls.picked.connect(self.open_scroll)
        self.scrolls.quit_asked.connect(QApplication.quit)
        self.scrolls.help_asked.connect(
            lambda: self.stack.setCurrentWidget(self.help))
        self.scrolls.folders_asked.connect(
            lambda: self.stack.setCurrentWidget(self.folders))
        self.scrolls.gate_asked.connect(self.open_gate)
        self.scrolls.build_asked.connect(self.open_build)
        self.scrolls.progress_asked.connect(self.open_progress)
        self.scrolls.about_asked.connect(self.show_about)
        self.stack.addWidget(self.scrolls)

        self.progress = progress_page.ProgressPage()
        self.progress.back.connect(self.to_scrolls)
        self.progress.picked.connect(self.open_scroll)
        self.stack.addWidget(self.progress)

        self.build = build_page.BuildPage()
        self.build.back.connect(self.to_scrolls)
        # a esteira terminou ou parou: o catalogo relê o disco
        self.build.produced.connect(self.reload_catalog)
        self.stack.addWidget(self.build)

        self.gate = gate_page.GatePage(self.cache)
        self.gate.back.connect(self.to_scrolls)
        self.stack.addWidget(self.gate)

        self.folders = folders_page.FoldersPage()
        self.folders.back.connect(self.to_scrolls)
        self.folders.changed.connect(self.reload_catalog)
        self.stack.addWidget(self.folders)

        self.help = help_page.HelpPage()
        self.help.back.connect(self.to_scrolls)
        self.stack.addWidget(self.help)

        self.surfaces = surfaces.SurfacesPage(self.cache)
        self.surfaces.back.connect(self.to_scrolls)
        self.surfaces.opened.connect(self.open_unit)
        self.stack.addWidget(self.surfaces)

        self.explore = explore.ExplorePage(self.cache)
        self.explore.back.connect(self.back_from_explore)
        self.explore.lesson.connect(self.open_lesson)
        self.explore.step_asked.connect(self.step_unit)
        self.stack.addWidget(self.explore)

        self.came_from = None
        self.to_scrolls()

    # -- helpers -------------------------------------------------------
    def intro_flag(self) -> str:
        return os.path.join(self.cache.root, "seen-intro")

    def seen_intro(self) -> bool:
        return os.path.isfile(self.intro_flag())

    def findings(self) -> dict:
        return surfaces.read_findings(self.cache)

    def intro_finished(self):
        p = self.intro_flag()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()
        self.to_scrolls()

    def show_about(self):
        self.intro.show_at_once()
        self.stack.setCurrentWidget(self.intro)

    def open_progress(self):
        # read fresh each time: the pipeline and the gate move it along
        self.progress.fill(self.catalog, self.cache)
        self.stack.setCurrentWidget(self.progress)

    def open_build(self):
        self.build.refresh()
        self.stack.setCurrentWidget(self.build)

    def open_gate(self):
        # a fila muda enquanto a esteira roda, entao recarrega ao entrar
        self.gate.queue = gate_page.panels()
        self.gate.judged = self.gate.load_judged()
        self.gate.i = 0
        self.gate.show_current()
        self.stack.setCurrentWidget(self.gate)

    def reload_catalog(self):
        self.catalog = sources.Catalog(cache=self.cache).load()

    def gated(self) -> dict:
        import gate as gate_page
        out = {}
        p = config.FINDINGS
        if not os.path.isfile(p):
            return out
        import json
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if r.get("unit") and r.get("origin") == "gate.py":
                    out[r["unit"]] = r.get("surface")
        return out

    def to_scrolls(self):
        self.scrolls.fill(self.catalog, self.findings(), self.gated())
        self.stack.setCurrentWidget(self.scrolls)

    # -- navigation ----------------------------------------------------
    def open_scroll(self, name: str):
        s = core.SCROLLS.get(name)
        if s is None:
            units = self.catalog.by_scroll().get(name, [])
            if units:
                self.surfaces.show_scroll(name, units)
                self.stack.setCurrentWidget(self.surfaces)
            return
        if s.route == "demo":
            self.came_from = self.scrolls
            self.explore.show_view(explore.demo_view())
            self.stack.setCurrentWidget(self.explore)
            return
        units = self.catalog.by_scroll().get(name, [])
        # a scroll withdrawn from the prize: say why, not what the pipeline
        # would need (1447, 25/09)
        if not units and s is not None and not s.eligible and s.note:
            self.scrolls.sub.setText(
                f"{s.label} was {s.note[0].lower() + s.note[1:]}. It remains "
                "in the Grand Prize; nothing is prepared for it on this "
                "machine.")
            return
        if not units:
            why = (ROUTE_TEXT.get(s.route, "") if s else "")
            if not config.pipeline_ok():
                why = NO_PIPELINE_TEXT
            self.scrolls.sub.setText(
                f"{s.label if s else name} has no surfaces prepared yet. "
                f"{why}. "
                f"\"How this works\" explains what that means.")
            return
        self.surfaces.show_scroll(name, units)
        self.stack.setCurrentWidget(self.surfaces)

    def open_unit(self, unit):
        self.came_from = self.surfaces
        self.explore.show_view(explore.unit_view(unit))
        self.stack.setCurrentWidget(self.explore)

    def step_unit(self, d: int):
        """Enter or s: the next surface in the list; b: the previous one."""
        if self.came_from is not self.surfaces or not self.surfaces.units:
            return
        v = self.explore.view_data
        ids = [u.id for u in self.surfaces.units]
        if v is None or v.key not in ids:
            return
        j = ids.index(v.key) + d
        if 0 <= j < len(ids):
            self.open_unit(self.surfaces.units[j])

    def open_lesson(self):
        self.explore.show_view(explore.lesson_view())

    def back_from_explore(self):
        if self.came_from is self.surfaces:
            self.surfaces.show_scroll(self.surfaces.scroll_name,
                                      self.surfaces.units)
            self.stack.setCurrentWidget(self.surfaces)
        else:
            self.to_scrolls()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F11:
            (self.showNormal() if self.isFullScreen()
             else self.showFullScreen())
        elif e.key() == Qt.Key_Escape:
            if self.stack.currentWidget() is self.scrolls:
                self.close()
            else:
                self.to_scrolls()
        else:
            super().keyPressEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    splash = Splash()
    splash.resize(1360, 860)
    splash.show()
    splash.showFullScreen()

    win = Main()

    def go():
        splash.showNormal()
        splash.close()
        splash.deleteLater()
        win.showMaximized()
        win.raise_()
        win.activateWindow()

    splash.done.connect(go)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
