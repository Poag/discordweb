#!/usr/bin/env python3
"""Populate config/users.json and config/channels.json with real Discord
display names, using the same bot token the voicelog/gamelog cogs run
under (needs the Server Members privileged intent enabled, same as
gamelog itself).

Usage:
    DISCORD_BOT_TOKEN=... python scripts/fetch_discord_names.py --guild-id 123456789012345678

Only touches names for IDs it can resolve; run it again later to pick up
new members without losing manual edits to the JSON files.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://discord.com/api/v10"
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

VOICE_CHANNEL_TYPES = {2, 13}  # GUILD_VOICE, GUILD_STAGE_VOICE


def _get(token: str, path: str) -> object:
    req = urllib.request.Request(f"{API}{path}", headers={"Authorization": f"Bot {token}"})
    while True:
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = float(e.headers.get("Retry-After", "1"))
                time.sleep(retry_after)
                continue
            raise SystemExit(f"Discord API error {e.code} for {path}: {e.read().decode()}")


def fetch_members(token: str, guild_id: str) -> dict:
    names = {}
    after = "0"
    while True:
        batch = _get(token, f"/guilds/{guild_id}/members?limit=1000&after={after}")
        if not batch:
            break
        for member in batch:
            user = member["user"]
            display = member.get("nick") or user.get("global_name") or user["username"]
            names[user["id"]] = display
        after = batch[-1]["user"]["id"]
        if len(batch) < 1000:
            break
    return names


def fetch_voice_channels(token: str, guild_id: str) -> dict:
    channels = _get(token, f"/guilds/{guild_id}/channels")
    return {c["id"]: c["name"] for c in channels if c.get("type") in VOICE_CHANNEL_TYPES}


def merge_write(path: Path, new_entries: dict) -> None:
    existing = {}
    if path.exists():
        existing = json.loads(path.read_text())
    existing.update(new_entries)
    path.write_text(json.dumps(existing, indent=2, sort_keys=True))
    print(f"Wrote {len(existing)} entries ({len(new_entries)} updated) to {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guild-id", required=True)
    parser.add_argument("--token", default=os.environ.get("DISCORD_BOT_TOKEN"))
    args = parser.parse_args()

    if not args.token:
        sys.exit("Pass --token or set DISCORD_BOT_TOKEN.")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    users = fetch_members(args.token, args.guild_id)
    channels = fetch_voice_channels(args.token, args.guild_id)
    merge_write(CONFIG_DIR / "users.json", users)
    merge_write(CONFIG_DIR / "channels.json", channels)


if __name__ == "__main__":
    main()
