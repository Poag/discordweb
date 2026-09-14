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
