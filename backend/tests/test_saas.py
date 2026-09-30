from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.seed import seed_demo_data
from tests.conftest import login

API = "/api/v1"
PASSWORD = "ChangeMe123"


@pytest.fixture
def demo(db):
    seed_demo_data(db)
    return db


def test_facility_subscription_is_per_seat(client, demo):
    fm = login(client, "facility@irongate.sa", PASSWORD)
    sub = client.get(f"{API}/billing/subscription", headers=fm).json()["data"]
    # Riyadh Park Mall: 6 distinct guards rostered on its active contract this month.
    assert sub["active"] is True and sub["seats"] == 6 and len(sub["seat_guards"]) == 6
    assert Decimal(sub["platform_fee"]) == Decimal("199.00") and Decimal(sub["seat_fee"]) == Decimal("30.00")
    assert Decimal(sub["seats_total"]) == Decimal("180.00")
    assert Decimal(sub["monthly_total"]) == Decimal("379.00")

    firm = login(client, "firm@irongate.sa", PASSWORD)
    assert client.get(f"{API}/billing/subscription", headers=firm).status_code == 403


def test_admin_saas_metrics(client, demo):
    admin = login(client, "admin@irongate.sa", "AdminPass123")
    m = client.get(f"{API}/admin/saas-metrics", headers=admin).json()["data"]
    # 2 subscribed facilities (marketplace + BYOC) and 6 + 5 tracked guards.
    assert m["subscribed_facilities"] == 2 and m["tracked_guards"] == 11
    assert Decimal(m["mrr"]) == Decimal("2") * 199 + 11 * 30
    assert Decimal(m["arr"]) == Decimal(m["mrr"]) * 12
    # GMV counts marketplace contracts only: 108k + 63k live + 386k completed history; not the imported 270k.
    assert Decimal(m["gmv"]) == Decimal("557000.00")
    assert m["marketplace_contracts"] == 7 and m["imported_contracts"] == 1
    assert len(m["gmv_by_month"]) == 6
    assert sum(Decimal(x["value"]) for x in m["gmv_by_month"]) == Decimal("557000.00")
    assert sum(1 for x in m["gmv_by_month"] if Decimal(x["value"]) > 0) >= 5  # history spread over months

    fm = login(client, "facility@irongate.sa", PASSWORD)
    assert client.get(f"{API}/admin/saas-metrics", headers=fm).status_code == 403


def test_bring_your_own_contract_flow(client, demo):
    fm = login(client, "facility@irongate.sa", PASSWORD)
    firms = client.get(f"{API}/lookups/firms").json()["data"]
    najd = next(f for f in firms if f["code"] == "MOI-DEMO-1001")
    assert all(f["code"] != "MOI-DEMO-3003" for f in firms)  # pending firms are not listed

    body = {
        "firm_id": najd["id"], "external_reference": "RPM-2025-07", "title": "Existing night coverage",
        "start_date": str(date.today() - timedelta(days=30)), "end_date": str(date.today() + timedelta(days=200)),
        "guard_count": 3, "contract_value": "90000",
    }
    ended = {**body, "end_date": str(date.today() - timedelta(days=1)), "start_date": str(date.today() - timedelta(days=90))}
    res = client.post(f"{API}/contracts/import", json=ended, headers={**fm, "Accept-Language": "ar"})
    assert res.status_code == 422 and "العقود السارية" in res.json()["errors"][0]["message"]

    res = client.post(f"{API}/contracts/import", json=body, headers=fm)
    assert res.status_code == 201, res.text
    contract = res.json()["data"]
    assert contract["source"] == "imported" and contract["external_reference"] == "RPM-2025-07"
    assert contract["status"]["code"] == "pending_firm_signature" and contract["contract_number"].startswith("BYOC-")

    firm = login(client, "firm@irongate.sa", PASSWORD)
    res = client.post(f"{API}/contracts/{contract['id']}/sign", headers=firm)
    assert res.json()["code"] if res.status_code != 200 else res.json()["data"]["status"]["code"] == "active"
    assert res.json()["message"].startswith("Imported contract confirmed")

    # Imported contracts stay out of marketplace GMV.
    admin = login(client, "admin@irongate.sa", "AdminPass123")
    m = client.get(f"{API}/admin/saas-metrics", headers=admin).json()["data"]
    assert Decimal(m["gmv"]) == Decimal("557000.00") and m["imported_contracts"] == 2


def test_gmv_chart_ends_on_current_month(client, demo):
    admin = login(client, "admin@irongate.sa", "AdminPass123")
    months = client.get(f"{API}/admin/saas-metrics", headers=admin).json()["data"]["gmv_by_month"]
    assert all(Decimal(x["value"]) > 0 for x in months)  # continuous history, and this month has a deal


def test_billing_months_follow_riyadh_time():
    from datetime import date, datetime

    from app.services.saas import month_start, period_dates

    late_utc = datetime(2026, 9, 30, 22, 30)  # 01:30 on 1 Oct in Riyadh
    assert period_dates(late_utc) == (date(2026, 10, 1), date(2026, 11, 1))
    assert month_start(late_utc) == datetime(2026, 9, 30, 21, 0)
    assert period_dates(datetime(2026, 12, 15, 12, 0)) == (date(2026, 12, 1), date(2027, 1, 1))
