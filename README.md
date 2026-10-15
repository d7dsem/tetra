# tetra (PoC)

Офлайн-демодулятор TETRA π/4-DQPSK з IQ-файлів (WAV int16 2ch або raw `.cs16`).
Канального декодування (FEC/дескремблювання/деперемеження) немає: на виході
"сирі" демодульовані біти burst'ів плюс діагностика якості й виявлення полів TETRA.

Навігація по коду (де що шукати, збірка, потік даних): `docs/INDEX.md`.

## Структура репозиторію

```
bin/
  tetra_demod        - sh-обгортка запуску (знаходить свій каталог, cd, exec)
source-py/
  tetra_demod.py     - точка входу (CLI, argparse)
  config.py          - ЄДИНЕ місце всіх параметрів (секція CONSTANTS)
  front_end.py       - ресемплінг, RRC matched filter
  burst_search.py    - пошук burst'ів (поріг+гістерезис на matched-filtered сигналі)
  coarse_detect.py   - альтернативна груба детекція ДО matched filter (вимкнена
                       за замовчуванням, див. docs/cheat-shit.md)
  symbols.py         - символьна синхронізація (Oerder-Meyr)
  demod.py           - диференціальна демодуляція, мапінг дібітів
  snr_estimate.py    - SNR на сирому масиві, часовий метод
  snr_freq.py        - SNR, частотний метод (FFT)
  pattern_check.py   - пошук полів TETRA (FCF/NTS/STS/ETS/TAIL), звірено з
                       ETSI EN 300 392-2
  checks.py          - діагностичні перевірки (HealthReport findings)
  health.py          - модель Finding/CheckResult/HealthReport
  memcheck.py        - оцінка потрібної пам'яті ДО завантаження файлу
  pipeline.py         - оркестратор, викликає етапи по черзі
  io_stage.py        - читання WAV/raw, запис .txt/.bin/.bin2/.bin3
  synth.py           - генератор синтетичних сигналів для тестів
  test_*.py          - тести (unittest)
docs/
  cheat-shit.md      - практичні команди й шпаргалка (цей архів)
```

## Запуск

```bash
chmod +x bin/tetra_demod        # один раз
./bin/tetra_demod in.wav -o out
```

Працює з довільного каталогу (не лише з кореня репо), якщо `bin/` є у PATH
або викликається за шляхом - сам знаходить `source-py/` відносно себе.

## Тести

```bash
cd source-py
python3 -m unittest discover -p "test_*.py" -v
```

## Параметри

Усі в `source-py/config.py`, секція CONSTANTS. Перевизначення з командного рядка:
`--set група.параметр=значення` (можна кілька разів). `--print-config` показує
поточні значення у JSON.

## Детальніше

Команди, формат виходу, таблиця кодів діагностики, тюнінг - у `docs/cheat-shit.md`.
