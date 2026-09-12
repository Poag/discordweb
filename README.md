# Voice & Game Dashboard

A local dashboard for the data logged by the [`voicelog`](https://github.com/Poag/PogCogs/tree/main/voicelog)
and [`gamelog`](https://github.com/Poag/PogCogs/tree/main/gamelog) Red-DiscordBot cogs: who's playing what,
top10 leaderboards per game, voice channel activity, a force-directed relationship graph (in the
spirit of Obsidian's graph view) showing who hangs out in voice together and who games together,
and a per-person "Your Year" recap (Spotify-Wrapped style) — top games, who they chatted/gamed
with most, busiest month, longest session. The relationship graph and the wrapped partner stats
are both built by joining each cog's session intervals on overlapping time windows, exactly as
both cogs' own docstrings describe.

## How it's built

- **Backend** (`backend/`): a small FastAPI app that opens the two cogs' SQLite files
  **read-only** and serves a JSON API. No copy of your data is made; nothing is written back
  to either database.
- **Co-occurrence graph** (`backend/overlap.py`): a sweep-line algorithm computes, for every
  pair of users, how many seconds they spent in the same voice channel or playing the same
  game at overlapping times. Cost tracks actual concurrency, not the total number of logged
  sessions, so it stays fast even with a lot of history.
- **Frontend** (`frontend/`): a single static page (no build step) using D3 (vendored locally
  in `frontend/vendor/` — no CDN dependency, works fully offline) for the force-directed graph,
  plus plain HTML/CSS for the leaderboard and stats views.
- **Name resolution** (`backend/names.py`): the two cogs only ever log raw Discord snowflake
  IDs, so display names come from `config/users.json` / `config/channels.json`, either filled
  in by the demo generator or fetched for real via `scripts/fetch_discord_names.py`.

Discord snowflake IDs are 64-bit and exceed JavaScript's safe integer range (2^53), so every
ID that crosses the API boundary is serialized as a **string**, never a JSON number — this
matters if you extend the API.

## Quickstart (demo data)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/generate_demo_data.py   # ~14 months of synthetic data, three overlapping friend groups
.venv/bin/uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000.

## Pointing it at real data

1. Copy your bot's `voicelog.sqlite3` and `gamelog.sqlite3` (from each cog's data folder under
   Red's `cog_data_path`) somewhere this machine can read, or set the paths directly:

   ```bash
   export VOICELOG_DB=/path/to/voicelog.sqlite3
   export GAMELOG_DB=/path/to/gamelog.sqlite3
   ```

   By default they're read from `data/voicelog.sqlite3` and `data/gamelog.sqlite3`.

2. Resolve real display names (needs the same bot token, with the Server Members privileged
   intent enabled — the same requirement `gamelog` itself has):

   ```bash
   DISCORD_BOT_TOKEN=... .venv/bin/python scripts/fetch_discord_names.py --guild-id <your guild id>
   ```

   This writes `config/users.json` and `config/channels.json`. Re-run it any time to pick up
   new members; it merges rather than replaces, so manual edits survive. Without this step,
   unmapped users show up as `User 1234` placeholders — the dashboard still works, just with
   less readable labels.

3. Restart the server. If your bot logs multiple guilds, a guild selector appears automatically
   in the top bar.

`config/users.json`, `config/channels.json`, and any real `*.sqlite3` files are gitignored —
this repo is meant to hold the code, not your server's data. See `config/*.example.json` for
the mapping format.

## API

All endpoints accept an optional `?guild_id=` (defaults to the only/first guild with data):

| Endpoint | Returns |
|---|---|
| `GET /api/guilds` | guild IDs with any logged data |
| `GET /api/overview` | headline stats |
| `GET /api/leaderboard` | top players by total game time |
| `GET /api/voice/leaderboard` | top users by total voice time |
| `GET /api/voice/channels` | per-channel voice time |
| `GET /api/games` | every logged game, sorted by total time |
| `GET /api/games/{game}/top10` | top 10 players of a specific game |
| `GET /api/graph?min_seconds=` | relationship graph: nodes + edges (voice/game overlap seconds, plus per-channel/per-game breakdown for tooltips) |
| `GET /api/users` | every known user (id + resolved name), for the "Your Year" picker |
| `GET /api/years` | calendar years with any logged activity |
| `GET /api/wrapped?user_id=&year=` | one person's year-in-review: totals, ranks, top games, top voice/game partner, busiest month, longest sessions. 404s if that person has no activity that year |

## Project layout

```
backend/            FastAPI app, SQLite access, overlap/co-occurrence math, name resolution
frontend/            Static dashboard (index.html, style.css, app.js) + vendored D3
scripts/
  generate_demo_data.py   Synthetic voicelog.sqlite3 / gamelog.sqlite3 + name mappings
  fetch_discord_names.py  Resolves real display names via the Discord API
config/               users.json / channels.json (gitignored) + .example.json formats
data/                 SQLite files live here by default (gitignored)
```
