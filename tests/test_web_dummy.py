import base64
import hashlib
import os
import pytest
from pokeldn import pokemon
from pokeldn.web.storage import BankStore,StorageError
from pokeldn.web.trading import SimulatedTrading
from test_web_storage import imported,TRAINER

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Pi website targets Linux')


def test_reserve_always_full_and_received_record_goes_to_normal_box(tmp_path,imported):
 s=BankStore(tmp_path);s.set_trainer(TRAINER)
 reserve=s.boxes()[4];assert reserve['id']==5 and reserve['kind']=='dummy'
 assert len(reserve['slots'])==30 and all(p['dex']==25 and p['dummy'] for p in reserve['slots'])
 info={'species':'Eevee','species_id':133,'level':10,'legal':True}
 entry=s.receive_record('swsh',b'incoming',info,'receipt-1',sent_id='dummy-pikachu-01')
 assert s.boxes()[0]['slots'][0]['id']==entry
 assert s.boxes()[4]==reserve
 assert s.receive_record('swsh',b'incoming',info,'receipt-1')==entry
 assert len([p for b in s.boxes()[:4] for p in b['slots'] if p])==1
 with pytest.raises(StorageError):s.rename(5,'Other')
 with pytest.raises(StorageError):s.move(entry,5,0,None)


def test_confirmed_exchange_removes_outgoing_only_in_same_atomic_commit(tmp_path,imported):
 s=BankStore(tmp_path);s.set_trainer(TRAINER);s.import_file('pika.pk8',b'outgoing')
 outgoing=s.boxes()[0]['slots'][0]['id']
 incoming=s.receive_record('swsh',b'new',{'species':'Eevee','species_id':133,'level':10,'legal':True},'one',sent_id=outgoing,sent_sha256=hashlib.sha256(b'outgoing').hexdigest())
 assert s.boxes()[0]['slots'][0]['id']==incoming
 with pytest.raises(StorageError):s.export(outgoing)
 assert s.export(incoming)[1]==b'new'


def test_full_normal_boxes_refuse_receipt_without_losing_outgoing(tmp_path,imported):
 s=BankStore(tmp_path);s.set_trainer(TRAINER)
 # Fill real slots with actual distinct Bank records through existing importer.
 for i in range(120):s.import_file(f'{i}.pk8',str(i).encode())
 before=(tmp_path/'CURRENT').read_bytes()
 with pytest.raises(StorageError,match='full'):s.receive_record('swsh',b'new',{'species':'Eevee','species_id':133,'level':10,'legal':True},'full',sent_id='dummy-pikachu-02')
 assert (tmp_path/'CURRENT').read_bytes()==before
 assert len(s.boxes()[4]['slots'])==30
 # Existing overflow is exposed as box 6, never replaces reserve 5.
 s.import_file('overflow.pk8',b'overflow')
 assert s.boxes()[5]['id']==6 and s.boxes()[5]['slots'][0]


def test_real_pikachu_generated_automatically_and_cached(tmp_path):
 try:pokemon._command()
 except pokemon.BuilderError:pytest.skip('Build PKHeX helper')
 s=BankStore(tmp_path);s.set_trainer(TRAINER);manager=SimulatedTrading(s)
 a=manager.preview('swsh',['dummy-pikachu-01'])
 b=manager.preview('swsh',['dummy-pikachu-01'])
 assert a['compatible'] and a['token']==b['token']
 session=manager.stage('swsh',['dummy-pikachu-01'],a['token'])
 session=manager.action(session['id'],'start',session['version'])
 for _ in range(3):session=manager.action(session['id'],'advance',session['version'])
 assert session['status']=='completed' and len(s.boxes()[4]['slots'])==30
 assert not any(p for b in s.boxes()[:4] for p in b['slots'])
