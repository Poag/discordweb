"""Resolve Discord user/channel snowflake IDs to display names.

The two cogs only ever log raw IDs, so name resolution is external to
them. This module reads flat JSON mapping files (id string -> name),
generated either by scripts/generate_demo_data.py for the demo, or by
scripts/fetch_discord_names.py against a real bot token + guild.
Unmapped IDs fall back to a short, stable placeholder rather than erroring.
"""
import json
from pathlib import Path
from typing import Dict

from . import config


def _load(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


class NameResolver:
    def __init__(self) -> None:
        self._users = _load(config.USERS_FILE)
        self._channels = _load(config.CHANNELS_FILE)

    def user(self, user_id: int) -> str:
        return self._users.get(str(user_id), f"User {user_id % 10000:04d}")

    def channel(self, channel_id: int) -> str:
        return self._channels.get(str(channel_id), f"channel-{channel_id % 10000:04d}")


resolver = NameResolver()
