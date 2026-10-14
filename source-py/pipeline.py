"""
Оркестратор. Лише викликає етапи по черзі, власного DSP тут немає.
Кожен етап обгорнуто: виняток не валить процес, а стає ERROR-знахідкою (fatal),
якщо не ввімкнено health.reraise.

  0  check_meta                         checks      (fs, довжина)
  1  sanitize + check_nonfinite         checks
  2  check_levels                       checks
  A  to_work_rate                       front_end
  3  check_spectrum                     checks      (до matched filter)
     matched_filter                     front_end
  B  search_bursts                      burst_search
  4  check_activity                     checks
  C  estimate_timing, sample_symbols    symbols     (по burst'ах, з ізоляцією винятків)
  D  diff_demod ... map_dibits          demod
  5  check_bursts                       checks
"""
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

import burst_search, checks, coarse_detect, demod, front_end, symbols
from snr_estimate import _power as _raw_power, estimate_burst_snr_db
from config import PipelineConfig
from health import HealthReport, error


@dataclass
class BurstResult:
    start: int            # відліки на work fs
    end: int
    t_start_s: float
    tau: float
    n_sym: int
    freq_hz: float
    coherence: float
    phase_rms_deg: float
    bits: np.ndarray
    d: np.ndarray         # диф. символи після корекції (для діаграм)
    snr_db: Optional[float] = None   # часовий метод, на сирому масиві (до matched filter)
    flags: str = "-"      # LOWCOH, NEARLIM (через кому) або "-"


@dataclass
class PipelineResult:
    cfg: PipelineConfig
    health: HealthReport
    y: Optional[np.ndarray] = None                 # після matched filter
    search: Optional[burst_search.SearchResult] = None
    bursts: List[BurstResult] = field(default_factory=list)
    rejected: int = 0
    failed: int = 0


def demod_burst(y: np.ndarray, s: int, e: int, cfg: PipelineConfig,
                raw_power: Optional[np.ndarray] = None, all_segments=None,
                noise_window_samples: int = 0) -> Optional[BurstResult]:
    fe = cfg.front
    tau = symbols.estimate_timing(y[s:e], fe.sps)
    sym = symbols.sample_symbols(y, s, e, tau, fe, cfg.timing)
    if len(sym) < 3:
        return None
    d = demod.diff_demod(sym)
    theta = 0.0
    if cfg.freq.enabled:
        theta = demod.estimate_freq_offset(d)
        demod.correct_freq(d, theta)     # in-place
    coh, rms = demod.quality_metrics(d)
    snr_db = None
    if raw_power is not None and all_segments is not None:
        snr_db = estimate_burst_snr_db(raw_power, (s, e), all_segments, noise_window_samples)
    freq_hz = theta * fe.symbol_rate_hz / (2 * np.pi)
    flags = []
    if coh < cfg.health.flag_min_coherence:
        flags.append("LOWCOH")
    if abs(freq_hz) > cfg.health.near_limit_frac * demod.ambiguity_hz(fe.symbol_rate_hz):
        flags.append("NEARLIM")
    return BurstResult(
        start=s, end=e, t_start_s=s / fe.work_fs_hz, tau=tau, n_sym=len(d) + 1,
        freq_hz=freq_hz, coherence=coh, phase_rms_deg=rms,
        bits=demod.map_dibits(d, cfg.mapping), d=d, snr_db=snr_db, flags=",".join(flags) or "-")


def _coarse_matched_filter(xw: np.ndarray, cfg: PipelineConfig) -> np.ndarray:
    """Альтернатива до front_end.matched_filter(xw, cfg.front) на весь файл:
    груба детекція активних ділянок (coarse_detect.py) + matched filter лише
    на них (з запасом filter_margin_samples під крайові ефекти згортки).
    Решта масиву лишається нулями. Вимикається/вмикається cfg.coarse.enabled.

    ПЕРЕВІРЕНО на file 1 з coarse.merge_fraction=1/16 (поточне значення за
    замовчуванням у config.py): дає ТОЙ САМИЙ результат (242/242 burst'ів,
    коефіцієнти в межах 0.08 коефіцієнта когерентності), що й повний прохід.
    На решті 4 файлів ще НЕ перевірено - звідси cfg.coarse.enabled=False
    за замовчуванням."""
    margin = coarse_detect.filter_margin_samples(cfg.front.rrc_span_sym, cfg.front.sps)
    segments = coarse_detect.coarse_detect(xw, cfg.front.work_fs_hz, cfg.coarse)
    n = len(xw)
    y = np.zeros(n, dtype=np.complex64)
    for cs, ce in segments:
        s0, e0 = max(0, cs - margin), min(n, ce + margin)
        y[s0:e0] = front_end.matched_filter(xw[s0:e0], cfg.front)
    return y


def _guard(h: HealthReport, cfg: PipelineConfig, stage: str, fn, *args):
    """Виконує етап; виняток -> fatal ERROR (або повторно, якщо health.reraise)."""
    try:
        return fn(*args), True
    except Exception as ex:                                  # noqa: BLE001
        if cfg.health.reraise:
            raise
        h.add(error(stage, "STAGE_EXCEPTION", f"{type(ex).__name__}: {ex}", fatal=True))
        return None, False


def _stop(h: HealthReport, cfg: PipelineConfig) -> bool:
    """Зупинитись: є fatal, або policy=abort і вже є ERROR."""
    return h.fatal or (cfg.health.policy == "abort" and h.status == "failed")


def run(x: np.ndarray, fs: float, cfg: Optional[PipelineConfig] = None,
        health: Optional[HealthReport] = None) -> PipelineResult:
    cfg = cfg or PipelineConfig()
    h = health if health is not None else HealthReport()
    res = PipelineResult(cfg=cfg, health=h)

    h.merge(checks.check_meta(len(x), fs, cfg))
    if _stop(h, cfg):
        return res

    out, ok = _guard(h, cfg, "input", checks.sanitize, x)
    if not ok:
        return res
    x, bad = out
    h.merge(checks.check_nonfinite(bad, len(x), cfg))
    if _stop(h, cfg):
        return res

    r, ok = _guard(h, cfg, "levels", checks.check_levels, x, cfg)
    if not ok:
        return res
    h.merge(r)
    if _stop(h, cfg):
        return res

    xw, ok = _guard(h, cfg, "front_end", front_end.to_work_rate, x, fs, cfg.front)
    if not ok:
        return res
    r, ok = _guard(h, cfg, "spectrum", checks.check_spectrum, xw, cfg)
    if not ok:
        return res
    h.merge(r)
    if _stop(h, cfg):
        return res

    raw_power = _raw_power(xw)  # для SNR: ДО видалення xw нижче

    if cfg.coarse.enabled:
        y, ok = _guard(h, cfg, "front_end", _coarse_matched_filter, xw, cfg)
    else:
        y, ok = _guard(h, cfg, "front_end", front_end.matched_filter, xw, cfg.front)
    if not ok:
        return res
    del xw  # звільнити буфер, якщо це була окрема копія після ресемплінгу
    res.y = y

    sr, ok = _guard(h, cfg, "search", burst_search.search_bursts, y, cfg.search)
    if not ok:
        return res
    res.search = sr
    h.merge(checks.check_activity(sr, len(y), cfg))

    noise_window = int(round(cfg.coarse.burst_duration_s * cfg.front.work_fs_hz))  # ETSI: таймслот
    first_error = None
    for s, e in sr.final:
        try:
            b = demod_burst(y, s, e, cfg, raw_power, sr.final, noise_window)
        except Exception as ex:                              # noqa: BLE001
            if cfg.health.reraise:
                raise
            res.failed += 1
            first_error = first_error or f"{type(ex).__name__}: {ex}"
            continue
        if b is None or b.coherence < cfg.quality.min_coherence:
            res.rejected += 1
            continue
        res.bursts.append(b)

    h.merge(checks.check_bursts(res.bursts, res.rejected, res.failed, first_error, cfg,
                                h.metrics.get("spec_coarse_offset_hz")))
    h.merge(checks.check_patterns(res.bursts, cfg))
    return res


def describe(res: PipelineResult) -> str:
    head = f"[{res.health.status}] "
    if res.search is None:
        return head + "обробку зупинено до пошуку burst'ів"
    return (head + burst_search.describe(res.search)
            + f"  | demod ok={len(res.bursts)} rejected={res.rejected} failed={res.failed}")
