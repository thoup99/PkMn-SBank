"""Virtual, inexhaustible deposit offers; never real Bank entries."""
import base64
import hashlib
import json
import os
import re
import threading
from pokeldn import pokemon


def is_dummy(entry_id):
    return isinstance(entry_id, str) and re.fullmatch(r'dummy-pikachu-(0[1-9]|[12][0-9]|30)', entry_id) is not None


def reserve_box():
    return {'id':5,'kind':'dummy','name':'Pikachu reserve','slots':[
        {'id':f'dummy-pikachu-{i:02}', 'species':'Pikachu','dex':25,'level':None,'types':['Electric'],
         'nature':None,'ability':None,'game':'Reusable deposit offer','trainer':None,'shiny':False,
         'dummy':True,'summary':'Automatically prepared for the selected game. Received Pokémon go to boxes 1–4.'}
        for i in range(1,31)]}


class DummyOffers:
    def __init__(self, root):
        self.folder=root/'dummy-offers'
        self.lock=threading.Lock()

    def get(self,game,trainer):
        key=hashlib.sha256(json.dumps({'game':game,'trainer':trainer,'version':1},sort_keys=True).encode()).hexdigest()
        with self.lock:
            path=self.folder/(key+'.json')
            if path.is_file():
                try:
                    reply=json.loads(path.read_text())
                    base64.b64decode(reply['data'],validate=True)
                    return reply
                except (OSError,ValueError,KeyError):
                    pass
            reply=pokemon.SERVICE.make(game,25,trainer)
            reply={k:v for k,v in reply.items() if k!='file'}
            self.folder.mkdir(parents=True,exist_ok=True,mode=0o700)
            temporary=path.with_suffix('.tmp')
            with temporary.open('w') as out:
                json.dump(reply,out);out.flush();os.fsync(out.fileno())
            os.replace(temporary,path)
            return reply
