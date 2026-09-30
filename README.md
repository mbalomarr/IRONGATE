# Iron Gate

**Every post. Every guard. Accounted for.**

Iron Gate is the operating layer for private security in Saudi Arabia. It is a SaaS-enabled marketplace that connects
facilities (malls, hospitals, compounds and campuses) with MOI-licensed security firms. On one audited platform it handles
bidding, Shamoos clearance, live GPS geofencing and automatic SLA enforcement.

---

## The problem

Facilities spend millions on guard contracts but cannot verify that a guard is actually on post. Firms compete on
spreadsheets and phone calls, and compliance checks are manual. SLA breaches are rarely detected, and even when
they are, they are seldom priced into the invoice.

## The product

| For | What Iron Gate does |
|---|---|
| **Facilities** | Post a guard request, compare bids side by side, award, and watch every guard live on a geofence radar |
| **Security firms** | Bid on open requests in their cities, sign contracts, manage a Shamoos-verified roster |
| **Guards** | A native-feel mobile app: one-tap check-in inside the geofence, background location pings, breach alerts |
| **Platform** | Firm approvals, Shamoos audit trail, MRR / GMV analytics |

**Bring Your Own Contract (BYOC).** A facility that already has a security provider can import its existing contract.
Live tracking starts as soon as the provider confirms, with no new tender, which removes the main barrier to adoption.

## Business model

Two revenue engines:

1. **SaaS tracking subscription** (recurring):
   **199 SAR / month platform fee + 30 SAR per tracked guard / month.**
   *Example: 5 active guards = 150 SAR + platform 199 SAR = **349 SAR / month**.*
2. **Marketplace commission**: a take rate on the value of contracts won through Iron Gate bidding.
   Imported (BYOC) contracts are SaaS revenue only.

The Super Admin console reports MRR, ARR, average revenue per facility, tracked guards, marketplace GMV with
month-over-month trend, and the split between marketplace and imported contracts.

## Tech stack

| Layer | Technology |
|---|---|
| API | Python · **FastAPI** · Pydantic v2 |
| Data | **SQLAlchemy 2** · Alembic migrations · SQLite (local) / **MySQL 8** (production target) |
| Security | JWT (PyJWT) · bcrypt · role-based access control (7 roles) |
| Localization | Native **Arabic (RTL)** and English (LTR), end to end, including API error messages |
| Frontend | Single-file HTML apps · **Tailwind CSS** · vanilla JS, with no build step |
| Background jobs | In-process SLA penalty engine |
| Quality | pytest suite (25 tests) |

## Repository layout

```
IronGate/
├── backend/            FastAPI service (API, models, migrations, seed, tests)
│   ├── app/            main.py, api/routes, models, schemas, services, locales (en/ar)
│   ├── alembic/        database migrations
│   ├── tests/          pytest suite
│   └── README.md       technical API reference
├── frontend/
│   ├── index.html      marketing site with live pricing calculator
│   └── dashboard.html  operations console (admin · firm · facility · guard app)
├── .gitignore
└── README.md
```

## Run it locally

**Requirements:** Python 3.9+ and a modern browser.

```bash
# 1. One-time setup (from the repository root)
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
cd backend
pip install -r requirements.txt
cp .env.example .env               # the defaults use a local SQLite file

# 2. Create the database and the demo data
alembic upgrade head
python -m app.db.seed

# 3. Start the API
uvicorn app.main:app --reload
```

The API now runs at **http://localhost:8000**, with interactive docs at **http://localhost:8000/docs**.

**4. Open the frontend** by double-clicking `frontend/index.html` or `frontend/dashboard.html`. Both connect to
`http://localhost:8000` by default. To use another address, add `?api=http://host:port` to the URL.

### Demo accounts

All demo accounts use the password `ChangeMe123`. The dashboard login screen also has one-click demo buttons.

| Email | Role | Demo highlight |
|---|---|---|
| `admin@irongate.sa` | Super Admin | MRR, GMV trend, tracked guards, firm approvals |
| `facility@irongate.sa` | Facility Manager | Billing & subscriptions, BYOC import, live tracking |
| `firm@irongate.sa` | Security Firm | Bidding, contracts, guard roster |
| `guard@irongate.sa` | Security Guard | Mobile guard app: check in, geofence radar |

The super admin password comes from `SEED_ADMIN_PASSWORD` in `backend/.env`. Re-running the seed is safe: it never
duplicates data and re-centres the demo shifts on "now".

### Tests

```bash
cd backend && pytest
```

---

*Semester project · Built with FastAPI and Tailwind CSS.*
