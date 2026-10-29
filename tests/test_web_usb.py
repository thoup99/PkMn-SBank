import base64
import io
import json
import os
from pathlib import Path
import threading
import time
import uuid
import pytest
from pokeldn import pokemon,gen8
from pokeldn.swsh import pokemon as swsh_pokemon
from pokeldn.app.trade_receipt import write_receipt
from pokeldn.web.storage import BankStore,StorageError
from pokeldn.web.live import LiveTrading
from test_web_storage import TRAINER

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Pi USB trade lifecycle uses POSIX locks')


class FakeProcess:
 def __init__(self,argv,**kwargs):
  self.argv=argv;self.kwargs=kwargs;self.stdin=io.StringIO();self.stdout=io.StringIO('radio waiting\n');self.code=None
 def wait(self,timeout=None):self.code=0;return 0
 def poll(self):return self.code
 def kill(self):self.code=-9
 def terminate(self):self.code=-15


def wait_for(manager,statuses):
 end=time.monotonic()+10
 while time.monotonic()<end:
  result=manager.current()['session']
  if result and result['status'] in statuses:return result
  time.sleep(.02)
 raise AssertionError(manager.current())


@pytest.fixture
def usb(tmp_path,monkeypatch):
 try:pokemon._command()
 except pokemon.BuilderError:pytest.skip('Build PKHeX helper')
 store=BankStore(tmp_path/'store');store.set_trainer(TRAINER)
 device=tmp_path/'ttyACM0';device.touch()
 keys=tmp_path/'prod.keys';keys.write_text('synthetic test file; process is mocked')
 monkeypatch.setenv('PKMN_SBANK_KEYS',str(keys))
 devices=lambda:[{'device':str(device),'description':'Test native USB','serial_number':'TEST'}]
 incoming=base64.b64decode(pokemon.SERVICE.make('swsh',133,TRAINER)['data'])
 return store,device,devices,incoming


def test_live_generated_confirmed_receipt_is_committed_once_to_normal_boxes(usb):
 store,device,devices,incoming=usb;calls=[]
 def factory(argv,**kwargs):
  proc=FakeProcess(argv,**kwargs);calls.append(proc)
  raw=Path(argv[argv.index('--offer-file')+1]).read_bytes()
  offered=swsh_pokemon.encrypt(gen8.load(raw))
  write_receipt(argv[argv.index('--one-trade-receipt')+1],incoming,offered)
  return proc
 manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=factory)
 request=str(uuid.uuid4());manager.start('generated-pikachu',str(device),'12345678',request)
 result=wait_for(manager,{'completed'})
 assert store.boxes()[0]['slots'][0]['id']==result['received_id']
 assert store.export(result['received_id'])[1]==incoming
 assert len(store.boxes())==4
 assert calls[0].kwargs['env']['POKELDN_RADIO']=='esp32:'+str(device)
 assert '--one-trade-receipt' in calls[0].argv and calls[0].kwargs['pass_fds']
 assert manager.start('generated-pikachu',str(device),'12345678',request)['id']==result['id']
 assert len(calls)==1
 manager.recover(result['id'])
 assert len([p for b in store.boxes()[:4] for p in b['slots'] if p])==1


def test_unconfirmed_exit_never_deposits_candidate_and_requires_operator_resolution(usb):
 store,device,devices,incoming=usb
 def factory(argv,**kwargs):
  Path(argv[argv.index('--received')+1]).write_bytes(incoming)
  return FakeProcess(argv,**kwargs)
 manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=factory)
 manager.start('generated-pikachu',str(device),'12345678',str(uuid.uuid4()))
 result=wait_for(manager,{'uncertain'})
 assert not any(p for b in store.boxes()[:4] for p in b['slots'])
 with pytest.raises(StorageError):manager.start('dummy-pikachu-02',str(device),'12345678',str(uuid.uuid4()))
 assert manager.recover(result['id'],resolve=True)['status']=='resolved'
 assert (manager._folder(result)/'candidate.pk8').read_bytes()==incoming


def test_recovery_replays_durable_receipt_after_failed_bank_commit(usb,monkeypatch):
 store,device,devices,incoming=usb
 def factory(argv,**kwargs):
  raw=Path(argv[argv.index('--offer-file')+1]).read_bytes()
  write_receipt(argv[argv.index('--one-trade-receipt')+1],incoming,swsh_pokemon.encrypt(gen8.load(raw)))
  return FakeProcess(argv,**kwargs)
 original=store.receive_record
 monkeypatch.setattr(store,'receive_record',lambda *a,**k:(_ for _ in ()).throw(OSError('disk full')))
 manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=factory)
 manager.start('generated-pikachu',str(device),'12345678',str(uuid.uuid4()))
 result=wait_for(manager,{'recovery_required'})
 assert (manager._folder(result)/'confirmed.json').is_file()
 monkeypatch.setattr(store,'receive_record',original)
 # Worker releases the advisory lock on exit before a recovery command can proceed.
 manager.worker.join(5)
 recovered=manager.recover(result['id']);assert recovered['status']=='completed'
 assert store.export(recovered['received_id'])[1]==incoming


def test_host_and_device_guards_prevent_process_launch(usb):
 store,device,devices,_=usb
 manager=LiveTrading(store,host_check=lambda:False,devices=devices,process_factory=lambda *a,**k:pytest.fail('must not launch'))
 with pytest.raises(StorageError,match='Pi 5'):manager.start('generated-pikachu',str(device),'12345678',str(uuid.uuid4()))
 manager.host_check=lambda:True
 with pytest.raises(StorageError,match='attached'):manager.start('generated-pikachu','/dev/other','12345678',str(uuid.uuid4()))
 with pytest.raises(StorageError):manager.start('generated-pikachu',str(device),'bad',str(uuid.uuid4()))


def test_normal_outgoing_is_removed_only_after_receipt_and_restart_can_recover(usb):
 store,device,devices,incoming=usb
 outgoing=base64.b64decode(pokemon.SERVICE.make('swsh',25,TRAINER)['data'])
 store.receive_record('swsh',outgoing,pokemon.SERVICE.check_bytes('swsh',outgoing),'seed')
 entry=store.boxes()[0]['slots'][0]['id']
 manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=FakeProcess)
 manager.start(entry,str(device),'12345678',str(uuid.uuid4()))
 result=wait_for(manager,{'uncertain'});manager.worker.join(5)
 assert store.export(entry)[1]==outgoing
 run=manager._folder(result)
 raw=(run/'offer.pk8').read_bytes();write_receipt(run/'confirmed.json',incoming,swsh_pokemon.encrypt(gen8.load(raw)))
 restarted=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=FakeProcess)
 result=restarted.recover(result['id'])
 assert result['status']=='completed'
 with pytest.raises(StorageError):store.export(entry)
 assert store.boxes()[0]['slots'][0]['id']==result['received_id']


def test_native_limit_keeps_saving_stage_and_receipt_write_is_atomic(tmp_path):
 from pokeldn.swsh.host_trade import HostTrade
 host=HostTrade(1,2,bytes(3456),bytes(344),lambda *a:None,lambda *a:None,lambda *a:None,trade_limit=1)
 host.trades=1;host.stage='saving';host._next_round();assert host.stage=='saving'
 path=tmp_path/'confirmed.json';write_receipt(path,b'incoming',b'outgoing')
 data=json.loads(path.read_text());assert base64.b64decode(data['received'])==b'incoming'
 assert not path.with_suffix('.tmp').exists()


def test_http_usb_controls_require_same_origin_and_explicit_resolution(usb,monkeypatch):
 from fastapi.testclient import TestClient
 import importlib
 module=importlib.import_module('pokeldn.web.app')
 store,device,devices,_=usb
 monkeypatch.setattr(module,'LiveTrading',lambda s:LiveTrading(s,host_check=lambda:True,devices=devices,process_factory=FakeProcess))
 client=TestClient(module.create_app(data_dir=store.root))
 body={'entry_id':'generated-pikachu','device':str(device),'code':'12345678','request_id':str(uuid.uuid4())}
 assert client.post('/api/usb/start',json=body).status_code==403
 assert client.post('/api/usb/start',json=body,headers={'X-PkMn-SBank':'1','Origin':'http://evil.example'}).status_code==403
 response=client.post('/api/usb/start',json=body,headers={'X-PkMn-SBank':'1'})
 assert response.status_code==200
 id=response.json()['id']
 assert client.post(f'/api/usb/{id}/recover',json={'resolve_without_confirmation':'yes'},headers={'X-PkMn-SBank':'1'}).status_code==422


def test_orphan_process_lock_blocks_second_owner_and_receipt_recovery(usb):
 store,_,devices,_=usb
 owner=LiveTrading(store,host_check=lambda:True,devices=devices)
 fd=owner._usb_lock()
 second=LiveTrading(store,host_check=lambda:True,devices=devices)
 try:
  with pytest.raises(StorageError,match='owns the board'):second._usb_lock()
 finally:os.close(fd)
 fd=second._usb_lock();os.close(fd)


def test_stop_closes_managed_input_retains_originals_and_releases_board(usb):
 store,device,devices,_=usb
 stopped=threading.Event()
 class ManagedInput(io.StringIO):
  def close(self):
   super().close();stopped.set()
 class BlockingOutput:
  def __iter__(self):
   stopped.wait(5)
   return iter(())
  def close(self):pass
 class RunningProcess(FakeProcess):
  def __init__(self,*args,**kwargs):
   super().__init__(*args,**kwargs)
   self.stdin=ManagedInput();self.stdout=BlockingOutput()
  def wait(self,timeout=None):
   if not stopped.wait(timeout or 5):raise TimeoutError('test process did not stop')
   self.code=0;return 0
 manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=RunningProcess)
 session=manager.start('generated-pikachu',str(device),'12345678',str(uuid.uuid4()))
 assert session['status']=='running'
 with pytest.raises(StorageError):store.rename(1,'Blocked during USB trade')
 manager.cancel(session['id'])
 result=wait_for(manager,{'uncertain'});manager.worker.join(5)
 assert stopped.is_set() and not manager.worker.is_alive()
 assert not any(p for b in store.boxes()[:4] for p in b['slots'])
 assert len(store.boxes())==4
 assert manager.recover(result['id'],resolve=True)['status']=='resolved'
 fd=manager._usb_lock();os.close(fd)


def test_restarted_server_marks_old_active_session_interrupted_but_respects_lock(usb):
 store,_,devices,_=usb
 owner=LiveTrading(store,host_check=lambda:True,devices=devices)
 session={'id':uuid.uuid4().hex,'owner':owner.owner,'status':'running'}
 owner._mutate('Test active session',lambda f,s:s.update(live_session=session))
 fd=owner._usb_lock()
 try:
  restarted=LiveTrading(store,host_check=lambda:True,devices=devices)
  assert restarted.current()['session']['status']=='interrupted'
  with pytest.raises(StorageError,match='owns the board'):restarted.recover(session['id'])
 finally:os.close(fd)
 assert restarted.recover(session['id'],resolve=True)['status']=='resolved'



def test_destination_catalog_and_unsupported_game_are_explicit(usb):
 from fastapi.testclient import TestClient
 from pokeldn.web.app import create_app
 store,device,devices,_=usb
 manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=lambda *a,**k:pytest.fail('must not launch an unsupported game'))
 games=manager.current()['games']
 assert {g['key'] for g in games}=={'lgpe','swsh','bdsp','pla','sv','za'}
 assert [g['key'] for g in games if g['available']]==['swsh','za']
 with pytest.raises(StorageError,match='Choose Sword / Shield'):
  manager.start('generated-pikachu',str(device),'12345678',str(uuid.uuid4()),game='sv')
 client=TestClient(create_app(data_dir=store.root))
 body={'game':'sv','entry_id':'generated-pikachu','device':str(device),'code':'12345678','request_id':str(uuid.uuid4())}
 assert client.post('/api/usb/start',json=body,headers={'X-PkMn-SBank':'1'}).status_code==422
 assert client.get('/api/usb/status').json()['games']==games
