"""
Пошук burst'ів за потужністю. Кожен етап це окрема чиста функція:

  1. power()              y (complex)        -> p (float), |y|^2
  2. smooth()             p                  -> env, ковзне середнє
  3. estimate_noise_floor() env              -> floor (масив тієї ж довжини)
  4. detect_segments()    env, floor         -> сегменти (гістерезис on/off)
  5. merge_close()        сегменти           -> сегменти (склеїти малі провали)
  6. filter_length()      сегменти           -> сегменти (min/max довжина)
  7. trim_edges()         сегменти           -> сегменти (відрізати рампи)

search_bursts() просто викликає їх по черзі і зберігає проміжні результати
в SearchResult, щоб кожен крок можна було подивитись окремо.

Усі індекси сегментів: відліки вхідного масиву, [start, end), end не включено.
Усі параметри в SearchConfig; довжини задаються в символах і переводяться
у відліки через sps.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from scipy.ndimage import uniform_filter1d

from config import SearchConfig

Segments = List[Tuple[int, int]]


@dataclass
class SearchResult:
    cfg: SearchConfig
    env: np.ndarray
    floor: np.ndarray
    raw: Segments = field(default_factory=list)       # після етапу 4
    merged: Segments = field(default_factory=list)    # після етапу 5
    filtered: Segments = field(default_factory=list)  # після етапу 6
    final: Segments = field(default_factory=list)     # після етапу 7


# ---------- 1. потужність ----------
def power(y: np.ndarray, out: Optional[np.ndarray] = None) -> np.ndarray:
    """|y|^2 у буфері out (за потреби створює один). abs(out=) + square(out=):
    виміряно на complex64 4.25 М відліків ~3.4 мс проти ~9.2 мс для re*re+im*im,
    бо np.abs для complex має оптимізований шлях, а з out= жодних тимчасових масивів."""
    if out is None:
        out = np.empty(y.shape, dtype=y.real.dtype)
    np.abs(y, out=out)
    np.square(out, out=out)
    return out


# ---------- 2. згладжування ----------
def smooth(p: np.ndarray, win: int, out: Optional[np.ndarray] = None) -> np.ndarray:
    """Ковзне середнє довжини win, краї 'nearest'. out=p дозволяє рахувати in-place."""
    win = max(1, int(win))
    if win == 1 or len(p) == 0:
        if out is None:
            return p.copy()
        out[...] = p
        return out
    return uniform_filter1d(p, win, mode="nearest", output=out)


# ---------- 3. шумова підлога ----------
def estimate_noise_floor(env: np.ndarray, cfg: SearchConfig) -> np.ndarray:
    n = len(env)
    if cfg.noise_mode == "fixed":
        if cfg.noise_fixed is None:
            raise ValueError("noise_mode='fixed' потребує noise_fixed")
        return np.broadcast_to(np.float32(cfg.noise_fixed), (n,))
    if cfg.noise_mode == "global":
        return np.broadcast_to(np.float32(np.percentile(env, cfg.noise_percentile)), (n,))
    if cfg.noise_mode == "local":
        block = max(1, cfg.n(cfg.noise_block_sym))
        if n <= block:
            return np.broadcast_to(np.float32(np.percentile(env, cfg.noise_percentile)), (n,))
        edges = np.arange(0, n, block)
        vals, centers = [], []
        for s in edges:
            e = min(n, s + block)
            vals.append(np.percentile(env[s:e], cfg.noise_percentile))
            centers.append((s + e - 1) / 2)
        return np.interp(np.arange(n), centers, vals).astype(np.float32)
    raise ValueError(f"невідомий noise_mode: {cfg.noise_mode}")


# ---------- 4. детекція (гістерезис) ----------
def mask_to_segments(mask: np.ndarray) -> Segments:
    """Межі серій True. Працює на bool-масиві без int64-проміжних копій."""
    mask = np.asarray(mask, dtype=bool)
    n = len(mask)
    if n == 0:
        return []
    edges = np.flatnonzero(mask[1:] != mask[:-1]) + 1
    if mask[0]:
        edges = np.concatenate(([0], edges))
    if mask[-1]:
        edges = np.concatenate((edges, [n]))
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist()))


def _scaled(floor: np.ndarray, k: float):
    """Для постійної підлоги (broadcast, stride 0) повертає скаляр: без масиву n."""
    if floor.ndim == 1 and len(floor) and floor.strides[0] == 0:
        return np.float32(floor[0]) * np.float32(k)
    return floor * k


def detect_segments(env: np.ndarray, floor: np.ndarray,
                    on_db: float, off_db: float) -> Segments:
    """Область вважається burst'ом, якщо env > floor+off_db, і хоча б в одній
    точці області env > floor+on_db. Кордони визначає нижчий поріг off_db."""
    if off_db > on_db:
        raise ValueError("off_db має бути <= on_db")
    weak = env > _scaled(floor, 10 ** (off_db / 10))
    strong = env > _scaled(floor, 10 ** (on_db / 10))
    return [(s, e) for s, e in mask_to_segments(weak) if strong[s:e].any()]


# ---------- 5. склеювання ----------
def merge_close(segs: Segments, max_gap: int) -> Segments:
    out: Segments = []
    for s, e in segs:
        if out and s - out[-1][1] <= max_gap:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


# ---------- 6. фільтр довжини ----------
def filter_length(segs: Segments, min_len: int, max_len: Optional[int] = None) -> Segments:
    return [(s, e) for s, e in segs
            if (e - s) >= min_len and (max_len is None or (e - s) <= max_len)]


# ---------- 7. обрізання країв ----------
def trim_edges(segs: Segments, trim: int) -> Segments:
    return [(s + trim, e - trim) for s, e in segs if (e - s) > 2 * trim]


# ---------- повний пошук ----------
def search_bursts(y: np.ndarray, cfg: Optional[SearchConfig] = None) -> SearchResult:
    cfg = cfg or SearchConfig()
    p = power(y)
    env = smooth(p, cfg.n(cfg.smooth_sym), out=p)  # in-place: env перезаписує p
    floor = estimate_noise_floor(env, cfg)
    res = SearchResult(cfg=cfg, env=env, floor=floor)
    res.raw = detect_segments(env, floor, cfg.on_db, cfg.off_db)
    res.merged = merge_close(res.raw, cfg.n(cfg.merge_gap_sym))
    max_len = cfg.n(cfg.max_len_sym) if cfg.max_len_sym else None
    res.filtered = filter_length(res.merged, cfg.n(cfg.min_len_sym), max_len)
    res.final = trim_edges(res.filtered, cfg.n(cfg.trim_sym))
    return res


def describe(res: SearchResult) -> str:
    fl = float(np.median(res.floor))
    return (f"floor(median)={10*np.log10(fl+1e-20):.1f} dB  "
            f"raw={len(res.raw)} -> merged={len(res.merged)} -> "
            f"filtered={len(res.filtered)} -> final={len(res.final)}")


def plot_search(res: SearchResult, fs: float):
    import matplotlib.pyplot as plt
    t = np.arange(len(res.env)) / fs
    db = lambda a: 10 * np.log10(np.asarray(a) + 1e-20)
    plt.figure(figsize=(12, 4))
    plt.plot(t, db(res.env), label="env")
    plt.plot(t, db(res.floor), label="floor")
    plt.plot(t, db(res.floor) + res.cfg.on_db, "--", label="on")
    plt.plot(t, db(res.floor) + res.cfg.off_db, ":", label="off")
    for s, e in res.final:
        plt.axvspan(s / fs, e / fs, alpha=0.2, color="g")
    plt.xlabel("s"); plt.ylabel("dB"); plt.legend(); plt.show()
