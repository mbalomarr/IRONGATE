import os

os.environ["SLA_JOB_ENABLED"] = "false"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SEED_ADMIN_EMAIL"] = "admin@irongate.sa"
os.environ["SEED_ADMIN_PASSWORD"] = "AdminPass123"

from typing import Dict, Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import get_db  # noqa: E402
from app.db.seed import seed_reference_data, seed_super_admin  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, City, Sector  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.enums import ShamoosStatus  # noqa: E402
from app.services.shamoos import ShamoosClient, ShamoosResult, get_shamoos_client  # noqa: E402

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class FixedShamoosClient(ShamoosClient):
    def __init__(self, status: ShamoosStatus = ShamoosStatus.VERIFIED) -> None:
        self.status = status

    def verify(self, national_id: str) -> ShamoosResult:
        return ShamoosResult(national_id, self.status, "SHM-TEST", utcnow())


@pytest.fixture
def db() -> Iterator[Session]:
    Base.metadata.create_all(engine)
    session = TestingSession()
    seed_reference_data(session)
    seed_super_admin(session)
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def shamoos() -> FixedShamoosClient:
    return FixedShamoosClient()


@pytest.fixture
def client(db: Session, shamoos: FixedShamoosClient) -> Iterator[TestClient]:
    def _get_db() -> Iterator[Session]:
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_shamoos_client] = lambda: shamoos
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def city_ids(db: Session) -> Dict[str, int]:
    return {c.code: c.id for c in db.scalars(select(City))}


@pytest.fixture
def sector_ids(db: Session) -> Dict[str, int]:
    return {s.code: s.id for s in db.scalars(select(Sector))}


def login(client: TestClient, email: str, password: str) -> Dict[str, str]:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['data']['access_token']}"}
