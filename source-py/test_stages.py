"""Тести етапів A, C, D, пайплайна і конфігу.
Запуск з кореня проєкту:  python3 -m unittest discover -s tests -t . -v"""
import unittest
from dataclasses import replace

import numpy as np

import demod, front_end, symbols
from config import (FrontEndConfig, MapConfig, PipelineConfig,
                                TimingConfig, apply_overrides)
from pipeline import run
from synth import FE, H, ber_aligned, cnoise, make_signal, tx_burst

IDEAL = np.array([np.pi / 4, 3 * np.pi / 4, -3 * np.pi / 4, -np.pi / 4])


class TestFrontEnd(unittest.TestCase):
    def test_rrc_unit_energy_symmetric(self):
        self.assertAlmostEqual(float(np.sum(H ** 2)), 1.0, places=6)
        np.testing.assert_allclose(H, H[::-1], atol=1e-12)

    def test_to_work_rate_length(self):
        x = np.ones(180000, np.complex64)
        y = front_end.to_work_rate(x, 1.8e6, FE)
        self.assertAlmostEqual(len(y), 7200, delta=2)
        z = front_end.to_work_rate(x, FE.work_fs_hz, FE)
        self.assertEqual(len(z), len(x))

    def test_matched_filter_zero_delay(self):
        x = np.zeros(1000, np.complex64); x[500] = 1
        y = front_end.matched_filter(x, FE)
        self.assertEqual(int(np.argmax(np.abs(y))), 500)


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

    def test_sample_symbols_count(self):
        y = self._y(0)
        s, e = 100, len(y) - 100
        sym = symbols.sample_symbols(y, s, e, 0.0, FE, TimingConfig())
        self.assertAlmostEqual(len(sym), (e - s) / FE.sps, delta=1)


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

    def test_map_is_configurable(self):
        d = np.exp(1j * IDEAL)
        alt = MapConfig(dibit_by_quadrant=((1, 1), (1, 0), (0, 0), (0, 1)))
        self.assertEqual(demod.map_dibits(d, alt).tolist(), [1, 1, 1, 0, 0, 0, 0, 1])

    def test_quality_ideal_vs_random(self):
        rng = np.random.default_rng(3)
        coh, rms = demod.quality_metrics(np.exp(1j * rng.choice(IDEAL, 2000)))
        self.assertAlmostEqual(coh, 1.0, places=6)
        self.assertLess(rms, 1e-3)
        coh, _ = demod.quality_metrics(np.exp(1j * rng.uniform(-np.pi, np.pi, 5000)))
        self.assertLess(coh, 0.1)


class TestInPlaceAndEquivalence(unittest.TestCase):
    def test_power_matches_reference_and_uses_out(self):
        import burst_search as bs
        rng = np.random.default_rng(7)
        y = cnoise(1000, 2.0, rng).astype(np.complex64)
        ref = y.real * y.real + y.imag * y.imag
        np.testing.assert_allclose(bs.power(y), ref, rtol=1e-5)
        out = np.empty(1000, np.float32)
        self.assertIs(bs.power(y, out=out), out)
        np.testing.assert_allclose(out, ref, rtol=1e-5)

    def test_smooth_inplace_matches_out_of_place(self):
        import burst_search as bs
        p = np.random.default_rng(8).random(5000).astype(np.float32)
        ref = bs.smooth(p.copy(), 32)
        q = p.copy()
        self.assertIs(bs.smooth(q, 32, out=q), q)
        np.testing.assert_allclose(q, ref, atol=1e-6)

    def test_timing_matches_direct_formula(self):
        rng = np.random.default_rng(9)
        for n in (1000, 1001, 1002, 1003):          # різні залишки n mod sps
            seg = cnoise(n, 1.0, rng).astype(np.complex64)
            seg[::4] *= 3
            c = np.sum((np.abs(seg) ** 2) * np.exp(-2j * np.pi * np.arange(n) / 4))
            ref = (-np.angle(c) * 4 / (2 * np.pi)) % 4
            self.assertAlmostEqual(symbols.estimate_timing(seg, 4), ref, places=4)

    def test_map_dibits_matches_angle_reference(self):
        rng = np.random.default_rng(10)
        ph = rng.uniform(-np.pi, np.pi, 5000)
        ph = ph[np.abs(np.sin(2 * ph)) > 1e-3]       # не на осях
        d = np.exp(1j * ph)
        q = np.floor(np.angle(d) / (np.pi / 2)).astype(int) % 4
        ref = np.array(MapConfig().dibit_by_quadrant, np.uint8)[q].reshape(-1)
        np.testing.assert_array_equal(demod.map_dibits(d, MapConfig()), ref)

    def test_pure_functions_do_not_mutate_input(self):
        rng = np.random.default_rng(11)
        d = np.exp(1j * rng.choice(IDEAL, 300))
        before = d.copy()
        demod.estimate_freq_offset(d); demod.quality_metrics(d); demod.map_dibits(d, MapConfig())
        np.testing.assert_array_equal(d, before)
        sym = self_sym = np.exp(1j * np.cumsum(rng.choice(IDEAL, 100)))
        keep = sym.copy(); demod.diff_demod(sym)
        np.testing.assert_array_equal(sym, keep)

    def test_correct_freq_is_inplace(self):
        d = np.exp(1j * np.full(10, 0.3))
        self.assertIs(demod.correct_freq(d, 0.3), d)
        np.testing.assert_allclose(np.angle(d), 0.0, atol=1e-12)


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

    def test_defaults_come_from_constants(self):
        import config as c
        cfg = PipelineConfig()
        self.assertEqual(cfg.search.on_db, c.SEARCH_ON_DB)
        self.assertEqual(cfg.front.sps, c.SPS)

    def test_tuple_override_rejected(self):
        with self.assertRaises(ValueError):
            apply_overrides(PipelineConfig(), ["mapping.dibit_by_quadrant=1"])


if __name__ == "__main__":
    unittest.main()
