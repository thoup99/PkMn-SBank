"""Fixed-version, checksum-verified ESP32-S3 radio installer child process."""
import hashlib
import os
from pathlib import Path
import re
import signal
import sys

from pokeldn import __version__
from pokeldn.app import update

RELEASE = 'v' + __version__
IMAGE = 'pokeldn-radio-s3.bin'
BASE = f'https://github.com/Decryptu/pokeldn/releases/download/{RELEASE}'
IMAGE_LIMIT = 4 * 1024 * 1024


def download_image(folder, say=print, get=None):
    def fetch(url, limit):
        with update._open(url) as reply:
            return update.read_bytes(reply, limit, 60)
    get = get or fetch
    say(f'Downloading matching wireless radio firmware from {RELEASE}…')
    sums = get(BASE + '/SHA256SUMS', 100_000).decode('ascii')
    matches = [m[1].lower() for line in sums.splitlines()
               if (m := re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?' + re.escape(IMAGE), line.strip()))]
    if len(matches) != 1:
        raise ValueError('The release does not contain one valid S3 checksum. Nothing was flashed.')
    data = get(BASE + '/' + IMAGE, IMAGE_LIMIT)
    if len(data) > IMAGE_LIMIT or hashlib.sha256(data).hexdigest() != matches[0]:
        raise ValueError('Firmware SHA-256 mismatch. Nothing was flashed.')
    # A merged S3 image starts with the ROM bootloader at offset 0, chip ID 9.
    if len(data) < 24 or data[0] != 0xE9 or int.from_bytes(data[12:14], 'little') != 9:
        raise ValueError('This is not a merged ESP32-S3 image. Nothing was flashed.')
    path = Path(folder) / IMAGE
    path.write_bytes(data)
    say('Firmware checksum and ESP32-S3 image header verified.')
    return path


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--folder', required=True)
    args = parser.parse_args()
    # Survives exec: even an orphaned esptool releases the inherited USB lock after ten minutes.
    signal.alarm(600)
    path = download_image(args.folder, lambda text: print(text, flush=True))
    print('Connecting to ESP32-S3. If needed: hold BOOT, tap RESET/EN, release BOOT. Do not unplug during writing.', flush=True)
    os.execv(sys.executable, [sys.executable, '-u', '-m', 'esptool', '--chip', 'esp32s3',
                            '--port', args.port, '--baud', '460800', 'write-flash', '0x0', str(path)])


if __name__ == '__main__':
    main()
