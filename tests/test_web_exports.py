"""ZIP exports preserve exact record bytes and the selected snapshot's box layout."""
import io
import zipfile
from fastapi.testclient import TestClient
from pokeldn.web.app import create_app
from pokeldn.web.storage import BankStore
from test_web_storage import TRAINER, imported


def test_box_and_mass_exports_preserve_bytes_layout_and_bank(tmp_path, imported):
    store=BankStore(tmp_path);store.set_trainer(TRAINER)
    store.import_file('one.pk8',b'first');store.import_file('two.pk8',b'second')
    one,two=store.boxes()[0]['slots'][:2]
    store.move(two['id'],32,29,None)
    store.rename(1,'../../bad\\name:é')
    store.rename(32,'../../bad\\name:é')
    client=TestClient(create_app(data_dir=tmp_path))
    pointer=(tmp_path/'CURRENT').read_bytes();history=store.history()
    response=client.get('/api/boxes/32/export')
    assert response.status_code==200
    assert response.headers['content-type']=='application/zip'
    assert 'pkmn-sbank-box-32.zip' in response.headers['content-disposition']
    assert response.headers['cache-control']=='no-store'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist())==1
        name=archive.namelist()[0]
        assert name.startswith('Slot 30 - ') and name.endswith('.pk8') and '/' not in name
        assert archive.read(name)==b'second'
    response=client.get('/api/boxes/export')
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names=archive.namelist()
        assert len(names)==2
        assert {n.split('/')[0][:6] for n in names}=={'Box 01','Box 32'}
        assert all(len(n.split('/'))==2 and '..' not in n and '\\' not in n for n in names)
        assert {archive.read(n) for n in names}=={b'first',b'second'}
        assert all(n.endswith('.pk8') for n in names)  # no ledger, sidecars or settings
    assert (tmp_path/'CURRENT').read_bytes()==pointer and store.history()==history
    assert store.export(one['id'])[1]==b'first' and store.export(two['id'])[1]==b'second'


def test_empty_missing_demo_and_corrupt_exports_fail_without_archives(tmp_path, imported):
    client=TestClient(create_app(data_dir=tmp_path))
    for route in ('/api/boxes/export','/api/boxes/1/export'):
        assert client.get(route).status_code==422
        assert TestClient(create_app(data_dir=tmp_path,mode='demo')).get(route).status_code==404
    assert client.get('/api/boxes/33/export').status_code==404
    store=BankStore(tmp_path);store.set_trainer(TRAINER);store.import_file('one.pk8',b'safe')
    next((store._current()/'Bank').glob('*.pk8')).write_bytes(b'changed')
    assert client.get('/api/boxes/export').status_code==503
    assert client.get('/api/boxes/1/export').status_code==503
