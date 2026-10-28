import os
import stat
import pytest
from fastapi.testclient import TestClient
from pokeldn.web.app import create_app
from pokeldn.web.keys import LIMIT

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='Pi key upload uses POSIX locks')

# Synthetic values, not usable console keys.
CONTENT = b'\n'.join(name+b' = '+b'01'*16 for name in
    (b'master_key_00', b'aes_kek_generation_source', b'aes_key_generation_source'))
HEADERS = {'X-PkMn-SBank':'1', 'Content-Type':'application/octet-stream'}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    target = tmp_path/'private'/'prod.keys'
    monkeypatch.setenv('PKMN_SBANK_KEYS', str(target))
    return TestClient(create_app(data_dir=tmp_path/'bank')), target


def test_upload_private_atomic_and_no_readback(setup):
    client, target = setup
    assert client.get('/api/settings/keys').json() == {'installed':False}
    response = client.put('/api/settings/keys', content=CONTENT, headers=HEADERS)
    assert response.json() == {'installed':True}
    assert client.get('/api/settings/keys').json() == {'installed':True}
    if os.name == 'posix':
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    original = target.read_bytes()
    for content, code in ((b'bad secret text',422), (b'x'*(LIMIT+1),413), (b'',422)):
        result = client.put('/api/settings/keys', content=content, headers=HEADERS)
        assert result.status_code == code
        assert b'bad secret text' not in result.content
        assert target.read_bytes() == original
    assert not list(target.parent.glob('.prod-keys-*'))


def test_upload_csrf_demo_and_type_guards(setup, tmp_path):
    client, target = setup
    assert client.put('/api/settings/keys', content=CONTENT).status_code == 403
    assert client.put('/api/settings/keys', content=CONTENT, headers={**HEADERS,'Origin':'http://evil.invalid'}).status_code == 403
    assert client.put('/api/settings/keys', content=CONTENT, headers={'X-PkMn-SBank':'1'}).status_code == 415
    demo = TestClient(create_app(data_dir=tmp_path/'demo',mode='demo'))
    assert demo.put('/api/settings/keys', content=CONTENT, headers=HEADERS).status_code == 403
    assert not target.exists()


@pytest.mark.skipif(os.name != 'posix', reason='USB locks use POSIX')
def test_upload_refuses_live_session_and_orphan_lock(setup):
    from pokeldn.web.storage import BankStore
    from pokeldn.web.live import LiveTrading
    client, target = setup
    store = BankStore(target.parent.parent/'bank')
    manager = LiveTrading(store)
    fd = manager._usb_lock()
    try:
        assert client.put('/api/settings/keys',content=CONTENT,headers=HEADERS).status_code == 409
    finally:os.close(fd)
    manager._mutate('test running',lambda f,s:s.update(live_session={'status':'running'}))
    assert client.put('/api/settings/keys',content=CONTENT,headers=HEADERS).status_code == 409
    assert not target.exists()


def test_valid_replacement_and_failed_write_keep_private_file(setup, monkeypatch):
    client, target = setup
    assert client.put('/api/settings/keys',content=CONTENT,headers=HEADERS).status_code == 200
    replacement = CONTENT.replace(b'01', b'02')
    assert client.put('/api/settings/keys',content=replacement,headers=HEADERS).status_code == 200
    original = target.read_bytes()
    assert b'02'*16 in original
    def unavailable(*args):raise OSError('synthetic disk error')
    monkeypatch.setattr(os, 'replace', unavailable)
    assert client.put('/api/settings/keys',content=CONTENT,headers=HEADERS).status_code == 503
    assert target.read_bytes() == original
    assert not list(target.parent.glob('.prod-keys-*'))


def test_symlink_target_cannot_overwrite_another_file(setup, tmp_path):
    client, target = setup
    target.parent.mkdir()
    other = tmp_path/'other'
    other.write_bytes(b'original')
    target.symlink_to(other)
    assert client.put('/api/settings/keys',content=CONTENT,headers=HEADERS).status_code == 422
    assert other.read_bytes() == b'original'
