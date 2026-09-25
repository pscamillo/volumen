#!/usr/bin/env python3
"""
build.py — running the pipeline from inside Volumen.

One route: esteira_via3.sh, with the team's sheet-direction volumes
(lasagna) feeding the spiral fit, then the post-fit (posfit.sh): flatten,
render, mid, fibre panel, ink, vetoes. The scrolls it offers are the ones
prepared in this pipeline folder. A geometric route (sheet directions from a
structure tensor on the raw CT) was tried and dropped on 25/09: it crossed
sheets on 0175B and put the axis on the edge of 0826.

The pipeline is found through Folders: any folder holding esteira_via3.sh.

STOPPING WITHOUT BREAKING THINGS. The lasagna route decides a window is done
from the existence of its directories, so killing it mid-window would leave
a half-made window that the next run skips as finished. Stop is in two
steps: the first drops a signal file the script checks between windows;
only a second click kills, and it moves the window in flight to
_interrompidos/ instead of deleting it.

No pause: freezing the process holds the GPU and leaves S3 connections idle,
and S3 drops idle connections.

ONE AT A TIME, counting the pipeline's desktop icon: two runs on one GPU
fight for memory, and each rewrites UM_ALVO in painel_fibras.py.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import signal
import subprocess
import time

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, Signal
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
}

# Crossing between sheets was seen on 21/09 in a lasagna surface of 0125.
CROSSING = (
    "Any fitted surface can cross from one sheet to the next — seen here on "
    "0125, and mask escape does not catch it. Ink on a crossing may "
    "belong to the neighbouring sheet: look at a cut before taking any "
    "candidate seriously."
)
WARNING_ALL = CROSSING


def pipeline_root() -> str:
    return config.pipeline_root()


RE_ROLOS = re.compile(r"^\s*(?P<rolo>[0-9A-Za-z]+)\)\s+VOLID=.*?LAS=(?P<las>\S+)",
                      re.M)


def lasagna_scrolls(root: str) -> list[str]:
    """Scrolls this pipeline can run with lasagna.

    An installed pipeline (setup_pipeline.py) keeps the table in rolos.sh;
    a scroll is listed once it is prepared (render_<ROLO>.sh written by
    `scroll`). The author's rota_minima keeps the table inside
    esteira_via3.sh, in a case statement."""
    rolos = os.path.join(root, "rolos.sh")
    if os.path.isfile(rolos):
        try:
            txt = open(rolos, encoding="utf-8").read()
        except OSError:
            return []
        return [m.group("rolo") for m in RE_ROLOS.finditer(txt)
                if m.group("las") != "SEM-LASAGNA"
                and os.path.isfile(os.path.join(root, f"render_{m.group('rolo')}.sh"))]
    try:
        with open(os.path.join(root, "esteira_via3.sh"),
                  encoding="utf-8") as f:
            return RE_CASE.findall(f.read())
    except OSError:
        return []


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
        self.route = QComboBox()
        for key, (label, _) in MODES.items():
            self.route.addItem(label, key)
        self.route.currentIndexChanged.connect(self.mode_changed)
        row.addSpacing(18)
        # which pipeline, when Folders holds more than one (25/09)
        self.pipe_lbl = QLabel("Pipeline")
        self.pipe = QComboBox()
        self.pipe.currentIndexChanged.connect(self.pipe_changed)
        row.addWidget(self.pipe_lbl)
        row.addWidget(self.pipe)
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

        # without a pipeline: the installer (setup_page.py), checks first
        self.setup_btn = QPushButton("Set up the pipeline…")
        self.setup_btn.setObjectName("primary")
        self.setup_btn.clicked.connect(self.open_setup)
        self.setup_btn.setVisible(False)
        self.scroll_btn = QPushButton("Prepare another scroll…")
        self.scroll_btn.clicked.connect(self.open_setup)
        self.scroll_btn.setVisible(False)
        srow = QHBoxLayout()
        srow.addWidget(self.setup_btn)
        srow.addWidget(self.scroll_btn)
        srow.addStretch()
        outer.addLayout(srow)

        self.warning = QLabel(WARNING_ALL)
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(
            "color: #e8a33d; border: 1px solid #e8a33d; border-radius: 8px;"
            " padding: 10px 14px;")
        self.warning.setVisible(False)
        outer.addWidget(self.warning)
        # a scroll that gained lasagna since the last check (once a day)
        self.news = QLabel("")
        self.news.setWordWrap(True)
        self.news.setStyleSheet("color: #e8a33d;")
        self.news.setVisible(False)
        self.news.setTextFormat(Qt.RichText)
        self.news.linkActivated.connect(self.dismiss_news)
        outer.addWidget(self.news)

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
    def check_lasagna(self) -> None:
        """Scrolls that gained lasagna this session stay announced until
        they are prepared in this pipeline."""
        if not hasattr(self, "gained"):
            self.gained = set()
        self.gained |= set(core.apply_lasagna(core.lasagna_published()))
        self.gained -= getattr(self, "dismissed", set())
        if self.root:
            self.gained -= set(lasagna_scrolls(self.root))
        if not self.gained:
            self.news.setVisible(False)
            return
        names = ", ".join(f"PHerc{n}" for n in sorted(self.gained))
        if not self.root:
            how = "Set up the pipeline… and prepare it"
        elif os.path.isfile(os.path.join(self.root, "rolos.sh")):
            how = "Prepare another scroll… adds it here"
        else:
            how = "add it to this pipeline's scroll table"
        self.news.setText(f"Lasagna is now published for {names}. {how}, "
                          "and it can be fitted like the others.  "
                          "<a href='dismiss' style='color:#8a8272'>dismiss</a>")
        self.news.setVisible(True)

    def dismiss_news(self, *_):
        self.dismissed = getattr(self, "dismissed", set()) | self.gained
        self.gained = set()
        self.news.setVisible(False)

    def pipe_changed(self, *_):
        r = self.pipe.currentData()
        if r and r != self.root:
            self.chosen_root = r
            self.refresh()

    def refresh(self) -> None:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, self.check_lasagna)
        roots = config.pipeline_roots()
        chosen = getattr(self, "chosen_root", "")
        self.root = chosen if chosen in roots else (roots[0] if roots else "")
        self.pipe.blockSignals(True)
        self.pipe.clear()
        for r in roots:
            # an installed pipeline's root is <dest>/work: name it by <dest>
            name = os.path.basename(os.path.dirname(r)) \
                if os.path.basename(r) == "work" else os.path.basename(r)
            self.pipe.addItem(name, r)
            self.pipe.setItemData(self.pipe.count() - 1, r, Qt.ToolTipRole)
        if self.root in roots:
            self.pipe.setCurrentIndex(roots.index(self.root))
        self.pipe.blockSignals(False)
        for w in (self.pipe_lbl, self.pipe):
            w.setVisible(len(roots) > 1)
        if not self.root:
            self.pick.clear()
            needs = "".join(f"<li><b>{k}</b> — {v}</li>"
                            for k, v in config.PIPELINE_NEEDS)
            self.blurb.setText(
                "<p>No pipeline on this machine. Making surfaces here "
                "means running the spiral fitter and the ink model, and "
                "that needs:</p>"
                f"<ul>{needs}</ul>"
                "<p><b>Set up the pipeline</b> does this for you: it checks "
                "the machine first (Linux or WSL, NVIDIA GPU, memory, disk) "
                "and downloads only after you have seen what it costs and "
                "said yes. If you already have these, add the folder that "
                "holds esteira_via3.sh in Folders. Without them, surfaces "
                "still come from the published package, from a patch grown "
                "in VC3D (add its .volpkg in Folders), or from any tifxyz "
                "folder.</p>")
            self.start_btn.setEnabled(False)
            self.setup_btn.setVisible(True)
            return
        self.setup_btn.setVisible(False)
        # an installed pipeline (rolos.sh) can prepare more scrolls here
        self.scroll_btn.setVisible(
            os.path.isfile(os.path.join(self.root, "rolos.sh")))
        self.mode_changed()

    def open_setup(self) -> None:
        import setup_page
        dest = os.path.dirname(self.root) if self.root and os.path.isfile(
            os.path.join(self.root, "rolos.sh")) else ""
        dlg = setup_page.SetupDialog(self, dest=dest)
        dlg.installed.connect(lambda _d: self.refresh())
        dlg.exec()
        self.refresh()

    def mode_changed(self, *_):
        self.mode = self.route.currentData() or "lasagna"
        self.pick.clear()
        self.warning.setText(WARNING_ALL)
        self.warning.setVisible(True)
        if not self.root:
            return
        script = MODES[self.mode][1]
        if not os.path.isfile(os.path.join(self.root, script)):
            self.blurb.setText(f"{script} is not in {self.root} yet.")
            self.start_btn.setEnabled(False)
            return
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
        self.pipe.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("Stop")
        self.status.setText(f"Running · PHerc{self.scroll}")
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
            if ln.startswith("==") or "FLAG" in ln or "RUIM" in ln or "no winding" in ln:
                self.summary.setText(ln.strip())

    def update_clock(self) -> None:
        if self.proc is None:
            return
        m, s = divmod(int(time.time() - self.started_at), 60)
        h, m = divmod(m, 60)
        where = f" · window z{self.current_z0}" if self.current_z0 else ""
        tail = " · stopping after this window" if self.stop_requested else ""
        self.status.setText(f"Running · PHerc{self.scroll}{where} · "
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
        self.pipe.setEnabled(True)
        self.start_btn.setEnabled(self.pick.count() > 0)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Stop")
        self.produced.emit()
