"""
Оцінка SNR на burst. Рахується НА СИРОМУ масиві (до matched filter) -
узгоджено з грубою детекцією (coarse_detect.py), щоб не змішувати processing
gain фільтра в число.

Шум: локальна медіана потужності в сусідніх ділянках (ліворуч+праворуч від
burst'а), довжиною burst_duration_s, З ВИКЛЮЧЕННЯМ зон, зайнятих іншими
burst'ами (інакше для щільного ефіру шум оцінювався б частково по сигналу).
Сигнал: середня потужність усередині burst'а МІНУС оцінений шум (бо виміряна
потужність burst'а це сигнал+шум разом, а не чистий сигнал).
"""
from typing import List, Optional, Tuple

import numpy as np

Segments = List[Tuple[int, int]]


def _power(x: np.ndarray) -> np.ndarray:
    re = x.real.astype(np.float64); im = x.imag.astype(np.float64)
    return re * re + im * im


def _free_noise_mask(n: int, all_segments: Segments, lo: int, hi: int) -> np.ndarray:
    """True там, де [lo,hi) НЕ зайнято жодним burst'ом з all_segments."""
    lo = max(0, lo); hi = min(n, hi)
    mask = np.ones(hi - lo, dtype=bool)
    for s, e in all_segments:
        a, b = max(s, lo), min(e, hi)
        if a < b:
            mask[a - lo:b - lo] = False
    return mask


def estimate_noise_power(raw_power: np.ndarray, burst: Tuple[int, int],
                         all_segments: Segments, window_samples: int,
                         min_samples: int = 16) -> Optional[float]:
    """Локальна медіана потужності шуму в сусідніх з burst'ом ділянках,
    з винятком зон інших burst'ів. None, якщо вільних відліків замало."""
    s, e = burst; n = len(raw_power)
    left = _free_noise_mask(n, all_segments, s - window_samples, s)
    right = _free_noise_mask(n, all_segments, e, e + window_samples)
    vals = np.concatenate([
        raw_power[max(0, s - window_samples):s][left],
        raw_power[e:min(n, e + window_samples)][right],
    ])
    if len(vals) < min_samples:
        return None
    return float(np.median(vals))


def estimate_burst_snr_db(raw_power: np.ndarray, burst: Tuple[int, int],
                          all_segments: Segments, window_samples: int) -> Optional[float]:
    """SNR burst'а в дБ, рахований на СИРОМУ масиві потужності.
    signal = mean(P_burst) - P_noise (виправлення на шум у самій вибірці burst'а).
    Якщо signal <= 0 (сигнал нижче оціненого шуму) -> None (ненадійна оцінка)."""
    s, e = burst
    noise = estimate_noise_power(raw_power, burst, all_segments, window_samples)
    if noise is None or noise <= 0:
        return None
    p_total = float(raw_power[s:e].mean())
    signal = p_total - noise
    if signal <= 0:
        return None
    return float(10 * np.log10(signal / noise))
