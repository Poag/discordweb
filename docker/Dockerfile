# Built with: docker build -f docker/Dockerfile .   (context is the repo root -
# see .github/workflows/docker-publish.yml, which builds this on every push)
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY scripts/ scripts/
COPY config/*.example.json config/

# Bake in synthetic demo data at build time (same generator as local dev)
# so the image runs out of the box. Point VOICELOG_DB/GAMELOG_DB at a
# mounted volume, or bind-mount real files over these same paths, to use
# real data instead - see README "Docker" section.
RUN python scripts/generate_demo_data.py

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV HOST=0.0.0.0 \
    PORT=8000 \
    VOICELOG_DB=/app/data/voicelog.sqlite3 \
    GAMELOG_DB=/app/data/gamelog.sqlite3 \
    USERS_FILE=/app/config/users.json \
    CHANNELS_FILE=/app/config/channels.json

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/api/guilds')" || exit 1

CMD ["sh", "-c", "uvicorn backend.main:app --host ${HOST} --port ${PORT}"]
