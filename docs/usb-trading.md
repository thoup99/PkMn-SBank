---
title: USB Sword and Shield hardware test
---
# Phase 5: real Sword/Shield trade using a USB ESP32-S3

The website can start **one real Sword/Shield Link Trade** using the existing
pokeldn engine. The only supported website host is Raspberry Pi 5 with 64-bit
Raspberry Pi OS. Initial physical testing is for Sword/Shield; other games retain
simulation/CLI support. No 3DS integration is included.

## What you need

- Your Pi 5 and an ESP32-S3 connected with a **USB data cable to its native USB
  Serial/JTAG socket**, not a separate UART socket. Attach the required antenna
  if your board uses an external antenna.
- The **wireless radio firmware** `pokeldn-radio-s3.bin`; controller/pad firmware
  does not work as the radio. A USB ID alone does not identify the chip: S3/C3/C6
  share `303a:1001`, so verify the physical S3 board and socket.
- Your Switch running Sword or Shield, and your own locally installed Switch
  `prod.keys`, required by upstream LDN authentication.
- At least one empty slot in normal boxes 1–4 for a reserve-Pikachu deposit, or a
  real outgoing record from those normal boxes that will free a slot.

This code has automated lifecycle and simulated-radio tests. A physical Pi/S3/
Switch test is still required; the assistant does not have access to your board.

## Update the Pi

Stop the website first. Back up your Bank, then run:

```sh
cd ~/PkMn-SBank
git fetch origin
git switch main
git pull --ff-only origin main
bash scripts/setup_web_pi5.sh
```

Setup now installs the original protocol/USB runtime dependencies into `.venv-web`
as well as the website dependencies. Never run the web server as root.

For serial access, add your normal login user to `dialout` if necessary:

```sh
sudo usermod -aG dialout "$USER"
```

Log out and back in (or reboot) after changing groups. Connect the native USB port
and check `ls -l /dev/serial/by-id/` or `ls -l /dev/ttyACM*`.

## Firmware, if the board is not already flashed

You can now flash from the website: open **ESP32** between **History** and
**Settings**, refresh boards, select the native USB port, acknowledge replacement,
and click **Install matching firmware**. The Pi downloads only the matching S3
wireless image, verifies its SHA-256 and S3 header, then runs esptool with an
explicit ESP32-S3 chip guard. Progress and failure details appear on that page.
The Pi needs Internet access; no Switch keys are required for flashing.

If your connected board does not appear in the list, enter download mode **before
starting installation**:

1. Hold **BOOT**.
2. While holding BOOT, press and release **RESET/EN**.
3. Release **BOOT**.
4. Click **Refresh boards and status** on the ESP32 page, then select the port
   that appears. Its name may change when entering download mode.

Do not perform this reset sequence during a flash write. After installation,
reset or reconnect normally to run the wireless firmware.

Flashing is blocked during active or unresolved USB trades and shares the same
exclusive USB lock. Do not unplug or restart the website during writing. If the server restarts, the
page reports an interrupted installation rather than automatically retrying; the
old child retains the lock until it exits (at most ten minutes). A completed flash
means esptool finished, not that Switch/radio communication has been verified.
Use the page’s BOOT/RESET, native-USB, cable and dialout instructions if needed.

The manual alternative follows. Stop any app using the board. The fork currently inherits upstream pokeldn 0.47.0;
its matching release publishes the merged S3 wireless image and checksums:

```sh
cd ~/PkMn-SBank
mkdir -p .web-tools/firmware
cd .web-tools/firmware
curl -fL https://github.com/Decryptu/pokeldn/releases/download/v0.47.0/pokeldn-radio-s3.bin -o pokeldn-radio-s3.bin
curl -fL https://github.com/Decryptu/pokeldn/releases/download/v0.47.0/SHA256SUMS -o SHA256SUMS
grep '  pokeldn-radio-s3.bin$' SHA256SUMS | sha256sum --check --strict -
cd ../..
.venv-web/bin/python -m esptool --chip esp32s3 --port /dev/ttyACM0 write-flash 0x0 .web-tools/firmware/pokeldn-radio-s3.bin
```

Replace `/dev/ttyACM0` with the actual port. The `--chip esp32s3` guard refuses a
different chip. Enter BOOT/loader mode if required by your board, then reconnect
normally after flashing. Flashing replaces the board firmware; skip this step if
the matching wireless firmware is already installed. To build instead, use ESP-IDF
v6.1 and the existing [firmware instructions](gui.md#build-a-desktop-app).

## Install keys locally

At the top of website **Settings**, under **Switch keys**, click **Upload prod.keys**
to open your device’s file picker and select your own `prod.keys` file. The label
next to the button shows whether keys are present; no firmware version is inferred
from key names. If this control is missing after pulling, rebuild the frontend with
`bash scripts/setup_web_pi5.sh`, restart the website and reload the browser. The
Pi validates its text format and required LDN key entries, then installs it with
owner-only file permissions. Uploads replace existing keys atomically and are
blocked during an active USB trade or while an orphan process owns the USB lock.
The file is limited to 256 KiB; invalid uploads leave existing keys unchanged.
Key contents are never returned by the API or included in Bank snapshots. Use
the upload on your trusted LAN; plain HTTP does not encrypt the upload in transit.

Alternatively, keep keys outside the repository and use the existing installer:

```sh
bash scripts/install_switch_keys.sh --source /absolute/path/to/your/prod.keys
```

The default web location is `~/.switch/prod.keys`. You can instead set
`PKMN_SBANK_KEYS=/absolute/path/to/prod.keys` when launching. Upload only through Settings; do not paste keys into a bug report. The UI only reports whether a readable file
is available; it never returns key contents.

## First deposit test

```sh
cd ~/PkMn-SBank
bash scripts/run_web_pi5.sh
```

1. Open `http://<PI-IP>:8000`, save your receiving trainer in Settings, and verify
   box 5 has 30 Pikachus. No manually generated outgoing file is needed.
2. Open **Trading → Real USB trade — Sword / Shield**. Select a reserve Pikachu
   and the attached native USB port. Choose your own eight-digit Link Code.
3. Press **Start real Sword/Shield trade** once. This opens a real radio session,
   not the separate Phase 4 simulator below it.
4. On the Switch, open Sword/Shield's **Y-Comm**, ensure **local communication**,
   choose **Link Trade → Set Link Code**, and enter the same code. Search near the
   board, accept the partner and inspect the offered Pikachu. Use an expendable
   Pokémon for the first test, then confirm the trade on the console.
5. Wait for the game to finish saving and the website to show **completed**.
   The engine allows the upstream save/migration grace period (about 27 seconds
   after protocol confirmation), so the website can finish later than the game.
6. Verify the received Pokémon appears in **boxes 1–4** and box 5 is still full.
   Refresh/restart the website and confirm the record persists. Export a copy and
   download a backup before another test.

For a withdrawal/exchange test, select a real Bank record instead of a reserve
Pikachu. After a durable protocol confirmation, the received record and removal of
the outgoing record are committed **atomically**. The reserve is unaffected.
Each website run is bounded to one trade; start a new run for the next trade.
Do not initiate a second exchange in the same console session.

## Stop, disconnect, restart and recovery

**Stop USB trade** closes the managed child's stdin, allowing the original engine
to leave the network. It escalates to termination if needed. A durable confirmation
already written is still processed; cancellation cannot undo an actual trade.

Incoming candidate bytes are fsynced before confirmation. A separate fsynced
`confirmed.json` records the completed protocol exchange and exact incoming/offered
hashes. Bank originals are not removed on stdout text, a process exit code, or an
unconfirmed offered record.

If the session is **uncertain/interrupted**, do not automatically repeat it. Check
the console and use **Recover confirmed receipt** after the old process has exited.
A restarted server cannot safely signal a child it no longer owns: wait for the
bounded run's deadline (up to five minutes after the radio starts), or reboot the
Pi to stop the orphan, before recovery. An inherited OS file lock prevents another
web process from opening a second session while the old child is alive.

If no confirmation exists, the UI requires you to acknowledge that you stopped
the old process and checked the game before **Resolve unconfirmed session**.
That keeps all raw files and Bank originals; it does not invent a deposit or mark
a real trade successful. If a confirmation exists, resolution is refused: recover
it instead. **recovery_required** retains the receipt after a parsing/disk/Bank
commit error; fix the problem and recover without trading again.

Private recovery files are retained under:

```text
$POKELDN_DATA/web-bank/live-runs/<session-id>/
```

The default `POKELDN_DATA` is `~/.local/share/pkmn-sbank`. Each folder holds the
outgoing offer, session metadata, candidate/confirmation if present, and bounded
process logs. Do not delete these files during an unresolved trade. Resolve or
recover USB sessions **before** restoring an older Bank snapshot. Old backups can
reintroduce already-sent records; a byte mismatch blocks automatic removal and
retains the receipt for inspection. This is a trusted-LAN test server, not an
Internet-facing or multi-user service.

## Troubleshooting

- No board listed: check native USB socket, data cable and matching wireless
  firmware. IDs are not a chip/firmware health check; handshake errors appear in
  the USB session log.
- Permission denied: check `dialout`, re-login and make sure no other app/flasher
  holds the port. Do not run two website servers or GUI trade sessions together.
- No partner: check local rather than online communication, matching code,
  antenna, distance, and correct game. The first implementation is Sword/Shield.
- Full normal boxes: make space before starting; the reserve is never an incoming
  destination. An uncommitted received file stays in recovery storage.
- Missing dependencies/helper: rerun the setup script, then restart the website.
- Recovery lock busy: the old process still owns the board; wait for it or reboot
  before trying recovery. No automatic retries are performed after ambiguity.
