"""Канальне декодування TCH (дані) для DMO: .tch від dmo_rx (type-4, BLOCK_BITS біт/кадр) -> інформаційні біти.
Типи: 2.4, 4.8 (RCPC + Вітербі), 7.2 (без кодування); перемежування N з INTERLEAVE_DEPTHS (для 7.2 лише 1).
Вихід: файл бітів, 1 біт = 1 байт (0/1). Режим --scan пробує всі варіанти й друкує таблицю індикаторів.
Ref: ETSI EN 300 392-2 8.2.3.1 (RCPC), 8.2.4.1-8.2.4.2 (перемежування), 8.3.1.3.2-8.3.1.3.4 (TCH/4.8, 2.4, 7.2)."""
import argparse, os, sys
from collections import namedtuple
import numpy as np

# --- Блок і перемежування (ETSI 8.2.4) ---
BLOCK_BITS = 432                 # довжина type-3/type-4 блока TCH (два блоки по 216 біт у слоті)
BLOCK_INTERLEAVER_A = 103        # параметр a блокового перемежувача, формула (8.36)
INTERLEAVE_DEPTHS = (1, 4, 8)    # дозволені N перемежування по блоках

# --- Материнський код RCPC (ETSI 8.2.3.1.1): пам'ять 4, швидкість 1/4 ---
CODE_MEMORY = 4
N_STATES = 1 << CODE_MEMORY      # 16 станів
GENERATORS = ((1, 4), (2, 3, 4), (1, 2, 4), (1, 3, 4))   # G1..G4: степені D (1 завжди входить)
MOTHER_OUTPUTS = len(GENERATORS)
TAIL_BITS = CODE_MEMORY          # нулі в кінці type-2
PUNCT_PERIOD = 2 * MOTHER_OUTPUTS   # період пунктурування в символах материнського коду (ETSI 8.2.3.1.2)
P_RATE_2_3 = (0, 1, 2, 5)        # таблиці P: ETSI 8.2.3.1.3 / 8.2.3.1.4
P_RATE_1_3 = (0, 1, 2, 3, 5, 6, 7)
VITERBI_INF = 10 ** 6            # метрика недосяжного стану, більша за будь-яку кількість помилок

# info_bits - біти type-1; punct - таблиця P; skip_every - крок у i_func(j) = j + (j-1) div skip_every (8.2.3.1.5/8.2.3.1.6)
TchType = namedtuple("TchType", "info_bits punct skip_every")
TYPES = {"2.4": TchType(144, P_RATE_1_3, 35), "4.8": TchType(288, P_RATE_2_3, 65)}
UNCODED_TYPE = "7.2"             # type-4 = type-1, без кодування (8.3.1.3.4)
ALL_TYPES = (*TYPES, UNCODED_TYPE)
DEFAULT_TYPE = "2.4"

# --- Формат запису .tch (dmo_traffic_record у dmo/dmo_core/dmo_parse.c): слова int16, біт = знак ---
TCH_RECORD_WORDS = 690
TCH_RECORD_CHUNKS = ((1, 114), (116, 114), (231, 114), (346, 90))   # (перше слово, кількість бітів)
TCH_BIT_WORDS = np.concatenate([np.arange(a, a + n) for a, n in TCH_RECORD_CHUNKS])
assert len(TCH_BIT_WORDS) == BLOCK_BITS

SCAN_SEED = 1                    # випадковий контроль у --scan відтворюваний
PERCENT = 100.0


def steps_of(typ):
    return TYPES[typ].info_bits + TAIL_BITS


def mother_index(typ):
    """Позиції 432 прийнятих бітів у материнському коді (депанктурування, ETSI 8.2.3.1.2)."""
    t = TYPES[typ]; P = t.punct; period_t = len(P) - 1   # t = кількість бітів P на період
    idx = []
    for j in range(1, BLOCK_BITS + 1):
        i = j + (j - 1) // t.skip_every
        idx.append(PUNCT_PERIOD * ((i - 1) // period_t) + P[i - period_t * ((i - 1) // period_t)] - 1)
    return np.array(idx)


def block_deint(x, a=BLOCK_INTERLEAVER_A, K=BLOCK_BITS):
    return x[(1 + (a * np.arange(1, K + 1)) % K) - 1]


def unwrap_n(t4, N):
    """N послідовних type-4 блоків -> type-3 блоки (8.2.4.2). Видає len(t4)-N+1 блоків."""
    bp = np.array([block_deint(f) for f in t4])
    if N == 1:
        return bp
    q = BLOCK_BITS // N; i = np.arange(q)
    out = np.zeros((len(bp) - N + 1, BLOCK_BITS), np.uint8)
    for n in range(len(out)):
        for j in range(N):
            out[n, j + i * N] = bp[n + j, j * q + i]
    return out


# Вітербі: стан s - біти затримок, d_k = (s >> (k-1)) & 1; наступний = ((s << 1) & (N_STATES-1)) | b
def _outputs():
    o = np.zeros((N_STATES, 2, MOTHER_OUTPUTS), np.uint8)
    for s in range(N_STATES):
        for b in (0, 1):
            o[s, b] = [(b + sum((s >> (k - 1)) & 1 for k in g)) & 1 for g in GENERATORS]
    return o


OUT = _outputs()
PRED = np.array([[(ns >> 1) | (d << (CODE_MEMORY - 1)) for d in (0, 1)] for ns in range(N_STATES)])
PB = np.arange(N_STATES) & 1     # вхідний біт, що привів у стан ns


def viterbi(rx, known, steps):
    pm = np.full(N_STATES, VITERBI_INF); pm[0] = 0
    back = np.zeros((steps, N_STATES), np.int8)
    for t in range(steps):
        r = rx[MOTHER_OUTPUTS * t:MOTHER_OUTPUTS * (t + 1)]; k = known[MOTHER_OUTPUTS * t:MOTHER_OUTPUTS * (t + 1)]
        bm = ((OUT != r) & k).sum(2)            # [s,b]
        cand = np.stack([pm[PRED[:, d]] + bm[PRED[:, d], PB] for d in (0, 1)], 1)
        back[t] = cand.argmin(1); pm = cand.min(1)
    s = 0; bits = np.zeros(steps, np.uint8)
    for t in range(steps - 1, -1, -1):
        d = back[t, s]; bits[t] = s & 1; s = PRED[s, d]
    return bits, int(pm[0])


def decode_t3(t3, typ):
    steps = steps_of(typ)
    rx = np.zeros(MOTHER_OUTPUTS * steps, np.uint8); known = np.zeros(MOTHER_OUTPUTS * steps, bool)
    idx = mother_index(typ); rx[idx] = t3; known[idx] = True
    bits, m = viterbi(rx, known, steps)
    return bits[:TYPES[typ].info_bits], m


def decode(t4, typ, N):
    """Список (інфо-біти, метрика) по type-3 блоках. Для 7.2 метрики немає (None)."""
    if typ == UNCODED_TYPE:
        return [(f, None) for f in t4]
    return [decode_t3(b, typ) for b in unwrap_n(t4, N)]


def read_tch(path):
    r = np.fromfile(path, dtype='<i2').reshape(-1, TCH_RECORD_WORDS)
    return (r[:, TCH_BIT_WORDS] < 0).astype(np.uint8)


def scan(t4):
    """Метрика лише по ненульових type-3 блоках: нульовий блок є кодовим словом будь-якого варіанту."""
    ctrl = np.random.default_rng(SCAN_SEED).integers(0, 2, t4.shape, dtype=np.uint8)
    print("%-4s %-2s %9s %10s %8s | контроль (випадкові біти): ненульових, середня" % ("тип", "N", "ненульових", "метрика=0", "середня"))
    for typ in TYPES:
        for N in INTERLEAVE_DEPTHS:
            row = []
            for src in (t4, ctrl):
                b3 = unwrap_n(src, N); b3 = b3[b3.any(1)]
                row.append(np.array([decode_t3(x, typ)[1] for x in b3]))
            m, c = row
            print("%-4s %-2d %9d %9.1f%% %8.2f | %9d %8.2f" % (typ, N, len(m), PERCENT * (m == 0).mean(), m.mean(), len(c), c.mean()))
    print("%s  1  без кодування: індикатора помилок немає, перевіряйте структуру даних вручну" % UNCODED_TYPE)


def main():
    ap = argparse.ArgumentParser(description="TCH (дані): .tch -> інфо-біти (1 біт = 1 байт)")
    ap.add_argument("infile", help=".tch з dmo_rx")
    ap.add_argument("--type", choices=ALL_TYPES, default=DEFAULT_TYPE)
    ap.add_argument("-n", "--interleave", type=int, choices=INTERLEAVE_DEPTHS, default=1, help="глибина перемежування N")
    ap.add_argument("--scan", action="store_true", help="спробувати всі варіанти, надрукувати таблицю, нічого не писати")
    ap.add_argument("-o", "--out", help="вихід (за замовчуванням <вхід>.tch<тип>_n<N>.bits)")
    a = ap.parse_args()
    t4 = read_tch(a.infile)
    if a.scan:
        scan(t4); return 0
    if a.type == UNCODED_TYPE and a.interleave != 1:
        sys.exit("для TCH/%s N=1 (перемежування немає)" % UNCODED_TYPE)
    res = decode(t4, a.type, a.interleave)
    out = a.out or "%s.tch%s_n%d.bits" % (os.path.splitext(a.infile)[0], a.type.replace(".", ""), a.interleave)
    np.concatenate([x[0] for x in res]).astype(np.uint8).tofile(out)
    ms = [x[1] for x in res if x[1] is not None]
    print("TCH/%s N=%d: блоків %d%s -> %s" % (a.type, a.interleave, len(res),
          ", метрика=0: %d, макс. %d" % (sum(m == 0 for m in ms), max(ms)) if ms else "", out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
