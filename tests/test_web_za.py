import base64
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from fastapi.testclient import TestClient
from pokeldn import pokemon
from pokeldn.app.trade_receipt import write_receipt
from pokeldn.web.live import LiveTrading
from pokeldn.web.storage import StorageError
from test_web_usb import usb, FakeProcess, wait_for
from test_web_storage import TRAINER

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='Pi USB lifecycle uses POSIX locks')


def seed(store, game, species, receipt):
    raw = base64.b64decode(pokemon.SERVICE.make(game, species, TRAINER)['data'])
    id = store.receive_record(game, raw, pokemon.SERVICE.check_bytes(game, raw), receipt)
    return id, raw


def test_za_generated_receipt_and_correct_launcher_are_idempotent(usb):
    store, device, devices, _ = usb
    incoming = base64.b64decode(pokemon.SERVICE.make('za',133,TRAINER)['data'])
    calls = []
    def factory(argv, **kwargs):
        proc = FakeProcess(argv, **kwargs); calls.append(proc)
        assert 'bin/za_host.py' in argv and '--trainer-tid' not in argv
        raw = Path(argv[argv.index('--trade-offer')+1]).read_bytes()
        write_receipt(argv[argv.index('--one-trade-receipt')+1], incoming,
                      pokemon.offer_bytes('za',raw), game='za')
        return proc
    manager = LiveTrading(store, host_check=lambda:True, devices=devices, process_factory=factory)
    request = str(uuid.uuid4())
    manager.start('generated-pikachu',str(device),'12345678',request,game='za')
    result = wait_for(manager, {'completed'}); manager.worker.join(5)
    assert result['game'] == 'za'
    assert store.export(result['received_id'])[1] == incoming
    assert store.boxes()[0]['slots'][0]['game'] == 'Legends Z-A'
    assert len(store.boxes()) == 32
    assert manager.start('generated-pikachu',str(device),'12345678',request,game='za')['id'] == result['id']
    assert len(calls) == 1


def test_za_exchange_retains_original_until_confirmed_and_can_recover(usb,monkeypatch):
    store, device, devices, _ = usb
    outgoing, raw = seed(store, 'swsh',25,'seed')
    incoming = base64.b64decode(pokemon.SERVICE.make('za',133,TRAINER)['data'])
    manager = LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=FakeProcess)
    manager.start(outgoing,str(device),'12345678',str(uuid.uuid4()),game='za')
    session = wait_for(manager,{'uncertain'}); manager.worker.join(5)
    assert store.export(outgoing)[1] == raw
    run = manager._folder(session)
    assert pokemon.SERVICE.owner('za',(run/'offer.pa9').read_bytes())['ot'] == TRAINER['ot']
    write_receipt(run/'confirmed.json',incoming,pokemon.offer_bytes('za',(run/'offer.pa9').read_bytes()),game='za')
    recovered = manager.recover(session['id'])
    assert recovered['status'] == 'completed'
    with pytest.raises(StorageError):store.export(outgoing)
    assert store.export(recovered['received_id'])[1] == incoming
    assert manager.recover(session['id'])['received_id'] == recovered['received_id']


def test_compatibility_uses_real_conversion_and_invalidates_after_bank_change(usb):
    store, device, devices, _ = usb
    grookey, raw = seed(store,'swsh',810,'grookey')
    manager = LiveTrading(store,host_check=lambda:True,devices=devices,
                          process_factory=lambda *a,**k:pytest.fail('must not launch'))
    available = {r['id']:r for r in manager.compatibility('swsh')['entries']}
    assert available[grookey]['compatible']
    za = {r['id']:r for r in manager.compatibility('za')['entries']}
    assert not za[grookey]['compatible'] and 'not in that game' in za[grookey]['reason']
    assert za['generated-pikachu']['compatible']
    with pytest.raises(pokemon.BuilderError):
        manager.start(grookey,str(device),'12345678',str(uuid.uuid4()),game='za')
    assert store.export(grookey)[1] == raw
    eevee, _ = seed(store,'za',133,'eevee')
    assert eevee in {r['id'] for r in manager.compatibility('za')['entries']}


def test_wrong_game_receipt_is_retained_without_deposit(usb):
    store,device,devices,incoming = usb
    def factory(argv,**kwargs):
        raw = Path(argv[argv.index('--trade-offer')+1]).read_bytes()
        write_receipt(argv[argv.index('--one-trade-receipt')+1],incoming,pokemon.offer_bytes('za',raw),game='swsh')
        return FakeProcess(argv,**kwargs)
    manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=factory)
    manager.start('generated-pikachu',str(device),'12345678',str(uuid.uuid4()),game='za')
    result=wait_for(manager,{'recovery_required'});manager.worker.join(5)
    assert not any(p for b in store.boxes() for p in b['slots'])
    assert (manager._folder(result)/'confirmed.json').exists()


def test_compatibility_api_and_demo(usb,monkeypatch,tmp_path):
    import importlib
    module=importlib.import_module('pokeldn.web.app')
    store,_,devices,_=usb
    monkeypatch.setattr(module,'LiveTrading',lambda s:LiveTrading(s,host_check=lambda:True,devices=devices))
    client=TestClient(module.create_app(data_dir=store.root))
    response=client.get('/api/usb/compatibility?game=za')
    assert response.status_code==200 and len(response.json()['entries'])==1
    assert client.get('/api/usb/compatibility?game=lgpe').status_code==422
    demo=TestClient(module.create_app(data_dir=tmp_path/'demo',mode='demo'))
    assert demo.get('/api/usb/compatibility?game=za').json()=={'game':'za','entries':[]}


def test_native_za_cli_writes_receipt_after_confirmation_and_hands_over(usb,tmp_path,monkeypatch):
    import za_host as cli
    store,_,_,_=usb
    raw=base64.b64decode(pokemon.SERVICE.make('za',25,TRAINER)['data'])
    incoming=base64.b64decode(pokemon.SERVICE.make('za',133,TRAINER)['data'])
    source=tmp_path/'offer.pa9';source.write_bytes(raw)
    candidate=tmp_path/'candidate.pa9';receipt=tmp_path/'confirmed.json'
    pick=pokemon.offer_bytes('za',incoming)
    clock=[100.0];created=[];stopped=[];handovers=[]
    class Session:
        def __init__(self,**kwargs):
            assert kwargs['trade_limit']==1
            created.append(self);self.record=kwargs['record'];self.offer=kwargs['offer'][0]
            self.console_offer=None;self.console_pick=None;self.trades=0;self.console_offers=0;self.steps=0
            self.departed=False;self.trade_complete=False
        def receive(self,payload,ip):
            if payload==b'pick':
                assert not candidate.exists() and not receipt.exists()
                self.console_offer=self.console_pick=pick;self.console_offers+=1
                self.record(rec='console_offer',data=pick.hex())
                assert candidate.read_bytes()==incoming and not receipt.exists()
            elif payload==b'confirmed':
                assert candidate.exists() and not receipt.exists()
                self.trades=1;self.steps=4;self.trade_complete=True
            else:
                assert receipt.exists()
                self.console_offer=pick[:-1]+b'\x01'
        def tick(self):return []
        def leave(self):self.departed=True;handovers.append(True)
    class Transport:
        our_ip='127.0.0.2';our_mac=bytes(6);ssid=bytes(16)
        def __init__(self,**kwargs):self.participants=[(1,'127.0.0.3')];self.frames=iter([b'pick',b'confirmed',b'preview'])
        def start(self):pass
        def wait_readable(self,seconds):
            clock[0]+=1
            # A second console is ignored in bounded mode even before the first completes.
            self.participants=[(1,'127.0.0.3'),(2,'127.0.0.4')]
        def recv(self):
            frame=next(self.frames,None)
            return [(frame,'127.0.0.3')] if frame else []
        def send(self,*args):pass
        def stop(self):stopped.append(True)
    monkeypatch.setattr(cli,'HostTransport',Transport)
    monkeypatch.setattr(cli.za_host,'HostSession',Session)
    monkeypatch.setattr(cli,'needs_root',lambda:False)
    monkeypatch.setattr(cli,'find_ap_phy',lambda **kw:'fake')
    monkeypatch.setattr(cli.time,'time',lambda:clock[0])
    monkeypatch.setattr(cli,'resolve_keys',lambda path:path)
    monkeypatch.setattr(cli.config,'load_project_host_file_config',lambda:SimpleNamespace(skip_encryption=False,accept_decrypted_ccmp=False))
    result=cli.main(['--trade-offer',str(source),'--offer-out',str(candidate),'--keys','synthetic',
                     '--one-trade-receipt',str(receipt),'--code','12345678'])
    assert result==0 and stopped and handovers and len(created)==1
    data=json.loads(receipt.read_text())
    assert data['game']=='za' and base64.b64decode(data['received'])==incoming
    assert data['offered_sha256']==hashlib.sha256(pokemon.offer_bytes('za',raw)).hexdigest()


def test_native_bounded_mode_rejects_mixed_options_before_radio_access():
    import za_host as cli
    with pytest.raises(SystemExit) as error:
        cli.main(['--one-trade-receipt','confirmed.json','--trade-offer','offer.pa9','--offer-out','candidate.pa9','--fresh-pid'])
    assert error.value.code==2



def test_each_generated_run_gets_a_fresh_identity_for_repeated_deposits(usb):
    store,device,devices,_=usb
    manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=FakeProcess)
    offers=[]
    for _ in range(2):
        manager.start('generated-pikachu',str(device),'12345678',str(uuid.uuid4()),game='za')
        session=wait_for(manager,{'uncertain'});manager.worker.join(5)
        offers.append((manager._folder(session)/'offer.pa9').read_bytes())
        manager.recover(session['id'],resolve=True)
    assert offers[0][:4]!=offers[1][:4]
    assert offers[0][0x1c:0x20]!=offers[1][0x1c:0x20]
    assert pokemon.SERVICE.owner('za',offers[0])['ot']==TRAINER['ot']
    assert pokemon.SERVICE.owner('za',offers[1])['ot']==TRAINER['ot']
    assert len(store.boxes())==32


def test_legacy_pikachu_box_receipt_remains_recoverable_after_box_removal(usb):
    store,device,devices,_=usb
    manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=FakeProcess)
    manager.start('generated-pikachu',str(device),'12345678',str(uuid.uuid4()),game='za')
    session=wait_for(manager,{'uncertain'});manager.worker.join(5)
    session=manager._status(session['id'],'uncertain','Legacy pending offer',entry_id='dummy-pikachu-01')
    run=manager._folder(session)
    incoming=base64.b64decode(pokemon.SERVICE.make('za',133,TRAINER)['data'])
    write_receipt(run/'confirmed.json',incoming,pokemon.offer_bytes('za',(run/'offer.pa9').read_bytes()),game='za')
    restarted=LiveTrading(store,host_check=lambda:True,devices=devices)
    result=restarted.recover(session['id'])
    assert result['status']=='completed' and len(store.boxes())==32
    assert store.export(result['received_id'])[1]==incoming
