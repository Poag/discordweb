"""Read-only SQLite connections to the voicelog / gamelog cog databases."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config


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
    try:
        yield conn
    finally:
        conn.close()
