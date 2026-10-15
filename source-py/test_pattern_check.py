"""Тести pattern_check.py. Запуск: python3 -m unittest test_pattern_check"""
import unittest
from dataclasses import dataclass
from typing import List

import numpy as np

from pattern_check import KNOWN_FIELDS, SLOT_BITS, check_all_fields, summarize_recording


@dataclass
class FakeBurst:
    bits: List[int]
    n_sym: int


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


class TestKnownFields(unittest.TestCase):
    def test_lengths_match_standard(self):
        expected = {"FCF": 80, "NTS1": 22, "NTS2": 22, "NTS3": 22, "STS": 38, "ETS": 30, "TAIL": 4}
        for name, exp_len in expected.items():
            pattern, _, status = KNOWN_FIELDS[name]
            self.assertEqual(status, "ok", name)
            self.assertEqual(len(pattern), exp_len, name)


class TestCheckAllFields(unittest.TestCase):
    def test_pure_random_bits_mostly_not_detected(self):
        # TAIL - лише 4 біти, випадковий збіг має помітну ймовірність (задокументовано
        # в pattern_check.py); виключаємо його з цієї перевірки, решта - довші поля
        # (22-80 біт), для них випадковий збіг нижче 10% статистично малоймовірний.
        rng = np.random.default_rng(0)
        bits = rng.integers(0, 2, 470).tolist()
        res = check_all_fields(bits)
        ok_fields = {n: e for n, e in res.items() if e is not None and n != "TAIL"}
        self.assertTrue(all(e > 0.10 for e in ok_fields.values()), ok_fields)

    def test_exact_field_detected_for_each_known_pattern(self):
        rng = np.random.default_rng(1)
        for name, (pattern, pos, status) in KNOWN_FIELDS.items():
            if status != "ok":
                continue
            bits = embed(pattern, pos, 470, rng)
            res = check_all_fields(bits)
            self.assertEqual(res[name], 0.0, name)

    def test_phase_field_always_none(self):
        rng = np.random.default_rng(2)
        bits = rng.integers(0, 2, 470).tolist()
        self.assertIsNone(check_all_fields(bits)["PHASE"])

    def test_tolerates_small_start_offset(self):
        rng = np.random.default_rng(3)
        pattern, pos, _ = KNOWN_FIELDS["NTS1"]
        bits = embed(pattern, pos + 5, 470, rng)
        res = check_all_fields(bits)
        self.assertEqual(res["NTS1"], 0.0)

    def test_finds_field_in_second_slot_of_merged_burst(self):
        rng = np.random.default_rng(4)
        pattern, pos, _ = KNOWN_FIELDS["FCF"]
        bits = embed(pattern, pos + SLOT_BITS, SLOT_BITS * 2 + 40, rng)
        res = check_all_fields(bits)
        self.assertEqual(res["FCF"], 0.0)

    def test_too_short_for_long_fields_gives_none(self):
        # 10 біт недостатньо для будь-якого поля, крім TAIL (4 біти, позиція 0),
        # яке технічно влазить - перевіряємо довгі поля окремо, а не всі.
        rng = np.random.default_rng(5)
        bits = rng.integers(0, 2, 10).tolist()
        res = check_all_fields(bits)
        for name in ("FCF", "NTS1", "NTS2", "NTS3", "STS", "ETS"):
            self.assertIsNone(res[name], name)


class TestSummarizeRecording(unittest.TestCase):
    def test_empty_recording(self):
        s = summarize_recording([])
        self.assertEqual((s.n_bursts, s.n_symbols_total, s.n_any_detected, s.detect_fraction),
                        (0, 0, 0, 0.0))
        for name, st in s.per_field.items():
            if st.status == "ok":
                self.assertEqual(st.n_found, 0)

    def test_per_field_independent_counts(self):
        rng = np.random.default_rng(6)
        fcf, pos_f, _ = KNOWN_FIELDS["FCF"]
        nts1, pos_n, _ = KNOWN_FIELDS["NTS1"]
        b_fcf = FakeBurst(embed(fcf, pos_f, 470, rng), n_sym=235)
        b_nts = FakeBurst(embed(nts1, pos_n, 470, rng), n_sym=236)
        b_bad = FakeBurst(rng.integers(0, 2, 470).tolist(), n_sym=235)
        s = summarize_recording([b_fcf, b_nts, b_bad])
        self.assertEqual(s.n_bursts, 3)
        self.assertEqual(s.n_symbols_total, 235 + 236 + 235)
        self.assertEqual(s.per_field["FCF"].n_found, 1)
        self.assertEqual(s.per_field["NTS1"].n_found, 1)
        self.assertEqual(s.n_any_detected, 2)      # b_fcf і b_nts, b_bad - ні
        self.assertAlmostEqual(s.detect_fraction, 2 / 3)
        self.assertEqual(s.per_field["PHASE"].status, "formula")
        self.assertEqual(s.per_field["PHASE"].n_found, 0)


    def test_exact_vs_within_threshold_split(self):
        rng = np.random.default_rng(8)
        fcf, pos, _ = KNOWN_FIELDS["FCF"]
        clean = FakeBurst(embed(fcf, pos, 470, rng), n_sym=235)             # 0% помилок
        noisy = FakeBurst(embed(fcf, pos, 470, rng, flip_frac=0.05), n_sym=235)  # 5% помилок, <=10%
        s = summarize_recording([clean, noisy])
        st = s.per_field["FCF"]
        self.assertEqual(st.n_exact, 1)
        self.assertEqual(st.n_within_threshold, 1)
        self.assertEqual(st.n_found, 2)

    def test_too_many_errors_counted_nowhere(self):
        rng = np.random.default_rng(9)
        fcf, pos, _ = KNOWN_FIELDS["FCF"]
        bad = FakeBurst(embed(fcf, pos, 470, rng, flip_frac=0.45), n_sym=235)
        s = summarize_recording([bad])
        st = s.per_field["FCF"]
        self.assertEqual(st.n_exact, 0)
        self.assertEqual(st.n_within_threshold, 0)
        self.assertEqual(st.n_checked, 1)


if __name__ == "__main__":
    unittest.main()
