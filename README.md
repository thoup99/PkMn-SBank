# PkMn-SBank

**A self-hosted Pokémon transfer bridge — move Pokémon between generations, not into permanent storage.**

> **Status: Early development.** PkMn-SBank is a fork of [Decryptu/pokeldn](https://github.com/Decryptu/pokeldn). The upstream trading engine is present in this repository; the website now has real Bank storage and a simulated trading workflow for Raspberry Pi 5 testing. A bounded Sword/Shield and Legends Z-A USB trade path is implemented for Pi/ESP32-S3 hardware testing; physical validation is still required. Appliance startup/hotspot setup and the 3DS companion remain planned.

## What we're building

PkMn-SBank (Pokémon Super Bank) aims to make it quick and convenient to move Pokémon between supported games and generations. A Raspberry Pi 5 hosts a local website with familiar Pokémon boxes, while the existing pokeldn trading protocols connect to unmodified Nintendo Switch games. A separate, future homebrew app will enable save-backed transfers on custom-firmware Nintendo 3DS consoles.

The boxes are primarily a **temporary transfer and recovery area**, not a promise of long-term cloud storage. We intend to preserve records until a transfer finishes safely and provide explicit backups and recovery paths.

## Planned system

```text
Phone / laptop browser
        |
    Wi-Fi / LAN
        |
Raspberry Pi 5 (64-bit Raspberry Pi OS; the only supported website host)
  - Self-hosted web interface and API
  - pokeldn game/trade engine and Pokémon Bank
  - PKHeX.Core compatibility and conversion
  - Transfer coordination, logs, and recovery
        |
        +--- USB ---> ESP32-S3 (pokeldn radio firmware)
        |                 |
        |          Stock Nintendo Switch
        |
        +--- Wi-Fi ---> Future 3DS homebrew app
                         |
                    CFW Nintendo 3DS
```

The ESP32-S3 **does not store the Pokémon Bank or run the trading engine**. It acts as a wireless interface; Pokémon records and application logic live on the Linux host. For Sword/Shield, pokeldn also supports a LAN mode that does not require an ESP32.

The intended appliance can host a local Wi-Fi hotspot for offline use, with the option to join an existing network during development or operation.

## Priorities

### Website-first release (v1)

1. **Preserve the upstream backend.** Keep all existing pokeldn game support, trading protocols, Bank functionality, PKHeX.Core integration, CLI utilities, tests, and firmware. Remove only iOS, Android, and macOS app/build targets as part of the migration, without deleting shared code.
2. **Create the website.** Build a responsive browser interface for a dashboard, 30-slot Pokémon boxes, Pokémon details, basic settings, and transfer history.
3. **Integrate real storage.** Display, organize, import, and export actual records using pokeldn's Bank implementation, with safe persistence, backups, and duplicate handling.
4. **Implement the trade workflow.** Choose a game, stage compatible Pokémon, prepare them through PKHeX.Core, and monitor a session. Validate the interface with a simulated mode first.
5. **Connect real Switch trading.** Use existing pokeldn sessions with the ESP32-S3 radio, starting with a supported game such as Sword/Shield; test deposits, withdrawals, disconnects, and recovery.
6. **Package the Linux appliance.** Automatic startup, optional 2.4 GHz hotspot, local web address, diagnostics, and documented installation/update steps.

**v1 is complete only when the website works on the target Linux hardware and a real stock Switch can deposit and withdraw Pokémon with recoverable failure handling.**

### After website v1

- **3DS companion:** Develop [PkMn-SBank-3ds](https://github.com/thoup99/PkMn-SBank-3ds), a separate CFW homebrew application for backed-up save extraction and insertion. Target Ultra Sun / Ultra Moon first, then explore X/Y and Omega Ruby / Alpha Sapphire.
- **Cross-generation transfers:** Coordinate transfers through the staging boxes, with explicit destination compatibility checks.
- **Legacy Conversion (advanced, optional):** Investigate backward-generation conversions (for example, Gen 8 to Gen 6), prioritizing preservation of OT, IVs, EVs, nature, and compatible battle attributes while clearly identifying reconstructed historical metadata. These transformations are not official transfers and may be impossible for some Pokémon. No authenticity or legality guarantee is implied.
- **More web features:** Expose additional functionality that already exists in pokeldn, such as raids and gifts, without removing the underlying support in the meantime.

## What exists today vs. what is planned

| Component | State |
| --- | --- |
| Original pokeldn trading engines, protocols, CLI, Bank, and ESP32 firmware | **Inherited from upstream** |
| Browser-based boxes, imports/exports and backups | **Phase 3 implemented for Pi 5 testing** — real Bank storage; trading deferred |
| Raspberry Pi boot service, hotspot, and deployment | **Planned** |
| Website preparation and session controls | **Phase 4 implemented in simulation** — PKHeX checks; originals stay in Bank |
| ESP32-S3 setup from the website | **Implemented** — ESP32 page installs matching, checksum-verified wireless firmware and shows setup instructions |
| Real Switch trades launched from our website | **Phase 5 hardware-test implementation** — bounded Sword/Shield and Legends Z-A USB session and durable receipt recovery |
| CFW 3DS homebrew app and save transfers | **Planned**, after website v1 |
| Backward-generation / destructive conversion | **Future research** |

Test the website on your Pi using [Raspberry Pi 5 deployment steps](docs/pi5-website.md), then follow [simulated trading tests](docs/simulated-trading.md) or [USB Sword/Shield and Z-A hardware testing](docs/usb-trading.md). The website server targets Raspberry Pi 5 only; phones/computers connect as browser clients. Refer to the preserved pokeldn documentation for upstream setup and CLI usage.

## Repositories and documentation

- **Main fork:** [PkMn-SBank](https://github.com/thoup99/PkMn-SBank) — Linux host application, web frontend/API, original pokeldn backend, and ESP32 firmware.
- **3DS companion:** [PkMn-SBank-3ds](https://github.com/thoup99/PkMn-SBank-3ds) — separately developed custom-firmware 3DS homebrew app.
- **Upstream project:** [Decryptu/pokeldn](https://github.com/Decryptu/pokeldn).
- **Preserved upstream README:** [UPSTREAM_README.md](UPSTREAM_README.md) — original overview, supported-game matrix, setup instructions, credits, and disclaimers.
- **Existing technical documentation:** [docs/](docs/) — game protocols, hardware, command-line usage, and architecture.

See [website development](docs/web-development.md) for the supported development environment and platform migration.

The fork will track upstream changes where practical. New work should be made in small, reviewable changes without unnecessarily rewriting protocol implementations.

## Licensing and disclaimer

This fork retains pokeldn's **AGPL-3.0** license, along with applicable third-party notices and the credits found in [the upstream README](UPSTREAM_README.md). The separate 3DS companion will document its own licensing before distribution.

PkMn-SBank is an unofficial fan-made project and is **not affiliated with or endorsed by Nintendo, The Pokémon Company, Game Freak, or Creatures**. Pokémon and related names are trademarks of their respective owners. This project does not grant rights to any third-party intellectual property.
