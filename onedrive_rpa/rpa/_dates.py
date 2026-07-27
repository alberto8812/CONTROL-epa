"""
rpa/_dates.py — Holiday-aware expiry date calculation.

Pure functions, no Playwright dependency. Used by main.py to extend a
sharing link's expiry date by a fixed number of days when the sharing
period crosses at least one public holiday.

Real holiday data comes from the third-party ``holidays`` package
(fail-open: any failure — missing package, unknown country code, network-
independent lookup errors — logs a warning and leaves the expiry
unchanged). Tests inject ``holiday_dates`` explicitly to avoid depending
on the package's data or on network access.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

from loguru import logger

from onedrive_rpa import config


def holidays_in_period(
    start: date,
    end: date,
    *,
    country: str,
    holiday_dates: "Iterable[date] | None" = None,
) -> list[date]:
    """Return the sorted, deduplicated holidays within the CLOSED interval [start, end].

    Args:
        start: First day of the period (inclusive).
        end: Last day of the period (inclusive).
        country: ISO country code passed to ``holidays.country_holidays``
                 when *holiday_dates* is not supplied.
        holiday_dates: Optional explicit iterable of holiday dates to check
                       against, bypassing the ``holidays`` package entirely.
                       Tests should always pass this to avoid network/package
                       dependence.

    Returns:
        Sorted list of unique ``date`` objects that fall within
        ``[start, end]`` (both ends inclusive). Empty list if none.
    """
    if holiday_dates is None:
        try:
            import holidays as holidays_pkg

            years = range(start.year, end.year + 1)
            candidate_dates = holidays_pkg.country_holidays(country, years=years).keys()
        except Exception as exc:
            logger.warning(
                "HOLIDAYS_UNAVAILABLE | country={c} | reason={r}",
                c=country,
                r=str(exc),
            )
            return []
    else:
        candidate_dates = holiday_dates

    matched = {d for d in candidate_dates if start <= d <= end}
    return sorted(matched)


def adjust_expiry_for_holidays(
    start: datetime,
    expiry: datetime,
    *,
    country: str = config.SHARE_HOLIDAY_COUNTRY,
    extra_days: int = config.SHARE_HOLIDAY_EXTENSION_DAYS,
    holiday_dates: "Iterable[date] | None" = None,
) -> datetime:
    """Extend *expiry* by *extra_days* if any holiday falls within [start, expiry].

    The interval checked is CLOSED on both ends: ``[start.date(), expiry.date()]``.

    IMPORTANT — this adjustment is FLAT and applied AT MOST ONCE. It is
    intentionally NOT recursive/rolling: if the newly-extended expiry date
    itself lands on (or crosses into) another holiday, that is NOT rechecked
    and NO further extension is applied. This is a deliberate product
    decision, not an oversight — do not "fix" this into a loop later without
    reconfirming the requirement.

    Fail-open contract: if real holiday lookup fails for any reason (package
    missing, invalid/unknown country code, etc.), a warning is logged and the
    original *expiry* is returned unchanged — this must never raise and must
    never block a run.

    Args:
        start: Start of the sharing period (time-of-day is ignored for the
               holiday check but irrelevant to the returned value's date part).
        expiry: The un-adjusted expiry datetime. Time-of-day is preserved in
                the result.
        country: ISO country code for the holiday calendar. Defaults to
                 ``config.SHARE_HOLIDAY_COUNTRY``.
        extra_days: Number of days to add when a holiday is found. Defaults
                    to ``config.SHARE_HOLIDAY_EXTENSION_DAYS``.
        holiday_dates: Optional explicit iterable of holiday dates, bypassing
                       the ``holidays`` package. Tests should always pass this.

    Returns:
        ``expiry`` unchanged, or ``expiry + timedelta(days=extra_days)`` if at
        least one holiday falls within the closed interval.
    """
    if holiday_dates is None:
        try:
            import holidays as holidays_pkg

            years = range(start.year, expiry.year + 1)
            candidate_dates = holidays_pkg.country_holidays(country, years=years).keys()
        except Exception as exc:
            logger.warning(
                "HOLIDAYS_UNAVAILABLE | country={c} | reason={r}",
                c=country,
                r=str(exc),
            )
            return expiry
    else:
        candidate_dates = holiday_dates

    found = holidays_in_period(start.date(), expiry.date(), country=country, holiday_dates=candidate_dates)
    if found:
        return expiry + timedelta(days=extra_days)
    return expiry
