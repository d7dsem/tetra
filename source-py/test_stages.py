"""Тести етапів A, C, D, пайплайна і конфігу.
Запуск з кореня проєкту:  python3 -m unittest discover -s tests -t . -v"""
import unittest

import numpy as np

import demod, front_end, symbols
from config import MapConfig, PipelineConfig, apply_overrides
from pipeline import run
from synth import FE, ber_aligned, cnoise, make_signal, tx_burst

IDEAL = np.array([np.pi / 4, 3 * np.pi / 4, -3 * np.pi / 4, -np.pi / 4])


class TestSymbols(unittest.TestCase):
    def _y(self, delay):
        rng = np.random.default_rng(5)
        bits = rng.integers(0, 2, 600).astype(np.uint8)
        return front_end.matched_filter(tx_burst(bits, delay).astype(np.complex64), FE)

    def test_timing_estimate_tracks_delay(self):
        for delay in (0, 1, 2, 3):
            y = self._y(delay)
            tau = symbols.estimate_timing(y[100:-100], FE.sps)
            diff = (tau - delay + FE.sps / 2) % FE.sps - FE.sps / 2
            self.assertLess(abs(diff), 0.25, (delay, tau))


class TestDemod(unittest.TestCase):
    def _sym_from_phases(self, ph):
        return np.exp(1j * np.cumsum(np.concatenate(([0.0], ph))))

    def test_diff_demod_recovers_phases(self):
        rng = np.random.default_rng(1)
        ph = rng.choice(IDEAL, 200)
        d = demod.diff_demod(self._sym_from_phases(ph))
        np.testing.assert_allclose(np.angle(d), np.angle(np.exp(1j * ph)), atol=1e-9)

    def test_freq_estimate_and_correct(self):
        rng = np.random.default_rng(2)
        ph = rng.choice(IDEAL, 500)
        for theta in (0.2, -0.3, 0.0):
            d = demod.diff_demod(self._sym_from_phases(ph + theta))
            est = demod.estimate_freq_offset(d)
            self.assertAlmostEqual(est, theta, places=6)
            back = demod.correct_freq(d, est)
            np.testing.assert_allclose(np.angle(back), np.angle(np.exp(1j * ph)), atol=1e-6)

    def test_map_dibits(self):
        d = np.exp(1j * IDEAL)  # +pi/4, +3pi/4, -3pi/4, -pi/4
        bits = demod.map_dibits(d, MapConfig())
        self.assertEqual(bits.tolist(), [0, 0, 0, 1, 1, 1, 1, 0])


    def test_quality_ideal_vs_random(self):
        rng = np.random.default_rng(3)
        coh, rms = demod.quality_metrics(np.exp(1j * rng.choice(IDEAL, 2000)))
        self.assertAlmostEqual(coh, 1.0, places=6)
        self.assertLess(rms, 1e-3)
        coh, _ = demod.quality_metrics(np.exp(1j * rng.uniform(-np.pi, np.pi, 5000)))
        self.assertLess(coh, 0.1)


class TestPipeline(unittest.TestCase):
    def test_tetra_bursts_decoded(self):
        rng = np.random.default_rng(1)
        x, txs = make_signal(rng, f_off=400.0)
        res = run(x, FE.work_fs_hz)
        self.assertEqual(len(res.bursts), 3)
        for b, tx in zip(res.bursts, txs):
            self.assertAlmostEqual(b.freq_hz, 400.0, delta=15)
            self.assertGreater(b.coherence, 0.9)
            self.assertEqual(ber_aligned(b.bits, tx), 0.0)

    def test_non_tetra_burst_has_low_coherence_and_can_be_rejected(self):
        rng = np.random.default_rng(4)
        x, _ = make_signal(rng, kind="noise")
        res = run(x, FE.work_fs_hz)
        self.assertGreaterEqual(len(res.bursts), 1)
        self.assertTrue(all(b.coherence < 0.3 for b in res.bursts))
        cfg = apply_overrides(PipelineConfig(), ["quality.min_coherence=0.5"])
        res = run(x, FE.work_fs_hz, cfg)
        self.assertEqual(len(res.bursts), 0)
        self.assertGreaterEqual(res.rejected, 1)

    def test_noise_only(self):
        rng = np.random.default_rng(6)
        x = (0.05 * cnoise(40000, 1, rng)).astype(np.complex64)
        self.assertEqual(len(run(x, FE.work_fs_hz).bursts), 0)

    def test_other_input_fs(self):
        from scipy.signal import resample_poly
        rng = np.random.default_rng(1)
        x, txs = make_signal(rng)
        x2 = resample_poly(x, 25, 1).astype(np.complex64)  # 1.8 МС/с
        res = run(x2, 1.8e6)
        self.assertEqual(len(res.bursts), 3)
        self.assertEqual(ber_aligned(res.bursts[0].bits, txs[0]), 0.0)


class TestConfig(unittest.TestCase):
    def test_overrides(self):
        cfg = apply_overrides(PipelineConfig(), [
            "search.on_db=10", "search.noise_mode=local",
            "search.noise_fixed=0.01", "freq.enabled=false", "front.sps=8"])
        self.assertEqual(cfg.search.on_db, 10.0)
        self.assertEqual(cfg.search.noise_mode, "local")
        self.assertEqual(cfg.search.noise_fixed, 0.01)
        self.assertFalse(cfg.freq.enabled)
        self.assertEqual(cfg.front.work_fs_hz, 144000.0)


    def test_tuple_override_rejected(self):
        with self.assertRaises(ValueError):
            apply_overrides(PipelineConfig(), ["mapping.dibit_by_quadrant=1"])


if __name__ == "__main__":
    unittest.main()
