"""
Окрема точка входу: готує IQ-запис у форматі, придатному для канального
декодера osmo-tetra (tetra-rx).

ПРИНЦИПОВА ВІДМІННІСТЬ від tetra_demod.py: tetra-rx сам шукає межі burst'ів
кореляцією з тренувальними послідовностями у БЕЗПЕРЕРВНОМУ потоці бітів. Тому
тут демодуляція йде по ВСЬОМУ файлу суцільно, без пошуку/нарізки burst'ів
(burst_search.py тут НЕ використовується).

Формат виходу - з реального коду float_to_bits.c (osmo-tetra), не з опису:
  1 байт = 1 біт, сире значення 0 або 1 (uint8), НЕ ASCII '0'/'1', НЕ запаковано.
  Таблиця символ -> дібіти (EXACT з їхнього коду):
    sym=-3 -> (1,1)   sym=-1 -> (1,0)   sym=+1 -> (0,0)   sym=+3 -> (0,1)
  Прийнято (НЕ підтверджено на реальному tetra-rx): sym = round(phase_deg/45),
  тобто ±45°/±135° -> {-1,+1}/{-3,+3} - ті самі 4 точки π/4-DQPSK.

НЕВИЗНАЧЕНІСТЬ ЗНАКУ ФАЗИ: інверсія Q, буквальна перестановка I/Q і спектральне
дзеркалення дають ОДНАКОВИЙ ефект на диференціальну фазу (перевірено алгебраїчно,
зберегти-sign.py чи git log) - це ОДНА вісь невизначеності, не кілька. Тому
пишемо ОБИДВА варіанти (sign=+1, sign=-1), а не гадаємо.

БЕЗПЕРЕРВНА символьна синхронізація: timing-фаза оцінюється ОДИН раз (Oerder-Meyr
по всьому сигналу), далі семпли беруться з цією фіксованою фазою по всьому файлу.
Дрейф таймінгу (напр. похибка ppm генератора) тут НЕ компенсується - спрощення
для першої версії, позначено явно, не прихована.
"""
import argparse

import numpy as np
from scipy.signal import resample_poly

import front_end
from config import PipelineConfig
from io_stage import load_iq, probe_input

# sym {-3,-1,1,3} -> (bit0,bit1), EXACT з float_to_bits.c (sym_int2bits)
SYM_TO_BITS = {-3: (1, 1), -1: (1, 0), 1: (0, 0), 3: (0, 1)}


def continuous_symbols(y: np.ndarray, sps: int, fine_upsample: int = 4) -> np.ndarray:
    """Timing-фаза оцінюється ОДНИМ Oerder-Meyr по всьому сигналу (чиста статистика
    power(y) по фазах n mod sps, не потребує величезного комплексного масиву),
    далі один прохід resample_poly + вибірка з цією фіксованою фазою по всьому y."""
    n = len(y)
    p = y.real.astype(np.float64) ** 2 + y.imag.astype(np.float64) ** 2
    w = np.exp(-2j * np.pi * np.arange(sps) / sps)
    m = n // sps * sps
    c = p[:m].reshape(-1, sps).sum(axis=0) @ w
    tau = (-np.angle(c) * sps / (2 * np.pi)) % sps

    fine = resample_poly(y, fine_upsample, 1)
    per_sym = sps * fine_upsample
    start = int(round(tau * fine_upsample)) % per_sym
    return fine[start::per_sym]


def phase_to_sym(d: np.ndarray, sign: int) -> np.ndarray:
    """d: диференціальні фазори (одиничної довжини). sign=+1 або -1 - перемикач
    невизначеності знаку, див. докстрінг модуля."""
    deg = sign * np.degrees(np.angle(d))
    sym = np.round(deg / 45.0).astype(int)
    sym = np.clip(sym, -3, 3)
    sym = np.where(sym == 0, 1, sym)          # округлення на межі, підстраховка
    sym = np.where(sym == -2, -1, sym)
    sym = np.where(sym == 2, 1, sym)
    return sym


def sym_to_unpacked_bits(sym: np.ndarray) -> np.ndarray:
    bits = np.empty(2 * len(sym), dtype=np.uint8)
    for s, (b0, b1) in SYM_TO_BITS.items():
        mask = sym == s
        bits[0::2][mask] = b0
        bits[1::2][mask] = b1
    return bits


def export(xw: np.ndarray, cfg: PipelineConfig):
    """Повертає (bits_sign_plus, bits_sign_minus) - обидва варіанти знаку,
    кожен np.uint8 масив 0/1, готовий для запису 1-байт-на-біт."""
    y = front_end.matched_filter(xw, cfg.front)
    sym = continuous_symbols(y, cfg.front.sps)
    d = sym[1:] * np.conj(sym[:-1])
    d = d / (np.abs(d) + 1e-12)
    plus = sym_to_unpacked_bits(phase_to_sym(d, +1))
    minus = sym_to_unpacked_bits(phase_to_sym(d, -1))
    return plus, minus


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Готує .bits-файл(и) для tetra-rx (osmo-tetra), 2 варіанти знаку фази.")
    ap.add_argument("infile")
    ap.add_argument("--fs", type=float, help="sample rate для raw .cs16")
    ap.add_argument("-o", "--out", metavar="STEM",
                    help="stem виходу (STEM.plus.bits, STEM.minus.bits); "
                         "за замовчуванням ім'я входу без розширення")
    a = ap.parse_args(argv)

    cfg = PipelineConfig()
    fs0, n_in = probe_input(a.infile, a.fs)
    print(f"Вхід: {n_in/fs0:.1f} с, {n_in/1e6:.2f} М відліків @ {fs0:.0f} Гц")

    fs, x = load_iq(a.infile, a.fs)
    xw = front_end.to_work_rate(x, fs, cfg.front)
    plus, minus = export(xw, cfg)

    import os
    stem = a.out or os.path.splitext(a.infile)[0]
    for suffix, bits in (("plus", plus), ("minus", minus)):
        path = f"{stem}.{suffix}.bits"
        bits.tofile(path)
        print(f"-> {path}  ({len(bits)} біт, {os.path.getsize(path)} B)")
    print("\nПеревірте ОБИДВА варіанти на tetra-rx; лишіть той, що дає захват.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
