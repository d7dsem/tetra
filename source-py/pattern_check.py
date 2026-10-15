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
  NTS3  - зі стандарту (формула 9.6, normal training sequence 3, q1..q22;
          9.4.4.3.2). Допоміжна послідовність, розкладена частинами по краях
          двох послідовних downlink burst'ів: у continuous q11..q22 на початку
          і q1..q10 в кінці, у discontinuous q21..q22 і q1..q2. У uplink
          burst'ах її немає, цілою 22-бітною в одному burst'і вона не зустрічається
          (розкладки - docs/burst-structures.md).
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

from config import CLASSIFY_END_SLACK_BITS, CLASSIFY_START_MAX_BITS, CLASSIFY_START_MIN_BITS

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


# Типи burst'ів за стандартом: розкладка = довжина, guard перед burst'ом у слоті 510 біт і відомі
# біти полів (преамбули, FCF, навчальні послідовності, tail). Поле phase adjustment і блоки даних
# невідомі й не перевіряються. Джерела: EN 300 396-2 V1.4.1 §9.4.3 (DMO: таблиці 14-16, формули
# (61)-(68)), EN 300 392-2 V3.8.1 §9.4.4 (TMO: таблиці 9.2-9.12, формули 9.4-9.12).
# Зсув - 0-based від першого біта burst'а (BN-1). Навчальна послідовність - якір положення.
@dataclass(frozen=True)
class BurstLayout:
    name: str
    length: int                           # довжина burst'а, біт
    guard_before: int                     # біти слота перед burst'ом (решта - guard після)
    fields: Tuple[Tuple[int, str], ...]   # (зсув, відомі біти)
    anchor: int                           # індекс навчальної послідовності у fields


_P1 = "001100100011"          # DMO preamble P1 (61): з NTS1, TCH або SCH/F
_P2 = "100110101001"          # DMO preamble P2 (62): з NTS2, STCH+TCH або STCH+STCH
_P3 = "000101000111"          # DMO synchronization preamble P3 (65): з STS
_Q = KNOWN_FIELDS["NTS3"][0]  # TMO NTS3 q1..q22: його частини на краях downlink burst'ів
_NTS = {"1": KNOWN_FIELDS["NTS1"][0], "2": KNOWN_FIELDS["NTS2"][0]}
_STS, _ETS, _FCF = (KNOWN_FIELDS[k][0] for k in ("STS", "ETS", "FCF"))
_TAIL_TMO = "1100"            # (9.12); у DMO tail "00" (68)


def _layouts() -> Tuple[BurstLayout, ...]:
    out = [BurstLayout("DSB", 470, 34, ((0, _P3), (14, _FCF), (214, _STS), (468, "00")), 2)]
    for k in "12":
        out.append(BurstLayout("DNB" + k, 470, 34, ((0, _P1 if k == "1" else _P2), (230, _NTS[k]), (468, "00")), 1))
    out.append(BurstLayout("SBc", 510, 0, ((0, _Q[10:]), (14, _FCF), (214, _STS), (500, _Q[:10])), 2))
    out.append(BurstLayout("SBd", 492, 10, ((0, _Q[20:]), (4, _FCF), (204, _STS), (490, _Q[:2])), 2))
    for k in "12":
        out.append(BurstLayout("NDBc" + k, 510, 0, ((0, _Q[10:]), (244, _NTS[k]), (500, _Q[:10])), 1))
        out.append(BurstLayout("NDBd" + k, 492, 10, ((0, _Q[20:]), (234, _NTS[k]), (490, _Q[:2])), 1))
        out.append(BurstLayout("NUB" + k, 462, 34, ((0, _TAIL_TMO), (220, _NTS[k]), (458, _TAIL_TMO)), 1))
    out.append(BurstLayout("CB", 206, 34, ((0, _TAIL_TMO), (88, _ETS), (202, _TAIL_TMO)), 1))
    return tuple(out)


BURST_LAYOUTS: Tuple[BurstLayout, ...] = _layouts()
BURST_LAYOUT_BY_NAME = {l.name: l for l in BURST_LAYOUTS}
BURST_TYPE_NONE = "-"


@dataclass(frozen=True)
class BurstMatch:
    layout: Optional[BurstLayout]
    start: Optional[int]          # положення першого біта burst'а в bits (може бути від'ємним)

    @property
    def name(self) -> str:
        return self.layout.name if self.layout else BURST_TYPE_NONE


def _match_at(s: str, layout: BurstLayout, start: int, threshold: float, end_slack: int):
    """(помилки, перевірено біт) для розкладки з початком у start; None, якщо не збігається.
    Кожне поле має вкластися в допуск threshold, якір має бути перевірений повністю."""
    n = len(s)
    if layout.length - (n - start) > end_slack:
        return None
    errs = total = 0
    for idx, (off, pat) in enumerate(layout.fields):
        a, b = start + off, start + off + len(pat)
        if a < 0 or b > n:
            if idx == layout.anchor:
                return None
            continue
        e = sum(x != y for x, y in zip(s[a:b], pat))
        if e > int(threshold * len(pat)):
            return None
        errs += e
        total += len(pat)
    return errs, total


def classify_burst(bits, threshold: float = DETECT_THRESHOLD, start_min: int = CLASSIFY_START_MIN_BITS,
                   start_max: int = CLASSIFY_START_MAX_BITS, end_slack: int = CLASSIFY_END_SLACK_BITS) -> BurstMatch:
    """Тип burst'а за стандартом: розкладка з BURST_LAYOUTS, у якій усі відомі поля (преамбула,
    навчальна послідовність, tail, FCF) збігаються в межах threshold при початку burst'а в
    start_min..start_max; найменша частка помилок, за рівності - більше перевірених біт.
    Перевіряється лише перший слот. Нічого не знайдено - BurstMatch(None, None)."""
    s = _bits_to_str(bits)
    best, best_key = BurstMatch(None, None), None
    for layout in BURST_LAYOUTS:
        for start in range(start_min, start_max + 1):
            r = _match_at(s, layout, start, threshold, end_slack)
            if r is None:
                continue
            key = (r[0] / r[1], -r[1])
            if best_key is None or key < best_key:
                best, best_key = BurstMatch(layout, start), key
    return best


def burst_type(bits, threshold: float = DETECT_THRESHOLD) -> str:
    """Назва типу burst'а за стандартом (DSB, DNB1, DNB2, SBc, SBd, NDBc1.., NUB1.., CB) або '-'."""
    return classify_burst(bits, threshold).name


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
