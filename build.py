#!/usr/bin/env python3
"""
build.py — running the pipeline from inside Volumen.

Two routes, same controls:

  with lasagna   esteira_via3.sh — the team's sheet-direction volumes feed the
                 spiral fit. The scrolls it offers are read from the script's
                 own case table.

  geometric      esteira_geo.sh — EXPERIMENTAL. Sheet directions come from a
                 structure tensor on the raw CT instead. It works — on
                 PHercParis4 the surface landed 3.0 voxels from the official
                 segment — but on 18/09 a cross-section through one window of
                 0175B showed the surface crossing between sheets in part of
                 it, while mask escape read 0.00%. Ink on these surfaces may
                 belong to the neighbouring sheet. The scrolls it offers are
                 the ones with tracks, an automatic umbilicus and a render
                 template on disk; the rest are listed with what is missing.

Both run the same post-fit (posfit.sh): flatten, render, mid, fibre panel,
ink, vetoes. A unit comes out the same whichever route made it.

The pipeline is found through Folders: any folder holding esteira_via3.sh.

STOPPING WITHOUT BREAKING THINGS. The lasagna route decides a window is done
from the existence of its directories, so killing it mid-window would leave
a half-made window that the next run skips as finished. Stop is in two
steps: the first drops a signal file both scripts check between windows;
only a second click kills, and it moves the window in flight to
_interrompidos/ instead of deleting it.

No pause: freezing the process holds the GPU and leaves S3 connections idle,
and S3 drops idle connections.

ONE AT A TIME, across both routes and the desktop icon: two runs on one GPU
fight for memory, and both routes rewrite UM_ALVO in painel_fibras.py.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import signal
import subprocess
import time

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

import core
import sources

STOP_FILE = ".volumen_stop"
RE_CASE = re.compile(r"^\s{2}(?P<rolo>[0-9A-Za-z]+)\)\s+VOLID=", re.M)
RE_WINDOW = re.compile(r"z(?P<z0>\d{4,5})")
import config  # noqa: E402  pipeline discovery and umbilici folder

MODES = {
    "lasagna": ("With lasagna", "esteira_via3.sh"),
    "geometric": ("Geometric — experimental", "esteira_geo.sh"),
}

# Crossing between sheets is not a failure of one route: it was seen on
# 18/09 in a geometric surface of 0175B and on 21/09 in a lasagna surface of
# 0125. One case each — nothing measured says which route crosses more.
CROSSING = (
    "Any fitted surface can cross from one sheet to the next — seen here on "
    "both routes, and mask escape catches neither. Ink on a crossing may "
    "belong to the neighbouring sheet: look at a cut before taking any "
    "candidate seriously."
)
WARNING_ALL = CROSSING
WARNING_GEO = (
    "EXPERIMENTAL — sheet directions come from the raw CT instead of the "
    "team's lasagna, validated on one scroll only (PHercParis4, 3.0 voxels "
    "from the official segment).  " + CROSSING
)


def pipeline_root() -> str:
    return config.pipeline_root()


def lasagna_scrolls(root: str) -> list[str]:
    try:
        with open(os.path.join(root, "esteira_via3.sh"),
                  encoding="utf-8") as f:
            return RE_CASE.findall(f.read())
    except OSError:
        return []


def geometric_status(root: str) -> tuple[list[str], dict[str, str]]:
    """Which no-lasagna scrolls can run, and what the others are missing."""
    ready, missing = [], {}
    names = [s.name for s in core.ELIGIBLE if s.route == "geometric"]
    for r in names:
        lack = []
        if not glob.glob(os.path.join(
                root, f"tracks_{r}", f"PHerc{r}_*_surface_m7_L0_th0.2.dbm")):
            lack.append("tracks")
        if not os.path.isfile(os.path.join(
                config.umbilici_dir() or "/nonexistent",
                f"PHerc{r}_umbilicus_auto.json")):
            lack.append("umbilicus")
        if not glob.glob(os.path.join(root, f"render_{r}_z*.sh")):
            lack.append("render template")
        if lack:
            missing[r] = ", ".join(lack)
        else:
            ready.append(r)
    return ready, missing


def already_running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-f", r"esteira_(via3|geo)\.sh"],
                             capture_output=True, text=True).stdout
        return bool(out.strip())
    except FileNotFoundError:
        return False


class BuildPage(QWidget):
    back = Signal()
    produced = Signal()

    def __init__(self):
        super().__init__()
        self.proc: QProcess | None = None
        self.root = ""
        self.mode = "lasagna"
        self.scroll = ""
        self.current_z0: str | None = None
        self.stop_requested = False
        self.started_at = 0.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 24, 40, 18)
        outer.setSpacing(12)

        top = QHBoxLayout()
        b = QPushButton("← Back")
        b.clicked.connect(self.back)
        top.addWidget(b)
        top.addStretch()
        t = QLabel("Make surfaces")
        t.setObjectName("h1")
        top.addWidget(t)
        top.addStretch()
        top.addSpacing(b.sizeHint().width())
        outer.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Route"))
        self.route = QComboBox()
        for key, (label, _) in MODES.items():
            self.route.addItem(label, key)
        self.route.currentIndexChanged.connect(self.mode_changed)
        row.addWidget(self.route)
        row.addSpacing(18)
        row.addWidget(QLabel("Scroll"))
        self.pick = QComboBox()
        self.pick.setMinimumWidth(120)
        row.addWidget(self.pick)
        row.addSpacing(18)
        row.addWidget(QLabel("Windows"))
        self.n = QSpinBox()
        self.n.setRange(1, 20)
        row.addWidget(self.n)
        row.addSpacing(18)
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        row.addWidget(self.start_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.stop_btn)
        row.addStretch()
        self.log_btn = QPushButton("Show log")
        self.log_btn.setCheckable(True)
        self.log_btn.toggled.connect(self.toggle_log)
        row.addWidget(self.log_btn)
        outer.addLayout(row)

        self.blurb = QLabel()
        self.blurb.setObjectName("muted")
        self.blurb.setWordWrap(True)
        outer.addWidget(self.blurb)

        self.warning = QLabel(WARNING_GEO)
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(
            "color: #e8a33d; border: 1px solid #e8a33d; border-radius: 8px;"
            " padding: 10px 14px;")
        self.warning.setVisible(False)
        outer.addWidget(self.warning)

        self.status = QLabel("Idle.")
        self.status.setObjectName("h2")
        outer.addWidget(self.status)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setVisible(False)
        outer.addWidget(self.log, 1)
        outer.addStretch()

        self.tick = QTimer(self)
        self.tick.timeout.connect(self.update_clock)
        self.refresh()

    # -- setup ---------------------------------------------------------
    def refresh(self) -> None:
        self.root = pipeline_root()
        if not self.root:
            self.pick.clear()
            needs = "".join(f"<li><b>{k}</b> — {v}</li>"
                            for k, v in config.PIPELINE_NEEDS)
            self.blurb.setText(
                "<p>No pipeline on this machine. Making surfaces here "
                "means running the spiral fitter and the ink model, and "
                "that needs:</p>"
                f"<ul>{needs}</ul>"
                "<p>With those in place, add the folder that holds "
                "esteira_via3.sh in Folders. Without them, surfaces can "
                "still come from the published package, from a patch "
                "grown in VC3D (add its .volpkg in Folders), or from "
                "any tifxyz folder.</p>")
            self.start_btn.setEnabled(False)
            return
        self.mode_changed()

    def mode_changed(self, *_):
        self.mode = self.route.currentData() or "lasagna"
        self.pick.clear()
        geo = self.mode == "geometric"
        self.warning.setText(WARNING_GEO if geo else WARNING_ALL)
        self.warning.setVisible(True)
        if not self.root:
            return
        script = MODES[self.mode][1]
        if not os.path.isfile(os.path.join(self.root, script)):
            self.blurb.setText(f"{script} is not in {self.root} yet.")
            self.start_btn.setEnabled(False)
            return
        if geo:
            ready, missing = geometric_status(self.root)
            self.pick.addItems(ready)
            miss = "; ".join(f"{k} ({v})" for k, v in sorted(missing.items()))
            self.blurb.setText(
                "Scrolls with no published lasagna. Windows run in order of "
                "umbilicus score, best first, and a window is only counted "
                "done when its content says so."
                + (f"  Not ready — missing: {miss}." if miss else ""))
        else:
            self.pick.addItems(lasagna_scrolls(self.root))
            self.blurb.setText(
                f"Runs the minimal route with lasagna from {self.root}. Each "
                f"window is fitted, flattened, rendered and run through the "
                f"ink model; its fibre panel lands in the gate queue. Windows "
                f"are drawn from the grid without repetition.")
        self.start_btn.setEnabled(self.proc is None and self.pick.count() > 0)

    def toggle_log(self, on: bool) -> None:
        self.log.setVisible(on)
        self.log_btn.setText("Hide log" if on else "Show log")

    # -- running -------------------------------------------------------
    def start(self) -> None:
        if not self.root or self.proc is not None or not self.pick.count():
            return
        if already_running():
            self.status.setText("The pipeline is already running.")
            self.summary.setText(
                "Maybe from the desktop icon. Two runs on one GPU fight for "
                "memory and rewrite the same panel settings, so this will not "
                "start another. Stop that one first.")
            return

        self.scroll = self.pick.currentText()
        n = self.n.value()
        script = MODES[self.mode][1]
        stop = os.path.join(self.root, STOP_FILE)
        if os.path.exists(stop):
            os.remove(stop)

        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(self.root)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        # Python buffers its output when it goes to a pipe rather than a
        # terminal: from the icon the log flows at once, from here it came in
        # 4 kB blocks with minutes of silence between them
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self.read_output)
        self.proc.finished.connect(self.finished)
        # setsid: the pipeline and every child it spawns share one process
        # group, so Stop now can end all of them rather than just the shell
        self.proc.start("setsid", ["bash", script, self.scroll, str(n)])

        self.stop_requested = False
        self.current_z0 = None
        self.started_at = time.time()
        self.tick.start(1000)
        self.start_btn.setEnabled(False)
        self.route.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("Stop")
        tag = " · experimental" if self.mode == "geometric" else ""
        self.status.setText(f"Running · PHerc{self.scroll}{tag}")
        self.summary.setText("")
        self.log.appendPlainText(
            f"=== {time.strftime('%F %T')} · {script} · {self.scroll} · "
            f"{n} windows")

    def read_output(self) -> None:
        if self.proc is None:
            return
        text = bytes(self.proc.readAllStandardOutput()).decode(
            "utf-8", errors="replace")
        for ln in text.splitlines():
            self.log.appendPlainText(ln)
            # only the window headers carry the window being worked on; the
            # "skipping" lines mention other windows and would mislead Stop now
            if ln.startswith("===="):
                m = RE_WINDOW.search(ln)
                if m:
                    self.current_z0 = m.group("z0")
            if ln.startswith("==") or "FLAG" in ln or "RUIM" in ln:
                self.summary.setText(ln.strip())

    def update_clock(self) -> None:
        if self.proc is None:
            return
        m, s = divmod(int(time.time() - self.started_at), 60)
        h, m = divmod(m, 60)
        where = f" · window z{self.current_z0}" if self.current_z0 else ""
        tag = " · experimental" if self.mode == "geometric" else ""
        tail = " · stopping after this window" if self.stop_requested else ""
        self.status.setText(f"Running · PHerc{self.scroll}{tag}{where} · "
                            f"{h:d}:{m:02d}:{s:02d}{tail}")

    def stop(self) -> None:
        if self.proc is None:
            return
        if not self.stop_requested:
            open(os.path.join(self.root, STOP_FILE), "w").close()
            self.stop_requested = True
            self.stop_btn.setText("Stop now")
            self.summary.setText(
                "The current window will finish, then the pipeline stops. "
                "Click Stop now only if you cannot wait — the window in "
                "flight will be set aside and redone next time.")
            return
        self.kill_now()

    def kill_now(self) -> None:
        pid = self.proc.processId() if self.proc else 0
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)
                QTimer.singleShot(6000, lambda: self._force(pid))
            except ProcessLookupError:
                pass
        self.summary.setText(self.set_aside())

    @staticmethod
    def _force(pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def set_aside(self) -> str:
        """Move the half-made window out of the way instead of deleting it."""
        if not self.current_z0:
            return ("Stopped, but the window in flight could not be "
                    "identified from the log. Check the newest work* and "
                    "render_* folders by hand before the next run.")
        dest = os.path.join(self.root, "_interrompidos",
                            time.strftime("%Y%m%d-%H%M%S"))
        moved = []
        for name in os.listdir(self.root):
            if (name.endswith(f"_{self.scroll}_z{self.current_z0}")
                    and (name.startswith("work")
                         or name.startswith("render_"))):
                os.makedirs(dest, exist_ok=True)
                shutil.move(os.path.join(self.root, name),
                            os.path.join(dest, name))
                moved.append(name)
        if not moved:
            return f"Stopped. Nothing on disk yet for z{self.current_z0}."
        return (f"Stopped. Set aside {', '.join(moved)} in {dest} — it will "
                f"be redone next time.")

    def finished(self, code: int, _status) -> None:
        self.tick.stop()
        stop = os.path.join(self.root, STOP_FILE)
        if os.path.exists(stop):
            os.remove(stop)
        was = "stopped" if self.stop_requested else "finished"
        self.log.appendPlainText(f"=== {was} with code {code}")
        self.status.setText(f"{was.capitalize()} · PHerc{self.scroll}")
        self.proc = None
        self.route.setEnabled(True)
        self.start_btn.setEnabled(self.pick.count() > 0)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Stop")
        self.produced.emit()
