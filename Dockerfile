# mechfight bot: survival-first. Standard library only, so no pip installs are needed.
FROM python:3.13.1-slim-bookworm@sha256:031ebf3cde9f3719d2db385233bcb18df5162038e9cda20e64e08f49f4b47a2f
WORKDIR /bot
COPY mechfight.py world.py base.py bot.py ./
RUN python3 -m compileall -q /bot && chmod -R a+rX /bot
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
ENTRYPOINT ["python3", "-u", "/bot/bot.py"]
