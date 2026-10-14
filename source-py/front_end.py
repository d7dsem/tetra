"""
Етап A: front-end.
  to_work_rate()   IQ @ fs               -> IQ @ work_fs (SPS * symbol rate)
  rrc_taps()       параметри             -> коефіцієнти RRC
  matched_filter() IQ @ work_fs          -> IQ після RRC (нульова затримка)
"""
from fractions import Fraction
from functools import lru_cache

import numpy as np
from scipy.signal import oaconvolve, resample_poly

from config import FrontEndConfig


def to_work_rate(x: np.ndarray, fs: float, cfg: FrontEndConfig) -> np.ndarray:
    if abs(fs - cfg.work_fs_hz) < 1e-6:
        return x.astype(np.complex64, copy=False)
    r = Fraction(cfg.work_fs_hz / fs).limit_denominator(1000)
    return resample_poly(x, r.numerator, r.denominator).astype(np.complex64, copy=False)


@lru_cache(maxsize=None)
def rrc_taps(beta: float, sps: int, span_sym: int) -> np.ndarray:
    """Векторизований RRC, нормований на одиничну енергію. Кешується (read-only)."""
    t = np.arange(-span_sym * sps // 2, span_sym * sps // 2 + 1) / sps
    with np.errstate(divide="ignore", invalid="ignore"):
        h = (np.sin(np.pi * t * (1 - beta)) + 4 * beta * t * np.cos(np.pi * t * (1 + beta))) / (
            np.pi * t * (1 - (4 * beta * t) ** 2))
    singular = (beta / np.sqrt(2)) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * beta))
                                      + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
    h = np.where(np.abs(t) < 1e-12, 1.0 - beta + 4 * beta / np.pi, h)
    h = np.where(np.abs(np.abs(t) - 1 / (4 * beta)) < 1e-9, singular, h)
    h = h / np.sqrt(np.sum(h ** 2))
    h.setflags(write=False)
    return h


def matched_filter(x: np.ndarray, cfg: FrontEndConfig) -> np.ndarray:
    # float32-коефіцієнти: результат лишається complex64 (з float64 було б complex128)
    h = rrc_taps(cfg.rrc_rolloff, cfg.sps, cfg.rrc_span_sym).astype(np.float32)
    return oaconvolve(x, h, mode="same").astype(np.complex64, copy=False)
