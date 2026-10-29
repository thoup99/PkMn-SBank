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


def test_sv_generated_receipt_and_correct_launcher_are_idempotent(usb):
    store, device, devices, _ = usb
    incoming = base64.b64decode(pokemon.SERVICE.make('sv',133,TRAINER)['data'])
    calls = []
    def factory(argv, **kwargs):
        proc = FakeProcess(argv, **kwargs); calls.append(proc)
        assert 'bin/sv_host.py' in argv and '--trainer-tid' not in argv
        raw = Path(argv[argv.index('--trade-offer')+1]).read_bytes()
        write_receipt(argv[argv.index('--one-trade-receipt')+1], incoming,
                      __import__('pokeldn.sv.trade',fromlist=['load_offer']).load_offer(raw), game='sv')
        return proc
    manager = LiveTrading(store, host_check=lambda:True, devices=devices, process_factory=factory)
    request = str(uuid.uuid4())
    manager.start('generated-pikachu',str(device),'12345678',request,game='sv')
    result = wait_for(manager, {'completed'}); manager.worker.join(5)
    assert result['game'] == 'sv'
    assert store.export(result['received_id'])[1] == incoming
    assert store.boxes()[0]['slots'][0]['game'] == 'Scarlet / Violet'
    assert len(store.boxes()) == 32
    assert manager.start('generated-pikachu',str(device),'12345678',request,game='sv')['id'] == result['id']
    assert len(calls) == 1



def test_sv_bounded_cli_requires_single_plain_offer(tmp_path):
    import sv_host
    with pytest.raises(SystemExit):
        sv_host.main(['--one-trade-receipt',str(tmp_path/'receipt.json')])


def test_sv_single_offer_stage_never_starts_a_second_exchange():
    from pokeldn.sv import trade
    stage=trade.TradeStage(bytes(trade.OFFER_SIZE))
    stage.on_message(0,trade.build(trade.KEY_TRADE,trade.KIND_OFFER,body=bytes(trade.OFFER_SIZE)))
    stage.on_message(0,trade.build(trade.KEY_TRADE,trade.KIND_COMMIT))
    stage.on_message(1,trade.table_update(trade.KEY_EXCHANGE,True))
    for step in trade.STEPS:
        stage.on_message(0,trade.build(trade.KEY_EXCHANGE,trade.KIND_STEP_OPEN,step))
    assert stage.trades==1 and stage.done
    assert stage.on_message(0,trade.build(trade.KEY_TRADE,trade.KIND_OFFER,body=bytes(trade.OFFER_SIZE)))==[]
