#!/usr/bin/env python3
"""
folders.py — where this machine keeps its surfaces.

Volumen reads the published package over the network, but anyone who runs
the pipeline themselves has meshes and ink maps on disk, organised their own
way. This screen lets them point at those folders — as many as they like.

The settings live in ~/.config/volumen/folders.json so they survive a cache
wipe, which is not true of anything under ~/.cache.

What a folder may contain, in either shape:

  <folder>/PHerc0800/z5664_w020/{x,y,z}.tif     meshes, package layout
  <folder>/PHerc0800/z5664_w020[_reverse].tif   ink maps, dataset layout

Both are scanned; a folder can hold one, the other, or both.
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout,
                               QWidget)

CONFIG_DIR = os.path.expanduser("~/.config/volumen")
CONFIG_PATH = os.path.join(CONFIG_DIR, "folders.json")

# Folders Volumen looks in by default, if they happen to exist. Someone who
# ran the community pipeline will have these; everyone else will not, and
# nothing breaks either way.
SUGGESTED = [
    "~/challenges/vesuvius/pacote_malhas/meshes",
    "~/challenges/vesuvius/mapas_up",
]


def load() -> list[str]:
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                got = json.load(f)
            if isinstance(got, list):
                return [str(p) for p in got]
        except (json.JSONDecodeError, OSError):
            pass
    # first run: offer the usual places, but only the ones that are there
    return [os.path.expanduser(p) for p in SUGGESTED
            if os.path.isdir(os.path.expanduser(p))]


def save(paths: list[str]) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(paths, f, indent=1)


def describe(path: str) -> str:
    """One line about what is in there, without scanning deeply."""
    p = os.path.expanduser(path)
    if not os.path.isdir(p):
        return "not found"
    # a pipeline working directory looks nothing like the package: the
    # catalogue reads it fine, but this line used to say "nothing" and lie
    if any(n.startswith("render_") or n.startswith("work")
           for n in os.listdir(p)):
        rend = sum(1 for n in os.listdir(p) if n.startswith("render_"))
        return (f"pipeline output — {rend} rendered window"
                f"{'s' if rend != 1 else ''}")
    meshes = inks = 0
    try:
        for sd in os.listdir(p):
            if not sd.startswith("PHerc"):
                continue
            d = os.path.join(p, sd)
            if not os.path.isdir(d):
                continue
            for entry in os.listdir(d):
                if entry.endswith(".tif"):
                    inks += 1
                elif os.path.isfile(os.path.join(d, entry, "x.tif")):
                    meshes += 1
    except OSError:
        return "could not be read"
    bits = []
    if meshes:
        bits.append(f"{meshes} mesh{'es' if meshes != 1 else ''}")
    if inks:
        bits.append(f"{inks} ink map{'s' if inks != 1 else ''}")
    return ", ".join(bits) if bits else "nothing Volumen recognises"


class FoldersPage(QWidget):
    back = Signal()
    changed = Signal()

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 24, 40, 20)
        outer.setSpacing(12)

        top = QHBoxLayout()
        b = QPushButton("← Back")
        b.clicked.connect(self.leave)
        top.addWidget(b)
        top.addStretch()
        t = QLabel("Folders on this machine")
        t.setObjectName("h1")
        top.addWidget(t)
        top.addStretch()
        top.addSpacing(b.sizeHint().width())
        outer.addLayout(top)

        blurb = QLabel(
            "Volumen reads the published package over the network on its "
            "own. If you also have surfaces or ink maps on this computer, "
            "point at the folders here and they will show up alongside.")
        blurb.setObjectName("muted")
        blurb.setWordWrap(True)
        outer.addWidget(blurb)

        self.list = QListWidget()
        outer.addWidget(self.list, 1)

        row = QHBoxLayout()
        add = QPushButton("Add a folder…")
        add.setObjectName("primary")
        add.clicked.connect(self.add)
        row.addWidget(add)
        rm = QPushButton("Remove the selected one")
        rm.clicked.connect(self.remove)
        row.addWidget(rm)
        row.addStretch()
        self.note = QLabel("")
        self.note.setObjectName("muted")
        row.addWidget(self.note)
        outer.addLayout(row)

        self.paths = load()
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for p in self.paths:
            it = QListWidgetItem(f"{p}\n    {describe(p)}")
            it.setData(Qt.UserRole, p)
            self.list.addItem(it)
        self.note.setText(f"{len(self.paths)} folder"
                          f"{'s' if len(self.paths) != 1 else ''}")

    def add(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Pick a folder with meshes or ink maps",
            os.path.expanduser("~"))
        if not d or d in self.paths:
            return
        self.paths.append(d)
        save(self.paths)
        self.refresh()
        self.changed.emit()

    def remove(self) -> None:
        it = self.list.currentItem()
        if it is None:
            return
        p = it.data(Qt.UserRole)
        if p in self.paths:
            self.paths.remove(p)
            save(self.paths)
            self.refresh()
            self.changed.emit()

    def leave(self) -> None:
        save(self.paths)
        self.back.emit()
