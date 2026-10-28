"""Copy-on-write snapshots around pokeldn's Bank. Only CURRENT commits a revision.

All website processes cooperate using flock on the Pi. Never point other tools at
an immutable revision: import/export records through the website instead.
"""
import contextlib
import dataclasses
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

from pokeldn.app import bank

GAMES = {"frlg": "FireRed / LeafGreen", "rse": "Ruby / Sapphire / Emerald", "lgpe": "Let's Go",
         "swsh": "Sword / Shield", "bdsp": "Brilliant Diamond / Shining Pearl",
         "pla": "Legends Arceus", "sv": "Scarlet / Violet", "za": "Legends Z-A"}
ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
REVISION = re.compile(r"^[0-9a-f]{32}$")


class StorageError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def durable_write(path, data):
    with path.open("wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def sync_dir(path):
    # Deployment is Linux; portable fallback permits upstream Windows test collection.
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class BankStore:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.revisions = self.root / "revisions"
        self.lock = threading.RLock()

    @contextlib.contextmanager
    def locked(self):
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with (self.root / "LOCK").open("a+b") as lock:
                if os.name == "posix":
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if os.name == "posix":
                        fcntl.flock(lock, fcntl.LOCK_UN)

    def _current(self):
        pointer = self.root / "CURRENT"
        if not pointer.exists():
            # An absent pointer in a previously committed store must not look like an empty Bank.
            if self.revisions.exists() and any(self.revisions.glob("*/state.json")):
                raise StorageError("Bank pointer is missing. Stop the server and recover CURRENT from a verified revision.", 503)
            return None
        revision = pointer.read_text().strip()
        if not REVISION.fullmatch(revision) or not (self.revisions / revision / "state.json").is_file():
            raise StorageError("Bank pointer is invalid. Stop the server and recover CURRENT from a verified revision.", 503)
        return self.revisions / revision

    def _state(self, revision, *, verify=True):
        if revision is None:
            return {"boxes": [{"id": i, "name": name, "slots": [None] * 30} for i, name in
                              enumerate(["Arrival box", "Ready to move", "Favorites", "Recovery"], 1)],
                    "events": [], "trainer": None}
        try:
            state = json.loads((revision / "state.json").read_text())
            if (not isinstance(state, dict) or not isinstance(state.get("files"), dict) or
                    not isinstance(state.get("boxes"), list) or not isinstance(state.get("events"), list) or
                    not (state.get("trainer") is None or isinstance(state.get("trainer"), dict))):
                raise ValueError("Invalid snapshot structure")
            boxes = state["boxes"]
            identifiers = [key for box in boxes for key in box["slots"] if key is not None]
            if (not boxes or len(identifiers) != len(set(identifiers)) or
                    [b["id"] for b in boxes] != list(range(1, len(boxes) + 1)) or
                    any(len(b["slots"]) != 30 or not isinstance(b["name"], str) or
                        not 1 <= len(b["name"]) <= 32 for b in boxes) or
                    any(not isinstance(key, str) or not ID.fullmatch(key) for key in identifiers)):
                raise ValueError("Invalid layout")
            folder = revision / "Bank"
            if verify and {p.name for p in folder.iterdir()} != set(state["files"]):
                raise ValueError("Snapshot files changed")
            if verify and {e.id for e in bank.entries(folder)} != set(identifiers):
                raise ValueError("Snapshot layout does not match records")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StorageError("Bank snapshot metadata is invalid. Recover a verified backup with the server stopped.", 503) from exc
        # Fail closed when a committed record is missing or changed; never silently drop it from boxes.
        for filename, digest in (state["files"].items() if verify else []):
            path = folder / filename
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise StorageError("A Bank snapshot failed its integrity check. Restore a verified backup.", 503)
        return state

    def _commit(self, operation, mutate, *, recovery=False, trade=False):
        with self.locked():
            try:
                current = self._current()
            except StorageError:
                if not recovery:
                    raise
                current = None
            try:
                state = self._state(current, verify=not recovery)
            except StorageError:
                if not recovery:
                    raise
                state = self._state(None)
            session = state.get("trade_session")
            if session is not None and not trade:
                # Lazy import keeps the generic Bank module independent of web session code.
                from pokeldn.web.trading import SimulatedTrading
                try:
                    session = SimulatedTrading._session(state)
                except StorageError:
                    if not recovery:
                        raise
                    state["trade_session"] = session = None
                if session and not recovery and session["status"] in {"connecting", "waiting", "exchanging"}:
                    raise StorageError("Cancel or finish the active simulation before changing Bank data or trainer settings.")
            if recovery and session:
                session.update(status="interrupted", invalidated=True, owner=None, version=session["version"] + 1)
                session["events"].append({"time": time.time(), "message": "Bank recovery invalidated this simulation. Stage a fresh queue."})
            self.revisions.mkdir(exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".pending-", dir=self.root))
            try:
                folder = stage / "Bank"
                if current and not recovery:
                    shutil.copytree(current / "Bank", folder)
                else:
                    folder.mkdir()
                result = mutate(folder, state)
                state["events"].append({"id": uuid.uuid4().hex, "time": time.time(), "action": operation})
                revision = uuid.uuid4().hex
                state.update({"revision": revision, "created": time.time(), "operation": operation,
                              "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in sorted(folder.iterdir()) if p.is_file()}})
                durable_write(stage / "state.json", json.dumps(state, ensure_ascii=False).encode())
                for path in folder.iterdir():
                    with path.open("rb") as record:
                        os.fsync(record.fileno())
                sync_dir(folder)
                sync_dir(stage)
                target = self.revisions / revision
                os.replace(stage, target)
                sync_dir(self.revisions)
                # The old pointer remains valid until the entire new revision is durable.
                temporary = self.root / "CURRENT.tmp"
                durable_write(temporary, (revision + "\n").encode())
                os.replace(temporary, self.root / "CURRENT")
                sync_dir(self.root)
                return result
            finally:
                shutil.rmtree(stage, ignore_errors=True)

    @staticmethod
    def _pokemon(entry):
        meta = bank._read_meta(entry.path)
        display = meta.get("display") or {}
        return {"id": entry.id, "species": meta.get("species") or "Unknown", "dex": entry.species_id,
                "level": display.get("level"), "nature": display.get("nature"),
                "ability": display.get("ability"), "trainer": display.get("ot"), "types": [],
                "game": GAMES.get(entry.game, entry.game), "shiny": entry.shiny,
                "summary": entry.summary, "legal": entry.legal, "home_tracker": entry.home_tracker}

    def boxes(self):
        with self.locked():
            revision = self._current()
            state = self._state(revision)
            entries = {e.id: self._pokemon(e) for e in bank.entries(revision / "Bank")} if revision else {}
            return [{**box, "slots": [entries.get(key) if key else None for key in box["slots"]]}
                    for box in state["boxes"]]

    def settings(self):
        with self.locked():
            return {"trainer": self._state(self._current())["trainer"]}

    def set_trainer(self, trainer):
        return self._commit("Updated receiving trainer", lambda folder, state: state.update(trainer=trainer))

    def import_file(self, name, data):
        def apply(folder, state):
            if state["trainer"] is None:
                raise StorageError("Set your receiving trainer in Settings before importing.", 422)
            before = {e.id for e in bank.entries(folder)}
            with tempfile.TemporaryDirectory(prefix="upload-", dir=self.root) as temp:
                source = Path(temp) / name
                source.write_bytes(data)
                report = bank.import_file(str(source), {g: state["trainer"] for g in GAMES}, folder=folder)
            added = [e for e in reversed(bank.entries(folder)) if e.id not in before]
            for entry in added:
                box = next((b for b in state["boxes"] if None in b["slots"]), None)
                if box is None:
                    box = {"id": len(state["boxes"]) + 1, "name": f"Box {len(state['boxes']) + 1}", "slots": [None] * 30}
                    state["boxes"].append(box)
                box["slots"][box["slots"].index(None)] = entry.id
            # The original name is useful; the transient server upload directory is not.
            for entry in added:
                meta = bank._read_meta(entry.path)
                meta["origin"] = name
                bank._write_meta(entry.path, meta)
            return dataclasses.asdict(report)
        return self._commit(f"Imported {name}", apply)

    def move(self, entry_id, box_id, slot, expected):
        def apply(folder, state):
            source = next(((b, i) for b in state["boxes"] for i, key in enumerate(b["slots"])
                           if key == entry_id), None)
            target = next((b for b in state["boxes"] if b["id"] == box_id), None)
            if not source or not target:
                raise StorageError("Pokémon or destination box not found.", 404)
            if target["slots"][slot] != expected:
                raise StorageError("Destination changed. Refresh your boxes before moving.")
            old_box, old_slot = source
            old_box["slots"][old_slot], target["slots"][slot] = target["slots"][slot], entry_id
        self._commit("Moved Pokémon between slots", apply)

    def rename(self, box_id, name):
        def apply(folder, state):
            box = next((b for b in state["boxes"] if b["id"] == box_id), None)
            if not box:
                raise StorageError("Box not found.", 404)
            box["name"] = name
        self._commit("Renamed box", apply)

    def export(self, entry_id):
        with self.locked():
            revision = self._current()
            self._state(revision)
            entry = bank.find(entry_id, folder=revision / "Bank") if revision else None
            if entry is None:
                raise StorageError("Pokémon not found.", 404)
            return Path(entry.path).name, bank.data(entry)

    def history(self):
        with self.locked():
            return list(reversed(self._state(self._current())["events"]))

    def backups(self):
        with self.locked():
            current = self._current()
            result = []
            if self.revisions.exists():
                for path in self.revisions.iterdir():
                    if not REVISION.fullmatch(path.name):
                        continue
                    try:
                        state = json.loads((path / "state.json").read_text())
                        result.append({"id": path.name, "time": float(state["created"]), "action": state["operation"],
                                       "current": current == path, "valid": True})
                    except (OSError, ValueError, KeyError, TypeError):
                        result.append({"id": path.name, "time": path.stat().st_mtime,
                                       "action": "Damaged snapshot metadata; restore unavailable",
                                       "current": current == path, "valid": False})
            return sorted(result, key=lambda b: b["time"], reverse=True)

    def _revision(self, revision_id):
        if not REVISION.fullmatch(revision_id):
            raise StorageError("Backup not found.", 404)
        revision = self.revisions / revision_id
        if not (revision / "state.json").is_file():
            raise StorageError("Backup not found.", 404)
        self._state(revision)
        return revision

    def backup_file(self):
        with self.locked():
            revision = self._current()
            if revision is None:
                raise StorageError("Save a trainer or import a Pokémon before downloading a backup.", 404)
            self._state(revision)
            fd, name = tempfile.mkstemp(prefix="pkmn-backup-", suffix=".zip", dir=self.root)
            os.close(fd)
            try:
                with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(revision / "state.json", "state.json")
                    for path in (revision / "Bank").iterdir():
                        archive.write(path, "Bank/" + path.name)
                return Path(name)
            except Exception:
                Path(name).unlink(missing_ok=True)
                raise

    def restore(self, revision_id):
        # Clone a previous known revision and commit a NEW revision. Existing history/backups survive.
        def apply(folder, state):
            revision = self._revision(revision_id)
            old = self._state(revision)
            shutil.rmtree(folder)
            shutil.copytree(revision / "Bank", folder)
            state.update(boxes=old["boxes"], trainer=old["trainer"])
        self._commit("Restored backup " + revision_id, apply, recovery=True)

    def restore_archive(self, archive_path):
        """Offline recovery from a downloaded ZIP; callers must stop the web server first."""
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="recover-", dir=self.root) as temp:
            extracted = Path(temp)
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    members = archive.infolist()
                    if len(members) > 50000 or sum(m.file_size for m in members) > 512 << 20:
                        raise ValueError("Backup is too large (512 MiB / 50,000 files).")
                    names = [m.filename for m in members]
                    if len(names) != len(set(names)) or "state.json" not in names:
                        raise ValueError("Invalid backup members")
                    for member in members:
                        name = member.filename
                        parts = name.split("/")
                        allowed = (name == "state.json" or len(parts) == 2 and parts[0] == "Bank" and
                                   (parts[1] == bank.LEDGER or
                                    bool(bank.FILES.search(parts[1])) or parts[1].endswith(".json")))
                        if (not allowed or ".." in parts or "\\" in name or member.is_dir() or
                                member.external_attr >> 16 & 0o170000 == 0o120000):
                            raise ValueError("Unexpected backup member")
                        target = extracted / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as source, target.open("wb") as out:
                            shutil.copyfileobj(source, out)
                (extracted / "Bank").mkdir(exist_ok=True)
                recovered = self._state(extracted)
            except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
                raise StorageError("The backup ZIP is invalid or damaged.", 422) from exc
            def apply(folder, state):
                shutil.rmtree(folder)
                shutil.copytree(extracted / "Bank", folder)
                state.update(boxes=recovered["boxes"], trainer=recovered["trainer"])
            self._commit("Recovered downloaded backup ZIP", apply, recovery=True)
