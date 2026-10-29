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
 assert len(s.boxes())==4 and all(b['kind']=='bank' for b in s.boxes())
 info={'species':'Eevee','species_id':133,'level':10,'legal':True}
 entry=s.receive_record('swsh',b'incoming',info,'receipt-1',sent_id='generated-pikachu')
 assert s.boxes()[0]['slots'][0]['id']==entry
 assert len(s.boxes())==4
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
 assert len(s.boxes())==4
 # The fifth real box is still available; removing the virtual reserve deletes no records.
 s.import_file('overflow.pk8',b'overflow')
 assert s.boxes()[4]['id']==5 and s.boxes()[4]['slots'][0]
 s.rename(5,'Overflow')
 assert s.boxes()[4]['name']=='Overflow'
 overflow=s.boxes()[4]['slots'][0]['id']
 first=s.boxes()[0]['slots'][0]['id']
 s.move(overflow,1,0,first)
 assert s.boxes()[0]['slots'][0]['id']==overflow and s.boxes()[4]['slots'][0]['id']==first
 assert s.export(overflow)[1]==b'overflow'


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
 assert session['status']=='completed' and len(s.boxes())==4
 assert not any(p for b in s.boxes()[:4] for p in b['slots'])
