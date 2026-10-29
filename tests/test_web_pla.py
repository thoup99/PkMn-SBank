import base64
import hashlib
import json
import os
from pathlib import Path
import uuid

import pytest
from pokeldn import pokemon
from pokeldn.pla import pokemon as pla_pokemon
from pokeldn.app.trade_receipt import write_receipt
from pokeldn.web.live import LiveTrading
from pokeldn.web.storage import StorageError
from test_web_usb import usb, FakeProcess, wait_for
from test_web_storage import TRAINER

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='Pi USB lifecycle uses POSIX locks')


def test_pla_generated_receipt_and_correct_launcher_are_idempotent(usb):
    store, device, devices, _ = usb
    incoming = base64.b64decode(pokemon.SERVICE.make('pla',133,TRAINER)['data'])
    calls = []
    def factory(argv, **kwargs):
        proc = FakeProcess(argv, **kwargs); calls.append(proc)
        assert 'bin/pla_host.py' in argv and '--trade-box' in argv and '--trainer-name' not in argv and '--trainer-tid' not in argv
        import pla_host
        parsed=pla_host.build_parser().parse_args(argv[argv.index('bin/pla_host.py')+1:])
        assert parsed.sustain and parsed.clock and parsed.game_channel and parsed.data_exchange and parsed.session_update
        raw = Path(argv[argv.index('--trade-box-record')+1]).read_bytes()
        write_receipt(argv[argv.index('--one-trade-receipt')+1], incoming,
                      pla_pokemon.encrypt(pla_pokemon.load(raw)), game='pla')
        return proc
    manager = LiveTrading(store, host_check=lambda:True, devices=devices, process_factory=factory)
    request = str(uuid.uuid4())
    manager.start('generated-pikachu',str(device),'12345678',request,game='pla')
    result = wait_for(manager, {'completed'}); manager.worker.join(5)
    assert result['game'] == 'pla'
    assert store.export(result['received_id'])[1] == incoming
    assert store.boxes()[0]['slots'][0]['game'] == 'Legends Arceus'
    assert len(store.boxes()) == 32
    assert manager.start('generated-pikachu',str(device),'12345678',request,game='pla')['id'] == result['id']
    assert len(calls) == 1




def test_bounded_receipt_requires_phases_and_is_once_only(tmp_path):
    from pokeldn.pla.receipt import BoundedTrade
    candidate=tmp_path/'candidate.pa8';receipt=tmp_path/'confirmed.json'
    trade=BoundedTrade(candidate,receipt,b'outgoing')
    assert trade.admit() and not trade.admit()
    assert not trade.closed() and not receipt.exists()
    trade.offered(b'withdrawn');trade.offered(b'incoming')
    assert candidate.read_bytes()==b'incoming'
    trade.phase_sent(3)
    assert not trade.closed() and not receipt.exists()
    trade.phase_sent(6)
    assert trade.closed() and not trade.closed()
    result=json.loads(receipt.read_text())
    assert result['game']=='pla'
    assert base64.b64decode(result['received'])==b'incoming'
    assert result['offered_sha256']==hashlib.sha256(b'outgoing').hexdigest()
    trade.offered(b'second')
    assert candidate.read_bytes()==b'incoming'


def test_candidate_failure_never_updates_incoming(tmp_path,monkeypatch):
    import pokeldn.pla.receipt as module
    trade=module.BoundedTrade(tmp_path/'candidate',tmp_path/'receipt',b'offer')
    monkeypatch.setattr(module,'write_candidate',lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):trade.offered(b'incoming')
    assert trade.incoming is None and not trade.closed()


def test_bounded_cli_rejects_missing_offer():
    import pla_host
    with pytest.raises(SystemExit):pla_host.main(['--one-trade-receipt','receipt.json'])


def test_pla_receipt_recovery_preserves_outgoing_until_commit(usb,monkeypatch):
    store,device,devices,_=usb
    raw=base64.b64decode(pokemon.SERVICE.make('pla',25,TRAINER)['data'])
    outgoing=store.receive_record('pla',raw,pokemon.SERVICE.check_bytes('pla',raw),'seed')
    incoming=base64.b64decode(pokemon.SERVICE.make('pla',133,TRAINER)['data'])
    def factory(argv,**kwargs):
        offered=Path(argv[argv.index('--trade-box-record')+1]).read_bytes()
        write_receipt(argv[argv.index('--one-trade-receipt')+1],pla_pokemon.encrypt(pla_pokemon.load(incoming)),pla_pokemon.encrypt(pla_pokemon.load(offered)),game='pla')
        return FakeProcess(argv,**kwargs)
    real=store.receive_record
    monkeypatch.setattr(store,'receive_record',lambda *a,**k: (_ for _ in ()).throw(OSError('disk full')))
    manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=factory)
    manager.start(outgoing,str(device),'12345678',str(uuid.uuid4()),game='pla')
    result=wait_for(manager,{'recovery_required'});manager.worker.join(5)
    assert store.export(outgoing)[1]==raw
    monkeypatch.setattr(store,'receive_record',real)
    recovered=manager.recover(result['id'])
    assert recovered['status']=='completed'
    with pytest.raises(StorageError):store.export(outgoing)
    assert pokemon.SERVICE.check_bytes('pla',store.export(recovered['received_id'])[1])['legal']
    assert manager.recover(result['id'])['received_id']==recovered['received_id']


def test_pla_compatibility_disables_unrepresentable_species(usb):
    store,_,devices,_=usb
    raw=base64.b64decode(pokemon.SERVICE.make('swsh',810,TRAINER)['data'])
    entry=store.receive_record('swsh',raw,pokemon.SERVICE.check_bytes('swsh',raw),'grookey')
    manager=LiveTrading(store,host_check=lambda:True,devices=devices)
    results={p['id']:p for p in manager.compatibility('pla')['entries']}
    assert not results[entry]['compatible'] and results[entry]['reason']
    assert results['generated-pikachu']['compatible']



def test_bounded_exchange_rejects_changed_offer_after_phase_started(tmp_path):
    from pokeldn.pla.receipt import BoundedTrade
    trade=BoundedTrade(tmp_path/'candidate',tmp_path/'receipt',b'offer')
    trade.offered(b'original');trade.phase_sent(3)
    with pytest.raises(ValueError):trade.offered(b'changed')
    assert trade.incoming==b'original'
    assert (tmp_path/'candidate').read_bytes()==b'original'
