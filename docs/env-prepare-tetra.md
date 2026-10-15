# Підготовка оточення з нуля (Debian)

Виконувати по черзі, у звичайному терміналі користувача `d7`.
Усі команди - без `sudo`, крім тих, де `sudo` написано.

## 1. Пакети

```bash
sudo apt install git build-essential pkgconf txt2man libosmocore-dev \
  unzip wget patch libncurses-dev libxml2-dev \
  python3 python3-numpy python3-scipy python3-matplotlib
```

## 2. Репозиторії

```bash
mkdir -p ~/Public/repos && cd ~/Public/repos
git clone https://gitea.osmocom.org/tetra/osmo-tetra
git clone https://github.com/sq5bpf/install-tetra-codec
git clone https://github.com/sq5bpf/telive
```

Примітка: `~/Public/repos` - приклад розташування, а не вимога. Якщо
репозиторії (включно з цим, `tetra`) лежать деінде, замінити шлях у командах
нижче.

## 3. tetra-rx

```bash
cd ~/Public/repos/osmo-tetra/src && make
ls -l tetra-rx
```

Попередження про `N_bits`/`P_bits`/`X_bits`/`t_bits`/`T_bits` - нормально.

## 4. Наші інструменти і PATH

```bash
chmod +x ~/Public/repos/tetra/bin/tetra_demod ~/Public/repos/tetra/bin/tetra_bits_export
cat >> ~/.bashrc <<'EOF'
export PATH="$PATH:$HOME/Public/repos/tetra/bin:/tetra/bin"
alias tetra-rx='~/Public/repos/osmo-tetra/src/tetra-rx'
alias telive='~/Public/repos/telive/telive'
EOF
source ~/.bashrc
```

Правило: інструменти з каталогів `bin/` викликаються через `PATH`
(`tetra_demod`, `tetra_bits_export`, `tplay`, `tetrad`, `scoder`, `sdecoder`,
`ccoder`, `cdecoder`); інструменти з вихідних дерев - через аліас (`tetra-rx`,
`telive`). Після кроків 5-6 усі десять викликаються за іменем.

## 5. Кодек (спершу кодек, потім telive)

```bash
cd ~/Public/repos/install-tetra-codec
chmod +x install.sh
./install.sh            # БЕЗ sudo; пароль запитає сам
ls /tetra/bin           # мають бути: ccoder cdecoder scoder sdecoder
```

У виводі рядки `Permission denied` / `Operation not permitted` - нормально:
скрипт пробує без `sudo`, потім повторює з `sudo`. Успіх - рядок
`Codec installed`.

Якщо `Bad codec checksum` - скрипт видалив поганий архів, просто запустити
`./install.sh` ще раз.

## 6. telive

```bash
cd ~/Public/repos/telive
chmod +x install.sh
./install.sh            # `mkdir ... /tetra/bin: File exists` - нормально
make                    # 2 попередження implicit declaration - нормально
ls -l telive /tetra/bin # є telive; у /tetra/bin додалися tetrad, tplay
```

## 7. Перевірка

```bash
tetra_demod файл.wav -o /tmp/chk
tetra_bits_export файл.wav -o /tmp/chk
tetra-rx /tmp/chk.true.plus.bits | grep -c "found SYNC"
```

`файл.wav` - ваш запис TETRA (WAV int16, 2 канали I/Q). Очікується число
більше 0. Використовувати `plus`, не `minus`.

## Щоденний запуск

```bash
tetra_demod файл.wav -o stem
tetra_bits_export файл.wav -o stem
mkdir -p /tmp/dump
tetra-rx -d /tmp/dump stem.true.plus.bits
```

Голос з дампа (потрібні кроки 5-6):

```bash
tplay /tmp/dump/*.out
```

Порожній `/tmp/dump` при наявних `BURST` - не помилка: це означає, що
голосового трафіку не знайдено.
