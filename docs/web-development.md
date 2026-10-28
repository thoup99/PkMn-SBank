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
