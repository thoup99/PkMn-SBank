import base64
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from fastapi.testclient import TestClient
import lgpe_host
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


def test_lgpe_generated_receipt_and_correct_launcher_are_idempotent(usb):
    store, device, devices, _ = usb
    incoming = lgpe_host.boxed(base64.b64decode(pokemon.SERVICE.make('lgpe',133,TRAINER)['data'])[:232])
    calls = []
    def factory(argv, **kwargs):
        proc = FakeProcess(argv, **kwargs); calls.append(proc)
        assert 'bin/lgpe_host.py' in argv and '--trainer-tid' not in argv
        raw = Path(argv[argv.index('--offer')+1]).read_bytes()
        write_receipt(argv[argv.index('--one-trade-receipt')+1], incoming,
                      lgpe_host.boxed(raw[:232]), game='lgpe')
        return proc
    manager = LiveTrading(store, host_check=lambda:True, devices=devices, process_factory=factory)
    request = str(uuid.uuid4())
    manager.start('generated-pikachu',str(device),'pikachu,pikachu,pikachu',request,game='lgpe')
    result = wait_for(manager, {'completed'}); manager.worker.join(5)
    assert result['game'] == 'lgpe'
    assert store.export(result['received_id'])[1] == incoming
    assert store.boxes()[0]['slots'][0]['game'] == "Let's Go"
    assert len(store.boxes()) == 32
    assert manager.start('generated-pikachu',str(device),'pikachu,pikachu,pikachu',request,game='lgpe')['id'] == result['id']
    assert len(calls) == 1






def test_lgpe_receipt_only_after_result(stage,tmp_path,monkeypatch):
    s=stage['s']
    from pokeldn.lgpe import pb7
    raw=Path(s.args.offer).read_bytes()
    s.bounded_offer=raw;s.args.one_trade_receipt=str(tmp_path/'receipt.json')
    s.args.received=str(tmp_path/'candidate.pb7')
    s.trade['peer_offer']=raw;s.committed_2=True
    monkeypatch.setattr(s,'send_result',lambda:None)
    s.game({'kind':s.result_kind,'step':99,'size':4,'body':bytes(4)})
    receipt=json.loads((tmp_path/'receipt.json').read_text())
    assert receipt['game']=='lgpe' and base64.b64decode(receipt['received'])==raw
    assert s.bounded_done_at is not None
    s.game({'kind':s.offer_kind,'step':100,'size':len(raw),'body':raw})
    assert not (tmp_path/'candidate.pb7').exists()


from test_lgpe_host_commit import stage


def test_lgpe_rejects_numeric_code_before_launch(usb):
    store,device,devices,_=usb
    manager=LiveTrading(store,host_check=lambda:True,devices=devices,process_factory=lambda *a,**k:pytest.fail('must not launch'))
    with pytest.raises(StorageError):manager.start('generated-pikachu',str(device),'12345678',str(uuid.uuid4()),game='lgpe')
