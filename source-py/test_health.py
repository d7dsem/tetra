"""Тести діагностики: кожен етап окремо, рівні деградації, стійкість, CLI.
Запуск: python3 -m unittest discover -s tests -t . -v"""
import json
import os
import tempfile
import unittest
from dataclasses import replace
from unittest import mock

import numpy as np
from scipy.io import wavfile

import burst_search as bs
import checks, demod, front_end
from tetra_demod import main
from config import PipelineConfig, apply_overrides
from health import CheckResult, HealthReport, Severity, error, info, warn
from pipeline import BurstResult, run
from synth import FE, cnoise, make_signal, tx_burst

CFG = PipelineConfig()
FS = FE.work_fs_hz


def codes(r):
    return {f.code for f in r.findings}


def sev(r, code):
    return next(f.severity for f in r.findings if f.code == code)


def clean(seed=1, **kw):
    return make_signal(np.random.default_rng(seed), **kw)


def mk_burst(coh=0.97, freq=400.0, rms=3.0):
    return BurstResult(start=0, end=1, t_start_s=0.0, tau=0.0, n_sym=256, freq_hz=freq,
                       coherence=coh, phase_rms_deg=rms, bits=np.zeros(4, np.uint8),
                       d=np.ones(3, np.complex64))


class TestHealthModel(unittest.TestCase):
    def test_status_levels_and_exit_codes(self):
        h = HealthReport()
        self.assertEqual((h.status, h.exit_code(), h.exit_code(True)), ("ok", 0, 0))
        h.add(info("s", "I", "x"))
        self.assertEqual(h.status, "ok")
        h.add(warn("s", "W", "x"))
        self.assertEqual((h.status, h.exit_code(), h.exit_code(True)), ("degraded", 0, 1))
        h.add(error("s", "E", "x"))
        self.assertEqual((h.status, h.exit_code(), h.exit_code(True)), ("failed", 2, 2))
        self.assertFalse(h.fatal)
        h.add(error("s", "F", "x", fatal=True))
        self.assertTrue(h.fatal)

    def test_merge_json_and_text(self):
        h = HealthReport()
        r = CheckResult(); r.add(warn("spectrum", "SOME_CODE", "повідомлення", 1.5, 1.0))
        r.metrics["spec_x"] = 2.5
        h.merge(r)
        self.assertTrue(h.has("SOME_CODE"))
        self.assertIn("SOME_CODE", h.format_text())
        self.assertIn("spec_x", h.format_text())
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.json"); h.to_json(p)
            with open(p) as fh:
                j = json.load(fh)
        self.assertEqual(j["status"], "degraded")
        self.assertEqual(j["findings"][0]["severity"], "WARN")
        self.assertEqual(j["metrics"]["spec_x"], 2.5)


class TestMeta(unittest.TestCase):
    def test_ok(self):
        r = checks.check_meta(72000, 72000.0, CFG)
        self.assertEqual(r.findings, [])
        self.assertAlmostEqual(r.metrics["meta_duration_s"], 1.0)

    def test_fatal_cases(self):
        for n, fs, code in ((0, 72000.0, "EMPTY_INPUT"), (100, 0.0, "BAD_FS"),
                            (100, float("nan"), "BAD_FS"), (10 ** 6, 10000.0, "FS_TOO_LOW"),
                            (100, 72000.0, "INPUT_TOO_SHORT")):
            r = checks.check_meta(n, fs, CFG)
            self.assertIn(code, codes(r), (n, fs))
            self.assertTrue(any(f.fatal for f in r.findings if f.code == code))


class TestSanitize(unittest.TestCase):
    def test_replaces_in_place_and_counts(self):
        x = np.ones(100, np.complex64)
        x[3] = np.nan; x[7] = complex(np.inf, 0)
        y, bad = checks.sanitize(x)
        self.assertEqual(bad, 2)
        self.assertIs(y, x)
        self.assertTrue(np.all(np.isfinite(y)))
        self.assertEqual(y[3], 0)

    def test_readonly_is_copied(self):
        x = np.ones(10, np.complex64); x[0] = np.nan; x.flags.writeable = False
        y, bad = checks.sanitize(x)
        self.assertEqual(bad, 1)
        self.assertTrue(np.all(np.isfinite(y)))

    def test_clean_untouched(self):
        x = np.ones(10, np.complex64)
        y, bad = checks.sanitize(x)
        self.assertEqual(bad, 0)
        self.assertIs(y, x)

    def test_severity_by_fraction(self):
        self.assertEqual(checks.check_nonfinite(0, 1000, CFG).findings, [])
        r = checks.check_nonfinite(2, 1000, CFG)
        self.assertEqual(sev(r, "NONFINITE_SAMPLES"), Severity.WARN)
        r = checks.check_nonfinite(100, 1000, CFG)
        self.assertEqual(sev(r, "NONFINITE_TOO_MANY"), Severity.ERROR)
        self.assertTrue(r.findings[0].fatal)


class TestLevels(unittest.TestCase):
    def setUp(self):
        self.x, _ = clean()

    def test_clean_signal_has_no_findings(self):
        r = checks.check_levels(self.x, CFG)
        self.assertEqual(r.findings, [], r.findings)
        self.assertIn("level_rms_dbfs", r.metrics)

    def test_silence_is_fatal(self):
        r = checks.check_levels(np.zeros(5000, np.complex64), CFG)
        self.assertEqual(codes(r), {"SILENT_INPUT"})
        self.assertTrue(r.findings[0].fatal)

    def test_low_level(self):
        r = checks.check_levels((self.x * 5e-4).astype(np.complex64), CFG)
        self.assertEqual(codes(r), {"LOW_LEVEL"})

    def test_clipping_warn_and_error(self):
        rng = np.random.default_rng(0)
        base = (0.05 * cnoise(20000, 1, rng)).astype(np.complex64)
        a = base.copy(); a[::200] = 1.0                       # 0.5%
        self.assertEqual(sev(checks.check_levels(a, CFG), "CLIPPING"), Severity.WARN)
        b = base.copy(); b[::10] = 1.0                        # 10%
        self.assertEqual(sev(checks.check_levels(b, CFG), "CLIPPING"), Severity.ERROR)

    def test_dc_offset(self):
        r = checks.check_levels((self.x + 0.1).astype(np.complex64), CFG)
        self.assertIn("DC_OFFSET", codes(r))

    def test_iq_improper(self):
        x = (self.x.real + 0.3j * self.x.imag).astype(np.complex64)
        self.assertIn("IQ_IMPROPER", codes(checks.check_levels(x, CFG)))


class TestSpectrum(unittest.TestCase):
    def test_clean_tetra(self):
        x, _ = clean()
        r = checks.check_spectrum(x, CFG)
        self.assertEqual(r.findings, [], r.findings)
        self.assertAlmostEqual(r.metrics["spec_coarse_offset_hz"], 400, delta=300)
        self.assertTrue(0.6 < r.metrics["spec_bw_ratio"] < 1.2)
        self.assertGreater(r.metrics["spec_symline_db"], 10)

    def test_coarse_offset_warn_then_error(self):
        r = checks.check_spectrum(clean(f_off=1400.0)[0], CFG)
        self.assertEqual(sev(r, "COARSE_OFFSET"), Severity.WARN)
        r = checks.check_spectrum(clean(f_off=3000.0)[0], CFG)
        self.assertEqual(sev(r, "COARSE_OFFSET"), Severity.ERROR)
        self.assertFalse(r.findings[0].fatal)
        self.assertAlmostEqual(r.metrics["spec_coarse_offset_hz"], 3000, delta=400)

    def test_wideband_noise_is_not_tetra_like(self):
        r = checks.check_spectrum(clean(4, kind="noise")[0], CFG)
        self.assertIn("BANDWIDTH", codes(r))
        self.assertIn("SYMBOL_LINE", codes(r))

    def test_noise_only(self):
        r = checks.check_spectrum((0.05 * cnoise(60000, 1, np.random.default_rng(6))).astype(np.complex64), CFG)
        self.assertEqual(codes(r), {"SPEC_NO_SIGNAL"})

    def test_continuous_signal_detected(self):
        rng = np.random.default_rng(2)
        s = tx_burst(rng.integers(0, 2, 20000).astype(np.uint8))
        x = (s + 0.05 * cnoise(len(s), 1, rng)).astype(np.complex64)
        self.assertIn("CONTINUOUS_SIGNAL", codes(checks.check_spectrum(x, CFG)))

    def test_dc_spike(self):
        x, _ = clean()
        r = checks.check_spectrum((x + 0.3).astype(np.complex64), CFG)
        self.assertIn("DC_SPIKE", codes(r))

    def test_too_short_is_skipped(self):
        r = checks.check_spectrum(np.ones(2000, np.complex64), CFG)
        self.assertEqual(codes(r), {"SPEC_SKIPPED"})


class TestActivityAndBursts(unittest.TestCase):
    def test_no_bursts(self):
        x = (0.05 * cnoise(60000, 1, np.random.default_rng(6))).astype(np.complex64)
        self.assertIn("NO_BURSTS", codes(run(x, FS).health))

    def test_segments_too_short(self):
        segs = [(i * 1000, i * 1000 + 50) for i in range(10)]
        sr = bs.SearchResult(cfg=CFG.search, env=np.zeros(1), floor=np.zeros(1),
                             merged=segs, final=[(0, 400)])
        self.assertIn("SEGMENTS_TOO_SHORT", codes(checks.check_activity(sr, 20000, CFG)))

    def test_burst_checks(self):
        good = [mk_burst(0.97, 400.0 + i) for i in range(5)]
        self.assertEqual(checks.check_bursts(good, 0, 0, None, CFG).findings, [])
        low = [mk_burst(0.1) for _ in range(4)]
        self.assertIn("LOW_COHERENCE", codes(checks.check_bursts(low, 0, 0, None, CFG)))
        near = [mk_burst(freq=2100.0) for _ in range(4)]
        self.assertIn("FREQ_NEAR_LIMIT", codes(checks.check_bursts(near, 0, 0, None, CFG)))
        spread = [mk_burst(freq=f) for f in (-800.0, 0.0, 900.0, 300.0)]
        self.assertIn("FREQ_UNSTABLE", codes(checks.check_bursts(spread, 0, 0, None, CFG)))
        self.assertIn("MANY_REJECTED", codes(checks.check_bursts(good, 20, 0, None, CFG)))
        r = checks.check_bursts(good, 0, 2, "ValueError: x", CFG)
        self.assertEqual(sev(r, "BURST_EXCEPTION"), Severity.ERROR)

    def test_freq_alias_from_cross_check(self):
        b = [mk_burst(0.84, -1500.0) for _ in range(3)]
        r = checks.check_bursts(b, 0, 0, None, CFG, spec_offset_hz=3000.0)
        self.assertEqual(sev(r, "FREQ_ALIAS"), Severity.ERROR)
        r = checks.check_bursts(b, 0, 0, None, CFG, spec_offset_hz=-1450.0)
        self.assertNotIn("FREQ_ALIAS", codes(r))


class TestPipelineStability(unittest.TestCase):
    def test_clean_run_is_ok(self):
        # synth.py генерує ВИПАДКОВІ біти (без TETRA-патернів), тож check_patterns
        # справедливо не знаходить FCF/STS/NTS -> статус "degraded" (NO_PATTERNS_FOUND).
        # Це коректна поведінка перевірки, не регресія: решта ознак, як і раніше, чисті.
        x, _ = clean()
        res = run(x, FS)
        self.assertEqual(res.health.status, "degraded", res.health.format_text())
        self.assertTrue(res.health.has("NO_PATTERNS_FOUND"))
        self.assertEqual(len(res.bursts), 3)
        self.assertTrue(all(b.flags == "-" for b in res.bursts))

    def test_empty_input_does_not_raise(self):
        res = run(np.zeros(0, np.complex64), FS)
        self.assertTrue(res.health.fatal)
        self.assertEqual((res.health.status, res.bursts, res.y), ("failed", [], None))

    def test_silent_input_is_fatal(self):
        res = run(np.zeros(40000, np.complex64), FS)
        self.assertTrue(res.health.has("SILENT_INPUT") and res.health.fatal)

    def test_few_nan_degrade_but_still_decode(self):
        x, _ = clean()
        x[100] = np.nan
        res = run(x, FS)
        self.assertTrue(res.health.has("NONFINITE_SAMPLES"))
        self.assertEqual((res.health.status, len(res.bursts)), ("degraded", 3))

    def test_many_nan_is_fatal(self):
        x, _ = clean()
        x[::10] = np.nan
        res = run(x, FS)
        self.assertTrue(res.health.has("NONFINITE_TOO_MANY") and res.health.fatal)
        self.assertEqual(res.bursts, [])

    def test_burst_exception_is_isolated(self):
        x, _ = clean()
        with mock.patch.object(demod, "diff_demod", side_effect=RuntimeError("boom")):
            res = run(x, FS)
        self.assertEqual((res.failed, len(res.bursts)), (3, 0))
        self.assertEqual(next(f.severity for f in res.health.findings if f.code == "BURST_EXCEPTION"),
                         Severity.ERROR)
        self.assertIn("boom", res.health.format_text())

    def test_stage_exception_is_fatal_not_raised(self):
        x, _ = clean()
        with mock.patch.object(front_end, "matched_filter", side_effect=MemoryError("oom")):
            res = run(x, FS)
        self.assertTrue(res.health.has("STAGE_EXCEPTION") and res.health.fatal)

    def test_reraise_flag_for_debugging(self):
        x, _ = clean()
        cfg = apply_overrides(CFG, ["health.reraise=true"])
        with mock.patch.object(demod, "diff_demod", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                run(x, FS, cfg)

    def test_policy_continue_vs_abort_on_coarse_offset(self):
        x, _ = clean(f_off=3000.0)
        cont = run(x, FS)
        self.assertEqual(cont.health.status, "failed")
        self.assertFalse(cont.health.fatal)
        self.assertEqual(len(cont.bursts), 3)                       # деградація: результат є
        self.assertTrue(cont.health.has("FREQ_ALIAS"))              # і помилку виявлено двічі
        ab = run(x, FS, apply_overrides(CFG, ["health.policy=abort"]))
        self.assertIsNone(ab.y)                                     # abort: зупинено після спектра
        self.assertEqual(ab.bursts, [])

    def test_flags_mark_suspect_bursts(self):
        res = run(clean(4, kind="noise")[0], FS)
        self.assertTrue(res.bursts and all("LOWCOH" in b.flags for b in res.bursts))
        res = run(clean(f_off=2000.0)[0], FS)
        self.assertTrue(all("NEARLIM" in b.flags for b in res.bursts))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.out = os.path.join(self.d, "o.txt")
        rng = np.random.default_rng(0)
        self.noise = self._wav("noise.wav", rng.normal(size=(72000, 2)) * 1500)
        self.silent = self._wav("silent.wav", np.zeros((72000, 2)))
        x, _ = clean()
        z = x / np.abs(x).max() * 0.5 * 32767
        self.tetra = self._wav("tetra.wav", np.stack([z.real, z.imag], 1))

    def _wav(self, name, arr):
        p = os.path.join(self.d, name)
        wavfile.write(p, 72000, np.asarray(arr).astype(np.int16))
        return p

    def cli(self, path, *extra):
        return main([path, "-o", self.out[:-4], *extra])

    def test_silent_input_exit_2_no_output(self):
        self.assertEqual(self.cli(self.silent), 2)
        self.assertFalse(os.path.exists(self.out))

    def test_unreadable_files_exit_2_without_traceback(self):
        bad = os.path.join(self.d, "bad.wav")
        with open(bad, "wb") as fh:
            fh.write(b"this is not a wav file at all")
        self.assertEqual(self.cli(bad), 2)
        self.assertEqual(self.cli(os.path.join(self.d, "missing.wav")), 2)

    def test_degraded_exit_codes_and_strict(self):
        self.assertEqual(self.cli(self.noise), 0)
        self.assertTrue(os.path.exists(self.out))
        self.assertEqual(self.cli(self.noise, "--strict"), 1)

    def test_good_input_ok_and_flags_column(self):
        # --strict без --set memory/health... тут не 0: синтетичні биты random,
        # NO_PATTERNS_FOUND дає "degraded" -> exit 1 за --strict (див. test_clean_run_is_ok).
        self.assertEqual(self.cli(self.tetra, "--strict"), 1)
        with open(self.out) as fh:
            first = next(l for l in fh if not l.startswith("#")).split()
        # t_start_s start_sample n_samples n_bits n_sym snr_db freq_hz coherence phase_rms_deg flags bits
        self.assertEqual(len(first), 11)
        self.assertEqual(first[9], "-")
        self.assertEqual(int(first[3]), len(first[10]))
        self.assertTrue(set(first[10]) <= {"0", "1"})

    def test_report_json_and_diagnose_only(self):
        rep = os.path.join(self.d, "rep.json")
        self.assertEqual(self.cli(self.noise, "--diagnose-only", "--report", rep), 0)
        self.assertFalse(os.path.exists(self.out))
        with open(rep) as fh:
            j = json.load(fh)
        self.assertEqual(j["status"], "degraded")
        self.assertIn("spec_power_swing_db", j["metrics"])
        self.assertIn("SPEC_NO_SIGNAL", {f["code"] for f in j["findings"]})


if __name__ == "__main__":
    unittest.main()
