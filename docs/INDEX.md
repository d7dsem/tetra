# INDEX: контекст проєкту і навігація

Головний документ для швидкого входу (людині й ШІ-асистенту): де що лежить і яка частина коду відповідає за яке питання. Мета - не парсити весь код, а одразу йти у потрібний файл/функцію.

## 0. Правила для ШІ-асистента

- `docs/cheat-shit.md` - робочі нотатки власника, він постійно їх змінює. **Не читати** без прямої вказівки; не спиратися на нього як на джерело.
- У **кожен** коміт безумовно включати `docs/cheat-shit.md` (у тексті коміту не згадувати).
- Без прямої команди файли не змінювати і не комітити.
- Спершу цей INDEX, потім лише модулі зі слів "де шукати" нижче.

## 1. Контекст

Проєкт обробляє IQ-записи TETRA (π/4-DQPSK, 18 кбод) офлайн. Записи лежать поза репо (`~/Public/signals/...`).

Дві частини:

1. **`source-py/`** - Python-демодулятор: IQ -> burst'и -> сирі біти + діагностика. Канального декодування (FEC, дескремблювання, деперемежіння) немає.
2. **`dmo/`** - C-декодер каналів прямого режиму DMO (DSB: SCH/S, SCH/H), працює з файлом бітів.

Зовнішній `osmo-tetra` (`~/Public/repos/osmo-tetra`, `tetra-rx`): декодує **лише TMO downlink (базова станція -> абонент)**, DMO не підтримує; статус "обмежено придатний". Через це існує `dmo/`. З osmo-tetra `dmo/osmo_leaf` компілює лише "листові" файли lower_mac (скремблер, інтерлівер, CRC, Viterbi) прямо з його сирців.

## 2. Потік даних

```
IQ (.wav 2ch int16 / .cs16)
  -> bin/tetra_demod  (source-py/tetra_demod.py -> pipeline.run)
       -> out.txt   (burst'и + статистика)
       -> out.bin   (потік бітів для декодерів)   .bin2/.bin3/.bin4 - лише для перегляду
  -> source-py/wav-proc/tetra_prep.py   (запис 25 кГц для osmo tetra-rx)
  -> source-py/tetra_bits_export.py     (біти burst'ів у форматі tetra-rx: 1 біт = 1 байт)
  -> dmo/dmo_rx  (читає файл бітів, 1 біт/байт; DMO)
```

## 3. Етапи пайплайна (порядок = `pipeline.run`, `source-py/pipeline.py`)

| # | Етап | Модуль / функція |
|---|---|---|
| 0 | перевірка fs, довжини | `checks.check_meta` |
| 1 | NaN/Inf | `checks.sanitize`, `checks.check_nonfinite` |
| 2 | рівні, кліппінг | `checks.check_levels` |
| A | ресемплінг до work fs = 72 кГц (SPS=4) | `front_end.to_work_rate` |
| 3 | спектр (до matched filter) | `checks.check_spectrum` |
| - | RRC matched filter (rolloff 0.35, 12 символів) | `front_end.matched_filter` (альтернатива: `pipeline._coarse_matched_filter`, `config.COARSE_ENABLED=False`) |
| B | **пошук меж burst'ів** | `burst_search.search_bursts` |
| 4 | активність | `checks.check_activity` |
| C-D | по кожному burst'у: таймінг, символи, диф. демодуляція, частота, якість, біти, SNR, прапорці | `pipeline.demod_burst` |
| 5 | підсумкові перевірки | `checks.check_bursts`, `checks.check_patterns` |

Кожен етап обгорнуто `pipeline._guard`: виняток -> `Finding` fatal ERROR (не падіння), якщо не `health.reraise`.

## 4. Де шукати: питання -> місце

### Виділення меж burst'ів
Весь алгоритм - `source-py/burst_search.py`, робота ведеться на виході matched filter `y` (|y|², не на сирому IQ). `search_bursts` викликає чисті функції по черзі, проміжні результати лежать у `SearchResult` (`raw`, `merged`, `filtered`, `final`):

1. `power` -> |y|²; 2. `smooth` -> обвідна (вікно `SEARCH_SMOOTH_SYM`=8 симв.);
3. `estimate_noise_floor` -> підлога шуму (режими `global` / `local` / `fixed`, перцентиль `SEARCH_NOISE_PERCENTILE`=10);
4. `detect_segments` -> гістерезис: область де обвідна > підлога + `off_db` (5 дБ), якщо десь > підлога + `on_db` (8 дБ);
5. `merge_close` -> склеїти провали <= `SEARCH_MERGE_GAP_SYM`=8 симв.;
6. `filter_length` -> `min_len_sym`=100 (і `max_len_sym`);
7. `trim_edges` -> зрізати `trim_sym`=4 з країв (рампи).

Індекси сегментів - відліки work fs, `[start, end)`. Параметри - `SearchConfig` у `config.py` (секція CONSTANTS, префікс `SEARCH_`); з CLI: `--set search.on_db=10`. Тести: `source-py/test_burst_search.py`. Діагностика результату: `checks.check_activity`, `burst_search.describe`, `plot_search`.
Альтернативна груба детекція ДО matched filter (Otsu-поріг, часові частки слота): `source-py/coarse_detect.py`, вимкнена за замовчуванням.

### Таймінг і символи
`symbols.estimate_timing` (Oerder-Meyr, фракційна затримка tau на burst), `symbols.sample_symbols` (інтерполяція). Таймінг оцінюється **окремо для кожного burst'а**, не на весь файл.

### Демодуляція
`source-py/demod.py`: `diff_demod` (π/4-DQPSK диференційно), `estimate_freq_offset` / `correct_freq` (частота; межа однозначності `ambiguity_hz` = symbol_rate/8), `map_dibits` (дібіти -> біти; мапінг у `MapConfig`), `quality_metrics` (когерентність = |mean(d⁴)|, `phase_rms_deg`).

### Прапорці й відсів burst'ів
- відкидання: `quality.min_coherence` (за замовчуванням 0 = не відкидати), у `pipeline.run`;
- `LOWCOH` (когерентність < `health.flag_min_coherence`=0.5), `NEARLIM` (частота біля межі) - ставляться в `pipeline.demod_burst`.

### SNR
`snr_estimate.py` - часовий метод на сирому масиві (потужність burst'а проти шуму у вільних від burst'ів вікнах; використовується в пайплайні). `snr_freq.py` - частотний метод (FFT), у пайплайн не входить.

### Пошук полів TETRA в бітах
`source-py/pattern_check.py`: FCF, NTS1-3, STS, ETS, TAIL (ETSI EN 300 392-2, 9.4.4.3); поріг збігу `DETECT_THRESHOLD`=0.10; `SLOT_BITS`=510; `summarize_recording` - лічильники для заголовка out.txt. Виклик: `checks.check_patterns`.

### Діагностика (Health)
`health.py`: `Finding`, `CheckResult`, `HealthReport` (статус ok/degraded/failed), всі коди - у `checks.py` і `memcheck.py`. Пороги - `HEALTH_*` у `config.py`.

### Пам'ять
`memcheck.py`: `estimate_memory` оцінює RAM ДО завантаження файлу; `--mem-only` у CLI.

### Вхід/вихід
`source-py/io_stage.py`: `load_iq`/`probe_input` (WAV, raw `.cs16`), `write_bursts` (out.txt), `write_bits_bin`, `write_bits_bin_aligned` (.bin2), `write_bits_bin_phase_aligned` (.bin3), `write_bits_bin_structured` (.bin4: слот на burst за навчальною послідовністю, поля в колонках стандарту; `pattern_check.locate_training`, параметри `BIN4_*` у `config.py`). Формат out.txt, `#`-рядки, збірка .bin* - `docs/tetra-demod-internals.md`.

### CLI
`source-py/tetra_demod.py` (`main`): аргументи `-o`, `-e LE|BE`, `--fs`, `--set`, `--print-config`, `--mem-only`, `--diagnose-only`, `--report`, `--strict`, `--plot`. Коди виходу: 0 ok/degraded, 1 degraded з `--strict`, 2 failed. Обгортка: `bin/tetra_demod` (sh, знаходить `source-py/` відносно себе).

### Параметри
Усі тільки в `source-py/config.py`: секція CONSTANTS -> dataclass-конфіги (`SearchConfig`, `FrontEndConfig`, `MapConfig`, `PipelineConfig`...). Три способи зміни: правка CONSTANTS, `replace(cfg.search, ...)` у коді, `--set група.параметр=значення`. Ніяких магічних чисел в етапах.

### Синтетика й тести
`source-py/synth.py` (генератор сигналів `make_signal`, `tx_burst`, `ber_aligned`), `test_*.py` (unittest): `test_burst_search`, `test_pattern_check`, `test_health`, `test_memcheck`, `test_stages`, `test_output`.

### Підготовка для osmo-tetra
`source-py/wav-proc/tetra_prep.py` (передискретизація до 25 кГц, `DEFAULT_OUT_RATE_HZ`) і `source-py/tetra_bits_export.py` (burst'и у біти для tetra-rx: TRUE-TIME - на справжніх позиціях, підтверджено на tetra-rx; SEQUENTIAL - підряд, НЕ перевірено). Обидва перевикористовують `burst_search.search_bursts` і `symbols.estimate_timing`.

### DMO (C)
- `dmo/dmo_core/dmo_tuning.h` - усі константи DSB (470 біт, зсуви STS/SCH/S/SCH/H, довжини, інтерлівер) - "магічні числа" тільки тут;
- `dmo_sync.c` - `dmo_sync_find` (пошук STS з допуском помилок); `dmo_burst.c` - `dmo_burst_slice`; `dmo_block.c` - `dmo_block_decode` (дескремблювання, деперемежіння, Viterbi, CRC; параметри `dmo_sch_s_params`, `dmo_sch_h_params`);
- `dmo/dmo_rx_entry.c` - точка входу exe `dmo_rx`: `dmo_rx <bits-file> [-v]`; файл = байти 0/1 (інакше помилка), крок: `dmo_sync_find` -> `dmo_burst_slice` -> `dmo_block_decode` для SCH/S і SCH/H; друкує на кожен кандидат зсув, `crc=OK/FAIL`, type1-біти (`-v` додає перевірку tail), в кінці `candidates=… SCH/S_crc_ok=… SCH/H_crc_ok=…`; коди виходу 0 ok, 1 помилка, 2 аргументи; допуск помилок STS - `DMO_STS_MAX_BIT_ERRORS_DEFAULT`=0 у `dmo_tuning.h` (з CLI не міняється);
- специфікації: `dmo/docs/dmo-phy-spec.md` (розкладка бурстів, кодування; EN 300 396-2), `dmo/docs/dmo-mac-spec.md` (DMAC-SYNC, DM colour code; EN 300 396-3). Позначка **UNVERIFIED** = не підтверджено.

## 5. Збірка

| Що | Як |
|---|---|
| Python | збірки немає; запуск `./bin/tetra_demod in.wav -o out`; потрібні python3, numpy, scipy, matplotlib |
| Тести Python | `cd source-py && python3 -m unittest discover -p "test_*.py" -v` |
| C (dmo) | CMake >= 3.20, C11/C++17, потрібен libosmocore (pkg-config) і сирці osmo-tetra: `OSMO_TETRA_DIR` (за замовчуванням `~/Public/repos/osmo-tetra/src`) |
| Скрипт збірки | `scripts/deploy.sh -m debug|release [-t target]`; компілятор жорстко `clang` (змінна `compiler` у скрипті), генератор з `GEN`; збирає у `build-<mode>-<compiler>/`, копіює бінарі: debug -> `wd/`, release -> `bin/` (`bin/` відстежується git і містить ручні скрипти - нічого не видаляється) |
| Цілі CMake | лише `dmo_rx` (бібліотеки `dmo_core`, `osmo_leaf`); exe додаються тільки в корневому `CMakeLists.txt` як `<target>_entry.c`, бібліотеки - у піддиректоріях |
| Попередження | `-Wall -Wextra -Wpedantic` через INTERFACE-цільову `project_warnings`; чужий код `osmo_leaf` без неї |
| Бекап | `scripts/back-up.sh` - zip `source-py/` у `bak/` без `__pycache__` |
| Оточення з нуля | `docs/env-prepare-tetra.md` (Debian) |

## 6. Інші документи

| Файл | Зміст |
|---|---|
| `README.md` | короткий опис, структура, запуск |
| `docs/tetra-demod-internals.md` | когерентність, `#`-рядки out.txt, збірка .bin/.bin2/.bin3/.bin4, колонка `type` |
| `docs/env-prepare-tetra.md` | оточення Debian |
| `docs/to-do.md` | плани й нотатки |
| `docs/cheat-shit.md` | робочі нотатки власника - **не читати** без вказівки |

## 7. Нормативні документи (не в git)

PDF стандартів лежать у `docs/ETSI/` і додані до `.gitignore`. Якщо їх немає (новий клон), завантажити з etsi.org (пошук за номером на https://www.etsi.org/standards), саме ці версії, бо номери таблиць і клаузул у `dmo/docs/*.md` і в `source-py/pattern_check.py` відповідають їм:

| Документ | Версія | Дата | Для чого |
|---|---|---|---|
| ETSI EN 300 392-2 | V3.8.1 | 2016-08 | TMO: air interface, burst'и і навчальні послідовності (9.4.4), `pattern_check.py` |
| ETSI EN 300 396-2 | V1.4.1 | 2011-12 | DMO: фізичний рівень, DSB/DNB (9.4.3), `dmo/docs/dmo-phy-spec.md` |
| ETSI EN 300 396-3 | V1.4.1 | 2011-12 | DMO: MAC, DMAC-SYNC (SCH/S, SCH/H), `dmo/docs/dmo-mac-spec.md`; зараз у `docs/ETSI/` відсутній |

Ім'я файлу в `docs/ETSI/`: `ETSI_EN_300_392-2_V3.8.1(2016-08).pdf`, `ETSI_EN_300_396-2 V1.4.1(2011-12).pdf`.
