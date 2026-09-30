import pytest
from sqlalchemy import func, select

from app.db.seed import SITE, seed_demo_data
from app.models import Contract, Guard, Shift, User
from app.models.enums import ShiftStatus
from tests.conftest import login

API = "/api/v1"
PASSWORD = "ChangeMe123"
ON_SITE = {"latitude": str(SITE["lat"]), "longitude": str(SITE["lng"])}
OFF_SITE = {"latitude": "24.7650000", "longitude": "46.6400000"}  # ~1.5 km away


@pytest.fixture
def demo(db):
    seed_demo_data(db)
    return db


def test_demo_seed_is_idempotent(demo):
    seed_demo_data(demo)  # second run
    emails = ["admin@irongate.sa", "firm@irongate.sa", "facility@irongate.sa", "guard@irongate.sa"]
    users = demo.scalars(select(User).where(User.email.in_(emails))).all()
    assert sorted(u.role.code.value for u in users) == ["facility_manager", "firm_manager", "security_guard", "super_admin"]
    assert demo.scalar(select(func.count(Guard.id))) == 19
    assert demo.scalar(select(func.count(Contract.id))) == 8  # 2 live + 5 completed marketplace + 1 imported (BYOC)
    guard = demo.scalar(select(Guard).join(User).where(User.email == "guard@irongate.sa"))
    open_shifts = demo.scalar(select(func.count(Shift.id)).where(Shift.guard_id == guard.id, Shift.status == ShiftStatus.SCHEDULED))
    assert open_shifts == 4  # refreshed, not duplicated


def test_guard_clock_in_geofence_and_clock_out(client, demo):
    guard = login(client, "guard@irongate.sa", PASSWORD)
    duty = client.get(f"{API}/shifts/me", headers=guard).json()["data"]
    shift = duty["current"]
    assert shift["status"]["code"] == "scheduled" and len(duty["upcoming"]) == 3

    res = client.post(f"{API}/shifts/{shift['id']}/clock-in", json=OFF_SITE, headers={**guard, "Accept-Language": "ar"})
    assert res.status_code == 422
    assert res.json()["code"] == "shift.outside_geofence"
    assert "النطاق الجغرافي" in res.json()["message"]

    res = client.post(f"{API}/shifts/{shift['id']}/clock-in", json=ON_SITE, headers=guard)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["status"]["code"] == "in_progress"
    assert res.json()["data"]["inside_geofence"] is True

    res = client.post(f"{API}/shifts/{shift['id']}/location", json=OFF_SITE, headers=guard)
    assert res.json()["code"] if res.status_code != 200 else res.json()["data"]["breach_active"] is True
    assert res.json()["message"].startswith("Warning")

    res = client.post(f"{API}/shifts/{shift['id']}/location", json=ON_SITE, headers=guard)
    assert res.json()["data"]["breach_active"] is False and res.json()["data"]["geofence_breach_flag"] is True

    res = client.post(f"{API}/shifts/{shift['id']}/clock-out", json=ON_SITE, headers=guard)
    assert res.json()["data"]["status"]["code"] == "completed"
    assert client.post(f"{API}/shifts/{shift['id']}/clock-out", json=ON_SITE, headers=guard).status_code == 409

    # Guards have no marketplace access
    assert client.get(f"{API}/requests", headers=guard).status_code == 403


def test_facility_sees_tracking_bids_and_contracts(client, demo):
    fm = login(client, "facility@irongate.sa", PASSWORD)
    shifts = client.get(f"{API}/shifts", headers=fm).json()["data"]["items"]
    assert any(s["breach_active"] for s in shifts)
    assert sum(1 for s in shifts if s["status"]["code"] == "in_progress") == 4
    assert all(s["site"]["geofence_radius_m"] == 300 for s in shifts)

    bids = client.get(f"{API}/bids", headers=fm).json()["data"]
    assert bids["total"] == 11 and all("request_title" in b for b in bids["items"])  # 6 live + 5 historical
    contracts = client.get(f"{API}/contracts", headers=fm).json()["data"]
    assert contracts["total"] == 7


def test_firm_signs_contract_and_bids_on_open_request(client, demo):
    firm = login(client, "firm@irongate.sa", PASSWORD)
    pending = client.get(f"{API}/contracts?status=pending_firm_signature", headers=firm).json()["data"]["items"]
    assert len(pending) == 1
    res = client.post(f"{API}/contracts/{pending[0]['id']}/sign", headers=firm)
    assert res.json()["data"]["status"]["code"] == "pending_facility_approval"

    my_bids = client.get(f"{API}/bids", headers=firm).json()["data"]
    assert my_bids["total"] == 6  # 3 live + 3 historical wins
    open_requests = client.get(f"{API}/requests?status=open", headers=firm).json()["data"]["items"]
    bid_on = {b["request_id"] for b in my_bids["items"]}
    target = next(r for r in open_requests if r["id"] not in bid_on)
    res = client.post(f"{API}/requests/{target['id']}/bids", json={"price_per_guard": "11000"}, headers=firm)
    assert res.status_code == 201, res.text


def test_shamoos_logs_are_masked_and_restricted(client, demo):
    admin = login(client, "admin@irongate.sa", "AdminPass123")
    logs = client.get(f"{API}/shamoos/logs", headers=admin).json()["data"]
    assert logs["total"] >= 18
    assert all("•" in item["national_id"] for item in logs["items"])
    assert {item["result"]["code"] for item in logs["items"]} <= {"verified", "rejected", "error"}

    fm = login(client, "facility@irongate.sa", PASSWORD)
    assert client.get(f"{API}/shamoos/logs", headers=fm).status_code == 403
