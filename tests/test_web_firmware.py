import hashlib
import os
from pathlib import Path
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from pokeldn.web import firmware_runner as runner
from pokeldn.web.firmware import FirmwareInstaller
from pokeldn.web.live import LiveTrading
from pokeldn.web.storage import BankStore, StorageError


def image():
    data = bytearray(64)
    data[0] = 0xe9
    data[12] = 9
    return bytes(data)


def test_download_verifies_pinned_s3_image(tmp_path):
    data = image()
    calls = []
    def get(url, limit):
        calls.append(url)
        return (hashlib.sha256(data).hexdigest() + '  ' + runner.IMAGE).encode() if url.endswith('SHA256SUMS') else data
    path = runner.download_image(tmp_path, get=get)
    assert path.read_bytes() == data
    assert calls == [runner.BASE+'/SHA256SUMS', runner.BASE+'/'+runner.IMAGE]
    assert '/' + runner.RELEASE + '/' in calls[0]


@pytest.mark.parametrize('kind', ['checksum', 'missing', 'wrong-chip', 'oversized'])
def test_bad_download_never_creates_flash_image(tmp_path, kind):
    data = bytearray(image())
    if kind == 'wrong-chip':data[12] = 5
    if kind == 'oversized':data.extend(bytes(runner.IMAGE_LIMIT))
    digest = '0'*64 if kind == 'checksum' else hashlib.sha256(data).hexdigest()
    sums = b'' if kind == 'missing' else f'{digest}  {runner.IMAGE}'.encode()
    with pytest.raises(ValueError):
        runner.download_image(tmp_path, get=lambda url, limit:sums if url.endswith('SHA256SUMS') else bytes(data))
    assert not (tmp_path/runner.IMAGE).exists()


@pytest.mark.skipif(os.name != 'posix', reason='Pi installer deadline')
def test_child_execs_guarded_esptool_after_verification(tmp_path, monkeypatch):
    calls = []; alarms = []
    monkeypatch.setattr(runner, 'download_image', lambda folder, say:tmp_path/runner.IMAGE)
    monkeypatch.setattr(runner.signal, 'alarm', alarms.append)
    monkeypatch.setattr(runner.os, 'execv', lambda exe, args:calls.append(args))
    monkeypatch.setattr(runner.sys, 'argv', ['firmware_runner','--port','/dev/ttyACM0','--folder',str(tmp_path)])
    runner.main()
    assert alarms == [600]
    assert calls[0][2:6] == ['-m','esptool','--chip','esp32s3']
    assert calls[0][-3:] == ['write-flash','0x0',str(tmp_path/runner.IMAGE)]


class FakeProcess:
    def __init__(self, args, **kwargs):
        self.args = args; self.kwargs = kwargs; self.code = 0
        kwargs['stdout'].write('Writing firmware\nHash of data verified\n'); kwargs['stdout'].flush()
    def poll(self):return self.code
    def wait(self):self.code = 0; return 0
    def kill(self):self.code = -9


@pytest.fixture
def manager(tmp_path):
    device = tmp_path/'ttyACM0'; device.touch()
    usb = LiveTrading(BankStore(tmp_path/'bank'), host_check=lambda:True,
                      devices=lambda:[{'device':str(device),'description':'Test native USB'}])
    return FirmwareInstaller(usb, process_factory=FakeProcess), str(device)


@pytest.mark.skipif(os.name != 'posix', reason='Pi USB file lock')
def test_completed_job_persists_and_replay_does_not_flash_again(manager):
    installer, device = manager
    request = str(uuid.uuid4())
    job = installer.start(device, request); installer.worker.join(5)
    result = installer.current()['job']
    assert result['status'] == 'completed'
    assert 'Hash of data verified' in result['logs']
    assert installer.start(device, request)['id'] == job['id']
    assert installer.proc.kwargs['pass_fds']
    assert '--port' in installer.proc.args
    restarted = FirmwareInstaller(installer.usb)
    assert restarted.current()['job']['status'] == 'completed'
    fd = installer.usb._usb_lock(); os.close(fd)


@pytest.mark.skipif(os.name != 'posix', reason='Pi USB file lock')
def test_flash_blocks_other_usb_owners_and_restart_does_not_retry(manager):
    installer, device = manager; finished = threading.Event()
    def factory(*args, **kwargs):
        process = FakeProcess(*args, **kwargs)
        process.poll = lambda:0 if finished.is_set() else None
        return process
    installer.process_factory = factory
    installer.start(device, str(uuid.uuid4()))
    try:
        with pytest.raises(StorageError):installer.usb._usb_lock()
        with pytest.raises(StorageError):installer.start(device, str(uuid.uuid4()))
        restarted = FirmwareInstaller(installer.usb, process_factory=lambda *a,**k:pytest.fail('no auto retry'))
        assert restarted.current()['job']['status'] == 'interrupted'
        with pytest.raises(StorageError):restarted.start(device, str(uuid.uuid4()))
    finally:
        finished.set(); installer.worker.join(5)
    fd = installer.usb._usb_lock(); os.close(fd)


@pytest.mark.skipif(os.name != 'posix', reason='Pi USB file lock')
def test_startup_failure_releases_lock_and_records_failure(manager):
    installer, device = manager
    installer.process_factory = lambda *a,**k:(_ for _ in ()).throw(OSError('missing executable'))
    with pytest.raises(OSError):installer.start(device,str(uuid.uuid4()))
    assert installer.current()['job']['status'] == 'failed'
    fd = installer.usb._usb_lock(); os.close(fd)


def test_host_device_and_pending_trade_guards(manager):
    installer, device = manager
    installer.usb.host_check = lambda:False
    with pytest.raises(StorageError,match='Pi 5'):installer.start(device,str(uuid.uuid4()))
    installer.usb.host_check = lambda:True
    with pytest.raises(StorageError,match='connected'):installer.start('/dev/other',str(uuid.uuid4()))
    installer.usb._mutate('Test pending', lambda f,s:s.update(live_session={'status':'uncertain'}))
    with pytest.raises(StorageError,match='resolve'):installer.start(device,str(uuid.uuid4()))


@pytest.mark.skipif(os.name != 'posix', reason='Pi API launches POSIX USB job')
def test_api_confirmation_csrf_demo_and_start(manager, monkeypatch, tmp_path):
    import importlib
    module = importlib.import_module('pokeldn.web.app')
    installer, device = manager
    monkeypatch.setattr(module, 'FirmwareInstaller', lambda usb:installer)
    client = TestClient(module.create_app(data_dir=installer.root))
    body = {'device':device,'request_id':str(uuid.uuid4()),'confirmed':True}
    headers = {'X-PkMn-SBank':'1'}
    assert client.post('/api/esp32/flash',json=body).status_code == 403
    assert client.post('/api/esp32/flash',json=body,headers={**headers,'Origin':'http://evil.invalid'}).status_code == 403
    assert client.post('/api/esp32/flash',json={**body,'confirmed':False},headers=headers).status_code == 422
    assert client.post('/api/esp32/flash',json={**body,'confirmed':'yes'},headers=headers).status_code == 422
    assert client.post('/api/esp32/flash',json=body,headers=headers).status_code == 202
    installer.worker.join(5)
    assert client.get('/api/esp32/status').json()['job']['status'] == 'completed'
    demo = TestClient(module.create_app(data_dir=tmp_path/'demo',mode='demo'))
    assert demo.post('/api/esp32/flash',json=body,headers=headers).status_code == 403
    assert demo.get('/api/esp32/status').json()['devices'] == []


@pytest.mark.skipif(os.name != 'posix', reason='Pi USB file lock')
def test_a_failed_log_write_does_not_interrupt_flashing(manager, monkeypatch):
    installer, device = manager
    original = installer._save
    faults = []
    def save(job):
        if job['logs'] and not faults:
            faults.append(True)
            raise OSError('synthetic full disk during log write')
        original(job)
    monkeypatch.setattr(installer, '_save', save)
    installer.start(device, str(uuid.uuid4())); installer.worker.join(5)
    assert faults
    assert installer.current()['job']['status'] == 'completed'
