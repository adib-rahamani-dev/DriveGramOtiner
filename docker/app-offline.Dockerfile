# Development fallback when PyPI is unreachable inside WSL.
# Supply the trusted locked Linux wheel directory as the "wheels" build context.
FROM python:3.12.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home drivegram \
    && mkdir /transfers && chown drivegram:drivegram /transfers
WORKDIR /app
COPY requirements.lock ./
COPY --from=wheels / /wheels/
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.lock \
    && rm -rf /wheels
COPY . .
USER drivegram
CMD ["uvicorn", "drivegram.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
