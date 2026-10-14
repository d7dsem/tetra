"""
Етап 0 (вхід) і етап E (вихід).
  probe_input()  файл -> (fs, n_samples), БЕЗ читання даних (memmap)
  load_iq()      файл -> (fs, complex64 IQ)   WAV int16 2ch або raw .cs16 (+fs)
  write_bursts() burst'и -> текстовий файл
  write_bits_bin() біти burst'ів підряд -> бінарний файл (2 біти на символ)
Формат рядка: t_start_s n_sym freq_hz coherence phase_rms_deg flags bits
(flags: '-' або LOWCOH,NEARLIM)
"""
import numpy as np
from scipy.io import wavfile


def _open_int16_iq(path: str, fs_hint=None):
    """Повертає (fs, memmap int16 форми (n, 2)); дані з диска не копіюються."""
    if path.lower().endswith(".wav"):
        fs, d = wavfile.read(path, mmap=True)
        if d.dtype != np.int16 or d.ndim != 2 or d.shape[1] != 2:
            raise ValueError("очікується WAV int16, 2 канали (I,Q)")
        return float(fs), d
    if not fs_hint:
        raise ValueError("для raw-файлу потрібен --fs")
    raw = np.memmap(path, dtype=np.int16, mode="r")
    return float(fs_hint), raw[: len(raw) // 2 * 2].reshape(-1, 2)


def probe_input(path: str, fs_hint=None):
    fs, d = _open_int16_iq(path, fs_hint)
    return fs, len(d)


def load_iq(path: str, fs_hint=None):
    """int16 -> complex64 одним проходом у заздалегідь виділений масив
    (без float32-копій I і Q та проміжного complex)."""
    fs, d = _open_int16_iq(path, fs_hint)
    x = np.empty(len(d), dtype=np.complex64)
    k = np.float32(1.0 / 32768.0)
    np.multiply(d[:, 0], k, out=x.real, dtype=np.float32)
    np.multiply(d[:, 1], k, out=x.imag, dtype=np.float32)
    return fs, x


def write_bursts(path: str, bursts) -> None:
    with open(path, "w") as f:
        for b in bursts:
            f.write(f"{b.t_start_s:.6f} {b.n_sym} {b.freq_hz:+.1f} "
                    f"{b.coherence:.3f} {b.phase_rms_deg:.1f} {b.flags} "
                    f"{''.join(map(str, b.bits))}\n")


def write_bits_bin(path: str, bursts) -> None:
    """Біти всіх burst'ів суцільним потоком; перший біт у молодшому розряді байта.
    Нулі лише в кінці файлу, до кратності 8 біт; меж burst'ів немає."""
    parts = [np.asarray(b.bits, dtype=np.uint8) for b in bursts]
    stream = np.concatenate(parts) if parts else np.empty(0, dtype=np.uint8)
    with open(path, "wb") as f:
        f.write(np.packbits(stream, bitorder="little").tobytes())
