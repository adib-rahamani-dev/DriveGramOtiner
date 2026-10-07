# Verification record — 2026-10-07

- Windows / Python 3.12: 29 mock tests passed, 1 PostgreSQL locking test skipped.
- Linux (WSL) / Python 3.12.15 / PostgreSQL 14.24: 30 tests passed, including 8 competing claimers and the global concurrency cap.
- Alembic initial migration applied successfully; `alembic check` reported no model/schema drift.
- Ruff passed. `pip check` passed. `pip-audit --local` reported no known vulnerabilities in the installed environment after dependency upgrades.
- A generated 300 MiB stream was downloaded through the mocked Drive HTTP transport in 1 MiB chunks; size, checksum and progress were verified. This does not claim a real Google-to-Telegram transfer.
- Admin login, selection and queueing were exercised through the browser with disposable sample records. Mobile width 390 and desktop width 1280 were inspected; the mobile document had no horizontal overflow.
- `docker compose config --quiet` passed. The pinned Python and PostgreSQL image tags were verified against the container registry.
- The real bot token and generated local secrets were scanned against staged repository files; none were found. `.env` is ignored and excluded from Docker build context.

Not verified here: running the full Compose stack or compiling the official Local Bot API image (local Docker daemon unavailable), a real OAuth grant, Telegram permissions, and a real 300 MiB end-to-end transfer. Google OAuth credentials/folder, Telegram application API ID/hash and channel ID are still required. The CI workflow repeats migration, drift, PostgreSQL tests and app-image build on Linux.

One non-failing warning remains in tests: Starlette deprecates its current HTTPX TestClient integration. Runtime clients use the explicitly pinned HTTPX version; tests currently pass.
