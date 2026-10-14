# tetra_demod (PoC)

Офлайн-демодулятор TETRA π/4-DQPSK з IQ-файлів. Канального декодування і кореляції зі
sync-послідовностями поки немає: на виході «сирі» біти burst'ів.

## Запуск

```bash
python3 -m tetra_demod in.wav -o bursts [--set search.on_db=10] [--plot]
python3 -m tetra_demod in.wav --diagnose-only --report health.json
python3 -m tetra_demod in.wav --mem-only
python3 -m tetra_demod --print-config
```

## Тести

```bash
python3 -m unittest discover -s tests -t . -v
```

## Параметри

Усі в одному місці: `tetra_demod/config.py`, секція CONSTANTS.
З командного рядка: `--set група.параметр=значення` (можна повторювати).

## Діагностика й деградація

Кожен етап діагностики ізольований (`checks.py`): чиста функція `дані + конфіг -> CheckResult`.
Жодних припущень про пристрій захоплення: лише вимірювання з даних.

┌─────┬─────────────────────┬──────────────────────────────────┬────────────────────────────────────────────┐
│ #   │ Етап                │ Що перевіряє                     │ Коди                                       │
├─────┼─────────────────────┼──────────────────────────────────┼────────────────────────────────────────────┤
│ 0   │ check_meta          │ fs, довжина                      │ BAD_FS, FS_TOO_LOW, EMPTY_INPUT,           │
│     │                     │                                  │ INPUT_TOO_SHORT (fatal)                    │
├─────┼─────────────────────┼──────────────────────────────────┼────────────────────────────────────────────┤
│ 1   │ sanitize +          │ NaN/Inf                          │ NONFINITE_SAMPLES, NONFINITE_TOO_MANY      │
│     │ check_nonfinite     │                                  │ (fatal)                                    │
├─────┼─────────────────────┼──────────────────────────────────┼────────────────────────────────────────────┤
│ 2   │ check_levels        │ рівень, кліпінг, DC, кругова     │ SILENT_INPUT (fatal), LOW_LEVEL, CLIPPING, │
│     │                     │ симетрія IQ                      │ DC_OFFSET, IQ_IMPROPER                     │
├─────┼─────────────────────┼──────────────────────────────────┼────────────────────────────────────────────┤
│ 3   │ check_spectrum      │ грубий зсув, ширина, DC-пік,     │ COARSE_OFFSET, BANDWIDTH, DC_SPIKE,        │
│     │                     │ лінія символьної швидкості, пауз │ SYMBOL_LINE, CONTINUOUS_SIGNAL,            │
│     │                     │ немає                            │ SPEC_NO_SIGNAL                             │
├─────┼─────────────────────┼──────────────────────────────────┼────────────────────────────────────────────┤
│ 4   │ check_activity      │ пошук burst'ів                   │ NO_BURSTS, SEGMENTS_TOO_SHORT              │
├─────┼─────────────────────┼──────────────────────────────────┼────────────────────────────────────────────┤
│ 5   │ check_bursts        │ якість і стабільність burst'ів,  │ LOW_COHERENCE, FREQ_NEAR_LIMIT,            │
│     │                     │ спектр проти burst'ів            │ FREQ_UNSTABLE, FREQ_ALIAS, MANY_REJECTED,  │
│     │                     │                                  │ BURST_EXCEPTION                            │
└─────┴─────────────────────┴──────────────────────────────────┴────────────────────────────────────────────┘

- Статус запуску: `ok` -> `degraded` (є WARN, результат є) -> `failed` (є ERROR).
- Код виходу: 0 ok/degraded, 1 degraded за `--strict`, 2 failed.
- `health.policy=continue` (за замовчуванням): нефатальна ERROR не зупиняє обробку
  (результат є, але ненадійний). `abort`: зупинитись.
- Fatal-знахідки зупиняють завжди.
- Винятки етапів і burst'ів не валять процес (`health.reraise=true` вимикає це для налагодження).
- Підозрілі burst'и у виході мають прапорці LOWCOH / NEARLIM.

## Формат виходу

Один рядок на burst:

```
t_start_s n_sym freq_hz coherence phase_rms_deg flags bits
```

Опис колонок і приклади команд: див. `cheat-shit.md`.