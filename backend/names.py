"""Resolve Discord user/channel snowflake IDs to display names.

voicelog and gamelog each cache their own id -> display name mappings
directly in their SQLite databases (voicelog's ``user_names`` and
``channel_names``, gamelog's ``user_names``), refreshed automatically as
members are seen - see PogCogs' README "Relationship data" section. This
reads straight from those tables rather than a separate export step, so
names stay current without a manual re-run. Where both cogs have a row
for the same user, whichever was updated more recently wins.

Cached in memory with a short TTL rather than re-querying per lookup,
since a single API response typically resolves many IDs in a row.
Unmapped IDs (nothing logged yet, or an older cog build predating these
tables) fall back to a short, stable placeholder rather than erroring -
and a whole database being temporarily unreadable degrades the same way
rather than breaking every other endpoint that resolves a name.
"""
import sqlite3
import time
from typing import Dict, Tuple

from . import db

_CACHE_TTL_SECONDS = 30


class NameResolver:
    def __init__(self) -> None:
        self._users: Dict[int, str] = {}
        self._channels: Dict[int, str] = {}
        self._loaded_at = 0.0

    def _ensure_fresh(self) -> None:
        if time.monotonic() - self._loaded_at < _CACHE_TTL_SECONDS:
            return
        self._reload()

    def _reload(self) -> None:
        users: Dict[int, Tuple[str, int]] = {}
        channels: Dict[int, str] = {}

        try:
            with db.voicelog_conn() as conn:
                for user_id, name, updated_at in conn.execute(
                    "SELECT user_id, name, updated_at FROM user_names"
                ):
                    users[user_id] = (name, updated_at)
                for channel_id, name in conn.execute(
                    "SELECT channel_id, name FROM channel_names"
                ):
                    channels[channel_id] = name
        except (FileNotFoundError, sqlite3.OperationalError):
            pass  # missing file, or an older cog build predating these tables

        try:
            with db.gamelog_conn() as conn:
                for user_id, name, updated_at in conn.execute(
                    "SELECT user_id, name, updated_at FROM user_names"
                ):
                    if user_id not in users or updated_at >= users[user_id][1]:
                        users[user_id] = (name, updated_at)
        except (FileNotFoundError, sqlite3.OperationalError):
            pass

        self._users = {user_id: name for user_id, (name, _) in users.items()}
        self._channels = channels
        self._loaded_at = time.monotonic()

    def user(self, user_id: int) -> str:
        self._ensure_fresh()
        return self._users.get(user_id, f"User {user_id % 10000:04d}")

    def channel(self, channel_id: int) -> str:
        self._ensure_fresh()
        return self._channels.get(channel_id, f"channel-{channel_id % 10000:04d}")


resolver = NameResolver()
