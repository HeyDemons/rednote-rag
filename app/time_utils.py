"""
Time helpers shared across the app.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return a naive UTC datetime without deprecated utcnow()."""
    return datetime.now(UTC).replace(tzinfo=None)
