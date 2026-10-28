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

Node.js 22.12+ (or 24 LTS) is needed to build the frontend. The API demo does not
need .NET, Switch keys, a board, Flet, or the upstream Python dependencies.

```sh
python -m pip install -r requirements-web.txt
cd web
npm ci
npm run dev
```

In another terminal, from the repository root:

```sh
python -m uvicorn pokeldn.web.app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:5173` or `http://<host-LAN-IP>:5173` on a phone.
Vite proxies `/api` to FastAPI. Hash navigation supports refresh/back/forward.
The Dashboard, Boxes, Trading, History, and Settings pages use read-only synthetic
data. Search and filters apply to the current box without moving slot positions.
Preferences last for the page session. Trading is explicitly unavailable.

### Serve on a Raspberry Pi 5

Use a 64-bit Raspberry Pi OS / Linux installation and the same Python/Node build
steps. Build once and serve everything from FastAPI (Node is not needed at runtime):

```sh
cd web
npm ci
npm run build
cd ..
python -m uvicorn pokeldn.web.app:app --host 0.0.0.0 --port 8000
```

Open `http://<pi-LAN-IP>:8000`. The API and static frontend share one origin; no
CORS configuration is required. `PKMN_SBANK_WEB_DIST` can override the build folder.
Restart the API after building. This is a LAN development preview: no login,
Internet exposure, boot service, hotspot, hardware control, or real persistence is
provided. These belong to later milestones. Do not use the Vite development
server as the appliance's production server.

### Website checks

```sh
python -m pip install -r requirements-web.txt pytest==9.1.1 httpx==0.28.1
python -m pytest --confcutdir=tests tests/test_web.py -q
cd web
npm ci
npm test
npm run build
```

Local sprites for the twelve sample species are bundled for offline browsing;
see `web/public/sprites/README.md` for attribution. Missing images fall back to
species initials. Demo data must never be interpreted as imported records,
legality results, or completed transfers.
