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


def a(url: str, text: str) -> str:
    return f"<a href='{url}'>{text}</a>"


GROUPS = [
    ("The loop", [
        ("What this is for",
         "Volumen runs one loop: make surfaces from a scroll, check that each "
         "one sits on a single sheet, look for writing on the ones that do, "
         "and keep a record of every judgement. <b>Make surfaces</b>, the "
         "<b>Fibre gate</b>, the surface view with its cuts, and "
         "<b>Progress</b> are its steps. It fits surfaces but never traces or "
         f"edits them by hand — that, and much more, is {a(VC3D, 'VC3D')}, "
         "and any surface here can be exported to it as a ready-made project. "
         "Everything but <i>making</i> surfaces runs on any computer with "
         "Python: the flattened view is made here, from the CT, without "
         "VC3D. Making surfaces is the optional step, and needs the pipeline "
         "described under <i>Make surfaces</i>. "
         "The surfaces already here when the app first opens are the 340 of "
         f"{a('https://github.com/pscamillo/vesuvius-eligible-meshes', 'vesuvius-eligible-meshes')}"
         ", a package published by the author: one per window and wrap on "
         "eight eligible scrolls, made with the same minimal route this app "
         "runs, and fetched on demand as you open them. They are fitted, not "
         "verified — the checks below apply to them as to any other. Surfaces "
         "you make or bring in join them in the same lists."),

        ("Why judge",
         "Judging is how the search narrows. A scroll has hundreds of "
         "surfaces; the ones you have marked as sitting on one sheet with "
         "clean weave are the short list you come back to — to look again at "
         "higher zoom, to run another model on, to export to VC3D. A surface "
         "judged sound with nothing on it is one you will not have to open "
         "again. Verdicts are yours, kept on this machine."),
    ]),

    ("Using the app", [
        ("The scroll grid",
         "One card per eligible scroll, plus PHerc Paris 4 for calibration and, at the end, any scroll withdrawn from the prize, with the reason. "
         "Bright cards have surfaces; the numbers say how many, how many were "
         "judged for ink and how many went through the gate. Dimmed cards "
         "have nothing yet, in two shades: the lighter has lasagna published and only needs the pipeline run; the darker has no lasagna or no tracks yet, and its surfaces come from VC3D."
         " Without the "
         "pipeline on this machine, dimmed cards all say the same thing — "
         "bring your own surface: grow a patch in VC3D and add its "
         "<code>.volpkg</code> in Folders. Click a bright card to open its "
         "surfaces."),

        ("The surface list",
         "One row per surface: window, wrap, area, what the package's own "
         "screen thought of its shape, and your verdict if there is one. "
         "Rest the pointer on a row for a preview of its ink map — a preview "
         "is for choosing what to open, never for judging. Click to open."),

        ("The surface view",
         "The buttons at the top right are the layers: <b>Surface · CT</b>, "
         "the flattened sheet; <b>Ink · forward</b> and <b>Ink · reverse</b>; "
         "and <b>Cut 1–3</b> once cuts exist. Scroll to zoom, drag to move. "
         "The bar at the bottom left is 1 mm and the dashed square is the "
         "size of a letter, both at the current zoom. Three rows record what "
         "you see, in the order to judge them: <i>Surface · CT</i> for the "
         "weave, <i>Sheet · cuts</i> for the cuts, <i>Ink — what do you "
         "see?</i> for the ink. Only the row for the open layer can be "
         "judged, and the keys follow the same rule; <i>i</i> over the CT "
         "opens both surface and ink. Amber lines below the picture warn when a verdict does not "
         "rest on what was opened — ink judged without an ink map, say, or "
         "nothing judged at a zoom too low to see a letter. A surface that "
         "came without a flattened view — the published package is meshes "
         "only — shows an amber <b>Make flattened view</b> button. It reads "
         "the CT along the mesh the way vc_render_tifxyz would, with the "
         "same rules, and needs no VC3D: about half a minute for a package "
         "surface, two minutes for a large one."),

        ("Cuts and their labels",
         "<b>Make cut</b> appears on surfaces that have none and takes about "
         "fifteen seconds. While a cut is open, a row lets you label it — "
         "<i>follows one sheet</i>, <i>crosses sheets</i>, <i>can't tell</i> "
         "— with an optional note on what you saw."),

        ("Open in VC3D",
         "Builds a project folder for VC3D in <code>~/Volumen exports/</code> "
         "and shows the steps left: in VC3D, <i>Open Project</i>, press "
         "Ctrl+L in the file dialog and paste the folder path, accept the "
         "conversion, attach the volume URL, and pick both in the Volume "
         "Package panel. The window has buttons to copy the path and the "
         "URL."),

        ("Make surfaces",
         "Pick a scroll and how many windows, then <b>Start</b>. "
         "<b>Show log</b> follows it live. Only one run at a time: "
         "two on one GPU would fight for memory "
         "and could pick the same window. New surfaces join the catalogue "
         "when the run ends; nothing needs restarting. Without a pipeline on "
         "this machine the screen lists what one needs — the villa checkout "
         "with its spiral environment (Linux or WSL with an NVIDIA GPU), "
         "vc_render_tifxyz from a VC3D release, the ink-detection checkout "
         "and per-scroll inputs. <b>Set up the pipeline…</b> checks this "
         "machine, shows what it would download, and installs only after "
         "you say yes; <b>Prepare another scroll…</b> then fetches each "
         "scroll's inputs, and ends by showing the scroll's axis on three "
         "slices: accept it only if it sits in the middle of the rings on all "
         "three, or give your own umbilicus file."),

        ("The fibre gate",
         "The queue of panels the pipeline made, one at a time. Judge with "
         "the four buttons and the next one comes up; <i>skip</i> leaves it "
         "for later. The table beside each panel is what the pipeline "
         "measured on that surface, direction in the team's terms. Empty "
         "without the pipeline: the panels come from its runs."),

        ("Folders",
         "Where material on this machine lives. The published package comes "
         "over the network on its own; add folders for local surfaces, ink "
         "maps, or the pipeline's working folder, which is recognised and "
         "read as it is. A VC3D <code>.volpkg</code> is read too: every patch "
         "under its <code>paths/</code> shows up, named by its uuid, with the "
         "window taken from its bounding box, and gets a flattened view and "
         "cuts like any other surface."),

        ("Keys",
         "In the surface view: "
         "<b>1 2 3 4</b> ink verdict, <b>z x c v</b> surface verdict "
         "(good, partial, poor, unreadable), <b>Tab</b> next layer and "
         "<b>Shift+Tab</b> the previous one, <b>i</b> ink over the CT in "
         "amber, <b>o</b> fit or one pixel per voxel, <b>e</b> the scale "
         "bar, <b>+ −</b> zoom, <b>Enter</b> or <b>s</b> the next surface, "
         "<b>b</b> the previous one, <b>Esc</b> back to the list. In the "
         "fibre gate: <b>z x c v</b> judge and move on, <b>s</b> skip, "
         "<b>b</b> back. While a text field has the cursor, letters go to "
         "the field."),
    ]),

    ("Making surfaces", [
        ("Getting a flat sheet out of a rolled scroll",
         "The CT scan is a block of voxels; the writing is on a sheet wound "
         "hundreds of times inside it. A fitter takes an ideal spiral and "
         "deforms it until it matches the real, crushed scroll, and then one "
         "winding at a time is flattened into a page. The team calls the "
         "smallest useful set of inputs for this the <i>minimal route</i>; "
         f"the code is in {a(VILLA, 'villa')}."),

        ("What the fitter needs",
         "<b>Tracks</b>, which say where sheet material is. An axis through "
         "the middle of the scroll, the <i>umbilicus</i>. And volumes saying "
         "which way each sheet faces at every point — nicknamed "
         f"{a(LASAGNA, 'lasagna')}, published for some of the eligible "
         "scrolls, not all."),

        ("Scrolls without lasagna",
         "Lasagna is published for some of the eligible scrolls, not all, and "
         "new ones appear from time to time; <b>Make surfaces</b> checks once "
         "a day and says when a scroll gains one. For a scroll without it, "
         "grow a patch in VC3D, the team's own tool, and add its .volpkg in "
         "<b>Folders</b>: the app reads it like any other surface — flattened "
         "view, cuts, gate and verdicts. An earlier experiment here fitted "
         "surfaces without lasagna, from the raw CT; it was left out after it "
         "crossed sheets on one scroll and put the axis on the edge of "
         "another."),

        ("Stopping without breaking anything",
         "The pipeline decides a window is finished from what is on disk, so "
         "cutting it off mid-window would leave a half-made one that looks "
         "done. <b>Stop</b> lets the current window finish and starts no "
         "other. Only a second click, <b>Stop now</b>, kills it — and the "
         "half-made window is moved aside to <code>_interrupted/</code>, "
         "not deleted, and redone next time."),

        ("Windows with no winding",
         "When the fit finds no winding, the window is marked as tried. Most sit "
         "at the top and bottom of a scroll, where the geometry runs out. "
         "Progress draws them hatched, so a gap on a strip reads as <i>never "
         "tried</i> and hatching as <i>tried, no winding</i> — one asks for "
         "the pipeline, the other says not to insist."),
    ]),

    ("Checking the surface", [
        ("A surface, step by step",
         "Open it and look at the flattened CT first, not the ink. "
         "<b>1. Surface.</b> Can you follow fibres across it — horizontals "
         "crossing verticals, the weave of a sheet? Clean weave is "
         "<i>good</i>; weave in parts is <i>partial</i>; swirls, blocks or "
         "diagonal fibre is <i>poor</i>; nothing readable is "
         "<i>unreadable</i>. <b>2. Sheet.</b> Make the cuts and open each. "
         "The amber line is the surface; the grey layers are the sheets of "
         "the scroll, stacked. On one sheet, the line runs along one layer "
         "and bends with it. Where the line bends and the layers around it "
         "do not — a V across a straight stack — or where it slides from one "
         "layer to the next, the surface has crossed to a neighbouring sheet, "
         "and any ink there may belong to that sheet: <i>crosses sheets</i>. "
         "Mark <i>can't tell</i> when the layers themselves are too crushed "
         "to follow. <b>3. Ink</b>, last, and only on surfaces that passed "
         "the first two: zoom until the dashed square is large, and look for "
         "organisation — marks in rows, at regular spacing, letter-sized — "
         "not for sharp strokes. Most maps at 9 µm will show nothing; "
         "<i>nothing but texture</i> is a real answer."),

        ("The fibre gate",
         "Before ink, the question is whether the surface sits on papyrus at "
         "all. The gate shows each flattened panel next to one from PHerc1667 "
         "w013, a scroll that has been read. Can you follow horizontal fibres "
         "across the page, with weave — horizontals crossing verticals? "
         "Closed swirls, wavy lines, rectangular blocks or fibre running "
         "diagonally mean it is not on a sheet. The pipeline's measurements "
         "sit beside each panel."),

        ("The failure to watch for",
         "Every unwrapping method has the same worst failure: the surface "
         "crosses from one winding to the next, and ink showing there may "
         "belong to the neighbouring sheet. The usual checks miss it — a "
         "surface that jumps to its neighbour is still inside the scroll, so "
         "the check for leaving the scroll reads clean. It has been seen here, on a surface of 0125 on 21/09."
         ""),

        ("Reading a cut",
         "A cut is one slice of the raw CT with the mesh drawn across it in "
         "amber. A surface on one sheet runs along the layering, and where it "
         "bends, the layers around it bend too. <b>When the line bends and "
         "the layers around it do not</b> — a V where the stack runs straight "
         "— the surface is crossing. That test came from the 0125 case, and "
         "it is the most useful one so far. Marking a surface as having "
         "shapes of letters makes the app cut it on its own."),

        ("Labelling a cut",
         "Open the cut and zoom until the grey layers are separate lines. "
         "Then follow the amber line from one end to the other, asking three "
         "things. Does it sit on a layer — a bright band of papyrus — rather "
         "than in the dark gap between two? Does it stay on the same layer "
         "all the way? A quick test is to count the layers between the line "
         "and a landmark — the edge of the scroll, a gap, a thick band — near "
         "each end; if the count changes, the line has moved. And where it "
         "bends, do the layers bend with it? A line that bends while the "
         "stack runs straight has left its sheet. <b>Follows one sheet</b> "
         "only if all three hold along the whole line. If the line leaves "
         "its layer anywhere, even for a short stretch, the label is "
         "<b>crosses sheets</b> — and say where in the note (right third, at "
         "the fold), because ink away from that stretch may still be sound. "
         "<b>Can't tell</b> is for layers that merge or vanish over much of "
         "the line, so that none can be followed; a doubt about one short "
         "stretch is not can't tell, it is a reason to look closer there. "
         "A cut can show the line twice: on an inner wrap of a crushed "
         "scroll the same winding crosses the slice on its way out and back; "
         "judge each line against its own layer. "
         "Each label is about its own cut: the three cuts cross different "
         "parts of the surface, and a surface can follow in one and cross in "
         "another."),

        ("Why cut labels",
         "Each cut can be labelled: <i>follows one sheet</i>, <i>crosses "
         "sheets</i> or <i>can't tell</i>. The labels are your own record "
         "of which surfaces are sound, cut by cut: a surface with three "
         "cuts that follow one sheet is one you can trust when you go back "
         "to it. <i>Can't tell</i> counts too: it marks where the layers are "
         "too crushed for the test to work, which is worth knowing before "
         "spending time on the ink there."),
    ]),

    ("Reading the ink", [
        ("Calibrating the eye",
         "PHerc Paris 4 has been read. Open it before working through a "
         "scroll nobody has, and again when a long session starts to blur. "
         "But it is a 2.4 µm scan; writing at 8.6 or 9.4 µm looks far "
         "blurrier. What separates writing from noise at those resolutions "
         "is <b>organisation</b> — marks lined up in rows, at a regular "
         "spacing, about the size of the dashed square — not sharpness."),

        ("Reading a map without fooling yourself",
         "A flat-looking map at low zoom is not evidence of absence. That "
         "mistake has been made here more than once — a map read as noise "
         "turned out to have strokes following a human annotation once it was "
         "looked at properly. Zoom in until the dashed square is large on "
         "screen; the app warns when it is not."),

        ("The two directions",
         "The model reads the sheet from one side and then the other. Real "
         "writing sits on one face, so it tends to answer strongly in one "
         "direction and weakly in the other; a mark that looks the same both "
         "ways is more likely to be in the papyrus than on it. "
         "<i>Forward</i> and <i>reverse</i> are the team's directions, and "
         "mean the same thing everywhere in the app."),

        ("The model's resolution",
         "The ink model was trained at 9.362 µm. On scrolls scanned at 8.64 "
         "µm it is 8% off, so its answer there is approximate — good for "
         "choosing where to look, not for deciding what is there."),

        ("What the wrap number means",
         "Each surface is one winding, counted outward from the middle: w020 "
         "is close to the axis, w100 far out. Inner windings hold up better "
         "— across eight scrolls, 83% of w020 surfaces looked clean against "
         "33% at w100 — but are smaller, from about 2 cm² at w020 to 8–10 cm² "
         "at w100. The prize asks for ten letters inside a single 4 cm² area, "
         "so the middle wraps are the compromise."),
    ]),

    ("Keeping track", [
        ("Progress",
         "One strip per scroll along its height, every window the pipeline "
         "tried as a block on it: filled as its surfaces are judged, a teal "
         "band once something went through the gate, an amber edge if "
         "letters are suspected, hatched where the fit found no winding. "
         "Counting surfaces says how "
         "much was done; the strip says <i>where</i> — and usually that most "
         "of a scroll is still untouched."),
    ]),

    ("Where things are kept", [
        ("Your records",
         "Verdicts, surface and gate judgements: "
         "<code>~/.local/share/volumen/my-findings.jsonl</code>, one line each, "
         "the last one for a surface wins. Cuts: "
         "<code>~/.cache/volumen/cuts/</code>. Cut labels: "
         "<code>~/.local/share/volumen/cut_labels.jsonl</code>. "
         "Folder settings: <code>~/.config/volumen/folders.json</code>. "
         "Exports for VC3D: <code>~/Volumen exports/</code>. Flattened views "
         "made here, downloaded meshes and ink maps: "
         "<code>~/.cache/volumen/</code>. The first and the third are the "
         "ones worth backing up — everything else can be made again."),
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
         "Designed and directed by Paulo Sergio Camillo (pscamillo); "
         "implemented with Claude. Code under the MIT licence, at "
         f"{a('https://github.com/pscamillo/volumen', 'github.com/pscamillo/volumen')}. "
         "The surfaces come from "
         f"{a('https://github.com/pscamillo/vesuvius-eligible-meshes', 'vesuvius-eligible-meshes')}; "
         "the scans, lasagna, tracks and ink model from the Vesuvius "
         "Challenge's open data and code (CC BY-NC 4.0), and the minimal "
         f"route from the team's {a(VILLA, 'villa')}."),
    ]),
]


def as_html() -> str:
    css = """<style>
      h1 { color: #e8a33d; font-size: 13px; font-weight: 600;
           letter-spacing: 2px; margin: 34px 0 2px 0; }
      h2 { color: #eee8d8; font-size: 18px; font-weight: 500;
           margin: 18px 0 5px 0; }
      p  { color: #c8c0ac; font-size: 15px; line-height: 165%;
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
