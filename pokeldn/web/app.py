"""Raspberry Pi 5 website API; no Switch sessions or 3DS integration."""
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import Response, FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from urllib.parse import urlsplit
from pydantic import Field
from typing import Literal
from pokeldn.web.trading import SimulatedTrading, TARGETS
from pokeldn.web.storage import BankStore, StorageError
from pokeldn.pokemon import BuilderError, _command
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pokeldn.web.dummy import reserve_box
from pokeldn.web.live import LiveTrading


class Pokemon(BaseModel):
    id: str
    species: str
    dex: int
    level: int | None
    types: list[str]
    nature: str | None
    ability: str | None
    game: str
    shiny: bool = False
    trainer: str | None = "DEMO"
    summary: str = ""
    legal: bool | None = None
    home_tracker: str = ""
    dummy: bool = False


class Box(BaseModel):
    kind: str = "bank"
    id: int
    name: str
    slots: list[Pokemon | None]


# Synthetic display data only: never reads/writes the user's real Bank or Pokémon files.
SAMPLES = [
    ("Bulbasaur", 1, 12, ["Grass", "Poison"], "Modest", "Overgrow", "Sword / Shield"),
    ("Charmander", 4, 16, ["Fire"], "Timid", "Blaze", "Sword / Shield"),
    ("Squirtle", 7, 14, ["Water"], "Bold", "Torrent", "Sword / Shield"),
    ("Pikachu", 25, 28, ["Electric"], "Jolly", "Static", "Sword / Shield"),
    ("Eevee", 133, 20, ["Normal"], "Calm", "Adaptability", "Let's Go"),
    ("Gengar", 94, 45, ["Ghost", "Poison"], "Timid", "Cursed Body", "Scarlet / Violet"),
    ("Dragonite", 149, 55, ["Dragon", "Flying"], "Adamant", "Inner Focus", "Scarlet / Violet"),
    ("Lucario", 448, 36, ["Fighting", "Steel"], "Jolly", "Steadfast", "Sword / Shield"),
    ("Rowlet", 722, 10, ["Grass", "Flying"], "Adamant", "Overgrow", "Legends Arceus"),
    ("Mimikyu", 778, 32, ["Ghost", "Fairy"], "Jolly", "Disguise", "Scarlet / Violet"),
    ("Snorlax", 143, 40, ["Normal"], "Careful", "Immunity", "Sword / Shield"),
    ("Gardevoir", 282, 38, ["Psychic", "Fairy"], "Modest", "Synchronize", "Scarlet / Violet"),
]


def demo_boxes() -> list[Box]:
    boxes = [Box(id=i + 1, name=name, slots=[None] * 30)
             for i, name in enumerate(["Arrival box", "Ready to move", "Favorites", "Recovery"])]
    for i, (species, dex, level, types, nature, ability, game) in enumerate(SAMPLES):
        box, slot = (0, i) if i < 8 else (1, i - 8)
        boxes[box].slots[slot] = Pokemon(id=f"demo-{dex}", species=species, dex=dex,
            level=level, types=types, nature=nature, ability=ability, game=game, shiny=dex == 25)
    return boxes


class Trainer(BaseModel):
    ot: str = Field(min_length=1, max_length=12)
    tid: int = Field(ge=0, le=65535)
    sid: int = Field(ge=0, le=65535)
    language: int = Field(default=2, ge=1, le=10)
    gender: int = Field(default=0, ge=0, le=1)


class Move(BaseModel):
    box_id: int = Field(ge=1)
    slot: int = Field(ge=0, le=29)
    expected: str | None = None


class BoxName(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class TradeSelection(BaseModel):
    game: Literal["frlg", "lgpe", "swsh", "bdsp", "pla", "sv", "za"]
    entry_ids: list[str] = Field(min_length=1, max_length=6)


class TradeStage(TradeSelection):
    token: str = Field(min_length=64, max_length=64)


class TradeAction(BaseModel):
    version: int = Field(strict=True, ge=1)
    scenario: Literal["success", "disconnect", "failure"] = "success"
    fault_after: int = Field(strict=True, default=0, ge=0, le=5)


class USBStart(BaseModel):
    entry_id: str = Field(min_length=1,max_length=160)
    device: str = Field(min_length=1,max_length=200)
    code: str = Field(pattern=r"^[0-9]{8}$")
    request_id: str = Field(min_length=36,max_length=36)


class USBRecovery(BaseModel):
    resolve_without_confirmation: bool = Field(default=False, strict=True)


def create_app(frontend_dir: Path | None = None, *, data_dir: Path | None = None,
               mode: str | None = None) -> FastAPI:
    mode = mode or os.environ.get("PKMN_SBANK_MODE", "bank")
    if mode not in ("bank", "demo"):
        raise ValueError("PKMN_SBANK_MODE must be bank or demo")
    root = data_dir or Path(os.environ.get("POKELDN_DATA", str(Path.home() / ".local/share/pkmn-sbank"))) / "web-bank"
    store = BankStore(root)
    trading = SimulatedTrading(store)
    usb = LiveTrading(store)
    from pokeldn.app.sprites import SpriteCache
    sprites = SpriteCache(folder=root / "sprites")
    app = FastAPI(title="PkMn-SBank", version="0.5.0", description="Pi 5 Bank storage, simulated trading, and single Sword/Shield trades over USB ESP32-S3.")

    @app.exception_handler(StorageError)
    async def storage_error(request, error):
        return JSONResponse(status_code=error.status, content={"detail": str(error)})

    @app.exception_handler(BuilderError)
    async def builder_error(request, error):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(OSError)
    async def disk_error(request, error):
        return JSONResponse(status_code=503, content={"detail": "Storage is unavailable or full. The last committed snapshot is retained."})

    @app.middleware("http")
    async def writes(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if mode == "demo":
                return JSONResponse(status_code=403, content={"detail": "Demo mode is read-only."})
            origin = request.headers.get("origin")
            if request.headers.get("x-pkmn-sbank") != "1" or (origin and urlsplit(origin).netloc != request.headers.get("host")):
                return JSONResponse(status_code=403, content={"detail": "Use the website on this Pi to change Bank data."})
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        try:
            _command()
            pkhex = True
        except BuilderError:
            pkhex = False
        return {"status": "ok", "mode": mode, "hardware_connected": False, "pkhex_available": pkhex,
                "host_target": "Raspberry Pi 5"}

    @app.get("/api/boxes", response_model=list[Box])
    def boxes():
        return [*demo_boxes(), Box(**reserve_box())] if mode == "demo" else store.boxes()

    @app.get("/api/boxes/{box_id}", response_model=Box)
    def box(box_id: int):
        return next((b for b in boxes() if (b.id if isinstance(b, Box) else b["id"]) == box_id), None) or missing_box()

    @app.get("/api/settings")
    def settings():
        return {"trainer": None} if mode == "demo" else store.settings()

    @app.put("/api/settings/trainer")
    def trainer(value: Trainer):
        if value.language == 6 or value.ot.strip() != value.ot or any(ord(c) < 32 for c in value.ot):
            raise HTTPException(422, "Enter a valid trainer name and Pokémon language (language 6 is unused).")
        store.set_trainer(value.model_dump())
        return store.settings()

    @app.post("/api/import")
    async def import_file(request: Request, name: str = Query(min_length=1, max_length=120)):
        if name in (".", "..") or Path(name).name != name or "\\" in name or any(ord(c) < 32 for c in name):
            raise HTTPException(422, "Choose a plain file name.")
        if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
            raise HTTPException(415, "Upload a Pokémon file or save as application/octet-stream.")
        from pokeldn.app.bank import IMPORT_LIMIT
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > IMPORT_LIMIT:
                raise HTTPException(413, "The import limit is 64 MiB.")
            chunks.append(chunk)
        if not size:
            raise HTTPException(422, "The file is empty.")
        return await run_in_threadpool(store.import_file, name, b"".join(chunks))

    @app.post("/api/pokemon/{entry_id}/move")
    def move(entry_id: str, target: Move):
        store.move(entry_id, target.box_id, target.slot, target.expected)
        return {"ok": True}

    @app.patch("/api/boxes/{box_id}")
    def rename(box_id: int, value: BoxName):
        name = value.name.strip()
        if not name or any(ord(c) < 32 for c in name):
            raise HTTPException(422, "Enter a box name.")
        store.rename(box_id, name)
        return {"ok": True}

    @app.get("/api/pokemon/{entry_id}/export")
    def export(entry_id: str):
        if mode == "demo":
            raise HTTPException(404, "Demo mode has no stored Pokémon exports.")
        name, data = store.export(entry_id)
        return Response(data, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/sprites/{dex}")
    def sprite(dex: int, shiny: bool = False):
        if not 1 <= dex <= 2000:
            raise HTTPException(404, "Sprite not found")
        data = sprites.get(dex, shiny)
        if data is None:
            raise HTTPException(404, "Sprite unavailable offline")
        return Response(data, media_type="image/png")

    @app.get("/api/history")
    def history():
        return {"mode": mode, "entries": [] if mode == "demo" else store.history(),
                "message": "Bank and simulation operations only; no real trades have been performed."}

    @app.get("/api/backups")
    def backups():
        return [] if mode == "demo" else store.backups()

    @app.get("/api/backup")
    def backup():
        if mode == "demo":
            raise HTTPException(404, "Demo mode has no Bank backup.")
        path = store.backup_file()
        return FileResponse(path, media_type="application/zip", filename="pkmn-sbank-backup.zip",
                            background=BackgroundTask(path.unlink, missing_ok=True))

    @app.post("/api/backups/{revision_id}/restore")
    def restore(revision_id: str):
        store.restore(revision_id)
        return {"ok": True}

    @app.get("/api/trade/session")
    def trade_session():
        if mode == "demo":
            return {"mode": "demo", "games": [{"key": key, "name": name} for key, name in TARGETS.items()], "session": None}
        return trading.current()

    @app.post("/api/trade/preview")
    def trade_preview(value: TradeSelection):
        return trading.preview(value.game, value.entry_ids)

    @app.post("/api/trade/stage")
    def trade_stage(value: TradeStage):
        return trading.stage(value.game, value.entry_ids, value.token)

    @app.post("/api/trade/session/{session_id}/{action}")
    def trade_action(session_id: str, action: Literal["start", "advance", "resume", "cancel"], value: TradeAction):
        return trading.action(session_id, action, value.version, scenario=value.scenario, fault_after=value.fault_after)

    @app.get("/api/usb/status")
    def usb_status():
        if mode == "demo":
            return {"supported_host":False,"keys_available":False,"devices":[],"session":None,"logs":[]}
        return usb.current()

    @app.post("/api/usb/start")
    def usb_start(value: USBStart):
        return usb.start(value.entry_id,value.device,value.code,value.request_id)

    @app.post("/api/usb/{session_id}/stop")
    def usb_stop(session_id: str):
        return usb.cancel(session_id)

    @app.post("/api/usb/{session_id}/recover")
    def usb_recover(session_id: str,value: USBRecovery):
        return usb.recover(session_id,resolve=value.resolve_without_confirmation)

    @app.get("/api/{path:path}", include_in_schema=False)
    def unknown_api(path: str):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    frontend = frontend_dir or Path(os.environ.get("PKMN_SBANK_WEB_DIST",
        str(Path(__file__).resolve().parents[2] / "web" / "dist")))
    if (frontend / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="website")
    else:
        @app.get("/", include_in_schema=False)
        def build_help():
            return {"message": "Build web/ with npm ci && npm run build, then restart the API.", "mode": mode}
    return app


def missing_box():
    raise HTTPException(status_code=404, detail="Box not found")


app = create_app()
