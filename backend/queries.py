"""Query layer: turns the two cogs' raw session tables into the shapes the
dashboard API needs - leaderboards, top10s, the co-occurrence graph, and
the per-user year-in-review ("wrapped") stats.
"""
from datetime import datetime, timezone
from itertools import groupby
from typing import Dict, List, Optional, Tuple

from . import db
from .names import resolver
from .overlap import merge_pair_seconds, pairwise_overlap_seconds

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


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


def get_all_users(guild_id: int) -> List[dict]:
    users = [{"id": str(uid), "name": resolver.user(uid)} for uid in _all_user_ids(guild_id)]
    users.sort(key=lambda u: u["name"].lower())
    return users


def get_years(guild_id: int) -> List[int]:
    years = set()
    with db.voicelog_conn() as conn:
        years.update(r[0] for r in conn.execute(
            "SELECT DISTINCT CAST(strftime('%Y', start_time, 'unixepoch') AS INTEGER) "
            "FROM voice_sessions WHERE guild_id = ?", (guild_id,),
        ))
    with db.gamelog_conn() as conn:
        years.update(r[0] for r in conn.execute(
            "SELECT DISTINCT CAST(strftime('%Y', start_time, 'unixepoch') AS INTEGER) "
            "FROM sessions WHERE guild_id = ?", (guild_id,),
        ))
    return sorted(years, reverse=True)


def _year_bounds(year: int) -> Tuple[int, int]:
    start = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp())
    return start, end


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


def _voice_pairwise(guild_id: int, year_bounds: Optional[Tuple[int, int]] = None):
    sql = "SELECT channel_id, user_id, start_time, end_time FROM voice_sessions WHERE guild_id = ?"
    params: List = [guild_id]
    if year_bounds:
        sql += " AND start_time >= ? AND start_time < ?"
        params.extend(year_bounds)
    sql += " ORDER BY channel_id"
    with db.voicelog_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    rows = [(r["channel_id"], r["user_id"], r["start_time"], r["end_time"]) for r in rows]
    return _grouped_pairwise(rows, 0)


def _game_pairwise(guild_id: int, year_bounds: Optional[Tuple[int, int]] = None):
    sql = "SELECT game, user_id, start_time, end_time FROM sessions WHERE guild_id = ?"
    params: List = [guild_id]
    if year_bounds:
        sql += " AND start_time >= ? AND start_time < ?"
        params.extend(year_bounds)
    sql += " ORDER BY game"
    with db.gamelog_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
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


def _rank_of(guild_id: int, user_id: int, year_bounds: Tuple[int, int], table: str) -> Optional[dict]:
    """This user's 1-based rank (and the field of how many participants) on
    the given year's total-duration leaderboard for `voice_sessions` or
    `sessions`. None if the user has no rows that year.
    """
    conn_factory = db.voicelog_conn if table == "voice_sessions" else db.gamelog_conn
    with conn_factory() as conn:
        rows = conn.execute(
            f"SELECT user_id, SUM(duration) AS total FROM {table} "
            f"WHERE guild_id = ? AND start_time >= ? AND start_time < ? "
            f"GROUP BY user_id ORDER BY total DESC",
            (guild_id, *year_bounds),
        ).fetchall()
    for i, r in enumerate(rows):
        if r["user_id"] == user_id:
            return {"rank": i + 1, "of": len(rows), "seconds": r["total"]}
    return None


def _top_partner(pair_total: Dict[Tuple[int, int], int], user_id: int) -> Optional[Tuple[int, int]]:
    """(other_user_id, seconds) of user_id's highest-overlap pair, or None."""
    best = None
    for (a, b), secs in pair_total.items():
        if user_id not in (a, b):
            continue
        other = b if a == user_id else a
        if best is None or secs > best[1]:
            best = (other, secs)
    return best


def get_wrapped(guild_id: int, user_id: int, year: int) -> Optional[dict]:
    year_bounds = _year_bounds(year)
    ys, ye = year_bounds

    with db.voicelog_conn() as conn:
        voice_total = conn.execute(
            "SELECT COALESCE(SUM(duration),0) FROM voice_sessions "
            "WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ?",
            (guild_id, user_id, ys, ye),
        ).fetchone()[0]
        top_channel_row = conn.execute(
            "SELECT channel_id, SUM(duration) AS total FROM voice_sessions "
            "WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ? "
            "GROUP BY channel_id ORDER BY total DESC LIMIT 1",
            (guild_id, user_id, ys, ye),
        ).fetchone()
        longest_voice = conn.execute(
            "SELECT channel_id, start_time, duration FROM voice_sessions "
            "WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ? "
            "ORDER BY duration DESC LIMIT 1",
            (guild_id, user_id, ys, ye),
        ).fetchone()
        voice_months = conn.execute(
            "SELECT CAST(strftime('%m', start_time, 'unixepoch') AS INTEGER) AS m, SUM(duration) AS total "
            "FROM voice_sessions WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ? "
            "GROUP BY m",
            (guild_id, user_id, ys, ye),
        ).fetchall()
        voice_days = {r[0] for r in conn.execute(
            "SELECT DISTINCT date(start_time, 'unixepoch') FROM voice_sessions "
            "WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ?",
            (guild_id, user_id, ys, ye),
        )}

    with db.gamelog_conn() as conn:
        game_total = conn.execute(
            "SELECT COALESCE(SUM(duration),0) FROM sessions "
            "WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ?",
            (guild_id, user_id, ys, ye),
        ).fetchone()[0]
        top_games = conn.execute(
            "SELECT game, SUM(duration) AS total FROM sessions "
            "WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ? "
            "GROUP BY game ORDER BY total DESC LIMIT 5",
            (guild_id, user_id, ys, ye),
        ).fetchall()
        longest_game = conn.execute(
            "SELECT game, start_time, duration FROM sessions "
            "WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ? "
            "ORDER BY duration DESC LIMIT 1",
            (guild_id, user_id, ys, ye),
        ).fetchone()
        game_months = conn.execute(
            "SELECT CAST(strftime('%m', start_time, 'unixepoch') AS INTEGER) AS m, SUM(duration) AS total "
            "FROM sessions WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ? "
            "GROUP BY m",
            (guild_id, user_id, ys, ye),
        ).fetchall()
        game_days = {r[0] for r in conn.execute(
            "SELECT DISTINCT date(start_time, 'unixepoch') FROM sessions "
            "WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ?",
            (guild_id, user_id, ys, ye),
        )}

    if voice_total == 0 and game_total == 0:
        return None

    month_totals: Dict[int, int] = {}
    for m, total in voice_months:
        month_totals[m] = month_totals.get(m, 0) + total
    for m, total in game_months:
        month_totals[m] = month_totals.get(m, 0) + total
    busiest_month = max(month_totals.items(), key=lambda kv: kv[1]) if month_totals else None

    voice_pair_total, _ = _voice_pairwise(guild_id, year_bounds)
    game_pair_total, game_pair_breakdown = _game_pairwise(guild_id, year_bounds)

    top_voice_partner = _top_partner(voice_pair_total, user_id)
    top_game_partner = _top_partner(game_pair_total, user_id)

    top_game_partner_games = []
    if top_game_partner:
        pair_key = tuple(sorted((user_id, top_game_partner[0])))
        top_game_partner_games = sorted(
            game_pair_breakdown.get(pair_key, {}).items(), key=lambda kv: -kv[1]
        )[:3]

    return {
        "year": year,
        "user": {"id": str(user_id), "name": resolver.user(user_id)},
        "voice_seconds": voice_total,
        "game_seconds": game_total,
        "active_days": len(voice_days | game_days),
        "voice_rank": _rank_of(guild_id, user_id, year_bounds, "voice_sessions"),
        "game_rank": _rank_of(guild_id, user_id, year_bounds, "sessions"),
        "top_games": [{"game": r["game"], "seconds": r["total"]} for r in top_games],
        "top_voice_channel": (
            {"name": resolver.channel(top_channel_row["channel_id"]), "seconds": top_channel_row["total"]}
            if top_channel_row else None
        ),
        "top_voice_partner": (
            {"user_id": str(top_voice_partner[0]), "name": resolver.user(top_voice_partner[0]), "seconds": top_voice_partner[1]}
            if top_voice_partner else None
        ),
        "top_game_partner": (
            {
                "user_id": str(top_game_partner[0]),
                "name": resolver.user(top_game_partner[0]),
                "seconds": top_game_partner[1],
                "top_games": [{"game": g, "seconds": s} for g, s in top_game_partner_games],
            }
            if top_game_partner else None
        ),
        "longest_voice_session": (
            {
                "channel": resolver.channel(longest_voice["channel_id"]),
                "seconds": longest_voice["duration"],
                "date": longest_voice["start_time"],
            }
            if longest_voice else None
        ),
        "longest_game_session": (
            {
                "game": longest_game["game"],
                "seconds": longest_game["duration"],
                "date": longest_game["start_time"],
            }
            if longest_game else None
        ),
        "busiest_month": (
            {"name": MONTH_NAMES[busiest_month[0] - 1], "seconds": busiest_month[1]}
            if busiest_month else None
        ),
    }
