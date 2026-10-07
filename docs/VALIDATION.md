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

## Vercel/cloud update

- Production deployment `dpl_HyJwFf7uYFdXkRFTYQZ2rc5i5aUK` is READY at https://drivegramotiner.vercel.app. Public checks without credentials: root 200, stylesheet 200, health 503/setup_required, private status 404. The browser confirms the Persian setup page explicitly says transfers are not active.
- Windows: 31 passed, 1 PostgreSQL test skipped. Linux/PostgreSQL: all 32 passed. An initial Linux run had a transient CSRF test failure; its isolated rerun and the subsequent complete suite passed.
- Migration 0002 applied; Alembic check reports no schema drift. Ruff and cloud Compose validation passed. Cloud Compose itself has not been started.
- Remote panel tests forbid local disk access and verify worker disk values and unknown status after a missing heartbeat. The unconfigured entrypoint does not expose private API routes.
- No .env file or Telegram credentials were sent to Vercel. The deployment uploaded 27 source/config files (85.7 KB); local dependencies, tests, data and private environment files are excluded.
- Vercel GitHub connection was attempted but rejected for repository access. Automatic Git-triggered deployments are not enabled. CLI deployment succeeded independently.
- A permanent cloud worker, managed database, credentials and real end-to-end verification are still pending; publishing the setup page is not a fully running transfer service.
