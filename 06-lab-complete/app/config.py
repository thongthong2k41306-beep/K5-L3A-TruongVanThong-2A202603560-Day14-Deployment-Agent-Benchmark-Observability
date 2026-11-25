"""Environment configuration shared by all workers."""
import math
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "10")))
    daily_budget_usd: Decimal = field(default_factory=lambda: Decimal(os.getenv("DAILY_BUDGET_USD", "1.0")))
    price_input_per_1k: Decimal = field(default_factory=lambda: Decimal(os.getenv("PRICE_INPUT_PER_1K", "0.00015")))
    price_output_per_1k: Decimal = field(default_factory=lambda: Decimal(os.getenv("PRICE_OUTPUT_PER_1K", "0.0006")))
    redis_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("REDIS_TIMEOUT_SECONDS", "1")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    def __post_init__(self):
        if not 1 <= self.port <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
        if self.rate_limit_per_minute < 1:
            raise ValueError("RATE_LIMIT_PER_MINUTE must be positive")
        for name in ("daily_budget_usd", "price_input_per_1k", "price_output_per_1k"):
            value = getattr(self, name)
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if not math.isfinite(self.redis_timeout_seconds) or self.redis_timeout_seconds <= 0:
            raise ValueError("REDIS_TIMEOUT_SECONDS must be finite and positive")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL is invalid")


settings = Settings()
