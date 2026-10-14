"""
Груба детекція burst'ів. Окремий, явний шар ПЕРЕД matched filter.

Домен цього шару: ЧАС (секунди/відліки) і ВЛАСТИВОСТІ МАСИВУ (sample_rate_hz).
Жодного поняття "символ"/"символьна швидкість" тут немає і бути не повинно —
це поняття демодуляції, шару нижче.

Єдиний протокольний параметр: burst_duration_s (тривалість таймслота TETRA,
задокументоване значення — 14.167 мс, джерело: структура кадру TETRA).
Гарантованого мінімального інтервалу МІЖ burst'ами стандарт не дає (безперервна
передача має крок 0 с між слотами) — тому поріг злиття це внутрішній алгоритмічний
допуск, похідний від тієї ж burst_duration_s, а не протокольна константа.

Метод порогу: Оцу (Otsu) на лог-потужності — автоматично знаходить межу між
двома популяціями (шум/сигнал) без ручного порогу в дБ.
"""
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

Segments = List[Tuple[int, int]]


@dataclass(frozen=True)
class CoarseConfig:
    burst_duration_s: float = 0.014167     # ETSI: тривалість таймслота TETRA
    smooth_fraction: float = 1 / 128       # частка burst_duration на згладжування
    merge_fraction: float = 1 / 128        # частка burst_duration: допуск злиття (НЕ протокольна межа)
    min_len_fraction: float = 1 / 20       # мінімальна довжина сегмента, частка burst_duration


def _power(x: np.ndarray) -> np.ndarray:
    re = x.real.astype(np.float64); im = x.imag.astype(np.float64)
    return re * re + im * im


def _boxcar_centered(x: np.ndarray, win: int) -> np.ndarray:
    win = max(1, win)
    c = np.cumsum(np.insert(x, 0, 0.0))
    out = (c[win:] - c[:-win]) / win
    pad = len(x) - len(out)
    left = pad // 2; right = pad - left
    return np.concatenate([np.full(left, out[0]), out, np.full(right, out[-1])])


def _otsu_threshold(values: np.ndarray, nbins: int = 256) -> float:
    hist, edges = np.histogram(values, bins=nbins)
    hist = hist.astype(np.float64); p = hist / hist.sum()
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(p); w1 = 1 - w0
    mu = np.cumsum(p * centers); mu_t = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu_t * w0 - mu) ** 2 / (w0 * w1)
    between[~np.isfinite(between)] = -1
    return float(centers[int(np.argmax(between))])


def _mask_to_segments(mask: np.ndarray) -> Segments:
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.where(d == 1)[0].tolist(), np.where(d == -1)[0].tolist()))


def _merge_close(segs: Segments, gap: int) -> Segments:
    out: Segments = []
    for s, e in sorted(segs):
        if out and s - out[-1][1] <= gap:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def coarse_detect(raw: np.ndarray, sample_rate_hz: float,
                  cfg: CoarseConfig = CoarseConfig()) -> Segments:
    """raw: сирі (ДО matched filter) комплексні семпли. Повертає грубі (start,end)
    в індексах raw. Може коректно повернути один довгий сегмент, якщо реальна
    передача безперервна (це НЕ помилка — протокол це дозволяє)."""
    smooth_win = max(1, int(round(cfg.burst_duration_s * cfg.smooth_fraction * sample_rate_hz)))
    merge_gap = max(1, int(round(cfg.burst_duration_s * cfg.merge_fraction * sample_rate_hz)))
    min_len = max(1, int(round(cfg.burst_duration_s * cfg.min_len_fraction * sample_rate_hz)))

    logp = np.log(_boxcar_centered(_power(raw), smooth_win) + 1e-20)
    thr = _otsu_threshold(logp)
    segs = _merge_close(_mask_to_segments(logp > thr), merge_gap)
    return [(s, e) for s, e in segs if (e - s) >= min_len]


def filter_margin_samples(rrc_span_sym: int, sps: int) -> int:
    """Запас з кожного боку сегмента перед matched filter, щоб прибрати крайові
    артефакти згортки (overlap-save). Похідне від довжини RRC-фільтра, НЕ довільне."""
    return int(np.ceil(rrc_span_sym * sps / 2))
