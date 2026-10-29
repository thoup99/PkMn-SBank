---
title: Simulated website trading
---
# Phase 4: simulated trading on the Pi 5

The Trading page now stages up to six real Bank Pokémon, checks whether PKHeX
can prepare them for a selected Switch game, and exercises session controls with
synthetic connection, partner and confirmation events. **No real trade occurs.**
Nothing opens an ESP32-S3, radio, socket to a console or upstream trade launcher.
Every original record remains in the Bank, even after a simulated completion.
Real Switch trading is Phase 5; 3DS integration is still deferred.

## Update and run on your Pi

Stop the current website with Ctrl+C and download a backup before updating.
After the Phase 4 PR has merged into `main`:

```sh
cd ~/PkMn-SBank
git fetch origin
git switch main
git pull --ff-only origin main
bash scripts/setup_web_pi5.sh
bash scripts/run_web_pi5.sh
```

Open `http://<PI-LAN-IP>:8000` and refresh the browser. The supported server
remains Raspberry Pi 5 with 64-bit Raspberry Pi OS; laptops and phones are browser
clients. No keys or board are needed to simulate. See [Pi deployment](pi5-website.md)
for first installation, backups, data paths and troubleshooting.

## Stage and validate

1. Save your receiving trainer in **Settings** and import a copy of a Pokémon file
   or game save in **Pokémon boxes**. Keep your own backup outside the Pi.
2. Open **Trading** and select Sword/Shield, Scarlet/Violet, Brilliant
   Diamond/Shining Pearl, Legends Arceus, Let's Go, Legends Z-A or FireRed/LeafGreen.
   Ruby/Sapphire/Emerald is not offered as a Switch trade destination.
3. Select one to six Bank Pokémon, optionally using **Include a generated deposit offer** to add a Pikachu without a Bank record. Their queue order is their selection order;
   uncheck/reselect to change it. Search by species or source game if needed.
4. Choose **Check compatibility**. Each result is compatible or refused with
   PKHeX's reason. Review conversion and HOME-tracker warnings. This assesses
   preparation for the game, not an authenticity guarantee or a hardware test.
5. Choose **Stage simulation queue** only when every result is compatible.
   Changing the selection or game requires another check. Trainer/record changes
   invalidate a stale preview, and preparation is checked again on stage/start.

The preparation path uses the upstream PKHeX move and final-record check, without
changing the original trainer or rewriting the original Bank file. Prepared bytes
are not stored/exported by the simulator; only display information and hashes are
kept. Actual transfer orchestration and destination-game save writes are absent.

## Test each scenario

Choose a scenario on the staged session, then **Start simulation**. Use
**Advance simulation** to inject the next event. Progress is deliberately manual:
there is no hidden timed worker making confirmations.

| Current status | Next Advance simulation |
| --- | --- |
| connecting | Simulated connection ready; status becomes waiting |
| waiting | Simulated partner ready; status becomes exchanging |
| exchanging | Confirmation, or the selected disconnect/failure before confirmation |

After each confirmation, another queued Pokémon waits for its partner. The last
confirmation ends the simulation. Both the progress bar and log explicitly label
these as simulated confirmations, with **zero real transfers**.

- **Success:** advance until completed. Inspect/export the originals in Boxes;
  their records and positions should be unchanged.
- **Disconnect:** choose the number of confirmations before the fault (zero through
  queue length minus one). Advance to the disconnect. The failed item is not counted.
  Choose **Resume simulation** and advance again. The fault is injected once per
  session; the remaining queue completes without repeating confirmed items.
- **Failure:** repeat the same test with Failure before confirmation. It should
  stop before adding a confirmation and offer explicit resume or cancellation.
- **Partial queue:** stage at least two Pokémon and inject the fault after one
  confirmation. Resume and verify the counter reaches the queue length exactly,
  rather than counting the first confirmation twice.
- **Cancel:** cancel while staged or running. The session ends; the Bank keeps
  every original record. Stage a fresh queue for another test.

## Refresh, restart and recover

A browser refresh loads the same persisted session. The page polls its status
while running; **Refresh session status** is also available. Polling never makes
a confirmation or advances progress by itself.

To test a server restart, stop it during a running simulation, then run
`bash scripts/run_web_pi5.sh` again. The first session read marks that run
**interrupted**. It cannot advance automatically. Choose **Resume simulation** to
revalidate the queue and continue, or cancel and stage a new queue. Already saved
simulated confirmations are retained. A duplicate/stale button request is refused
using the session ID and version, rather than applying a step twice.

Bank/trainer edits are blocked while a simulation is connecting, waiting or
exchanging. Finish/cancel it before importing, moving or renaming Bank data or
changing trainer settings. Backup downloads remain available. Restoring a Bank
snapshot (including offline ZIP recovery) invalidates the old session: stage a
fresh queue rather than resuming against restored records.

Storage/session events appear in **History** and all states use the existing
atomic snapshot mechanism. No path calls the upstream Bank's real trade-completion
removal logic. Serve the website with the supplied single-worker Pi launcher;
multiple web server workers are not supported for simulation ownership. If another
process takes ownership, the old active session fails safe to interrupted.

## Developer verification

Build the PKHeX helper and install the existing test dependencies first:

```sh
dotnet build -c Release services/pkhex -warnaserror
python -m pytest tests/test_web.py tests/test_web_storage.py tests/test_web_trading.py -q -W error
cd web
npm test
npm run build
```

The suite exercises real PKHeX conversion/refusal, preserved original bytes,
partial failures, cancellation, duplicate requests, explicit restart recovery,
Bank mutation guards and API/demo isolation. Physical Pi/browser/hardware testing
is still necessary before claiming real Switch support.
