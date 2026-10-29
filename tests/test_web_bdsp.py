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


def test_bdsp_generated_receipt_and_correct_launcher_are_idempotent(usb):
    store, device, devices, _ = usb
    incoming = base64.b64decode(pokemon.SERVICE.make('bdsp',133,TRAINER)['data'])
    calls = []
    def factory(argv, **kwargs):
        proc = FakeProcess(argv, **kwargs); calls.append(proc)
        assert 'bin/bdsp_host.py' in argv and '--trainer-tid' not in argv
        raw = Path(argv[argv.index('--offer')+1]).read_bytes()
        write_receipt(argv[argv.index('--one-trade-receipt')+1], incoming,
                      __import__('pokeldn.bdsp.pokemon',fromlist=['build_from']).build_from(raw), game='bdsp')
        return proc
    manager = LiveTrading(store, host_check=lambda:True, devices=devices, process_factory=factory)
    request = str(uuid.uuid4())
    manager.start('generated-pikachu',str(device),'12345678',request,game='bdsp')
    result = wait_for(manager, {'completed'}); manager.worker.join(5)
    assert result['game'] == 'bdsp'
    assert store.export(result['received_id'])[1] == incoming
    assert store.boxes()[0]['slots'][0]['game'] == 'Brilliant Diamond / Shining Pearl'
    assert len(store.boxes()) == 32
    assert manager.start('generated-pikachu',str(device),'12345678',request,game='bdsp')['id'] == result['id']
    assert len(calls) == 1





def test_bounded_bdsp_waits_for_post_animation_selection():
    from pokeldn.bdsp import room
    from pokeldn.bdsp.host import TradePartner
    confirmed=[]
    p=TradePartner(bytes(328),complete=True,trade_limit=1,confirmed=lambda *a:confirmed.append(a))
    p.their_poke=b'original';p.arriving=True;p.trades=1
    assert confirmed==[]
    assert p.game(None,{'data_id':room.TRADE_POKE},bytes(room.HEADER_SIZE)+b'next',1)==[]
    assert confirmed==[(b'original',bytes(328))] and p.finished
    assert p.game(None,{'data_id':room.TRADE_POKE},bytes(room.HEADER_SIZE)+b'another',2)==[]
    assert len(confirmed)==1
