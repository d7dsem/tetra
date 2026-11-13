"""Генератор синтетичних сигналів для тестів."""
import numpy as np

from config import FrontEndConfig
from front_end import rrc_taps
from pattern_check import SLOT_BITS

PHASE_NEAR_RAD = np.pi / 4        # |dphi| для бітів "близько" (+-pi/4)
PHASE_FAR_RAD = 3 * np.pi / 4     # |dphi| для бітів "далеко" (+-3pi/4)
START_PHASE_RAD = 0.3             # початкова фаза burst'а
TX_DELAY_SAMPLES = 3              # затримка burst'а в tx_burst за замовчуванням у make_signal
SILENCE_NOISE_AMP = 0.01          # амплітуда шуму між burst'ами й на самих burst'ах
LEAD_SAMPLES = 5000               # шум перед першим burst'ом
RX_NOISE_AMP = 0.05               # адитивний шум усього запису
NOISE_BURST_SAMPLES = 1100        # довжина шумоподібного burst'а (kind="noise")
NOISE_BURST_POWER = 0.25          # його потужність
DEFAULT_N_BURSTS = 3
DEFAULT_F_OFF_HZ = 400.0
DEFAULT_GAP_SAMPLES = 6000        # пауза після кожного burst'а
BER_MAX_SHIFT = 12                # макс. зсув при вирівнюванні бітів, біти
BER_MIN_OVERLAP = 200             # менше спільних бітів - зсув не враховуємо

FE = FrontEndConfig()
H = rrc_taps(FE.rrc_rolloff, FE.sps, FE.rrc_span_sym)


def cnoise(n, p, rng):
    return np.sqrt(p / 2) * (rng.normal(size=n) + 1j * rng.normal(size=n))


def bits_to_dphase(bits):
    """b1=знак (1 -> мінус), b2=далеко (1 -> 3pi/4)."""
    mag = np.where(bits[1::2] == 1, PHASE_FAR_RAD, PHASE_NEAR_RAD)
    return mag * np.where(bits[0::2] == 1, -1, 1)


def tx_burst(bits, delay=0):
    s = np.exp(1j * np.cumsum(np.concatenate(([START_PHASE_RAD], bits_to_dphase(bits)))))
    up = np.zeros(len(s) * FE.sps, dtype=complex)
    up[::FE.sps] = s
    return np.concatenate((np.zeros(delay), np.convolve(up, H)))


def make_signal(rng, n_bursts=DEFAULT_N_BURSTS, n_bits=SLOT_BITS, f_off=DEFAULT_F_OFF_HZ, kind="tetra",
                gap=DEFAULT_GAP_SAMPLES):
    """kind: 'tetra' | 'noise' (шумоподібний burst тієї ж потужності)."""
    pieces, txs = [SILENCE_NOISE_AMP * cnoise(LEAD_SAMPLES, 1, rng)], []
    for _ in range(n_bursts):
        bits = rng.integers(0, 2, n_bits).astype(np.uint8)
        b = tx_burst(bits, delay=TX_DELAY_SAMPLES) if kind == "tetra" else cnoise(NOISE_BURST_SAMPLES, NOISE_BURST_POWER, rng)
        txs.append(bits)
        pieces.append(b + SILENCE_NOISE_AMP * cnoise(len(b), 1, rng))
        pieces.append(SILENCE_NOISE_AMP * cnoise(gap, 1, rng))
    x = np.concatenate(pieces)
    x = x * np.exp(2j * np.pi * f_off * np.arange(len(x)) / FE.work_fs_hz)
    x = x + RX_NOISE_AMP * cnoise(len(x), 1, rng)
    return x.astype(np.complex64), txs


def ber_aligned(rx, tx, max_shift=BER_MAX_SHIFT):
    best = 1.0
    for sh in range(-max_shift, max_shift + 1):
        a, b = rx[max(0, sh):], tx[max(0, -sh):]
        m = min(len(a), len(b))
        if m > BER_MIN_OVERLAP:
            best = min(best, float(np.mean(a[:m] != b[:m])))
    return best
