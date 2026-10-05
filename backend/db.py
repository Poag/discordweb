"""Read-only SQLite connections to the voicelog / gamelog cog databases."""
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config

_TRADEMARK_CHARS = str.maketrans("", "", "™®©")  # (TM) (R) (C)


def normalize_game_key(name: str) -> str:
    """Comparison key for deduping game names that differ only in
    trademark symbols, case, or whitespace (seen in practice: "Star Wars
    Zero Company" vs "STAR WARS Zero Company(TM)") - Discord's own Rich
    Presence activity name for a game isn't guaranteed consistent across
    platforms/sessions, so gamelog's `sessions.game` column can end up
    with several spellings of what is, to a person looking at the
    dashboard, obviously the same game. Registered as a SQL function
    (game_key) on gamelog connections below so every query that groups or
    filters by game can use it directly, idempotent (normalizing an
    already-normalized key is a no-op) so it's also safe to call on a
    value that's already a key.
    """
    cleaned = name.translate(_TRADEMARK_CHARS)
    return re.sub(r"\s+", " ", cleaned).strip().casefold()


def _connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(
            f"Database not found at {path}. Point VOICELOG_DB / GAMELOG_DB at your "
            f"Red-DiscordBot cog data files, or run scripts/generate_demo_data.py."
        )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def voicelog_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect_ro(config.VOICELOG_DB)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def gamelog_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect_ro(config.GAMELOG_DB)
    conn.create_function("game_key", 1, normalize_game_key, deterministic=True)
    try:
        yield conn
    finally:
        conn.close()
