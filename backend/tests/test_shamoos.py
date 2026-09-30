import random

from app.models.enums import ShamoosStatus
from app.services.shamoos import MockShamoosClient, get_shamoos_client

API = "/api/v1"


def test_mock_endpoint_returns_verified_or_rejected(client, shamoos):
    res = client.post(f"{API}/shamoos/verify", json={"national_id": "1012345678"})
    assert res.status_code == 200
    assert res.json()["data"]["result"] == "Verified"

    shamoos.status = ShamoosStatus.REJECTED
    res = client.post(f"{API}/shamoos/verify", json={"national_id": "2012345678"}, headers={"Accept-Language": "ar"})
    data = res.json()["data"]
    assert data["result"] == "Rejected"
    assert data["result_label"] == "مرفوض أمنياً"


def test_mock_client_is_random_but_bounded():
    client = MockShamoosClient(approval_rate=0.5, rng=random.Random(42))
    outcomes = {client.verify("1000000000").status for _ in range(50)}
    assert outcomes == {ShamoosStatus.VERIFIED, ShamoosStatus.REJECTED}


def test_mock_outage_returns_503(client):
    from app.main import app

    app.dependency_overrides[get_shamoos_client] = lambda: MockShamoosClient(approval_rate=1, failure_rate=1)
    res = client.post(f"{API}/shamoos/verify", json={"national_id": "1012345678"})
    assert res.status_code == 503
    assert res.json()["code"] == "shamoos.service_unavailable"
