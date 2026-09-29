#!/usr/bin/env python3
"""
help.py — How this works.

Grouped in the order of the work: make surfaces, check them, read the ink,
keep track, and what to do if letters turn up. Every criterion here comes
with the case it was learned from, so it can be checked rather than trusted.

Rendered in a QTextBrowser: it scrolls, selects, copies and opens links. A
column of wrapped QLabels clipped its text and would not let it be copied.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

VC3D = "https://github.com/ScrollPrize/villa/tree/main/volume-cartographer"
LASAGNA = "https://github.com/ScrollPrize/villa/tree/main/lasagna"
VILLA = "https://github.com/ScrollPrize/villa"
PRIZES = "https://scrollprize.org/prizes"
MESHES = "https://github.com/pscamillo/vesuvius-eligible-meshes"


def a(url: str, text: str) -> str:
    return f"<a href='{url}'>{text}</a>"


GROUPS = [
    ('The loop', [
        ('What this is for',
         'Volumen runs one loop: get surfaces, check that each sits on a single sheet, look for writing on those that do, and keep a record of every judgement. Surfaces come three ways: the 340 of ' + a(MESHES, 'vesuvius-eligible-meshes') + ' are here from the start, published by the author for eight eligible scrolls with the same minimal route this app runs; <b>Make surfaces</b> fits new ones, on Linux with an NVIDIA GPU; and <b>Folders</b> brings in your own, grown in VC3D or from any tifxyz folder. None comes verified, and the checks below apply to every one. Everything but making surfaces runs on an ordinary computer, with no GPU — uv brings its own Python. Volumen fits surfaces but never traces or edits them — that is ' + a(VC3D, 'VC3D') + ', and any surface here exports to it as a ready-made project.'),
        ('Why judge',
         'A scroll has hundreds of surfaces. The ones you mark as sound are the short list you come back to; one judged sound with nothing on it you will not open again. Verdicts stay on this machine.'),
    ]),
    ('Using the app', [
        ('The scroll grid',
         'Bright cards have surfaces, with how many were judged for ink and went through the gate. Dimmed cards have none yet: the lighter shade has lasagna and only needs the pipeline run; the darker has no lasagna or no tracks, and its surfaces come from VC3D. PHerc Paris 4, already read, is there to calibrate the eye; scrolls withdrawn from the prize close the grid, with the reason.'),
        ('The surface list',
         "One row per surface: window, wrap, area, the package's own verdict on its shape, and yours. Rest the pointer on a row to preview its ink map — for choosing what to open, never for judging."),
        ('The surface view',
         'The buttons at the top right are the layers: <i>Surface · CT</i>, <i>Ink · forward</i> and <i>reverse</i>, and <i>Cut 1–3</i> once cuts exist. The bar is 1 mm and the dashed square the size of a letter, at the current zoom. Three rows record what you see, in the order to judge them — Surface · CT, Sheet · cuts, Ink — and only the row for the open layer can be judged; <i>i</i> over the CT opens surface and ink together. With a cut open, the sheet row becomes <i>This cut</i>: follows one sheet, crosses sheets, can’t tell, with an optional note. Amber lines warn when a verdict does not rest on what was opened. A package surface first needs <b>Make flattened view</b>, which reads the CT along the mesh as vc_render_tifxyz would, without VC3D. <b>Make cut</b> takes about fifteen seconds.'),
        ('Open in VC3D',
         'Builds a project for VC3D in <code>~/Volumen exports/</code> and lists the steps left, with buttons to copy the folder path and the volume URL.'),
        ('Make surfaces',
         "Pick a scroll and how many windows, then <b>Start</b>; <b>Show log</b> follows it live. One run at a time; new surfaces join the lists when the run ends. Without a pipeline, <b>Set up the pipeline…</b> checks this machine, shows what it would download and installs only after you say yes; <b>Prepare another scroll…</b> fetches each scroll's inputs and ends by showing its axis on three slices — accept it only if it sits in the middle of the rings on all three. What it takes: Linux, or WSL2 on Windows (expected to work, not yet tested); an NVIDIA GPU with a CUDA 12.8 driver — 12 GB of VRAM tested, 6 GB very tight; 32 GB of RAM comfortable, 16 GB tight; about 20 GB to install and 5–13 GB per scroll."),
        ('The fibre gate',
         'Each panel the pipeline made, next to one from PHerc1667 w013, a scroll that has been read. Can you follow horizontal fibres across it, crossing verticals? Swirls, wavy lines, blocks or diagonal fibre mean it is not on a sheet. Judge with the four buttons; <b>skip</b> leaves it for later. Beside each panel, what the pipeline measured. Empty without the pipeline.'),
        ('Folders',
         "The package comes over the network on its own. Add folders for local surfaces, ink maps or a pipeline's working folder; a VC3D .volpkg shows every patch under <code>paths/</code>, like any other surface."),
        ('Keys',
         'Surface view: 1–4 ink, z x c v surface (good, partial, poor, unreadable), Tab and Shift+Tab layers, i ink over the CT, o fit or one pixel per voxel, e scale bar, + − zoom, Enter or s next surface, b previous, Esc the list. Fibre gate: z x c v judge and move on, s skip, b back.'),
    ]),
    ('Making surfaces', [
        ('How a surface is made',
         "The writing is on a sheet wound hundreds of times inside the CT. A fitter deforms an ideal spiral until it matches the real, crushed scroll, and each winding is then flattened into a page. The minimal route, the team's smallest set of inputs (code in " + a(VILLA, 'villa') + '), needs tracks (where sheet material is), an umbilicus (the axis through the middle) and ' + a(LASAGNA, 'lasagna') + ' (which way each sheet faces), published for some eligible scrolls, not all. Make surfaces checks daily and says when a scroll gains lasagna; for the others, grow a patch in VC3D and add its .volpkg in Folders.'),
        ('Stopping, and windows with no winding',
         'A window counts as finished from what is on disk, so <b>Stop</b> lets the current one finish; a second click, <b>Stop now</b>, kills it and moves the half-made window to <code>_interrupted/</code>, to be redone. A window where the fit finds no winding is marked as tried — most sit at the top and bottom of a scroll — and Progress draws it hatched.'),
    ]),
    ('Checking the surface', [
        ('A surface, step by step',
         'Look at the flattened CT first, not the ink. <b>1. Surface:</b> can you follow fibres, horizontals crossing verticals? Clean weave is good; in parts, partial; swirls, blocks or diagonal fibre, poor; nothing readable, unreadable. <b>2. Sheet:</b> make the cuts and label each (below). <b>3. Ink</b>, last, only on surfaces that passed both: zoom until the dashed square is large and look for organisation — marks in rows, regularly spaced, letter-sized. Most maps at 9 µm show nothing; <i>nothing but texture</i> is a real answer.'),
        ('The failure to watch for',
         'The worst failure of every unwrapping method: the surface crosses to the next winding, and ink there may belong to the neighbouring sheet. The usual checks miss it, because the surface is still inside the scroll. It was seen here on a 0125 surface on 21 Sep 2026, and the cut is the test that caught it. Marking a surface as having shapes of letters makes the app cut it on its own.'),
        ('Labelling a cut',
         "A cut is one slice of the raw CT with the surface drawn across it in amber; the grey layers are the sheets. Zoom until they separate, follow the line end to end, and ask: does it sit on a bright layer, not in a dark gap? Does it stay on the same one — count the layers to a landmark near each end? Where it bends, do the layers bend with it? <i>Follows one sheet</i> only if all three hold along the whole line. If it leaves its layer anywhere, it <i>crosses sheets</i> — note where, since ink away from that stretch may still be sound. <i>Can't tell</i> is for layers too merged to follow over much of the line. On an inner wrap the same winding may cross a cut twice; judge each line against its own layer. The three cuts cross different parts of a surface, and each label is about its own."),
    ]),
    ('Reading the ink', [
        ('Calibrating the eye',
         'PHerc Paris 4 has been read: open it before a scroll nobody has, and when a long session starts to blur. It is a 2.4 µm scan; at 8.6 or 9.4 µm writing is far blurrier, and what separates it from noise is organisation, not sharpness.'),
        ('Not fooling yourself',
         'A flat-looking map at low zoom is not evidence of absence; a map read here as noise once turned out to hold strokes. Zoom in until the dashed square is large; the app warns when it is not. Real writing sits on one face, so it tends to answer strongly in one direction and weakly in the other; a mark the same both ways is more likely inside the papyrus. The ink model was trained at 9.362 µm, so on 8.64 µm scrolls its answer is approximate — good for choosing where to look.'),
        ('What the wrap number means',
         'Each surface is one winding, counted outward from the middle. Inner wraps hold up better — across eight scrolls, 83% of w020 surfaces looked clean against 33% at w100 — but are smaller, about 2 cm² at w020 against 8–10 cm² at w100. The prize asks for ten letters within 4 cm², so the middle wraps are the compromise.'),
    ]),
    ('Keeping track', [
        ('Progress',
         'One strip per scroll along its height, a block per window tried: filled as its surfaces are judged, a teal band once one passed the gate, an amber edge where letters are suspected, hatched where the fit found no winding. The strip shows where the work is — usually, that most of a scroll is untouched.'),
        ('Your records',
         '<code>~</code> is your home folder (<code>C:\\Users\\&lt;you&gt;</code> on Windows). Verdicts: <code>~/.local/share/volumen/my-findings.jsonl</code>. Cut labels: <code>~/.local/share/volumen/cut_labels.jsonl</code>. Those two are worth backing up; everything else (cuts, flattened views, meshes and ink maps in <code>~/.cache/volumen/</code>, exports in <code>~/Volumen exports/</code>) can be made again.'),
    ]),
    ("If you do find letters", [
        ("Before anything else",
         "Ten letters inside a single 4 cm² area of a scroll nobody has read "
         "is the First Letters prize. The rules "
         "matter — among other things, candidates go to the Scroll Prize "
         "team privately before any public post — and they change, so read "
         f"them at the source: {a(PRIZES, 'scrollprize.org/prizes')}. Check "
         "the cut first: a candidate on a crossing surface is not one."),
    ]),
    ("Credits", [
        ("Who made this",
         "By Paulo Sergio Camillo (pscamillo), with Claude. "
         "Code under the MIT licence, at "
         f"{a('https://github.com/pscamillo/volumen', 'github.com/pscamillo/volumen')}. "
         "The surfaces come from "
         f"{a('https://github.com/pscamillo/vesuvius-eligible-meshes', 'vesuvius-eligible-meshes')}; "
         "the scans, lasagna, tracks, ink model, VC3D and the minimal route "
         "with its spiral fitter are the Vesuvius Challenge team's open data "
         f"and code (CC BY-NC 4.0), in {a(VILLA, 'villa')}; the fitter runs "
         "here from the [fork of Iyán Dopico](https://github.com/IyanDopico/villa) (IyanDopico), which carries his "
         "fix. Built on PySide6 (Qt), zarr and numpy. An independent project, "
         "not affiliated with the Scroll Prize."),
    ]),
]


def as_html() -> str:
    css = """<style>
      h1 { color: #e8a33d; font-size: 13px; font-weight: 600;
           letter-spacing: 2px; margin: 34px 0 2px 0; }
      h2 { color: #eee8d8; font-size: 18px; font-weight: 500;
           margin: 18px 0 5px 0; }
      p  { color: #c8c0ac; font-size: 15px; line-height: 145%;
           margin: 0 0 4px 0; }
      a  { color: #e8a33d; text-decoration: none; }
      code { color: #eee8d8; }
    </style>"""
    parts = [css]
    for group, entries in GROUPS:
        parts.append(f"<h1>{group.upper()}</h1>")
        for head, body in entries:
            parts.append(f"<h2>{head}</h2><p>{body}</p>")
    inner = "".join(parts)
    # a centred column by HTML: moving the viewport margins in showEvent
    # recursed through resizeEvent and crashed the app (exit 139)
    return (f'<table width="100%"><tr><td></td><td width="860">{inner}'
            f'</td><td></td></tr></table>')


class HelpPage(QWidget):
    back = Signal()

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 24, 40, 18)
        outer.setSpacing(10)

        top = QHBoxLayout()
        b = QPushButton("← Back")
        b.clicked.connect(self.back)
        top.addWidget(b)
        top.addStretch()
        t = QLabel("How this works")
        t.setObjectName("h1")
        top.addWidget(t)
        top.addStretch()
        top.addSpacing(b.sizeHint().width())
        outer.addLayout(top)

        self.body = QTextBrowser()
        self.body.setOpenLinks(False)
        self.body.anchorClicked.connect(QDesktopServices.openUrl)
        self.body.setHtml(as_html())
        self.body.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }")
        self.body.setTextInteractionFlags(
            Qt.TextSelectableByMouse
            | Qt.LinksAccessibleByMouse)
        outer.addWidget(self.body)

        foot = QLabel("Select any of this and copy it — Ctrl+C works.")
        foot.setObjectName("muted")
        outer.addWidget(foot)
