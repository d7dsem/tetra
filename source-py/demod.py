"""
Етап D: демодуляція pi/4-DQPSK з символів одного burst'а.
  diff_demod()           символи          -> d (одиничні фазори, dphi)
  estimate_freq_offset() d                -> theta, рад/символ
  correct_freq()         d, theta         -> d без зсуву
  map_dibits()           d, таблиця       -> біти (2 на символ)
  quality_metrics()      d                -> (coherence, phase_rms_deg)

Ідеальні dphi: +-pi/4, +-3pi/4, тому d^4 = -1 незалежно від даних.
"""
from typing import Tuple

import numpy as np

from config import MapConfig


def ambiguity_hz(symbol_rate_hz: float) -> float:
    """Межа однозначності оцінки тонкого зсуву: |f| < symbol_rate/8."""
    return symbol_rate_hz / 8.0


def diff_demod(sym: np.ndarray) -> np.ndarray:
    """d[k] = s[k]*conj(s[k-1]) / |.| ; один новий масив, далі in-place."""
    d = np.conjugate(sym[:-1])
    d *= sym[1:]
    a = np.abs(d)
    a += 1e-12
    d /= a
    return d


def estimate_freq_offset(d: np.ndarray) -> float:
    """Рад/символ. Однозначно для |theta| < pi/4 (|f| < symbol_rate/8). d не змінюється."""
    d4 = np.square(d)
    np.square(d4, out=d4)
    return float(np.angle(-d4.mean()) / 4)


def correct_freq(d: np.ndarray, theta: float) -> np.ndarray:
    """IN-PLACE: змінює d і повертає його ж."""
    d *= np.exp(-1j * theta)
    return d


def map_dibits(d: np.ndarray, cfg: MapConfig) -> np.ndarray:
    """Квадрант за знаками Re/Im (без тригонометрії), біти беруться з таблиці."""
    neg_im = d.imag < 0
    q = neg_im.astype(np.intp)
    q *= 2
    q += (d.real < 0) ^ neg_im          # 0:(+,+) 1:(-,+) 2:(-,-) 3:(+,-)
    bits = np.empty((len(d), 2), dtype=np.uint8)
    np.take(np.asarray(cfg.dibit_by_quadrant, dtype=np.uint8), q, axis=0, out=bits)
    return bits.reshape(-1)


def quality_metrics(d: np.ndarray) -> Tuple[float, float]:
    """coherence: |mean(d^4)| (1 ідеально, ~0 шум/не та модуляція);
    phase_rms_deg: розкид фази навколо найближчої ідеальної точки. d не змінюється."""
    if len(d) == 0:
        return 0.0, 180.0
    d4 = np.square(d)
    np.square(d4, out=d4)
    coherence = float(np.abs(d4.mean()))
    np.negative(d4, out=d4)
    err = np.angle(d4)                   # = 4 * відхилення від ідеалу
    rms = float(np.sqrt(np.dot(err, err) / len(err))) / 4
    return coherence, float(np.degrees(rms))
