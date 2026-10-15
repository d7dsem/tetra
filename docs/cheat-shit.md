# cheat-sheet - Шпаргалка

Документ для збереженя нотатко щодо базових дій (проєкт tetra: офлайн-демодулятор TETRA π/4-DQPSK).

ШІ - без прямої команди не модифікує. Включає у всі коміти безумвоно, в коміт меседж не вносити. 

# Послідовності, які шукаємо (біти, 0/1)

Джерело: `source-py/pattern_check.py`, ETSI EN 300 392-2 V3.8.1, розділ 9.4.4.3.

```
FCF   (80)  11111111000000000000000000000000000000000000000000000000000000000000000011111111
NTS1  (22)  1101000011101001110100
NTS2  (22)  0111101001000011011110
NTS3  (22)  1011011100000110101101
STS   (38)  11000001100111001110100111000001100111
ETS   (30)  100111010000111010011101000011
TAIL  (4)   1100
```

- FCF (Frequency Correction Field) - частотна корекція: 8 одиниць, 64 нулі, 8 одиниць.
- NTS1/NTS2/NTS3 (Normal Training Sequence 1/2/3) - навчальні послідовності для
  синхронізації й оцінки каналу; NTS3 - допоміжна, частинами по краях downlink burst'ів
  (q11..q22 на початку, q1..q10 в кінці); розкладки burst'ів - `docs/burst-structures.md`.
- STS (Synchronization Training Sequence) - навчальна послідовність sync burst'а.
- ETS (Extended Training Sequence) - довга навчальна послідовність uplink control burst'а.
- TAIL (tail bits) - 4 біти наприкінці; надто коротке, щоб вважати знайденим саме по собі.
- PHASE (phase adjustment bits) - не фіксована послідовність, обчислюється для кожного
  burst'а, тому не шукається.


# Захват

```
voss_lch_cap -f 410.0e6 -m 0 -l 64 --viz --tag test
```

# Приклади, прив'язані до ПК

Запис-приклад: `~/Public/signals/1otd/azart-open/72KHz/1_voice_open_rsmp_72e3.wav`
(лежить на цьому ПК, у репозиторій не входить). Усі інструменти викликаються за
іменем: `PATH` і аліаси з `docs/env-prepare-tetra.md`.

```bash
cd ~/Public/signals/1otd/azart-open/72KHz
tetra_demod 1_voice_open_rsmp_72e3.wav -o 1_voice_open_rsmp_72e3
tetra_bits_export 1_voice_open_rsmp_72e3.wav -o 1_voice_open_rsmp_72e3
tetra-rx 1_voice_open_rsmp_72e3.true.plus.bits | grep -c "found SYNC"   # 12
mkdir -p /tmp/dump && tetra-rx -d /tmp/dump 1_voice_open_rsmp_72e3.true.plus.bits
tplay /tmp/dump/*.out       # на цьому записі /tmp/dump порожній: tplay нічого не знайде
```


# Підготовка

```bash
cd /шлях/до/репо
chmod +x bin/tetra_demod            # один раз
cd source-py && python3 -m unittest discover -p "test_*.py" -v
```

# Запуск

```bash
cd ~/Public/signals/1otd/azart-open/72KHz

# з довільного каталогу (bin/ сам знаходить source-py/ відносно себе)
tetra_demod 1_voice_open_rsmp_72e3.wav -o out

# raw int16 interleaved I,Q: fs обов'язковий
tetra_demod in.cs16 --fs 192000 -o out

# графіки
tetra_demod 1_voice_open_rsmp_72e3.wav -o out --plot
```

NOTE: `-o out` задає STEM, а не повне ім'я. Без `-o` стем = ім'я входу без розширення.

`-e LE|BE` (`--endian`) - порядок бітів при пакуванні в байти `.bin`/`.bin2`/`.bin3`/`.bin4`:
`BE` (за замовчуванням) - перший біт у старшому розряді байта, `LE` - у молодшому.

```bash
tetra_demod 1_voice_open_rsmp_72e3.wav -o out -e BE
```


# Вихідні файли

```
out.txt   - текстовий звіт по burst'ах (назви колонок - у рядку-заголовку самого файлу)
out.bin   - чисті демодульовані біти підряд, БЕЗ доповнень (для роботи з даними)
out.bin2  - те саме, але кожен burst доповнений нулями в КІНЦІ до кратності 510 біт
            (вирівнювання "наживо", не знає справжньої фази burst'а в слоті)
out.bin3  - точніше: доповнення З ОБОХ боків за СПРАВЖНЬОЮ фазою burst'а
            (обчислено з start_sample) - для перегляду в bit viewer'і (Hobbits,
            Width Framer, width=510) дає чистішу структуру, ніж .bin2
```

NOTE: `.bin2`/`.bin3` - лише для візуального аналізу структури, не для декодування
(містять зайві нулі-доповнювачі між burst'ами).

# Декодування DMO (dmo_rx)

Нові вихідні файли `tetra_demod` (додатково до `out.bin`, `out.bin2`, `out.bin3`):

```
out.bin4  - слот (510 біт) на burst, burst вирівняно за типом за стандартом: поля в колонках
            стандарту (для перегляду, ширина 510)
out.bits, out.bits2, out.bits3, out.bits4
          - ті самі біти, що .bin, .bin2, .bin3, .bin4, але ОДИН БІТ У БАЙТІ (0/1), без упаковки,
            `-e` на них не діє; це вхід dmo_rx
```

NOTE: `-e` тепер за замовчуванням `BE` (перший біт у старшому розряді байта); стосується лише
упакованих `.bin*`.

```bash
# зібрати один раз: потрібні clang, libosmocore, сирці osmo-tetra в ~/Public/repos/osmo-tetra/src
cd ~/Public/repos/tetra
scripts/deploy.sh -m release -t dmo_rx        # -> bin/dmo_rx (debug: -m debug -> wd/)

# запуск: вхід - файл бітів, один біт у байті
tetra_demod in.wav -o out
bin/dmo_rx out.bits4
bin/dmo_rx out.bits4 -v                       # додає перевірку tail
```

Вихід: рядок на кожен знайдений DSB (зсув, `SCH/S crc=OK|FAIL type1=...`, `SCH/H crc=...`),
у кінці `candidates=N SCH/S_crc_ok=N SCH/H_crc_ok=N`. Коди виходу: 0, 1 (помилка), 2 (аргументи).
STS шукається точним збігом, декодуються лише DSB (DNB, тобто голос, ще ні).
Вимоги до входів - у `README.md`, розділ "Вимоги до входу".


# Діагностика

```bash
cd ~/Public/signals/1otd/azart-open/72KHz
tetra_demod 1_voice_open_rsmp_72e3.wav --mem-only                           # лише оцінка пам'яті
tetra_demod 1_voice_open_rsmp_72e3.wav --diagnose-only --report health.json # аналіз без запису burst'ів
tetra_demod 1_voice_open_rsmp_72e3.wav -o out --strict; echo $?              # 1 якщо degraded
```

Коди виходу: `0` ok/degraded, `1` degraded за `--strict`, `2` failed (є ERROR).

| Код | Що означає |
|---|---|
| SILENT_INPUT, EMPTY_INPUT (fatal) | тиша / порожній файл |
| INPUT_UNREADABLE (fatal) | не WAV int16 2ch / не читається |
| NONFINITE_* | NaN/Inf у даних |
| CLIPPING | відліки на межі шкали |
| DC_OFFSET, IQ_IMPROPER | постійна складова / I,Q нерівноправні |
| COARSE_OFFSET | центр потужності близько/за межею ±2250 Гц |
| FREQ_ALIAS | зсув за burst'ами не збігається зі спектром |
| BANDWIDTH, SYMBOL_LINE | не схоже на один канал 18 кбод |
| CONTINUOUS_SIGNAL | пауз між burst'ами немає (режим search.noise_mode=global не підійде) |
| SPEC_NO_SIGNAL, NO_BURSTS | сигналу/burst'ів не знайдено |
| LOW_COHERENCE | не схоже на π/4-DQPSK |
| FREQ_UNSTABLE | зсув між burst'ами розкиданий |
| NO_PATTERNS_FOUND | жодного поля TETRA не знайдено в жодному burst'і |
| BURST_EXCEPTION, STAGE_EXCEPTION | виняток усередині етапу (`--set health.reraise=true` покаже traceback) |


# [SUMMARY]: пошук полів TETRA

Блок у виводі одразу після `[ARTEFACTS]`. Поля звірені з **ETSI EN 300 392-2
V3.8.1, розділ 9.4.4.3** (формули 9.1-9.13) напряму з текстом стандарту.

```
      назва           перевірено   чисто (0%)  з пом. (≤10%)  медіана пом.
      FCF (80bit)            242           48              1         42.5%
      NTS1 (22bit)           242          183              6          0.0%
      ...
```

| Поле | Довжина | Статус |
|---|---|---|
| FCF | 80 біт | звірено зі стандартом |
| NTS1, NTS2, NTS3 | 22 біт | звірено зі стандартом (3 різні training sequences) |
| STS | 38 біт | звірено зі стандартом + незалежне стороннє джерело |
| ETS | 30 біт | звірено зі стандартом (uplink control burst) |
| TAIL | 4 біт | звірено, але коротке - випадковий збіг статистично ймовірний, не враховується в "хоч щось знайдено" |
| PHASE | - | НЕ фіксована послідовність (обчислюється динамічно за формулою 9.14), пошук структурно неможливий |

Поріг помилок - тюнінг-параметр: `pattern_check.DETECT_THRESHOLD` (10% за замовчуванням).


# Тюнінг параметрів

```bash
cd ~/Public/signals/1otd/azart-open/72KHz
tetra_demod --print-config              # усі поточні значення, JSON

# пошук burst'ів
tetra_demod 1_voice_open_rsmp_72e3.wav -o out --set search.on_db=10
tetra_demod 1_voice_open_rsmp_72e3.wav -o out --set search.noise_mode=fixed --set search.noise_fixed=0.001

# відсіяти слабкі burst'и
tetra_demod 1_voice_open_rsmp_72e3.wav -o out --set quality.min_coherence=0.5

# поріг пошуку полів TETRA - НЕ підключений через --set, лише в коді:
#   source-py/pattern_check.py, DETECT_THRESHOLD (10% за замовчуванням)
```

## Груба детекція (coarse_detect) - ЕКСПЕРИМЕНТАЛЬНО, вимкнена за замовчуванням

```bash
cd ~/Public/signals/1otd/azart-open/72KHz
tetra_demod 1_voice_open_rsmp_72e3.wav -o out --set coarse.enabled=true
```

Альтернативний шлях: груба детекція активних ділянок ДО matched filter (на
сирих семплах), фільтр лише на знайдених ділянках замість усього файлу.

NOTE: перевірено на 5 файлах з `coarse.merge_fraction=1/16` (значення за
замовчуванням при enabled=true): **4 з 5 дають точний збіг** з дефолтним
шляхом (242/242, 165/165, 323/323, 7/7 burst'ів), але **на одному файлі
(file 3) втрачено 4 з 173 burst'ів** (169/173). Тому `enabled=False` -
свідомий вибір дефолту, не перевірено достатньо для продакшну. Вмикайте
лише усвідомлено, звіряючи результат зі старим шляхом на своїх даних.

Побічний ефект: з `coarse.enabled=true` рядок `floor(median)=...dB` у виводі
пошуку стає неінформативним (burst_search.describe() рахує його по
переважно нульовому масиву поза активними ділянками) - не баг, не
впливає на сам результат пошуку burst'ів.


# Обмеження (щоб не забути)

- `tetra_demod` не робить канального декодування (дескремблювання, деперемеження, FEC/Viterbi): на виході
  "сирі" біти burst'ів. Для DSB (DMO) це робить `dmo_rx` (SCH/S, SCH/H з CRC); DNB (голос) ще не декодується.
- Для голосу (ACELP) потрібен окремий відкритий ланцюжок: osmo-tetra-sq5bpf +
  telive + install-tetra-codec (завантажує референсний кодек з сайту ETSI,
  під їхньою ліцензією) - не інтегровано в цей проєкт.
- Тести лише на синтетиці (`synth.py`, генерує ВИПАДКОВІ біти - тому
  NO_PATTERNS_FOUND на них коректний, не помилка); тестів на реальних записах немає.
- `tetra-rx` (osmo-tetra) розрахований на конкретний трафік - мережевий режим TETRA (TMO)
  від базової станції. У його коді немає жодної згадки DMO (`dmo`, `direct mode`, `dm-sync`).
  Підтверджено, що записи 1_mask_voice - DMO: `dmo_rx` декодує DSB за DMO-ланцюгом (CRC OK), system code `1100`,
  преамбули P1-P3 і tail `00` в усіх burst'ах (TMO мав би tail `1100`). Раніша гіпотеза про TMO з нулями MCC/MNC/CC
  у BSCH була хибним тлумаченням DMO-блоку.
- Тонкий зсув частоти однозначний лише в межах ±2250 Гц (symbol_rate/8).
- Файл завантажується в пам'ять повністю (потокової обробки блоками немає).
