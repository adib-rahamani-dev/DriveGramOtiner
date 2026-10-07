# Official tdlib/telegram-bot-api source, pinned with its recursive TDLib revision.
FROM debian:bookworm-slim AS builder
ARG BOT_API_REF=e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git g++ make cmake gperf libssl-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --recursive https://github.com/tdlib/telegram-bot-api.git /src \
    && cd /src && git checkout "$BOT_API_REF" && git submodule update --init --recursive \
    && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/bot-api \
    && cmake --build build --target install --parallel 2
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libssl3 zlib1g curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home drivegram \
    && mkdir /bot-api-data /transfers && chown drivegram:drivegram /bot-api-data /transfers
COPY --from=builder /opt/bot-api/bin/telegram-bot-api /usr/local/bin/telegram-bot-api
COPY docker/bot-api-entrypoint.sh /usr/local/bin/bot-api-entrypoint
RUN chmod +x /usr/local/bin/bot-api-entrypoint
USER drivegram
WORKDIR /bot-api-data
ENTRYPOINT ["/usr/local/bin/bot-api-entrypoint"]
