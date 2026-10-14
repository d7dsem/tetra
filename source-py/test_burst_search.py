"""Тести етапів пошуку. Запуск з кореня проєкту: python3 -m unittest discover -s tests -t . -v"""
import unittest

import numpy as np

import burst_search as bs
from config import SearchConfig


def cnoise(n, p, rng):
    return np.sqrt(p / 2) * (rng.normal(size=n) + 1j * rng.normal(size=n))


class TestSmooth(unittest.TestCase):
    def test_constant_and_length(self):
        out = bs.smooth(np.ones(1000, dtype=np.float32), 32)
        self.assertEqual(len(out), 1000)
        np.testing.assert_allclose(out, 1.0, atol=1e-5)  # краї теж без просадки

    def test_step_width(self):
        p = np.concatenate((np.zeros(500), np.ones(500))).astype(np.float32)
        out = bs.smooth(p, 32)
        width = np.sum((out > 0.01) & (out < 0.99))
        self.assertTrue(28 <= width <= 34, width)


class TestNoiseFloor(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(0)

    def test_global_near_noise_power(self):
        env = bs.smooth(bs.power(cnoise(200000, 1.0, self.rng)), 32)
        f = bs.estimate_noise_floor(env, SearchConfig())[0]
        self.assertTrue(0.6 < f < 1.0, f)

    def test_local_tracks_level_change(self):
        y = np.concatenate((cnoise(20000, 1.0, self.rng), cnoise(20000, 10.0, self.rng)))
        env = bs.smooth(bs.power(y), 32)
        cfg = SearchConfig(noise_mode="local", noise_block_sym=500)
        f = bs.estimate_noise_floor(env, cfg)
        self.assertTrue(f[35000] / f[5000] > 6)
        g = bs.estimate_noise_floor(env, SearchConfig(noise_mode="global"))
        self.assertAlmostEqual(g[5000], g[35000])

    def test_fixed(self):
        f = bs.estimate_noise_floor(np.ones(10, np.float32),
                                    SearchConfig(noise_mode="fixed", noise_fixed=0.5))
        np.testing.assert_allclose(f, 0.5)
        with self.assertRaises(ValueError):
            bs.estimate_noise_floor(np.ones(10, np.float32), SearchConfig(noise_mode="fixed"))


class TestDetect(unittest.TestCase):
    def test_mask_to_segments(self):
        m = np.array([0, 1, 1, 0, 0, 1, 0, 1, 1, 1], bool)
        self.assertEqual(bs.mask_to_segments(m), [(1, 3), (5, 6), (7, 10)])
        self.assertEqual(bs.mask_to_segments(np.ones(5, bool)), [(0, 5)])
        self.assertEqual(bs.mask_to_segments(np.zeros(5, bool)), [])

    def _env(self):
        # 0 dB, 10 dB, 6 dB (між off=5 і on=8), 10 dB, 0 dB
        parts = [(1.0, 100), (10.0, 100), (4.0, 50), (10.0, 100), (1.0, 100)]
        return np.concatenate([np.full(n, v) for v, n in parts]).astype(np.float32)

    def test_hysteresis_keeps_dip(self):
        env = self._env()
        segs = bs.detect_segments(env, np.ones_like(env), on_db=8, off_db=5)
        self.assertEqual(segs, [(100, 350)])

    def test_single_threshold_splits(self):
        env = self._env()
        segs = bs.detect_segments(env, np.ones_like(env), on_db=8, off_db=8)
        self.assertEqual(segs, [(100, 200), (250, 350)])

    def test_weak_plateau_rejected(self):
        env = np.ones(300, np.float32); env[100:200] = 4.0  # 6 дБ: > off, < on
        self.assertEqual(bs.detect_segments(env, np.ones_like(env), 8, 5), [])

    def test_bad_thresholds(self):
        with self.assertRaises(ValueError):
            bs.detect_segments(np.ones(5, np.float32), np.ones(5, np.float32), 5, 8)


class TestPostProcessing(unittest.TestCase):
    def test_merge(self):
        segs = [(0, 10), (15, 20), (100, 110)]
        self.assertEqual(bs.merge_close(segs, 5), [(0, 20), (100, 110)])
        self.assertEqual(bs.merge_close(segs, 4), segs)

    def test_filter_length(self):
        segs = [(0, 5), (10, 30), (50, 150)]
        self.assertEqual(bs.filter_length(segs, 10), [(10, 30), (50, 150)])
        self.assertEqual(bs.filter_length(segs, 10, 50), [(10, 30)])

    def test_trim(self):
        self.assertEqual(bs.trim_edges([(0, 10), (100, 104)], 3), [(3, 7)])


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(3)

    def _signal(self, starts, length=1100, n=30000, noise=0.01, sig=1.0):
        y = cnoise(n, noise, self.rng)
        for s in starts:
            y[s:s + length] += cnoise(length, sig, self.rng)
        return y

    def test_finds_bursts_at_right_place(self):
        starts = [5000, 12000, 20000]
        cfg = SearchConfig()
        res = bs.search_bursts(self._signal(starts), cfg)
        self.assertEqual(len(res.final), 3, bs.describe(res))
        for (s, e), s0 in zip(res.final, starts):
            self.assertLessEqual(abs(s - (s0 + cfg.n(cfg.trim_sym))), 24)
            self.assertLessEqual(abs(e - (s0 + 1100 - cfg.n(cfg.trim_sym))), 24)

    def test_noise_only(self):
        res = bs.search_bursts(self._signal([]), SearchConfig())
        self.assertEqual(res.final, [])

    def test_short_pulse_filtered(self):
        res = bs.search_bursts(self._signal([5000], length=200), SearchConfig())
        self.assertEqual(len(res.merged), 1)   # знайдено на етапі 5
        self.assertEqual(res.final, [])        # відсіяно на етапі 6

    def test_continuous_signal_global_fails_fixed_works(self):
        # задокументоване обмеження: без пауз global-підлога сидить на сигналі
        y = cnoise(30000, 1.0, self.rng)
        self.assertEqual(bs.search_bursts(y, SearchConfig()).final, [])
        cfg = SearchConfig(noise_mode="fixed", noise_fixed=0.01)
        self.assertEqual(len(bs.search_bursts(y, cfg).final), 1)


if __name__ == "__main__":
    unittest.main()
