"""Тести pattern_check.py. Запуск: python3 -m unittest test_pattern_check"""
import unittest
from dataclasses import dataclass
from typing import List

import numpy as np

from pattern_check import KNOWN_FIELDS, check_burst_patterns, summarize_recording


@dataclass
class FakeBurst:
    bits: List[int]
    n_sym: int


def bits_from(s: str) -> List[int]:
    return [int(c) for c in s]


def embed(pattern: str, pos: int, total_bits: int, rng, flip_frac: float = 0.0) -> List[int]:
    bits = rng.integers(0, 2, total_bits).tolist()
    pat = list(map(int, pattern))
    if flip_frac > 0:
        n_flip = max(1, int(round(len(pat) * flip_frac)))
        idx = rng.choice(len(pat), n_flip, replace=False)
        for i in idx:
            pat[i] ^= 1
    bits[pos:pos + len(pat)] = pat
    return bits


class TestCheckBurstPatterns(unittest.TestCase):
    def test_pure_random_bits_not_detected(self):
        rng = np.random.default_rng(0)
        bits = rng.integers(0, 2, 470).tolist()
        r = check_burst_patterns(bits)
        self.assertFalse(r.detected)
        self.assertIsNone(r.best_field)

    def test_exact_field_detected_for_each_known_pattern(self):
        rng = np.random.default_rng(1)
        for name, (pattern, pos) in KNOWN_FIELDS.items():
            bits = embed(pattern, pos, 470, rng)
            r = check_burst_patterns(bits)
            self.assertTrue(r.detected, name)
            self.assertEqual(r.best_field, name)
            self.assertEqual(r.err_rate, 0.0)

    def test_tolerates_some_bit_errors(self):
        rng = np.random.default_rng(2)
        pattern, pos = KNOWN_FIELDS["FCF"]
        bits = embed(pattern, pos, 470, rng, flip_frac=0.1)   # 10% помилок
        r = check_burst_patterns(bits)
        self.assertTrue(r.detected)
        self.assertLess(r.err_rate, 0.2)

    def test_too_many_errors_not_detected(self):
        rng = np.random.default_rng(3)
        pattern, pos = KNOWN_FIELDS["STS"]
        bits = embed(pattern, pos, 470, rng, flip_frac=0.45)  # майже випадково
        r = check_burst_patterns(bits)
        self.assertFalse(r.detected)

    def test_tolerates_small_start_offset(self):
        rng = np.random.default_rng(4)
        pattern, pos = KNOWN_FIELDS["NTS"]
        bits = embed(pattern, pos + 5, 470, rng)   # зсув старту на 5 біт
        r = check_burst_patterns(bits)
        self.assertTrue(r.detected)
        self.assertEqual(r.err_rate, 0.0)

    def test_finds_field_in_second_slot_of_merged_burst(self):
        rng = np.random.default_rng(5)
        pattern, pos = KNOWN_FIELDS["FCF"]
        from pattern_check import SLOT_BITS
        bits = embed(pattern, pos + SLOT_BITS, SLOT_BITS * 2 + 40, rng)
        r = check_burst_patterns(bits)
        self.assertTrue(r.detected)

    def test_too_short_burst_not_detected(self):
        rng = np.random.default_rng(6)
        bits = rng.integers(0, 2, 10).tolist()
        r = check_burst_patterns(bits)
        self.assertFalse(r.detected)
        self.assertIsNone(r.err_rate)


class TestSummarizeRecording(unittest.TestCase):
    def test_empty_recording(self):
        s = summarize_recording([])
        self.assertEqual((s.n_bursts, s.n_symbols_total, s.n_detected, s.detect_fraction),
                        (0, 0, 0, 0.0))
        self.assertIsNone(s.median_err_rate_detected)

    def test_mixed_recording_fraction_and_median(self):
        rng = np.random.default_rng(7)
        fcf, pos_f = KNOWN_FIELDS["FCF"]
        good1 = FakeBurst(embed(fcf, pos_f, 470, rng), n_sym=235)
        good2 = FakeBurst(embed(fcf, pos_f, 470, rng, flip_frac=0.1), n_sym=236)
        bad = FakeBurst(rng.integers(0, 2, 470).tolist(), n_sym=235)
        s = summarize_recording([good1, good2, bad])
        self.assertEqual(s.n_bursts, 3)
        self.assertEqual(s.n_symbols_total, 235 + 236 + 235)
        self.assertEqual(s.n_detected, 2)
        self.assertAlmostEqual(s.detect_fraction, 2 / 3)
        self.assertEqual(s.per_field_counts.get("FCF"), 2)
        self.assertGreater(s.median_err_rate_detected, 0.0)   # усереднено з одним точним і одним з помилками


if __name__ == "__main__":
    unittest.main()
