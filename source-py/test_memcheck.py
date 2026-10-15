"""Тести етапу 0a (пам'ять) і вводу. Запуск: python3 -m unittest discover -s tests -t . -v"""
import os
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

from tetra_demod import main
from config import PipelineConfig, apply_overrides
from io_stage import load_iq, probe_input
from memcheck import available_memory_bytes, estimate_memory, format_report

CFG = PipelineConfig()
WORK = CFG.front.work_fs_hz


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


class TestAvailableMemory(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.mi = os.path.join(self.d, "meminfo")
        _write(self.mi, "MemTotal: 100 kB\nMemAvailable: 2000 kB\n")
        self.none = os.path.join(self.d, "nope")

    def test_meminfo_only(self):
        r = available_memory_bytes(self.mi, self.none, self.none)
        self.assertEqual(r, (2000 * 1024, "/proc/meminfo MemAvailable"))

    def test_cgroup_v2_limit_wins_when_smaller(self):
        cg = os.path.join(self.d, "cg2"); os.makedirs(cg)
        _write(os.path.join(cg, "memory.max"), "1000000")
        _write(os.path.join(cg, "memory.current"), "400000")
        r = available_memory_bytes(self.mi, cg, self.none)
        self.assertEqual(r, (600000, "cgroup v2"))

    def test_cgroup_unlimited_ignored(self):
        cg = os.path.join(self.d, "cg2"); os.makedirs(cg)
        _write(os.path.join(cg, "memory.max"), "max")
        _write(os.path.join(cg, "memory.current"), "400000")
        self.assertEqual(available_memory_bytes(self.mi, cg, self.none)[1],
                         "/proc/meminfo MemAvailable")

    def test_cgroup_v1_unlimited_ignored(self):
        cg = os.path.join(self.d, "cg1"); os.makedirs(cg)
        _write(os.path.join(cg, "memory.limit_in_bytes"), str((1 << 63) - 4096))
        _write(os.path.join(cg, "memory.usage_in_bytes"), "1000")
        self.assertEqual(available_memory_bytes(self.mi, self.none, cg)[1],
                         "/proc/meminfo MemAvailable")

    def test_nothing_available(self):
        self.assertIsNone(available_memory_bytes(self.none, self.none, self.none))


class TestEstimate(unittest.TestCase):
    def test_grows_with_duration(self):
        a = estimate_memory(int(WORK * 10), WORK, CFG)
        b = estimate_memory(int(WORK * 100), WORK, CFG)
        self.assertGreater(b.peak_bytes, a.peak_bytes)
        self.assertIsNone(a.ok)  # available не передано

    def test_resampling_costs_more(self):
        same = estimate_memory(int(WORK * 60), WORK, CFG)
        wide = estimate_memory(int(1.8e6 * 60), 1.8e6, CFG)
        self.assertTrue(wide.resampled and not same.resampled)
        self.assertGreater(wide.peak_bytes, same.peak_bytes)
        self.assertIn("resample", wide.stage_bytes)

    def test_ok_flag_and_max_duration_consistent(self):
        avail = (800 * 10 ** 6, "test")
        e = estimate_memory(int(WORK * 3600), WORK, CFG, avail)   # година: не влізе
        self.assertFalse(e.ok)
        self.assertGreater(e.max_duration_s, 0)
        at_limit = estimate_memory(int(WORK * e.max_duration_s), WORK, CFG, avail)
        self.assertLessEqual(at_limit.required_bytes, avail[0] * 1.001)
        over = estimate_memory(int(WORK * e.max_duration_s * 1.05), WORK, CFG, avail)
        self.assertGreater(over.required_bytes, avail[0])
        small = estimate_memory(int(WORK * 5), WORK, CFG, avail)
        self.assertTrue(small.ok)

    def test_report_mentions_verdict(self):
        e = estimate_memory(int(WORK * 3600), WORK, CFG, (500 * 10 ** 6, "test"))
        self.assertIn("NO", format_report(e))
        self.assertIn("Available: 500 MB", format_report(e))
        e = estimate_memory(int(WORK * 3600), WORK, CFG)
        self.assertIn("skipped", format_report(e))


class TestInput(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        rng = np.random.default_rng(0)
        self.iq = rng.integers(-32768, 32767, (1000, 2)).astype(np.int16)
        self.wav = os.path.join(self.d, "a.wav")
        wavfile.write(self.wav, 72000, self.iq)
        self.raw = os.path.join(self.d, "a.cs16")
        self.iq.tofile(self.raw)

    def test_probe_wav_and_raw(self):
        self.assertEqual(probe_input(self.wav), (72000.0, 1000))
        self.assertEqual(probe_input(self.raw, 192000.0), (192000.0, 1000))
        with self.assertRaises(ValueError):
            probe_input(self.raw)

    def test_load_matches_reference_formula(self):
        ref = (self.iq[:, 0].astype(np.float32) + 1j * self.iq[:, 1].astype(np.float32)) / 32768
        for path, hint in ((self.wav, None), (self.raw, 72000.0)):
            fs, x = load_iq(path, hint)
            self.assertEqual(x.dtype, np.complex64)
            np.testing.assert_allclose(x, ref, atol=1e-7)

    def test_odd_raw_tail_is_dropped(self):
        p = os.path.join(self.d, "odd.cs16")
        with open(p, "wb") as f:
            f.write(self.iq.tobytes() + b"\x01\x00")  # зайвий один int16
        self.assertEqual(probe_input(p, 1.0)[1], 1000)


class TestCliPolicy(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.wav = os.path.join(self.d, "a.wav")
        wavfile.write(self.wav, 72000,
                      (np.random.default_rng(0).normal(size=(72000, 2)) * 1500).astype(np.int16))
        self.out = os.path.join(self.d, "o.txt")

    def run_cli(self, *extra):
        return main([self.wav, "-o", self.out[:-4], *extra])

    def test_abort_when_not_enough(self):
        self.assertEqual(self.run_cli("--set", "memory.safety_factor=1000000"), 2)
        self.assertFalse(os.path.exists(self.out))

    def test_warn_continues(self):
        self.assertEqual(self.run_cli("--set", "memory.safety_factor=1000000",
                                      "--set", "memory.policy=warn"), 0)
        self.assertTrue(os.path.exists(self.out))

    def test_off_skips_check(self):
        self.assertEqual(self.run_cli("--set", "memory.safety_factor=1000000",
                                      "--set", "memory.policy=off"), 0)

    def test_mem_only(self):
        self.assertEqual(self.run_cli("--mem-only"), 0)
        self.assertFalse(os.path.exists(self.out))

    def test_default_small_file_passes(self):
        self.assertEqual(self.run_cli(), 0)


if __name__ == "__main__":
    unittest.main()
