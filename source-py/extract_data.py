"""Розділення бітів tch_decode (1 біт = 1 байт) на дані й службову частину.
Пакет (PACKET_BITS): PREFIX (4 байти) + заголовок від магії C0FFEE (MAGIC, PARAM1, PARAM2, RESERVED, COUNTER) + дані.
Береться ланцюжок магій із кроком рівно PACKET_BITS; решта магій (сигналізація, хвіст) - не дані.
Вихід: STEM.bin (дані), STEM.hdr.txt (заголовки пакетів), STEM.svc.txt (все поза пакетами даних: hex-дамп і текстові рядки);
з --ref - порівняння даних з еталоном."""
import argparse, os, re, sys
import numpy as np

MAGIC_HEX = 'c0ffee'
PACKET_BITS = 960
PREFIX_BITS = 32                     # байти перед магією
HEADER_BITS = 128                    # від початку магії до даних
FIELDS = (('MAGIC', 3), ('PARAM1', 4), ('PARAM2', 3), ('RESERVED', 5), ('COUNTER', 1))   # байти від магії; сума = HEADER_BITS/8
BYTE_BITS = 8
HEXDUMP_ROW = 16                     # байтів у рядку дампа
MIN_TEXT_RUN = 8                     # найкоротший текстовий рядок, що вважається змістовним
TEXT_RUN_RE = re.compile(rb'[ -~]{%d,}' % MIN_TEXT_RUN)
assert sum(n for _, n in FIELDS) * BYTE_BITS == HEADER_BITS


def packet_bytes(s, p):
    """Байти пакета, що починається за PREFIX_BITS до магії p."""
    return np.packbits(s[p - PREFIX_BITS:p - PREFIX_BITS + PACKET_BITS]).tobytes()


def parse(pk):
    """-> (prefix, {поле: bytes}, дані)."""
    pre_n, hdr_n = PREFIX_BITS // BYTE_BITS, (PREFIX_BITS + HEADER_BITS) // BYTE_BITS
    f, o = {}, pre_n
    for name, n in FIELDS:
        f[name] = pk[o:o + n]; o += n
    return pk[:pre_n], f, pk[hdr_n:]


def find_chain(s):
    """Позиції магій, за якими через PACKET_BITS іде наступна магія; не менше PREFIX_BITS від початку."""
    magic = np.unpackbits(np.frombuffer(bytes.fromhex(MAGIC_HEX), np.uint8))
    pos = {i for i in range(PREFIX_BITS, len(s) - len(magic)) if (s[i:i + len(magic)] == magic).all()}
    return sorted(p for p in pos if p + PACKET_BITS in pos)


def write_header_report(path, chain, pkts):
    with open(path, 'w') as h:
        h.write('# пакет  біт_магії  PREFIX(4Б)  ' + ' '.join(n for n, _ in FIELDS) + '\n')
        for i, (p, (pre, f, _)) in enumerate(zip(chain, pkts)):
            h.write('%5d %9d  %s  %s\n' % (i, p, pre.hex(), ' '.join(f[n].hex() for n, _ in FIELDS)))
        const = ['%s=%s' % (n, pkts[0][1][n].hex()) for n, _ in FIELDS[:-1] if len({x[1][n] for x in pkts}) == 1]
        h.write('# сталі поля: ' + ', '.join(const) + '\n')
        cnt = [x[1]['COUNTER'][0] for x in pkts]
        seq = cnt == list(range(cnt[0], cnt[0] + len(cnt)))
        h.write('# COUNTER: %d..%d, %s\n' % (cnt[0], cnt[-1], 'послідовний +1' if seq else 'НЕ послідовний'))
        h.write('# PREFIX: %d різних значень з %d пакетів\n' % (len({x[0] for x in pkts}), len(pkts)))


def service_segments(chain, n_bits):
    """Діапазони бітів поза пакетами ланцюжка (пакет займає PACKET_BITS від PREFIX_BITS до магії); порожні відкидаються."""
    segs, pos = [], 0
    for p in chain:
        start = p - PREFIX_BITS
        if start > pos:
            segs.append((pos, start))
        pos = max(pos, start + PACKET_BITS)
    if n_bits > pos:
        segs.append((pos, n_bits))
    return segs


def text_runs(s, a, b):
    """Друковані ASCII-рядки в s[a:b] при будь-якому зсуві бітів 0..BYTE_BITS-1: [(біт, текст)]."""
    found = []
    for off in range(BYTE_BITS):
        n = (b - a - off) // BYTE_BITS
        if n < MIN_TEXT_RUN:
            continue
        raw = np.packbits(s[a + off:a + off + n * BYTE_BITS]).tobytes()
        found += [(a + off + m.start() * BYTE_BITS, m.group().decode()) for m in TEXT_RUN_RE.finditer(raw)]
    return sorted(found)


def write_service_report(path, s, segs):
    with open(path, 'w') as h:
        h.write('# службова частина: біти поза пакетами даних; усього %d сегментів\n' % len(segs))
        for a, b in segs:
            h.write('\n== біти %d..%d (%d біт, %d байт від початку сегмента) ==\n' % (a, b, b - a, (b - a) // BYTE_BITS))
            runs = text_runs(s, a, b)
            h.write('текстові рядки (>= %d знаків, будь-який зсув біт): %s\n' % (MIN_TEXT_RUN, 'немає' if not runs else ''))
            for pos, t in runs:
                h.write('  біт %d: %s\n' % (pos, t))
            raw = np.packbits(s[a:b - (b - a) % BYTE_BITS]).tobytes()
            for i in range(0, len(raw), HEXDUMP_ROW):
                row = raw[i:i + HEXDUMP_ROW]
                h.write('%6d  %-*s  %s\n' % (i, HEXDUMP_ROW * 3 - 1, row.hex(' '), ''.join(chr(c) if 32 <= c < 127 else '.' for c in row)))


def main():
    ap = argparse.ArgumentParser(description="біти tch_decode -> дані, заголовки пакетів, службова частина")
    ap.add_argument("infile", help="файл бітів від tch_decode (1 біт = 1 байт)")
    ap.add_argument("-o", "--out", metavar="STEM", help="STEM.bin, STEM.hdr.txt, STEM.svc.txt (за замовчуванням: вхід без розширення)")
    ap.add_argument("--ref", metavar="FILE", help="еталонний файл для порівняння")
    a = ap.parse_args()
    s = np.fromfile(a.infile, dtype=np.uint8)
    chain = find_chain(s)
    if not chain:
        sys.exit("ланцюжка пакетів (магія %s, крок %d біт) не знайдено" % (MAGIC_HEX, PACKET_BITS))
    pkts = [parse(packet_bytes(s, p)) for p in chain]
    stem = a.out or os.path.splitext(a.infile)[0]
    out = b''.join(d for _, _, d in pkts)
    open(stem + '.bin', 'wb').write(out)
    write_header_report(stem + '.hdr.txt', chain, pkts)
    segs = service_segments(chain, len(s))
    write_service_report(stem + '.svc.txt', s, segs)
    msg = 'пакетів %d, байт %d, службових сегментів %d -> %s.bin, .hdr.txt, .svc.txt' % (len(chain), len(out), len(segs), stem)
    if a.ref:
        ref = open(a.ref, 'rb').read()
        msg += ', ref %d: %s' % (len(ref), 'ЗБІГАЄТЬСЯ' if out == ref else 'ВІДРІЗНЯЄТЬСЯ: %d байт' % sum(x != y for x, y in zip(out, ref)))
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
