"""Складання файлу з бітів tch_decode (1 біт = 1 байт) + службова інформація пакетів.
Пакет (PACKET_BITS): PREFIX (4 байти) + заголовок від магії C0FFEE (MAGIC, PARAM1, PARAM2, RESERVED, COUNTER) + дані.
Береться ланцюжок магій із кроком рівно PACKET_BITS; решта магій (сигналізація, хвіст) - не дані.
Вихід: STEM.bin (дані), STEM.hdr.txt (службова інформація); з --ref - порівняння з еталоном."""
import argparse, os, sys
import numpy as np

MAGIC_HEX = 'c0ffee'
PACKET_BITS = 960
PREFIX_BITS = 32                     # байти перед магією
HEADER_BITS = 128                    # від початку магії до даних
FIELDS = (('MAGIC', 3), ('PARAM1', 4), ('PARAM2', 3), ('RESERVED', 5), ('COUNTER', 1))   # байти від магії; сума = HEADER_BITS/8
BYTE_BITS = 8
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


def main():
    ap = argparse.ArgumentParser(description="біти tch_decode -> файл даних + службова інформація пакетів")
    ap.add_argument("infile", help="файл бітів від tch_decode (1 біт = 1 байт)")
    ap.add_argument("-o", "--out", metavar="STEM", help="STEM.bin, STEM.hdr.txt (за замовчуванням: вхід без розширення)")
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
    msg = 'пакетів %d, байт %d -> %s.bin, %s.hdr.txt' % (len(chain), len(out), stem, stem)
    if a.ref:
        ref = open(a.ref, 'rb').read()
        msg += ', ref %d: %s' % (len(ref), 'ЗБІГАЄТЬСЯ' if out == ref else 'ВІДРІЗНЯЄТЬСЯ: %d байт' % sum(x != y for x, y in zip(out, ref)))
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
