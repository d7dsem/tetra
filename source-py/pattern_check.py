"""
Оцінка якості виявлення фіксованих бітових послідовностей TETRA в демодульованих
бітах burst'ів. Статистика рахується ОКРЕМО по кожному полю стандарту
(ETSI EN 300 392-2 V3.8.1, розділ 9.4.4.3 "Burst fields", формули 9.1-9.13) -
скільки burst'ів у файлі містять саме це поле, незалежно від інших.

=====================================================================
ТЮНІНГ: константи й статус полів
=====================================================================
ДЖЕРЕЛО: ETSI EN 300 392-2 V3.8.1 (2016-08), наданий користувачем PDF,
звірено напряму з текстом розділу 9.4.4.3 (формули 9.1-9.13).

СТАТУС ПОЛІВ:
  FCF   - зі стандарту (формули 9.1-9.3). Збігається з нашим попереднім
          емпіричним значенням (з аналізу реальних записів) ПОБІТОВО.
  NTS1  - зі стандарту (формула 9.4, normal training sequence 1, n1..n22).
          Збігається з нашим попереднім емпіричним значенням ПОБІТОВО.
  NTS2  - зі стандарту (формула 9.5, normal training sequence 2, p1..p22).
  NTS3  - зі стандарту (формула 9.6, normal training sequence 3, q1..q22).
          Використовується в start/stop burst та discontinuous sync burst,
          НЕ в normal uplink/downlink burst - додано понад початкові 7,
          бо явно присутнє в тих самих даних (sync-burst'и).
  STS   - зі стандарту (формула 9.11, synchronization training sequence,
          y1..y38). Збігається з нашим попереднім емпіричним значенням
          ПОБІТОВО, і з незалежним стороннім джерелом (gophertrunk.org).
  ETS   - зі стандарту (формула 9.9, extended training sequence для
          π/4-DQPSK, x1..x30; використовується в uplink control burst).
  TAIL  - зі стандарту (формула 9.12, tail bits, t1..t4 = 1,1,0,0).
          УВАГА: лише 4 біти - ймовірність випадкового збігу ~6% навіть
          на шумі, тож "знайдено TAIL" саме по собі малоінформативне;
          дивитись разом з іншими полями, не окремо.
  PHASE - PHASE ADJUSTMENT BITS НЕ Є фіксованою послідовністю (розділ
          9.4.4.3.6, формула 9.14): це 2 біти, що обчислюються ДИНАМІЧНО
          для кожного конкретного burst'а за формулою фазового балансу
          (залежать від вмісту решти burst'а). Пошук "фіксованого
          патерну" для цього поля структурно неможливий - це НЕ недолік
          наших даних, а властивість самого поля. Status="formula",
          не "stub": вписувати сюди нема чого навіть за наявності PDF.

Джерело PDF: наданий користувачем ETSI_EN_300_392-2.pdf (V3.8.1, 2016-08).
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

SLOT_BITS = 510              # довжина таймслота в бітах (ETSI, підтверджено: 510 = 255 симв.)
DETECT_THRESHOLD = 0.10      # базовий тюнінг-параметр: допустимий поріг помилок (10%)
ALIGN_WINDOW_BITS = 12       # допуск на зсув старту burst'а при пошуку поля, у бітах
MIN_RELIABLE_FIELD_BITS = 20 # поля коротші за це (зараз лише TAIL, 4 біти) НЕ враховуються
                              # у зведеному "хоч щось знайдено": на короткій послідовності
                              # випадковий збіг статистично ймовірний (перевірено тестом -
                              # на чисто випадкових бітах TAIL "знаходився" в усіх burst'ах).
                              # Власна статистика TAIL все одно виводиться окремо, не ховається.


def _seq(pairs_str: str) -> str:
    """Парсить рядок виду '1,1, 0,1, 0,0' (як у формулах стандарту) у бітовий рядок."""
    return "".join(x for x in pairs_str.replace(" ", "").split(",") if x != "")


# (назва -> (бітовий рядок АБО None, позиція в слоті, статус))
# позиції: FCF/STS/ETS - орієнтовні (за структурою sync/control burst, розділ 9.4.4.2);
#          NTS1/NTS2/NTS3 - орієнтовні (normal burst, позиція середини/країв слота).
KNOWN_FIELDS: Dict[str, Tuple[Optional[str], int, str]] = {
    "FCF":   (_seq("1,1,1,1,1,1,1,1") + "0" * 64 + _seq("1,1,1,1,1,1,1,1"), 18, "ok"),
    "NTS1":  (_seq("1,1, 0,1, 0,0, 0,0, 1,1, 1,0, 1,0, 0,1, 1,1, 0,1, 0,0"), 234, "ok"),
    "NTS2":  (_seq("0,1, 1,1, 1,0, 1,0, 0,1, 0,0, 0,0, 1,1, 0,1, 1,1, 1,0"), 234, "ok"),
    "NTS3":  (_seq("1,0, 1,1, 0,1, 1,1, 0,0, 0,0, 0,1, 1,0, 1,0, 1,1, 0,1"), 0, "ok"),
    "STS":   (_seq("1,1, 0,0, 0,0, 0,1, 1,0, 0,1, 1,1, 0,0, 1,1, 1,0, "
                   "1,0, 0,1, 1,1, 0,0, 0,0, 0,1, 1,0, 0,1, 1,1"), 218, "ok"),
    "ETS":   (_seq("1,0, 0,1, 1,1, 0,1, 0,0, 0,0, 1,1, 1,0, 1,0, 0,1, "
                   "1,1, 0,1, 0,0, 0,0, 1,1"), 18, "ok"),
    "TAIL":  (_seq("1, 1, 0, 0"), 0, "ok"),            # лише 4 біти, див. застереження в докстрінгу
    "PHASE": (None, 0, "formula"),                     # НЕ фіксована послідовність, див. докстрінг
}


def _bits_to_str(bits) -> str:
    return "".join(str(int(b)) for b in bits)


def best_match_for_field(bits_str: str, pattern: str, base_pos: int,
                         align_window: int = ALIGN_WINDOW_BITS) -> Optional[float]:
    """Шукає pattern у bits_str по кожному 510-бітному кроку (слоту) з допуском
    зсуву ±align_window біт. Повертає мінімальну частку помилок, або None,
    якщо жодного повного вікна перевірити не вдалось (burst надто короткий)."""
    n = len(bits_str); L = len(pattern)
    best: Optional[int] = None
    for k in range((n - base_pos) // SLOT_BITS + 1):
        for sh in range(-align_window, align_window + 1):
            p = base_pos + SLOT_BITS * k + sh
            if p < 0 or p + L > n:
                continue
            err = sum(a != c for a, c in zip(bits_str[p:p + L], pattern))
            if best is None or err < best:
                best = err
    return best / L if best is not None else None


# Типи burst'ів за навчальною послідовністю: назва -> позиція в burst'і (з KNOWN_FIELDS).
# NTS3 не враховується: позиція в KNOWN_FIELDS невизначена (0).
BURST_TYPE_FIELDS = ("STS", "NTS1", "NTS2")
BURST_TYPE_NONE = "-"


def burst_type(bits, threshold: float = DETECT_THRESHOLD) -> str:
    """Тип burst'а за навчальною послідовністю в першому слоті: назва послідовності
    з найменшою часткою помилок (<= threshold) у вікні ±ALIGN_WINDOW_BITS навколо
    її позиції, або BURST_TYPE_NONE."""
    s = _bits_to_str(bits)
    best_name, best_rate = BURST_TYPE_NONE, None
    for name in BURST_TYPE_FIELDS:
        pattern, pos, _ = KNOWN_FIELDS[name]
        rate = best_match_for_field(s[:pos + len(pattern) + ALIGN_WINDOW_BITS], pattern, pos)
        if rate is not None and rate <= threshold and (best_rate is None or rate < best_rate):
            best_name, best_rate = name, rate
    return best_name


@dataclass
class FieldStat:
    status: str               # "ok" (шукали) | "formula" (не фіксована послідовність)
    n_checked: int = 0
    n_exact: int = 0           # err_rate == 0 (побітово чисто)
    n_within_threshold: int = 0  # 0 < err_rate <= threshold (у межах дозволеного)
    median_err_rate: Optional[float] = None

    @property
    def n_found(self) -> int:
        """n_exact + n_within_threshold, для зворотної сумісності."""
        return self.n_exact + self.n_within_threshold


def check_all_fields(bits, threshold: float = DETECT_THRESHOLD) -> Dict[str, Optional[float]]:
    """Для ОДНОГО burst'а: частка помилок по кожному полю зі status="ok" окремо."""
    s = _bits_to_str(bits)
    out: Dict[str, Optional[float]] = {}
    for name, (pattern, pos, status) in KNOWN_FIELDS.items():
        if status != "ok" or pattern is None:
            out[name] = None
            continue
        out[name] = best_match_for_field(s, pattern, pos)
    return out


@dataclass
class RecordingPatternSummary:
    n_bursts: int
    n_symbols_total: int
    threshold: float
    per_field: Dict[str, FieldStat] = field(default_factory=dict)
    n_any_detected: int = 0
    detect_fraction: float = 0.0


def summarize_recording(bursts, threshold: float = DETECT_THRESHOLD) -> RecordingPatternSummary:
    """bursts: список об'єктів з .bits і .n_sym (BurstResult-сумісні).
    Статистика рахується НЕЗАЛЕЖНО по кожному полю (а не "переможець")."""
    n_bursts = len(bursts)
    n_symbols_total = sum(b.n_sym for b in bursts)
    per_field: Dict[str, FieldStat] = {
        name: FieldStat(status=status) for name, (_, _, status) in KNOWN_FIELDS.items()
    }
    any_detected = [False] * n_bursts
    err_lists: Dict[str, List[float]] = {name: [] for name in KNOWN_FIELDS}

    for i, b in enumerate(bursts):
        per_burst = check_all_fields(b.bits, threshold)
        for name, err in per_burst.items():
            st = per_field[name]
            if st.status != "ok" or err is None:
                continue
            st.n_checked += 1
            err_lists[name].append(err)
            if err <= threshold:
                if err == 0.0:
                    st.n_exact += 1
                else:
                    st.n_within_threshold += 1
                pattern, _, _ = KNOWN_FIELDS[name]
                if len(pattern) >= MIN_RELIABLE_FIELD_BITS:
                    any_detected[i] = True

    for name, st in per_field.items():
        if st.status == "ok" and err_lists[name]:
            st.median_err_rate = float(np.median(err_lists[name]))

    n_any = sum(any_detected)
    return RecordingPatternSummary(
        n_bursts=n_bursts, n_symbols_total=n_symbols_total, threshold=threshold,
        per_field=per_field, n_any_detected=n_any,
        detect_fraction=(n_any / n_bursts) if n_bursts else 0.0,
    )
