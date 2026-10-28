"""Run the website appliance on a 64-bit Raspberry Pi 5."""
import argparse
import os
import platform
from pathlib import Path
import sys


def supported_host(model=None, machine=None, system=None):
    if model is None:
        try:
            model = Path('/proc/device-tree/model').read_text().rstrip('\0')
        except OSError:
            return False
    return ((system or sys.platform).startswith('linux') and
            (machine or platform.machine()).lower() in ('aarch64', 'arm64') and
            model.startswith('Raspberry Pi 5 Model'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if not supported_host():
        parser.error('This website deployment requires a Raspberry Pi 5 running 64-bit Raspberry Pi OS.')
    os.umask(0o077)
    import uvicorn
    uvicorn.run('pokeldn.web.app:app', host=args.host, port=args.port, workers=1)


if __name__ == '__main__':
    main()
