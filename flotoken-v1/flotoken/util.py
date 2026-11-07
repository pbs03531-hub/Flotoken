"""Small shared helpers: time (IST), API errors, input cleaning, simple rate limiting."""
import re
import time
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now_ms():
    return int(time.time() * 1000)


def today():
    return datetime.now(IST).strftime("%Y-%m-%d")


def ist(ms):
    return datetime.fromtimestamp(ms / 1000, IST)


class ApiError(Exception):
    """Raise anywhere in an API route; the app turns it into a JSON error response."""

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


def parse_date(value, default):
    if not value:
        return default
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ApiError(400, "Dates must look like 2026-10-31")
    return value


def clean_text(value, max_len, field="Value", required=False):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if required and not text:
        raise ApiError(400, f"{field} is required")
    if len(text) > max_len:
        raise ApiError(400, f"{field} must be at most {max_len} characters")
    return text


def clean_phone(value):
    """Keep digits and a leading +, at most 15 characters. Empty is allowed."""
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)[:15]
    return ("+" if raw.startswith("+") and digits else "") + digits


def as_int(value, field, low, high):
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise ApiError(400, f"{field} must be a whole number")
    if not low <= value <= high:
        raise ApiError(400, f"{field} must be between {low} and {high}")
    return value


_hits = {}


def rate_limit(key, limit, window_seconds, message="Too many attempts. Please wait a few minutes."):
    """In-memory limiter (per process). Good enough for one restaurant; use Redis if you scale out."""
    now = time.time()
    recent = [t for t in _hits.get(key, []) if now - t < window_seconds]
    if len(recent) >= limit:
        raise ApiError(429, message)
    recent.append(now)
    _hits[key] = recent
