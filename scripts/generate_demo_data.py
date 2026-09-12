#!/usr/bin/env python3
"""Generate synthetic voicelog.sqlite3 / gamelog.sqlite3 files matching the
voicelog and gamelog cog schemas, so the dashboard can be exercised without
real Discord data. Also writes config/users.json and config/channels.json
name mappings for the generated IDs.

Data is shaped around a few overlapping friend "cliques" plus one bridge
user, so the relationship graph has visible, meaningful structure instead
of random noise.

Usage: python scripts/generate_demo_data.py
"""
import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"

GUILD_ID = 111111111111111111

USERS = [
    "Nova", "Kestrel", "Bramble", "Flick", "Juniper", "Pixel",
    "Rowan", "Sable", "Wisp", "Thistle", "Ozzy", "Mochi",
]
USER_IDS = {name: 200000000000000000 + i for i, name in enumerate(USERS)}

CHANNELS = ["General Voice", "Gaming Lounge", "Movie Night", "AFK"]
CHANNEL_IDS = {name: 300000000000000000 + i for i, name in enumerate(CHANNELS)}

# Overlapping friend groups. Mochi is a bridge who floats between all three.
CLIQUE_A = ["Nova", "Kestrel", "Bramble", "Flick"]          # Valorant squad
CLIQUE_B = ["Juniper", "Pixel", "Rowan"]                    # Minecraft crew
CLIQUE_C = ["Sable", "Wisp", "Thistle", "Ozzy"]              # Overwatch/Apex group
BRIDGE = "Mochi"

CLIQUE_GAMES = {
    "A": ["Valorant", "Apex Legends"],
    "B": ["Minecraft", "Stardew Valley"],
    "C": ["Overwatch 2", "Apex Legends", "Among Us"],
}
SOLO_GAMES = ["Elden Ring", "Balatro", "Hades II"]

CLIQUES = {"A": CLIQUE_A, "B": CLIQUE_B, "C": CLIQUE_C}
CLIQUE_WEIGHTS = [5, 4, 4]  # relative frequency of events per clique

now = datetime.now(timezone.utc)
start_of_range = now - timedelta(days=45)

voice_rows = []  # (guild_id, user_id, channel_id, start_time, end_time, duration)
game_rows = []   # (guild_id, user_id, game, start_time, end_time, duration)


def add_voice(user, channel, start, end):
    if end <= start:
        return
    voice_rows.append((
        GUILD_ID, USER_IDS[user], CHANNEL_IDS[channel],
        int(start.timestamp()), int(end.timestamp()), int((end - start).total_seconds()),
    ))


def add_game(user, game, start, end):
    if end <= start:
        return
    game_rows.append((
        GUILD_ID, USER_IDS[user], game,
        int(start.timestamp()), int(end.timestamp()), int((end - start).total_seconds()),
    ))


def random_event_start(day_offset: int) -> datetime:
    day = start_of_range + timedelta(days=day_offset)
    hour = random.choice([18, 19, 20, 21, 22])
    return day.replace(hour=hour, minute=random.randint(0, 59), second=0, microsecond=0)


def simulate_hangout(day_offset: int) -> None:
    clique_key = random.choices(list(CLIQUES), weights=CLIQUE_WEIGHTS)[0]
    members = list(CLIQUES[clique_key])
    if random.random() < 0.25:
        members.append(BRIDGE)
    # Not everyone in the clique shows up to every hangout.
    attendees = [m for m in members if random.random() < 0.75]
    if len(attendees) < 2:
        attendees = members[:2]

    channel = random.choice(["General Voice", "Gaming Lounge", "Movie Night"])
    start = random_event_start(day_offset)
    duration = timedelta(minutes=random.randint(45, 180))
    end = start + duration

    for member in attendees:
        # Stagger joins/leaves a bit so overlap isn't perfectly identical.
        join = start + timedelta(minutes=random.randint(0, 10))
        leave = end - timedelta(minutes=random.randint(0, 15))
        add_voice(member, channel, join, leave)

    if random.random() < 0.7 and len(attendees) >= 2:
        game = random.choice(CLIQUE_GAMES[clique_key])
        gstart = start + timedelta(minutes=random.randint(5, 15))
        gend = gstart + timedelta(minutes=random.randint(30, int(duration.total_seconds() // 60) - 10))
        for member in attendees:
            join = gstart + timedelta(minutes=random.randint(0, 5))
            leave = gend - timedelta(minutes=random.randint(0, 5))
            add_game(member, game, join, leave)


def simulate_solo_activity(day_offset: int) -> None:
    user = random.choice(USERS)
    game = random.choice(SOLO_GAMES + [g for games in CLIQUE_GAMES.values() for g in games])
    start = random_event_start(day_offset) + timedelta(hours=random.uniform(-2, 2))
    end = start + timedelta(minutes=random.randint(20, 150))
    add_game(user, game, start, end)

    if random.random() < 0.3:
        add_voice(user, "AFK", start, end)


for day_offset in range(45):
    for _ in range(random.randint(1, 3)):
        simulate_hangout(day_offset)
    for _ in range(random.randint(0, 2)):
        simulate_solo_activity(day_offset)


def write_voicelog_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "voicelog.sqlite3"
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            start_time INTEGER NOT NULL,
            end_time INTEGER NOT NULL,
            duration INTEGER NOT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO voice_sessions (guild_id, user_id, channel_id, start_time, end_time, duration) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        voice_rows,
    )
    conn.commit()
    conn.close()
    print(f"Wrote {len(voice_rows)} voice sessions to {path}")


def write_gamelog_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "gamelog.sqlite3"
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            game TEXT NOT NULL,
            start_time INTEGER NOT NULL,
            end_time INTEGER NOT NULL,
            duration INTEGER NOT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO sessions (guild_id, user_id, game, start_time, end_time, duration) VALUES (?, ?, ?, ?, ?, ?)",
        game_rows,
    )
    conn.commit()
    conn.close()
    print(f"Wrote {len(game_rows)} game sessions to {path}")


def write_name_maps() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    users_map = {str(uid): name for name, uid in USER_IDS.items()}
    channels_map = {str(cid): name for name, cid in CHANNEL_IDS.items()}
    (CONFIG_DIR / "users.json").write_text(json.dumps(users_map, indent=2))
    (CONFIG_DIR / "channels.json").write_text(json.dumps(channels_map, indent=2))
    print(f"Wrote {CONFIG_DIR / 'users.json'} and {CONFIG_DIR / 'channels.json'}")


if __name__ == "__main__":
    write_voicelog_db()
    write_gamelog_db()
    write_name_maps()
