"""FastAPI app: REST API over the voicelog/gamelog data, plus the static
dashboard frontend.

Run with: uvicorn backend.main:app --reload
"""
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from . import queries
from .config import ROOT

app = FastAPI(title="Voice/Game Dashboard")

FRONTEND_DIR = ROOT / "frontend"


def _resolve_guild(guild_id: Optional[int]) -> int:
    guilds = queries.get_guilds()
    if not guilds:
        raise HTTPException(404, "No data found in either database yet.")
    if guild_id is None:
        return guilds[0]
    if guild_id not in guilds:
        raise HTTPException(404, f"guild_id {guild_id} has no logged data.")
    return guild_id


@app.get("/api/guilds")
def api_guilds():
    return {"guilds": queries.get_guilds_with_names()}


@app.get("/api/overview")
def api_overview(guild_id: Optional[int] = None):
    gid = _resolve_guild(guild_id)
    return {"guild_id": str(gid), **queries.get_overview(gid)}


@app.get("/api/leaderboard")
def api_leaderboard(guild_id: Optional[int] = None, limit: int = Query(10, ge=1, le=100)):
    gid = _resolve_guild(guild_id)
    return {"guild_id": str(gid), "leaderboard": queries.get_leaderboard(gid, limit)}


@app.get("/api/voice/leaderboard")
def api_voice_leaderboard(guild_id: Optional[int] = None, limit: int = Query(10, ge=1, le=100)):
    gid = _resolve_guild(guild_id)
    return {"guild_id": str(gid), "leaderboard": queries.get_voice_leaderboard(gid, limit)}


@app.get("/api/voice/channels")
def api_voice_channels(guild_id: Optional[int] = None):
    gid = _resolve_guild(guild_id)
    return {"guild_id": str(gid), "channels": queries.get_voice_channels(gid)}


@app.get("/api/games")
def api_games(guild_id: Optional[int] = None):
    gid = _resolve_guild(guild_id)
    return {"guild_id": str(gid), "games": queries.get_games_list(gid)}


@app.get("/api/games/{game}/top10")
def api_game_top10(game: str, guild_id: Optional[int] = None):
    gid = _resolve_guild(guild_id)
    top = queries.get_game_top10(gid, game)
    if not top:
        raise HTTPException(404, f"No logged sessions for game {game!r}.")
    return {"guild_id": str(gid), "game": game, "top10": top}


@app.get("/api/graph")
def api_graph(guild_id: Optional[int] = None, min_seconds: int = Query(60, ge=0)):
    gid = _resolve_guild(guild_id)
    return {"guild_id": str(gid), **queries.get_graph(gid, min_seconds)}


@app.get("/api/users")
def api_users(guild_id: Optional[int] = None):
    gid = _resolve_guild(guild_id)
    return {"guild_id": str(gid), "users": queries.get_all_users(gid)}


@app.get("/api/years")
def api_years(guild_id: Optional[int] = None):
    gid = _resolve_guild(guild_id)
    return {"guild_id": str(gid), "years": queries.get_years(gid)}


@app.get("/api/wrapped")
def api_wrapped(user_id: int, year: int, guild_id: Optional[int] = None):
    gid = _resolve_guild(guild_id)
    wrapped = queries.get_wrapped(gid, user_id, year)
    if wrapped is None:
        raise HTTPException(404, f"No logged activity for that person in {year}.")
    return {"guild_id": str(gid), **wrapped}


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
