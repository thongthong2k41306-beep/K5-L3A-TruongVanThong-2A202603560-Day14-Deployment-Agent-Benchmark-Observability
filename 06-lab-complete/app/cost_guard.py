"""Reserve and settle a shared daily mock-LLM budget atomically in Redis."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Integer nanodollars avoid accumulating binary floating-point errors.
UNITS_PER_USD = Decimal(1_000_000_000)
PRICE_INPUT_PER_1K = settings.price_input_per_1k
PRICE_OUTPUT_PER_1K = settings.price_output_per_1k

_RESERVE = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
local budget = tonumber(ARGV[1])
local amount = tonumber(ARGV[2])
if used >= budget or used + amount > budget then return 0 end
redis.call('INCRBY', KEYS[1], amount)
redis.call('EXPIREAT', KEYS[1], ARGV[3])
return 1
"""
_SETTLE = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local updated = math.max(0, current + tonumber(ARGV[1]))
redis.call('SET', KEYS[1], updated)
redis.call('EXPIREAT', KEYS[1], ARGV[2])
return updated
"""


@dataclass(frozen=True)
class BudgetReservation:
    key: str
    units: int
    expires_at: int


def estimate_cost(input_tokens: int, output_tokens: int) -> Decimal:
    return (Decimal(input_tokens) * PRICE_INPUT_PER_1K
            + Decimal(output_tokens) * PRICE_OUTPUT_PER_1K) / 1000


def _units(cost: Decimal) -> int:
    return int((cost * UNITS_PER_USD).to_integral_value(rounding=ROUND_CEILING))


def check_budget(estimated_cost: Decimal = Decimal(0)) -> BudgetReservation:
    """Reserve an upper bound before calling the mock; reject with HTTP 402."""
    now = datetime.now(timezone.utc)
    key = f"production-agent:{settings.environment}:budget:{now:%Y-%m-%d}"
    # The active key changes at UTC midnight; retain yesterday for in-flight work.
    expires = int((now.replace(hour=0, minute=0, second=0, microsecond=0)
                   + timedelta(days=2)).timestamp())
    budget = int((settings.daily_budget_usd * UNITS_PER_USD).to_integral_value(rounding=ROUND_FLOOR))
    amount = _units(estimated_cost)
    if not r.eval(_RESERVE, 1, key, budget, amount, expires):
        raise HTTPException(status_code=402, detail="Daily budget exhausted")
    return BudgetReservation(key, amount, expires)


def record_cost(input_tokens: int, output_tokens: int,
                reservation: BudgetReservation) -> float:
    cost = estimate_cost(input_tokens, output_tokens)
    r.eval(_SETTLE, 1, reservation.key, _units(cost) - reservation.units, reservation.expires_at)
    return float(cost)


def release_reservation(reservation: BudgetReservation) -> None:
    """Refund the reserved amount when the mock call fails."""
    r.eval(_SETTLE, 1, reservation.key, -reservation.units, reservation.expires_at)
