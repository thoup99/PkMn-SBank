---
title: Website-first development
---
# Website-first development

## Phase 1: preserve the engine

Use Python 3.13 and .NET SDK 10. The upstream protocol engines, CLI, Bank,
PKHeX service, firmware, shared GUI and Windows/Linux apps remain available.
Only the Android/iOS applications, their release tools, macOS packaging and
app-specific scheduler test were removed. Platform adapters in shared Python
code and their tests remain to avoid breaking shared imports and transport support.
UPSTREAM_README.md remains an archival copy; its mobile/macOS installation
instructions do not describe this fork's supported app builds.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt 'flet[desktop]==1.0.2'
dotnet build -c Release services/pkhex -warnaserror
python -m pytest tests/ -q -W error -n auto --dist worksteal
```

## Phase 2: browser foundation

React, TypeScript and Vite provide the browser UI; FastAPI serves the API and
production frontend on the Linux host. This phase uses explicitly labeled sample
data, not the real Bank. Real storage and Switch session coordination follow in
later phases. The Raspberry Pi 5 hosts application logic and records; ESP32-S3
remains a future radio connection. No 3DS API, save access or integration belongs
in these phases. The companion repository stays unchanged.

### Run the website locally

Node.js 22.12+ (or 24 LTS) is needed to build the frontend. The API needs the built PKHeX helper for real imports. The read-only demo does not
need .NET, Switch keys, a board, Flet, or upstream protocol dependencies.

```sh
python -m pip install -r requirements-web.txt
cd web
npm ci
npm run dev
```

In another terminal, from the repository root:

```sh
PKMN_SBANK_MODE=demo python -m uvicorn pokeldn.web.app:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:5173` or `http://<host-LAN-IP>:5173` on a phone.
Vite proxies `/api` to FastAPI. Hash navigation supports refresh/back/forward.
The Dashboard, Boxes, Trading, History, and Settings pages use read-only synthetic
data. Search and filters apply to the current box without moving slot positions.
Preferences last for the page session. Trading is explicitly unavailable.

## Phase 3: real Bank storage on Raspberry Pi 5

The website now defaults to the persistent Bank, with validated imports, original
Bank duplicate handling, exports, box organization and snapshot recovery. The
supported server is **Raspberry Pi 5 with 64-bit Raspberry Pi OS only**; other
computers and phones are browser clients. See [Pi 5 deployment and test steps](pi5-website.md)
for the feature-branch checkout, installer, launch commands and recovery checklist.
Switch trading and 3DS integration have not started.

Developer tests may run on CI without Pi hardware. `pokeldn.web.serve` is the
hardware-checked deployment entry point; direct ASGI testing is for development.
Set `PKMN_SBANK_MODE=demo` to use the read-only sample mode from Phase 2.

### Website checks

```sh
python -m pip install -r requirements-web.txt pytest==9.1.1 httpx==0.28.1
python -m pytest --confcutdir=tests tests/test_web.py tests/test_web_storage.py -q
cd web
npm ci
npm test
npm run build
```

Local sprites for the twelve sample species are bundled for offline browsing;
see `web/public/sprites/README.md` for attribution. Missing images fall back to
species initials. Demo data must never be interpreted as imported records,
legality results, or completed transfers.
