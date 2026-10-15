"""
Етап 0a: оцінка пам'яті ДО завантаження файлу.
  available_memory_bytes()  -> (байт, джерело) | None
  estimate_memory()         -> MemoryEstimate (чиста функція, available передається)
  format_report()           -> текст

Модель лінійна за кількістю відліків; коефіцієнти в config.py (секція MEM_*).
Доступна пам'ять = min(cgroup-ліміт мінус використане, MemAvailable).
Своп не враховується. memory.current у cgroup включає page cache, тож оцінка
доступного трохи занижена (в безпечний бік).
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from config import PipelineConfig
from health import CheckResult, error, info, warn

MB = 1e6


def _read(path: str) -> Optional[str]:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def available_memory_bytes(meminfo: str = "/proc/meminfo",
                           cg2: str = "/sys/fs/cgroup",
                           cg1: str = "/sys/fs/cgroup/memory") -> Optional[Tuple[int, str]]:
    cands = []
    mx, cur = _read(f"{cg2}/memory.max"), _read(f"{cg2}/memory.current")
    if mx and mx != "max" and cur:
        try:
            cands.append((int(mx) - int(cur), "cgroup v2"))
        except ValueError:
            pass
    lim, use = _read(f"{cg1}/memory.limit_in_bytes"), _read(f"{cg1}/memory.usage_in_bytes")
    if lim and use:
        try:
            if int(lim) < (1 << 60):       # "необмежено" = величезне число
                cands.append((int(lim) - int(use), "cgroup v1"))
        except ValueError:
            pass
    txt = _read(meminfo)
    if txt:
        for line in txt.splitlines():
            if line.startswith("MemAvailable:"):
                cands.append((int(line.split()[1]) * 1024, "/proc/meminfo MemAvailable"))
                break
    return min(cands) if cands else None


@dataclass
class MemoryEstimate:
    n_in: int
    fs: float
    duration_s: float
    n_work: int
    resampled: bool
    stage_bytes: Dict[str, float] = field(default_factory=dict)
    bottleneck: str = ""
    peak_bytes: float = 0.0            # з overhead, без safety
    required_bytes: float = 0.0        # peak * safety
    available_bytes: Optional[int] = None
    source: str = ""
    ok: Optional[bool] = None          # None: доступну пам'ять визначити не вдалось
    max_duration_s: Optional[float] = None


def _peak(n_in: float, fs: float, cfg: PipelineConfig):
    m = cfg.memory
    work_fs = cfg.front.work_fs_hz
    resampled = abs(fs - work_fs) > 1e-6
    n_w = n_in * work_fs / fs
    dur = n_in / fs
    x = m.b_per_input_sample * n_in
    xw = m.b_per_work_sample_buf * n_w if resampled else 0.0
    bursts = m.b_per_burst * m.max_bursts_per_s * dur
    stages = {}
    if resampled:
        stages["resample"] = x + m.b_resample_pad * n_in + m.b_per_work_sample_buf * n_w
    stages["matched_filter+search"] = x + xw + m.b_per_work_sample_peak * n_w
    stages["bursts (results)"] = x + m.b_resident_per_work_sample * n_w + bursts
    name = max(stages, key=stages.get)
    return stages, name, m.runtime_overhead_mb * MB + stages[name], resampled, int(n_w)


def estimate_memory(n_in: int, fs: float, cfg: PipelineConfig,
                    available: Optional[Tuple[int, str]] = None) -> MemoryEstimate:
    stages, name, peak, resampled, n_w = _peak(n_in, fs, cfg)
    sf = cfg.memory.safety_factor
    est = MemoryEstimate(n_in=n_in, fs=fs, duration_s=n_in / fs, n_work=n_w,
                         resampled=resampled, stage_bytes=stages, bottleneck=name,
                         peak_bytes=peak, required_bytes=peak * sf)
    if available is not None:
        est.available_bytes, est.source = available
        est.ok = est.required_bytes <= est.available_bytes
        lo, hi = 0.0, 1e7                          # найбільша тривалість, що вміщується
        for _ in range(60):
            mid = (lo + hi) / 2
            if _peak(mid * fs, fs, cfg)[2] * sf <= est.available_bytes:
                lo = mid
            else:
                hi = mid
        est.max_duration_s = lo
    return est


def format_report(e: MemoryEstimate) -> str:
    L = [f"Input: {e.duration_s:.1f} s, {e.n_in/1e6:.2f} M samples @ {e.fs:.0f} Hz"
         f"{' (resampling required)' if e.resampled else ''}",
         f"Peak estimate: {e.peak_bytes/MB:.0f} MB, with margin: {e.required_bytes/MB:.0f} MB"
         f"  (bottleneck: {e.bottleneck})"]
    if e.available_bytes is None:
        L.append("Could not determine available memory, check skipped.")
    else:
        L.append(f"Available: {e.available_bytes/MB:.0f} MB ({e.source})")
        L.append("Sufficient: " + ("yes" if e.ok else
                 f"NO. Max recording duration at these settings ~= {e.max_duration_s:.0f} s"))
    return "\n".join(L)


def memory_findings(e: MemoryEstimate, cfg: PipelineConfig, mem_only: bool = False) -> CheckResult:
    """Перетворює оцінку пам'яті на знахідки для єдиного звіту."""
    r = CheckResult()
    r.metrics.update(mem_required_mb=e.required_bytes / MB)
    if e.available_bytes is None:
        r.add(info("memory", "MEM_UNKNOWN", "could not determine available memory, check skipped"))
        return r
    r.metrics["mem_available_mb"] = e.available_bytes / MB
    if e.ok:
        return r
    msg = (f"required ~={e.required_bytes / MB:.0f} MB, available {e.available_bytes / MB:.0f} MB ({e.source}); "
           f"max recording duration ~={e.max_duration_s:.0f} s")
    if cfg.memory.policy == "abort" or mem_only:
        r.add(error("memory", "MEM_INSUFFICIENT", msg + ". Shorten the recording or set memory.policy=warn",
                    e.required_bytes / MB, e.available_bytes / MB, fatal=cfg.memory.policy == "abort"))
    else:
        r.add(warn("memory", "MEM_INSUFFICIENT", msg + " (policy=warn, continuing)",
                   e.required_bytes / MB, e.available_bytes / MB))
    return r
