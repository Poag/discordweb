"""Query layer: turns the two cogs' raw session tables into the shapes the
dashboard API needs - leaderboards, top10s, and the co-occurrence graph.
"""
from itertools import groupby
from typing import Dict, List, Optional, Tuple

from . import db
from .names import resolver
from .overlap import merge_pair_seconds, pairwise_overlap_seconds


def get_guilds() -> List[int]:
    guilds = set()
    with db.voicelog_conn() as conn:
        guilds.update(r[0] for r in conn.execute("SELECT DISTINCT guild_id FROM voice_sessions"))
    with db.gamelog_conn() as conn:
        guilds.update(r[0] for r in conn.execute("SELECT DISTINCT guild_id FROM sessions"))
    return sorted(guilds)


def get_overview(guild_id: int) -> dict:
    with db.voicelog_conn() as conn:
        voice_total, voice_users, voice_min, voice_max = conn.execute(
            "SELECT COALESCE(SUM(duration),0), COUNT(DISTINCT user_id), MIN(start_time), MAX(end_time) "
            "FROM voice_sessions WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        channel_count = conn.execute(
            "SELECT COUNT(DISTINCT channel_id) FROM voice_sessions WHERE guild_id = ?", (guild_id,)
        ).fetchone()[0]

    with db.gamelog_conn() as conn:
        game_total, game_users, game_count, game_min, game_max = conn.execute(
            "SELECT COALESCE(SUM(duration),0), COUNT(DISTINCT user_id), COUNT(DISTINCT game), "
            "MIN(start_time), MAX(end_time) FROM sessions WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()

    mins = [m for m in (voice_min, game_min) if m is not None]
    maxs = [m for m in (voice_max, game_max) if m is not None]

    return {
        "voice_seconds": voice_total,
        "voice_users": voice_users,
        "voice_channels": channel_count,
        "game_seconds": game_total,
        "game_users": game_users,
        "game_count": game_count,
        "unique_users": len(_all_user_ids(guild_id)),
        "first_seen": min(mins) if mins else None,
        "last_seen": max(maxs) if maxs else None,
    }


def _all_user_ids(guild_id: int) -> set:
    ids = set()
    with db.voicelog_conn() as conn:
        ids.update(r[0] for r in conn.execute(
            "SELECT DISTINCT user_id FROM voice_sessions WHERE guild_id = ?", (guild_id,)
        ))
    with db.gamelog_conn() as conn:
        ids.update(r[0] for r in conn.execute(
            "SELECT DISTINCT user_id FROM sessions WHERE guild_id = ?", (guild_id,)
        ))
    return ids


def get_leaderboard(guild_id: int, limit: int = 10) -> List[dict]:
    with db.gamelog_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, SUM(duration) AS total FROM sessions WHERE guild_id = ? "
            "GROUP BY user_id ORDER BY total DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()
    return [
        {"rank": i + 1, "user_id": str(r["user_id"]), "name": resolver.user(r["user_id"]), "seconds": r["total"]}
        for i, r in enumerate(rows)
    ]


def get_voice_leaderboard(guild_id: int, limit: int = 10) -> List[dict]:
    with db.voicelog_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, SUM(duration) AS total FROM voice_sessions WHERE guild_id = ? "
            "GROUP BY user_id ORDER BY total DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()
    return [
        {"rank": i + 1, "user_id": str(r["user_id"]), "name": resolver.user(r["user_id"]), "seconds": r["total"]}
        for i, r in enumerate(rows)
    ]


def get_games_list(guild_id: int) -> List[dict]:
    with db.gamelog_conn() as conn:
        rows = conn.execute(
            "SELECT game, SUM(duration) AS total, COUNT(DISTINCT user_id) AS players "
            "FROM sessions WHERE guild_id = ? GROUP BY game ORDER BY total DESC",
            (guild_id,),
        ).fetchall()
    return [{"game": r["game"], "seconds": r["total"], "players": r["players"]} for r in rows]


def get_game_top10(guild_id: int, game: str) -> List[dict]:
    with db.gamelog_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, SUM(duration) AS total FROM sessions WHERE guild_id = ? AND game = ? "
            "GROUP BY user_id ORDER BY total DESC LIMIT 10",
            (guild_id, game),
        ).fetchall()
    return [
        {"rank": i + 1, "user_id": str(r["user_id"]), "name": resolver.user(r["user_id"]), "seconds": r["total"]}
        for i, r in enumerate(rows)
    ]


def get_voice_channels(guild_id: int) -> List[dict]:
    with db.voicelog_conn() as conn:
        rows = conn.execute(
            "SELECT channel_id, SUM(duration) AS total, COUNT(DISTINCT user_id) AS users "
            "FROM voice_sessions WHERE guild_id = ? GROUP BY channel_id ORDER BY total DESC",
            (guild_id,),
        ).fetchall()
    return [
        {"channel_id": str(r["channel_id"]), "name": resolver.channel(r["channel_id"]), "seconds": r["total"], "users": r["users"]}
        for r in rows
    ]


def _grouped_pairwise(
    rows: List[Tuple], group_key_index: int
) -> Tuple[Dict[Tuple[int, int], int], Dict[Tuple[int, int], Dict[str, int]]]:
    """rows: (group_key, user_id, start_time, end_time), pre-sorted by group_key.
    Returns (total pair->seconds, pair->{group_key: seconds}) for breakdown/tooltips.
    """
    total: Dict[Tuple[int, int], int] = {}
    breakdown: Dict[Tuple[int, int], Dict[str, int]] = {}

    for key, group in groupby(rows, key=lambda r: r[group_key_index]):
        sessions = [(r[1], r[2], r[3]) for r in group]
        pair_secs = pairwise_overlap_seconds(sessions)
        if not pair_secs:
            continue
        total = merge_pair_seconds(total, pair_secs)
        for pair, secs in pair_secs.items():
            breakdown.setdefault(pair, {})[str(key)] = secs

    return total, breakdown


def _voice_pairwise(guild_id: int):
    with db.voicelog_conn() as conn:
        rows = conn.execute(
            "SELECT channel_id, user_id, start_time, end_time FROM voice_sessions "
            "WHERE guild_id = ? ORDER BY channel_id",
            (guild_id,),
        ).fetchall()
    rows = [(r["channel_id"], r["user_id"], r["start_time"], r["end_time"]) for r in rows]
    return _grouped_pairwise(rows, 0)


def _game_pairwise(guild_id: int):
    with db.gamelog_conn() as conn:
        rows = conn.execute(
            "SELECT game, user_id, start_time, end_time FROM sessions "
            "WHERE guild_id = ? ORDER BY game",
            (guild_id,),
        ).fetchall()
    rows = [(r["game"], r["user_id"], r["start_time"], r["end_time"]) for r in rows]
    return _grouped_pairwise(rows, 0)


def get_graph(guild_id: int, min_seconds: int = 60) -> dict:
    voice_total, voice_breakdown = _voice_pairwise(guild_id)
    game_total, game_breakdown = _game_pairwise(guild_id)

    with db.voicelog_conn() as conn:
        voice_by_user = dict(conn.execute(
            "SELECT user_id, SUM(duration) FROM voice_sessions WHERE guild_id = ? GROUP BY user_id",
            (guild_id,),
        ).fetchall())
    with db.gamelog_conn() as conn:
        game_by_user = dict(conn.execute(
            "SELECT user_id, SUM(duration) FROM sessions WHERE guild_id = ? GROUP BY user_id",
            (guild_id,),
        ).fetchall())
        top_game_by_user = {}
        for row in conn.execute(
            "SELECT user_id, game, SUM(duration) AS total FROM sessions WHERE guild_id = ? "
            "GROUP BY user_id, game ORDER BY user_id, total DESC",
            (guild_id,),
        ).fetchall():
            top_game_by_user.setdefault(row["user_id"], row["game"])

    # IDs are Discord snowflakes (64-bit) - they overflow JS's safe integer
    # range (2^53), so every ID that crosses the API boundary must be a
    # string or it will silently corrupt (and collide) once JSON.parse'd.
    user_ids = _all_user_ids(guild_id)
    nodes = [
        {
            "id": str(uid),
            "name": resolver.user(uid),
            "voice_seconds": voice_by_user.get(uid, 0),
            "game_seconds": game_by_user.get(uid, 0),
            "top_game": top_game_by_user.get(uid),
        }
        for uid in user_ids
    ]

    all_pairs = set(voice_total) | set(game_total)
    edges = []
    for a, b in all_pairs:
        v = voice_total.get((a, b), 0)
        g = game_total.get((a, b), 0)
        if v + g < min_seconds:
            continue
        top_channels = sorted(
            voice_breakdown.get((a, b), {}).items(), key=lambda kv: -kv[1]
        )[:3]
        top_games = sorted(
            game_breakdown.get((a, b), {}).items(), key=lambda kv: -kv[1]
        )[:3]
        edges.append({
            "source": str(a),
            "target": str(b),
            "voice_seconds": v,
            "game_seconds": g,
            "top_channels": [{"name": resolver.channel(int(cid)), "seconds": s} for cid, s in top_channels],
            "top_games": [{"game": game, "seconds": s} for game, s in top_games],
        })

    return {"nodes": nodes, "edges": edges}
