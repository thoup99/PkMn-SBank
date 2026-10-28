#!/usr/bin/env bash
# Website/storage setup only. No radio, networking, keys, firmware or GUI changes.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Usage: bash scripts/setup_web_pi5.sh [--no-apt]'
    echo 'Build the website and PKHeX helper on Raspberry Pi 5, 64-bit Raspberry Pi OS.'
    exit 0
fi
if [[ $# -gt 1 || ($# -eq 1 && $1 != --no-apt) ]]; then
    echo 'Unknown option. Use --help.' >&2; exit 2
fi
if [[ $(uname -m) != aarch64 ]] || ! tr -d '\0' < /proc/device-tree/model 2>/dev/null | grep -q '^Raspberry Pi 5 Model'; then
    echo 'Requires a Raspberry Pi 5 with 64-bit Raspberry Pi OS.' >&2; exit 1
fi
if [[ ${1:-} != --no-apt ]]; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv git curl xz-utils build-essential libicu-dev libssl-dev libkrb5-3 zlib1g ca-certificates
fi
# Install per-checkout tools; no system Node/.NET packages are replaced.
mkdir -p "$ROOT/.web-tools"
NODE_VERSION=24.22.1
NODE_HOME="$ROOT/.web-tools/node-v${NODE_VERSION}-linux-arm64"
if [[ ! -x "$NODE_HOME/bin/node" ]]; then
    TEMP=$(mktemp -d)
    trap 'rm -rf "$TEMP"' EXIT
    ARCHIVE="node-v${NODE_VERSION}-linux-arm64.tar.xz"
    curl --fail --location --retry 3 "https://nodejs.org/dist/v${NODE_VERSION}/$ARCHIVE" -o "$TEMP/$ARCHIVE"
    curl --fail --location --retry 3 "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" -o "$TEMP/SHASUMS256.txt"
    (cd "$TEMP"; grep "  $ARCHIVE$" SHASUMS256.txt | sha256sum --check --strict -)
    tar -xJf "$TEMP/$ARCHIVE" -C "$ROOT/.web-tools"
fi
export PATH="$NODE_HOME/bin:$ROOT/.web-tools/dotnet:$PATH"
export DOTNET_ROOT="$ROOT/.web-tools/dotnet"
if [[ ! -x "$DOTNET_ROOT/dotnet" ]]; then
    curl --fail --location --retry 3 https://dot.net/v1/dotnet-install.sh -o "$ROOT/.web-tools/dotnet-install.sh"
    bash "$ROOT/.web-tools/dotnet-install.sh" --channel 10.0 --architecture arm64 --install-dir "$DOTNET_ROOT" --no-path
fi
cd "$ROOT"
python3 -m venv .venv-web
.venv-web/bin/python -m pip install --upgrade pip
.venv-web/bin/python -m pip install -r requirements-web.txt
# Native self-contained linux-arm64 helper: no dotnet PATH requirement at runtime.
dotnet publish services/pkhex -c Release -r linux-arm64 -p:PublishTrimmed=false -o services/pkhex/dist -warnaserror
(cd web; npm ci; npm run build)
echo 'Build complete. Start with: bash scripts/run_web_pi5.sh'
