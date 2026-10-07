#!/bin/sh
set -eu
if [ -z "${TELEGRAM_API_ID:-}" ] || [ -z "${TELEGRAM_API_HASH:-}" ]; then
  echo 'Local Bot API needs TELEGRAM_API_ID and TELEGRAM_API_HASH; configure .env and recreate this service.'
  # Keep the unconfigured service alive; app/worker remain usable for setup.
  exec sleep infinity
fi
# Official server accepts credentials from environment. Never echo or put them in argv.
exec telegram-bot-api --local --http-port=8081 --http-ip-address=0.0.0.0 \
  --dir=/bot-api-data --temp-dir=/bot-api-data/tmp --verbosity=0 --log=/dev/null
