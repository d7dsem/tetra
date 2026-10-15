import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from scipy.io import wavfile

from io_stage import write_bits_bin, write_bits_bin_aligned, write_bits_bin_phase_aligned
from synth import make_signal

HERE = os.path.dirname(os.path.abspath(__file__))


class TestBitsBin(unittest.TestCase):
    def test_packing_lsb_first_concat_pad_end(self):
        bursts = [SimpleNamespace(bits=np.array([1, 0, 0], np.uint8)),
                  SimpleNamespace(bits=np.array([1, 1], np.uint8))]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin")
            write_bits_bin(p, bursts)
            self.assertEqual(open(p, "rb").read(), bytes([0b00011001]))

    def test_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin")
            write_bits_bin(p, [])
            self.assertEqual(open(p, "rb").read(), b"")


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

    def test_burst_exact_multiple_gets_no_padding(self):
        bursts = [SimpleNamespace(bits=np.ones(10, np.uint8)),
                  SimpleNamespace(bits=np.array([1, 0], np.uint8))]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin2")
            write_bits_bin_aligned(p, bursts, slot_bits=5)
            got = np.unpackbits(np.frombuffer(open(p, "rb").read(), np.uint8), bitorder="little")
            np.testing.assert_array_equal(got[:15], [1] * 10 + [1, 0, 0, 0, 0])

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

    def test_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bin2")
            write_bits_bin_aligned(p, [], slot_bits=510)
            self.assertEqual(open(p, "rb").read(), b"")

    def test_differs_from_unaligned_when_padding_needed(self):
        bursts = [SimpleNamespace(bits=np.array([1, 0, 1], np.uint8)),
                  SimpleNamespace(bits=np.array([1, 1], np.uint8))]
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = os.path.join(d, "x.bin"), os.path.join(d, "x.bin2")
            write_bits_bin(p1, bursts)
            write_bits_bin_aligned(p2, bursts, slot_bits=5)
            self.assertNotEqual(open(p1, "rb").read(), open(p2, "rb").read())


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

    def test_zero_start_has_no_leading_zeros(self):
        b = SimpleNamespace(start=0, bits=np.array([1, 1], np.uint8))
        got = self._write([b])
        np.testing.assert_array_equal(got[:2], [1, 1])

    def test_two_bursts_each_independently_phased(self):
        b1 = SimpleNamespace(start=3, bits=np.array([1, 1], np.uint8))    # phase=3
        b2 = SimpleNamespace(start=15, bits=np.array([1, 1], np.uint8))   # phase=15%10=5
        got = self._write([b1, b2])[:20]       # по 10 на кожен burst (3+2<=10, 5+2<=10)
        np.testing.assert_array_equal(got[3:5], [1, 1])
        np.testing.assert_array_equal(got[15:17], [1, 1])

    def test_empty(self):
        self.assertEqual(len(self._write([])), 0)

    def test_burst_duration_derived_not_hardcoded(self):
        # інший symbol_rate_hz -> інша burst_duration_s -> інша фаза для того самого start.
        b = SimpleNamespace(start=7, bits=np.array([1], np.uint8))
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = os.path.join(d, "a.bin3"), os.path.join(d, "b.bin3")
            write_bits_bin_phase_aligned(p1, [b], 10, 2.0, 1.0)
            write_bits_bin_phase_aligned(p2, [b], 10, 2.0, 2.0)   # вдвічі більша symbol_rate
            self.assertNotEqual(open(p1, "rb").read(), open(p2, "rb").read())


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
            self.assertEqual(self._run(d), ["rec.bin", "rec.bin2", "rec.bin3", "rec.txt", "rec.wav"])

    def test_o_is_stem(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._run(d, "-o", os.path.join(d, "out")),
                             ["out.bin", "out.bin2", "out.bin3", "out.txt", "rec.wav"])

    def test_artefacts_section_lists_abs_paths_and_sizes(self):
        with tempfile.TemporaryDirectory() as d:
            out = self._run(d, capture=True)
            tail = out.split("[ARTEFACTS]\n")[1].split("[SUMMARY]")[0].splitlines()
            for line, ext in zip(tail, (".txt", ".bin", ".bin2", ".bin3")):
                path, size = line.strip().rsplit("  ", 1)
                self.assertEqual(path, os.path.realpath(os.path.join(d, "rec" + ext)))
                self.assertEqual(size, f"{os.path.getsize(path)} B")

    def test_bin_matches_txt_bits(self):
        with tempfile.TemporaryDirectory() as d:
            self._run(d)
            txt = [l.split()[-1] for l in open(os.path.join(d, "rec.txt"))]
            bits = np.array(list("".join(txt)), dtype=np.uint8)
            got = np.unpackbits(np.frombuffer(open(os.path.join(d, "rec.bin"), "rb").read(),
                                              np.uint8), bitorder="little")[:len(bits)]
            self.assertTrue(len(txt) > 0 and (got == bits).all())


if __name__ == "__main__":
    unittest.main()
