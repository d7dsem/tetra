"""
Оцінка якості виявлення фіксованих бітових послідовностей TETRA в демодульованих
бітах burst'ів.

ЗАСТЕРЕЖЕННЯ: самі бітові рядки нижче ВІДНОВЛЕНІ ЕМПІРИЧНО зі статистичного
пошуку повторюваних послідовностей у цьому конкретному записі (sms.wav, див.
обговорення), а НЕ звірені проти повного тексту ETSI EN 300 392-2 (був
доступний лише зміст документа). Довжини й призначення (FCF/STS/NTS) та
позиції узгоджуються зі змістом стандарту, самі значення бітів - ні.

Позиції (у бітах від початку burst'а/слота, слот = 510 біт = 14.167 мс):
  FCF (Frequency correction field,        80 біт) ~ позиція 18
  STS (Synchronisation training sequence, 38 біт) ~ позиція 218
  NTS (Normal training sequence,          22 біт) ~ позиція 234

Burst може містити кілька злитих слотів (continuous transmission, без паузи
між ними - див. coarse_detect.py), тому пошук іде по кожному 510-бітному
кроку всередині burst'а, з допуском на зсув старту (align_window).
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

SLOT_BITS = 510

# (назва, бітовий рядок, позиція в слоті) - емпіричні, див. застереження вище
KNOWN_FIELDS: Dict[str, Tuple[str, int]] = {
    "FCF": ("1" * 8 + "0" * 64 + "1" * 8, 18),
    "STS": ("11000001100111001110100111000001100111", 218),
    "NTS": ("1101000011101001110100", 234),
}

RANDOM_ERR_RATE = 0.5    # очікувана частка помилок на випадкових бітах (контрольний рівень)


@dataclass
class BurstPatternResult:
    best_field: Optional[str]      # назва поля з найменшою часткою помилок, або None
    err_rate: Optional[float]      # частка помилок на цьому полі (0..1)
    detected: bool                 # err_rate нижче порога (явно не випадкові біти)


def _bits_to_str(bits) -> str:
    return "".join(str(int(b)) for b in bits)


def best_match_for_field(bits_str: str, pattern: str, base_pos: int,
                         align_window: int = 12) -> Optional[float]:
    """Шукає pattern у bits_str по кожному 510-бітному кроку (слоту) з допуском
    зсуву ±align_window біт. Повертає мінімальну частку помилок, або None,
    якщо жодного повного вікна перевірити не вдалось (burst надто короткий)."""
    n = len(bits_str); L = len(pattern)
    best: Optional[int] = None; checked = 0
    for k in range((n - base_pos) // SLOT_BITS + 1):
        for sh in range(-align_window, align_window + 1):
            p = base_pos + SLOT_BITS * k + sh
            if p < 0 or p + L > n:
                continue
            err = sum(a != c for a, c in zip(bits_str[p:p + L], pattern))
            checked += 1
            if best is None or err < best:
                best = err
    if best is None:
        return None
    return best / len(pattern)


def check_burst_patterns(bits, detect_threshold: float = 0.2) -> BurstPatternResult:
    """detect_threshold: частка помилок, нижче якої вважаємо поле реально знайденим
    (0.2 істотно нижче за випадкові ~0.5, з запасом на шумові помилки символів)."""
    s = _bits_to_str(bits)
    best_name: Optional[str] = None; best_err: Optional[float] = None
    for name, (pattern, pos) in KNOWN_FIELDS.items():
        err = best_match_for_field(s, pattern, pos)
        if err is not None and (best_err is None or err < best_err):
            best_name, best_err = name, err
    detected = best_err is not None and best_err <= detect_threshold
    return BurstPatternResult(best_field=best_name if detected else None,
                              err_rate=best_err, detected=detected)


@dataclass
class RecordingPatternSummary:
    n_bursts: int
    n_symbols_total: int
    n_detected: int
    detect_fraction: float
    median_err_rate_detected: Optional[float]
    per_field_counts: Dict[str, int]


def summarize_recording(bursts) -> RecordingPatternSummary:
    """bursts: список об'єктів з .bits і .n_sym (BurstResult-сумісні)."""
    n_bursts = len(bursts)
    n_symbols_total = sum(b.n_sym for b in bursts)
    results = [check_burst_patterns(b.bits) for b in bursts]
    detected = [r for r in results if r.detected]
    per_field: Dict[str, int] = {}
    for r in detected:
        per_field[r.best_field] = per_field.get(r.best_field, 0) + 1
    err_rates = [r.err_rate for r in detected if r.err_rate is not None]
    return RecordingPatternSummary(
        n_bursts=n_bursts, n_symbols_total=n_symbols_total,
        n_detected=len(detected),
        detect_fraction=(len(detected) / n_bursts) if n_bursts else 0.0,
        median_err_rate_detected=float(np.median(err_rates)) if err_rates else None,
        per_field_counts=per_field,
    )
