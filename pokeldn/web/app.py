"""Read-only demo API and same-origin production frontend for PkMn-SBank."""
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


class Pokemon(BaseModel):
    id: str
    species: str
    dex: int
    level: int
    types: list[str]
    nature: str
    ability: str
    game: str
    shiny: bool = False
    trainer: str = "DEMO"


class Box(BaseModel):
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


def create_app(frontend_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="PkMn-SBank", version="0.1.0", description="Read-only website demo; no hardware control.")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "demo", "hardware_connected": False}

    @app.get("/api/boxes", response_model=list[Box])
    def boxes():
        return demo_boxes()

    @app.get("/api/boxes/{box_id}", response_model=Box)
    def box(box_id: int):
        return next((box for box in demo_boxes() if box.id == box_id), None) or missing_box()

    @app.get("/api/history")
    def history():
        return {"mode": "demo", "entries": [], "message": "No real transfers have been performed."}

    # Register /api fallback before StaticFiles so unknown API paths never return HTML.
    @app.get("/api/{path:path}", include_in_schema=False)
    def unknown_api(path: str):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    frontend = frontend_dir or Path(os.environ.get("PKMN_SBANK_WEB_DIST",
        str(Path(__file__).resolve().parents[2] / "web" / "dist")))
    if (frontend / "index.html").is_file():
        # Hash navigation means StaticFiles can enforce traversal and missing-asset checks.
        app.mount("/", StaticFiles(directory=frontend, html=True), name="website")
    else:
        @app.get("/", include_in_schema=False)
        def build_help():
            return {"message": "Build web/ with npm ci && npm run build, then restart the API.", "mode": "demo"}
    return app


def missing_box():
    raise HTTPException(status_code=404, detail="Box not found")


app = create_app()
