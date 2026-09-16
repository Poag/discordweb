# Voice & Game Dashboard

A local dashboard for the data logged by the [`voicelog`](https://github.com/Poag/PogCogs/tree/main/voicelog)
and [`gamelog`](https://github.com/Poag/PogCogs/tree/main/gamelog) Red-DiscordBot cogs: who's playing what,
top10 leaderboards per game, voice channel activity, a force-directed relationship graph (in the
spirit of Obsidian's graph view) showing who hangs out in voice together and who games together,
a per-person "Your Year" recap (Spotify-Wrapped style) — top games, who they chatted/gamed
with most, busiest month, longest session — and a game-popularity-over-time chart (guild-wide on
the Games tab, one person's own mix on their Your Year page) showing the month-to-month shift in
what's being played as a 100%-stacked area chart. The relationship graph and the wrapped partner
stats are both built by joining each cog's session intervals on overlapping time windows, exactly
as both cogs' own docstrings describe.

## How it's built

- **Backend** (`backend/`): a small FastAPI app that opens the two cogs' SQLite files
  **read-only** and serves a JSON API. No copy of your data is made; nothing is written back
  to either database.
- **Co-occurrence graph** (`backend/overlap.py`): a sweep-line algorithm computes, for every
  pair of users, how many seconds they spent in the same voice channel or playing the same
  game at overlapping times. Cost tracks actual concurrency, not the total number of logged
  sessions, so it stays fast even with a lot of history. "Games together" only means both had
  overlapping sessions in that game - not that they were in a call together. The graph's
  "Together" mode is the stricter check: same game **and** same voice channel **and** the same
  moment, found by intersecting each person's own game and voice sessions before the pairwise
  sweep runs, so a shared game and a shared call that just happen to overlap by chance don't
  get counted as playing together.
- **Frontend** (`frontend/`): a single static page (no build step) using D3 (vendored locally
  in `frontend/vendor/` — no CDN dependency, works fully offline) for the force-directed graph,
  plus plain HTML/CSS for the leaderboard and stats views.
- **Name resolution** (`backend/names.py`): both cogs cache a live id → display name mapping
  directly in their own SQLite databases (`user_names`, and `channel_names` in voicelog's),
  refreshed automatically as members are seen - see PogCogs' README "Relationship data" section.
  This reads straight from those tables (merged, most-recently-seen wins), cached in memory for
  30 seconds at a time, so names stay current with zero setup and no separate export step.

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

Copy your bot's `voicelog.sqlite3` and `gamelog.sqlite3` (from each cog's data folder under
Red's `cog_data_path`) somewhere this machine can read, or set the paths directly:

```bash
export VOICELOG_DB=/path/to/voicelog.sqlite3
export GAMELOG_DB=/path/to/gamelog.sqlite3
```

By default they're read from `data/voicelog.sqlite3` and `data/gamelog.sqlite3`. That's it -
display names come from the same files (see "Name resolution" above), so there's no separate
step. If your bot is running an older PogCogs build from before it cached names itself, unmapped
users show up as `User 1234` placeholders until they're next seen (join/leave/move voice, or
start/stop a game) on the current version - the dashboard still works either way, just with
less readable labels until then.

Restart the server after pointing it at new files. If your bot logs multiple guilds, a guild
selector appears automatically in the top bar.

Any real `*.sqlite3` files placed under `data/` are gitignored - this repo is meant to hold the
code, not your server's data.

## Docker

```bash
docker build -f docker/Dockerfile -t discordweb .
docker run -p 8000:8000 discordweb
```

The image bakes in the same synthetic demo data as the local quickstart (via
`scripts/generate_demo_data.py`, run at build time), so it works immediately with no extra
setup. `.github/workflows/docker-publish.yml` builds and pushes this image to
`ghcr.io/poag/discordweb` on every push to `main` and on version tags.

To run it against real data, bind-mount your files over the same in-container paths instead of
rebuilding the image:

```bash
docker run -p 8000:8000 \
  -v /path/to/voicelog.sqlite3:/app/data/voicelog.sqlite3:ro \
  -v /path/to/gamelog.sqlite3:/app/data/gamelog.sqlite3:ro \
  discordweb
```

The container runs as a non-root user (uid 1000), so a mounted file needs to be world-readable
or owned by that uid; the default permissions Linux gives a normal file (`644`) already satisfy
this. It exposes port `8000` and a `HEALTHCHECK` against `/api/guilds`.

### Compose / Dockhand

`compose.yaml` at the repo root deploys the same image with `docker compose up -d` (or
`podman compose up -d`) — pulls `ghcr.io/poag/discordweb:latest` rather than building locally,
which suits a mixed Docker/Podman, ARM+x86 fleet better than rebuilding per host. It's also a
plain [Compose Specification](https://github.com/compose-spec/compose-spec) file, so it deploys
as a [Dockhand](https://dockhand.pro/) git stack as-is: point a git stack at this repo with
`compose_path: compose.yaml` (repo root, so no `context_dir` override is needed) and it'll
build/redeploy on every push via Dockhand's webhook auto-sync.

The real-data bind mounts are commented out in the file by default (same paths as the
`docker run` example above) — uncomment and point them at your actual host paths before
deploying for real; Docker/Podman silently creates an empty directory for a missing bind-mount
source, which breaks the app rather than erroring clearly.

If the image pull comes back unauthorized: GitHub Actions publishes GHCR packages **private by
default**, even from a public repo. Either flip the `discordweb` package to public under its own
Settings on GitHub, or configure registry credentials in Dockhand (or `docker login ghcr.io`)
instead.

## Authentication

Optional, off by default - with no `DISCORD_*` env vars set, the dashboard is open to anyone who
can reach it, showing every guild the bot logs, exactly as before this existed.

Set all four of these to require Discord login and restrict each viewer to the guilds they're
actually a member of (the intersection of "guilds the bot logs" and "guilds this Discord account
is currently in" - not a separate access list to maintain by hand):

```bash
export DISCORD_CLIENT_ID=...        # OAuth2 > General > Client ID, in the Discord dev portal
export DISCORD_CLIENT_SECRET=...    # same page > Client Secret
export DISCORD_REDIRECT_URI=https://your-dashboard-host/auth/callback
export SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

You can reuse the bot's own Discord application (bot applications already have an OAuth2 page) -
no new app needed. In that application's **OAuth2 > General > Redirects**, add the exact URL you
set as `DISCORD_REDIRECT_URI` (same scheme/host/port, no trailing slash - Discord checks it
byte-for-byte). No bot permissions or extra scopes need to change; login only ever requests
`identify guilds` (who you are, and which servers you're in), never anything the bot itself uses.

A login lasts 7 days (then you're prompted to log in again), and takes a snapshot of your guild
membership at login time - joining a server won't unlock it here until you log in again. Sessions
are a signed cookie, not a server-side store, so there's nothing to clean up or lose on restart;
the cookie holds only your Discord id/name/avatar and guild id list, the same things visible on
your public Discord profile - never your OAuth token or anything secret.

## API

All endpoints accept an optional `?guild_id=` (defaults to the only/first guild you have access
to). When [authentication](#authentication) is enabled, every endpoint below 401s if you're not
logged in, and 404s a `guild_id` you're logged in but not a member of.

| Endpoint | Returns |
|---|---|
| `GET /api/me` | login status: `{auth_enabled}` when auth is off, else `{auth_enabled, authenticated, user?}` |
| `GET /api/guilds` | every guild you have access to, as `{id, name}` |
| `GET /api/overview` | headline stats |
| `GET /api/leaderboard` | top players by total game time |
| `GET /api/voice/leaderboard` | top users by total voice time |
| `GET /api/voice/channels` | per-channel voice time |
| `GET /api/games` | every logged game, sorted by total time |
| `GET /api/games/{game}/top10` | top 10 players of a specific game |
| `GET /api/games/timeline?top_n=` | monthly game-time mix: the top N games (by all-time total, `top_n` default 7, max 8) as fixed series plus an "Other" catch-all, raw seconds per game per month - the frontend normalizes to a 100% stacked chart itself |
| `GET /api/graph?min_seconds=&game=` | relationship graph: nodes + edges with `voice_seconds`/`game_seconds` (overlapping sessions) and `together_seconds` (the stricter same-game-same-channel-same-time check), plus per-channel/per-game/per-"game in channel" breakdowns for tooltips. `game` (optional) scopes every game-related number to that one game instead of summing all games |
| `GET /api/users` | every known user (id + resolved name), for the "Your Year" picker |
| `GET /api/years` | calendar years with any logged activity |
| `GET /api/wrapped?user_id=&year=` | one person's year-in-review: totals, ranks, top games, top voice/game partner, busiest month, longest sessions. 404s if that person has no activity that year |
| `GET /api/wrapped/timeline?user_id=&year=&top_n=` | the same monthly game-time mix as `/api/games/timeline`, scoped to one person's one year (`top_n` default 5, max 8) |

## Project layout

```
backend/            FastAPI app, SQLite access, overlap/co-occurrence math, name resolution
  auth.py           Discord OAuth2 login (see "Authentication" above)
frontend/            Static dashboard (index.html, style.css, app.js) + vendored D3
scripts/
  generate_demo_data.py   Synthetic voicelog.sqlite3 / gamelog.sqlite3, incl. name tables
data/                 SQLite files live here by default (gitignored)
docker/Dockerfile     Container build (see "Docker" above)
compose.yaml          Compose / Dockhand git-stack deployment, pulls the published image
.github/workflows/    docker-publish.yml - builds & pushes docker/Dockerfile to ghcr.io
```
