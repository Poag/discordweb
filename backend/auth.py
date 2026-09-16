"""Discord OAuth2 login: restricts each viewer to the guilds they're
actually a member of on Discord, rather than everyone seeing every guild
the bot logs.

Only active when config.AUTH_ENABLED (DISCORD_CLIENT_ID/SECRET/REDIRECT_URI
are all set) - with none of that configured, get_allowed_guilds() always
returns None ("no restriction") and this router is never mounted, so the
app behaves exactly as it did before auth existed. That keeps the local
demo-data quickstart working with zero setup.
"""
import secrets
from typing import Optional, Set
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import config

router = APIRouter()

DISCORD_API = "https://discord.com/api/v10"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = f"{DISCORD_API}/oauth2/token"
# "identify" for the username/avatar shown in the topbar, "guilds" for the
# membership list every /api endpoint filters against - deliberately not
# "guilds.members.read" (which needs per-guild approval and isn't needed
# here: we only care whether the user is in a guild, not their roles).
SCOPE = "identify guilds"


def get_allowed_guilds(request: Request) -> Optional[Set[int]]:
    """None means "no restriction" (auth disabled). Otherwise the set of
    guild_ids this logged-in Discord user is currently a member of, as
    snapshotted at login time - every /api endpoint that takes a guild_id
    filters against this so a person only ever sees servers they're on.
    """
    if not config.AUTH_ENABLED:
        return None
    if not request.session.get("user"):
        raise HTTPException(401, "Not logged in.")
    return {int(g) for g in request.session.get("guild_ids", [])}


@router.get("/auth/login")
def login(request: Request):
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "redirect_uri": config.DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
    }
    return RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/auth/callback")
async def callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    if error:
        raise HTTPException(400, f"Discord login was not completed: {error}")

    expected_state = request.session.pop("oauth_state", None)
    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(400, "Login request expired or was tampered with - please try logging in again.")
    if not code:
        raise HTTPException(400, "Discord did not return an authorization code.")

    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": config.DISCORD_CLIENT_ID,
                "client_secret": config.DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(502, "Discord rejected the login exchange - please try logging in again.")
        access_token = token_resp.json()["access_token"]

        auth_header = {"Authorization": f"Bearer {access_token}"}
        user_resp = await client.get(f"{DISCORD_API}/users/@me", headers=auth_header)
        guilds_resp = await client.get(f"{DISCORD_API}/users/@me/guilds", headers=auth_header)
        if user_resp.status_code != 200 or guilds_resp.status_code != 200:
            raise HTTPException(502, "Could not read your Discord profile - please try logging in again.")

    user = user_resp.json()
    request.session["user"] = {
        "id": user["id"],
        "name": user.get("global_name") or user["username"],
        "avatar": user.get("avatar"),
    }
    request.session["guild_ids"] = [g["id"] for g in guilds_resp.json()]
    return RedirectResponse("/")


@router.get("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
