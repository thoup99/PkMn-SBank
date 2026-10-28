"""The simulation has a durable session ledger and never applies real Bank trade completion."""
import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from pokeldn import pokemon
from pokeldn.app import bank
from pokeldn.web.app import create_app
from pokeldn.web.storage import BankStore, StorageError
from pokeldn.web.trading import SimulatedTrading
from test_web_storage import imported, TRAINER, HEADERS  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='Pi website sessions target Linux.')


@pytest.fixture
def setup(tmp_path, imported, monkeypatch):
    def move(source, target, data, tracker, trainer):
        if target == 'bdsp' and data == b'two':
            raise pokemon.BuilderError('This species is not in that game.')
        return {'data':base64.b64encode(b'prepared-'+data).decode(),'legal':True,'home_tracker':'empty'}
    monkeypatch.setattr(pokemon.SERVICE,'move',move)
    monkeypatch.setattr(pokemon.SERVICE,'check_bytes',lambda game,data:{'legal':True,'format':'PK8'})
    store=BankStore(tmp_path);store.set_trainer(TRAINER)
    store.import_file('one.pk8',b'one');store.import_file('two.pk8',b'two')
    ids=[p['id'] for b in store.boxes() if b.get('kind') != 'dummy' for p in b['slots'] if p]
    return store,SimulatedTrading(store),ids


def stage(manager,ids,game='swsh'):
    preview=manager.preview(game,ids)
    return manager.stage(game,ids,preview['token'])


def act(manager,session,action,**kwargs):
    return manager.action(session['id'],action,session['version'],**kwargs)


def advance_until_stopped(manager,session):
    for _ in range(25):
        if session['status'] not in ('connecting','waiting','exchanging'):
            return session
        session=act(manager,session,'advance')
    raise AssertionError('Simulation did not terminate')


def assert_originals(store,before):
    assert {p['id']:store.export(p['id'])[1] for b in store.boxes() if b.get('kind') != 'dummy' for p in b['slots'] if p}==before


def test_preview_refusals_and_queue_limits_without_mutating_bank(setup):
    store,manager,ids=setup
    revisions=len(store.backups())
    preview=manager.preview('bdsp',ids)
    assert not preview['compatible']
    assert preview['queue'][0]['compatible'] and 'not in that game' in preview['queue'][1]['reason']
    assert preview['queue'][0]['warnings']
    with pytest.raises(StorageError): manager.stage('bdsp',ids,preview['token'])
    for game,chosen in [('rse',ids),('swsh',ids*4),('swsh',[ids[0],ids[0]]),('swsh',[])]:
        with pytest.raises(StorageError): manager.preview(game,chosen)
    assert len(store.backups())==revisions and manager.current()['session'] is None


def test_success_has_only_simulated_confirmations_and_preserves_every_original(setup):
    store,manager,ids=setup
    before={id:store.export(id)[1] for id in ids}
    session=stage(manager,ids)
    assert session['status']=='ready' and all('data' not in p for p in session['queue'])
    session=advance_until_stopped(manager,act(manager,session,'start'))
    assert session['status']=='completed' and session['completed']==2 and session['mode']=='simulation'
    assert 'No real trade occurred' in session['events'][-1]['message']
    assert_originals(store,before)
    with pytest.raises(StorageError): act(manager,session,'advance')
    assert SimulatedTrading(store).current()['session']['status']=='completed'


@pytest.mark.parametrize('scenario,status',[('disconnect','disconnected'),('failure','failed')])
def test_partial_fault_resume_and_cancel_never_remove_records(setup,scenario,status):
    store,manager,ids=setup
    before={id:store.export(id)[1] for id in ids}
    session=stage(manager,ids)
    session=advance_until_stopped(manager,act(manager,session,'start',scenario=scenario,fault_after=1))
    assert session['status']==status and session['completed']==1
    assert_originals(store,before)
    session=advance_until_stopped(manager,act(manager,session,'resume'))
    assert session['status']=='completed' and session['completed']==2
    assert_originals(store,before)
    session=stage(manager,ids)
    session=act(manager,session,'start',scenario=scenario)
    session=advance_until_stopped(manager,session)
    assert session['completed']==0
    session=act(manager,session,'cancel')
    assert session['status']=='cancelled'
    assert_originals(store,before)


def test_restart_requires_explicit_resume_and_never_auto_confirms(setup):
    store,manager,ids=setup
    session=act(manager,stage(manager,ids),'start')
    assert manager.current()['session']['status']=='connecting' # browser refresh, same server
    restarted=SimulatedTrading(BankStore(store.root))
    interrupted=restarted.current()['session']
    assert interrupted['status']=='interrupted' and interrupted['completed']==0
    assert interrupted['version']==session['version']+1
    with pytest.raises(StorageError,match='changed'): act(restarted,session,'advance')
    resumed=act(restarted,interrupted,'resume')
    assert resumed['status']=='connecting'
    assert advance_until_stopped(restarted,resumed)['completed']==2
    assert len([p for b in store.boxes() if b.get('kind') != 'dummy' for p in b['slots'] if p])==2


def test_stale_preview_and_ready_queue_revalidate_trainer_before_start(setup):
    store,manager,ids=setup
    preview=manager.preview('swsh',ids)
    store.set_trainer({**TRAINER,'ot':'NEW'})
    with pytest.raises(StorageError,match='changed'):manager.stage('swsh',ids,preview['token'])
    session=stage(manager,ids)
    store.set_trainer(TRAINER)
    with pytest.raises(StorageError,match='changed'):act(manager,session,'start')
    assert manager.current()['session']['status']=='ready'


def test_duplicate_confirmation_requests_cannot_advance_twice(setup):
    store,manager,ids=setup
    session=act(manager,stage(manager,ids),'start')
    session=act(manager,session,'advance');session=act(manager,session,'advance')
    assert session['status']=='exchanging'
    def request():
        try:return act(manager,session,'advance')['completed']
        except StorageError:return 'stale'
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:request(),range(2)))
    assert sorted(map(str,results))==['1','stale']
    assert manager.current()['session']['completed']==1


def test_active_bank_changes_blocked_and_recovery_invalidates_session(setup):
    store,manager,ids=setup
    backup=store.backups()[0]['id']
    session=act(manager,stage(manager,ids),'start')
    with pytest.raises(StorageError,match='active simulation'):store.set_trainer(TRAINER)
    with pytest.raises(StorageError,match='active simulation'):store.rename(1,'New')
    with pytest.raises(StorageError,match='active simulation'):stage(manager,ids)
    store.restore(backup)
    session=manager.current()['session']
    assert session['status']=='interrupted' and session['invalidated']
    with pytest.raises(StorageError,match='fresh queue'):act(manager,session,'resume')
    assert len([p for b in store.boxes() if b.get('kind') != 'dummy' for p in b['slots'] if p])==2


def test_http_contract_csrf_versioning_and_demo_isolation(setup):
    store,_,ids=setup
    client=TestClient(create_app(data_dir=store.root))
    selection={'game':'swsh','entry_ids':ids}
    assert client.get('/api/trade/session').json()['session'] is None
    assert client.post('/api/trade/preview',json=selection).status_code==403
    preview=client.post('/api/trade/preview',json=selection,headers=HEADERS).json()
    session=client.post('/api/trade/stage',json={**selection,'token':preview['token']},headers=HEADERS).json()
    endpoint=f"/api/trade/session/{session['id']}/start"
    assert client.post(endpoint,json={'version':True},headers=HEADERS).status_code==422
    started=client.post(endpoint,json={'version':1},headers=HEADERS)
    assert started.status_code==200 and started.json()['status']=='connecting'
    assert client.post(endpoint,json={'version':1},headers=HEADERS).status_code==409
    demo=TestClient(create_app(data_dir=store.root,mode='demo'))
    assert demo.get('/api/trade/session').json()['session'] is None
    assert demo.post('/api/trade/preview',json=selection,headers=HEADERS).status_code==403
    assert client.post('/api/trade/stage',json={**selection,'token':'a'*64},headers=HEADERS).status_code==409


def test_real_pkhex_conversion_refusal_and_simulation_leave_original_bytes(tmp_path,monkeypatch):
    try:pokemon._command()
    except pokemon.BuilderError:pytest.skip('Build services/pkhex for real preparation integration')
    store=BankStore(tmp_path);store.set_trainer(TRAINER)
    # A Bank import can choose any supported game. Explicit deposits create known
    # SwSh records here, then the website exercises the real conversion boundary.
    def deposit(folder,state):
        for species in (25,831):
            reply=pokemon.SERVICE.make('swsh',species,TRAINER)
            bank._keep('swsh',base64.b64decode(reply['data']),reply,folder,'test fixture')
        state['boxes'][0]['slots'][:2]=[e.id for e in bank.entries(folder)]
    store._commit('Seed validated test records',deposit)
    entries=[p for b in store.boxes() if b.get('kind') != 'dummy' for p in b['slots'] if p]
    ids=[p['id'] for p in entries]
    before={id:store.export(id)[1] for id in ids}
    store.set_trainer({**TRAINER,'ot':'MISTY'})
    checked_records=[]
    original_check=pokemon.SERVICE.check_bytes
    def observe(game,data):
        result=original_check(game,data)
        checked_records.append(result)
        return result
    monkeypatch.setattr(pokemon.SERVICE,'check_bytes',observe)
    manager=SimulatedTrading(store)
    refused=manager.preview('bdsp',ids)
    assert any(not p['compatible'] and p['reason'] for p in refused['queue'])
    pika=next(p['id'] for p in entries if p['dex']==25)
    checked=manager.preview('sv',[pika])
    assert checked['compatible'] and checked['queue'][0]['format']=='PK9'
    assert checked_records[-1]['ot']==TRAINER['ot'] # receiving trainer does not overwrite OT
    session=advance_until_stopped(manager,act(manager,manager.stage('sv',[pika],checked['token']),'start'))
    assert session['status']=='completed'
    assert_originals(store,before)


def test_recovery_can_discard_damaged_session_metadata_without_losing_bank(setup):
    import json
    store,manager,ids=setup
    backup=store.backups()[0]['id']
    session=stage(manager,ids)
    current=store.root/'revisions'/(store.root/'CURRENT').read_text().strip()/'state.json'
    state=json.loads(current.read_text());state['trade_session']={'mode':'simulation','version':'broken'}
    current.write_text(json.dumps(state))
    with pytest.raises(StorageError,match='metadata'):manager.current()
    store.restore(backup)
    assert manager.current()['session'] is None
    assert len([p for b in store.boxes() if b.get('kind') != 'dummy' for p in b['slots'] if p])==2


def test_failed_confirmation_write_retains_prior_counter_and_all_records(setup,monkeypatch):
    store,manager,ids=setup
    session=act(manager,stage(manager,ids),'start')
    session=act(manager,session,'advance');session=act(manager,session,'advance')
    before={id:store.export(id)[1] for id in ids}
    real=os.replace
    def fail(source,target):
        if Path(target).name=='CURRENT':raise OSError('disk full')
        return real(source,target)
    monkeypatch.setattr(os,'replace',fail)
    with pytest.raises(OSError):act(manager,session,'advance')
    unchanged=manager.current()['session']
    assert unchanged['completed']==0 and unchanged['version']==session['version']
    assert_originals(store,before)
    monkeypatch.setattr(os,'replace',real)
    assert act(manager,unchanged,'advance')['completed']==1
