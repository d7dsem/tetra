# Встановлення osmo-tetra / tetra-rx

Канальний декодер TETRA (нижній MAC, дешифрування структури слотів/MAC-PDU).
Приймає потік бітів, не наш `.txt`/`.bin`/`.bin2`/`.bin3` формат напряму -
див. `tetra_bits_export.py` у цьому репо для мосту між нашим демодулятором
і форматом, який очікує `tetra-rx`.

## Статус пакета в Debian

`osmo-tetra` є офіційним пакетом Debian, але **лише в `trixie`/`sid`**
(testing/unstable). У `bookworm` (поточний stable на момент написання) його
немає взагалі - перевірено пошуком по `packages.debian.org`.


## Встановлення: збірка з джерела (перевірено, працює)

```bash
sudo apt install git libosmocore-dev gnuradio gr-osmosdr pkgconf txt2man build-essential

git clone https://gitea.osmocom.org/tetra/osmo-tetra
cd osmo-tetra/src
make
```

Збирається без помилок (лише нешкідливі попередження компілятора про
невикористані масиви `N_bits`/`P_bits`/`X_bits`/`t_bits`/`T_bits` - поля
π/8-D8PSK, не застосовуються в поточній конфігурації збірки).

Результат: бінарники `tetra-rx`, `float_to_bits`, `conv_enc_test`, `crc_test`,
`tunctl` у `osmo-tetra/src/`.

NOTE: збірка перевірена на Debian 13 (trixie) з пакетними залежностями з
власних репозиторіїв дистрибутива. На Debian 12 (bookworm) залежності
(`libosmocore-dev` версії 1.11.0) можуть бути відсутні в стандартних
репозиторіях - у такому разі знадобиться backports чи збірка `libosmocore`
теж із джерела.


## Запуск

```bash
# ~/.bashrc
# alias tetra-rx-run='~/Public/repos/osmo-tetra/src/tetra-rx'
tetra-rx [-d DUMPDIR] <file_with_1_byte_per_bit>
```

Формат вхідного файлу (з коду `float_to_bits.c`, не з опису): **1 байт = 1
біт**, сире значення `0` або `1` (uint8), не ASCII `'0'`/`'1'`, не
запаковано. Наш `tetra_bits_export.py` генерує саме цей формат.

`--help` НЕ підтримується - парсер аргументів трактує кожну літеру як
окремий (невідомий) прапорець. Єдиний реальний прапорець - `-d DUMPDIR`.

```bash
tetra-rx 4_open_voice.plus.bits
```



## `-d DUMPDIR`: коли насправді пише файли

Перевірено за вихідним кодом (`tetra-rx.c`): дамп пишеться ТІЛЬКИ для
burst'ів типу `SCH_F`, позначених як `is_traffic` (тобто вже триваючий
голосовий трафік конкретного з'єднання). Самого лише успішного `found
SYNC`/`BURST` недостатньо - порожній `DUMPDIR` при наявних `BURST` у
виводі **не є ознакою помилки**, а означає, що серед знайдених burst'ів
немає класифікованого голосового трафіку (control/сигналізація теж дають
`BURST`, але нічого не пишуть у dumpdir).

```bash
mkdir -p /tmp/dump
tetra-rx -d /tmp/dump запис.bits
ls -la /tmp/dump/      # traffic_*.out / traffic_*.txt, якщо є голосовий трафік
```


## GSMTAP (структурований вивід PDU) - НЕ підтверджено нами

За архітектурою проєкту (з документації), декодований вміст MAC/LLC/MM/CMCE
може йти окремим потоком GSMTAP по UDP для перегляду у Wireshark, окремо
від `-d DUMPDIR`. Точний порт і умови активації МИ НЕ перевіряли на
практиці - перевірка через `tcpdump`:

```bash
sudo -v
sudo tcpdump -i lo -w gsmtap.pcap udp &
sleep 1
tetra-rx запис.bits
sudo pkill -f "tcpdump -i lo"
ls -la gsmtap.pcap
```

NOTE: жодних пакетів на localhost не зафіксовано в нашому тесті - або цей
білд не шле GSMTAP без додаткового (невідомого нам) налаштування, або та
сама умова `is_traffic`, що й для `-d DUMPDIR`.


## Дрейф таймінгу у вхідних бітах (якщо захват губиться після кількох burst'ів)

Якщо `tetra-rx` знаходить перші кілька burst'ів, а далі стабільно губить
синхронізацію ("could not find successive..." без повернення) - це, швидше
за все, не проблема `tetra-rx`, а якість вхідного бітового потоку: кожен
burst має бути демодульований зі СВІЖИМ (а не одним на весь файл) таймінгом,
інакше дрейф (похибка ppm, фазовий шум) накопичується. Наш
`tetra_bits_export.py` (друга версія, після виправлення) оцінює таймінг
ОКРЕМО для кожного знайденого burst'а - якщо проблема повторюється і з цим
виходом, причина, найімовірніше, в іншому місці (конвенція знаку фази,
якість самого запису).


## Кодек (ACELP) для прослуховування голосу - окремий крок

```bash
git clone https://github.com/sq5bpf/telive
git clone https://github.com/sq5bpf/install-tetra-codec
cd install-tetra-codec
chmod 755 install.sh
./install.sh
```

Скрипт завантажує референсний кодек з сайту ETSI під їхньою ліцензією,
компілює (`scoder`/`ccoder`/`sdecoder`/`cdecoder`), намагається встановити
в `/tetra/bin` (**потребує root** - без `sudo` впаде з `Permission denied`
на `mkdir /tetra`, перевірено). Якщо впало на цьому кроці, бінарники все
одно лишаються зібраними у тимчасовому каталозі збірки - або перезапустити
`./install.sh` із `sudo`, або вручну скопіювати бінарники з виведеного
тимчасового шляху (`/tmp/codec-XXXXX`) туди, де їх шукає `telive`.