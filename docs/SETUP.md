# Setup, configuration and tests

Detailed operating notes moved here from the previous README. The [README](../README.md#quick-start) has the short
version. Commands marked *destructive* erase data in the database they target.

## Running the application

### Option A — Docker Compose
```bash
cp .env.example .env    # then set POSTGRES_PASSWORD and API_TOKEN (required; no insecure defaults)
docker compose up --build
```
Open http://127.0.0.1:3010 (published on 127.0.0.1 only; the API is not published). Migrations run on backend start.
*Docker was not available in the development environment: the compose file was parsed as YAML, but the images were
**never built or started**.*

### Option B — local, no Docker (macOS arm64; verified on an isolated stack)

**The existing demo uses 3010/8010 and database `ddc_e2e` on 55433. Do not run setup or reset against it.**
Use a new database and different ports for verification; see [VERIFICATION.md](VERIFICATION.md).
Uses an embedded PostgreSQL 17 binary from npm (`@embedded-postgres/darwin-arm64`) on port 55433.
```bash
./dev.sh setup
./dev.sh start
```
Open http://127.0.0.1:3010. Stop this checkout’s recorded services with `./dev.sh stop` (PostgreSQL stays running).
Tested with Python 3.14.5 and Node 24.22.0. `./dev.sh start` refuses occupied service ports, applies migrations,
checks integrity, builds the frontend, and waits for an authenticated proxy request to succeed. It parses
`backend/.env` without shell evaluation and passes the same API token to both servers. Environment variables
override the private file. `BACKEND_PORT`, `FRONTEND_PORT`, `PORT_DB`, `DDC_PGDATA`, and `DDC_PG_BIN` allow an isolated
stack; set `DATABASE_URL` explicitly to match it. `setup` installs test dependencies too. A clean dependency install
was not repeated in the November verification; existing matching dependencies were reused.

The production build currently downloads Inter from Google Fonts; network access is needed on a cold build.
Build before the defense. The stop helper uses recorded process start time/owner, avoiding broad process-name kills.
Processes launched by older helpers must be identified and stopped separately; they are not adopted automatically.

Manual equivalent: start PostgreSQL, then
`cd backend && . .venv/bin/activate && alembic upgrade head && uvicorn app.main:app --host 127.0.0.1 --port 8010`, and
`cd frontend && npm run build && npm start` (the server-side route `src/app/api/[...path]` forwards `/api/*` to `API_URL`).

### Upgrading an existing installation
```bash
cd backend && . .venv/bin/activate
alembic upgrade head                        # adds import-preview expiry; normalises cleared staging to SQL NULL
python scripts/integrity_check.py           # read-only report on data imported before the integrity fixes
python scripts/integrity_check.py --redact-validation --purge-expired-previews   # optional, explicit repairs
```
Migration `6129d2b374e8` is reversible (`alembic downgrade -1` drops the expiry column); its JSON-null → SQL-NULL
normalisation is data-only and intentionally not reverted. A stored "min classes per textbook" below 3 is raised to 3
at load time and shown as a notice in Settings.

## Access and configuration
* **Local demo (default):** no `API_TOKEN` → the API serves loopback clients only, the UI is bound to 127.0.0.1.
* **Token mode:** set `API_TOKEN` for both backend and frontend processes; the Next.js server adds it to proxied
  requests, it never reaches the browser. Optional `DEMO_BASIC_AUTH_USER/PASSWORD` protects the whole UI.
* **Delete all data** is disabled unless `ENABLE_DATA_RESET=true` and `ADMIN_TOKEN` (≥ 16 chars) are set; the Settings
  dialog then asks for the admin token. `./dev.sh setup` enables it for local development with a random token stored
  in the git-ignored `backend/.env`.
* There are no user accounts and no per-school isolation: anyone with the API token sees all data.

### Optional LLM
Without a key the **deterministic explainer** is used and the UI labels the mode. For Gemini, edit only the private
server file (`backend/.env` locally; root `.env` for Compose):

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-3.8-flash
LLM_TIMEOUT_SECONDS=60
# Set LLM_API_KEY privately; never paste a real key into documentation or chat.
```

The endpoint matches [Google’s official OpenAI compatibility documentation](https://aistudio.google.com/docs/openai),
checked 11 November 2026. Check model access for your own account before relying on it. Compose now forwards the
base URL and timeout as well as provider/key/model, but its images have **not** been run here. Locally, the helper
passes the API token to the frontend; for a manual launch set `API_TOKEN` and `API_URL` on the frontend process too.
The model receives aggregate facts; output guards are heuristic and do not certify every sentence.

Evidence: the handoff records one successful live Gemini request (about 27 seconds). This verification used mocks
and deterministic mode, and made no live model calls. The prior key’s rotation is unconfirmed; replace it privately
before using it beyond the original demonstration. Do not copy the original private configuration into source exports.

## Tests

Tests destroy the schema of their target database. `TEST_DATABASE_URL` is now required explicitly and its parsed
PostgreSQL database name must end in `_test`. Create a **fresh** database on a separate verification instance/port.
Never use `ddc_e2e`: despite its name, it is the live demonstration database.

```bash
# From backend/, with dependencies installed:
TEST_DATABASE_URL=postgresql+psycopg://verification@127.0.0.1:55434/ddc_verification_test python -m pytest -q
# From frontend/:
npm run typecheck       # generates Next.js route types before tsc
npx eslint src e2e playwright.config.ts
npm test
npm run build
```

Browser tests require an already running isolated backend/database and production frontend. After checking those
service targets, run from `frontend/`:

```bash
E2E_BASE_URL=http://127.0.0.1:3011 E2E_ALLOW_RESET=isolated-database \
  E2E_ADMIN_TOKEN='<private test admin token>' npm run e2e
```

If the pinned Playwright browser build is not installed (e.g. a sandbox image with its own Chromium), add
`E2E_CHROMIUM_PATH=/path/to/chrome`. Load the actual token from a private file, rather than putting it literally in shell history. The configuration refuses
missing targets, remote hosts, and demo port 3010. The journey **resets all data** on the selected stack. Use
`E2E_ARTIFACT_DIR` to keep new screenshots/PDFs separate from the archive’s historical screenshots.
Full commands, results, limitations, and coverage are in [VERIFICATION.md](VERIFICATION.md).
