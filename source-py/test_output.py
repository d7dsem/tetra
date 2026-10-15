import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from scipy.io import wavfile

from io_stage import (write_bits_bin, write_bits_bin_aligned, write_bits_bin_phase_aligned,
                      write_bits_bin_structured, write_bursts)
from pattern_check import BURST_LAYOUT_BY_NAME, KNOWN_FIELDS
from synth import make_signal

HERE = os.path.dirname(os.path.abspath(__file__))


class TestWriteBursts(unittest.TestCase):
    def _burst(self, start, bits, flags="-"):
        return SimpleNamespace(t_start_s=start / 72000, start=start, n_sym=len(bits) // 2,
                               end=start + 100, snr_db=12.3456, freq_hz=-5.55, coherence=0.9,
                               phase_rms_deg=3.21, flags=flags, bits=bits)

    def _lines(self, bursts):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.txt")
            write_bursts(p, bursts)
            return open(p).read().splitlines()

    def test_header_count_patterns_and_columns(self):
        lines = self._lines([self._burst(5, [1, 0]), self._burst(123456789, [1, 1, 0, 0])])
        head = [l for l in lines if l.startswith("#")]
        self.assertIn("# bursts: 2", head)
        self.assertTrue(any(l.startswith("#   NTS1 (22) 1101000011101001110100") for l in head))
        self.assertIn("bits", head[-1])
        self.assertEqual(len(lines) - len(head), 2)


class TestBitsBin(unittest.TestCase):
    def test_packing_lsb_first_concat_pad_end(self):
        bursts = [SimpleNamespace(bits=np.array([1, 0, 0], np.uint8)),
                  SimpleNamespace(bits=np.array([1, 1], np.uint8))]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin")
            write_bits_bin(p, bursts)
            self.assertEqual(open(p, "rb").read(), bytes([0b00011001]))

    def test_packing_msb_first_when_big(self):
        bursts = [SimpleNamespace(bits=np.array([1, 0, 0], np.uint8)),
                  SimpleNamespace(bits=np.array([1, 1], np.uint8))]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin")
            write_bits_bin(p, bursts, "big")
            self.assertEqual(open(p, "rb").read(), bytes([0b10011000]))


class TestBitsBinAligned(unittest.TestCase):
    def test_each_burst_padded_to_slot_multiple(self):
        bursts = [SimpleNamespace(bits=np.array([1, 0, 1], np.uint8)),    # 3 біти
                  SimpleNamespace(bits=np.array([1, 1], np.uint8))]       # 2 біти
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin2")
            write_bits_bin_aligned(p, bursts, slot_bits=5)
            got = np.unpackbits(np.frombuffer(open(p, "rb").read(), np.uint8), bitorder="little")
            # перший burst: [1,0,1,0,0] (доповнено до 5), другий: [1,1,0,0,0]
            np.testing.assert_array_equal(got[:10], [1, 0, 1, 0, 0, 1, 1, 0, 0, 0])


    def test_every_burst_starts_on_slot_boundary(self):
        rng = np.random.default_rng(0)
        slot = 510
        bursts = [SimpleNamespace(bits=rng.integers(0, 2, n).tolist())
                 for n in (474, 476, 480, 8634)]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin2")
            write_bits_bin_aligned(p, bursts, slot_bits=slot)
            n_bits = sum(-(-len(b.bits) // slot) * slot for b in bursts)
            got = np.unpackbits(np.frombuffer(open(p, "rb").read(), np.uint8),
                                bitorder="little")[:n_bits]
            offset = 0
            for b in bursts:
                self.assertEqual(offset % slot, 0)
                np.testing.assert_array_equal(got[offset:offset + len(b.bits)], b.bits)
                offset += -(-len(b.bits) // slot) * slot


class TestBitsBinPhaseAligned(unittest.TestCase):
    # symbol_rate_hz=1, slot_bits=10 -> burst_duration_s=10/(2*1)=5 с
    # sample_rate_hz=2 -> відліків на слот = 2*5=10 = slot_bits, тож phase = start % 10 - просто для тесту.
    SR, SYM_RATE, SLOT = 2.0, 1.0, 10

    def _write(self, bursts):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin3")
            write_bits_bin_phase_aligned(p, bursts, self.SLOT, self.SR, self.SYM_RATE)
            return np.unpackbits(np.frombuffer(open(p, "rb").read(), np.uint8), bitorder="little")

    def test_phase_equals_start_mod_slot_for_these_params(self):
        b = SimpleNamespace(start=3, bits=np.array([1, 1, 1], np.uint8))
        got = self._write([b])[:10]                           # логічна довжина = 10 (кратність slot)
        np.testing.assert_array_equal(got[:3], [0, 0, 0])     # ведучі нулі - справжня фаза
        np.testing.assert_array_equal(got[3:6], [1, 1, 1])
        np.testing.assert_array_equal(got[6:], [0, 0, 0, 0])

    def test_rounds_up_when_phase_plus_len_exceeds_slot(self):
        b = SimpleNamespace(start=8, bits=np.array([1, 0, 1, 1], np.uint8))   # phase=8, 8+4=12>10
        got = self._write([b])[:20]                           # логічна довжина = 20
        np.testing.assert_array_equal(got[:8], np.zeros(8))
        np.testing.assert_array_equal(got[8:12], [1, 0, 1, 1])
        np.testing.assert_array_equal(got[12:], np.zeros(8))


    def test_two_bursts_each_independently_phased(self):
        b1 = SimpleNamespace(start=3, bits=np.array([1, 1], np.uint8))    # phase=3
        b2 = SimpleNamespace(start=15, bits=np.array([1, 1], np.uint8))   # phase=15%10=5
        got = self._write([b1, b2])[:20]       # по 10 на кожен burst (3+2<=10, 5+2<=10)
        np.testing.assert_array_equal(got[3:5], [1, 1])
        np.testing.assert_array_equal(got[15:17], [1, 1])

    def test_empty(self):
        self.assertEqual(len(self._write([])), 0)


class TestBitsBinStructured(unittest.TestCase):
    """.bin4: один слот на burst, поля у колонках стандарту незалежно від зсуву захоплення."""
    STS_COL = 34 + 214          # guard 34 + зсув STS у burst'і (таблиця 16 EN 300 396-2)

    def _burst_470(self, seed=0):
        bits = np.random.default_rng(seed).integers(0, 2, 470).astype(np.uint8)
        for off, pat in BURST_LAYOUT_BY_NAME["DSB"].fields:        # відомі поля DSB: preamble, FCF, STS, tail
            bits[off:off + len(pat)] = [int(c) for c in pat]
        return bits

    def _rows(self, bits_list):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin4")
            n_rows, n_unanchored = write_bits_bin_structured(
                p, [SimpleNamespace(bits=b) for b in bits_list])
            raw = np.unpackbits(np.fromfile(p, dtype=np.uint8), bitorder="little")
        return raw[:n_rows * 510].reshape(n_rows, 510), n_unanchored

    def test_capture_offset_does_not_move_fields(self):
        core = self._burst_470()
        rng = np.random.default_rng(5)
        captures = [np.concatenate([rng.integers(0, 2, pre).astype(np.uint8), core, rng.integers(0, 2, post).astype(np.uint8)])
                    for pre, post in ((2, 0), (4, 0), (6, 2), (8, 4))]
        rows, unanchored = self._rows(captures)
        self.assertEqual(unanchored, 0)
        for r in rows:
            self.assertTrue((r[:34] == 0).all() and (r[504:] == 0).all())
            self.assertEqual(r[self.STS_COL:self.STS_COL + 38].tolist(), core[214:252].tolist())
            self.assertEqual(r[34:504].tolist(), core.tolist())

    def test_continuous_slots_split_into_rows(self):
        core = self._burst_470()
        stream = np.zeros(4 + 2 * 510 + 470, dtype=np.uint8)
        for k in range(3):
            stream[4 + 510 * k:4 + 510 * k + 470] = core
        rows, _ = self._rows([stream])
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertEqual(r[34:504].tolist(), core.tolist())


class TestCliOutputNames(unittest.TestCase):
    def _run(self, d, *extra, capture=False):
        x, _ = make_signal(np.random.default_rng(1))
        wav = os.path.join(d, "rec.wav")
        iq = np.stack([x.real, x.imag], 1) * 8000
        wavfile.write(wav, 72000, iq.astype(np.int16))
        r = subprocess.run([sys.executable, os.path.join(HERE, "tetra_demod.py"), wav, *extra],
                           check=True, capture_output=True, text=True)
        return r.stdout if capture else sorted(os.listdir(d))

    def test_default_stem_from_input(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._run(d), ["rec.bin", "rec.bin2", "rec.bin3", "rec.bin4", "rec.txt", "rec.wav"])

    def test_o_is_stem(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._run(d, "-o", os.path.join(d, "out")),
                             ["out.bin", "out.bin2", "out.bin3", "out.bin4", "out.txt", "rec.wav"])


    def test_bin_matches_txt_bits(self):
        with tempfile.TemporaryDirectory() as d:
            self._run(d)
            txt = [l.split()[-1] for l in open(os.path.join(d, "rec.txt")) if not l.startswith("#")]
            bits = np.array(list("".join(txt)), dtype=np.uint8)
            got = np.unpackbits(np.frombuffer(open(os.path.join(d, "rec.bin"), "rb").read(),
                                              np.uint8), bitorder="little")[:len(bits)]
            self.assertTrue(len(txt) > 0 and (got == bits).all())


if __name__ == "__main__":
    unittest.main()
