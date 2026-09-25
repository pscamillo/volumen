#!/usr/bin/env python3
"""
explore.py — looking at one surface.

Takes either a demo view (a published segment of a scroll that has been read)
or a unit from the catalogue, builds the layers it can show, and asks the
person what they see.

WHY THE PERSON STILL HAS TO LOOK. The detector does not decide whether there
is writing. It produces a map, and maps are read wrong at the wrong zoom —
measured on this pipeline: a map that read as noise at low zoom had strokes
following the annotation once the numbers disagreed with the impression. So
the app shows and asks; it never claims.

DIRECTION. No render in this pipeline passes --flip-normals, so the file
named "_reverse" is the team's forward direction. The layer titles say the
real direction, not the file name.

RESOLUTION IS THE STORY. The demo carries an ink map from a 2.4 um scan. The
23 eligible volumes are all 8.6 or 9.4 um, and prize rules forbid using a
finer scan of the scroll you submit. The lesson view exists to make that
visible rather than argued.
"""
from __future__ import annotations

import json
import re
import os
import time
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import (QObject, QRectF, Qt, QThread, QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QImage,
                           QKeySequence, QPainter, QPen, QPixmap, QShortcut)
from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame,
                               QGraphicsOpacityEffect,
                               QGraphicsPixmapItem, QGraphicsScene,
                               QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

import core
import cuts
import flat
import export_vc3d
import sources

S3 = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"

VERDICTS = [
    ("nothing but texture", "Just the weave of the papyrus."),
    ("marks, but no shapes", "Something is there, but nothing letter-like."),
    ("shapes that could be letters", "Worth a second look. No commitment."),
    ("clear letters", "You can read them."),
]
HITS = ("shapes that could be letters", "clear letters")

# cut labels, same format as the ones made by hand on 21/09; the file now
# lives in the Volumen's data folder (config.py adopts the old one once)
import config  # noqa: E402
CUT_LABELS_PATH = config.CUT_LABELS
CUT_LABELS = [
    ("follows one sheet", "segue",
     "The line runs along the layering, and where it bends the layers "
     "around it bend too."),
    ("crosses sheets", "atravessa",
     "The line cuts across the layering, or bends where the layers around "
     "it do not."),
    ("can't tell", "incerto",
     "Too crumpled or too blurred to decide. Worth recording: it shows "
     "where the visual criterion stops working."),
]

# The surface axis, back from the triage tool. It answers a different
# question from the ink axis and the two are easy to confuse: a poor surface
# with a strong ink answer is probably bleed from the neighbouring sheet,
# and with one axis there is nowhere to record that. The 84 verdicts
# inherited from the package's own screen also only exist because the axes
# are separate.
SURFACES = [
    ("good", "Weave across the whole panel."),
    ("partial", "Weave in places, melted in others."),
    ("poor", "Little or no weave."),
    ("unreadable", "Nothing to judge."),
]


@dataclass
class Layer:
    key: str
    title: str
    subtitle: str
    voxel_um: float
    kind: str                 # jpeg | zarr | ink | file
    url: str = ""
    level: int = 0
    stretch: str = "auto"     # auto | raw
    unit: object = None
    direction: str = "forward"


@dataclass
class View:
    key: str                  # what verdicts are filed under
    title: str
    layers: list = field(default_factory=list)
    note: str = ""
    unit: object = None       # the catalogue unit, when there is one


SEG_PARIS4 = "20231005123336"
SEG_0139 = "20260112000000-w043_2026011217"


def demo_view() -> View:
    return View(
        key=f"Paris4/{SEG_PARIS4}",
        title="PHerc Paris 4 · traced October 2023",
        note="This scroll has been read. It is here so you know what "
             "success looks like.",
        layers=[Layer(
            "ink", "Ink · 2.4 µm",
            "This is Greek, and people have read it. The scan behind it is "
            "2.4 µm — finer than anything the 23 eligible scrolls have.",
            2.4, "jpeg", stretch="raw",
            url=f"{S3}/PHercParis4/segments/{SEG_PARIS4}/ink-detection/"
                "downsampled/PHercParis4-20231005123336-2.4um-0.22m-78keV-"
                "volume-20260411134726-20260417190342-"
                "new_canon_autoresearch_recipe-tile256-stride128-ds8.jpg")])


def lesson_view() -> View:
    return View(
        key=f"0139/{SEG_0139}",
        title="PHerc0139 · the same idea, coarser",
        note="Why the other scrolls are hard.",
        layers=[
            Layer("ink", "Ink · 2.399 µm",
                  "A fine scan again. Harder to read than Paris 4, but the "
                  "lines of text are there.",
                  2.399, "jpeg", stretch="raw",
                  url=f"{S3}/PHerc0139/segments/{SEG_0139}/ink-detection/"
                      "downsampled/PHerc0139-20260112000000-2.399um-0.22m-"
                      "78keV-volume-20260102150214-20260417190342-"
                      "new_canon_autoresearch_recipe-tile256-stride128-"
                      "ds8.jpg"),
            Layer("surface", "Surface · 9.362 µm",
                  "The same sheet at the resolution every eligible scroll "
                  "actually has. This is the real problem.",
                  9.362, "zarr", level=3,
                  url=f"{S3}/PHerc0139/segments/{SEG_0139}/surface-volumes/"
                      "9.362um-1.2m-113keV-volume-20250728140407.zarr")])


def unit_view(u) -> View:
    """One surface: the flattened CT, the two ink directions, the cuts."""
    # a scroll outside the prize set has no known voxel size; 0 tells the
    # view to draw no scale bar rather than invent a number
    um = u.scale_um or 0.0
    layers = []
    mid = getattr(u, "mid", None)
    if mid:
        layers.append(Layer("mid", "Surface · CT",
                            "The flattened sheet as the CT sees it. Weave "
                            "means the surface is sitting on a sheet; this "
                            "is what the fibre gate judges.",
                            um, "file", url=mid))
    ausentes = ExplorePage.missing_ink()
    if u.ink_forward and f"{u.id}/ink_fwd" not in ausentes:
        layers.append(Layer("ink_fwd", "Ink · forward",
                            "The ink model's answer for this surface.",
                            um, "ink", unit=u, direction="forward",
                            stretch="raw"))
    if u.ink_reverse and f"{u.id}/ink_rev" not in ausentes:
        layers.append(Layer("ink_rev", "Ink · reverse",
                            "The same surface read from the other side. "
                            "Real writing tends to favour one direction.",
                            um, "ink", unit=u, direction="reverse",
                            stretch="raw"))
    # cross-sections, when they have been generated for this unit
    import glob as _g
    for i, c in enumerate(sorted(_g.glob(os.path.expanduser(
            f"~/.cache/volumen/cortes/"
            f"{u.scroll}_z{u.window}_{u.wrap}_*.png"))), 1):
        layers.append(Layer(f"cut{i}", f"Cut {i}",
                            "A slice of the raw CT with the mesh drawn on "
                            "it. A line running along the layering is a "
                            "surface sitting on a sheet; a line cutting "
                            "across it is crossing between sheets.",
                            um, "file", url=c))

    note = []
    if not u.scale_um:
        note.append("Volumen does not know the voxel size of this scroll, "
                    "so there is no scale bar and no letter-size box.")
    if u.screened:
        note.append(f"The package screen called the sheet shape "
                    f"{u.screened} — that is about the surface, not ink.")
    if u.area_cm2:
        note.append(f"{u.area_cm2:.2f} cm²; the prize asks for ten letters "
                    f"inside 4 cm².")
    if u.origin == "produced":
        note.append("Made on this machine with lasagna, not from the "
                    "published package.")
    title = u.id.replace("/", " · ")
    return View(key=u.id, title=title,
                layers=layers, note="  ".join(note), unit=u)


# ---------------------------------------------------------------- loader --
class LoadSignals(QObject):
    done = Signal(str, object, float)
    failed = Signal(str, str)
    note = Signal(str)
    step = Signal(int, int)


class Loader(QThread):
    def __init__(self, layer: Layer, cache: core.Cache, key: str = ""):
        super().__init__()
        self.layer = layer
        self.cache = cache
        self.key = key.replace("/", "_")
        self.sig = LoadSignals()

    def run(self):
        L = self.layer
        try:
            if L.kind == "jpeg":
                self.sig.note.emit("Downloading…")
                arr = self._jpeg(L)
            elif L.kind == "ink":
                self.sig.note.emit("Fetching the ink map…")
                arr = self._ink(L)
            elif L.kind == "file":
                arr = (self._png(L.url) if L.url.lower().endswith(".png")
                       else self._tif(L.url))
            else:
                self.sig.note.emit("Opening the CT of the sheet…")
                arr = self._zarr(L)
            self.sig.done.emit(L.key, arr, L.voxel_um)
        except Exception as e:  # noqa: BLE001
            self.sig.failed.emit(L.key, f"{type(e).__name__}: {e}")

    def _jpeg(self, L: Layer) -> np.ndarray:
        import urllib.request
        from PIL import Image
        # the cache name carries the view key: two demos with the same layer
        # name used to read each other's file
        path = self.cache.path("demo", f"{self.key}_{L.key}.jpg")
        if not os.path.isfile(path):
            with urllib.request.urlopen(L.url, timeout=180) as r, \
                    open(path, "wb") as f:
                f.write(r.read())
        return np.asarray(Image.open(path).convert("L"))

    def _ink(self, L: Layer) -> np.ndarray:
        p = sources.fetch_ink(L.unit, self.cache, L.direction,
                              lambda g, t: self.sig.step.emit(g, t))
        if not p:
            raise RuntimeError("no ink map published for this surface")
        return self._tif(p)

    @staticmethod
    def _tif(path: str) -> np.ndarray:
        import tifffile
        a = tifffile.imread(path)
        if a.ndim == 3:
            a = a[a.shape[0] // 2]
        a = a.astype(np.float32)
        if a.size and float(a.max()) <= 1.5:   # probability, not 0..255
            a *= 255.0
        return a

    @staticmethod
    def _png(path: str) -> np.ndarray:
        """The cuts are PNG with the mesh drawn in colour: keep the colour,
        or the line that is the whole point of the cut disappears."""
        from PIL import Image
        return np.asarray(Image.open(path).convert("RGB"))

    def _zarr(self, L: Layer) -> np.ndarray:
        import zarr
        z = zarr.open(core.http_url(f"{L.url}/{L.level}"), mode="r")
        return np.asarray(z[z.shape[0] // 2]).astype(np.float32)


# ------------------------------------------------------------------ view --
class SheetView(QGraphicsView):
    zoomed = Signal(float)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.scene().addItem(self.item)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(QColor("#0e0d09"))
        self.voxel_um = 9.362
        self.show_scale = True
        self._fit_pending = True

    def set_image(self, arr, voxel_um: float, mode: str = "auto") -> None:
        if arr is None:
            self.item.setPixmap(QPixmap())
            self.voxel_um = voxel_um
            return
        if arr.ndim == 3:
            # colour image (a cut): show as is, no contrast stretch
            g = np.ascontiguousarray(arr[..., :3], dtype=np.uint8)
            h, w = g.shape[:2]
            img = QImage(g.tobytes(), w, h, 3 * w,
                         QImage.Format_RGB888).copy()
        else:
            g = (np.clip(arr, 0, 255).astype(np.uint8) if mode == "raw"
                 else core.stretch(arr))
            h, w = g.shape
            img = QImage(g.tobytes(), w, h, w,
                         QImage.Format_Grayscale8).copy()
        self.item.setPixmap(QPixmap.fromImage(img))
        self.scene().setSceneRect(QRectF(0, 0, w, h))
        self.voxel_um = voxel_um
        self.resetTransform()
        self._fit_pending = True
        self.fitInView(self.item, Qt.KeepAspectRatio)
        self.zoomed.emit(self.zoom)
        self.set_overlay(None)
        self.viewport().update()

    @property
    def zoom(self) -> float:
        return float(self.transform().m11())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # the first fit happens before the widget has its real size
        if self._fit_pending and not self.item.pixmap().isNull():
            self.fitInView(self.item, Qt.KeepAspectRatio)
            self.zoomed.emit(self.zoom)

    def mousePressEvent(self, e):
        self._fit_pending = False
        super().mousePressEvent(e)

    def wheelEvent(self, e):
        self._fit_pending = False
        f = 1.18 if e.angleDelta().y() > 0 else 1 / 1.18
        if 0.02 < self.zoom * f < 40:
            self.scale(f, f)
            self.zoomed.emit(self.zoom)
        self.viewport().update()

    def zoom_by(self, f: float) -> None:
        self._fit_pending = False
        if 0.02 < self.zoom * f < 40:
            self.scale(f, f)
            self.zoomed.emit(self.zoom)
        self.viewport().update()

    def toggle_one_to_one(self) -> None:
        """The triage tool's o: fit the window, or one pixel per voxel."""
        if self.item.pixmap().isNull():
            return
        self._fit_pending = False
        if abs(self.zoom - 1.0) < 1e-3:
            self.fitInView(self.item, Qt.KeepAspectRatio)
        else:
            self.resetTransform()
        self.zoomed.emit(self.zoom)
        self.viewport().update()

    def set_overlay(self, arr, mask=None) -> None:
        """Ink in amber over the CT. Only what is above the map's median gets
        colour, rising to full at the 99th percentile: ink maps are mid-grey
        in the background, and painting by raw value turned everything
        orange."""
        over = getattr(self, "over", None)
        if arr is None:
            if over is not None:
                over.setVisible(False)
            return
        base = self.item.pixmap()
        if base.isNull():
            return
        a = np.asarray(arr, dtype=np.float32)
        if a.ndim == 3:
            a = a[..., 0]
        v = a[a > 0]
        if v.size == 0:
            return
        lo, hi = np.percentile(v, 50), np.percentile(v, 99)
        t = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)
        # only where the CT exists: the ink map has values at the edges of
        # its inference tiles, over air, and those were painted amber too
        if mask is not None:
            m = np.asarray(mask)
            if m.ndim == 3:
                m = m[..., 0]
            if m.shape != t.shape:
                ri = np.linspace(0, m.shape[0] - 1, t.shape[0]).astype(int)
                ci = np.linspace(0, m.shape[1] - 1, t.shape[1]).astype(int)
                m = m[ri][:, ci]
            t = t * (m > 0)
        h, w = a.shape
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = 232, 163, 61
        rgba[..., 3] = (t * 210).astype(np.uint8)
        img = QImage(rgba.tobytes(), w, h, 4 * w,
                     QImage.Format_RGBA8888).copy()
        pm = QPixmap.fromImage(img)
        if (pm.width(), pm.height()) != (base.width(), base.height()):
            pm = pm.scaled(base.width(), base.height(),
                           Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if over is None:
            over = QGraphicsPixmapItem()
            over.setZValue(1)
            self.scene().addItem(over)
            self.over = over
        over.setPixmap(pm)
        over.setVisible(True)
        self.viewport().update()

    def drawForeground(self, p: QPainter, _rect):
        if not self.show_scale or self.item.pixmap().isNull():
            return
        p.resetTransform()
        vw, vh = self.viewport().width(), self.viewport().height()
        if not self.voxel_um:
            return
        px_mm = core.mm_bar_pixels(self.voxel_um, self.zoom)
        if 12 < px_mm < vw * 0.85:
            x0, y0 = 26, vh - 42
            p.setBrush(QColor(0, 0, 0, 150))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(x0 - 12, y0 - 24, px_mm + 96, 40, 8, 8)
            p.setPen(QPen(QColor("#f3ead6"), 2.5))
            p.drawLine(int(x0), int(y0), int(x0 + px_mm), int(y0))
            for x in (x0, x0 + px_mm):
                p.drawLine(int(x), int(y0 - 6), int(x), int(y0 + 6))
            p.setFont(QFont("", 10))
            p.drawText(int(x0 + px_mm + 10), int(y0 + 4), "1 mm")

        box = core.letter_box_pixels(self.voxel_um, self.zoom)
        if 10 < box < min(vw, vh) * 0.55:
            p.setPen(QPen(QColor("#e8a33d"), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            texto = "a typical letter"
            p.setFont(QFont("", 10))
            larg = p.fontMetrics().horizontalAdvance(texto)
            # a legenda comeca na esquerda da caixa e e mais larga que ela
            # quando a letra e pequena: a margem tem de caber as duas
            bx = vw - max(box, larg) - 34
            by = vh - box - 34
            p.setPen(QPen(QColor("#e8a33d"), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(int(bx), int(by), int(box), int(box))
            p.setPen(QColor("#e8a33d"))
            p.drawText(int(bx), int(by - 8), texto)


# ------------------------------------------------------------ the screen --
class ExplorePage(QWidget):
    back = Signal()
    lesson = Signal()
    step_asked = Signal(int)          # next or previous surface in the list

    def __init__(self, cache: core.Cache | None = None):
        super().__init__()
        self.cache = cache or core.Cache()
        self.view_data = None
        self.arrays = {}
        self.loaders = {}
        self.current = ""
        self.sel = None
        self.sel_surface = None
        self.seen_layers = set()
        self.layer_group = QButtonGroup(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(22, 14, 22, 10)
        b = QPushButton("← Back")
        b.clicked.connect(self.back)
        bar.addWidget(b)
        bar.addSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("h2")
        bar.addWidget(self.title)
        bar.addStretch()
        self.layer_bar = QHBoxLayout()
        bar.addLayout(self.layer_bar)
        lay.addLayout(bar)

        self.caption = QLabel()
        self.caption.setObjectName("muted")
        self.caption.setWordWrap(True)
        self.caption.setContentsMargins(22, 0, 22, 8)
        lay.addWidget(self.caption)

        self.view = SheetView()
        lay.addWidget(self.view, 1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        lay.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setContentsMargins(22, 8, 22, 0)
        lay.addWidget(self.status)

        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setContentsMargins(22, 4, 22, 0)
        self.warn.setStyleSheet("color: #e8a33d;")
        lay.addWidget(self.warn)

        hint = QLabel("Scroll wheel to zoom · drag to move · the dashed "
                      "square is the size of a letter · a cut shows whether "
                      "the surface stays on one sheet")
        hint.setObjectName("muted")
        hint.setContentsMargins(22, 4, 22, 0)
        lay.addWidget(hint)
        keys = QLabel("Keys:  1–4 ink  ·  z x c v surface  ·  Tab layer  ·  "
                      "i ink over the CT  ·  o fit / 1:1  ·  e scale  ·  "
                      "+ − zoom  ·  Enter next  ·  b previous  ·  Esc list")
        keys.setObjectName("muted")
        keys.setContentsMargins(22, 2, 22, 0)
        lay.addWidget(keys)

        # cut labels: only shown while a cut is the open layer
        self.cut_row = QWidget()
        cr = QHBoxLayout(self.cut_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(10)
        cl = QLabel("This cut:")
        cl.setObjectName("muted")
        cr.addWidget(cl)
        self.cut_group = QButtonGroup(self)
        self.cut_buttons = {}
        for label, code, tip in CUT_LABELS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, c=code: self.record_cut_label(c))
            self.cut_group.addButton(b)
            self.cut_buttons[code] = b
            cr.addWidget(b)
        self.cut_note = QLineEdit()
        self.cut_note.setPlaceholderText("what you saw (optional)")
        cr.addWidget(self.cut_note, 1)
        self.cut_others = QLabel("")
        self.cut_others.setStyleSheet("color:#e8a33d")
        self.cut_count = QLabel("")   # kept for update_cut_row, not shown
        self.cut_row.setVisible(False)

        ask = QVBoxLayout()
        ask.setContentsMargins(22, 6, 22, 16)
        ask.setSpacing(8)
        q = QLabel("Ink — what do you see?")
        q.setObjectName("h2")
        # placed at the end of this block, not here: How this works teaches
        # surface (CT), sheet (cuts), ink last (25/09)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.verdict_group = QButtonGroup(self)
        self.verdict_buttons = {}
        for name, hint in VERDICTS:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setToolTip(hint)
            btn.clicked.connect(lambda _=False, n=name: self.record(n))
            self.verdict_group.addButton(btn)
            self.verdict_buttons[name] = btn
            row.addWidget(btn)
        row.addStretch()
        self._ink_q, self._ink_row = q, row

        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel("Surface · CT:")
        self._surf_lbl = lbl
        lbl.setObjectName("muted")
        row.addWidget(lbl)
        self.surface_group = QButtonGroup(self)
        self.surface_buttons = {}
        for name, hint in SURFACES:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setToolTip(hint)
            btn.clicked.connect(
                lambda _=False, n=name: self.record_surface(n))
            self.surface_group.addButton(btn)
            self.surface_buttons[name] = btn
            row.addWidget(btn)
        row.addStretch()
        self.why = QPushButton("Why can't we do this on the other scrolls?")
        self.why.clicked.connect(self.lesson)
        row.addWidget(self.why)
        self.to_vc3d = QPushButton("Open in VC3D")
        self.to_vc3d.clicked.connect(self.export_vc3d)
        row.addWidget(self.to_vc3d)
        self.cut_btn = QPushButton("Make cut")
        self.cut_btn.setToolTip(
            "A slice of the raw CT with the mesh drawn on it: does the "
            "surface follow one sheet, or cross between sheets?")
        self.cut_btn.clicked.connect(lambda: self.make_cut(auto=False))
        row.addWidget(self.cut_btn)
        self.flat_btn = QPushButton("Make flattened view")
        self.flat_btn.setToolTip(
            "Read the CT along this mesh and flatten it, the way "
            "vc_render_tifxyz would. A few minutes; no VC3D needed.")
        self.flat_btn.clicked.connect(self.make_flat)
        row.addWidget(self.flat_btn)
        self.flatter = None
        # it appears only while there is no flattened view, and stops the
        # moment it is pressed: a slow pulse says "this is what is missing"
        self._flat_fx = QGraphicsOpacityEffect(self.flat_btn)
        self.flat_btn.setGraphicsEffect(self._flat_fx)
        self._flat_anim = QPropertyAnimation(self._flat_fx, b"opacity", self)
        self._flat_anim.setDuration(1100)
        self._flat_anim.setStartValue(1.0)
        self._flat_anim.setEndValue(0.45)
        self._flat_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._flat_anim.setLoopCount(-1)
        self.cutter = None
        row.addSpacing(16)
        self.counter = QLabel("")
        self.counter.setObjectName("muted")
        row.addWidget(self.counter)
        ask.addLayout(row)

        # third axis: does the surface stay on one sheet? The label itself
        # is made on the cut (cut_row); this row is where it becomes part
        # of the verdict instead of an optional extra.
        self.sheet_row = QWidget()
        row = QHBoxLayout(self.sheet_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        lbl = QLabel("Sheet · cuts:")
        lbl.setObjectName("muted")
        row.addWidget(lbl)
        self.sheet_marks = []
        for n in (1, 2, 3):
            b = QPushButton(f"c{n} —")
            b.setFlat(True)
            b.setToolTip(f"Open cut {n} and label it there")
            b.clicked.connect(lambda _=False, k=n: self.show_layer(f"cut{k}"))
            self.sheet_marks.append(b)
            row.addWidget(b)
        self.sheet_summary = QLabel("")
        self.sheet_summary.setStyleSheet("color:#e8a33d")
        row.addWidget(self.sheet_summary)
        row.addStretch()
        ask.addWidget(self.sheet_row)
        ask.addWidget(self.cut_row)
        linha = QWidget()
        lo = QHBoxLayout(linha)
        lo.setContentsMargins(22, 0, 22, 0)
        recuo = QLabel("")
        recuo.setObjectName("muted")
        recuo.setFixedWidth(self.cut_row.findChild(QLabel).sizeHint().width() + 10)
        lo.addWidget(recuo)
        lo.addWidget(self.cut_others)
        lo.addStretch()
        self.cut_others_row = linha
        ask.addWidget(linha)

        ask.addSpacing(6)
        ask.addWidget(self._ink_q)
        ask.addLayout(self._ink_row)
        lay.addLayout(ask)
        self._overlay_on = False
        self._keys()

    # -- what to show --------------------------------------------------
    # -- keys: the triage tool's, so the hand that learned them keeps them
    def _keys(self) -> None:
        m = {
            "1": lambda: self._verdict(0), "2": lambda: self._verdict(1),
            "3": lambda: self._verdict(2), "4": lambda: self._verdict(3),
            "Z": lambda: self._surface(0), "X": lambda: self._surface(1),
            "C": lambda: self._surface(2), "V": lambda: self._surface(3),
            "Tab": lambda: self._cycle(+1),
            "Shift+Tab": lambda: self._cycle(-1),
            "I": self.toggle_overlay,
            "O": self.view.toggle_one_to_one,
            "E": self.toggle_scale,
            "+": lambda: self.view.zoom_by(1.18),
            "=": lambda: self.view.zoom_by(1.18),
            "-": lambda: self.view.zoom_by(1 / 1.18),
            "Return": lambda: self.step_asked.emit(1),
            "Enter": lambda: self.step_asked.emit(1),
            "S": lambda: self.step_asked.emit(1),
            "B": lambda: self.step_asked.emit(-1),
            "Escape": self.back.emit,
        }
        self._shortcuts = []
        for seq, fn in m.items():
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WindowShortcut)
            sc.setEnabled(False)
            sc.activated.connect(fn)
            self._shortcuts.append(sc)
        for i, (name, hint) in enumerate(VERDICTS):
            self.verdict_buttons[name].setToolTip(f"{hint}  —  key {i + 1}")
        for (name, hint), k in zip(SURFACES, "zxcv"):
            self.surface_buttons[name].setToolTip(f"{hint}  —  key {k}")

    def showEvent(self, e):
        super().showEvent(e)
        for sc in self._shortcuts:
            sc.setEnabled(True)

    def hideEvent(self, e):
        super().hideEvent(e)
        for sc in self._shortcuts:
            sc.setEnabled(False)

    def _verdict(self, i: int) -> None:
        if self.view_data is not None:
            self.verdict_buttons[VERDICTS[i][0]].click()

    def _surface(self, i: int) -> None:
        if self.view_data is not None:
            self.surface_buttons[SURFACES[i][0]].click()

    def _cycle(self, d: int) -> None:
        v = self.view_data
        if v is None or not v.layers:
            return
        keys = [L.key for L in v.layers]
        i = keys.index(self.current) if self.current in keys else 0
        j = (i + d) % len(keys)
        btns = self.layer_group.buttons()
        if j < len(btns):
            btns[j].click()

    def toggle_scale(self) -> None:
        self.view.show_scale = not self.view.show_scale
        self.view.viewport().update()

    def toggle_overlay(self) -> None:
        self._overlay_on = not self._overlay_on
        self._gate_rows()
        if not self._overlay_on:
            self.status.setText("")
        if self._overlay_on and self.current != "mid":
            self.status.setText("The ink overlay goes on Surface · CT — Tab "
                                "until it is open.")
        self._sync_overlay()

    def _sync_overlay(self) -> None:
        if not self._overlay_on or self.current != "mid":
            self.view.set_overlay(None)
            return
        for k in ("ink_fwd", "ink_rev"):
            if k in self.arrays:
                mid = self.arrays.get("mid", (None,))[0]
                self.view.set_overlay(self.arrays[k][0], mid)
                self.status.setText(
                    f"{self.layer(k).title} over the CT, in amber: where the "
                    f"model answered most on THIS map — relative, never proof "
                    f"of ink.  i to hide")
                return
        for k in ("ink_fwd", "ink_rev"):
            L = self.layer(k)
            if L is None:
                continue
            if k not in self.loaders:
                ld = Loader(L, self.cache, self.view_data.key)
                ld.sig.done.connect(self.loaded)
                ld.sig.failed.connect(self.failed)
                self.loaders[k] = ld
                ld.start()
            self.status.setText("Loading the ink map for the overlay…")
            return
        self.status.setText("No ink map for this surface to overlay.")

    def show_view(self, v: View) -> None:
        self.view_data = v
        self.arrays = {}
        self.loaders = {}

        while self.layer_bar.count():
            item = self.layer_bar.takeAt(0)
            w = item.widget()
            if w is not None:
                self.layer_group.removeButton(w)
                w.deleteLater()
        for L in v.layers:
            btn = QPushButton(L.title)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=L.key: self.show_layer(k))
            self.layer_group.addButton(btn)
            self.layer_bar.addWidget(btn)
        if v.layers:
            self.layer_group.buttons()[0].setChecked(True)

        self.title.setText(v.title)
        self.why.setVisible(v.key.startswith("Paris4/"))
        self.to_vc3d.setVisible(v.unit is not None)
        u = v.unit
        falta = u is not None and not u.mid and bool(u.mesh_dir or u.mesh_rel)
        # while the flattened view is the thing to do first, the other two
        # stay usable but quiet: both work from the mesh alone
        quieto = ("background: transparent; border: 1px solid #2a2820"
                  if falta else "")
        self.cut_btn.setStyleSheet(quieto)
        self.to_vc3d.setStyleSheet(quieto)
        self.flat_btn.setVisible(falta)
        self.flat_btn.setStyleSheet(
            "background:#e8a33d; color:#16150f; font-weight:600" if falta
            else "")
        if falta:
            self._flat_anim.start()
        else:
            self._flat_anim.stop()
            self._flat_fx.setOpacity(1.0)
        self.cut_btn.setVisible(v.unit is not None
                                and not cuts.existing(v.unit))
        self.cut_btn.setEnabled(self.cutter is None)
        self.warn.setText("")
        prev = self.previous_verdict(v.key)
        self.sel = config.verdict_en(prev.get("verdict"))
        self.sel_surface = prev.get("surface")
        # the same surface shown again (its cuts just made) keeps what was
        # opened; only a new surface starts from nothing (25/09: the ink
        # warning fired on a verdict made with the ink map open)
        if getattr(self, "_seen_key", None) != v.key:
            self.seen_layers = set()
        self._seen_key = v.key
        # an exclusive group will not let every button be unchecked, so the
        # previous unit's verdict stayed stuck without releasing it
        for group, buttons, chosen in (
                (self.verdict_group, self.verdict_buttons, self.sel),
                (self.surface_group, self.surface_buttons, self.sel_surface)):
            group.setExclusive(False)
            for name, btn in buttons.items():
                btn.setChecked(name == chosen)
            group.setExclusive(True)
        self.refresh_counter()
        self.update_sheet_row()
        # with no ink layer there is nothing to judge on the ink axis, and
        # with no flattened view nothing to judge on the surface axis
        tem_tinta = any(L.key.startswith("ink") for L in v.layers)
        tem_sup = any(L.key == "mid" or L.key.startswith("cut")
                      for L in v.layers)
        for b_ in self.verdict_buttons.values():
            b_.setEnabled(tem_tinta)
            b_.setToolTip("" if tem_tinta
                          else "No ink map for this surface")
        for b_ in self.surface_buttons.values():
            b_.setEnabled(tem_sup)
            b_.setToolTip("" if tem_sup
                          else "Make the flattened view first")

        if v.layers:
            self.show_layer(v.layers[0].key)
        else:
            self.status.setText("Nothing published for this surface yet.")

    def layer(self, key: str):
        v = self.view_data
        if v is None:
            return None
        return next((L for L in v.layers if L.key == key), None)

    def _gate_rows(self) -> None:
        """Judge what is open (25/09): the row for the open layer is live;
        the other is shown dimmed and locked, its verdict still visible.
        Surface · CT -> surface; an ink map -> ink; i over the CT -> both;
        a cut -> neither (the cut has its own row)."""
        from PySide6 import QtWidgets as _QtW
        k = self.current or ""
        on_ct, on_cut = k == "mid", k.startswith("cut")
        ink_live = (not on_ct and not on_cut) or (on_ct and self._overlay_on)
        surf_live = on_ct

        def dim(w, live):
            if live:
                w.setGraphicsEffect(None)
            else:
                fx = _QtW.QGraphicsOpacityEffect(w)
                fx.setOpacity(0.35)
                w.setGraphicsEffect(fx)
        for b in self.verdict_buttons.values():
            b.setEnabled(ink_live)
            dim(b, ink_live)
        dim(self._ink_q, ink_live)
        for b in self.surface_buttons.values():
            b.setEnabled(surf_live)
            dim(b, surf_live)
        dim(self._surf_lbl, surf_live)

    def show_layer(self, key: str) -> None:
        L = self.layer(key)
        if L is None:
            return
        self.current = key
        self._gate_rows()
        self.seen_layers.add(L.title)
        keys = [x.key for x in self.view_data.layers]
        btns = self.layer_group.buttons()
        if key in keys and len(btns) > keys.index(key):
            btns[keys.index(key)].setChecked(True)
        self.update_cut_row(key)
        self.update_sheet_row()
        self.caption.setText(f"{L.subtitle}  {self.view_data.note}".strip())
        if key in self.arrays:
            arr, um = self.arrays[key]
            self.view.set_image(arr, um, L.stretch)
            self.status.setText("")
            self.progress.hide()
            self._sync_overlay()
            return
        if key in self.loaders:
            return
        self.progress.setRange(0, 0)
        self.progress.show()
        ld = Loader(L, self.cache, self.view_data.key)
        ld.sig.done.connect(self.loaded)
        ld.sig.failed.connect(self.failed)
        ld.sig.note.connect(self.status.setText)
        ld.sig.step.connect(self.stepped)
        self.loaders[key] = ld
        ld.start()

    def stepped(self, got: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(got)

    def loaded(self, key: str, arr, um: float) -> None:
        self.arrays[key] = (arr, um)
        self.loaders.pop(key, None)
        if key == self.current:
            L = self.layer(key)
            self.view.set_image(arr, um, L.stretch if L else "auto")
            self.status.setText("")
            self.progress.hide()
        # an ink map loaded in the background may be waiting to be overlaid
        self._sync_overlay()

    NO_INK = os.path.expanduser("~/.cache/volumen/sem-tinta.txt")

    @classmethod
    def missing_ink(cls) -> set:
        try:
            with open(cls.NO_INK, encoding="utf-8") as f:
                return {ln.strip() for ln in f if ln.strip()}
        except OSError:
            return set()

    def note_missing_ink(self, key: str) -> None:
        v = self.view_data
        if v is None or v.unit is None or not key.startswith("ink"):
            return
        marca = f"{v.unit.id}/{key}"
        if marca in self.missing_ink():
            return
        os.makedirs(os.path.dirname(self.NO_INK), exist_ok=True)
        with open(self.NO_INK, "a", encoding="utf-8") as f:
            f.write(marca + "\n")

    def failed(self, key: str, msg: str) -> None:
        self.loaders.pop(key, None)
        if "no ink map" in msg or "404" in msg or "HTTPError" in msg:
            self.note_missing_ink(key)
        if key == self.current:
            self.progress.hide()
            # clear the view: leaving the previous layer on screen under the
            # new layer's caption is how a CT gets read as an ink map
            self.view.set_image(None, 0.0)
            self.status.setText(f"Could not load this layer — {msg}")

    def export_vc3d(self) -> None:
        """Build the project folder and tell the person what to do next."""
        v = self.view_data
        if v is None or v.unit is None:
            return
        self.status.setText("Preparing the project…")
        try:
            info = export_vc3d.export(v.unit, self.cache)
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"Could not prepare it — {e}")
            return
        self.status.setText("")

        dlg = QDialog(self)
        dlg.setWindowTitle("Open in VC3D")
        dlg.setMinimumWidth(760)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(12)
        lay.setContentsMargins(26, 22, 26, 20)

        head = QLabel(f"<b>{v.title}</b> is ready for VC3D.")
        head.setObjectName("h2")
        lay.addWidget(head)

        for label, value in (("Project folder", info["folder"]),
                             ("Volume to attach", info["volume_url"])):
            lay.addWidget(QLabel(f"<b>{label}</b>"))
            box = QLineEdit(value)
            box.setReadOnly(True)
            box.setCursorPosition(0)
            lay.addWidget(box)

        lay.addSpacing(6)
        for i, (h, body) in enumerate(info["steps"], 1):
            t = QLabel(f"<b>{i}. {h}.</b> {body}")
            t.setWordWrap(True)
            lay.addWidget(t)

        row = QHBoxLayout()
        copy_path = QPushButton("Copy the folder path")
        copy_path.clicked.connect(
            lambda: QApplication.clipboard().setText(info["folder"]))
        row.addWidget(copy_path)
        open_btn = QPushButton("Open the folder")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(info["folder"])))
        row.addWidget(open_btn)
        copy_btn = QPushButton("Copy the volume URL")
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(info["volume_url"]))
        row.addWidget(copy_btn)
        row.addStretch()
        close = QPushButton("Done")
        close.setObjectName("primary")
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        lay.addLayout(row)
        dlg.exec()

    # -- cut labels ------------------------------------------------------
    @staticmethod
    def read_cut_labels() -> dict:
        """Last label per (unit, cut). The file also holds other records,
        such as the outcome of a flag; only those with a label count."""
        out = {}
        if not os.path.isfile(CUT_LABELS_PATH):
            return out
        with open(CUT_LABELS_PATH, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if r.get("unit") and r.get("rotulo"):
                    out[(r["unit"], r.get("onde", ""))] = r
        return out

    def update_cut_row(self, key: str) -> None:
        v = self.view_data
        is_cut = (v is not None and v.unit is not None
                  and key.startswith("cut"))
        self.cut_row.setVisible(is_cut)
        self.cut_others_row.setVisible(is_cut)
        if not is_cut:
            return
        n = key[3:]
        labels = self.read_cut_labels()
        # a label may have been made by hand for the whole unit ("cortes
        # 1-3") rather than for this cut — show it, but as the unit's
        mine = labels.get((v.unit.id, f"corte {n}"))
        if mine is None:
            mine = next((r for (u, _), r in labels.items()
                         if u == v.unit.id), None)
        chosen = mine.get("rotulo") if mine else None
        self.cut_group.setExclusive(False)
        for code, b in self.cut_buttons.items():
            b.setChecked(code == chosen)
        self.cut_group.setExclusive(True)
        self.cut_note.setText(mine.get("criterio", "") if mine else "")
        decided = sum(1 for r in labels.values()
                      if r.get("rotulo") in ("segue", "atravessa"))
        unsure = sum(1 for r in labels.values()
                     if r.get("rotulo") == "incerto")
        outros = []
        for i in (1, 2, 3):
            if self.current == f"cut{i}":
                continue
            r = labels.get((v.unit.id, f"corte {i}"))
            if r is None:
                r = next((x for (u, onde), x in labels.items()
                          if u == v.unit.id and onde.startswith("cortes")), None)
            if r:
                curto = {"segue": "follows", "atravessa": "crosses",
                         "incerto": "can't tell"}.get(r["rotulo"], "—")
                outros.append(f"c{i} {curto}")
        self.cut_others.setText("   ·   ".join(outros))
        self.cut_count.setText(
            f"{decided} decided · {unsure} unsure across all surfaces")

    def update_sheet_row(self) -> None:
        """The three marks: what each cut of this unit says, if anything."""
        v = self.view_data
        if v is None or v.unit is None:
            self.sheet_row.setVisible(False)
            return
        self.sheet_row.setVisible(not self.current.startswith("cut"))
        curto = {"segue": "follows", "atravessa": "crosses",
                 "incerto": "can't tell"}
        labels = self.read_cut_labels()
        meus = {k: r for k, r in labels.items() if k[0] == v.unit.id}
        # o "onde" dos rotulos feitos a mao varia: "corte 2", "corte 2, ramo
        # superior perto do vertice", "cortes 1-3, fatia z5007". Casa pelo
        # numero que aparece no texto, e "cortes 1-3" vale para os tres.
        def para_corte(i):
            alvo = None
            for (_, onde), r in meus.items():
                nums = re.findall(r"\d+", onde)
                if onde.startswith("cortes"):
                    if alvo is None:
                        alvo = r
                elif nums and int(nums[0]) == i:
                    return r
            return alvo
        dito = []
        dito_por_corte = []
        for i, b in enumerate(self.sheet_marks, start=1):
            r = para_corte(i)
            code = r.get("rotulo") if r else None
            b.setText(f"c{i} {curto.get(code, '—')}")
            b.setEnabled(True)
            dito_por_corte.append(code)
            if code:
                dito.append(code)
        if not dito:
            self.sheet_summary.setText("not labelled — open a cut")
        elif "atravessa" in dito:
            quais = ", ".join(f"c{i}" for i, d in enumerate(dito_por_corte, 1)
                              if d == "atravessa")
            self.sheet_summary.setText(f"crosses on {quais}")
        elif all(d == "segue" for d in dito):
            self.sheet_summary.setText(f"follows on {len(dito)} of 3")
        else:
            self.sheet_summary.setText(f"{len(dito)} of 3 labelled")

    def record_cut_label(self, code: str) -> None:
        v = self.view_data
        if v is None or v.unit is None or not self.current.startswith("cut"):
            return
        n = self.current[3:]
        rec = {
            "unit": v.unit.id,
            "rotulo": code,
            "onde": f"corte {n}",
            "criterio": self.cut_note.text().strip(),
            "via": "lasagna",
            "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
            "por": "pscamillo",
            "origem": "volumen",
        }
        os.makedirs(os.path.dirname(CUT_LABELS_PATH), exist_ok=True)
        with open(CUT_LABELS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.update_cut_row(self.current)
        self.update_sheet_row()
        # the "no cut is labelled" warning was written when the verdict was
        # recorded; labelling a cut answers it, so it has to be redone
        self.warn.setText(self.judgement_warnings(self.sel))
        nome = next((lbl for lbl, c, _ in CUT_LABELS if c == code), code)
        self.status.setText(f"Cut {n} labelled: {nome}.")

    def judgement_warnings(self, name) -> str:
        """What the verdict just recorded did not rest on."""
        v = self.view_data
        if v is None:
            return ""
        seen = self.seen_layers
        titles = [L.title for L in v.layers]
        out = []

        # 1. ink judged with no ink map opened
        if (name is not None and any(t.startswith("Ink") for t in titles)
                and not any(t.startswith("Ink") for t in seen)):
            out.append("You judged ink without opening an ink map — that "
                       "verdict is about the CT, not the ink.")

        # 2. surface judged with neither the CT nor a cut opened
        if (name is None and self.sel_surface
                and any(L.key == "mid" or L.key.startswith("cut")
                        for L in v.layers)
                and not any(t == "Surface · CT" or t.startswith("Cut")
                            for t in seen)):
            out.append("You judged the surface without opening the CT view "
                       "or a cut.")

        # 3. judged with no cut labelled at all
        if (v.unit is not None
                and not any(k[0] == v.unit.id
                            for k in self.read_cut_labels())):
            out.append("No cut of this surface is labelled yet — whether it "
                       "stays on one sheet is still open.")

        # 4. "nothing" at a zoom where a letter is a few pixels
        L = self.layer(self.current)
        if (name == "nothing but texture" and L is not None
                and L.voxel_um):
            box = core.letter_box_pixels(L.voxel_um, self.view.zoom)
            if box < 20:
                out.append(f"At this zoom a letter is about {box:.0f} pixels "
                           f"on screen. A flat map at low zoom is not "
                           f"evidence of absence — zoom in before deciding.")
        return "  ".join(out)

    def make_flat(self) -> None:
        v = self.view_data
        if v is None or v.unit is None or self.flatter is not None:
            return
        self.flat_btn.setEnabled(False)
        self.flat_btn.setText("Reading the CT…")
        self._flat_anim.stop()
        self._flat_fx.setOpacity(1.0)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText("Reading the CT along the mesh — a few minutes…")
        self.flatter = flat.FlatWorker(v.unit, self.cache)
        self.flatter.sig.done.connect(self.flat_done)
        self.flatter.sig.failed.connect(self.flat_failed)
        self.flatter.sig.step.connect(self.stepped)
        self.flatter.start()

    def flat_done(self, path: str) -> None:
        self.flatter = None
        self.flat_btn.setText("Make flattened view")
        self.flat_btn.setEnabled(True)
        self.progress.hide()
        u = self.view_data.unit
        u.mid = path
        self.arrays.pop("mid", None)
        self.show_view(unit_view(u))
        self.show_layer("mid")
        self.status.setText("Flattened view made. Does it show fibre weave?")

    def flat_failed(self, msg: str) -> None:
        self.flatter = None
        self.flat_btn.setText("Make flattened view")
        self.flat_btn.setEnabled(True)
        self.progress.hide()
        self.status.setText(f"Could not make the flattened view — {msg}")

    def make_cut(self, auto: bool = False) -> None:
        v = self.view_data
        if v is None or v.unit is None or self.cutter is not None:
            return
        self.cut_btn.setEnabled(False)
        self._cut_busy(True)
        self.status.setText(
            "Letters suspected and no cut yet — making one before you move "
            "on…" if auto else "Making the cut…")
        self.cutter = cuts.CutWorker(v.unit, self.cache)
        self.cutter.sig.step.connect(self.cut_step)
        self.cutter.sig.done.connect(self.cut_done)
        self.cutter.sig.failed.connect(self.cut_failed)
        self.cutter.start()

    def _cut_busy(self, on: bool) -> None:
        """A cut takes about fifteen seconds. The status line alone was too
        quiet: the click looked like it did nothing until the view jumped.
        So the button itself counts, the thin bar under the picture moves,
        and the pointer over the picture waits."""
        if on:
            self.cut_btn.setText("Cutting…")
            self.cut_btn.setStyleSheet("color: #e8a33d; border-color: #e8a33d;")
            self.progress.setRange(0, 3)
            self.progress.setValue(0)
            self.progress.show()
            self.view.viewport().setCursor(Qt.BusyCursor)
        else:
            self.cut_btn.setText("Make cut")
            self.cut_btn.setStyleSheet("")
            self.progress.hide()
            self.view.viewport().setCursor(Qt.OpenHandCursor)

    def cut_step(self, j: int, n: int) -> None:
        self.cut_btn.setText(f"Cutting {j}/{n}…")
        self.progress.setRange(0, n)
        self.progress.setValue(j - 1)
        self.status.setText(f"Cutting window {j} of {n}…")

    def cut_done(self, paths) -> None:
        unit = self.cutter.unit if self.cutter else None
        self.cutter = None
        self._cut_busy(False)
        v = self.view_data
        if unit is None or v is None or v.unit is not unit:
            return                  # moved on to another surface meanwhile
        # rebuild the view so the cuts join the layers, then open the first
        self.show_view(unit_view(unit))
        keys = [L.key for L in self.view_data.layers]
        if "cut1" in keys:
            i = keys.index("cut1")
            self.layer_group.buttons()[i].setChecked(True)
            self.show_layer("cut1")
        self.status.setText(f"{len(paths)} cuts made. Does the line follow "
                            f"one sheet, or cut across the layering?")

    def cut_failed(self, msg: str) -> None:
        self.cutter = None
        self._cut_busy(False)
        self.cut_btn.setEnabled(True)
        self.status.setText(f"Could not make the cut — {msg}")

    # -- verdicts ------------------------------------------------------
    def findings_path(self) -> str:
        return config.FINDINGS

    def previous_verdict(self, key: str) -> dict:
        p = self.findings_path()
        if not os.path.isfile(p):
            return {}
        last = {}
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if r.get("unit") == key:
                    last = r
        return last

    def record_surface(self, name: str) -> None:
        if not next(iter(self.surface_buttons.values())).isEnabled():
            self.status.setText("Open Surface · CT to judge the surface.")
            return
        self.sel_surface = name
        self.record(None)

    def record(self, name) -> None:
        if not next(iter(self.verdict_buttons.values())).isEnabled():
            self.status.setText("Open Ink · forward or reverse (or i over the "
                                "CT) to judge the ink.")
            return
        if self.view_data is None:
            return
        if name is not None:
            self.sel = name
        rec = {
            "unit": self.view_data.key,
            "verdict": self.sel,
            "surface": self.sel_surface,
            "layers_seen": sorted(self.seen_layers),
            "layer": self.current,
            "zoom": round(self.view.zoom, 3),
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        p = self.findings_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.refresh_counter()
        # letters suspected on a surface with no cut: that is exactly when
        # "is this ink from this sheet or the next one?" starts to matter
        u = self.view_data.unit
        if (self.sel in HITS and u is not None and not cuts.existing(u)
                and self.cutter is None):
            self.make_cut(auto=True)
        self.warn.setText(self.judgement_warnings(name))

    def refresh_counter(self) -> None:
        p = self.findings_path()
        seen = {}
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        r = json.loads(ln)
                    except json.JSONDecodeError:
                        continue
                    if r.get("unit"):
                        seen[r["unit"]] = config.verdict_en(r.get("verdict"))
        n = len(seen)
        hits = sum(1 for v in seen.values() if v in HITS)
        self.counter.setText(
            f"{n} surface{'s' if n != 1 else ''} looked at · {hits} with "
            f"shapes" if n else "")
