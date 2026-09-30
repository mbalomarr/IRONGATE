"""Application settings, loaded from environment variables / `.env`."""
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]  # .../backend


class Settings(BaseSettings):
    # Anchored to backend/ so the API works whether it is started from backend/ or the repo root.
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    APP_NAME: str = "Iron Gate API"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: List[str] = ["*"]

    # --- Database ---
    DATABASE_URL: str = "mysql+pymysql://irongate:irongate@localhost:3306/irongate?charset=utf8mb4"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600

    @field_validator("DATABASE_URL")
    @classmethod
    def _anchor_relative_sqlite(cls, v: str) -> str:
        """`sqlite:///./x.db` resolves against backend/, not the shell's current directory."""
        prefix = "sqlite:///./"
        return f"sqlite:///{BACKEND_DIR / v[len(prefix):]}" if v.startswith(prefix) else v

    # --- Auth ---
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # --- i18n ---
    DEFAULT_LOCALE: str = "en"
    SUPPORTED_LOCALES: List[str] = ["en", "ar"]

    # --- Mock Shamoos ---
    SHAMOOS_MOCK_APPROVAL_RATE: float = 0.8
    SHAMOOS_MOCK_FAILURE_RATE: float = 0.0

    # --- SLA / billing ---
    SLA_JOB_ENABLED: bool = True
    SLA_JOB_INTERVAL_SECONDS: int = 300
    SLA_BREACH_THRESHOLD_MINUTES: int = 30
    SLA_DEFAULT_PENALTY_AMOUNT: Decimal = Decimal("500.00")
    SLA_DEFAULT_MAX_PENALTY_PERCENT: Decimal = Decimal("10.00")
    PLATFORM_COMMISSION_RATE: Decimal = Decimal("0.10")
    CLOCK_IN_EARLY_MINUTES: int = 30  # guards may clock in this long before a shift starts
    SAAS_PLATFORM_FEE: Decimal = Decimal("199.00")  # SAR / facility / month
    SAAS_SEAT_FEE: Decimal = Decimal("30.00")  # SAR / tracked guard / month
    CURRENCY: str = "SAR"

    # --- Seeding ---
    SEED_ADMIN_EMAIL: Optional[str] = None
    SEED_ADMIN_PASSWORD: Optional[str] = None
    SEED_ADMIN_NAME: str = "Platform Admin"
    SEED_DEMO_DATA: bool = True  # demo firm/facility/guard accounts + a live scenario
    SEED_DEMO_PASSWORD: str = "ChangeMe123"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
