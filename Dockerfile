# The match runs it with no network, a read-only root (writable /tmp), 1 CPU, 512 MB, and the map at /arena.
FROM oven/bun:1.4.4-slim
WORKDIR /bot
COPY src ./src
COPY bots ./bots
COPY data ./data
COPY package.json ./
ENV BUN_RUNTIME_TRANSPILER_CACHE_PATH=0
ENTRYPOINT ["bun", "/bot/bots/splitlvr5/main.ts"]
