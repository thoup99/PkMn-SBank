"""Durable, manually advanced simulation. No radio, child trade process or Bank removal.

Preparation uses the same PKHeX move/check boundary as the upstream Bank. Only
fingerprints and display metadata are retained, never prepared record bytes.
"""
import base64
import copy
import hashlib
import json
import re
import time
import uuid

from pokeldn import pokemon
from pokeldn.app import bank
from pokeldn.web.storage import GAMES, StorageError
from pokeldn.web.dummy import DummyOffers, is_dummy

TARGETS = {key: name for key, name in GAMES.items() if key != "rse"}
ACTIVE = {"connecting", "waiting", "exchanging"}
RESUMABLE = {"disconnected", "failed", "interrupted"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def log(session, message):
    session["events"].append({"time": time.time(), "message": message})
    session["updated_at"] = time.time()


class SimulatedTrading:
    def __init__(self, store):
        self.store = store
        self.owner = uuid.uuid4().hex
        self.dummies = DummyOffers(store.root)

    @staticmethod
    def _session(state):
        session = state.get("trade_session")
        if session is not None:
            try:
                queue = session["queue"]
                valid = (isinstance(session, dict) and session["mode"] == "simulation" and
                         isinstance(queue, list) and 1 <= len(queue) <= 6 and
                         all(isinstance(item, dict) and isinstance(item["id"], str) and
                             isinstance(item["species"], str) for item in queue) and
                         len({item["id"] for item in queue}) == len(queue) and
                         re.fullmatch(r"[0-9a-f]{32}", session["id"]) is not None and
                         re.fullmatch(r"[0-9a-f]{64}", session["token"]) is not None and
                         type(session["completed"]) is int and 0 <= session["completed"] <= len(queue) and
                         type(session["version"]) is int and session["version"] >= 1 and
                         type(session["fault_after"]) is int and 0 <= session["fault_after"] < len(queue) and
                         session["scenario"] in ("success", "disconnect", "failure") and
                         type(session["fault_injected"]) is bool and type(session["invalidated"]) is bool and
                         isinstance(session["events"], list) and
                         all(isinstance(event, dict) and isinstance(event["message"], str) and
                             type(event["time"]) in (int, float) for event in session["events"]) and
                         session["game"] in TARGETS and session["status"] in
                         ACTIVE | RESUMABLE | {"ready", "completed", "cancelled"})
            except (KeyError, TypeError):
                valid = False
            if not valid:
                raise StorageError("Simulation metadata is invalid. Recover a verified Bank backup.", 503)
        return session

    def current(self):
        with self.store.locked():
            state = self.store._state(self.store._current())
            session = copy.deepcopy(self._session(state))
        if session and session["status"] in ACTIVE and session.get("owner") != self.owner:
            def interrupt(folder, state):
                current = self._session(state)
                if current and current["status"] in ACTIVE and current.get("owner") != self.owner:
                    current["status"] = "interrupted"
                    current["version"] += 1
                    current["owner"] = None
                    log(current, "Server restarted or another process took over. Resume explicitly; Bank records are unchanged.")
                return copy.deepcopy(current)
            session = self.store._commit("Simulation interrupted; explicit recovery required", interrupt, trade=True)
        return {"mode": "simulation", "games": [{"key": key, "name": name} for key, name in TARGETS.items()],
                "session": session}

    def _prepare(self, folder, state, game, entry_ids):
        if game not in TARGETS or not 1 <= len(entry_ids) <= 6 or len(entry_ids) != len(set(entry_ids)):
            raise StorageError("Choose a supported Switch game and one to six distinct Bank Pokémon.", 422)
        trainer = state["trainer"]
        if trainer is None:
            raise StorageError("Set your receiving trainer in Settings first.", 422)
        records, sources = [], []
        for entry_id in entry_ids:
            dummy = is_dummy(entry_id)
            entry = None if dummy else bank.find(entry_id, folder=folder)
            if not dummy and entry is None:
                raise StorageError("A staged Pokémon is no longer in the Bank. Refresh and select it again.", 409)
            result = {"id": entry_id, "species": "Pikachu" if dummy else self.store._pokemon(entry)["species"],
                      "source_game": "Generated Pikachu" if dummy else GAMES[entry.game], "dummy": dummy,
                      "compatible": False, "reason": "", "warnings": []}
            try:
                reply = self.dummies.get(game, trainer) if dummy else pokemon.SERVICE.move(
                    entry.game, game, bank.data(entry), entry.tracker, trainer)
                raw = base64.b64decode(reply['data']) if dummy else bank.data(entry)
                sources.append({"id":entry_id,"sha256":hashlib.sha256(raw).hexdigest(),
                                "game":game if dummy else entry.game,"tracker":"0" if dummy else str(entry.tracker)})
                prepared = base64.b64decode(reply["data"], validate=True)
                checked = pokemon.SERVICE.check_bytes(game, prepared)
                if not reply.get("legal") or not checked.get("legal"):
                    raise pokemon.BuilderError(checked.get("report") or checked.get("problems") or "PKHeX refused the prepared record.")
                result.update(compatible=True, prepared_sha256=hashlib.sha256(prepared).hexdigest(),
                              format=checked.get("format", ""))
                home = reply.get("home_tracker", "")
                if home in pokemon.HOME_TRACKER_WARNINGS:
                    result["warnings"].append(pokemon.HOME_TRACKER_WARNINGS[home])
                if dummy:
                    result["warnings"].append("Generated Pikachu offer: incoming records are routed to boxes 1–4.")
                if not dummy and entry.game != game:
                    result["warnings"].append("Prepared for the selected game using the Bank's conversion rules; the original record stays unchanged.")
            except pokemon.BuilderError as error:
                result["reason"] = str(error)
            except (KeyError, ValueError) as error:
                raise StorageError("PKHeX returned an invalid preparation result. Try again after checking the helper.", 503) from error
            records.append(result)
        token = digest({"game": game, "trainer": trainer, "sources": sources,
                        "home_tracker": pokemon.SERVICE.home_tracker})
        return {"game": game, "queue": records, "token": token,
                "compatible": all(record["compatible"] for record in records)}

    def preview(self, game, entry_ids):
        with self.store.locked():
            revision = self.store._current()
            state = self.store._state(revision)
            if revision is None:
                raise StorageError("Import Pokémon into your Bank first.", 422)
            return self._prepare(revision / "Bank", state, game, entry_ids)

    def stage(self, game, entry_ids, token):
        def apply(folder, state):
            old = self._session(state)
            if old and old["status"] in ACTIVE:
                raise StorageError("Cancel or finish the active simulation before staging a new queue.")
            prepared = self._prepare(folder, state, game, entry_ids)
            if prepared["token"] != token:
                raise StorageError("Bank records or trainer settings changed. Check compatibility again.")
            if not prepared["compatible"]:
                raise StorageError("One or more Pokémon cannot be prepared for this game. Check compatibility again.", 422)
            session = {"id": uuid.uuid4().hex, "mode": "simulation", "version": 1, "game": game,
                       "status": "ready", "queue": prepared["queue"], "token": token, "completed": 0,
                       "owner": None, "scenario": "success", "fault_after": 0, "fault_injected": False,
                       "invalidated": False, "events": [], "updated_at": time.time()}
            log(session, "Queue staged. Simulation only; no Bank Pokémon will be removed.")
            state["trade_session"] = session
            return copy.deepcopy(session)
        return self.store._commit("Simulation queue staged for " + GAMES.get(game, game), apply, trade=True)

    def action(self, session_id, action, version, *, scenario="success", fault_after=0):
        # A request after restart first invalidates the old worker's running state.
        self.current()
        def apply(folder, state):
            session = self._session(state)
            if not session or session["id"] != session_id:
                raise StorageError("Session not found. Refresh the Trading page.", 404)
            if session["version"] != version:
                raise StorageError("Session changed. Refresh its status before trying again.")
            status = session["status"]
            if action in ("start", "resume"):
                allowed = status == "ready" if action == "start" else status in RESUMABLE
                if not allowed or session.get("invalidated"):
                    raise StorageError("This session cannot start or resume. Stage a fresh queue.")
                check = self._prepare(folder, state, session["game"], [record["id"] for record in session["queue"]])
                if check["token"] != session["token"] or not check["compatible"]:
                    raise StorageError("Bank records, trainer settings or compatibility changed. Stage a fresh queue.")
                if action == "start":
                    if scenario not in ("success", "disconnect", "failure") or not 0 <= fault_after < len(session["queue"]):
                        raise StorageError("Choose a valid simulation scenario and fault position.", 422)
                    session.update(scenario=scenario, fault_after=fault_after)
                session.update(status="connecting", owner=self.owner, queue=check["queue"])
                log(session, "Simulation started." if action == "start" else "Simulation resumed after revalidation.")
            elif action == "advance":
                if status == "connecting":
                    session["status"] = "waiting"
                    log(session, "Simulated connection ready. Waiting for the simulated partner.")
                elif status == "waiting":
                    session["status"] = "exchanging"
                    log(session, "Simulated partner ready. Awaiting a simulated confirmation.")
                elif status == "exchanging":
                    if (session["scenario"] != "success" and not session["fault_injected"] and
                            session["completed"] == session["fault_after"]):
                        session["status"] = "disconnected" if session["scenario"] == "disconnect" else "failed"
                        session["fault_injected"] = True
                        log(session, "Simulated disconnect before confirmation." if session["scenario"] == "disconnect"
                            else "Simulated failure before confirmation.")
                    else:
                        record = session["queue"][session["completed"]]
                        session["completed"] += 1
                        session["status"] = "completed" if session["completed"] == len(session["queue"]) else "waiting"
                        log(session, f"Simulated confirmation {session['completed']}: {record['species']}. Original retained in Bank.")
                        if session["status"] == "completed":
                            log(session, "Simulation completed. No real trade occurred; every Bank record is retained.")
                else:
                    raise StorageError("Only a running simulation can advance.")
            elif action == "cancel":
                if status not in ACTIVE | RESUMABLE | {"ready"}:
                    raise StorageError("This simulation has already ended.")
                session["status"] = "cancelled"
                log(session, "Simulation cancelled. All Bank records are retained.")
            else:
                raise StorageError("Unknown simulation action.", 422)
            session["version"] += 1
            return copy.deepcopy(session)
        return self.store._commit("Simulation: " + action, apply, trade=True)
