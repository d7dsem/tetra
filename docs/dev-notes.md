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


# DMO пйаплайн

**Захват Х310 -> підготвка (філтр/ресемплінг) -> демодуляція -> декодуваня -> to voice**

Базується на підготовленоум оточені в якому виконано розгортання відпоівлно дол `docs/env-prepare-tetra.md`.
Каталоги в `PATH` і аліаси в `~/.bashrc`

```bash
# Пілготовча частина
# Обрати катлог для роботи і перейти
cd ~/Public/signals/1otd/
mkdir azart-open && cd azart-open

voss_lch_cap -f 410.0e6 -m 0 -l 64 --viz --tag voice_open
# Результат voice_open_2026-10-15_10-29-54_part000.wav
tetra_prep voice_open_2026-10-15_10-29-54_part000.wav --out-raete 72e3 -o 1_voice_open_rsmp72e3.wav



tetra_demod 1_voice_open_rsmp72e3.wav -o 1_voice_open
dmo_rx 1_voice_open.bits # -v - verbose

dmo_voice 1_voice_open.tch

# Послухати
# audacity 1_voice_open_audio.wav
```


# tetra_demod


NOTE: `-o out` задає STEM, а не повне ім'я. Без `-o` стем = ім'я входу без розширення.

`-e LE|BE` (`--endian`) - порядок бітів при пакуванні в байти `.bin`/`.bin2`/`.bin3`/`.bin4`:
`BE` (за замовчуванням) - перший біт у старшому розряді байта, `LE` - у молодшому.



## Вихідні артефакти

```bash
tetra_demod 1_voice_open_rsmp_72e3.wav -o 1_out_be [-e BE] # be - default
# Якщо надо в le
# tetra_demod 1_voice_open_rsmp_72e3.wav -o 1_out_le -e LE
```

**Основний результат**
`1_out_be.txt`   - текстовий звіт по burst'ах (назви колонок - у рядку-заголовку самого файлу), містить класифікацію бурстів і технічну інформацію 

**Для контроль біт в'юверами**
`1_out_be.bin`   - чисті демодульовані біти підряд, БЕЗ доповнень (для роботи з даними), запаковані у байт.
`1_out_be.bin2`  - те саме, але кожен burst доповнений нулями в КІНЦІ до кратності 510 біт
            (вирівнювання "наживо", не знає справжньої фази burst'а в слоті)
`1_out_be.bin3`  - точніше: доповнення З ОБОХ боків за СПРАВЖНЬОЮ фазою burst'а
            (обчислено з start_sample) - для перегляду в bit viewer'і (Hobbits,
            Width Framer, width=510) дає чистішу структуру, ніж .bin2
`1_out_be.bin4`  - вирівнювання з прив'язкою до NTS, саме красівк у біт в'юверах

**Для декодувавня**

`1_out_be.bits` - біт-байт предстваленя резултавитиу демодуляції (того що в `.txt` та `.bin`)

`1_out_be.bits4` - біт-байт предстваленя резултавитиу демодуляції (того що `.bin4`)

NOTE: `.bin2`/`.bin3` / `bin4` - лише для візуального аналізу структури, не для декодування (містять зайві нулі-доповнювачі між burst'ами).



# Декодування DMO (dmo_rx)

На вход подавати вихідні `.bits` (або `.bits4`) файли `tetra_demod` :

```bash
# зібрати один раз: потрібні clang, libosmocore, сирці osmo-tetra в ~/Public/repos/osmo-tetra/src
cd ~/Public/repos/tetra
scripts/deploy.sh -m release -t dmo_rx        # -> bin/dmo_rx (debug: -m debug -> wd/)

dmo_rx 1_out_be.bits -v                       # + сирі біти SCH/S, SCH/H, SCH/F
dmo_rx 1_out_be.bits -o res                   # артефакт res.tch (за замовчуванням ім'я входу + .tch)

# голос: .tch -> WAV 8 кГц mono (кодек cdecoder/sdecoder з /tetra/bin, як є)
dmo_voice 1_out_be.tch                         # -> out_audio.wav
dmo_voice 1_out_be.tch something_you_want.wav
```

Вихід `dmo_rx`: першими рядками підсумок (`#`: скільки DSB, DNB1, DNB2; CRC OK по SCH/S, SCH/H, SCH/F, STCH;
колір-код), далі рядок на burst: DSB - `S:OK H:OK slot frame DM-1 cd DM-SETUP src dst mni`, DNB1 - `SCH/F OK`
або `TCH`, DNB2 - `STCH OK|FAIL`. Останній рядок `-> res.tch (N TCH records for cdecoder)`.
Коди виходу: 0, 1 (помилка), 2 (аргументи).
`.tch` - записи по 690 int16 (формат входу cdecoder, той самий, що `.out` у `tetra-rx -d`); 1 запис = 60 мс мовлення.
Вимоги до входів - у `README.md`, розділ "Вимоги до входу".

# Діагностика

```bash
cd ~/Public/signals/1otd/azart-open/72KHz
tetra_demod 1_voice_open_rsmp_72e3.wav --mem-only                           # лише оцінка пам'яті
tetra_demod 1_voice_open_rsmp_72e3.wav --diagnose-only --report health.json # аналіз без запису burst'ів
tetra_demod 1_voice_open_rsmp_72e3.wav -o out --strict; echo $?              # 1 якщо degraded
```

Коди виходу: `0` ok/degraded, `1` degraded за `--strict`, `2` failed (є ERROR).

Код                                  Що означає
------------------------------------ -------------------------------------------------------------
SILENT_INPUT, EMPTY_INPUT (fatal)    тиша / порожній файл
INPUT_UNREADABLE (fatal)             не WAV int16 2ch / не читається
NONFINITE_*                          NaN/Inf у даних
CLIPPING                             відліки на межі шкали
DC_OFFSET, IQ_IMPROPER               постійна складова / I,Q нерівноправні
COARSE_OFFSET                        центр потужності близько/за межею ±2250 Гц
FREQ_ALIAS                           зсув за burst'ами не збігається зі спектром
BANDWIDTH, SYMBOL_LINE               не схоже на один канал 18 кбод
CONTINUOUS_SIGNAL                    пауз між burst'ами немає (режим search.noise_mode=global не підійде)
SPEC_NO_SIGNAL, NO_BURSTS            сигналу/burst'ів не знайдено
LOW_COHERENCE                        не схоже на π/4-DQPSK
FREQ_UNSTABLE                        зсув між burst'ами розкиданий
NO_PATTERNS_FOUND                    жодного поля TETRA не знайдено в жодному burst'і
BURST_EXCEPTION, STAGE_EXCEPTION     виняток усередині етапу (--set health.reraise=true покаже traceback)

# [SUMMARY]: пошук полів TETRA

Блок у виводі одразу після `[ARTEFACTS]`. Поля звірені з **ETSI EN 300 392-2
V3.8.1, розділ 9.4.4.3** (формули 9.1-9.13) напряму з текстом стандарту.

```
      назва           перевірено   чисто (0%)  з пом. (≤10%)  медіана пом.
      FCF (80bit)            242           48              1         42.5%
      NTS1 (22bit)           242          183              6          0.0%
      ...
```

Поле             Довжина  Статус
---------------- -------- ------------------------------------------------------------------------------------------
FCF              80 біт   звірено зі стандартом
NTS1, NTS2, NTS3 22 біт   звірено зі стандартом (3 різні training sequences)
STS              38 біт   звірено зі стандартом + незалежне стороннє джерело
ETS              30 біт   звірено зі стандартом (uplink control burst)
TAIL             4 біт    звірено, але коротке - випадковий збіг статистично ймовірний, не враховується в "хоч щось знайдено"
PHASE            -        НЕ фіксована послідовність (обчислюється динамічно за формулою 9.14), пошук структурно неможливий

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

- `tetra_demod` працює на семпл рейті  72 КГц, записи з рейтом нижче порогу 36 КГц не обробляютсья.
- `tetra_demod` не робить канального декодування (дескремблювання, деперемеження, FEC/Viterbi): на виході
  "сирі" біти burst'ів. Для DSB (DMO) це робить `dmo_rx` (SCH/S, SCH/H з CRC); DNB (голос) ще не декодується.
- Для голосу (ACELP) потрібен окремий відкритий ланцюжок: osmo-tetra-sq5bpf +
  telive + install-tetra-codec (завантажує референсний кодек з сайту ETSI,
  під їхньою ліцензією) - не інтегровано в цей проєкт.
- Тести лише на синтетиці (`synth.py`, генерує ВИПАДКОВІ біти - тому
  NO_PATTERNS_FOUND на них коректний, не помилка); тестів на реальних записах немає.
- `tetra-rx` (osmo-tetra) розрахований на конкретний трафік - мережевий режим TETRA (TMO)
  від базової станції.
- Тонкий зсув частоти однозначний лише в межах ±2250 Гц (symbol_rate/8).
- Файл завантажується в пам'ять повністю (потокової обробки блоками немає).
