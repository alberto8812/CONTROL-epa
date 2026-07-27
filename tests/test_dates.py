"""
tests/test_dates.py — Unit tests for rpa/_dates.py (holiday-aware expiry).

Covered:
    holidays_in_period(start, end, *, country, holiday_dates=None) -> list[date]
    adjust_expiry_for_holidays(start, expiry, *, country, extra_days, holiday_dates=None) -> datetime

All cases use explicit holiday_dates= (no network, no dependence on the
`holidays` package's actual calendar data), except the final smoke test
which validates the real package/API is wired correctly.
"""

import unittest
from datetime import date, datetime, timedelta


class TestAdjustExpiryForHolidays(unittest.TestCase):
    """Tests for adjust_expiry_for_holidays()."""

    def _import(self):
        from onedrive_rpa.rpa._dates import adjust_expiry_for_holidays
        return adjust_expiry_for_holidays

    def test_holiday_strictly_inside_period_adds_one_day(self):
        """Holiday strictly between start and expiry -> +1 day."""
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 6, 1, 10, 0)
        expiry = datetime(2026, 6, 10, 10, 0)
        result = adjust_expiry_for_holidays(
            start, expiry, country="CO", holiday_dates=[date(2026, 6, 5)]
        )
        self.assertEqual(result, expiry + timedelta(days=1))

    def test_no_holiday_in_period_unchanged(self):
        """No holiday anywhere near the period -> expiry unchanged."""
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 6, 1, 10, 0)
        expiry = datetime(2026, 6, 10, 10, 0)
        result = adjust_expiry_for_holidays(
            start, expiry, country="CO", holiday_dates=[date(2026, 3, 1)]
        )
        self.assertEqual(result, expiry)

    def test_holiday_on_start_boundary_adds_one_day(self):
        """Holiday exactly on start date -> +1 (closed interval)."""
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 6, 1, 10, 0)
        expiry = datetime(2026, 6, 10, 10, 0)
        result = adjust_expiry_for_holidays(
            start, expiry, country="CO", holiday_dates=[date(2026, 6, 1)]
        )
        self.assertEqual(result, expiry + timedelta(days=1))

    def test_holiday_on_expiry_boundary_adds_one_day(self):
        """Holiday exactly on the un-adjusted expiry date -> +1 (closed interval)."""
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 6, 1, 10, 0)
        expiry = datetime(2026, 6, 10, 10, 0)
        result = adjust_expiry_for_holidays(
            start, expiry, country="CO", holiday_dates=[date(2026, 6, 10)]
        )
        self.assertEqual(result, expiry + timedelta(days=1))

    def test_holiday_one_day_before_start_unchanged(self):
        """Holiday strictly before start (outside closed interval) -> unchanged."""
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 6, 1, 10, 0)
        expiry = datetime(2026, 6, 10, 10, 0)
        result = adjust_expiry_for_holidays(
            start, expiry, country="CO", holiday_dates=[date(2026, 5, 31)]
        )
        self.assertEqual(result, expiry)

    def test_holiday_one_day_after_base_expiry_unchanged_no_rolling(self):
        """Holiday one day after the (un-adjusted) expiry -> unchanged.

        Proves the adjustment does NOT recheck the newly-extended date
        (no rolling/recursive extension).
        """
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 6, 1, 10, 0)
        expiry = datetime(2026, 6, 10, 10, 0)
        result = adjust_expiry_for_holidays(
            start, expiry, country="CO", holiday_dates=[date(2026, 6, 11)]
        )
        self.assertEqual(result, expiry)

    def test_multiple_holidays_inside_add_only_one_day(self):
        """Multiple holidays inside the period -> +1 only, never +N."""
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 6, 1, 10, 0)
        expiry = datetime(2026, 6, 10, 10, 0)
        result = adjust_expiry_for_holidays(
            start,
            expiry,
            country="CO",
            holiday_dates=[date(2026, 6, 3), date(2026, 6, 5), date(2026, 6, 7)],
        )
        self.assertEqual(result, expiry + timedelta(days=1))

    def test_time_of_day_preserved(self):
        """Result must preserve the original expiry's time-of-day."""
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 6, 1, 14, 37, 22)
        expiry = datetime(2026, 6, 10, 14, 37, 22)
        result = adjust_expiry_for_holidays(
            start, expiry, country="CO", holiday_dates=[date(2026, 6, 5)]
        )
        self.assertEqual(result.time(), expiry.time())

    def test_extra_days_override_honored(self):
        """extra_days= overrides the default extension length."""
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 6, 1, 10, 0)
        expiry = datetime(2026, 6, 10, 10, 0)
        result = adjust_expiry_for_holidays(
            start, expiry, country="CO", extra_days=3, holiday_dates=[date(2026, 6, 5)]
        )
        self.assertEqual(result, expiry + timedelta(days=3))

    def test_invalid_country_fail_open_no_exception(self):
        """Invalid/unknown country with holiday_dates=None -> fail-open, no exception."""
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 6, 1, 10, 0)
        expiry = datetime(2026, 6, 10, 10, 0)
        try:
            result = adjust_expiry_for_holidays(
                start, expiry, country="ZZ_NOT_A_REAL_COUNTRY", holiday_dates=None
            )
        except Exception as exc:  # pragma: no cover - must never happen
            self.fail(f"adjust_expiry_for_holidays raised unexpectedly: {exc}")
        self.assertEqual(result, expiry)

    def test_year_spanning_period_with_jan_1_holiday(self):
        """Period crossing Dec -> Jan with a Jan 1 holiday -> +1 day."""
        adjust_expiry_for_holidays = self._import()
        start = datetime(2026, 12, 28, 9, 0)
        expiry = datetime(2027, 1, 5, 9, 0)
        result = adjust_expiry_for_holidays(
            start, expiry, country="CO", holiday_dates=[date(2027, 1, 1)]
        )
        self.assertEqual(result, expiry + timedelta(days=1))


class TestHolidaysInPeriod(unittest.TestCase):
    """Tests for holidays_in_period()."""

    def _import(self):
        from onedrive_rpa.rpa._dates import holidays_in_period
        return holidays_in_period

    def test_returns_sorted_deduped_list(self):
        """Duplicate and out-of-order holidays are deduped and sorted."""
        holidays_in_period = self._import()
        result = holidays_in_period(
            date(2026, 6, 1),
            date(2026, 6, 10),
            country="CO",
            holiday_dates=[date(2026, 6, 7), date(2026, 6, 3), date(2026, 6, 3)],
        )
        self.assertEqual(result, [date(2026, 6, 3), date(2026, 6, 7)])

    def test_empty_when_none_in_period(self):
        """No holidays within the interval -> empty list."""
        holidays_in_period = self._import()
        result = holidays_in_period(
            date(2026, 6, 1),
            date(2026, 6, 10),
            country="CO",
            holiday_dates=[date(2026, 1, 1)],
        )
        self.assertEqual(result, [])

    def test_closed_interval_includes_boundaries(self):
        """Holidays exactly on start/end boundaries are included."""
        holidays_in_period = self._import()
        result = holidays_in_period(
            date(2026, 6, 1),
            date(2026, 6, 10),
            country="CO",
            holiday_dates=[date(2026, 6, 1), date(2026, 6, 10), date(2026, 5, 31), date(2026, 6, 11)],
        )
        self.assertEqual(result, [date(2026, 6, 1), date(2026, 6, 10)])


class TestRealHolidaysPackage(unittest.TestCase):
    """Smoke test against the real `holidays` package (skipped if unavailable)."""

    def test_colombia_real_holidays_contains_2027_jan_1(self):
        try:
            import holidays as holidays_pkg
        except ImportError:
            self.skipTest("holidays package is not installed")

        co_holidays = holidays_pkg.country_holidays("CO", years=[2027])
        self.assertIn(date(2027, 1, 1), co_holidays)


if __name__ == "__main__":
    unittest.main()
