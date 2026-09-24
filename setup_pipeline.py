#!/usr/bin/env python3
"""
setup_pipeline.py — set up the surface-making pipeline on this machine.

Nothing is downloaded before every check passes, and nothing is downloaded
before the person has seen what it costs and said yes. Contract:
app/ESTEIRA_INSTALADOR.md (23/09/2026).

    uv run setup_pipeline.py check                  the seven checks, nothing else
    uv run setup_pipeline.py plan  [dest] [--scroll 0826 ...]
                                                    checks + what it would cost
    uv run setup_pipeline.py install <dest> [--vc3d stable|latest] [--yes]
                                                    the environment (slice 2)
    uv run setup_pipeline.py scroll  <dest> <ROLO>  tracks + umbilicus (slice 3)

Checks, in the order they cost least, the first failure stops everything:
  1 system     Linux or WSL2 (Triton + CUDA run nowhere else)
  2 gpu        nvidia-smi answers; driver with CUDA >= 12.8 (torch cu128)
  3 vram       >= 11.5 GB tested (RTX 5070 reports 11.9); 6-11.5 warns; < 6 blocks
  4 ram        >= 32 GB comfortable; 16-32 warns; < 16 blocks
  5 disk       enough free space at the destination for what was planned
  6 tools      git and uv on PATH
  7 network    the release list and the tracks host answer

Install steps (each idempotent, marked by a .done file, resumable):
  villa        shallow clone of ScrollPrize/villa at the pinned commit
  spiral       uv sync in scripts/spiral (Python 3.14) + torch cu128 from the
               PyTorch index — the spiral pyproject does not list torch
  vc3d         the linux AppImage of the chosen release, extracted
  ink          uv sync in ink-detection + the ink_9um checkpoint from HF
  smoke        torch sees the GPU, vc_render_tifxyz answers, koine imports

Thresholds and their sources: ESTEIRA_INSTALADOR.md section 3.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

# ------------------------------------------------------------------ pins --
VILLA_REPO = "https://github.com/ScrollPrize/villa.git"
VILLA_COMMIT = "208faea7d"            # 27/07/2026, the code behind the package
VILLA_SINCE = "2026-07-25"            # shallow-since must reach the commit
TORCH_SPEC = "torch==2.11.0"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
SPIRAL_PY = "3.14"                    # scripts/spiral requires >= 3.14
VC3D_RELEASES = "https://api.github.com/repos/ScrollPrize/villa/releases"
VC3D_ASSET_SUFFIX = "linux-x86_64.AppImage"
# ink-detection (koine_machines) lives on upstream's merge-ink-pipelines
# branch, not on main (24/09/2026): erdpx's "aligned-corpus training and
# inference" of 09/08/2026. Fetched by full sha, depth 1 — GitHub serves
# any reachable commit that way, no branch or date needed.
INK_COMMIT = "4c33995ce7ff206fd3ead7aa4db5306cc6a6567b"
INK_CKPT_URL = ("https://huggingface.co/scrollprize/ink_9um/resolve/main/"
                "hybrid_3d2d-seed43/step-060000.pth")
INK_CKPT_NAME = "ink_9um_hybrid_3d2d-seed43_step-060000.pth"
TRACKS_HOST = "https://dl.ash2txt.org/datasets/spiral_datasets/"
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
# the fibre-gate reference panel (PHerc1667 w013, a scroll that has been
# read; 161 MB, the author's derived file from open data) — hosted on HF
REF_URL = ("https://huggingface.co/datasets/pscamillo/volumen-assets/resolve/main/"
           "ref_1667_w013_mid.tif")
REF_NAME = "ref_1667_w013_mid.tif"
HERE = os.path.dirname(os.path.abspath(__file__))

# sizes in GB, from the author's machine (23/09); the plan adds them up
SIZE_GB = {
    # measured on a clean install, 24/09: 20 GB in all
    "villa + spiral environment (torch cu128, triton)": 14.0,
    "VC3D release (AppImage, extracted)": 0.5,
    "ink-detection environment + checkpoint": 5.5,
}
SCROLL_GB = {                     # the .dbm tracks, measured
    "0125": 9.0, "0175A": 8.2, "0175B": 11.0, "0191": 12.0, "0211": 7.0,
    "0257": 6.0, "0268": 13.0, "0343": 9.0, "0358": 5.6, "0800": 13.0,
    "0813": 7.7, "0826": 5.1,
}
SCROLL_GB_DEFAULT = 10.0
MIN_DISK_GB = 30.0

CUDA_MIN = (12, 8)
VRAM_OK, VRAM_MIN = 11.5, 6.0     # the RTX 5070 reports 11.9 GB
RAM_OK, RAM_MIN = 32.0, 16.0

PRETEND = ""   # for tests: no-gpu | low-vram | low-ram | low-disk
LOG = None     # set by install: <dest>/setup.log


# --------------------------------------------------------------- checks --
class Check:
    def __init__(self, name: str, ok: bool, text: str, warn: bool = False):
        self.name, self.ok, self.text, self.warn = name, ok, text, warn

    @property
    def mark(self) -> str:
        return "✓" if self.ok and not self.warn else ("!" if self.ok else "✗")


def is_wsl() -> bool:
    try:
        return "microsoft" in open("/proc/version").read().lower()
    except OSError:
        return False


def check_system() -> Check:
    s = platform.system()
    if s == "Linux":
        return Check("system", True, "WSL2" if is_wsl() else "Linux")
    return Check("system", False,
                 f"{s}: the fitter runs on Triton + CUDA, which need Linux "
                 "or WSL2. Reading, cutting and judging surfaces work here; "
                 "making them does not.")


def nvidia_smi() -> list[str] | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]


def cuda_of_driver() -> tuple[int, int] | None:
    """nvidia-smi's CUDA column is not in --query-gpu; read the header."""
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True,
                             timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        if "CUDA Version:" in line:
            v = line.split("CUDA Version:")[1].split("|")[0].strip()
            try:
                a, b = v.split(".")[:2]
                return int(a), int(b)
            except ValueError:
                return None
    return None


def check_gpu() -> tuple[Check, float | None]:
    g = nvidia_smi()
    if not g:
        return Check("gpu", False,
                     "no NVIDIA GPU found (nvidia-smi does not answer). The "
                     "fitter needs one; install the NVIDIA driver first, or "
                     "use this computer for the reading tier only."), None
    name, mem, driver = g[0], float(g[1]) / 1024, g[2]
    cuda = cuda_of_driver()
    if cuda and cuda < CUDA_MIN:
        return Check("gpu", False,
                     f"{name}, driver {driver}, CUDA {cuda[0]}.{cuda[1]}: "
                     f"torch cu128 needs a driver with CUDA >= "
                     f"{CUDA_MIN[0]}.{CUDA_MIN[1]}. Update the driver."), mem
    c = f"CUDA {cuda[0]}.{cuda[1]}" if cuda else "CUDA version unknown"
    return Check("gpu", True, f"{name}, driver {driver}, {c}"), mem


def check_vram(mem_gb: float | None) -> Check:
    if mem_gb is None:
        return Check("vram", False, "could not read VRAM")
    if mem_gb < VRAM_MIN:
        return Check("vram", False,
                     f"{mem_gb:.1f} GB: below {VRAM_MIN:.0f} GB the fitter "
                     "will not fit in memory.")
    if mem_gb < VRAM_OK:
        return Check("vram", True,
                     f"{mem_gb:.1f} GB: not tested here; 12 GB is the tested "
                     "size and the community reports 6 GB as very tight "
                     "(sean, 22/09/2026). It may work, slowly.", warn=True)
    return Check("vram", True, f"{mem_gb:.1f} GB")


def ram_gb() -> float | None:
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return None


def check_ram() -> Check:
    r = ram_gb()
    if r is None:
        return Check("ram", False, "could not read RAM")
    if r < RAM_MIN:
        return Check("ram", False,
                     f"{r:.0f} GB: below {RAM_MIN:.0f} GB the fit and the "
                     "render run out of memory.")
    if r < RAM_OK:
        return Check("ram", True,
                     f"{r:.0f} GB: {RAM_OK:.0f} GB is comfortable; "
                     f"{RAM_MIN:.0f} GB may work with swap, and is tight "
                     "(waldkauz, 22/09/2026).", warn=True)
    return Check("ram", True, f"{r:.0f} GB")


def free_gb(path: str) -> float:
    p = path
    while not os.path.isdir(p):
        p = os.path.dirname(p) or "/"
    return shutil.disk_usage(p).free / 1e9


def check_disk(dest: str, need_gb: float) -> Check:
    # the pipeline's shell scripts build command lines from this path; a
    # space breaks them silently (render found no fit output, 24/09)
    if any(c.isspace() for c in dest):
        return Check("disk", False,
                     f"'{dest}' has a space in it; the pipeline's scripts "
                     "need a folder path without spaces, e.g. ~/volumen-pipeline.")
    f = free_gb(dest)
    if f < need_gb:
        return Check("disk", False,
                     f"{f:.0f} GB free at {dest}; this needs about "
                     f"{need_gb:.0f} GB. Pick another folder or free space.")
    return Check("disk", True, f"{f:.0f} GB free at {dest}")


def check_tools() -> Check:
    missing = [t for t in ("git", "uv") if not shutil.which(t)]
    if missing:
        hint = {"git": "https://git-scm.com", "uv": "https://docs.astral.sh/uv/"}
        return Check("tools", False, "missing: " + ", ".join(
            f"{m} ({hint[m]})" for m in missing))
    return Check("tools", True, "git and uv on PATH")


def head_ok(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "Volumen"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status < 400
    except (urllib.error.URLError, OSError):
        return False


def check_network() -> Check:
    bad = [u for u in (VC3D_RELEASES, TRACKS_HOST) if not head_ok(u)]
    if bad:
        return Check("network", False, "cannot reach: " + ", ".join(bad))
    return Check("network", True, "github.com and dl.ash2txt.org answer")


def run_checks(dest: str | None, need_gb: float) -> list[Check]:
    """All checks in cost order; stops after the first failure."""
    out = [check_system()]
    if not out[-1].ok:
        return out
    gpu, mem = check_gpu()
    if PRETEND == "no-gpu":
        gpu, mem = Check("gpu", False, "(pretend) no NVIDIA GPU found"), None
    elif PRETEND == "low-vram":
        mem = 4.0
    out.append(gpu)
    if not gpu.ok:
        return out
    out.append(check_vram(mem))
    if not out[-1].ok:
        return out
    out.append(check_ram())
    if PRETEND == "low-ram":
        out[-1] = Check("ram", False, "(pretend) 8 GB")
    if not out[-1].ok:
        return out
    out.append(check_disk(dest or os.path.expanduser("~"), need_gb))
    if PRETEND == "low-disk":
        out[-1] = Check("disk", False, "(pretend) 5 GB free")
    if not out[-1].ok:
        return out
    out.append(check_tools())
    if not out[-1].ok:
        return out
    out.append(check_network())
    return out


def print_checks(checks: list[Check]) -> bool:
    for c in checks:
        print(f"  {c.mark} {c.name:8s} {c.text}")
    ok = all(c.ok for c in checks)
    if not ok:
        print("\nStopped at the first check that failed. Nothing was "
              "downloaded or created.")
    return ok


# ----------------------------------------------------------------- plan --
def plan_cost(scrolls: list[str]) -> tuple[list[tuple[str, float]], float]:
    rows = list(SIZE_GB.items())
    for s in scrolls:
        rows.append((f"scroll PHerc{s}: tracks (.dbm), umbilicus, template",
                     SCROLL_GB.get(s, SCROLL_GB_DEFAULT)))
    return rows, sum(g for _, g in rows)


def print_plan(dest: str, scrolls: list[str]) -> float:
    rows, total = plan_cost(scrolls)
    print(f"\nWhat it would put in {dest}:")
    for name, gb in rows:
        print(f"  {gb:6.1f} GB  {name}")
    print(f"  {total:6.1f} GB  total, downloaded over the network once")
    print(f"  {free_gb(dest):6.0f} GB  free there now")
    print("\nTime: the spiral environment is the slow part (torch, several "
          "GB); tracks are 5-13 GB per scroll. On a 100 Mbit/s line, count "
          f"about {total * 8 * 1000 / 100 / 60:.0f} minutes for the downloads.")
    return total


def confirm(question: str) -> bool:
    try:
        a = input(f"{question} [y/N] ").strip().lower()
    except EOFError:
        return False
    return a in ("y", "yes")


# -------------------------------------------------------------- install --
def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def run(cmd: list[str], cwd: str | None = None, env: dict | None = None,
        what: str = "") -> None:
    """Run a command, stream its output to the log, raise on failure."""
    log(f"$ {' '.join(cmd)}" + (f"   (in {cwd})" if cwd else ""))
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.Popen(cmd, cwd=cwd, env=e, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    assert p.stdout
    for line in p.stdout:
        line = line.rstrip()
        if LOG:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write("    " + line + "\n")
        # keep the terminal readable: only the last 100 chars of each line
        print("    " + line[-100:], flush=True)
    if p.wait() != 0:
        raise RuntimeError(f"{what or cmd[0]} failed (exit {p.returncode}); "
                           f"see {LOG}")


def download(url: str, dest: str, what: str = "") -> None:
    """Resumable download: <dest>.part with Range, rename when whole."""
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    headers = {"User-Agent": "Volumen"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        if have and r.status != 206:      # server ignored Range: start over
            have = 0
        total = r.headers.get("Content-Length")
        total = (int(total) + have) if total else 0
        mode = "ab" if have else "wb"
        got, t0, last = have, time.time(), 0.0
        with open(part, mode) as f:
            while True:
                block = r.read(1 << 20)
                if not block:
                    break
                f.write(block)
                got += len(block)
                if time.time() - last > 2:
                    last = time.time()
                    pct = f"{100 * got / total:5.1f}%" if total else "     "
                    mbs = (got - have) / 1e6 / max(time.time() - t0, 0.1)
                    print(f"\r    {what or os.path.basename(dest)}  {pct}  "
                          f"{got / 1e9:.2f} GB  {mbs:.1f} MB/s   ",
                          end="", flush=True)
    print()
    if total and got != total:
        raise RuntimeError(f"short download: {got} of {total} bytes")
    os.replace(part, dest)
    log(f"downloaded {dest} ({got / 1e6:.0f} MB)")


def done(dest: str, step: str) -> bool:
    return os.path.isfile(os.path.join(dest, f".{step}.done"))


def mark(dest: str, step: str) -> None:
    open(os.path.join(dest, f".{step}.done"), "w").write(time.strftime("%F %T\n"))
    log(f"== {step}: done")


def step_villa(dest: str) -> str:
    villa = os.path.join(dest, "villa")
    if done(dest, "villa"):
        return villa
    log("== villa: shallow clone at the pinned commit")
    if os.path.isdir(os.path.join(villa, ".git")):
        run(["git", "-C", villa, "fetch", "--shallow-since=" + VILLA_SINCE,
             "origin", "main"], what="git fetch")
    else:
        run(["git", "clone", "--shallow-since=" + VILLA_SINCE,
             "--single-branch", "--branch", "main", VILLA_REPO, villa],
            what="git clone")
    run(["git", "-C", villa, "checkout", "--quiet", VILLA_COMMIT],
        what="git checkout")
    mark(dest, "villa")
    return villa


def step_spiral(dest: str, villa: str) -> str:
    spiral = os.path.join(villa, "volume-cartographer", "scripts", "spiral")
    if done(dest, "spiral"):
        return spiral
    log("== spiral: uv sync (Python %s) + torch cu128" % SPIRAL_PY)
    run(["uv", "sync", "--python", SPIRAL_PY], cwd=spiral, what="uv sync spiral")
    # uv sync pulls torch transitively (kornia, torchdiffeq) as the PyPI
    # build — cu13 in 09/2026 — which a CUDA 12.x driver cannot use. Replace
    # it with the cu128 build the author runs (torch 2.11.0+cu128, 23/09).
    py = spiral_python(spiral)
    # purge BEFORE installing cu128: cu12 and cu13 wheels write into the
    # same nvidia/<lib>/ folders, so removing cu13 afterwards deletes files
    # the cu12 wheels also own (libcudnn.so.9 gone, 24/09)
    purge_cu13(py)
    run(["uv", "pip", "install", "--python", py, TORCH_SPEC,
         "--index-url", TORCH_INDEX], what="torch cu128")
    # the ink model writes LZW tiffs; tifffile reads them only with
    # imagecodecs (the posfit vetoes crashed without it, 24/09)
    run(["uv", "pip", "install", "--python", py, "imagecodecs"],
        what="imagecodecs")
    mark(dest, "spiral")
    return spiral


def purge_cu13(py: str) -> None:
    """The cu13 nvidia-* wheels uv sync left behind shadow the cu12 ones
    (libtorch_cuda: undefined symbol ncclCommResume, 24/09). Remove every
    nvidia-* package whose name does not end in -cu12."""
    out = subprocess.run(["uv", "pip", "list", "--python", py, "--format", "json"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("uv pip list failed: " + out.stderr[-300:])
    names = [d["name"] for d in json.loads(out.stdout)
             if d["name"].startswith("nvidia-") or d["name"] in ("torch", "triton")]
    if names:
        run(["uv", "pip", "uninstall", "--python", py] + names,
            what="purge cu13 wheels")


def spiral_python(spiral: str) -> str:
    """The interpreter of the venv uv made for scripts/spiral — uv picks the
    project root (volume-cartographer/), so the path is asked, not assumed."""
    # --no-sync matters: a plain `uv run` re-syncs the venv to the lock and
    # puts the cu13 torch back (seen 24/09). The pipeline scripts must call
    # this interpreter by path for the same reason, never `uv run`.
    out = subprocess.run(["uv", "run", "--no-sync", "python", "-c",
                          "import sys; print(sys.executable)"],
                         cwd=spiral, capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError("could not locate the spiral venv: " + out.stderr[-300:])
    return out.stdout.strip().splitlines()[-1]


def vc3d_asset(tag: str) -> tuple[str, str, int]:
    with urllib.request.urlopen(urllib.request.Request(
            f"{VC3D_RELEASES}/tags/{tag}",
            headers={"User-Agent": "Volumen"}), timeout=30) as r:
        rel = json.load(r)
    for a in rel.get("assets", []):
        if a["name"].endswith(VC3D_ASSET_SUFFIX):
            return a["name"], a["browser_download_url"], int(a["size"])
    raise RuntimeError(f"release {tag} has no *{VC3D_ASSET_SUFFIX}")


def step_vc3d(dest: str, tag: str) -> str:
    vdir = os.path.join(dest, "vc3d")
    if done(dest, "vc3d"):
        return vdir
    os.makedirs(vdir, exist_ok=True)
    name, url, size = vc3d_asset(tag)
    log(f"== vc3d: {name} ({size / 1e6:.0f} MB, release {tag})")
    app = os.path.join(vdir, name)
    if not (os.path.isfile(app) and os.path.getsize(app) == size):
        download(url, app, name)
    os.chmod(app, 0o755)
    # extract: the binaries inside want the AppImage's own glibc, so they
    # are run through squashfs-root/AppRun, never directly
    if not os.path.isdir(os.path.join(vdir, "squashfs-root")):
        run([app, "--appimage-extract"], cwd=vdir, what="appimage extract")
    open(os.path.join(vdir, "RELEASE"), "w").write(f"{tag} {name}\n")
    mark(dest, "vc3d")
    return vdir


def step_ink(dest: str, villa: str) -> tuple[str, str]:
    vink = os.path.join(dest, "villa-ink")
    ink = os.path.join(vink, "ink-detection")
    ck = os.path.join(dest, "ink", INK_CKPT_NAME)
    if done(dest, "ink"):
        return ink, ck
    log("== ink: second shallow clone, ink-detection pin by sha")
    if not os.path.isdir(os.path.join(vink, ".git")):
        os.makedirs(vink, exist_ok=True)
        run(["git", "init", "--quiet", vink], what="git init (ink)")
        run(["git", "-C", vink, "remote", "add", "origin", VILLA_REPO],
            what="git remote add (ink)")
    run(["git", "-C", vink, "fetch", "--depth", "1", "origin", INK_COMMIT],
        what="git fetch by sha (ink)")
    run(["git", "-C", vink, "checkout", "--quiet", "FETCH_HEAD"],
        what="git checkout (ink)")
    if not os.path.isfile(os.path.join(ink, "pyproject.toml")):
        raise RuntimeError(f"{ink} has no pyproject.toml at the pinned commit")
    log("== ink: uv sync in ink-detection + checkpoint")
    run(["uv", "sync"], cwd=ink, what="uv sync ink-detection")
    os.makedirs(os.path.dirname(ck), exist_ok=True)
    if not os.path.isfile(ck):
        download(INK_CKPT_URL, ck, INK_CKPT_NAME)
    mark(dest, "ink")
    return ink, ck


def step_smoke(dest: str, spiral: str, vdir: str, ink: str) -> None:
    log("== smoke: torch sees the GPU, vc_render_tifxyz answers, koine imports")
    py = spiral_python(spiral)
    run([py, "-c", "import torch, triton, sys; "
         "ok = torch.cuda.is_available() and str(torch.version.cuda).startswith('12.'); "
         "print('torch', torch.__version__, 'cuda', torch.version.cuda, "
         "'triton', triton.__version__, 'gpu', "
         "torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-'); "
         "sys.exit(0 if ok else 1)"],
        what="torch smoke (needs a cu12 torch that sees the GPU)")
    run([os.path.join(vdir, "squashfs-root", "AppRun"), "vc_render_tifxyz",
         "--help"], what="vc_render_tifxyz smoke")
    run(["uv", "run", "python", "-c", "import koine_machines; print('koine ok')"],
        cwd=ink, what="koine smoke")
    mark(dest, "smoke")


def write_env(dest: str, villa: str, spiral: str, vdir: str, ink: str,
              ck: str) -> None:
    """pipeline/env.sh — every path the scripts need, from one place."""
    pdir = os.path.join(dest, "pipeline")
    os.makedirs(pdir, exist_ok=True)
    env = f"""# generated by setup_pipeline.py on {time.strftime('%F')} — paths for the scripts
export VOLUMEN_PIPE="{dest}"
export VOLUMEN_VILLA="{villa}"
export VOLUMEN_SPIRAL="{spiral}"
export VOLUMEN_SPIRAL_PY="{spiral_python(spiral)}"
export VOLUMEN_VC3D="{vdir}/squashfs-root/AppRun"
export VOLUMEN_INK="{ink}"
export VOLUMEN_CKPT="{ck}"
export VOLUMEN_TRACKS="{dest}/tracks"
export VOLUMEN_UMBILICI="{dest}/umbilici"
export VOLUMEN_WORK="{dest}/work"
export VOLUMEN_REF="{dest}/ink/{REF_NAME}"
"""
    open(os.path.join(pdir, "env.sh"), "w").write(env)
    log(f"wrote {pdir}/env.sh")


def install(dest: str, tag: str) -> None:
    global LOG
    os.makedirs(dest, exist_ok=True)
    LOG = os.path.join(dest, "setup.log")
    log(f"install -> {dest} (vc3d {tag})")
    villa = step_villa(dest)
    spiral = step_spiral(dest, villa)
    vdir = step_vc3d(dest, tag)
    ink, ck = step_ink(dest, villa)
    step_smoke(dest, spiral, vdir, ink)
    write_env(dest, villa, spiral, vdir, ink, ck)
    for d in ("tracks", "umbilici", "work"):
        os.makedirs(os.path.join(dest, d), exist_ok=True)
    step_pipeline(dest)
    log("environment ready. Per scroll: setup_pipeline.py scroll <dest> <ROLO>")


# ------------------------------------------------------------ pipeline --
def lasagna_id(rolo: str) -> str:
    """<VOLID>-lasagna-<date> under representations/predictions/lasagna/,
    or SEM-LASAGNA when the scroll has none published."""
    import re
    url = (f"{BUCKET}/?prefix=PHerc{rolo}/representations/predictions/lasagna/"
           "&delimiter=/")
    try:
        with urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "Volumen"}), timeout=30) as r:
            xml = r.read().decode()
    except (urllib.error.URLError, OSError):
        return "SEM-LASAGNA"
    ids = re.findall(r"lasagna/([0-9]+-lasagna-[0-9]+)/</Prefix>", xml)
    return sorted(ids)[-1] if ids else "SEM-LASAGNA"


def write_rolos(dest: str) -> None:
    """work/rolos.sh: rolo_config <ROLO> sets VOLID VOX VOL LAS."""
    sys.path.insert(0, HERE)
    import core
    lines = ["# generated by setup_pipeline.py — per-scroll values from the "
             "app's table and the bucket", "rolo_config() {", "  case \"$1\" in"]
    for s in core.ELIGIBLE:
        volid = s.volume.split("-")[0]
        las = lasagna_id(s.name)
        lines.append(f'    {s.name}) VOLID={volid}; VOX={s.voxel_um:g}; '
                     f'VOL="{core.http_url(s.volume_url)}"; LAS={las} ;;')
        log(f"   {s.name}: lasagna {las}")
    lines += ["    *) return 1 ;;", "  esac", "}", ""]
    open(os.path.join(dest, "work", "rolos.sh"), "w").write("\n".join(lines))


def register_folder(work: str) -> None:
    """Add <dest>/work to ~/.config/volumen/folders.json (what the app scans)."""
    p = os.path.expanduser("~/.config/volumen/folders.json")
    try:
        got = json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else []
    except (json.JSONDecodeError, OSError):
        got = []
    if work not in got:
        got.append(work)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(got, open(p, "w", encoding="utf-8"), indent=1)
        log(f"registered {work} in {p}")


def step_pipeline(dest: str) -> None:
    work = os.path.join(dest, "work")
    if done(dest, "pipeline"):
        return
    log("== pipeline: scripts, reference panel, per-scroll table")
    src = os.path.join(HERE, "pipeline")
    if not os.path.isdir(src):
        raise RuntimeError(f"{src} missing: this checkout has no pipeline/")
    for f in os.listdir(src):
        shutil.copy2(os.path.join(src, f), os.path.join(work, f))
    ref = os.path.join(dest, "ink", REF_NAME)
    if not os.path.isfile(ref):
        download(REF_URL, ref, REF_NAME)
    write_rolos(dest)
    register_folder(work)
    mark(dest, "pipeline")


def scroll(dest: str, rolo: str) -> None:
    """tracks (.dbm), umbilicus, render template for one scroll."""
    global LOG
    LOG = os.path.join(dest, "setup.log")
    sys.path.insert(0, HERE)
    import core
    s = core.SCROLLS.get(rolo)
    if s is None:
        raise RuntimeError(f"unknown scroll {rolo}")
    volid = s.volume.split("-")[0]
    work = os.path.join(dest, "work")
    # tracks
    dbm = f"PHerc{rolo}_{volid}_surface_m7_L0_th0.2.dbm"
    dst = os.path.join(dest, "tracks", dbm)
    if not os.path.isfile(dst):
        url = f"{TRACKS_HOST}PHerc{rolo}/{volid}/tracks/{dbm}"
        if not head_ok(url):
            raise RuntimeError(f"no tracks published for {rolo} at {url}")
        log(f"== tracks: {dbm} ({SCROLL_GB.get(rolo, SCROLL_GB_DEFAULT):.0f} GB)")
        download(url, dst, dbm)
    else:
        log(f"== tracks: already here")
    # umbilicus: the author's generator over the whole scroll, unless the
    # person put one there already (any source, the fit only needs the JSON)
    umb = os.path.join(dest, "umbilici", f"PHerc{rolo}_umbilicus.json")
    if not os.path.isfile(umb):
        depth = volume_depth(s)
        log(f"== umbilicus: gera_umbilicus.py over z 0..{depth} (takes a while)")
        py = spiral_python(os.path.join(dest, "villa", "volume-cartographer",
                                        "scripts", "spiral"))
        run([py, os.path.join(work, "gera_umbilicus.py"), "--rolo", rolo,
             "--zarr", f"PHerc{rolo}/volumes/{s.volume}", "--um", f"{s.voxel_um:g}",
             "--z0", "0", "--z1", str(depth), "--saida", umb],
            cwd=work, what="gera_umbilicus")
    else:
        log("== umbilicus: already here")
    # render template
    tpl = open(os.path.join(work, "render_template.sh")).read()
    tpl = (tpl.replace("__ROLO__", rolo).replace("__VOL__", core.http_url(s.volume_url))
              .replace("__PX__", f"{s.voxel_um * 1e-4:.6g}"))
    out = os.path.join(work, f"render_{rolo}.sh")
    open(out, "w").write(tpl)
    os.chmod(out, 0o755)
    log(f"wrote {out}")
    log(f"{rolo} ready: bash {work}/esteira_via3.sh {rolo} 1")


def volume_depth(s) -> int:
    """z extent of the native level, from the bucket's .zarray."""
    sys.path.insert(0, HERE)
    import core
    url = f"{core.http_url(s.volume_url)}/0/.zarray"
    with urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "Volumen"}), timeout=30) as r:
        return int(json.load(r)["shape"][0])


# ----------------------------------------------------------------- main --
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pretend", choices=("no-gpu", "low-vram", "low-ram", "low-disk"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    p = sub.add_parser("plan")
    p.add_argument("dest", nargs="?", default=os.path.expanduser("~/volumen-pipeline"))
    p.add_argument("--scroll", action="append", default=[])
    p = sub.add_parser("install")
    p.add_argument("dest")
    p.add_argument("--vc3d", choices=("stable", "latest"), default="stable")
    p.add_argument("--scroll", action="append", default=[])
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("scroll")
    p.add_argument("dest")
    p.add_argument("rolo")
    a = ap.parse_args()
    global PRETEND
    PRETEND = a.pretend or ""

    if a.cmd == "check":
        print("Checks:")
        return 0 if print_checks(run_checks(None, MIN_DISK_GB)) else 1

    if a.cmd == "plan":
        dest = os.path.expanduser(a.dest)
        rows, total = plan_cost(a.scroll)
        print("Checks:")
        if not print_checks(run_checks(dest, max(MIN_DISK_GB, total))):
            return 1
        print_plan(dest, a.scroll)
        print("\nThis was only a plan. `install` asks the same question "
              "and then does it.")
        return 0

    if a.cmd == "install":
        dest = os.path.expanduser(a.dest)
        rows, total = plan_cost(a.scroll)
        print("Checks:")
        if not print_checks(run_checks(dest, max(MIN_DISK_GB, total))):
            return 1
        print_plan(dest, a.scroll)
        if not a.yes and not confirm("\nProceed?"):
            print("Not installed. Nothing was downloaded or created.")
            return 2
        try:
            install(dest, a.vc3d)
        except (RuntimeError, urllib.error.URLError, OSError) as e:
            log(f"!! {e}")
            print("\nStopped. What finished is kept and marked; run the same "
                  "command again to resume.")
            return 4
        if a.scroll:
            print("\n`scroll` (tracks + umbilicus) comes in the next slice; "
                  "run it per scroll when it lands.")
        return 0

    if a.cmd == "scroll":
        dest = os.path.expanduser(a.dest)
        if not done(dest, "pipeline"):
            print(f"{dest} is not installed yet: run `install` first.")
            return 1
        try:
            scroll(dest, a.rolo)
        except (RuntimeError, urllib.error.URLError, OSError) as e:
            log(f"!! {e}")
            print("\nStopped. Run the same command again to resume.")
            return 4
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
