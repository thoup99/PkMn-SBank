"""Pi firmware jobs sharing the native trading engine's exclusive USB lock."""
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid

from pokeldn.app.paths import ROOT
from pokeldn.web.firmware_runner import RELEASE, IMAGE
from pokeldn.web.live import PENDING
from pokeldn.web.storage import StorageError, durable_write, sync_dir

ACTIVE = {'starting', 'running'}


class FirmwareInstaller:
    def __init__(self, usb, *, process_factory=None):
        self.usb = usb
        self.root = usb.store.root
        self.path = self.root / 'firmware-job.json'
        self.owner = uuid.uuid4().hex
        self.process_factory = process_factory or subprocess.Popen
        self.proc = None
        self.worker = None
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text())

    def _save(self, job):
        temporary = self.root / ('.firmware-job-' + uuid.uuid4().hex + '.tmp')
        try:
            durable_write(temporary, json.dumps(job).encode())
            os.replace(temporary, self.path)
            sync_dir(self.root)
        finally:
            temporary.unlink(missing_ok=True)

    def current(self):
        with self.lock:
            job = self._read()
            if job and job['status'] in ACTIVE and (job['owner'] != self.owner or
                    (self.worker is not None and not self.worker.is_alive() and self.proc is not None and self.proc.poll() is not None)):
                job.update(status='interrupted', message='The server restarted during installation. Do not unplug a board still writing. Wait up to ten minutes for the old process, then refresh and retry only if needed.')
                self._save(job)
            supported = self.usb.host_check()
            return {'supported_host': supported, 'release': RELEASE, 'image': IMAGE,
                    'esptool_available': importlib.util.find_spec('esptool') is not None,
                    'devices': self.usb.devices() if supported else [], 'job': copy.deepcopy(job)}

    def start(self, device, request_id):
        with self.lock, self.usb.lock:
            if not self.usb.host_check():
                raise StorageError('Firmware installation requires the Raspberry Pi 5 server.', 422)
            if not re.fullmatch(r'[0-9a-f-]{36}', request_id):
                raise StorageError('Invalid firmware request ID.', 422)
            previous = self._read()
            if previous and previous['request_id'] == request_id:
                return previous
            if previous and previous['status'] in ACTIVE:
                raise StorageError('A firmware installation is already active. Refresh its status first.')
            if importlib.util.find_spec('esptool') is None:
                raise StorageError('Run bash scripts/setup_web_pi5.sh on the Pi to install esptool.', 422)
            if device not in {p['device'] for p in self.usb.devices()}:
                raise StorageError('Select a connected native-USB ESP32-S3 port.', 422)
            if not os.access(device, os.R_OK | os.W_OK):
                raise StorageError('Serial permission denied. Add your Pi user to dialout and log in again.', 422)
            session = self.usb._read()
            if session and session['status'] in PENDING:
                raise StorageError('Stop and recover or resolve the USB trade before flashing firmware.')
            fd = self.usb._usb_lock()
            try:
                job = {'id': uuid.uuid4().hex, 'request_id': request_id, 'owner': self.owner,
                       'status': 'starting', 'device': device, 'release': RELEASE,
                       'started_at': time.time(), 'message': 'Preparing matching firmware.', 'logs': []}
                folder = self.root / 'firmware-runs' / job['id']
                folder.mkdir(parents=True, mode=0o700)
                job.update(status='running', message='Installation started. Keep the USB cable connected and watch the log.')
                self._save(job)
                # The child writes to a file, so a server restart cannot break its stdout pipe mid-flash.
                log_path = folder / 'process.log'
                with log_path.open('w') as output:
                    self.proc = self.process_factory(
                        [sys.executable, '-u', '-m', 'pokeldn.web.firmware_runner', '--port', device,
                         '--folder', str(folder)], cwd=ROOT, stdin=subprocess.DEVNULL,
                        stdout=output, stderr=subprocess.STDOUT, pass_fds=(fd,), start_new_session=True)
                self.worker = threading.Thread(target=self._run, args=(job, self.proc, fd, log_path), daemon=True)
                self.worker.start()
                fd = None
                return copy.deepcopy(job)
            except Exception:
                if self.proc is not None and self.proc.poll() is None:
                    self.proc.kill()
                    self.proc.wait()
                if 'job' in locals():
                    job.update(status='failed', message='Unable to start installation. Check Pi dependencies and storage, then retry.')
                    self._save(job)
                raise
            finally:
                if fd is not None:
                    os.close(fd)

    def _run(self, job, proc, fd, log_path):
        try:
            with log_path.open(encoding='utf-8', errors='replace') as output:
                while True:
                    line = output.readline()
                    if not line:
                        if proc.poll() is not None:
                            # Drain bytes flushed just before process exit on the next iteration.
                            line = output.readline()
                            if not line:
                                break
                        else:
                            time.sleep(0.1)
                            continue
                    with self.lock:
                        job['logs'] = (job['logs'] + [line.rstrip()[:1000]])[-100:]
                        try:
                            self._save(job)
                        except OSError:
                            # A full log disk must not interrupt a board that is being written.
                            pass
            code = proc.wait()
            with self.lock:
                job.update(status='completed' if code == 0 else 'failed', returncode=code,
                           message='Firmware written and verified by esptool. Reconnect/reset the board, then test a trade; a radio handshake has not yet been checked.' if code == 0 else
                           'Installation failed or timed out. Read the log, check USB/BOOT and permissions, then retry. Do not assume the board is ready.')
                self._save(job)
        except Exception:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            with self.lock:
                job.update(status='failed', message='Installation monitoring failed. Check the board before retrying.')
                self._save(job)
        finally:
            os.close(fd)
