"""
ЄДИНЕ МІСЦЕ ВСІХ ПАРАМЕТРІВ.

Секція CONSTANTS нижче це те, що тюнять. Dataclass-конфіги беруть звідти
значення за замовчуванням. Змінити параметр можна:
  1) тут (глобально),
  2) у коді: replace(cfg.search, on_db=10)
  3) з командного рядка: --set search.on_db=10
"""
from dataclasses import dataclass, field, replace
from typing import Optional, Tuple

# =====================================================================
#                           CONSTANTS (TUNING)
# =====================================================================

# --- Сигнал (визначено стандартом TETRA, зазвичай не чіпати) ----------
SYMBOL_RATE_HZ = 18000.0
RRC_ROLLOFF = 0.35

# --- Front-end: робочий формат після ресемплінгу ----------------------
SPS = 4                       # відліків на символ -> work fs = 72 кГц
RRC_SPAN_SYM = 12             # довжина matched filter у символах

# --- Пошук burst'ів (burst_search.py) ---------------------------------
SEARCH_SMOOTH_SYM = 8.0       # вікно згладжування обвідної, символів
SEARCH_NOISE_MODE = "global"  # "global" | "local" | "fixed"
SEARCH_NOISE_PERCENTILE = 10.0
SEARCH_NOISE_BLOCK_SYM = 2000.0   # блок для "local"
SEARCH_NOISE_FIXED = None     # |y|^2 шуму для "fixed"
SEARCH_ON_DB = 8.0            # поріг входу в burst над підлогою
SEARCH_OFF_DB = 5.0           # поріг виходу (<= ON), гістерезис
SEARCH_MERGE_GAP_SYM = 8.0    # провали не довші за це склеюються
SEARCH_MIN_LEN_SYM = 100.0
SEARCH_MAX_LEN_SYM = None
SEARCH_TRIM_SYM = 4.0         # відрізати з кожного краю burst'а

# --- Символьна синхронізація (symbols.py) -----------------------------
TIMING_FINE_UPSAMPLE = 4      # додаткова передискретизація для вибору символу
TIMING_MARGIN_SYM = 4.0       # запас навколо burst'а під фільтр ресемплера

# --- Частотний зсув (demod.py) ----------------------------------------
FREQ_CORRECTION_ENABLED = True

# --- Відображення дібітів (demod.py) ----------------------------------
# індекс квадранта dphi: 0:(0,pi/2) +pi/4, 1:(pi/2,pi) +3pi/4,
#                        2:(-pi,-pi/2) -3pi/4, 3:(-pi/2,0) -pi/4
# ПЕРЕВІРИТИ за ETSI EN 300 392-2
DIBIT_BY_QUADRANT = ((0, 0), (0, 1), (1, 1), (1, 0))

# --- Класифікація burst'ів за стандартом (pattern_check.py) ------------
# Розкладки типів burst'ів (довжини, зсуви, відомі біти) - дані стандарту, у pattern_check.BURST_LAYOUTS.
CLASSIFY_START_MIN_BITS = -4          # де може починатися справжній burst відносно початку захопленого вікна
CLASSIFY_START_MAX_BITS = 24
CLASSIFY_END_SLACK_BITS = 6           # скільки бітів burst'а може бракувати в кінці захоплення

# --- Структурне подання .bin4 (io_stage.py) ----------------------------
BIN4_DEFAULT_LAYOUT = "DNB1"          # геометрія слота, якщо тип не визначено
BIN4_DEFAULT_START_EXCESS_BITS = 4    # там само: типовий зайвий початок захоплення (медіана на записі 1_)
BIN4_SLOT_TOLERANCE_BITS = 20         # скільки бракуючих бітів у кінці ще дозволяє вважати слот наявним

# --- Контроль якості burst'а (demod.py) -------------------------------
QUALITY_MIN_COHERENCE = 0.0   # 0 = нічого не відкидати; 0..1

# --- Контроль пам'яті на вході (memcheck.py) --------------------------
MEM_POLICY = "abort"          # "abort" | "warn" | "off"
MEM_SAFETY_FACTOR = 1.25      # запас понад оцінку піку
MEM_RUNTIME_OVERHEAD_MB = 150.0   # python + numpy + scipy (виміряно ~100 МБ, з запасом)
MEM_B_PER_INPUT_SAMPLE = 8.0      # x: complex64
MEM_B_RESAMPLE_PAD = 8.0          # копія входу всередині resample_poly (припущення)
MEM_B_PER_WORK_SAMPLE_BUF = 8.0   # xw: complex64 (лише якщо був ресемплінг)
MEM_B_PER_WORK_SAMPLE_PEAK = 40.0 # пік matched filter + пошуку (виміряно ~34 на синтетиці)
MEM_B_RESIDENT_PER_WORK_SAMPLE = 12.0  # y (complex64) + env (float32), живуть до кінця
MEM_B_PER_BURST = 3000.0      # BurstResult: d + bits + об'єкт (оцінка)
MEM_MAX_BURSTS_PER_S = 70.0   # верхня межа: 1 burst на слот ~14.2 мс

# --- Діагностика та стійкість (health.py, checks.py) ------------------
# Пороги це тюнінг, а не вимоги стандарту. Жодних припущень про пристрій
# захоплення: усе міряється з самих даних. Повна шкала int16 = 1.0.
HEALTH_POLICY = "continue"       # при НЕфатальній ERROR: "continue" (деградація) | "abort"
HEALTH_RERAISE = False           # True: не ловити винятки (для налагодження)
HEALTH_MIN_DURATION_S = 0.02     # коротше: обробка безглузда (фатально)
HEALTH_MIN_FS_HZ = 36000.0       # нижче 2*symbol_rate сигнал не вміщується (фатально)
HEALTH_NONFINITE_ERR_FRAC = 0.01     # частка NaN/Inf: вище це фатально, будь-яка інша WARN
HEALTH_SILENCE_RMS = 1e-5        # RMS нижче: вхід порожній/тихий (фатально)
HEALTH_LOW_LEVEL_RMS = 1e-3      # нижче: WARN (мало розрядів АЦП у сигналі)
HEALTH_CLIP_LEVEL = 0.999        # |I| або |Q| не менше: "на межі шкали"
HEALTH_CLIP_WARN_FRAC = 1e-3
HEALTH_CLIP_ERR_FRAC = 5e-2
HEALTH_DC_WARN_RATIO = 0.1       # |mean(IQ)| / RMS
HEALTH_CIRCULARITY_WARN = 0.1    # |mean(x^2)| / mean(|x|^2): IQ-дисбаланс або некруглий сигнал
HEALTH_SPEC_NFFT = 1024
HEALTH_SPEC_MAX_BLOCKS = 4096    # скільки блоків аналізувати (рівномірно по файлу)
HEALTH_SPEC_MAX_ACTIVE = 2048
HEALTH_SPEC_ACTIVE_DB = 3.0      # блок активний, якщо потужність на стільки вище за 10-й перцентиль
HEALTH_SPEC_SIGNAL_DB = 3.0      # бін належить сигналу, якщо вище шуму на стільки
HEALTH_SPEC_NOISE_PERCENTILE = 20.0
HEALTH_COARSE_WARN_FRAC = 0.5    # частка межі однозначності (symbol_rate/8) для WARN
HEALTH_BW_MIN_RATIO = 0.6        # ширина 99% / очікувана symbol_rate*(1+rolloff)
HEALTH_BW_MAX_RATIO = 1.6
HEALTH_DC_SPIKE_WARN_DB = 10.0
HEALTH_SYMLINE_MIN_DB = 6.0      # лінія символьної швидкості в спектрі обвідної
HEALTH_CONTINUOUS_SWING_DB = 3.0 # розмах потужності блоків нижче: сигнал без пауз
HEALTH_SEGMENTS_SHORT_FRAC = 0.2 # частка сегментів, що пережили фільтр довжини
HEALTH_COH_MEDIAN_MIN = 0.5
HEALTH_FLAG_MIN_COHERENCE = 0.5  # burst з меншою когерентністю помічається LOWCOH
HEALTH_NEAR_LIMIT_FRAC = 0.8     # |f| більше цієї частки межі: NEARLIM
HEALTH_NEAR_LIMIT_SHARE_WARN = 0.1
HEALTH_FREQ_SPREAD_WARN_HZ = 300.0
HEALTH_REJECTED_SHARE_WARN = 0.5
HEALTH_FREQ_MISMATCH_HZ = 1000.0 # розбіжність центру спектра й медіани зсуву по burst'ах

# --- Груба детекція перед matched filter (coarse_detect.py) -----------
# ВИМКНЕНО за замовчуванням: перевірено лише на одному файлі (file 1),
# дає прискорення (фільтрує ~20% замість 100% файлу), але ще не прогнано
# на решті записів. Старий шлях (фільтр усього файлу) лишається дефолтом.
COARSE_ENABLED = False
COARSE_BURST_DURATION_S = 0.014167   # ETSI: тривалість таймслота TETRA
COARSE_SMOOTH_FRACTION = 1 / 128
COARSE_MERGE_FRACTION = 1 / 16       # ВАЛІДОВАНО на file 1: 1/128 дробив слабкі
                                      # burst'и (235/242), 1/16 дав 242/242 без шкоди
COARSE_MIN_LEN_FRACTION = 1 / 20

# =====================================================================
#                       DATACLASSES (структура)
# =====================================================================


@dataclass(frozen=True)
class FrontEndConfig:
    symbol_rate_hz: float = SYMBOL_RATE_HZ
    sps: int = SPS
    rrc_rolloff: float = RRC_ROLLOFF
    rrc_span_sym: int = RRC_SPAN_SYM

    @property
    def work_fs_hz(self) -> float:
        return self.symbol_rate_hz * self.sps


@dataclass(frozen=True)
class SearchConfig:
    sps: int = SPS
    smooth_sym: float = SEARCH_SMOOTH_SYM
    noise_mode: str = SEARCH_NOISE_MODE
    noise_percentile: float = SEARCH_NOISE_PERCENTILE
    noise_block_sym: float = SEARCH_NOISE_BLOCK_SYM
    noise_fixed: Optional[float] = SEARCH_NOISE_FIXED
    on_db: float = SEARCH_ON_DB
    off_db: float = SEARCH_OFF_DB
    merge_gap_sym: float = SEARCH_MERGE_GAP_SYM
    min_len_sym: float = SEARCH_MIN_LEN_SYM
    max_len_sym: Optional[float] = SEARCH_MAX_LEN_SYM
    trim_sym: float = SEARCH_TRIM_SYM

    def n(self, symbols: float) -> int:
        return int(round(symbols * self.sps))


@dataclass(frozen=True)
class TimingConfig:
    fine_upsample: int = TIMING_FINE_UPSAMPLE
    margin_sym: float = TIMING_MARGIN_SYM


@dataclass(frozen=True)
class FreqConfig:
    enabled: bool = FREQ_CORRECTION_ENABLED


@dataclass(frozen=True)
class MapConfig:
    dibit_by_quadrant: Tuple[Tuple[int, int], ...] = DIBIT_BY_QUADRANT


@dataclass(frozen=True)
class QualityConfig:
    min_coherence: float = QUALITY_MIN_COHERENCE


@dataclass(frozen=True)
class MemoryConfig:
    policy: str = MEM_POLICY
    safety_factor: float = MEM_SAFETY_FACTOR
    runtime_overhead_mb: float = MEM_RUNTIME_OVERHEAD_MB
    b_per_input_sample: float = MEM_B_PER_INPUT_SAMPLE
    b_resample_pad: float = MEM_B_RESAMPLE_PAD
    b_per_work_sample_buf: float = MEM_B_PER_WORK_SAMPLE_BUF
    b_per_work_sample_peak: float = MEM_B_PER_WORK_SAMPLE_PEAK
    b_resident_per_work_sample: float = MEM_B_RESIDENT_PER_WORK_SAMPLE
    b_per_burst: float = MEM_B_PER_BURST
    max_bursts_per_s: float = MEM_MAX_BURSTS_PER_S


@dataclass(frozen=True)
class HealthConfig:
    policy: str = HEALTH_POLICY
    reraise: bool = HEALTH_RERAISE
    min_duration_s: float = HEALTH_MIN_DURATION_S
    min_fs_hz: float = HEALTH_MIN_FS_HZ
    nonfinite_err_frac: float = HEALTH_NONFINITE_ERR_FRAC
    silence_rms: float = HEALTH_SILENCE_RMS
    low_level_rms: float = HEALTH_LOW_LEVEL_RMS
    clip_level: float = HEALTH_CLIP_LEVEL
    clip_warn_frac: float = HEALTH_CLIP_WARN_FRAC
    clip_err_frac: float = HEALTH_CLIP_ERR_FRAC
    dc_warn_ratio: float = HEALTH_DC_WARN_RATIO
    circularity_warn: float = HEALTH_CIRCULARITY_WARN
    spec_nfft: int = HEALTH_SPEC_NFFT
    spec_max_blocks: int = HEALTH_SPEC_MAX_BLOCKS
    spec_max_active: int = HEALTH_SPEC_MAX_ACTIVE
    spec_active_db: float = HEALTH_SPEC_ACTIVE_DB
    spec_signal_db: float = HEALTH_SPEC_SIGNAL_DB
    spec_noise_percentile: float = HEALTH_SPEC_NOISE_PERCENTILE
    coarse_warn_frac: float = HEALTH_COARSE_WARN_FRAC
    bw_min_ratio: float = HEALTH_BW_MIN_RATIO
    bw_max_ratio: float = HEALTH_BW_MAX_RATIO
    dc_spike_warn_db: float = HEALTH_DC_SPIKE_WARN_DB
    symline_min_db: float = HEALTH_SYMLINE_MIN_DB
    continuous_swing_db: float = HEALTH_CONTINUOUS_SWING_DB
    segments_short_frac: float = HEALTH_SEGMENTS_SHORT_FRAC
    coh_median_min: float = HEALTH_COH_MEDIAN_MIN
    flag_min_coherence: float = HEALTH_FLAG_MIN_COHERENCE
    near_limit_frac: float = HEALTH_NEAR_LIMIT_FRAC
    near_limit_share_warn: float = HEALTH_NEAR_LIMIT_SHARE_WARN
    freq_spread_warn_hz: float = HEALTH_FREQ_SPREAD_WARN_HZ
    rejected_share_warn: float = HEALTH_REJECTED_SHARE_WARN
    freq_mismatch_hz: float = HEALTH_FREQ_MISMATCH_HZ


@dataclass(frozen=True)
class CoarseConfig:
    enabled: bool = COARSE_ENABLED           # перемикач: --set coarse.enabled=true
    burst_duration_s: float = COARSE_BURST_DURATION_S
    smooth_fraction: float = COARSE_SMOOTH_FRACTION
    merge_fraction: float = COARSE_MERGE_FRACTION
    min_len_fraction: float = COARSE_MIN_LEN_FRACTION


@dataclass(frozen=True)
class PipelineConfig:
    front: FrontEndConfig = field(default_factory=FrontEndConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    freq: FreqConfig = field(default_factory=FreqConfig)
    mapping: MapConfig = field(default_factory=MapConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    coarse: CoarseConfig = field(default_factory=CoarseConfig)


# =====================================================================
#                 Перевизначення з командного рядка
# =====================================================================


def _coerce(val: str, cur):
    if val.lower() == "none":
        return None
    if isinstance(cur, bool):
        return val.lower() in ("1", "true", "yes", "on")
    if isinstance(cur, int):
        return int(val)
    if isinstance(cur, float):
        return float(val)
    if isinstance(cur, tuple):
        raise ValueError("tuple-параметри міняються лише в config.py")
    if cur is None:
        try:
            return float(val)
        except ValueError:
            return val
    return val


def apply_overrides(cfg: PipelineConfig, items) -> PipelineConfig:
    """items: ['search.on_db=10', 'quality.min_coherence=0.5', ...]"""
    for it in items or []:
        key, _, val = it.partition("=")
        group, _, name = key.partition(".")
        g = getattr(cfg, group)
        new = _coerce(val, getattr(g, name))
        cfg = replace(cfg, **{group: replace(g, **{name: new})})
    return cfg
