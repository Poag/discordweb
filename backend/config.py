"""Runtime configuration, entirely via environment variables so the same
code runs against demo data or a real bot's data directory without edits.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VOICELOG_DB = Path(os.environ.get("VOICELOG_DB", ROOT / "data" / "voicelog.sqlite3"))
GAMELOG_DB = Path(os.environ.get("GAMELOG_DB", ROOT / "data" / "gamelog.sqlite3"))

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

# Discord OAuth2 login, restricting each viewer to the guilds they're
# actually a member of. Optional: with none of these set, the app behaves
# exactly as it did before auth existed (open access, every logged guild
# visible to everyone) - see README "Authentication".
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI")
SESSION_SECRET = os.environ.get("SESSION_SECRET")

AUTH_ENABLED = bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI)

if AUTH_ENABLED and not SESSION_SECRET:
    raise RuntimeError(
        "DISCORD_CLIENT_ID/DISCORD_CLIENT_SECRET/DISCORD_REDIRECT_URI are set but "
        "SESSION_SECRET is not - set SESSION_SECRET to a random value (e.g. "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"`) to sign login "
        "session cookies."
    )
