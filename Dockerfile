# Team Inventors - Mech Royale bot. Build from the repository root: docker build -t inventors-bot .
# Standard library only, so the build downloads nothing but this base image, pinned by digest.
# The match runs it as uid 65534 with no network, a read-only root (writable /tmp), 1 CPU, 512 MB, map at /arena.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /bot
COPY mechfight.py world.py bot.py /bot/
RUN python3 -m compileall -q /bot
ENTRYPOINT ["python3", "-u", "/bot/bot.py"]
