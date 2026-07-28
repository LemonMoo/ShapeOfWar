"""Save/load games. Each save is a slot on disk identified by a short id:
  saves/<id>.pkl   the pickled World (factions, regions, grids, everything)
  saves/<id>.json  lightweight metadata (species, realm name, created date)

Keeping metadata in a tiny separate JSON file means listing saves for the
Load Game menu doesn't require unpickling every (multi-megabyte) World just
to read a name off it.
"""
import json
import pickle
import sys
import uuid
from datetime import datetime
from pathlib import Path


def _app_root():
    """Where "saves/" lives. A PyInstaller --onefile .exe unpacks itself into
    a throwaway temp dir every launch (deleted on exit) and __file__ resolves
    inside *that*, not the real install — so saves written relative to
    __file__ would vanish the moment the game closes. sys.executable, by
    contrast, is always the actual persistent .exe path when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


SAVE_DIR = _app_root() / "saves"


def _world_path(save_id):
    return SAVE_DIR / f"{save_id}.pkl"


def _meta_path(save_id):
    return SAVE_DIR / f"{save_id}.json"


def new_save_id():
    return uuid.uuid4().hex[:12]


def list_saves():
    """All saves on disk, newest first: [{"id", "species", "name", "created_at"}, ...]."""
    if not SAVE_DIR.exists():
        return []
    saves = []
    for meta_file in SAVE_DIR.glob("*.json"):
        if not _world_path(meta_file.stem).exists():
            continue        # metadata with no matching world file — ignore
        try:
            meta = json.loads(meta_file.read_text())
        except (OSError, ValueError):
            continue
        meta["id"] = meta_file.stem
        saves.append(meta)
    saves.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return saves


def has_save():
    return bool(list_saves())


def save_game(world, save_id, created_at=None):
    """Save `world` into `save_id`'s slot, creating it if it doesn't exist
    yet. Pass the slot's existing `created_at` on repeat saves so the
    displayed creation date doesn't change every time you save; leave it
    None only the first time a slot is written."""
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    if created_at is None:
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    player = (world.factions[world.player_faction_idx]
              if world.player_faction_idx is not None else None)
    meta = {
        "species": player.meta["species"] if player else "?",
        "name": player.name if player else "Unnamed World",
        "created_at": created_at,
    }

    tmp_path = _world_path(save_id).with_suffix(".tmp")
    with open(tmp_path, "wb") as f:
        pickle.dump(world, f)
    tmp_path.replace(_world_path(save_id))     # never leaves a half-written save
    _meta_path(save_id).write_text(json.dumps(meta))
    return created_at


def load_game(save_id):
    with open(_world_path(save_id), "rb") as f:
        world = pickle.load(f)
    # Schema migrations for worlds saved by older builds. Imported here rather
    # than at module scope: resources.py imports this module for _app_root, so
    # a top-level import would be circular.
    from app.world.resources import migrate_legacy_overflow
    migrate_legacy_overflow(world)
    return world


def delete_save(save_id):
    """Remove a save slot's world + metadata files. Missing files (already
    deleted, or a metadata-only stub) are ignored rather than raising."""
    for path in (_world_path(save_id), _meta_path(save_id)):
        path.unlink(missing_ok=True)
