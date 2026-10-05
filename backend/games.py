"""Picks a single display spelling for each canonical game.

gamelog's `sessions.game` column holds whatever Discord's Rich Presence
reports as the activity name at the moment a session starts - not
guaranteed consistent for the same game across platforms or sessions (a
real example: "Star Wars Zero Company" vs "STAR WARS Zero Company(TM)").
Every query that groups or filters by game normalizes through
`db.normalize_game_key` (registered as the SQL function `game_key`) so
those variants merge into one bucket instead of silently fragmenting into
separate "games" throughout the dashboard - and, more subtly, so two
people whose clients logged different spellings of the same game still
show up as having played it together.

This module only answers the other half of that: once rows are grouped
by key, what display string to show for it. Picks whichever raw spelling
has the most total logged seconds, on the theory that's the one most
people's clients are actually reporting - with a couple of tie-breakers
(no stray whitespace, not ALL-CAPS/all-lowercase) so two spellings with
near-identical playtime don't come down to SQLite's arbitrary row order,
which can otherwise pick the messiest-looking variant just because it
happened to sort first.
"""
import sqlite3
import time
from typing import Dict, Tuple

from . import db

_CACHE_TTL_SECONDS = 30


def _quality(raw: str, total: int) -> Tuple[int, bool, bool]:
    looks_clean = raw == raw.strip()
    looks_proper_case = not raw.isupper() and not raw.islower()
    return (total, looks_clean, looks_proper_case)


class GameNameResolver:
    def __init__(self) -> None:
        self._display: Dict[str, str] = {}  # normalize_game_key(name) -> display spelling
        self._loaded_at = 0.0

    def _ensure_fresh(self) -> None:
        if time.monotonic() - self._loaded_at < _CACHE_TTL_SECONDS:
            return
        self._reload()

    def _reload(self) -> None:
        best: Dict[str, Tuple[int, bool, bool]] = {}
        display: Dict[str, str] = {}
        try:
            with db.gamelog_conn() as conn:
                rows = conn.execute(
                    "SELECT game, SUM(duration) AS total FROM sessions GROUP BY game"
                ).fetchall()
        except (FileNotFoundError, sqlite3.OperationalError):
            rows = []  # missing file, or no sessions table yet

        for row in rows:
            key = db.normalize_game_key(row["game"])
            score = _quality(row["game"], row["total"] or 0)
            if key not in best or score > best[key]:
                best[key] = score
                display[key] = row["game"]

        self._display = display
        self._loaded_at = time.monotonic()

    def display(self, name: str) -> str:
        """name may be a raw session spelling or an already-normalized
        key (normalize_game_key is idempotent, so either works)."""
        self._ensure_fresh()
        return self._display.get(db.normalize_game_key(name), name)


resolver = GameNameResolver()
