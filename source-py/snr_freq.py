"""
SNR burst'а в ЧАСТОТНОМУ домені. Для кожного burst'а:
  1. вирізати сирі (до matched filter) семпли burst'а;
  2. розбити на вікна фіксованої довжини (частотна роздільність = 1/win_s),
     з усередненням спектра по вікнах (periodogram averaging, Welch-подібно,
     без перекриття - просто);
  3. зона сигналу: |f| < bw/2, де bw = symbol_rate*(1+rolloff) (та сама величина,
     що й check_spectrum.spec_bw99_hz, тут береться теоретично, не вимірюється);
  4. P_signal_zone = середня потужність бінів у зоні; P_noise = медіана потужності
     бінів ПОЗА зоною (у межах семплрейту, за винятком DC +-2 біни);
  5. SNR = 10*log10((P_signal_zone - P_noise_density*bins_in_zone... )) -- спрощено:
     SNR = 10*log10(mean_in_zone / median_out_of_zone).
Рахується НА СИРОМУ масиві (до matched filter), узгоджено з часовим методом.
"""
from typing import List, Optional, Tuple

import numpy as np

Segments = List[Tuple[int, int]]


def burst_freq_snr_db(raw: np.ndarray, burst: Tuple[int, int], sample_rate_hz: float,
                      bandwidth_hz: float, win_s: float = 100e-6,
                      dc_guard_bins: int = 2) -> Optional[dict]:
    """raw: СИРІ (до matched filter) семпли ВСЬОГО масиву. burst: (start,end) у ньому.
    win_s: тривалість вікна FFT (визначає частотну роздільність = 1/win_s).
    Повертає dict з snr_db, n_windows, freq_resolution_hz, або None якщо замало даних."""
    s, e = burst
    seg = raw[s:e]
    win = max(8, int(round(win_s * sample_rate_hz)))
    n_win = len(seg) // win
    if n_win < 1:
        return None
    blocks = seg[:n_win * win].reshape(n_win, win)
    window_fn = np.hanning(win).astype(np.float64)
    F = np.fft.fft(blocks * window_fn, axis=1)
    P = (F.real ** 2 + F.imag ** 2).mean(axis=0)     # усереднений периодограма по вікнах
    P = np.fft.fftshift(P)
    freqs = np.fft.fftshift(np.fft.fftfreq(win, 1 / sample_rate_hz))

    zone = np.abs(freqs) < bandwidth_hz / 2
    dc = np.abs(freqs) < dc_guard_bins * (sample_rate_hz / win)
    out_zone = (~zone) & (~dc)

    if zone.sum() < 2 or out_zone.sum() < 2:
        return None
    p_in = float(P[zone].mean())
    p_out = float(np.median(P[out_zone]))
    if p_out <= 0 or p_in <= p_out:
        return None
    return dict(snr_db=float(10 * np.log10(p_in / p_out)),
               n_windows=n_win, freq_resolution_hz=sample_rate_hz / win,
               bins_in_zone=int(zone.sum()), bins_out_zone=int(out_zone.sum()))
