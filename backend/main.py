"""FastAPI app: REST API over the voicelog/gamelog data, plus the static
dashboard frontend.

Run with: uvicorn backend.main:app --reload
"""
from typing import Optional, Set

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import queries
from .auth import get_allowed_guilds, router as auth_router
from .config import AUTH_ENABLED, ROOT, SESSION_SECRET

app = FastAPI(title="Voice/Game Dashboard")

if AUTH_ENABLED:
    # Signed session cookie, not a server-side store - fine for what it
    # holds (Discord user id/name/avatar + guild id list, all already
    # visible on the user's own Discord profile). 7-day expiry so a stale
    # guild-membership snapshot (someone who left a server) can't linger
    # indefinitely without forcing a re-login.
    app.add_middleware(
        SessionMiddleware, secret_key=SESSION_SECRET, max_age=7 * 24 * 3600, same_site="lax"
    )
    app.include_router(auth_router)

FRONTEND_DIR = ROOT / "frontend"


@app.get("/api/me")
def api_me(request: Request):
    if not AUTH_ENABLED:
        return {"auth_enabled": False}
    user = request.session.get("user")
    if not user:
        return {"auth_enabled": True, "authenticated": False}
    return {"auth_enabled": True, "authenticated": True, "user": user}


def _resolve_guild(guild_id: Optional[int], allowed: Optional[Set[int]]) -> int:
    guilds = queries.get_guilds()
    if allowed is not None:
        guilds = [g for g in guilds if g in allowed]
    if not guilds:
        raise HTTPException(
            404,
            "No data found in either database yet."
            if allowed is None
            else "You're not a member of any server this dashboard logs.",
        )
    if guild_id is None:
        return guilds[0]
    if guild_id not in guilds:
        raise HTTPException(404, f"guild_id {guild_id} has no logged data, or you don't have access to it.")
    return guild_id


@app.get("/api/guilds")
def api_guilds(allowed: Optional[Set[int]] = Depends(get_allowed_guilds)):
    guilds = queries.get_guilds_with_names()
    if allowed is not None:
        guilds = [g for g in guilds if int(g["id"]) in allowed]
    return {"guilds": guilds}


@app.get("/api/overview")
def api_overview(guild_id: Optional[int] = None, allowed: Optional[Set[int]] = Depends(get_allowed_guilds)):
    gid = _resolve_guild(guild_id, allowed)
    return {"guild_id": str(gid), **queries.get_overview(gid)}


@app.get("/api/leaderboard")
def api_leaderboard(
    guild_id: Optional[int] = None,
    limit: int = Query(10, ge=1, le=100),
    allowed: Optional[Set[int]] = Depends(get_allowed_guilds),
):
    gid = _resolve_guild(guild_id, allowed)
    return {"guild_id": str(gid), "leaderboard": queries.get_leaderboard(gid, limit)}


@app.get("/api/voice/leaderboard")
def api_voice_leaderboard(
    guild_id: Optional[int] = None,
    limit: int = Query(10, ge=1, le=100),
    allowed: Optional[Set[int]] = Depends(get_allowed_guilds),
):
    gid = _resolve_guild(guild_id, allowed)
    return {"guild_id": str(gid), "leaderboard": queries.get_voice_leaderboard(gid, limit)}


@app.get("/api/voice/channels")
def api_voice_channels(guild_id: Optional[int] = None, allowed: Optional[Set[int]] = Depends(get_allowed_guilds)):
    gid = _resolve_guild(guild_id, allowed)
    return {"guild_id": str(gid), "channels": queries.get_voice_channels(gid)}


@app.get("/api/games")
def api_games(guild_id: Optional[int] = None, allowed: Optional[Set[int]] = Depends(get_allowed_guilds)):
    gid = _resolve_guild(guild_id, allowed)
    return {"guild_id": str(gid), "games": queries.get_games_list(gid)}


@app.get("/api/games/timeline")
def api_games_timeline(
    guild_id: Optional[int] = None,
    top_n: int = Query(7, ge=1, le=8),
    allowed: Optional[Set[int]] = Depends(get_allowed_guilds),
):
    gid = _resolve_guild(guild_id, allowed)
    return {"guild_id": str(gid), **queries.get_game_timeline(gid, top_n)}


@app.get("/api/games/{game}/top10")
def api_game_top10(game: str, guild_id: Optional[int] = None, allowed: Optional[Set[int]] = Depends(get_allowed_guilds)):
    gid = _resolve_guild(guild_id, allowed)
    top = queries.get_game_top10(gid, game)
    if not top:
        raise HTTPException(404, f"No logged sessions for game {game!r}.")
    return {"guild_id": str(gid), "game": game, "top10": top}


@app.get("/api/graph")
def api_graph(
    guild_id: Optional[int] = None,
    min_seconds: int = Query(60, ge=0),
    allowed: Optional[Set[int]] = Depends(get_allowed_guilds),
):
    gid = _resolve_guild(guild_id, allowed)
    return {"guild_id": str(gid), **queries.get_graph(gid, min_seconds)}


@app.get("/api/users")
def api_users(guild_id: Optional[int] = None, allowed: Optional[Set[int]] = Depends(get_allowed_guilds)):
    gid = _resolve_guild(guild_id, allowed)
    return {"guild_id": str(gid), "users": queries.get_all_users(gid)}


@app.get("/api/years")
def api_years(guild_id: Optional[int] = None, allowed: Optional[Set[int]] = Depends(get_allowed_guilds)):
    gid = _resolve_guild(guild_id, allowed)
    return {"guild_id": str(gid), "years": queries.get_years(gid)}


@app.get("/api/wrapped")
def api_wrapped(
    user_id: int,
    year: int,
    guild_id: Optional[int] = None,
    allowed: Optional[Set[int]] = Depends(get_allowed_guilds),
):
    gid = _resolve_guild(guild_id, allowed)
    wrapped = queries.get_wrapped(gid, user_id, year)
    if wrapped is None:
        raise HTTPException(404, f"No logged activity for that person in {year}.")
    return {"guild_id": str(gid), **wrapped}


@app.get("/api/wrapped/timeline")
def api_wrapped_timeline(
    user_id: int,
    year: int,
    guild_id: Optional[int] = None,
    top_n: int = Query(5, ge=1, le=8),
    allowed: Optional[Set[int]] = Depends(get_allowed_guilds),
):
    gid = _resolve_guild(guild_id, allowed)
    return {"guild_id": str(gid), **queries.get_user_game_timeline(gid, user_id, year, top_n)}


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
