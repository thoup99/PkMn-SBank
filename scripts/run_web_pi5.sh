#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
export POKELDN_DATA="${POKELDN_DATA:-$HOME/.local/share/pkmn-sbank}"
export PKMN_SBANK_MODE="${PKMN_SBANK_MODE:-bank}"
if [[ ! -x .venv-web/bin/python || ! -f web/dist/index.html || ! -x services/pkhex/dist/pokeldn-pkhex ]]; then
    echo 'Build first: bash scripts/setup_web_pi5.sh' >&2; exit 1
fi
exec .venv-web/bin/python -m pokeldn.web.serve "$@"
