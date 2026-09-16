"""Query layer: turns the two cogs' raw session tables into the shapes the
dashboard API needs - leaderboards, top10s, the co-occurrence graph, and
the per-user year-in-review ("wrapped") stats.
"""
from collections import defaultdict
from datetime import datetime, timezone
from itertools import groupby
from typing import Dict, List, Optional, Tuple

from . import db
from .names import resolver
from .overlap import intersect_interval_lists, merge_pair_seconds, pairwise_overlap_seconds

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


def get_guilds_with_names() -> List[dict]:
    return [{"id": str(gid), "name": resolver.guild(gid)} for gid in get_guilds()]


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


def _game_pairwise(guild_id: int, year_bounds: Optional[Tuple[int, int]] = None, game: Optional[str] = None):
    sql = "SELECT game, user_id, start_time, end_time FROM sessions WHERE guild_id = ?"
    params: List = [guild_id]
    if year_bounds:
        sql += " AND start_time >= ? AND start_time < ?"
        params.extend(year_bounds)
    if game:
        sql += " AND game = ?"
        params.append(game)
    sql += " ORDER BY game"
    with db.gamelog_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    rows = [(r["game"], r["user_id"], r["start_time"], r["end_time"]) for r in rows]
    return _grouped_pairwise(rows, 0)


def _compound_sessions(
    guild_id: int, year_bounds: Optional[Tuple[int, int]] = None, game: Optional[str] = None
) -> List[Tuple[Tuple[str, int], int, int, int]]:
    """Per-user windows where a game session and a voice session overlap -
    "was playing game G while in voice channel C" - the actual "played
    together" signal, as opposed to _game_pairwise's "played the same
    game with overlapping session windows" (which says nothing about
    whether they were even in a call together). Returns rows of
    ((game, channel_id), user_id, start, end), sorted by the (game,
    channel_id) group key so they're ready for a groupby-based pairwise
    sweep, same shape convention as _grouped_pairwise expects.
    """
    game_sql = "SELECT user_id, game, start_time, end_time FROM sessions WHERE guild_id = ?"
    game_params: List = [guild_id]
    if year_bounds:
        game_sql += " AND start_time >= ? AND start_time < ?"
        game_params.extend(year_bounds)
    if game:
        game_sql += " AND game = ?"
        game_params.append(game)
    game_sql += " ORDER BY user_id, start_time"
    with db.gamelog_conn() as conn:
        game_rows = conn.execute(game_sql, game_params).fetchall()

    voice_sql = "SELECT user_id, channel_id, start_time, end_time FROM voice_sessions WHERE guild_id = ?"
    voice_params: List = [guild_id]
    if year_bounds:
        voice_sql += " AND start_time >= ? AND start_time < ?"
        voice_params.extend(year_bounds)
    voice_sql += " ORDER BY user_id, start_time"
    with db.voicelog_conn() as conn:
        voice_rows = conn.execute(voice_sql, voice_params).fetchall()

    games_by_user: Dict[int, List[Tuple[int, int, str]]] = defaultdict(list)
    for r in game_rows:
        games_by_user[r["user_id"]].append((r["start_time"], r["end_time"], r["game"]))
    voice_by_user: Dict[int, List[Tuple[int, int, int]]] = defaultdict(list)
    for r in voice_rows:
        voice_by_user[r["user_id"]].append((r["start_time"], r["end_time"], r["channel_id"]))

    compound = []
    for user_id, g_sessions in games_by_user.items():
        v_sessions = voice_by_user.get(user_id)
        if not v_sessions:
            continue
        for lo, hi, g, c in intersect_interval_lists(g_sessions, v_sessions):
            compound.append(((g, c), user_id, lo, hi))

    compound.sort(key=lambda row: row[0])
    return compound


def _together_data(
    guild_id: int, year_bounds: Optional[Tuple[int, int]] = None, game: Optional[str] = None
) -> Tuple[Dict[Tuple[int, int], int], Dict[Tuple[int, int], Dict[str, int]], Dict[int, int]]:
    """Genuine "played together" seconds - same game AND same voice
    channel AND overlapping time - for every pair, plus each person's own
    total (for node sizing/tooltips). Returns (pair -> total seconds,
    pair -> {"<game> in <channel>": seconds} breakdown, user_id -> total).
    """
    rows = _compound_sessions(guild_id, year_bounds, game)

    user_total: Dict[int, int] = defaultdict(int)
    for (_, _), uid, lo, hi in rows:
        user_total[uid] += hi - lo

    pair_total: Dict[Tuple[int, int], int] = {}
    pair_breakdown: Dict[Tuple[int, int], Dict[str, int]] = {}
    for key, group in groupby(rows, key=lambda r: r[0]):
        g, c = key
        sessions = [(r[1], r[2], r[3]) for r in group]
        pair_secs = pairwise_overlap_seconds(sessions)
        if not pair_secs:
            continue
        pair_total = merge_pair_seconds(pair_total, pair_secs)
        label = f"{g} in {resolver.channel(c)}"
        for pair, secs in pair_secs.items():
            pair_breakdown.setdefault(pair, {})[label] = secs

    return pair_total, pair_breakdown, dict(user_total)


def get_graph(guild_id: int, min_seconds: int = 60, game: Optional[str] = None) -> dict:
    """game restricts every "together" computation (edges, node totals, the
    per-edge game breakdown) to that one game rather than all games summed -
    the relationship graph's "just this game" filter. None (the default)
    keeps the original all-games view.
    """
    voice_total, voice_breakdown = _voice_pairwise(guild_id)
    game_total, game_breakdown = _game_pairwise(guild_id, game=game)
    together_total, together_breakdown, together_by_user = _together_data(guild_id, game=game)

    with db.voicelog_conn() as conn:
        voice_by_user = dict(conn.execute(
            "SELECT user_id, SUM(duration) FROM voice_sessions WHERE guild_id = ? GROUP BY user_id",
            (guild_id,),
        ).fetchall())
    with db.gamelog_conn() as conn:
        game_by_user_sql = "SELECT user_id, SUM(duration) FROM sessions WHERE guild_id = ?"
        game_by_user_params: List = [guild_id]
        if game:
            game_by_user_sql += " AND game = ?"
            game_by_user_params.append(game)
        game_by_user_sql += " GROUP BY user_id"
        game_by_user = dict(conn.execute(game_by_user_sql, game_by_user_params).fetchall())
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
    # together_seconds is defined as a subset of both voice and game time
    # (you can't have been "actually together" for longer than you were
    # in voice, or than you were in that game) - but the raw session rows
    # aren't guaranteed non-overlapping per user (a bot restart, a missed
    # disconnect event), which can occasionally let the geometric
    # intersection edge past voice_total/game_total's own independently-
    # computed numbers. Clamping keeps the three numbers honest relative
    # to each other without trying to perfectly relabel inherently
    # ambiguous overlapping data.
    user_ids = _all_user_ids(guild_id)
    nodes = [
        {
            "id": str(uid),
            "name": resolver.user(uid),
            "voice_seconds": voice_by_user.get(uid, 0),
            "game_seconds": game_by_user.get(uid, 0),
            "together_seconds": min(
                together_by_user.get(uid, 0), voice_by_user.get(uid, 0), game_by_user.get(uid, 0)
            ),
            "top_game": top_game_by_user.get(uid),
        }
        for uid in user_ids
    ]

    all_pairs = set(voice_total) | set(game_total) | set(together_total)
    edges = []
    for a, b in all_pairs:
        v = voice_total.get((a, b), 0)
        g = game_total.get((a, b), 0)
        tog = min(together_total.get((a, b), 0), v, g)
        if v + g < min_seconds:
            continue
        top_channels = sorted(
            voice_breakdown.get((a, b), {}).items(), key=lambda kv: -kv[1]
        )[:3]
        top_games = sorted(
            game_breakdown.get((a, b), {}).items(), key=lambda kv: -kv[1]
        )[:3]
        top_together = sorted(
            together_breakdown.get((a, b), {}).items(), key=lambda kv: -kv[1]
        )[:3]
        edges.append({
            "source": str(a),
            "target": str(b),
            "voice_seconds": v,
            "game_seconds": g,
            "together_seconds": tog,
            "top_channels": [{"name": resolver.channel(int(cid)), "seconds": s} for cid, s in top_channels],
            "top_games": [{"game": game, "seconds": s} for game, s in top_games],
            "top_together": [{"label": label, "seconds": s} for label, s in top_together],
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


def _build_month_series(rows: List[Tuple[str, str, int]], top_games: List[str]) -> dict:
    """Shapes (year_month, game, seconds) rows into the {games, months}
    timeline format shared by the guild-wide and per-user endpoints,
    folding anything outside top_games into "Other". top_games is fixed
    by the caller (by all-time or by-year total, whichever fits the
    scope) rather than recomputed per month, so a game's color/identity
    never shifts between months just because its rank did.
    """
    top_set = set(top_games)
    months: Dict[str, Dict[str, int]] = {}
    has_other = False
    for ym, game, total in rows:
        bucket = months.setdefault(ym, {})
        key = game if game in top_set else "Other"
        if key == "Other":
            has_other = True
        bucket[key] = bucket.get(key, 0) + total

    series = top_games + (["Other"] if has_other else [])

    month_rows = []
    for ym in sorted(months):
        year, month = (int(part) for part in ym.split("-"))
        bucket = months[ym]
        entry = {
            "month": ym,
            "label": f"{MONTH_NAMES[month - 1][:3]} {year}",
            "total_seconds": sum(bucket.values()),
        }
        for game in series:
            entry[game] = bucket.get(game, 0)
        month_rows.append(entry)

    return {"games": series, "months": month_rows}


def get_game_timeline(guild_id: int, top_n: int = 7) -> dict:
    """Monthly game-time mix across the whole guild's history. The
    frontend normalizes each month to 100% itself (a stacked percentage
    area chart), so this returns raw seconds per game per month rather
    than pre-computed shares.
    """
    with db.gamelog_conn() as conn:
        top_games = [
            row["game"]
            for row in conn.execute(
                "SELECT game, SUM(duration) AS total FROM sessions WHERE guild_id = ? "
                "GROUP BY game ORDER BY total DESC LIMIT ?",
                (guild_id, top_n),
            )
        ]
        rows = conn.execute(
            "SELECT strftime('%Y-%m', start_time, 'unixepoch') AS ym, game, SUM(duration) AS total "
            "FROM sessions WHERE guild_id = ? GROUP BY ym, game ORDER BY ym",
            (guild_id,),
        ).fetchall()

    return _build_month_series([(r["ym"], r["game"], r["total"]) for r in rows], top_games)


def get_user_game_timeline(guild_id: int, user_id: int, year: int, top_n: int = 5) -> dict:
    """Same shape as get_game_timeline, scoped to one person's one year -
    the "Your Year" version of the same ebb-and-flow chart.
    """
    ys, ye = _year_bounds(year)
    with db.gamelog_conn() as conn:
        top_games = [
            row["game"]
            for row in conn.execute(
                "SELECT game, SUM(duration) AS total FROM sessions "
                "WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ? "
                "GROUP BY game ORDER BY total DESC LIMIT ?",
                (guild_id, user_id, ys, ye, top_n),
            )
        ]
        rows = conn.execute(
            "SELECT strftime('%Y-%m', start_time, 'unixepoch') AS ym, game, SUM(duration) AS total "
            "FROM sessions WHERE guild_id = ? AND user_id = ? AND start_time >= ? AND start_time < ? "
            "GROUP BY ym, game ORDER BY ym",
            (guild_id, user_id, ys, ye),
        ).fetchall()

    return _build_month_series([(r["ym"], r["game"], r["total"]) for r in rows], top_games)
