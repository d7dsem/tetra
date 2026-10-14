"""
Етап C: символьна синхронізація одного burst'а.
  estimate_timing()  сегмент @ sps          -> tau (відліків, [0, sps))
  sample_symbols()   y, [s,e), tau          -> комплексні символи

Оцінювач Oerder-Meyr: лінія на частоті символів у |x|^2 дає фазу, яка
визначає оптимальний момент вибірки (енергія максимальна в точках символів).
"""
from functools import lru_cache

import numpy as np
from scipy.signal import firwin, resample_poly

from burst_search import power
from config import FrontEndConfig, TimingConfig


@lru_cache(maxsize=None)
def _interp_taps(F: int) -> np.ndarray:
    """Той самий фільтр, що resample_poly проєктує за замовчуванням (kaiser 5.0),
    але один раз, а не на кожен burst."""
    return firwin(2 * 10 * F + 1, 1.0 / F, window=("kaiser", 5.0))


@lru_cache(maxsize=None)
def _phasors(sps: int) -> np.ndarray:
    return np.exp(-2j * np.pi * np.arange(sps) / sps)


def estimate_timing(seg: np.ndarray, sps: int) -> float:
    """c = sum p[n] e^{-j2pi n/sps}. Замість комплексного масиву розміру n:
    сума p по фазах n mod sps (sps значень), далі згортка з sps фазорами."""
    p = power(seg)
    w = _phasors(sps)
    m = len(p) // sps * sps
    c = p[:m].reshape(-1, sps).sum(axis=0, dtype=np.float64) @ w
    rem = p[m:]
    c += rem.astype(np.float64) @ w[:len(rem)]
    return float((-np.angle(c) * sps / (2 * np.pi)) % sps)


def sample_symbols(y: np.ndarray, s: int, e: int, tau: float,
                   front: FrontEndConfig, timing: TimingConfig) -> np.ndarray:
    """Передискретизує лише потрібний шматок (з запасом), не весь файл."""
    sps, F = front.sps, timing.fine_upsample
    margin = int(round(timing.margin_sym * sps))
    s0, e0 = max(0, s - margin), min(len(y), e + margin)
    fine = resample_poly(y[s0:e0], F, 1, window=_interp_taps(F))
    per_sym = sps * F
    start = (s - s0) * F + int(round(tau * F)) % per_sym
    stop = (e - s0) * F
    return fine[start:stop:per_sym]
