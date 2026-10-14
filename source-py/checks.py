"""
Діагностичні етапи. Кожен це ізольована чиста функція: дані + конфіг -> CheckResult.
Жодних припущень про пристрій захоплення чи джерело сигналу: лише вимірювання з даних;
у повідомленнях описано, що ВИМІРЯНО, а не чому так сталося.

  0  check_meta        fs, довжина                       (до завантаження даних)
  1  sanitize          NaN/Inf -> 0 (in-place) + check_nonfinite
  2  check_levels      тиша, рівень, кліпінг, DC, кругова симетрія IQ
  3  check_spectrum    грубий зсув, ширина, DC-пік, лінія символьної швидкості, розмах потужності
  4  check_activity    результат пошуку burst'ів
  5  check_bursts      якість і стабільність демодульованих burst'ів
"""
from typing import List, Optional, Tuple

import numpy as np

from burst_search import SearchResult, power
from config import PipelineConfig
from demod import ambiguity_hz
from health import CheckResult, error, info, warn
from pattern_check import summarize_recording

EPS = 1e-30


def _db(ratio: float) -> float:
    return float(10.0 * np.log10(max(ratio, EPS)))


def _subsample(x: np.ndarray, max_n: int = 1 << 22) -> np.ndarray:
    """Рівномірне проріджування view-ом (без копії): статистика, а не повний прохід."""
    return x[:: max(1, len(x) // max_n)]


# ------------------------------------------------------------------ 0
def check_meta(n_in: int, fs: float, cfg: PipelineConfig) -> CheckResult:
    r, h = CheckResult(), cfg.health
    if not np.isfinite(fs) or fs <= 0:
        r.add(error("meta", "BAD_FS", f"некоректна частота дискретизації: {fs}", fatal=True))
        return r
    dur = n_in / fs
    r.metrics.update(meta_fs_hz=float(fs), meta_n_samples=int(n_in), meta_duration_s=float(dur))
    if fs < h.min_fs_hz:
        r.add(error("meta", "FS_TOO_LOW",
                    f"fs={fs:.0f} Гц нижче мінімуму {h.min_fs_hz:.0f} Гц (2·symbol_rate): сигнал не вміщується",
                    fs, h.min_fs_hz, fatal=True))
    if n_in == 0:
        r.add(error("meta", "EMPTY_INPUT", "у файлі немає відліків", 0, fatal=True))
    elif dur < h.min_duration_s:
        r.add(error("meta", "INPUT_TOO_SHORT",
                    f"тривалість {dur * 1e3:.1f} мс менша за мінімум {h.min_duration_s * 1e3:.0f} мс",
                    dur, h.min_duration_s, fatal=True))
    return r


# ------------------------------------------------------------------ 1
def sanitize(x: np.ndarray) -> Tuple[np.ndarray, int]:
    """Замінює NaN/Inf нулями IN-PLACE (копія лише якщо масив read-only). Повертає (x, кількість)."""
    bad = int(x.size - np.count_nonzero(np.isfinite(x)))
    if bad:
        if not x.flags.writeable:
            x = x.copy()
        np.nan_to_num(x, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    return x, bad


def check_nonfinite(bad: int, n: int, cfg: PipelineConfig) -> CheckResult:
    r = CheckResult()
    frac = bad / max(n, 1)
    r.metrics["input_nonfinite_frac"] = float(frac)
    if frac > cfg.health.nonfinite_err_frac:
        r.add(error("input", "NONFINITE_TOO_MANY",
                    f"{bad} відліків ({frac:.2%}) нескінченні або NaN: дані пошкоджено",
                    frac, cfg.health.nonfinite_err_frac, fatal=True))
    elif bad:
        r.add(warn("input", "NONFINITE_SAMPLES",
                   f"{bad} відліків NaN/Inf замінено нулями", frac))
    return r


# ------------------------------------------------------------------ 2
def check_levels(x: np.ndarray, cfg: PipelineConfig) -> CheckResult:
    r, h = CheckResult(), cfg.health
    s = _subsample(x)
    p = power(s)
    mean_p = float(p.mean(dtype=np.float64))
    rms = float(np.sqrt(mean_p))
    r.metrics["level_rms_dbfs"] = _db(mean_p)          # 10*log10(rms^2) = 20*log10(rms)
    if rms < h.silence_rms:
        r.add(error("levels", "SILENT_INPUT",
                    f"RMS={rms:.2e} (повна шкала 1.0) нижче {h.silence_rms:.0e}: вхід порожній або майже нульовий",
                    rms, h.silence_rms, fatal=True))
        return r
    if rms < h.low_level_rms:
        r.add(warn("levels", "LOW_LEVEL",
                   f"RMS={rms:.2e}: дуже низький рівень, корисний сигнал займає мало розрядів",
                   rms, h.low_level_rms))
    clip = float(np.mean((np.abs(s.real) >= h.clip_level) | (np.abs(s.imag) >= h.clip_level)))
    r.metrics["level_clip_frac"] = clip
    if clip > h.clip_err_frac:
        r.add(error("levels", "CLIPPING",
                    f"{clip:.2%} відліків на межі шкали: сигнал обрізано, демодуляція спотворена",
                    clip, h.clip_err_frac))
    elif clip > h.clip_warn_frac:
        r.add(warn("levels", "CLIPPING", f"{clip:.2%} відліків на межі шкали", clip, h.clip_warn_frac))
    dc = float(abs(s.mean(dtype=np.complex128)) / rms)
    r.metrics["level_dc_ratio"] = dc
    if dc > h.dc_warn_ratio:
        r.add(warn("levels", "DC_OFFSET",
                   f"середнє IQ складає {dc:.2f} від RMS (постійна складова)", dc, h.dc_warn_ratio))
    circ = float(abs((s * s).mean(dtype=np.complex128)) / mean_p)
    r.metrics["level_circularity"] = circ
    if circ > h.circularity_warn:
        r.add(warn("levels", "IQ_IMPROPER",
                   f"|mean(x²)|/mean|x|²={circ:.2f}: I і Q статистично не рівноправні "
                   "(дисбаланс IQ або сигнал з некруглою модуляцією)", circ, h.circularity_warn))
    return r


# ------------------------------------------------------------------ 3
def _select_blocks(n_blocks: int, max_blocks: int) -> np.ndarray:
    if n_blocks <= max_blocks:
        return np.arange(n_blocks)
    return np.unique(np.linspace(0, n_blocks - 1, max_blocks).astype(np.int64))


def check_spectrum(xw: np.ndarray, cfg: PipelineConfig) -> CheckResult:
    """xw: IQ на робочій частоті, ДО matched filter."""
    r, h, fe = CheckResult(), cfg.health, cfg.front
    fs, nfft = fe.work_fs_hz, h.spec_nfft
    nb = len(xw) // nfft
    if nb < 8:
        r.add(info("spectrum", "SPEC_SKIPPED", "замало відліків для спектрального аналізу"))
        return r
    X = xw[: nb * nfft].reshape(nb, nfft)
    sel = _select_blocks(nb, h.spec_max_blocks)
    B = 256

    bp = np.empty(len(sel))                                  # потужність блоків
    for i in range(0, len(sel), B):
        bp[i:i + B] = power(X[sel[i:i + B]]).mean(axis=1)
    p5, p95 = np.percentile(bp, [5, 95])
    swing = _db((p95 + EPS) / (p5 + EPS))
    r.metrics["spec_power_swing_db"] = swing
    active = bp > np.percentile(bp, 10) * 10 ** (h.spec_active_db / 10)
    if active.sum() < 3:
        active[:] = True
    act = sel[active]
    if len(act) > h.spec_max_active:
        act = act[np.linspace(0, len(act) - 1, h.spec_max_active).astype(np.int64)]
    r.metrics["spec_active_blocks"] = int(len(act))
    r.metrics["spec_blocks"] = int(len(sel))

    win = np.hanning(nfft).astype(np.float32)
    P = np.zeros(nfft)
    E = np.zeros(nfft // 2 + 1)
    for i in range(0, len(act), B):
        blk = X[act[i:i + B]]
        F = np.fft.fft(blk * win, axis=1)
        P += (F.real ** 2 + F.imag ** 2).sum(axis=0)
        env = power(blk)
        env -= env.mean(axis=1, keepdims=True)
        G = np.fft.rfft(env * win, axis=1)
        E += (G.real ** 2 + G.imag ** 2).sum(axis=0)
    P /= len(act)
    E /= len(act)

    S = np.convolve(np.fft.fftshift(P), np.ones(5) / 5, mode="same")
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs))
    c0 = nfft // 2
    noise = float(np.percentile(S, h.spec_noise_percentile))
    mask = S > noise * 10 ** (h.spec_signal_db / 10)
    r.metrics["spec_noise_floor_db"] = _db(noise)

    if mask.sum() < 8:
        r.add(warn("spectrum", "SPEC_NO_SIGNAL",
                   "у спектрі немає виділеної смуги над шумом: сигналу не знайдено або він нижче порога "
                   f"(поріг {h.spec_signal_db:.0f} дБ над шумом)"))
        return r

    Sig = np.where(mask, S - noise, 0.0)
    Sig[c0 - 3:c0 + 4] = 0.0                                  # DC-пік не псує центроїд і ширину
    tot = Sig.sum()
    if tot <= 0:
        return r
    centroid = float((freqs * Sig).sum() / tot)
    cs = np.cumsum(Sig)
    lo = float(freqs[np.searchsorted(cs, 0.005 * tot)])
    hi = float(freqs[min(np.searchsorted(cs, 0.995 * tot), nfft - 1)])
    bw, bw_exp = hi - lo, fe.symbol_rate_hz * (1 + fe.rrc_rolloff)
    r.metrics.update(spec_coarse_offset_hz=centroid, spec_bw99_hz=bw, spec_bw_ratio=bw / bw_exp)

    limit = ambiguity_hz(fe.symbol_rate_hz)
    if abs(centroid) > limit:
        r.add(error("spectrum", "COARSE_OFFSET",
                    f"центр потужності сигналу {centroid:+.0f} Гц виходить за межу однозначності ±{limit:.0f} Гц: "
                    "оцінка тонкого зсуву буде хибною (згортання фази). Зніміть грубий зсув до обробки",
                    centroid, limit))
    elif abs(centroid) > h.coarse_warn_frac * limit:
        r.add(warn("spectrum", "COARSE_OFFSET",
                   f"центр потужності {centroid:+.0f} Гц близько до межі однозначності ±{limit:.0f} Гц",
                   centroid, h.coarse_warn_frac * limit))
    ratio = bw / bw_exp
    if not (h.bw_min_ratio <= ratio <= h.bw_max_ratio):
        r.add(warn("spectrum", "BANDWIDTH",
                   f"ширина 99% потужності {bw:.0f} Гц це {ratio:.2f}× від очікуваної {bw_exp:.0f} Гц "
                   f"(symbol_rate·(1+rolloff)): не схоже на один канал заданого типу",
                   ratio, h.bw_max_ratio))

    near = np.r_[S[c0 - 60:c0 - 10], S[c0 + 11:c0 + 61]]
    dc_db = _db(S[c0 - 1:c0 + 2].max() / max(float(np.median(near)), EPS))
    r.metrics["spec_dc_spike_db"] = dc_db
    if dc_db > h.dc_spike_warn_db:
        r.add(warn("spectrum", "DC_SPIKE",
                   f"на 0 Гц є пік {dc_db:.1f} дБ над сусідніми бінами", dc_db, h.dc_spike_warn_db))

    k0 = int(round(fe.symbol_rate_hz / fs * nfft))
    if k0 + 41 < len(E):
        ref = float(np.median(np.r_[E[k0 - 40:k0 - 6], E[k0 + 7:k0 + 41]]))
        line_db = _db(E[k0 - 1:k0 + 2].max() / max(ref, EPS))
        r.metrics["spec_symline_db"] = line_db
        if line_db < h.symline_min_db:
            r.add(warn("spectrum", "SYMBOL_LINE",
                       f"лінія символьної швидкості {fe.symbol_rate_hz:.0f} Гц у спектрі обвідної слабка "
                       f"({line_db:.1f} дБ): сигнал не має очікуваної символьної структури або завеликий шум; "
                       "оцінка timing буде ненадійною", line_db, h.symline_min_db))
    if swing < h.continuous_swing_db:
        r.add(warn("spectrum", "CONTINUOUS_SIGNAL",
                   f"розмах потужності між блоками лише {swing:.1f} дБ за наявності сигналу: пауз немає. "
                   "Режим search.noise_mode=global тут не працює, використайте fixed або local",
                   swing, h.continuous_swing_db))
    return r


# ------------------------------------------------------------------ 4
def check_activity(sr: SearchResult, n_work: int, cfg: PipelineConfig) -> CheckResult:
    r, h = CheckResult(), cfg.health
    duty = sum(e - s for s, e in sr.merged) / max(n_work, 1)
    n_merged, n_final = len(sr.merged), len(sr.final)
    r.metrics.update(act_duty=float(duty), act_n_segments=n_merged, act_n_final=n_final)
    if n_final:
        r.metrics["act_median_len_sym"] = float(np.median([e - s for s, e in sr.final]) / cfg.search.sps)
    if n_final == 0:
        r.add(warn("activity", "NO_BURSTS",
                   f"burst'ів не знайдено (сегментів: raw={len(sr.raw)}, merged={n_merged}, "
                   f"після фільтра довжини={len(sr.filtered)}). Перевірте search.on_db, search.noise_mode, "
                   "search.min_len_sym"))
    elif n_merged and n_final / n_merged < h.segments_short_frac:
        r.add(warn("activity", "SEGMENTS_TOO_SHORT",
                   f"лише {n_final} з {n_merged} сегментів пройшли фільтр довжини та обрізання країв",
                   n_final / n_merged, h.segments_short_frac))
    return r


# ------------------------------------------------------------------ 5
def check_bursts(bursts, rejected: int, failed: int, first_error: Optional[str],
                 cfg: PipelineConfig, spec_offset_hz: Optional[float] = None) -> CheckResult:
    r, h = CheckResult(), cfg.health
    n = len(bursts)
    r.metrics.update(burst_ok=n, burst_rejected=rejected, burst_failed=failed)
    if failed:
        r.add(error("bursts", "BURST_EXCEPTION",
                    f"{failed} burst'ів не оброблено через виняток; перший: {first_error}", failed))
    total = n + rejected
    if total and rejected / total > h.rejected_share_warn:
        r.add(warn("bursts", "MANY_REJECTED",
                   f"{rejected} з {total} burst'ів відкинуто за quality.min_coherence",
                   rejected / total, h.rejected_share_warn))
    if n == 0:
        return r
    coh = np.array([b.coherence for b in bursts])
    freq = np.array([b.freq_hz for b in bursts])
    rms = np.array([b.phase_rms_deg for b in bursts])
    limit = ambiguity_hz(cfg.front.symbol_rate_hz)
    near = float(np.mean(np.abs(freq) > h.near_limit_frac * limit))
    r.metrics.update(burst_coherence_median=float(np.median(coh)),
                     burst_coherence_p10=float(np.percentile(coh, 10)),
                     burst_phase_rms_median_deg=float(np.median(rms)),
                     burst_freq_median_hz=float(np.median(freq)),
                     burst_freq_std_hz=float(np.std(freq)),
                     burst_near_limit_share=near)
    if spec_offset_hz is not None:
        diff = float(np.median(freq) - spec_offset_hz)
        r.metrics["burst_vs_spec_offset_hz"] = diff
        if abs(diff) > h.freq_mismatch_hz:
            step = cfg.front.symbol_rate_hz / 4
            r.add(error("bursts", "FREQ_ALIAS",
                        f"зсув за burst'ами ({np.median(freq):+.0f} Гц) розходиться зі спектральним центром "
                        f"({spec_offset_hz:+.0f} Гц) на {diff:+.0f} Гц (період згортання {step:.0f} Гц): "
                        "фазу, найімовірніше, згорнуто, біти недостовірні",
                        diff, h.freq_mismatch_hz))
    if np.median(coh) < h.coh_median_min:
        r.add(warn("bursts", "LOW_COHERENCE",
                   f"медіана когерентності {np.median(coh):.2f}: сигнал слабо схожий на π/4-DQPSK "
                   "(шум, інша модуляція або інша символьна швидкість)",
                   float(np.median(coh)), h.coh_median_min))
    if near >= h.near_limit_share_warn:
        r.add(warn("bursts", "FREQ_NEAR_LIMIT",
                   f"у {near:.0%} burst'ів |f| > {h.near_limit_frac:.0%} межі однозначності ±{limit:.0f} Гц: "
                   "можливе згортання фази, біти недостовірні", near, h.near_limit_share_warn))
    if n >= 3 and np.std(freq) > h.freq_spread_warn_hz:
        r.add(warn("bursts", "FREQ_UNSTABLE",
                   f"зсув частоти між burst'ами розкиданий (σ={np.std(freq):.0f} Гц): перевірте, "
                   "чи в записі одне джерело й чи частота не дрейфує",
                   float(np.std(freq)), h.freq_spread_warn_hz))
    return r


# ------------------------------------------------------------------ 6
def check_patterns(bursts, cfg: PipelineConfig) -> CheckResult:
    """Оцінка якості виявлення ЕМПІРИЧНИХ фіксованих послідовностей TETRA
    (FCF/STS/NTS, pattern_check.py) у вже демодульованих бітах burst'ів.
    Незалежна від порогів пошуку burst'ів перевірка: чи це взагалі схоже
    на TETRA на рівні бітового вмісту, а не лише форми сигналу (coherence)."""
    r = CheckResult()
    summ = summarize_recording(bursts)
    r.metrics.update(
        pattern_n_bursts=summ.n_bursts,
        pattern_n_symbols_total=summ.n_symbols_total,
        pattern_n_detected=summ.n_detected,
        pattern_detect_fraction=summ.detect_fraction,
    )
    if summ.median_err_rate_detected is not None:
        r.metrics["pattern_median_err_rate"] = summ.median_err_rate_detected
    for name, cnt in summ.per_field_counts.items():
        r.metrics[f"pattern_count_{name}"] = cnt
    if summ.n_bursts and summ.detect_fraction == 0.0:
        r.add(warn("patterns", "NO_PATTERNS_FOUND",
                   "жодної з емпіричних послідовностей FCF/STS/NTS не знайдено в жодному burst'і: "
                   "або це не TETRA, або дуже слабкий сигнал/неправильна демодуляція"))
    return r
