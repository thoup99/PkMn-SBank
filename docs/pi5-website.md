---
title: Raspberry Pi 5 website testing
---
# Test the website on a Raspberry Pi 5

Phase 3 adds real Bank imports/exports, persistent 30-slot boxes, moves/swaps,
box names, receiving-trainer settings, operation history and recoverable snapshots.
**The only supported website server is a Raspberry Pi 5 running 64-bit Raspberry
Pi OS.** Phones and computers access its website through a browser on the same LAN.
Phase 4 adds [simulated trading](simulated-trading.md). [Phase 5 USB Sword/Shield and Z-A testing](usb-trading.md) now connects the existing engine to a USB ESP32-S3.
Automatic startup, hotspot setup and 3DS integration remain later phases. Existing upstream CLI/desktop tools are preserved.

## 1. Prepare the Pi

Use a 64-bit Raspberry Pi OS installation, a stable power supply, free space for
build tools and snapshots, and an Internet connection for the initial build.
Run the following in a terminal on the Pi (or over SSH), as your normal user.
The installer asks for sudo only to install standard build/runtime dependencies.
It does not change Wi-Fi, flash firmware or install a desktop app.

```sh
sudo apt update
sudo apt install -y git
cd ~
git clone --branch main https://github.com/thoup99/PkMn-SBank.git PkMn-SBank
cd ~/PkMn-SBank
bash scripts/setup_web_pi5.sh
```

If you already have a checkout, keep your existing files, and use this instead of
cloning again (commit or stash unrelated local changes first):

```sh
cd ~/PkMn-SBank
git fetch origin
git switch main
git pull --ff-only
bash scripts/setup_web_pi5.sh
```

The website and Bank foundation are now on `main`. Phase updates also go through
a feature branch, tests and PR review before merging.

The installer creates `.venv-web`, downloads checksum-verified Node 24.22.1 ARM64
and .NET SDK 10 into `.web-tools`, publishes the self-contained PKHeX helper for
`linux-arm64` without trimming, and builds the Vite frontend. The untrimmed helper
keeps all PKHeX reflection paths and needs more disk space than a trimmed release. Tools are local to this checkout; no
system Node/.NET packages are replaced. Allow several minutes for the first build.
`--no-apt` skips system package installation when you have already installed those
dependencies. Runtime requirements are Python 3.11+ and the native helper; Node and
the .NET SDK are needed only for builds.

Tool installation references: [Node ARM64 releases](https://nodejs.org/dist/v24.22.1/)
and [Microsoft's .NET install script](https://learn.microsoft.com/dotnet/core/tools/dotnet-install-script).

## 2. Start the website

```sh
cd ~/PkMn-SBank
bash scripts/run_web_pi5.sh
```

Leave that terminal open. In another terminal on the Pi, find its LAN address:

```sh
hostname -I
```

On your phone or computer, open **`http://<PI-LAN-IP>:8000`**, replacing
`<PI-LAN-IP>` with the Pi's address, for example `http://192.168.1.50:8000`.
The browser devices need to be on the same network. On the Pi itself you can open
`http://localhost:8000`. FastAPI serves the API and built site together; no Vite
server or second website process is needed. Use a trusted LAN; this test server
has no login and should not be exposed with Internet port forwarding.

The launcher rejects other Pi models, 32-bit OS installations and non-Pi hosts.
There is no board/key requirement for this phase. Stop with **Ctrl+C**.

## 3. Test storage

1. The site starts with 32 normal boxes and the **Your Bank** badge.
2. Open **Settings**, enter the receiving trainer name, underlying 16-bit TID/SID,
   language and gender, then choose **Save receiving trainer**. The TID/SID are not
   the six-digit display ID used by some games. These identify the receiving
   handler for conversions; upstream rules preserve the original trainer.
3. Download the current backup ZIP in Settings, so you have an off-Pi recovery copy.
4. In **Pokémon boxes**, select a Pokémon file or a **copy** of a game save using
   the import picker. The upload limit is 64 MiB. The source file/save is read only;
   the importer can convert older records into a supported Bank format, leave held
   items behind or reject records. Read the per-Pokémon result and conversion notes.
5. Import the same file again. It should report **already imported** without adding
   duplicate records. The upstream ledger also remembers previously imported keys.
6. Select a Pokémon, check its details, and **Export Pokémon file**. Export leaves
   it in the Bank. The export is the stored/possibly converted record, not a rewrite
   of your original save. No save insertion or live transfer is performed.
7. Move it to another box/slot. Occupied destinations swap the two records. Rename
   a box, search by name/game/number, and filter by source game.
8. Stop the server, start it again, and verify the records, box names and positions
   persist. Reload the browser as well.
9. Review **History** and **Settings → Backups and recovery**. Restore an earlier
   snapshot and verify its boxes and trainer settings return. The state you
   replaced remains available as another snapshot.

Sprites use bundled samples first, then pokeldn's validated sprite cache/downloads
on the Pi. Without Internet access, cached art works and missing art falls back to
species initials. Base-species art is a visual aid, not a form/compatibility check.

To explore the old sample interface separately, stop the server and run:

```sh
PKMN_SBANK_MODE=demo bash scripts/run_web_pi5.sh
```

Demo mode is read-only and never shows/imports real Bank records. Stop and restart
normally to return to your Bank.

## Where data lives

By default the website uses:

```text
~/.local/share/pkmn-sbank/web-bank/
```

`CURRENT` is an atomic pointer to one immutable revision under `revisions/`.
Each revision holds the original Bank record files, JSON sidecars, import ledger,
layout, trainer settings and storage history. Every successful change writes a
complete new snapshot and fsyncs it before switching the pointer. Validation or
pre-commit disk failures leave the previous revision selected. Checksums detect
missing/changed committed files. This reduces interrupted-write risk; it does not
protect against SD-card failure, so keep downloaded backups on another device.

All revisions are retained and each is a full copy. Monitor `df -h` and free space;
this phase does not automatically prune backups. A downloaded ZIP contains trainer
metadata and Pokémon records: keep it private. Do not edit revision files or run
CLI/desktop tools against them. The website uses the upstream Bank implementation
in a separate snapshot store and does not automatically adopt an existing GUI Bank.
Import exported Pokémon files or a save through the website instead.

Set `POKELDN_DATA` to an absolute folder before **every** launch to choose a different
location, for example on an external SSD:

```sh
POKELDN_DATA=/absolute/path/to/pkmn-data bash scripts/run_web_pi5.sh
```

The launcher leaves your choice intact. The web store is its `web-bank` subfolder.
No record or backup is saved in the git checkout.

## Recover a downloaded ZIP

Stop the website first. Preserve a copy of the existing data folder if the disk
has enough space. Copy the downloaded ZIP to your Pi, then run from the checkout:

```sh
.venv-web/bin/python -m pokeldn.web.recover /absolute/path/to/pkmn-sbank-backup.zip
bash scripts/run_web_pi5.sh
```

For a custom data location, add `--data-dir /absolute/path/to/pkmn-data` to the
recovery command and use the same `POKELDN_DATA` when restarting. Recovery validates
ZIP paths, checksums and layout, and commits a new revision without deleting old
snapshots. The offline recovery ZIP limit is 512 MiB expanded / 50,000 files.
For larger stores, copy the entire data directory with the server stopped.

If an integrity error prevents the site loading, use this offline recovery path.
Do not delete `CURRENT` to try to create a new Bank; a missing/invalid pointer in
an existing store fails closed instead of pretending the Bank is empty.

## Troubleshooting and updates

- **Unsupported host:** confirm `uname -m` prints `aarch64` and
  `tr -d '\0' < /proc/device-tree/model` identifies Raspberry Pi 5.
- **Build/download failure:** check Internet access and disk space, then rerun the
  setup script. It does not erase saved Bank data.
- **PKHeX unavailable/import fails:** rerun the setup script and review the terminal
  error. Do not import until the ARM64 helper builds successfully.
- **Cannot reach the page:** keep the launch terminal open, check the current Pi
  address, ensure both devices are on the same LAN and check local firewall rules
  for TCP 8000. The launcher accepts `--port 8080` to use another port.
- **Storage unavailable/full:** stop the server, check your data drive and space,
  and recover a verified ZIP if necessary. Previous revisions are not overwritten.

To update this test branch, stop the server, run `git pull --ff-only`, rerun
`bash scripts/setup_web_pi5.sh`, then restart. Download a backup before updates.
Automatic startup and appliance installation will be added in the packaging phase.

## Generated Pikachu trade option

There is no virtual Pikachu box. In **Trading → Trade with your Switch**, choose
its destination and check **Use a valid generated Pikachu** below the outgoing
Pokémon dropdown. The app prepares a valid Pikachu for that game with PKHeX and
gives each real offer a fresh PID/encryption constant. It never occupies a Bank
slot. The dropdown is disabled while this option is selected; uncheck it to trade
a stored Pokémon instead. Your receiving trainer must be saved in Settings.

The Bank has 32 boxes of 30 Pokémon each (960 slots). Imports and confirmed
incoming trades fill the first empty slot, starting at box 1, slot 1 and continuing
in box/slot order. Duplicate records remain in their existing slots.
Existing Banks and older backups automatically expand to 32 boxes while retaining
Pokémon positions and custom names. Legacy overflow beyond box 32 remains accessible
for recovery, but new deposits use only boxes 1–32. If those 960 slots are full,
make room before starting a generated-Pikachu deposit. Raw recovery files are
retained if committing a received record fails. The simulator also offers
**Include a generated deposit offer** without creating a stored Pokémon.

Removing the old virtual box does not alter stored Pokémon or snapshots. Existing
overflow boxes use their real numbering (the previously displayed box 6 is now
box 5), and old pending Pikachu trades remain recoverable.


## Hardware indicators

The dashboard and sidebar automatically refresh native USB detection every three
seconds and when the browser window regains focus. Connected means an Espressif
native USB serial port is detected; it does not verify its chip, firmware, serial
permissions, or the Switch radio link. Polling never opens/resets the serial port,
so it can run while trading or flashing. Detection failures show Status unavailable
instead of leaving a stale Connected indicator. Demo mode does not probe hardware.
