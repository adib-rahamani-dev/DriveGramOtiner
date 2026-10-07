# Verification record — 2026-10-07

- Windows / Python 3.12: 29 mock tests passed, 1 PostgreSQL locking test skipped.
- Linux (WSL) / Python 3.12.15 / PostgreSQL 14.24: 30 tests passed, including 8 competing claimers and the global concurrency cap.
- Alembic initial migration applied successfully; `alembic check` reported no model/schema drift.
- Ruff passed. `pip check` passed. `pip-audit --local` reported no known vulnerabilities in the installed environment after dependency upgrades.
- A generated 300 MiB stream was downloaded through the mocked Drive HTTP transport in 1 MiB chunks; size, checksum and progress were verified. This does not claim a real Google-to-Telegram transfer.
- Admin login, selection and queueing were exercised through the browser with disposable sample records. Mobile width 390 and desktop width 1280 were inspected; the mobile document had no horizontal overflow.
- `docker compose config --quiet` passed. The pinned Python and PostgreSQL image tags were verified against the container registry.
- The real bot token and generated local secrets were scanned against staged repository files; none were found. `.env` is ignored and excluded from Docker build context.

At this initial verification, the full Compose stack and official Local Bot API image had not yet been built. See the later local-runtime record below. A real OAuth grant, destination access and real 300 MiB end-to-end transfer still require account setup. The CI workflow repeats migration, drift, PostgreSQL tests and app-image build on Linux.

One non-failing warning remains in tests: Starlette deprecates its current HTTPX TestClient integration. Runtime clients use the explicitly pinned HTTPX version; tests currently pass.

## Vercel/cloud update

- Production deployment `dpl_HyJwFf7uYFdXkRFTYQZ2rc5i5aUK` is READY at https://drivegramotiner.vercel.app. Public checks without credentials: root 200, stylesheet 200, health 503/setup_required, private status 404. The browser confirms the Persian setup page explicitly says transfers are not active.
- Windows: 31 passed, 1 PostgreSQL test skipped. Linux/PostgreSQL: all 32 passed. An initial Linux run had a transient CSRF test failure; its isolated rerun and the subsequent complete suite passed.
- Migration 0002 applied; Alembic check reports no schema drift. Ruff and cloud Compose validation passed. Cloud Compose itself has not been started.
- Remote panel tests forbid local disk access and verify worker disk values and unknown status after a missing heartbeat. The unconfigured entrypoint does not expose private API routes.
- No .env file or Telegram credentials were sent to Vercel. The deployment uploaded 27 source/config files (85.7 KB); local dependencies, tests, data and private environment files are excluded.
- Vercel GitHub connection was attempted but rejected for repository access. Automatic Git-triggered deployments are not enabled. CLI deployment succeeded independently.
- A permanent cloud worker, managed database, credentials and real end-to-end verification are still pending; publishing the setup page is not a fully running transfer service.

## Private chat and real local runtime

- Destination now supports the user's private bot conversation. Admin/CSRF-protected pairing issues a one-use, ten-minute deep link; only its hash is stored. Group/channel messages, expired codes and destination changes during active transfers are rejected. Pairing temporarily pauses new claims. Existing channel configuration remains a compatibility fallback.
- Windows: 36 tests passed, one PostgreSQL test skipped. Linux/PostgreSQL: all 37 passed. Migration 0003 applied and Alembic reported no schema drift; Ruff passed. Pairing, update offsets, admin/CSRF checks and private send payloads were tested with mock Telegram transports, without sending real messages.
- Official Docker Engine 29.8.2 and Compose 5.6.0 were installed in the existing Ubuntu-22.04 WSL instance. Official package metadata signatures and downloaded package checksums were verified. Linux base images and dependency wheels were loaded locally because some WSL download endpoints were inaccessible.
- App and official Telegram Bot API images built successfully. The pinned official binary reports Bot API 10.3. The real Compose database, migrations, panel and worker start; panel/database/worker health checks pass. The Bot API container deliberately waits for missing application API ID/hash, rather than claiming readiness.
- The actual panel is available at http://localhost:18080. Port 8000 was already occupied by an unrelated application and was left untouched. Admin browser login and the real worker heartbeat were verified. Start/Stop convenience scripts preserve the database and named volumes.
- The real bot token matches DriveGramOtiner_bot when checked read-only from Windows. Within the container, the Google OAuth/API endpoints respond, but the public Telegram endpoint is currently inaccessible. Windows uses its existing loopback proxy, which is not available to WSL. Telegram network access remains an unresolved prerequisite; no TLS checks, firewall rules or global proxy settings were weakened.
- Remaining account inputs: Google OAuth client/consent and Drive folder, Telegram application API ID/hash, and private-chat Start/pairing. Google Cloud is open for the user to sign in later. No real file transfer has been verified.
- Vercel deployment dpl_Bs4towcuA8a39R7h2mpChaqPkfMb is READY at https://drivegramotiner.vercel.app. Its setup page now states the private-chat destination and inactive transfer status. Only source/config was uploaded; credentials remain local. Remote transfer hosting is still absent.
- Staged files were checked against local secret values; none were found. Private environment files, WSL install artifacts, downloaded images/wheels and screenshots remain excluded from Git and deployment.
- The first GitHub run after the private-chat update found a test-helper import issue with the standalone `pytest` entrypoint. The tests directory is now an explicit package; the same standalone command passed all 37 tests against PostgreSQL locally. Runtime files were unaffected.
- GitHub run 37644496608 on de06e266d138d6dd40cf51381ace69a59272dd19 passed all 37 tests, migrations/drift checks, Ruff and the normal Docker app build.
- The Google Cloud project DriveGramOtiner (alien-kingdom-510915-q3) was created and Drive API reports Enabled. After the account owner's explicit policy confirmation, OAuth branding was submitted and Google reported "OAuth configuration created!". OAuth and Telegram application credential forms are prepared; credential creation and the Drive grant remain pending.
- A setup-only Windows pairing helper was added. It reads the expected bot's cloud updates through Windows' existing connection and uses the existing database nonce validator inside the worker; no bridge, proxy changes or exposed port is involved. Its replay/destination validation test passes. Real setup checks reached the pending-pair state but no matching Start was received; no private destination or file transfer is claimed.
- The helper update passed all 38 tests against Linux/PostgreSQL. One preceding full run had a transient admin-session failure; the isolated test and subsequent complete suite both passed.

## Complete files up to 50 MB — 2026-10-08

- Added an explicit cloud API mode using only the existing bot token and private-chat pairing. This mode requires the exact official HTTPS endpoint, uploads original bytes with streaming multipart, and caps files at 50,000,000 bytes. It neither divides nor converts files. Local mode retains the existing file-URI upload path and application-credential requirements.
- Windows: 42 tests passed, one PostgreSQL test skipped. Linux/PostgreSQL: all 43 passed, including cloud multipart video/document uploads, private destination, oversize queue/upload rejection, endpoint validation and ambiguous upload timeout. Ruff passed.
- The actual panel and database are healthy. The native Windows worker runs through the existing Windows connection and persists its heartbeat/disk state to the same PostgreSQL database. The Docker worker and Local Bot API are stopped in this mode. The database port is authenticated and bound only to loopback; its additional bridge has outgoing masquerading disabled. No proxy bridge, firewall change or TLS weakening was introduced.
- Created and opened a dedicated private DriveGramOtiner upload folder in the owner's Chrome Drive account. The folder identifier is saved only in the ignored local environment. With explicit owner approval, the Google OAuth web client was created and its credentials saved only locally. The owner is registered as a test user; the consent flow reached Google's unverified-testing-app notice and was handed to the owner for the actual Drive grant. Private-chat Start and a real Google-to-Telegram file transfer remain pending.
- The existing cloud bot identity was verified read-only from the Windows runtime. Its readiness check confirms database/schema are ready and lists only private-chat pairing as missing configuration after saving the Google client. This is not a claim that Drive authorization or transfers are complete.
