"""Генератор синтетичних сигналів для тестів."""
import numpy as np

from config import FrontEndConfig
from front_end import rrc_taps

FE = FrontEndConfig()
H = rrc_taps(FE.rrc_rolloff, FE.sps, FE.rrc_span_sym)


def cnoise(n, p, rng):
    return np.sqrt(p / 2) * (rng.normal(size=n) + 1j * rng.normal(size=n))


def bits_to_dphase(bits):
    """b1=знак (1 -> мінус), b2=далеко (1 -> 3pi/4)."""
    mag = np.where(bits[1::2] == 1, 3 * np.pi / 4, np.pi / 4)
    return mag * np.where(bits[0::2] == 1, -1, 1)


def tx_burst(bits, delay=0):
    s = np.exp(1j * np.cumsum(np.concatenate(([0.3], bits_to_dphase(bits)))))
    up = np.zeros(len(s) * FE.sps, dtype=complex)
    up[::FE.sps] = s
    return np.concatenate((np.zeros(delay), np.convolve(up, H)))


def make_signal(rng, n_bursts=3, n_bits=510, f_off=400.0, kind="tetra", gap=6000):
    """kind: 'tetra' | 'noise' (шумоподібний burst тієї ж потужності)."""
    pieces, txs = [0.01 * cnoise(5000, 1, rng)], []
    for _ in range(n_bursts):
        bits = rng.integers(0, 2, n_bits).astype(np.uint8)
        b = tx_burst(bits, delay=3) if kind == "tetra" else cnoise(1100, 0.25, rng)
        txs.append(bits)
        pieces.append(b + 0.01 * cnoise(len(b), 1, rng))
        pieces.append(0.01 * cnoise(gap, 1, rng))
    x = np.concatenate(pieces)
    x = x * np.exp(2j * np.pi * f_off * np.arange(len(x)) / FE.work_fs_hz)
    x = x + 0.05 * cnoise(len(x), 1, rng)
    return x.astype(np.complex64), txs


def ber_aligned(rx, tx, max_shift=12):
    best = 1.0
    for sh in range(-max_shift, max_shift + 1):
        a, b = rx[max(0, sh):], tx[max(0, -sh):]
        m = min(len(a), len(b))
        if m > 200:
            best = min(best, float(np.mean(a[:m] != b[:m])))
    return best
