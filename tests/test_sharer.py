"""
tests/test_sharer.py — Unit tests for pure helpers in rpa/sharer.py.

Covered:
    folder_key(folder_path: str) -> str
    _format_expiry(dt: datetime) -> str
    _parse_month_year(label: str) -> tuple[int, int]
    _month_delta(from_my, to_my) -> int
    _expiry_matches(actual: str, expected: datetime) -> bool
    _day_button_selector(day: int, month_name: str, year: int) -> str
    ShareStats dataclass default state and list operations
"""

import unittest
from datetime import datetime
from types import SimpleNamespace


class TestFormatExpiry(unittest.TestCase):
    """Tests for _format_expiry()."""

    def _import(self):
        from onedrive_rpa.rpa.sharer import _format_expiry
        return _format_expiry

    def test_format_expiry_basic(self):
        """Fixed datetime 2026-05-30 must format as '30/05/2026'."""
        _format_expiry = self._import()
        result = _format_expiry(datetime(2026, 5, 30))
        self.assertEqual(result, "30/05/2026")

    def test_format_expiry_zero_padding_day(self):
        """Single-digit day must be zero-padded: 2026-06-08 -> '08/06/2026'."""
        _format_expiry = self._import()
        result = _format_expiry(datetime(2026, 6, 8))
        self.assertEqual(result, "08/06/2026")

    def test_format_expiry_zero_padding_month(self):
        """Single-digit month must be zero-padded: 2026-01-05 -> '05/01/2026'."""
        _format_expiry = self._import()
        result = _format_expiry(datetime(2026, 1, 5))
        self.assertEqual(result, "05/01/2026")

    def test_format_expiry_double_digit_day_and_month(self):
        """Two-digit day and month produce no extra padding."""
        _format_expiry = self._import()
        result = _format_expiry(datetime(2026, 12, 31))
        self.assertEqual(result, "31/12/2026")


class TestFolderKey(unittest.TestCase):
    """Tests for folder_key()."""

    def _import(self):
        from onedrive_rpa.rpa.sharer import folder_key
        return folder_key

    def test_folder_key_simple(self):
        """'a/b/c' -> 'c'."""
        folder_key = self._import()
        self.assertEqual(folder_key("a/b/c"), "c")

    def test_folder_key_no_slash(self):
        """'folder' -> 'folder' (no slash)."""
        folder_key = self._import()
        self.assertEqual(folder_key("folder"), "folder")

    def test_folder_key_nested_path(self):
        """'pruebas/archivos_1' -> 'archivos_1'."""
        folder_key = self._import()
        self.assertEqual(folder_key("pruebas/archivos_1"), "archivos_1")

    def test_folder_key_trailing_slash(self):
        """'a/b/' -> 'b' (trailing slash stripped)."""
        folder_key = self._import()
        self.assertEqual(folder_key("a/b/"), "b")

    def test_folder_key_single_level_trailing_slash(self):
        """'documentos/' -> 'documentos'."""
        folder_key = self._import()
        self.assertEqual(folder_key("documentos/"), "documentos")


class TestShareStats(unittest.TestCase):
    """Tests for ShareStats dataclass."""

    def _import(self):
        from onedrive_rpa.rpa.sharer import ShareStats
        return ShareStats

    def test_sharestate_default_shared_empty(self):
        """ShareStats() must have shared == []."""
        ShareStats = self._import()
        stats = ShareStats()
        self.assertEqual(stats.shared, [])

    def test_sharestate_default_share_errors_empty(self):
        """ShareStats() must have share_errors == []."""
        ShareStats = self._import()
        stats = ShareStats()
        self.assertEqual(stats.share_errors, [])

    def test_sharestate_append_shared(self):
        """Appending to stats.shared works correctly."""
        ShareStats = self._import()
        stats = ShareStats()
        stats.shared.append("folder_a")
        stats.shared.append("folder_b")
        self.assertEqual(len(stats.shared), 2)
        self.assertIn("folder_a", stats.shared)

    def test_sharestate_append_share_errors(self):
        """Appending to stats.share_errors works correctly."""
        ShareStats = self._import()
        stats = ShareStats()
        stats.share_errors.append("folder_x")
        self.assertEqual(len(stats.share_errors), 1)
        self.assertEqual(stats.share_errors[0], "folder_x")

    def test_sharestate_instances_are_independent(self):
        """Two ShareStats instances must not share list references."""
        ShareStats = self._import()
        stats_a = ShareStats()
        stats_b = ShareStats()
        stats_a.shared.append("a")
        self.assertEqual(stats_b.shared, [])

    def test_sharestate_default_share_urls_empty(self):
        """ShareStats() must have share_urls == {}."""
        ShareStats = self._import()
        stats = ShareStats()
        self.assertEqual(stats.share_urls, {})

    def test_sharestate_default_share_skipped_empty(self):
        """ShareStats() must have share_skipped == []."""
        ShareStats = self._import()
        self.assertEqual(ShareStats().share_skipped, [])

    def test_sharestate_share_urls_accepts_entries(self):
        """share_urls dict must accept folder_key -> URL entries."""
        ShareStats = self._import()
        stats = ShareStats()
        stats.share_urls["archivos_1"] = "https://archacomco-my.sharepoint.com/:f:/r/test"
        self.assertEqual(stats.share_urls["archivos_1"], "https://archacomco-my.sharepoint.com/:f:/r/test")

    def test_sharestate_share_urls_instances_are_independent(self):
        """Two ShareStats instances must not share the share_urls dict reference."""
        ShareStats = self._import()
        stats_a = ShareStats()
        stats_b = ShareStats()
        stats_a.share_urls["a"] = "https://example.com/a"
        self.assertEqual(stats_b.share_urls, {})


class TestParseMonthYear(unittest.TestCase):
    """Tests for _parse_month_year()."""

    def _import(self):
        from onedrive_rpa.rpa.sharer import _parse_month_year
        return _parse_month_year

    def test_spanish_with_de(self):
        """'agosto de 2026' -> (8, 2026)."""
        _parse_month_year = self._import()
        self.assertEqual(_parse_month_year("agosto de 2026"), (8, 2026))

    def test_english(self):
        """'August 2026' -> (8, 2026)."""
        _parse_month_year = self._import()
        self.assertEqual(_parse_month_year("August 2026"), (8, 2026))

    def test_spanish_enero(self):
        """'enero de 2027' -> (1, 2027)."""
        _parse_month_year = self._import()
        self.assertEqual(_parse_month_year("enero de 2027"), (1, 2027))

    def test_mixed_case(self):
        """Mixed-case month names must still parse ('AgOsTo De 2026')."""
        _parse_month_year = self._import()
        self.assertEqual(_parse_month_year("AgOsTo De 2026"), (8, 2026))

    def test_mixed_case_english(self):
        """Mixed-case English month names must still parse ('AUGUST 2026')."""
        _parse_month_year = self._import()
        self.assertEqual(_parse_month_year("AUGUST 2026"), (8, 2026))

    def test_garbage_input_raises_share_error(self):
        """Unparseable input must raise ShareError."""
        from onedrive_rpa.rpa.sharer import ShareError
        _parse_month_year = self._import()
        with self.assertRaises(ShareError):
            _parse_month_year("not a real header")


class TestMonthDelta(unittest.TestCase):
    """Tests for _month_delta()."""

    def _import(self):
        from onedrive_rpa.rpa.sharer import _month_delta
        return _month_delta

    def test_same_month_is_zero(self):
        """Same (month, year) -> 0."""
        _month_delta = self._import()
        self.assertEqual(_month_delta((2026, 8), (2026, 8)), 0)

    def test_aug_to_sep_is_plus_one(self):
        """Aug 2026 -> Sep 2026 is +1."""
        _month_delta = self._import()
        self.assertEqual(_month_delta((8, 2026), (9, 2026)), 1)

    def test_dec_2026_to_jan_2027_is_plus_one(self):
        """Dec 2026 -> Jan 2027 is +1 (year rollover)."""
        _month_delta = self._import()
        self.assertEqual(_month_delta((12, 2026), (1, 2027)), 1)

    def test_backwards_is_negative(self):
        """Jan 2027 -> Dec 2026 is -1."""
        _month_delta = self._import()
        self.assertEqual(_month_delta((1, 2027), (12, 2026)), -1)


class TestExpiryMatches(unittest.TestCase):
    """Tests for _expiry_matches() — regression coverage for the reported bug
    where an empty/whitespace input was silently accepted as a successful
    expiry-date write."""

    def _import(self):
        from onedrive_rpa.rpa.sharer import _expiry_matches
        return _expiry_matches

    def test_exact_zero_padded_match(self):
        """'08/06/2026' matches datetime(2026, 6, 8) -> True."""
        _expiry_matches = self._import()
        self.assertTrue(_expiry_matches("08/06/2026", datetime(2026, 6, 8)))

    def test_non_padded_match(self):
        """'8/6/2026' (non-zero-padded) matches datetime(2026, 6, 8) -> True."""
        _expiry_matches = self._import()
        self.assertTrue(_expiry_matches("8/6/2026", datetime(2026, 6, 8)))

    def test_wrong_day_does_not_match(self):
        """'09/06/2026' does not match datetime(2026, 6, 8) -> False."""
        _expiry_matches = self._import()
        self.assertFalse(_expiry_matches("09/06/2026", datetime(2026, 6, 8)))

    def test_empty_string_is_false(self):
        """Empty string -> False (the bug: input never received the date)."""
        _expiry_matches = self._import()
        self.assertFalse(_expiry_matches("", datetime(2026, 6, 8)))

    def test_whitespace_only_is_false(self):
        """Whitespace-only string -> False."""
        _expiry_matches = self._import()
        self.assertFalse(_expiry_matches("   ", datetime(2026, 6, 8)))

    def test_garbage_string_is_false(self):
        """'abc' -> False."""
        _expiry_matches = self._import()
        self.assertFalse(_expiry_matches("abc", datetime(2026, 6, 8)))

    def test_iso_format_is_false(self):
        """ISO-formatted date '2026-06-08' -> False (this input never produces ISO)."""
        _expiry_matches = self._import()
        self.assertFalse(_expiry_matches("2026-06-08", datetime(2026, 6, 8)))

    def test_extenso_spanish_format_with_abbreviated_month(self):
        """Real Fluent input_value() format: 'miércoles, 5 de ago de 2026'
        (confirmed via live probe) matches datetime(2026, 8, 5) -> True."""
        _expiry_matches = self._import()
        self.assertTrue(
            _expiry_matches("miércoles, 5 de ago de 2026", datetime(2026, 8, 5))
        )

    def test_extenso_spanish_format_wrong_month_is_false(self):
        """'miércoles, 5 de ago de 2026' does not match a July expiry -> False."""
        _expiry_matches = self._import()
        self.assertFalse(
            _expiry_matches("miércoles, 5 de ago de 2026", datetime(2026, 7, 5))
        )

    def test_extenso_spanish_format_full_month_name(self):
        """Full (non-abbreviated) month name variant also matches."""
        _expiry_matches = self._import()
        self.assertTrue(
            _expiry_matches("miércoles, 5 de agosto de 2026", datetime(2026, 8, 5))
        )

    def test_extenso_english_format(self):
        """English full-month extenso format also matches, in case tenant
        language differs (e.g. 'Wednesday, August 5, 2026' style variants
        using the 'de'-separated pattern are ES-specific, but a plain
        'D de Month de YYYY' with an English month token must still resolve
        via SHARE_MONTH_NAMES)."""
        _expiry_matches = self._import()
        self.assertTrue(
            _expiry_matches("5 de august de 2026", datetime(2026, 8, 5))
        )


class TestDayButtonSelector(unittest.TestCase):
    """Tests for _day_button_selector() — builds the calendar day-cell
    selector from a confirmed live DOM aria-label format:
    "{day}, {MonthName}, {year}" (no leading zero on day, no "de")."""

    def _import(self):
        from onedrive_rpa.rpa.sharer import _day_button_selector
        return _day_button_selector

    def test_basic_spanish_month(self):
        """day=6, month_name='Julio', year=2026 builds the exact aria-label match."""
        _day_button_selector = self._import()
        result = _day_button_selector(6, "Julio", 2026)
        self.assertEqual(
            result,
            "button.fui-CalendarDayGrid__dayButton[aria-label='6, Julio, 2026']",
        )

    def test_no_leading_zero_on_day(self):
        """Single-digit day must NOT be zero-padded (DOM format has no padding)."""
        _day_button_selector = self._import()
        result = _day_button_selector(1, "Agosto", 2026)
        self.assertIn("[aria-label='1, Agosto, 2026']", result)
        self.assertNotIn("01,", result)

    def test_english_month_name(self):
        """English tenant rendering ('August') is passed through unchanged."""
        _day_button_selector = self._import()
        result = _day_button_selector(31, "August", 2026)
        self.assertEqual(
            result,
            "button.fui-CalendarDayGrid__dayButton[aria-label='31, August, 2026']",
        )

    def test_scoped_to_day_grid_button_class(self):
        """Selector must be scoped to the day-grid button class so it can
        never accidentally match the unrelated
        '.od-ExpirationDatePicker-delete' ("Quitar fecha de caducidad") button."""
        _day_button_selector = self._import()
        result = _day_button_selector(15, "Julio", 2026)
        self.assertTrue(result.startswith("button.fui-CalendarDayGrid__dayButton"))
        self.assertNotIn("od-ExpirationDatePicker-delete", result)


class _RowName:
    def __init__(self, name):
        self.name = name

    def inner_text(self, timeout=2_000):
        return self.name


class _VirtualRow:
    def __init__(self, name):
        self.name = name

    def locator(self, selector):
        return _RowName(self.name)

    def scroll_into_view_if_needed(self, timeout=None):
        return None


class _VirtualRows:
    def __init__(self, names):
        self.names = names

    def all(self):
        return [_VirtualRow(name) for name in self.names]


class _VirtualPage:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.index = 0
        self.mouse = SimpleNamespace(wheel=lambda *_: None)

    def locator(self, selector):
        return _VirtualRows(self.snapshots[min(self.index, len(self.snapshots) - 1)])

    def wait_for_timeout(self, ms):
        if self.index < len(self.snapshots) - 1:
            self.index += 1


class TestFindRowByName(unittest.TestCase):
    def test_finds_target_after_constant_size_windows_swap_twice(self):
        """A constant mounted-row count must not terminate a virtualized scan."""
        from onedrive_rpa.rpa.sharer import _find_row_by_name

        page = _VirtualPage([
            ["alpha", "beta"],
            ["gamma", "delta"],
            ["target", "epsilon"],
        ])

        row = _find_row_by_name(page, "target")

        self.assertIsNotNone(row)
        self.assertEqual(row.name, "target")


    def test_finds_target_when_only_the_case_differs(self):
        """Regression for the 2026-08-24 / 2026-08-31 runs.

        folders.json spells the folder 'BZ23ii'; the OneDrive row renders
        'Bz23ii'. Navigation succeeded (SharePoint URLs ignore case) so the
        folder was cleaned, but the share-row lookup compared with a raw
        `==` and raised 'Folder row not found in DOM' on every retry.
        """
        from onedrive_rpa.rpa.sharer import _find_row_by_name

        page = _VirtualPage([["alpha", "Bz23ii", "beta"]])

        row = _find_row_by_name(page, "BZ23ii")

        self.assertIsNotNone(row)
        self.assertEqual(row.name, "Bz23ii")

    def test_finds_target_case_insensitively_after_scrolling(self):
        """The case-folded comparison must also apply to rows that only
        mount after a scroll nudge, not just the first-paint scan."""
        from onedrive_rpa.rpa.sharer import _find_row_by_name

        page = _VirtualPage([
            ["alpha", "beta"],
            ["gamma", "delta"],
            ["Bz24kk", "epsilon"],
        ])

        row = _find_row_by_name(page, "BZ24kk")

        self.assertIsNotNone(row)
        self.assertEqual(row.name, "Bz24kk")

    def test_unrelated_name_still_not_found(self):
        """Folding case must not turn a genuine miss into a false match."""
        from onedrive_rpa.rpa.sharer import _find_row_by_name

        page = _VirtualPage([["alpha", "beta"]])

        self.assertIsNone(_find_row_by_name(page, "Bz23ii"))


if __name__ == "__main__":
    unittest.main()
