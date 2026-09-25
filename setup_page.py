#!/usr/bin/env python3
"""
setup_page.py — Set up the pipeline, inside the app.

Three parts, in the order the person needs them: what this machine has
(the seven checks, nothing downloaded), what it would cost (per component,
per scroll, with the destination folder), and — only after Proceed — the
install itself with a bar per step and the log underneath. Then a second
stage per scroll: tracks, umbilicus and render template.

Nothing here decides anything: setup_pipeline.py does, in a QProcess, and
this window shows what it prints. The checks are run in-process because
they are quick and print nothing.
"""
from __future__ import annotations

import os
import re
import sys

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

import core
import setup_pipeline as sp

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "setup_pipeline.py")
STEPS = ["villa", "spiral", "vc3d", "ink", "smoke", "pipeline"]
RE_STEP = re.compile(r"== (\w+):")
RE_PCT = re.compile(r"(\d+\.\d)%")
MARK_COLOR = {"✓": "#7fb77e", "!": "#e8a33d", "✗": "#a0523d"}


class SetupDialog(QDialog):
    """Returns Accepted when the environment (and optionally one scroll)
    was installed; the caller refreshes the Make surfaces screen."""
    installed = Signal(str)          # destination folder

    def __init__(self, parent: QWidget | None = None, dest: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Set up the pipeline")
        self.setMinimumWidth(880)
        self.proc: QProcess | None = None
        self.seen_install = False
        self.dest = dest or os.path.expanduser("~/volumen-pipeline")
        self.ok = False

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(26, 22, 26, 20)

        h = QLabel("<b>Set up the pipeline</b>")
        h.setObjectName("h2")
        lay.addWidget(h)
        intro = QLabel("Making surfaces here means running the spiral fitter "
                       "and the ink model on this machine. Nothing is "
                       "downloaded before every check passes, and nothing "
                       "before you have seen what it costs and said yes.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        # 1. checks
        lay.addWidget(QLabel("<b>1. This machine</b>"))
        self.checks = QLabel()
        self.checks.setTextFormat(Qt.RichText)
        self.checks.setWordWrap(True)
        lay.addWidget(self.checks)

        # 2. cost + destination
        lay.addWidget(QLabel("<b>2. What it costs</b>"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Install into"))
        self.dest_box = QLineEdit(self.dest)
        self.dest_box.editingFinished.connect(self.replan)
        row.addWidget(self.dest_box, 1)
        b = QPushButton("Browse…")
        b.clicked.connect(self.browse)
        row.addWidget(b)
        lay.addLayout(row)
        self.cost = QLabel()
        self.cost.setTextFormat(Qt.RichText)
        self.cost.setWordWrap(True)
        lay.addWidget(self.cost)

        # 3. progress
        lay.addWidget(QLabel("<b>3. Progress</b>"))
        self.step = QLabel("Not started.")
        lay.addWidget(self.step)
        self.bar = QProgressBar()
        self.bar.setRange(0, len(STEPS))
        self.bar.setValue(0)
        lay.addWidget(self.bar)
        self.sub = QProgressBar()
        self.sub.setRange(0, 100)
        self.sub.setValue(0)
        self.sub.setVisible(False)
        lay.addWidget(self.sub)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setMinimumHeight(180)
        lay.addWidget(self.log, 1)

        # per-scroll stage (enabled after the environment is in)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Then, per scroll:"))
        self.scroll = QComboBox()
        self.fill_scrolls()
        srow.addWidget(self.scroll)
        self.scroll_btn = QPushButton("Prepare this scroll")
        self.scroll_btn.clicked.connect(self.prepare_scroll)
        self.scroll_btn.setEnabled(False)
        srow.addWidget(self.scroll_btn)
        self.scroll_note = QLabel("tracks (5–13 GB), umbilicus (~30 min of "
                                  "CT reads), render template")
        self.scroll_note.setObjectName("muted")
        srow.addWidget(self.scroll_note)
        srow.addStretch()
        lay.addLayout(srow)

        # the axis check (25/09): after a scroll is prepared, before it can
        # be fitted — the automatic umbilicus can land off the scroll with a
        # good score (0826)
        self.axis_box = QWidget()
        ab = QVBoxLayout(self.axis_box)
        ab.setContentsMargins(0, 10, 0, 0)
        self.axis_text = QLabel("")
        self.axis_text.setWordWrap(True)
        self.axis_text.setTextFormat(Qt.RichText)
        ab.addWidget(self.axis_text)
        self.axis_img = QLabel()
        self.axis_img.setAlignment(Qt.AlignCenter)
        ab.addWidget(self.axis_img)
        arow = QHBoxLayout()
        self.axis_ok = QPushButton("Looks centred")
        self.axis_ok.setObjectName("primary")
        self.axis_own = QPushButton("Use my own umbilicus file…")
        self.axis_later = QPushButton("Not now")
        for b in (self.axis_ok, self.axis_own, self.axis_later):
            arow.addWidget(b)
        arow.addStretch()
        ab.addLayout(arow)
        self.axis_ok.clicked.connect(self.axis_accept)
        self.axis_own.clicked.connect(self.axis_own_file)
        self.axis_later.clicked.connect(lambda: self.axis_box.setVisible(False))
        self.axis_box.setVisible(False)
        lay.addWidget(self.axis_box)
        self.pending = ""
        self.axis_warn: list[str] = []

        # buttons
        brow = QHBoxLayout()
        brow.addStretch()
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        brow.addWidget(self.close_btn)
        self.go = QPushButton("Proceed")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.proceed)
        brow.addWidget(self.go)
        lay.addLayout(brow)

        self.replan()

    def fill_scrolls(self) -> None:
        """Eligible scrolls with published lasagna, not yet prepared here."""
        self.scroll.clear()
        work = os.path.join(self.dest, "work")
        # which scrolls have lasagna: the bucket (cached a day), not the
        # rolos.sh written at install — lasagna appears after installs
        pub = core.lasagna_published()
        has_las = None
        if pub is not None:
            core.apply_lasagna(pub)       # lasagna AND tracks: ready to fit
            has_las = {s.name for s in core.ELIGIBLE if s.route == "lasagna"}
        for s in core.ELIGIBLE:
            if has_las is not None and s.name not in has_las:
                continue
            done = os.path.isfile(os.path.join(work, f"render_{s.name}.sh"))
            self.scroll.addItem(f"PHerc{s.name}" + (" (prepared)" if done else ""),
                                s.name)

    # -- checks and plan --------------------------------------------------
    def replan(self) -> None:
        self.dest = os.path.expanduser(self.dest_box.text().strip() or "~/volumen-pipeline")
        rows, total = sp.plan_cost([])
        checks = sp.run_checks(self.dest, max(sp.MIN_DISK_GB, total))
        html = []
        for c in checks:
            col = MARK_COLOR[c.mark]
            html.append(f"<span style='color:{col}'>{c.mark}</span> "
                        f"<b>{c.name}</b> — {c.text}")
        self.all_ok = all(c.ok for c in checks)
        if not self.all_ok:
            html.append("<i>Stopped at the first check that failed. Nothing "
                        "was downloaded or created.</i>")
        self.checks.setText("<br>".join(html))
        if self.all_ok:
            free = sp.free_gb(self.dest)
            mins = total * 8 * 1000 / 100 / 60
            lines = [f"{gb:5.1f} GB &nbsp; {name}" for name, gb in rows]
            lines.append(f"<b>{total:5.1f} GB &nbsp; in all</b>, downloaded once; "
                         f"{free:.0f} GB free there now")
            lines.append(f"About {mins:.0f} minutes on a 100 Mbit/s line; "
                         "the spiral environment is the slow part. Each scroll "
                         "adds 5–13 GB later.")
            self.cost.setText("<br>".join(lines))
        else:
            self.cost.setText("—")
        self.go.setEnabled(self.all_ok and self.proc is None)
        # already installed here: skip to the per-scroll stage
        if os.path.isfile(os.path.join(self.dest, ".pipeline.done")):
            self.ok = True
            self.go.setEnabled(False)
            self.bar.setValue(len(STEPS))
            self.step.setText("The environment is installed here. Prepare "
                              "a scroll below.")
            self.scroll_btn.setEnabled(self.proc is None)
            self.fill_scrolls()

    def browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Install the pipeline into",
                                             os.path.dirname(self.dest))
        if d:
            self.dest_box.setText(os.path.join(d, "volumen-pipeline")
                                  if os.path.basename(d) != "volumen-pipeline" else d)
            self.replan()

    # -- running setup_pipeline.py ----------------------------------------
    def _spawn(self, args: list[str]) -> None:
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.go.setEnabled(False)
        self.scroll_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.log.appendPlainText("$ " + " ".join(args))
        self.proc.start(sys.executable, [SCRIPT] + args)

    def proceed(self) -> None:
        if not self.all_ok:
            return
        self.bar.setValue(0)
        self.step.setText("Starting…")
        self.mode = "install"
        self.seen_install = False
        self._spawn(["install", self.dest, "--yes"])

    def prepare_scroll(self) -> None:
        rolo = self.scroll.currentData()
        self.pending = rolo
        self.axis_warn = []
        self.axis_box.setVisible(False)
        self.mode = "scroll"
        self.step.setText(f"Preparing PHerc{rolo}: tracks, umbilicus, template…")
        self._spawn(["scroll", self.dest, rolo])

    def _read(self) -> None:
        assert self.proc
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for chunk in data.replace("\r", "\n").split("\n"):
            line = chunk.rstrip()
            if not line:
                continue
            m = RE_PCT.search(line)
            if m and "GB" in line:                 # a download progress line
                self.sub.setVisible(True)
                self.sub.setValue(int(float(m.group(1))))
                self.step.setText(line.strip())
                continue
            # the plan the script prints before installing is already on
            # screen above; keep the log for what happens
            if self.mode == "install" and not self.seen_install and \
                    " install -> " not in line:
                if line.startswith("Checks:") or line.startswith("What it would") \
                        or line.startswith("Time:") or line.strip().startswith(("✓", "!", "✗")) \
                        or line.strip().endswith(("GB", "now")) or "GB  " in line:
                    continue
            if " install -> " in line:
                self.seen_install = True
            self.log.appendPlainText(line)
            sb = self.log.verticalScrollBar()
            sb.setValue(sb.maximum())          # keep the last line in view
            m = RE_STEP.search(line)
            if m and self.mode == "scroll":
                self.sub.setVisible(False)
                self.step.setText(line.split("== ", 1)[1])
            if m and self.mode == "install":
                name = m.group(1)
                if name in STEPS:
                    done = "done" in line
                    idx = STEPS.index(name) + (1 if done else 0)
                    self.bar.setValue(idx)
                    self.step.setText(f"{name}: {'done' if done else 'working…'}")
                    self.sub.setVisible(False)
            if "!! axis" in line:
                self.axis_warn.append(line.split("!! ", 1)[1].strip())
            if line.startswith("!!"):
                self.step.setText(line)

    def _finished(self, code: int, _status) -> None:
        self.proc = None
        self.close_btn.setEnabled(True)
        self.sub.setVisible(False)
        if code == 0 and self.mode == "install":
            self.ok = True
            self.bar.setValue(len(STEPS))
            self.step.setText("Environment ready. Prepare a scroll to start "
                              "making surfaces.")
            self.scroll_btn.setEnabled(True)
            self.installed.emit(self.dest)
        elif code == 0 and self.mode in ("scroll", "axis") and not os.path.isfile(
                os.path.join(self.dest, "work", f"render_{self.pending}.sh")):
            self.show_axis()
            self.scroll_btn.setEnabled(True)
        elif code == 0:
            self.axis_box.setVisible(False)
            self.step.setText(f"PHerc{self.pending or self.scroll.currentData()} "
                              "ready: close this window and pick it under "
                              "Make surfaces.")
            self.scroll_btn.setEnabled(True)
            self.fill_scrolls()
            self.installed.emit(self.dest)
        elif self.mode == "install":
            self.step.setText("Stopped — see the log. What finished is kept; "
                              "Proceed again resumes.")
            self.go.setEnabled(True)
        else:
            self.step.setText("Stopped — see the log. What finished is kept; "
                              "Prepare this scroll again resumes.")
            self.scroll_btn.setEnabled(os.path.isfile(
                os.path.join(self.dest, ".pipeline.done")))

    # -- the axis check ---------------------------------------------------
    def show_axis(self) -> None:
        from PySide6.QtGui import QPixmap
        r = self.pending
        pm = QPixmap(os.path.join(self.dest, "umbilici", f"PHerc{r}_check.png"))
        if not pm.isNull():
            self.axis_img.setPixmap(pm.scaledToWidth(min(900, pm.width()),
                                                     Qt.SmoothTransformation))
        warn = ""
        if self.axis_warn:
            warn = ("<br><span style='color:#e8a33d'>" + "; ".join(
                w[0].upper() + w[1:] for w in self.axis_warn) + ".</span>")
        self.axis_text.setText(
            f"<b>Check the axis before fitting PHerc{r}.</b> The amber cross is "
            "the umbilicus the fit will wind around, on three slices a quarter, "
            "half and three quarters up the scroll. It should sit in the middle "
            "of the rings on all three. On crushed scrolls the automatic one can "
            "land off centre, or outside the scroll, with a good score." + warn)
        self.axis_box.setVisible(True)
        self.step.setText(f"PHerc{r}: tracks and umbilicus ready — check the "
                          "axis below.")
        self.adjustSize()

    def axis_accept(self) -> None:
        self.mode = "accept"
        self.step.setText(f"PHerc{self.pending}: writing the render template…")
        self._spawn(["accept", self.dest, self.pending])

    def axis_own_file(self) -> None:
        import json, shutil
        from PySide6.QtWidgets import QFileDialog
        f, _ = QFileDialog.getOpenFileName(
            self, "An umbilicus file (JSON with control_points x, y, z)",
            os.path.expanduser("~"), "JSON (*.json)")
        if not f:
            return
        try:
            pts = json.load(open(f, encoding="utf-8"))["control_points"]
            assert pts and all(k in pts[0] for k in ("x", "y", "z"))
        except Exception:                             # noqa: BLE001
            self.step.setText("That file is not an umbilicus: it needs "
                              "control_points with x, y and z.")
            return
        dst = os.path.join(self.dest, "umbilici", f"PHerc{self.pending}_umbilicus.json")
        auto = dst[:-5] + "_auto.json"
        if os.path.isfile(dst) and not os.path.isfile(auto):
            shutil.copy2(dst, auto)                    # keep the automatic one
        shutil.copy2(f, dst)
        self.axis_warn = []
        self.mode = "axis"
        self.step.setText("Drawing the axis check with your umbilicus…")
        self._spawn(["axis", self.dest, self.pending])

    def reject(self) -> None:
        if self.proc is not None:
            return                    # not while it runs
        super().accept() if self.ok else super().reject()
