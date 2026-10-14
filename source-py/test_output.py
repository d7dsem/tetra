import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from scipy.io import wavfile

from io_stage import write_bits_bin
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
            self.assertEqual(self._run(d), ["rec.bin", "rec.txt", "rec.wav"])

    def test_o_is_stem(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._run(d, "-o", os.path.join(d, "out")),
                             ["out.bin", "out.txt", "rec.wav"])

    def test_artefacts_section_lists_abs_paths_and_sizes(self):
        with tempfile.TemporaryDirectory() as d:
            out = self._run(d, capture=True)
            tail = out.split("[ARTEFACTS]\n")[1].splitlines()
            for line, ext in zip(tail, (".txt", ".bin")):
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
