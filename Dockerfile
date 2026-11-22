FROM gcc:13-bookworm AS builder
WORKDIR /build
COPY src ./src
RUN g++ -O3 -std=c++20 -DNDEBUG -pthread -static-libstdc++ -static-libgcc -Isrc src/main.cpp -o /mechbot

FROM debian:bookworm-slim
WORKDIR /bot
COPY --from=builder /mechbot /bot/mechbot
RUN chmod 755 /bot/mechbot
ENTRYPOINT ["/bot/mechbot"]
