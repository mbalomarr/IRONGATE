# Iron Gate — Backend API (technical reference)

B2B Security Manpower Marketplace: facilities post guard requests, MOI-licensed firms bid, contracts are signed and approved, guards are Shamoos-verified, and SLA breaches (geofence) become automatic invoice penalties.

**Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · MySQL 8 (PyMySQL) · Pydantic v2 · JWT (PyJWT + bcrypt)

## Quick start

Run from the repository root (the virtual environment lives at the root, the API in `backend/`):

```bash
python3 -m venv .venv && source .venv/bin/activate
cd backend
pip install -r requirements-dev.txt
cp .env.example .env                  # then edit DATABASE_URL / JWT_SECRET_KEY
alembic upgrade head                  # create schema
python -m app.db.seed                 # roles, lookups, super admin, demo scenario
uvicorn app.main:app --reload         # http://localhost:8000/docs
pytest                                # uses in-memory SQLite
```

`.env` and a relative SQLite URL (`sqlite:///./irongate.db`) always resolve against `backend/`.
For MySQL 8 instead of SQLite: `docker compose up -d mysql` and point `DATABASE_URL` at it (utf8mb4).

In Swagger, click **Authorize** and sign in with `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`.

### Demo accounts (password `ChangeMe123`)

`python -m app.db.seed` also builds a live demo scenario (disable with `SEED_DEMO_DATA=false`):

| Email | Role | What you can demo |
|---|---|---|
| `admin@irongate.sa` | `super_admin` | Platform KPIs, all requests, Shamoos logs, approve the pending firm |
| `firm@irongate.sa` | `firm_manager` | Bid on an open request, sign the awarded contract, guard roster |
| `facility@irongate.sa` | `facility_manager` | Compare & award bids, approve the signed contract, live geofence tracking |
| `guard@irongate.sa` | `security_guard` | Mobile guard app: check in/out inside the geofence, location pings, breach alerts |

Re-running the seed is safe: it never duplicates data, refreshes lookup translations, and re-centres the demo
shifts and Shamoos traffic on "now" so the guard always has a shift ready to check into.

Open `../frontend/index.html` (marketing site) or `../frontend/dashboard.html` (operations console) directly in a browser.

## Layout

```
app/
  main.py              App factory, middleware, lifespan (starts SLA job)
  core/                config, i18n (+ LocaleMiddleware), security (JWT/bcrypt),
                       exceptions (localized error envelope), permissions (RBAC matrix)
  db/                  engine/session, idempotent seed data
  models/              SQLAlchemy models (one file per aggregate)
  schemas/             Pydantic request/response models
  services/            shamoos (mock client), matching, geofence, sla
  tasks/scheduler.py   background SLA loop
  api/deps.py          get_db, get_current_user, require_permissions(...)
  api/routes/          auth, lookups, admin, guards, shamoos, bidding
  locales/{en,ar}.json message catalogs
alembic/versions/      0001_initial_schema
tests/
```

## RBAC

Roles live in the `roles` table (localized names + portal). The role → permission matrix is in
[`app/core/permissions.py`](app/core/permissions.py) and enforced with
`Depends(require_permissions(Permission.X))`. Data is also scoped by organization (`users.firm_id` / `users.facility_id`).

| Role | Portal | Key permissions |
|---|---|---|
| Super Admin | Platform | everything (firm approval, revenue, SLA run) |
| Operations | Platform | monitor all requests, Shamoos stats — **no financial access** |
| Firm Manager | Firm | submit/withdraw bids, sign contracts, view invoices, create HR/guard users |
| HR / Dispatcher | Firm | guard roster, Shamoos verification, shift assignment |
| Facility Manager | Client | create requests, compare/accept bids, approve contracts, pay invoices |
| Site Supervisor | Client | geofence alerts, incident review |
| Security Guard | Mobile | clock in/out, own shifts, report incidents |

## Schema

`roles`, `users`, `firms` (+ `firm_cities`), `facilities`, `guards`, `shamoos_verification_logs`,
`guard_requests`, `bids`, `contracts`, `shifts`, `incidents`, `invoices`, `sla_penalties`,
plus translatable lookups `cities`, `sectors`, `request_statuses`, whose `name` is a JSON column like
`{"en": "Shopping Mall", "ar": "مركز تجاري"}`.

Notes:
- The requests table is `guard_requests` (model `GuardRequest`) to avoid clashing with Starlette's `Request`.
- Contract → firm/facility are reached through `bid` (no duplicated FKs).
- `users.firm_id ↔ firms.reviewed_by_id` is a FK cycle; the migration adds the latter FK after both tables exist.
- Timestamps are naive UTC (`DATETIME`); money is `DECIMAL`.

## Localization

- `LocaleMiddleware` resolves the locale from `Accept-Language` (q-values honoured) or a `?lang=ar` override,
  stores it in a ContextVar and sets `Content-Language` on the response.
- `t("bid.submitted")` translates from `app/locales/*.json`; `localize(json_col)` picks the right language from lookup JSON.
- All responses use one envelope: `{"success", "message", "data"}` / `{"success": false, "message", "code", "errors"}`.
  Pydantic validation errors are translated per error type and field name (`"حقل البريد الإلكتروني مطلوب."`).
  Custom validators raise `i18n_error("some.key")` to get fully localized messages.
- Enum values come back as `{"code": "verified", "label": "تم التحقق"}`.

## Business logic

- **Mock Shamoos:** `POST /api/v1/shamoos/verify` randomly returns `Verified`/`Rejected`
  (`SHAMOOS_MOCK_APPROVAL_RATE`, `SHAMOOS_MOCK_FAILURE_RATE` simulates outages).
  `POST /shamoos/guards/{id}/verify` updates a roster guard; every call is logged for `GET /shamoos/stats` (Operations).
  Swap `MockShamoosClient` for a real client in `services/shamoos.py`.
- **Smart matching:** `GET /requests/{id}/recommended-firms` returns approved, licensed firms serving the facility's city
  whose *available* verified guards (verified in that city minus guards committed to overlapping contracts) cover the
  request, ranked by capacity, rating and local HQ. Bidding enforces the same capacity check.
- **SLA penalties:** `services/sla.py` finds active-contract shifts whose geofence breach exceeds the contract threshold
  (default 30 min) and books one penalty per shift on that month's draft invoice, capped at `sla_max_penalty_percent`.
  Runs every `SLA_JOB_INTERVAL_SECONDS` in-process, or on demand via `POST /admin/sla/run`. Idempotent.
  `services/geofence.py` has the haversine check and breach tracking for GPS pings.

## Bidding flow

```
POST /auth/register/firm  →  POST /admin/firms/{id}/approve  →  HR: POST /guards, POST /shamoos/guards/{id}/verify
POST /auth/register/facility  →  POST /requests  →  GET /requests/{id}/recommended-firms
Firm: POST /requests/{id}/bids  →  Facility: GET /requests/{id}/bids  →  POST /bids/{id}/accept
Firm: POST /contracts/{id}/sign  →  Facility: POST /contracts/{id}/approve  (contract ACTIVE)
```

## Portal endpoints (added for the dashboard)

| Endpoint | Who | Purpose |
|---|---|---|
| `GET /shifts` | facility, site supervisor, firm, platform | Live tracking feed (scoped to the caller) |
| `GET /shifts/me` | guard | Current + upcoming assignments |
| `POST /shifts/{id}/clock-in` · `/location` · `/clock-out` | guard | GPS check-in (must be inside the geofence), pings, check-out |
| `GET /bids` | facility / firm | Bids received / submitted |
| `GET /contracts` | facility / firm / admin | Contracts the caller is party to |
| `GET /shamoos/logs` | admin, operations | Masked audit trail of Shamoos calls |
| `POST /contracts/import` | facility manager | **Bring Your Own Contract** — import an existing agreement; the provider confirms once and tracking goes live |
| `GET /billing/subscription` | facility manager | Per-seat SaaS bill: 199 SAR platform fee + 30 SAR per tracked guard / month (Riyadh months) |
| `GET /admin/saas-metrics` | super admin | MRR / ARR, tracked guards, marketplace GMV (+6-month trend), take rate |
| `GET /lookups/firms` | public | Approved security firms (provider picker) |

Pricing lives in `SAAS_PLATFORM_FEE` / `SAAS_SEAT_FEE` (settings). Imported contracts are SaaS revenue only and are excluded from GMV.

## Next steps

- Shift assignment UI for HR/Dispatch (API models ready; shifts are currently created by the seed)
- Incident reporting & supervisor review routes; notifications for geofence alerts
- Invoice issue/pay routes
- Move the SLA loop to a single scheduler process (Celery beat / APScheduler) for multi-worker deployments
- Encrypt `guards.national_id` at rest; add refresh tokens and rate limiting on `/auth/*`
