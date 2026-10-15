"""
Етап 0 (вхід) і етап E (вихід).
  probe_input()  файл -> (fs, n_samples), БЕЗ читання даних (memmap)
  load_iq()      файл -> (fs, complex64 IQ)   WAV int16 2ch або raw .cs16 (+fs)
  write_bursts() burst'и -> текстовий файл
  write_bits_bin() біти burst'ів підряд -> бінарний файл (2 біти на символ)
  write_bits_bin_aligned() те саме, але з доповненням нулями до межі слота (510 біт)
                          перед кожним burst'ом - для перегляду в bit viewer'і з рамкою
  write_bits_bin_phase_aligned() точніше: burst доповнюється нулями З ОБОХ боків
                          на його СПРАВЖНЮ фазу всередині слота (з start_sample),
                          а не просто зшивається після попереднього - для bit viewer'а
Формат рядка: t_start_s start_sample n_samples n_bits n_sym snr_db freq_hz coherence phase_rms_deg flags bits
(start_sample, n_samples: позиція і довжина burst'а в СИРИХ семплах, work_fs_hz Гц -
 ті самі індекси, що й у вхідному масиві ДО matched filter, для дослідження сирого запису)
(snr_db: часовий метод, на сирому масиві до matched filter; '-' якщо недоступно)
(flags: '-' або LOWCOH,NEARLIM)
"""
import numpy as np
from scipy.io import wavfile

from pattern_check import KNOWN_FIELDS, summarize_recording


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


REPORT_COLUMNS = ("t_start_s", "start_sample", "n_samples", "n_bits", "n_sym", "snr_db",
                  "freq_hz", "coherence", "phase_rms_deg", "flags", "bits")


def write_bursts(path: str, bursts) -> None:
    """Рядки з '#' - заголовок (патерни з лічильниками, кількість і статистика burst'ів, назви колонок); колонки
    вирівняні за шириною, тож біти всіх burst'ів починаються з однієї позиції."""
    rows = []
    for b in bursts:
        snr_s = f"{b.snr_db:+.2f}" if b.snr_db is not None else "-"
        rows.append((f"{b.t_start_s:.6f}", str(b.start), str(b.end - b.start), str(len(b.bits)), str(b.n_sym),
                     snr_s, f"{b.freq_hz:+.1f}", f"{b.coherence:.3f}", f"{b.phase_rms_deg:.1f}",
                     str(b.flags), "".join(map(str, b.bits))))
    widths = [max([len(name), *(len(r[i]) for r in rows)]) for i, name in enumerate(REPORT_COLUMNS)]
    widths[0] += 2                      # місце під "# " у рядку-заголовку колонок

    def fmt(cells):
        return " ".join(c.rjust(w) for c, w in zip(cells[:-1], widths)) + " " + cells[-1]

    summ = summarize_recording(bursts)
    pat_w = max(len(p) for p, _, st in KNOWN_FIELDS.values() if st == "ok")
    with open(path, "w") as f:
        f.write("# known TETRA sequences (bits 0/1, ETSI EN 300 392-2, 9.4.4.3):".ljust(14 + pat_w + 2)
                + f"{'exact':>8} {f'err<={summ.threshold:.0%}':>10} {'total':>7}\n")
        for name, (pattern, _, status) in KNOWN_FIELDS.items():
            if status == "ok":
                st = summ.per_field[name]
                f.write(f"#   {name:<5}({len(pattern):>2}) {pattern:<{pat_w}}  "
                        f"{st.n_exact:>8} {st.n_within_threshold:>10} {st.n_found:>7}\n")
        f.write("#\n")
        f.write(f"# bursts: {len(rows)}\n")
        stats = (("SNR", [b.snr_db for b in bursts if b.snr_db is not None], ".2f"),
                 ("Coher", [b.coherence for b in bursts], ".3f"),
                 ("Dur", [b.end - b.start for b in bursts], ".0f"),
                 ("BitLn", [len(b.bits) for b in bursts], ".0f"))
        for label, vals, prec in stats:
            f.write(f"# {label + ':':<7}" + (f"min={min(vals):{prec}} mean={np.mean(vals):{prec}} "
                    f"max={max(vals):{prec}} std={np.std(vals):{prec}}" if vals else "-") + "\n")
        f.write("# Dur = n_samples (сирі семпли), BitLn = n_bits\n#\n")
        f.write("#" + fmt(REPORT_COLUMNS)[1:] + "\n")
        for r in rows:
            f.write(fmt(r) + "\n")


def write_bits_bin(path: str, bursts, bitorder: str = "little") -> None:
    """Біти всіх burst'ів суцільним потоком; bitorder="little" - перший біт у
    молодшому розряді байта, "big" - у старшому.
    Нулі лише в кінці файлу, до кратності 8 біт; меж burst'ів немає."""
    parts = [np.asarray(b.bits, dtype=np.uint8) for b in bursts]
    stream = np.concatenate(parts) if parts else np.empty(0, dtype=np.uint8)
    with open(path, "wb") as f:
        f.write(np.packbits(stream, bitorder=bitorder).tobytes())


def write_bits_bin_phase_aligned(path: str, bursts, slot_bits: int,
                                 sample_rate_hz: float, symbol_rate_hz: float,
                                 bitorder: str = "little") -> None:
    """Те саме призначення, що write_bits_bin_aligned, але ТОЧНІШЕ: кожен burst
    доповнюється нулями З ОБОХ боків так, щоб його перший реальний біт став саме
    на ту позицію всередині 510-бітного періоду, де він БУВ у сирому записі -
    обчислено з b.start (позиція в сирих семплах, work_fs_hz), а не просто
    "зшито" після попереднього burst'а (як у write_bits_bin_aligned/.bin2, де
    справжня фаза burst'а всередині слота губиться).

    Точка відліку фази 0: відлік №0 вхідного файлу. Це ДОВІЛЬНИЙ, але
    послідовний і відтворюваний вибір - "справжню" прив'язку до фази передавача
    з самого запису визначити не можна, тож беремо початок файлу як умовний 0.

    burst_duration_s виводиться з symbol_rate_hz і slot_bits (2 біти/символ),
    а не захардкожена - єдине джерело істини, узгоджене з rest проєкту."""
    burst_duration_s = slot_bits / 2.0 / symbol_rate_hz   # ETSI: 510 біт = 255 симв. = 14.167 мс
    parts = []
    for b in bursts:
        bits = np.asarray(b.bits, dtype=np.uint8)
        phase = int(round(b.start / sample_rate_hz / burst_duration_s * slot_bits)) % slot_bits
        total = -(-(phase + len(bits)) // slot_bits) * slot_bits   # округлення вгору до кратності
        chunk = np.zeros(total, dtype=np.uint8)
        chunk[phase:phase + len(bits)] = bits
        parts.append(chunk)
    stream = np.concatenate(parts) if parts else np.empty(0, dtype=np.uint8)
    with open(path, "wb") as f:
        f.write(np.packbits(stream, bitorder=bitorder).tobytes())


def write_bits_bin_aligned(path: str, bursts, slot_bits: int,
                           bitorder: str = "little") -> None:
    """Те саме, що write_bits_bin, але КОЖЕН burst доповнюється нулями до кратності
    slot_bits ПЕРЕД конкатенацією - щоб кожен burst у файлі починався рівно на межі
    510-бітного (ETSI) слота. Призначення: вирівняний перегляд у bit viewer'і з рамкою
    по slot_bits (наприклад width=510 у Hobbits) - без цього вирівнювання структура
    "пливе" вже з другого burst'а, бо довжини burst'ів (~470-480 біт) не кратні 510.
    Семантично ІНШИЙ файл за write_bits_bin (має зайві нулі-доповнювачі між burst'ами),
    не заміна йому - для демодульованих бітів як є лишайте write_bits_bin/.bin."""
    parts = []
    for b in bursts:
        bits = np.asarray(b.bits, dtype=np.uint8)
        pad = (-len(bits)) % slot_bits
        if pad:
            bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
        parts.append(bits)
    stream = np.concatenate(parts) if parts else np.empty(0, dtype=np.uint8)
    with open(path, "wb") as f:
        f.write(np.packbits(stream, bitorder=bitorder).tobytes())
