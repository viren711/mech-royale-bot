FROM python:3.13-slim
WORKDIR /bot
COPY mechfight.py bot.py ./
ENTRYPOINT ["python3", "-u", "/bot/bot.py"]
