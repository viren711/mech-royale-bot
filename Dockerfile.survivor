FROM python:3.13.9-slim-bookworm
WORKDIR /bot
ENV PYTHONDONTWRITEBYTECODE=1
COPY bot.py mechfight.py survivor.py ./
USER 65534:65534
ENTRYPOINT ["python3", "-u", "/bot/survivor.py"]
