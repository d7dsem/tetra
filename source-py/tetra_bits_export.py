"""
Готує IQ-запис у форматі для канального декодера osmo-tetra (tetra-rx).

Обидва burst-пошук і по-burst'овий таймінг - ПЕРЕВИКОРИСТАНІ з основного
пайплайна (burst_search.search_bursts, symbols.estimate_timing), а не
вигадані заново; перша версія цього модуля оцінювала таймінг один раз на
весь файл - причину такого підходу (дрейф, втрата синхронізації) підказав
user, виправлено.

Два СТРУКТУРНІ варіанти розміщення бітів burst'ів (за аналогією з .bin2/.bin3
з tetra_demod.py, але тут про формат для tetra-rx, не для перегляду):

  TRUE-TIME (аналог .bin3): кожен burst на СПРАВЖНІЙ позиції в бітовому часі
    (bit_pos = round(start_sample / sample_rate_hz * 2 * symbol_rate_hz)),
    проміжки - випадкові біти. ПІДТВЕРДЖЕНО working на реальному tetra-rx
    (CRC OK на BSCH/AACH/SB1, кілька burst'ів поспіль, зростання FN).

  SEQUENTIAL (аналог .bin2): burst'и йдуть ПІДРЯД, кожен доповнений нулями
    до кратності 510 біт (SLOT_BITS) ПІСЛЯ власного кінця - реальний
    проміжок часу між burst'ами ІГНОРУЄТЬСЯ. НЕ перевірено на tetra-rx;
    додано для порівняння на прохання user - чи критичне для декодера
    точне відтворення реального часу між burst'ами, чи ні.

Формат виходу: 1 байт = 1 біт, сире значення 0/1 (uint8), конвенція
sym{-3,-1,1,3}->bits - з float_to_bits.c (osmo-tetra), без змін.
Знак фази (sign=+1 "plus"): ПІДТВЕРДЖЕНО робочим на реальному декодуванні;
sign=-1 "minus" генерується й надалі для обох режимів, про всяк випадок -
дешево утримувати, якщо раптом стане в пригоді для іншого запису/налаштувань.
"""
import argparse
import os

import numpy as np

import burst_search
import front_end
import symbols
from config import PipelineConfig
from io_stage import load_iq, probe_input
from pattern_check import SLOT_BITS

SYM_TO_BITS = {-3: (1, 1), -1: (1, 0), 1: (0, 0), 3: (0, 1)}


def phase_to_sym(d: np.ndarray, sign: int) -> np.ndarray:
    deg = sign * np.degrees(np.angle(d))
    sym = np.round(deg / 45.0).astype(int)
    sym = np.clip(sym, -3, 3)
    sym = np.where(sym == 0, 1, sym)
    sym = np.where(sym == -2, -1, sym)
    sym = np.where(sym == 2, 1, sym)
    return sym


def sym_to_bits(sym: np.ndarray) -> np.ndarray:
    bits = np.empty(2 * len(sym), dtype=np.uint8)
    for s, (b0, b1) in SYM_TO_BITS.items():
        mask = sym == s
        bits[0::2][mask] = b0
        bits[1::2][mask] = b1
    return bits


def _burst_dibits(y, sr, cfg):
    """Спільний крок для обох режимів: для кожного burst'а - свіжий таймінг,
    диференціальна фаза. Повертає список (start_sample, d) по кожному
    успішно обробленому burst'у, у порядку появи."""
    out = []
    for s, e in sr.final:
        tau = symbols.estimate_timing(y[s:e], cfg.front.sps)
        sym_iq = symbols.sample_symbols(y, s, e, tau, cfg.front, cfg.timing)
        if len(sym_iq) < 3:
            continue
        d = sym_iq[1:] * np.conj(sym_iq[:-1])
        d = d / (np.abs(d) + 1e-12)
        out.append((s, d))
    return out


def export_true_time(xw: np.ndarray, cfg: PipelineConfig, rng: np.random.Generator):
    """TRUE-TIME (аналог .bin3): burst на справжній позиції в бітовому часі,
    проміжки - випадкові біти. Повертає (bits_plus, bits_minus, n_ok, n_total)."""
    y = front_end.matched_filter(xw, cfg.front)
    sr = burst_search.search_bursts(y, cfg.search)
    bursts = _burst_dibits(y, sr, cfg)

    n_samples = len(xw)
    total_bits = int(round(n_samples / cfg.front.work_fs_hz * 2 * cfg.front.symbol_rate_hz))
    out_plus = rng.integers(0, 2, total_bits, dtype=np.uint8)
    out_minus = rng.integers(0, 2, total_bits, dtype=np.uint8)

    for s, d in bursts:
        bit_pos = int(round(s / cfg.front.work_fs_hz * 2 * cfg.front.symbol_rate_hz))
        bp = sym_to_bits(phase_to_sym(d, +1))
        bm = sym_to_bits(phase_to_sym(d, -1))
        end = min(bit_pos + len(bp), total_bits)
        if end <= bit_pos:
            continue
        out_plus[bit_pos:end] = bp[:end - bit_pos]
        out_minus[bit_pos:end] = bm[:end - bit_pos]

    return out_plus, out_minus, len(bursts), len(sr.final)


def export_sequential(xw: np.ndarray, cfg: PipelineConfig):
    """SEQUENTIAL (аналог .bin2): burst'и підряд, кожен доповнений нулями до
    кратності SLOT_BITS, реальний проміжок часу між ними НЕ відтворюється.
    Повертає (bits_plus, bits_minus, n_ok, n_total)."""
    y = front_end.matched_filter(xw, cfg.front)
    sr = burst_search.search_bursts(y, cfg.search)
    bursts = _burst_dibits(y, sr, cfg)

    parts_plus, parts_minus = [], []
    for s, d in bursts:
        bp = sym_to_bits(phase_to_sym(d, +1))
        bm = sym_to_bits(phase_to_sym(d, -1))
        pad = (-len(bp)) % SLOT_BITS
        if pad:
            bp = np.concatenate([bp, np.zeros(pad, dtype=np.uint8)])
            bm = np.concatenate([bm, np.zeros(pad, dtype=np.uint8)])
        parts_plus.append(bp)
        parts_minus.append(bm)

    out_plus = np.concatenate(parts_plus) if parts_plus else np.empty(0, dtype=np.uint8)
    out_minus = np.concatenate(parts_minus) if parts_minus else np.empty(0, dtype=np.uint8)
    return out_plus, out_minus, len(bursts), len(sr.final)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Prepares .bits files for tetra-rx, both TRUE-TIME (true.*) and "
                   "SEQUENTIAL (seq.*) burst placement, both phase signs (plus/minus).")
    ap.add_argument("infile")
    ap.add_argument("--fs", type=float, help="sample rate for raw .cs16")
    ap.add_argument("-o", "--out", metavar="STEM")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed for TRUE-TIME gaps")
    a = ap.parse_args(argv)

    cfg = PipelineConfig()
    fs0, n_in = probe_input(a.infile, a.fs)
    print(f"Input: {n_in/fs0:.1f} s, {n_in/1e6:.2f} M samples @ {fs0:.0f} Hz")

    fs, x = load_iq(a.infile, a.fs)
    xw = front_end.to_work_rate(x, fs, cfg.front)
    rng = np.random.default_rng(a.seed)

    tp, tm, n_ok, n_total = export_true_time(xw, cfg, rng)
    print(f"bursts found: {n_total}, successfully processed: {n_ok}")
    sp, sm, _, _ = export_sequential(xw, cfg)

    stem = a.out or os.path.splitext(a.infile)[0]
    outputs = (("true.plus", tp), ("true.minus", tm), ("seq.plus", sp), ("seq.minus", sm))
    for suffix, bits in outputs:
        path = f"{stem}.{suffix}.bits"
        bits.tofile(path)
        print(f"-> {path}  ({len(bits)} bits, {os.path.getsize(path)} B)")
    print("\nTRUE-TIME (true.*) confirmed working on real tetra-rx (CRC OK, FN tracking).")
    print("SEQUENTIAL (seq.*) is untested - try it for comparison.")
    print("Within each, check both plus/minus; plus was already confirmed correct for true.*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
