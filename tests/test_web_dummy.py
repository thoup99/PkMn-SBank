import base64
import hashlib
import os
import pytest
from pokeldn import pokemon
from pokeldn.web.storage import BankStore,StorageError
from pokeldn.web.trading import SimulatedTrading
from test_web_storage import imported,TRAINER

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Pi website targets Linux')


def test_generated_offer_is_not_a_box_and_received_record_goes_to_normal_boxes(tmp_path,imported):
 s=BankStore(tmp_path);s.set_trainer(TRAINER)
 assert len(s.boxes())==32 and all(b['kind']=='bank' for b in s.boxes())
 info={'species':'Eevee','species_id':133,'level':10,'legal':True}
 entry=s.receive_record('swsh',b'incoming',info,'receipt-1',sent_id='generated-pikachu')
 assert s.boxes()[0]['slots'][0]['id']==entry
 assert len(s.boxes())==32
 assert s.receive_record('swsh',b'incoming',info,'receipt-1')==entry
 assert len([p for b in s.boxes() for p in b['slots'] if p])==1
 with pytest.raises(StorageError):s.rename(33,'Other')
 with pytest.raises(StorageError):s.move(entry,33,0,None)


def test_confirmed_exchange_removes_outgoing_only_in_same_atomic_commit(tmp_path,imported):
 s=BankStore(tmp_path);s.set_trainer(TRAINER);s.import_file('pika.pk8',b'outgoing')
 outgoing=s.boxes()[0]['slots'][0]['id']
 incoming=s.receive_record('swsh',b'new',{'species':'Eevee','species_id':133,'level':10,'legal':True},'one',sent_id=outgoing,sent_sha256=hashlib.sha256(b'outgoing').hexdigest())
 assert s.boxes()[0]['slots'][0]['id']==incoming
 with pytest.raises(StorageError):s.export(outgoing)
 assert s.export(incoming)[1]==b'new'


def test_full_bank_refuses_new_records_but_allows_atomic_exchange(tmp_path,imported,monkeypatch):
 s=BankStore(tmp_path);s.set_trainer(TRAINER)
 # One batch exercises the real importer without creating 960 historical snapshots.
 parse=pokemon.SERVICE.import_records
 records=[parse(str(i).encode(),f'{i}.pk8',{'swsh':TRAINER})['pokemon'][0] for i in range(960)]
 monkeypatch.setattr(pokemon.SERVICE,'import_records',lambda *args:{'save':'','pokemon':records})
 s.import_file('full.sav',b'full')
 assert len(s.boxes())==32 and all(all(b['slots']) for b in s.boxes())
 before=(tmp_path/'CURRENT').read_bytes()
 info={'species':'Eevee','species_id':133,'level':10,'legal':True}
 with pytest.raises(StorageError,match='full'):
  s.receive_record('swsh',b'new',info,'full',sent_id='generated-pikachu')
 monkeypatch.setattr(pokemon.SERVICE,'import_records',parse)
 with pytest.raises(StorageError,match='full'):s.import_file('extra.pk8',b'extra')
 assert (tmp_path/'CURRENT').read_bytes()==before
 # Duplicate imports and receipt replay do not consume another slot.
 s.import_file('existing.pk8',b'0')
 outgoing=s.boxes()[31]['slots'][29]['id']
 raw=s.export(outgoing)[1]
 received=s.receive_record('swsh',b'new',info,'exchange',sent_id=outgoing,sent_sha256=hashlib.sha256(raw).hexdigest())
 assert s.boxes()[31]['slots'][29]['id']==received
 assert s.receive_record('swsh',b'new',info,'exchange')==received
 assert len(s.boxes())==32
 with pytest.raises(StorageError):s.export(outgoing)


def test_real_pikachu_generated_automatically_and_cached(tmp_path):
 try:pokemon._command()
 except pokemon.BuilderError:pytest.skip('Build PKHeX helper')
 s=BankStore(tmp_path);s.set_trainer(TRAINER);manager=SimulatedTrading(s)
 a=manager.preview('swsh',['generated-pikachu'])
 b=manager.preview('swsh',['generated-pikachu'])
 assert a['compatible'] and a['token']==b['token']
 session=manager.stage('swsh',['generated-pikachu'],a['token'])
 session=manager.action(session['id'],'start',session['version'])
 for _ in range(3):session=manager.action(session['id'],'advance',session['version'])
 assert session['status']=='completed' and len(s.boxes())==32
 assert not any(p for b in s.boxes() for p in b['slots'])
