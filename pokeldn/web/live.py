"""One bounded USB Sword/Shield or Legends Z-A trade; raw confirmed receipts survive process/server failures."""
import base64
from collections import deque
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

from pokeldn import pokemon, gen8
from pokeldn.app import bank
from pokeldn.app.paths import ROOT
from pokeldn.swsh import pokemon as swsh_pokemon
from pokeldn.sv.trade import load_offer as sv_offer
from pokeldn.pla import pokemon as pla_pokemon
from pokeldn.web.dummy import DummyOffers,is_dummy,GENERATED_ID
from pokeldn.web.serve import supported_host
from pokeldn.web.keys import keys_path
from pokeldn.web.storage import GAMES,StorageError,durable_write,BOX_COUNT

ACTIVE={'starting','running','stopping'}
PENDING=ACTIVE|{'interrupted','uncertain','recovery_required'}
LIVE_GAMES=[{'key': key, 'name': name, 'available': key in {'swsh', 'za', 'sv', 'pla'}}
            for key, name in GAMES.items() if key not in {'frlg', 'rse'}]


def usb_devices():
    from serial.tools import list_ports
    return [{'device':p.device,'description':p.description,'serial_number':p.serial_number}
            for p in list_ports.comports() if (p.vid,p.pid)==(0x303a,0x1001)]


class LiveTrading:
    def __init__(self,store,*,host_check=None,devices=None,process_factory=None):
        self.store=store;self.owner=uuid.uuid4().hex
        self.host_check=host_check or supported_host;self.devices=devices or usb_devices
        self.process_factory=process_factory or subprocess.Popen
        self.proc=None;self.worker=None;self.lock=threading.RLock();self.logs=deque(maxlen=100)
        self.dummies=DummyOffers(store.root)
        self.compatibility_cache = {}

    def _mutate(self,operation,callback):
        return self.store._commit(operation,callback,trade=True,live=True)

    def _folder(self,session):
        if not re.fullmatch('[0-9a-f]{32}',session['id']):raise StorageError('Invalid USB session metadata.',503)
        return self.store.root/'live-runs'/session['id']

    def _usb_lock(self):
        import fcntl
        self.store.root.mkdir(parents=True,exist_ok=True)
        fd=os.open(self.store.root/'USB.lock',os.O_CREAT|os.O_RDWR,0o600)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            os.close(fd);raise StorageError('Another USB operation still owns the board. Wait for it to finish before retrying.')
        return fd

    def _read(self):
        with self.store.locked():return copy.deepcopy(self.store._state(self.store._current()).get('live_session'))

    def hardware_status(self):
        # Enumeration only: polling must never open/reset a board used by a trade or flasher.
        if not self.host_check():
            return {'hardware_connected': False, 'hardware_status': 'unsupported', 'devices': []}
        try:
            devices = self.devices()
        except (OSError, ImportError):
            return {'hardware_connected': False, 'hardware_status': 'unavailable', 'devices': []}
        return {'hardware_connected': bool(devices),
                'hardware_status': 'connected' if devices else 'disconnected', 'devices': devices}

    def current(self):
        with self.lock:
            session=self._read()
            if session and session['status'] in ACTIVE and (session.get('owner')!=self.owner or (self.worker is not None and not self.worker.is_alive() and self.proc is not None and self.proc.poll() is not None)):
                def interrupt(folder,state):
                    s=state['live_session'];s.update(status='interrupted',message='Server restarted. Do not repeat the trade; recover the durable receipt after the old process exits.')
                    return copy.deepcopy(s)
                session=self._mutate('USB session interrupted; recovery required',interrupt)
            keys=keys_path()
            return {'supported_host':self.host_check(),'keys_available':keys.is_file() and os.access(keys,os.R_OK),
                    'devices':self.devices() if self.host_check() else [],'game':'swsh','games':copy.deepcopy(LIVE_GAMES),
                    'session':session,'logs':list(self.logs)}

    def install_keys(self, content):
        from pokeldn.web.keys import install
        with self.lock:
            session = self._read()
            if session and session['status'] in ACTIVE:
                raise StorageError('Stop the USB trade before replacing keys.')
            fd = self._usb_lock()
            try:
                return install(content)
            finally:
                os.close(fd)

    def _prepare_offer(self, folder, trainer, entry_id, game, entry=None, *, fresh_dummy=False):
        if trainer is None:
            raise pokemon.BuilderError('Save your receiving trainer in Settings first.')
        dummy = is_dummy(entry_id)
        entry = None if dummy else entry or bank.find(entry_id, folder=folder)
        if not dummy and entry is None:
            raise pokemon.BuilderError('Outgoing Pokémon no longer exists.')
        reply = self.dummies.get(game, trainer) if dummy else pokemon.SERVICE.move(
            entry.game, game, bank.data(entry), entry.tracker, trainer)
        raw = base64.b64decode(reply['data'], validate=True)
        checked = pokemon.SERVICE.check_bytes(game, raw, fresh=fresh_dummy and dummy)
        if not reply.get('legal') or not checked.get('legal'):
            raise pokemon.BuilderError(checked.get('report') or 'PKHeX refused the outgoing offer.')
        if fresh_dummy and dummy:
            raw = base64.b64decode(checked['data'], validate=True)
        wire = swsh_pokemon.encrypt(gen8.load(raw)) if game == 'swsh' else pla_pokemon.encrypt(pla_pokemon.load(raw)) if game == 'pla' else (sv_offer(raw) if game == 'sv' else pokemon.offer_bytes('za', raw))
        return entry, raw, checked, wire

    def compatibility(self, game):
        if game not in {'swsh', 'za', 'sv', 'pla'}:
            raise StorageError('Choose a connected live trading game.', 422)
        with self.store.locked():
            revision = self.store._current()
            state = self.store._state(revision)
            key = (str(revision), game, pokemon.SERVICE.home_tracker)
            if key in self.compatibility_cache:
                return copy.deepcopy(self.compatibility_cache[key])
            folder = revision / 'Bank' if revision else None
            entries = bank.entries(folder) if folder else []
            results = []
            def check(entry_id, entry=None):
                try:
                    self._prepare_offer(folder, state['trainer'], entry_id, game, entry)
                    return {'compatible': True, 'reason': ''}
                except pokemon.BuilderError as error:
                    return {'compatible': False, 'reason': str(error)}
            for entry in entries:
                results.append({'id': entry.id, **check(entry.id, entry)})
            results.append({'id': GENERATED_ID, **check(GENERATED_ID)})
            result = {'game': game, 'entries': results}
            self.compatibility_cache = {key: result}
            return copy.deepcopy(result)

    def start(self,entry_id,device,code,request_id,*,game='swsh'):
        with self.lock:
            if game not in {'swsh', 'za', 'sv', 'pla'}:raise StorageError('Choose an available live trading game.',422)
            if not self.host_check():raise StorageError('Live USB trading requires a 64-bit Raspberry Pi 5.',422)
            if not re.fullmatch('[0-9]{8}',code) or not re.fullmatch('[0-9a-f-]{36}',request_id):
                raise StorageError('Use an eight-digit Link Code and a valid request ID.',422)
            if device not in {p['device'] for p in self.devices()}:
                raise StorageError('Choose an attached Espressif native USB port. S3 boards must use the native USB connector.',422)
            if not os.access(device,os.R_OK|os.W_OK):raise StorageError('The Pi user cannot access this serial port. Add the user to dialout and log in again.',422)
            keys=keys_path()
            if not keys.is_file() or not os.access(keys,os.R_OK):raise StorageError('Install your own Switch prod.keys on the Pi before a real trade.',422)
            previous=self._read()
            if previous and previous.get('request_id')==request_id:return previous
            if previous and previous['status'] in PENDING:raise StorageError('Stop/recover/resolve the previous USB session before starting another.')
            usb_fd=self._usb_lock()
            launched=False
            try:
                def prepare(folder,state):
                    simulation=state.get('trade_session')
                    if simulation and simulation.get('status') in {'connecting','waiting','exchanging'}:
                        raise StorageError('Cancel the running simulation before starting USB trading.')
                    trainer=state['trainer']
                    if trainer is None:raise StorageError('Save your receiving trainer first.',422)
                    dummy=is_dummy(entry_id);entry=None if dummy else bank.find(entry_id,folder=folder)
                    if not dummy and entry is None:raise StorageError('Outgoing Pokémon no longer exists.',404)
                    space=any(None in b['slots'] for b in state['boxes'][:BOX_COUNT])
                    frees=not dummy and any(entry_id in b['slots'] for b in state['boxes'][:BOX_COUNT])
                    if not space and not frees:raise StorageError('All 32 boxes are full. Make space before depositing.')
                    entry,raw,checked,wire=self._prepare_offer(folder,trainer,entry_id,game,entry,fresh_dummy=dummy)
                    session={'id':uuid.uuid4().hex,'request_id':request_id,'owner':self.owner,'mode':'usb','game':game,
                             'status':'starting','entry_id':entry_id,'dummy':dummy,'species':checked.get('species','Pikachu'),
                             'trainer':trainer,'sent_sha256':None if dummy else hashlib.sha256(bank.data(entry)).hexdigest(),
                             'offered_sha256':hashlib.sha256(wire).hexdigest(),'code':code,'device':device,
                             'started_at':time.time(),'message':'Starting one real '+GAMES[game]+' trade.','received_id':None}
                    run=self._folder(session);run.mkdir(parents=True,mode=0o700)
                    durable_write(run/('offer.'+pokemon.EXTENSIONS[game]),raw)
                    durable_write(run/'session.json',json.dumps(session).encode())
                    state['live_session']=session
                    return copy.deepcopy(session)
                session=self._mutate('Started USB '+GAMES[game]+' trade',prepare)
                run=self._folder(session)
                env=dict(os.environ,PYTHONUNBUFFERED='1',POKELDN_MANAGED_RUN='1',POKELDN_RADIO='esp32:'+device)
                env.pop('POKELDN_L2',None)
                env.pop('POKELDN_POPUPS',None)
                argv=[sys.executable,'-u',str(Path(ROOT)/'pokeldn/app/entry.py'),'--run',
                      'bin/swsh_host.py' if game=='swsh' else 'bin/sv_host.py' if game=='sv' else 'bin/pla_host.py' if game=='pla' else 'bin/za_host.py',
                      '--keys',str(keys), '--offer-file' if game=='swsh' else '--trade-box-record' if game=='pla' else '--trade-offer',
                      str(run/('offer.'+pokemon.EXTENSIONS[game])),
                      '--received' if game=='swsh' else '--offer-out',
                      str(run/('candidate.'+pokemon.EXTENSIONS[game])),
                      '--player-name',session['trainer']['ot'],'--trainer-name',session['trainer']['ot'],
                      '--code',code,'--seconds','300','--one-trade-receipt',str(run/'confirmed.json')]
                if game=='pla':
                    index=argv.index('--trainer-name')
                    del argv[index:index+2]
                    argv.extend(['--channel','6','--session-update','--sustain','--clock','--data-exchange','--game-channel','--trade-box','--gender',str(session['trainer']['gender'])])
                if game=='swsh':
                    argv.extend(['--trainer-tid',str(session['trainer']['tid']),'--trainer-sid',str(session['trainer']['sid'])])
                self.logs.clear()
                self.proc=self.process_factory(argv,cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                               stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
                                               bufsize=1,pass_fds=(usb_fd,),start_new_session=True)
                launched=True
                def running(folder,state):
                    state['live_session'].update(status='running',message=('In Sword/Shield, use local Y-Comm Link Trade' if game=='swsh' else 'In Scarlet/Violet, open Poké Portal and Link Trade with offline communication' if game=='sv' else 'In Legends Arceus, speak to Simona, choose I want to trade Pokémon and Someone nearby' if game=='pla' else 'In Legends Z-A, open Link Play, choose local communication and Link Trade')+' with this Link Code. Complete exactly one trade and wait for the website result.')
                self._mutate('USB trade process running',running)
                self.worker=threading.Thread(target=self._worker,args=(session,self.proc,usb_fd),daemon=True)
                self.worker.start()
                usb_fd=None
                return self._read()
            except Exception:
                if self.proc is not None and self.proc.poll() is None:
                    self.proc.kill();self.proc.wait()
                if self._read() and self._read().get('status')=='starting':
                    self._mutate('USB process startup failed',lambda f,s:s['live_session'].update(status='interrupted' if launched else 'failed',message='USB process startup did not finish. Inspect the game and recover any receipt before retrying.' if launched else 'Unable to start the USB trade process. Check dependencies.'))
                raise
            finally:
                if usb_fd is not None:os.close(usb_fd)

    def _worker(self,session,proc,usb_fd):
        run=self._folder(session)
        try:
            written=0
            with (run/'process.log').open('w') as out:
                for line in proc.stdout:
                    self.logs.append(line.rstrip()[:1000])
                    if written<4*1024*1024:out.write(line);out.flush();written+=len(line)
            proc.stdout.close();code=proc.wait()
            if proc.stdin and not proc.stdin.closed:
                try:proc.stdin.close()
                except (OSError,ValueError):pass
            self._finish(session,code)
        except Exception:
            if proc.poll() is None:
                try:
                    if proc.stdin and not proc.stdin.closed:
                        proc.stdin.close()
                    proc.wait(timeout=15)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    proc.kill()
                    proc.wait()
            try:self._status(session['id'],'recovery_required','Could not finalize the USB session. Received files are retained; use Recover receipt.')
            except Exception:pass
        finally:
            os.close(usb_fd)

    def _status(self,id,status,message,**fields):
        def apply(folder,state):
            s=state.get('live_session')
            if not s or s['id']!=id:raise StorageError('USB session changed; receipt remains in recovery storage.')
            s.update(status=status,message=message,**fields)
            return copy.deepcopy(s)
        return self._mutate('USB: '+status,apply)

    def _finish(self,session,returncode):
        run=self._folder(session);path=run/'confirmed.json'
        if not path.exists():
            return self._status(session['id'],'uncertain','No durable confirmation. Bank originals are retained. Inspect the game before resolving; do not automatically repeat this trade.',returncode=returncode)
        try:
            if path.stat().st_size>20000:raise ValueError('oversized receipt')
            receipt=json.loads(path.read_text())
            data=base64.b64decode(receipt['received'],validate=True)
            if (receipt['version']!=1 or receipt['game']!=session['game'] or receipt['trade']!=1 or
                    receipt['received_sha256']!=hashlib.sha256(data).hexdigest() or
                    receipt['offered_sha256']!=session['offered_sha256']):raise ValueError('receipt mismatch')
            info=pokemon.SERVICE.check_bytes(session['game'],data)
            received=self.store.receive_record(session['game'],data,info,'usb-'+session['id'],sent_id=session['entry_id'],sent_sha256=session['sent_sha256'])
            return self._status(session['id'],'completed','Confirmed trade committed. Incoming Pokémon is in the first available Bank slot.',received_id=received,returncode=returncode)
        except Exception:
            return self._status(session['id'],'recovery_required','Confirmed/raw files are retained. Commit failed; fix storage/helper issues and use Recover receipt.',returncode=returncode)

    def cancel(self,id):
        with self.lock:
            session=self._read()
            if not session or session['id']!=id:raise StorageError('USB session not found.',404)
            if session['status'] not in ACTIVE:return session
            self._status(id,'stopping','Stopping gracefully. A durable confirmation, if present, will still be committed.')
            if self.proc is None or self.proc.poll() is not None:
                return self._status(id,'interrupted','The old process is not owned by this server. Wait for its 300-second deadline or reboot the Pi, then recover.')
            if not self.proc.stdin.closed:
                try:self.proc.stdin.close()
                except (OSError,ValueError):pass
            def escalate(proc):
                try:proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:proc.kill()
            threading.Thread(target=escalate,args=(self.proc,),daemon=True).start()
            return self._read()

    def recover(self,id,*,resolve=False):
        with self.lock:
            session=self._read()
            if not session or session['id']!=id:raise StorageError('USB session not found.',404)
            if session['status']=='completed':return session
            if session['status'] in ACTIVE and self.proc is not None and self.proc.poll() is None:
                raise StorageError('Stop the current USB process before recovery.')
            fd=self._usb_lock()
            try:
                if resolve:
                    if (self._folder(session)/'confirmed.json').exists():raise StorageError('A confirmation exists; recover it instead of discarding it.')
                    return self._status(id,'resolved','Operator checked the game and resolved the unconfirmed session. Original Bank records and raw files are retained.')
                return self._finish(session,session.get('returncode'))
            finally:os.close(fd)
