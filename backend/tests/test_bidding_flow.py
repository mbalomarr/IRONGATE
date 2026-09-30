from datetime import date, timedelta

from tests.conftest import login

API = "/api/v1"
ADMIN = ("admin@irongate.sa", "AdminPass123")


def _register_firm(client, city_ids, email="firm@shield.sa", license_no="MOI-12345"):
    res = client.post(
        f"{API}/auth/register/firm",
        json={
            "email": email,
            "password": "FirmPass123",
            "full_name": "Firm Manager",
            "firm": {
                "name": "Shield Security",
                "name_ar": "درع للحراسات الأمنية",
                "moi_license_number": license_no,
                "license_expiry_date": str(date.today() + timedelta(days=730)),
                "headquarters_city_id": city_ids["riyadh"],
                "operating_city_ids": [city_ids["jeddah"]],
            },
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["data"]


def _register_facility(client, city_ids, sector_ids):
    res = client.post(
        f"{API}/auth/register/facility",
        json={
            "email": "fm@mall.sa",
            "password": "MallPass123",
            "full_name": "Facility Manager",
            "facility": {
                "name": "Riyadh Park Mall",
                "name_ar": "رياض بارك مول",
                "sector_id": sector_ids["shopping_mall"],
                "city_id": city_ids["riyadh"],
                "latitude": "24.7560",
                "longitude": "46.6290",
                "geofence_radius_m": 300,
            },
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["data"]


def test_full_bidding_flow(client, city_ids, sector_ids):
    admin = login(client, *ADMIN)
    firm = _register_firm(client, city_ids)
    assert firm["organization_status"]["code"] == "pending"
    firm_mgr = login(client, "firm@shield.sa", "FirmPass123")

    # Firm Manager creates an HR/Dispatcher, who builds and verifies the roster.
    res = client.post(
        f"{API}/auth/users",
        headers=firm_mgr,
        json={"email": "hr@shield.sa", "password": "HrPass1234", "full_name": "HR", "role": "hr_dispatcher"},
    )
    assert res.status_code == 201, res.text
    hr = login(client, "hr@shield.sa", "HrPass1234")

    for i in range(3):
        res = client.post(
            f"{API}/guards",
            headers=hr,
            json={"national_id": f"10000000{i:02d}", "full_name": f"Guard {i}", "city_id": city_ids["riyadh"]},
        )
        assert res.status_code == 201, res.text
        guard_id = res.json()["data"]["id"]
        res = client.post(f"{API}/shamoos/guards/{guard_id}/verify", headers=hr)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["shamoos_status"]["code"] == "verified"

    # Client posts a request.
    _register_facility(client, city_ids, sector_ids)
    fm = login(client, "fm@mall.sa", "MallPass123")
    start = date.today() + timedelta(days=7)
    res = client.post(
        f"{API}/requests",
        headers=fm,
        json={"title": "Weekend coverage", "guard_count": 2, "start_date": str(start), "end_date": str(start + timedelta(days=29))},
    )
    assert res.status_code == 201, res.text
    request_id = res.json()["data"]["id"]
    assert res.json()["data"]["status"]["code"] == "open"

    # Unapproved firm cannot bid, and is not recommended.
    res = client.post(f"{API}/requests/{request_id}/bids", headers=firm_mgr, json={"price_per_guard": "9000.00"})
    assert res.status_code == 403
    assert res.json()["code"] == "firm.not_approved"
    assert client.get(f"{API}/requests/{request_id}/recommended-firms", headers=fm).json()["data"] == []

    # Super Admin approves the firm -> it is now recommended with 3 available guards.
    res = client.post(f"{API}/admin/firms/{firm['organization_id']}/approve", headers=admin)
    assert res.status_code == 200, res.text
    recs = client.get(f"{API}/requests/{request_id}/recommended-firms", headers=fm).json()["data"]
    assert [r["available_guards"] for r in recs] == [3]

    # Firm sees the open request in its area and bids.
    listing = client.get(f"{API}/requests", headers=firm_mgr).json()["data"]
    assert listing["total"] == 1
    res = client.post(f"{API}/requests/{request_id}/bids", headers=firm_mgr, json={"price_per_guard": "9000.00"})
    assert res.status_code == 201, res.text
    bid = res.json()["data"]
    assert bid["total_price"] == "18000.00"
    res = client.post(f"{API}/requests/{request_id}/bids", headers=firm_mgr, json={"price_per_guard": "8000.00"})
    assert res.status_code == 409

    # Operations has no financial access to bids.
    client.post(
        f"{API}/auth/users",
        headers=admin,
        json={"email": "ops@irongate.sa", "password": "OpsPass123", "full_name": "Ops", "role": "operations"},
    )
    ops = login(client, "ops@irongate.sa", "OpsPass123")
    assert client.get(f"{API}/requests/{request_id}/bids", headers=ops).status_code == 403

    # Facility compares, accepts; firm signs; facility approves.
    bids = client.get(f"{API}/requests/{request_id}/bids", headers=fm).json()["data"]
    assert len(bids) == 1 and bids[0]["is_lowest"] is True
    res = client.post(f"{API}/bids/{bid['id']}/accept", headers=fm)
    assert res.status_code == 200, res.text
    contract = res.json()["data"]
    assert contract["status"]["code"] == "pending_firm_signature"
    assert contract["total_value"] == "18000.00"

    assert client.post(f"{API}/contracts/{contract['id']}/approve", headers=fm).status_code == 409
    res = client.post(f"{API}/contracts/{contract['id']}/sign", headers=firm_mgr)
    assert res.json()["data"]["status"]["code"] == "pending_facility_approval"
    res = client.post(f"{API}/contracts/{contract['id']}/approve", headers=fm)
    assert res.json()["data"]["status"]["code"] == "active"

    req = client.get(f"{API}/requests/{request_id}", headers=fm).json()["data"]
    assert req["status"]["code"] == "active"

    # Those 2 guards are now committed: only 1 left for an overlapping request.
    res = client.post(
        f"{API}/requests",
        headers=fm,
        json={"title": "Extra", "guard_count": 2, "start_date": str(start), "end_date": str(start + timedelta(days=5))},
    )
    second_id = res.json()["data"]["id"]
    res = client.post(
        f"{API}/requests/{second_id}/bids",
        headers={**firm_mgr, "Accept-Language": "ar"},
        json={"price_per_guard": "1000"},
    )
    assert res.status_code == 422
    assert res.json()["code"] == "bid.insufficient_capacity"
    assert "المتاح: 1" in res.json()["message"]


def test_rbac_blocks_wrong_roles(client, city_ids, sector_ids):
    _register_facility(client, city_ids, sector_ids)
    fm = login(client, "fm@mall.sa", "MallPass123")
    # Facility Manager can't add guards or create HR users.
    assert client.post(f"{API}/guards", headers=fm, json={"national_id": "1000000001", "full_name": "Xavier", "city_id": 1}).status_code == 403
    res = client.post(
        f"{API}/auth/users",
        headers=fm,
        json={"email": "x@mall.sa", "password": "Passw0rd1", "full_name": "Xavier", "role": "hr_dispatcher"},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "auth.role_not_assignable"
    # Unauthenticated
    assert client.get(f"{API}/auth/me").status_code == 401
