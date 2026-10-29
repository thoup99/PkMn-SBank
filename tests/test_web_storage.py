"""Persistence/recovery contracts using the real upstream Bank and a deterministic PKHeX reply.
The real PKHeX integration test below also runs when the helper is built.
"""
import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient
import pytest
from pokeldn import pokemon
from pokeldn.web.app import create_app
from pokeldn.web.storage import BankStore, StorageError
from pokeldn.web.serve import supported_host

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='Website storage targets Linux on Raspberry Pi 5.')

TRAINER = {'ot': 'ASH', 'tid': 1111, 'sid': 2222, 'language': 2, 'gender': 0}
HEADERS = {'X-PkMn-SBank': '1'}


@pytest.fixture
def imported(monkeypatch):
    # Only the validator boundary is replaced. Actual bank.import_file, hashing,
    # deduplication, sidecars, ledger, snapshots and API routes are exercised.
    def parse(data, name, trainers):
        assert all(t == TRAINER for t in trainers.values())
        return {'save': '', 'pokemon': [dict(key='fixture-' + data.hex(), where='', species='Pikachu',
            species_id=25, shiny=False, level=28, nature='Jolly', ability='Static', ot='ASH', legal=True,
            game='swsh', data=base64.b64encode(data).decode(), source='PK8', notes=[], home_tracker='')]}
    monkeypatch.setattr(pokemon.SERVICE, 'import_records', parse)


def request_import(client, data=b'validated record', name='pikachu.pk8'):
    return client.post('/api/import', params={'name': name}, content=data,
                       headers={**HEADERS, 'Content-Type': 'application/octet-stream'})


def test_api_import_duplicate_export_move_restart_and_restore(tmp_path, imported):
    client = TestClient(create_app(data_dir=tmp_path))
    assert not any(p for b in client.get('/api/boxes').json()[:4] for p in b['slots'])
    assert request_import(client).status_code == 422  # a receiving trainer is mandatory
    assert client.put('/api/settings/trainer', json=TRAINER, headers=HEADERS).status_code == 200
    trainer_revision = client.get('/api/backups').json()[0]['id']
    result = request_import(client)
    assert result.status_code == 200 and result.json()['pokemon'][0]['state'] == 'banked'
    entry = client.get('/api/boxes').json()[:4][0]['slots'][0]
    assert entry['trainer'] == 'ASH' and entry['level'] == 28 and entry['nature'] == 'Jolly'
    assert request_import(client).json()['pokemon'][0]['state'] == 'already'
    assert sum(p is not None for b in client.get('/api/boxes').json()[:4] for p in b['slots']) == 1
    assert client.get(f"/api/pokemon/{entry['id']}/export").content == b'validated record'
    demo = TestClient(create_app(data_dir=tmp_path, mode="demo"))
    assert demo.get(f"/api/pokemon/{entry['id']}/export").status_code == 404
    assert client.post(f"/api/pokemon/{entry['id']}/move", json={'box_id': 2, 'slot': 29}, headers=HEADERS).status_code == 200
    assert client.patch('/api/boxes/2', json={'name':'Travel party'}, headers=HEADERS).status_code == 200
    restarted = TestClient(create_app(data_dir=tmp_path))
    assert restarted.get('/api/boxes/2').json()['slots'][29]['id'] == entry['id']
    assert restarted.get('/api/boxes/2').json()['name'] == 'Travel party'
    zip_bytes = restarted.get('/api/backup').content
    import io
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        assert 'state.json' in z.namelist() and 'Bank/.imported' in z.namelist()
        assert any(n.endswith('.pk8') for n in z.namelist())
    assert restarted.post(f'/api/backups/{trainer_revision}/restore', headers=HEADERS).status_code == 200
    assert not any(p for b in restarted.get('/api/boxes').json()[:4] for p in b['slots'])
    assert len(restarted.get('/api/backups').json()) == 6
    assert restarted.get('/api/history').json()['entries'][0]['action'].startswith('Restored backup')


def test_validation_failures_never_commit(tmp_path, imported, monkeypatch):
    store = BankStore(tmp_path)
    store.set_trainer(TRAINER)
    pointer = (tmp_path/'CURRENT').read_bytes()
    def broken(data, name, trainers):
        raise pokemon.BuilderError('Invalid Pokémon')
    monkeypatch.setattr(pokemon.SERVICE, 'import_records', broken)
    with pytest.raises(pokemon.BuilderError):
        store.import_file('bad.pk8', b'bad')
    assert (tmp_path/'CURRENT').read_bytes() == pointer
    assert not list(tmp_path.glob('.pending-*'))
    assert len(store.backups()) == 1


def test_disk_failure_before_pointer_switch_keeps_previous_snapshot(tmp_path, imported, monkeypatch):
    store = BankStore(tmp_path); store.set_trainer(TRAINER)
    before = (tmp_path/'CURRENT').read_bytes()
    real = os.replace
    def fail(source, target):
        if Path(target).name == 'CURRENT':
            raise OSError('disk full')
        return real(source, target)
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        store.import_file('a.pk8', b'first')
    assert (tmp_path/'CURRENT').read_bytes() == before
    assert not any(p for b in BankStore(tmp_path).boxes() if b.get('kind') != 'dummy' for p in b['slots'])
    assert all(b['current'] == (b['id'] == before.decode().strip()) for b in store.backups())


def test_tamper_detection_and_verified_snapshot_restore(tmp_path, imported):
    store=BankStore(tmp_path);store.set_trainer(TRAINER)
    clean=store.backups()[0]['id'];store.import_file('a.pk8', b'first')
    current=tmp_path/'revisions'/(tmp_path/'CURRENT').read_text().strip()
    next((current/'Bank').glob('*.pk8')).write_bytes(b'corrupted')
    with pytest.raises(StorageError, match='integrity'):
        store.boxes()
    store.restore(clean)
    assert not any(p for b in store.boxes() if b.get('kind') != 'dummy' for p in b['slots'])


def test_concurrent_duplicate_imports_and_optimistic_slot_conflict(tmp_path, imported):
    first, second=BankStore(tmp_path),BankStore(tmp_path)
    first.set_trainer(TRAINER)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda store:store.import_file('a.pk8', b'same'),[first,second]))
    assert sorted(r['pokemon'][0]['state'] for r in results)==['already','banked']
    first.import_file('b.pk8', b'other')
    slots=first.boxes()[0]['slots'];one,two=slots[:2]
    with pytest.raises(StorageError, match='Destination changed'):
        first.move(one['id'],1,1,None)
    first.move(one['id'],1,1,two['id'])
    assert [p['id'] for p in first.boxes()[0]['slots'][:2]]==[two['id'],one['id']]


def test_mutation_boundaries_and_pi_only_launcher(tmp_path, imported, monkeypatch):
    client=TestClient(create_app(data_dir=tmp_path))
    assert client.put('/api/settings/trainer',json=TRAINER).status_code==403
    assert client.put('/api/settings/trainer',json=TRAINER,headers={**HEADERS,'Origin':'http://other-host'}).status_code==403
    assert request_import(client,name='../stolen.pk8').status_code==422
    assert request_import(client,data=b'').status_code==422
    assert client.get('/api/pokemon/not-found/export').status_code==404
    assert client.post('/api/pokemon/nope/move',headers=HEADERS,json={'box_id':1,'slot':30}).status_code==422
    assert client.put('/api/settings/trainer',json={**TRAINER,'language':6},headers=HEADERS).status_code==422
    assert client.get('/api/health').headers['cache-control']=='no-store'
    assert supported_host('Raspberry Pi 5 Model B Rev 1.0','aarch64','linux')
    assert not supported_host('Raspberry Pi 4 Model B','aarch64','linux')
    assert not supported_host('Raspberry Pi 5 Model B','x86_64','linux')
    assert not supported_host('Raspberry Pi 5 Model B','arm64','darwin')


def test_real_pkhex_save_import_and_export(tmp_path):
    try:
        pokemon._command()
    except pokemon.BuilderError:
        pytest.skip('Build services/pkhex to run real import integration')
    fixture=json.loads((Path(__file__).parent/'data/bank_import.json').read_text())
    import gzip
    source=gzip.decompress(base64.b64decode(fixture['black2_save_gz']))
    original=bytes(source)
    store=BankStore(tmp_path);store.set_trainer(TRAINER)
    result=store.import_file('black2.sav',source)
    assert source==original
    states=[p['state'] for p in result['pokemon']]
    assert states.count('banked')==2 and states.count('refused')==1
    entries=[p for b in store.boxes() if b.get('kind') != 'dummy' for p in b['slots'] if p]
    assert len(entries)==2 and {p['species'] for p in entries}=={'Patrat','Lillipup'}
    for p in entries:
        name,data=store.export(p['id'])
        assert Path(name).suffix[1:] in pokemon.EXTENSIONS.values()
        assert len(data) in (80,100,328,344)
    assert all(p['state'] in ('already','refused') for p in store.import_file('black2.sav',source)['pokemon'])


def test_downloaded_backup_recovers_new_store_and_rejects_zip_traversal(tmp_path, imported):
    store=BankStore(tmp_path/'source');store.set_trainer(TRAINER);store.import_file('a.pk8',b'safe')
    archive=store.backup_file()
    target=BankStore(tmp_path/'target');target.restore_archive(archive)
    assert target.boxes()[0]['slots'][0]['species']=='Pikachu'
    assert target.export(target.boxes()[0]['slots'][0]['id'])[1]==b'safe'
    bad=tmp_path/'bad.zip'
    with zipfile.ZipFile(bad,'w') as out:
        out.writestr('state.json','{}');out.writestr('../outside','malicious')
    pointer=(target.root/'CURRENT').read_bytes()
    with pytest.raises(StorageError):
        target.restore_archive(bad)
    assert (target.root/'CURRENT').read_bytes()==pointer
    assert not (tmp_path/'outside').exists()
    archive.unlink()


def test_offline_zip_recovery_survives_broken_current_metadata(tmp_path, imported):
    store=BankStore(tmp_path);store.set_trainer(TRAINER);store.import_file('a.pk8',b'safe')
    archive=store.backup_file()
    revision=tmp_path/'revisions'/(tmp_path/'CURRENT').read_text().strip()
    (revision/'state.json').write_text('broken JSON')
    with pytest.raises(StorageError):
        store.boxes()
    store.restore_archive(archive)
    assert store.boxes()[0]['slots'][0]['species']=='Pikachu'
    assert any(b.get('valid') is False for b in store.backups())
    archive.unlink()


def test_32_boxes_ordered_deposits_and_gap_reuse(tmp_path, imported):
    store=BankStore(tmp_path);store.set_trainer(TRAINER)
    assert [b['id'] for b in store.boxes()]==list(range(1,33))
    assert all(len(b['slots'])==30 for b in store.boxes())
    # Import crosses the old four-box limit into box 5.
    parse=pokemon.SERVICE.import_records
    from unittest.mock import patch
    records=[parse(str(i).encode(),f'{i}.pk8',{'swsh':TRAINER})['pokemon'][0] for i in range(121)]
    with patch.object(pokemon.SERVICE,'import_records',return_value={'save':'','pokemon':records}):
        store.import_file('batch.sav',b'batch')
    assert store.boxes()[4]['slots'][0] is not None
    first=store.boxes()[0]['slots'][0]['id']
    store.move(first,32,29,None)
    info={'species':'Eevee','species_id':133,'level':10,'legal':True}
    received=store.receive_record('swsh',b'incoming',info,'gap',sent_id='generated-pikachu')
    assert store.boxes()[0]['slots'][0]['id']==received
    next_id=store.receive_record('swsh',b'next',info,'next',sent_id='generated-pikachu')
    assert store.boxes()[4]['slots'][1]['id']==next_id
    store.move(received,32,28,None)
    store.import_file('fill.pk8',b'fill')
    assert store.boxes()[0]['slots'][0]['id'] not in (None,received)


def test_legacy_four_box_snapshot_expands_on_read_write_and_restore(tmp_path, imported):
    store=BankStore(tmp_path);store.set_trainer(TRAINER);store.import_file('a.pk8',b'safe')
    store.rename(2,'Keep my name')
    revision=store._current();path=revision/'state.json'
    state=json.loads(path.read_text());state['boxes']=state['boxes'][:4]
    original=json.dumps(state).encode();path.write_bytes(original)
    boxes=store.boxes()
    assert len(boxes)==32 and boxes[1]['name']=='Keep my name'
    assert path.read_bytes()==original  # reading never mutates a snapshot
    entry=boxes[0]['slots'][0]['id']
    archive=store.backup_file()
    target=BankStore(tmp_path/'recovered');target.restore_archive(archive)
    assert len(target.boxes())==32 and target.export(entry)[1]==b'safe'
    store.move(entry,32,29,None)
    assert len(json.loads((store._current()/'state.json').read_text())['boxes'])==32
    store.restore(revision.name)
    assert len(store.boxes())==32 and store.boxes()[0]['slots'][0]['id']==entry
    assert store.boxes()[1]['name']=='Keep my name'
    archive.unlink()
