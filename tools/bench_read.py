"""How fast this machine reads the CT: the app's own path, raw bytes, decoding.

    uv run python tools/bench_read.py
"""
import os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core

s = core.SCROLLS["0800"]
arr = core.open_volume(s, 0)
print("compressor:", arr.compressor)


def ids_at(frac):
    cz = int(arr.shape[0] * frac) // 128
    cy, cx = arr.shape[1] // 2 // 128, arr.shape[2] // 2 // 128
    return [(cz + i, cy + j, cx + k) for i in range(4) for j in range(4) for k in range(4)]


t = time.time(); out, _ = core.fetch_chunks(arr, ids_at(0.3)); dt = time.time() - t
mb = sum(b.nbytes for b in out.values()) / 1e6
print(f"app path (fetch_chunks) : {mb/dt:5.1f} MB/s  ({dt:.1f} s)")

st = arr.store
keys = [arr._chunk_key(i) for i in ids_at(0.7)]


def raw(k):
    try:
        return st[k]
    except KeyError:
        return b""


t = time.time()
with ThreadPoolExecutor(32) as ex:
    data = [d for d in ex.map(raw, keys) if d]
dt = time.time() - t
mb = sum(len(d) for d in data) / 1e6
print(f"raw bytes, 32 threads   : {mb/dt:5.1f} MB/s  ({dt:.1f} s)")

if arr.compressor is not None and data:
    t = time.time()
    with ThreadPoolExecutor(32) as ex:
        list(ex.map(arr.compressor.decode, data))
    print(f"decode only, 32 threads : {len(data)} chunks in {time.time() - t:.2f} s")
