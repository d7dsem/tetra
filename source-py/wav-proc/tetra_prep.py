import argparse
import math
import sys
import traceback
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import firwin, lfilter, resample_poly

# ---- Параметри (override: змінюються тут, CLI-прапорців немає) ----
DEFAULT_OUT_RATE_HZ = 25_000.0   # TETRA DMO
CHUNK_SIZE = 2_000_000           # вхідних відліків на ітерацію
MAX_RATE_DENOM = 1_000_000       # межа знаменника при розкладі out_rate у дріб
FIR_CUTOFF_FRAC = 1.0            # зріз як частка out_rate/2 (обидва режими)
# Цілочисельна децимація: lfilter + прорідження
FIR_NUMTAPS = 101                # довжина фільтра; більше -> крутіший зріз, повільніше
FIR_WINDOW = "hamming"           # вікно firwin
# Раціональний ресемплінг (up/down): поліфазний фільтр на частоті ×up
POLY_HALF_LEN_FACTOR = 10        # півдовжина фільтра = factor * max(up, down) відліків
POLY_WINDOW = ("kaiser", 5.0)    # як у scipy за замовчуванням
INT16_FULL_SCALE = 32768.0


def resolve_shift_hz(fc: float | None, sign_abs: float | None, sign_rel: float | None) -> float:
    """Зсув (Гц), що переносить центр сигналу в 0. None-параметри -> без зсуву."""
    if sign_abs is not None and sign_rel is not None:
        raise ValueError("--sign-abs і --sign-rel взаємовиключні")
    if sign_rel is not None:
        return sign_rel
    if sign_abs is not None:
        if fc is None:
            raise ValueError("--sign-abs потребує --fc (центральна частота захоплення)")
        return sign_abs - fc
    return 0.0


def load_iq(data_raw, lo: int, hi: int, shift_hz: float, fs_in: int) -> np.ndarray:
    """Відліки [lo, hi) як комплексний сигнал із зсувом; фаза рахується від глобального індексу."""
    chunk = data_raw[lo:hi]
    iq = (chunk[:, 0].astype(np.float32) + 1j * chunk[:, 1].astype(np.float32)) / INT16_FULL_SCALE
    if shift_hz != 0.0:
        n = np.arange(lo, hi, dtype=np.float64)
        iq = iq * np.exp(-2j * np.pi * shift_hz / fs_in * n)
    return iq


def write_int16(w, iq: np.ndarray):
    out = np.empty((iq.shape[0], 2), dtype=np.int16)
    out[:, 0] = np.clip(np.rint(iq.real * INT16_FULL_SCALE), -32768, 32767)
    out[:, 1] = np.clip(np.rint(iq.imag * INT16_FULL_SCALE), -32768, 32767)
    w.writeframes(out.tobytes())


def run_decimate(data_raw, w, fs_in: int, fs_out: int, decim: int, shift_hz: float):
    total = data_raw.shape[0]
    taps = firwin(FIR_NUMTAPS, FIR_CUTOFF_FRAC * fs_out / 2, window=FIR_WINDOW, fs=fs_in)
    state = np.zeros(len(taps) - 1, dtype=np.complex128)

    for start in range(0, total, CHUNK_SIZE):
        iq = load_iq(data_raw, start, min(start + CHUNK_SIZE, total), shift_hz, fs_in)
        iq, state = lfilter(taps, 1.0, iq, zi=state)
        # перший відлік, кратний decim у глобальній нумерації
        write_int16(w, iq[(-start) % decim::decim])


def run_rational(data_raw, w, fs_in: int, up: int, down: int, shift_hz: float):
    """Чанки з перекриттям: край чанка обробляється з запасом pad, який потім відкидається."""
    total = data_raw.shape[0]
    half_len = POLY_HALF_LEN_FACTOR * max(up, down)
    h = firwin(2 * half_len + 1, FIR_CUTOFF_FRAC / max(up, down), window=POLY_WINDOW)

    # pad і розмір чанка кратні down -> фаза виходу збігається між чанками
    pad = math.ceil(math.ceil(half_len / up) / down) * down
    step = max(CHUNK_SIZE // down, 1) * down

    for start in range(0, total, step):
        end = min(start + step, total)
        lo, hi = max(0, start - pad), min(total, end + pad)
        iq = load_iq(data_raw, lo, hi, shift_hz, fs_in)
        y = resample_poly(iq, up, down, window=h)
        first = (start - lo) * up // down
        count = -(-(end - start) * up // down)
        write_int16(w, y[first:first + count])


def process_wav(fp: str, shift_hz: float, out_rate: float, output_fp: str):
    fs_in, data_raw = wavfile.read(fp, mmap=True)

    if data_raw.ndim != 2 or data_raw.shape[1] != 2:
        raise ValueError("Файл має бути стерео (Channel 0 = I, Channel 1 = Q)")
    if data_raw.dtype != np.int16:
        raise ValueError(f"Очікується int16 WAV, а не {data_raw.dtype}")
    if out_rate <= 0 or out_rate > fs_in:
        raise ValueError(f"Вихідний rate ({out_rate} Hz) має бути в (0, {fs_in}] Hz")
    if abs(shift_hz) >= fs_in / 2:
        raise ValueError(f"Зсув {shift_hz} Hz поза межами ±{fs_in / 2} Hz")

    ratio = Fraction(out_rate).limit_denominator(MAX_RATE_DENOM) / fs_in
    up, down = ratio.numerator, ratio.denominator
    if (fs_in * up) % down != 0:
        raise ValueError(f"Вихідний rate {out_rate} Hz не дає цілої частоти для WAV (ratio={up}/{down})")
    fs_out = fs_in * up // down

    total = data_raw.shape[0]
    mode = f"децимація {down}" if up == 1 else f"ресемплінг {up}/{down}"
    print(f"Вхід: {fs_in} Hz, {total} відліків | Вихід: {fs_out} Hz ({mode}) | зсув={shift_hz} Hz")

    # wave сам виправляє заголовок при close()
    with wave.open(output_fp, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(fs_out)
        if up == 1:
            run_decimate(data_raw, w, fs_in, fs_out, down, shift_hz)
        else:
            run_rational(data_raw, w, fs_in, up, down, shift_hz)

    print(f"Готово! Збережено у {output_fp}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Блоковий зсув частоти + ресемплінг великих IQ WAV (int16 -> int16 WAV).")
    parser.add_argument("path", type=str, help="Шлях до вхідного WAV файлу")
    parser.add_argument("--fc", type=float, default=None, help="Центральна частота захоплення, Гц (для --sign-abs)")
    parser.add_argument("--sign-abs", type=float, default=None, help="Абсолютна частота центру сигналу, Гц")
    parser.add_argument("--sign-rel", type=float, default=None, help="Частота центру сигналу відносно центру захоплення, Гц")
    parser.add_argument("--out-rate", type=float, default=DEFAULT_OUT_RATE_HZ, help="Вихідна частота дискретизації, Гц")
    parser.add_argument("-o", "--output", type=str, default=None, help="Вихідний WAV файл")

    try:
        args = parser.parse_args()
        fout = args.output
        if fout is None:
            fout = f"{Path(args.path).stem}_rsmp_{int(args.out_rate)}.wav"
        shift = resolve_shift_hz(args.fc, args.sign_abs, args.sign_rel)
        process_wav(args.path, shift, args.out_rate, fout)
    except Exception as e:
        print(f"[EXCEPTION] {e}")
        traceback.print_exc()
        sys.exit(1)
