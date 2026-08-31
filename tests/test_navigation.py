"""
tests/test_navigation.py — Unit tests for _scroll_until_stable() in rpa/_navigation.py.

Uses a stubbed `page`/row/locator object graph (no Playwright/browser dependency)
whose mounted rows are driven by a scripted sequence of per-nudge name lists —
matching the real accumulate-distinct-names stopping semantics, not raw counts.
"""

import unittest
from types import SimpleNamespace
from unittest import mock


class _FakeNameLocator:
    """Stub for row.locator(SELECTORS["item_name"])."""

    def __init__(self, name: str):
        self._name = name

    def inner_text(self, timeout: int = 2_000) -> str:
        return self._name


class _FakeRow:
    """Stub row Locator exposing only what _read_row() touches."""

    def __init__(self, name: str):
        self._name = name
        self.scroll_calls = 0

    def locator(self, selector: str):
        if "field-DocIcon" in selector:
            raise Exception("no icon in this stub — treated as a file")
        return _FakeNameLocator(self._name)

    def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
        self.scroll_calls += 1


class _FakePage:
    """
    Minimal page stub exposing only what _scroll_until_stable() touches.

    `name_sequence` is a list of "snapshots" — each snapshot is the list of
    names mounted at that point in time. The first snapshot is the initial
    read (before any nudge); each subsequent snapshot is what's mounted
    right after the corresponding nudge. Once the sequence is exhausted the
    last snapshot repeats forever (simulating a DOM that stopped changing).
    """

    def __init__(self, name_sequence: list[list[str]]):
        self._name_sequence = name_sequence
        self._index = 0
        self.wheel_calls = 0
        self.wait_calls: list[int] = []
        self.mouse = SimpleNamespace(wheel=self._wheel)

    def _wheel(self, dx: int, dy: int) -> None:
        self.wheel_calls += 1

    def locator(self, selector: str) -> "_FakeRowsLocator":
        snapshot = self._name_sequence[min(self._index, len(self._name_sequence) - 1)]
        return _FakeRowsLocator([_FakeRow(name) for name in snapshot])

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_calls.append(ms)
        # Advance to the next snapshot only once settle-wait fires — mirrors
        # the real flow where each nudge is followed by exactly one settle wait.
        if self._index < len(self._name_sequence) - 1:
            self._index += 1


class _FakeRowsLocator:
    def __init__(self, rows: list[_FakeRow]):
        self._rows = rows

    def all(self) -> list[_FakeRow]:
        return self._rows

    def count(self) -> int:
        return len(self._rows)


class TestScrollUntilStable(unittest.TestCase):
    """Tests for _scroll_until_stable()."""

    def _fn(self):
        from onedrive_rpa.rpa._navigation import _scroll_until_stable
        return _scroll_until_stable

    def test_stops_when_distinct_names_stabilize(self):
        """
        Distinct-name accumulation across nudges: 20 → 60 → 103 → 103 → 103.
        Each snapshot after the 103-name one repeats the same 103 names, so
        two consecutive nudges add zero NEW names and the loop must stop.
        """
        _scroll_until_stable = self._fn()
        names_20 = [f"item-{i}" for i in range(20)]
        names_60 = [f"item-{i}" for i in range(60)]
        names_103 = [f"item-{i}" for i in range(103)]
        page = _FakePage([names_20, names_60, names_103, names_103, names_103])

        result = _scroll_until_stable(page)

        self.assertEqual(len(result), 103)
        self.assertEqual(set(result.keys()), set(names_103))

    def test_does_not_stop_early_when_row_count_shrinks_but_new_names_appear(self):
        """
        Sliding-window regression guard: raw mounted-row count SHRINKS
        (61 → 43) between nudges, but the 43-row snapshot contains names
        never seen before. The old count-based stopping logic would have
        kept going (counts never repeated) or, worse, could have been
        fooled by a coincidental count match — the new logic must judge
        "seen everything" purely by distinct-name accumulation and must NOT
        stop just because the row count dropped.
        """
        _scroll_until_stable = self._fn()
        window_1 = [f"item-{i}" for i in range(31)]
        window_2 = [f"item-{i}" for i in range(61)]  # grew: 31 -> 61
        # Shrunk to 43 rows, but 20 of them are brand new names (61..80).
        window_3 = [f"item-{i}" for i in range(41, 84)]
        # Final snapshot repeats the same distinct names as window_3 twice
        # in a row so the loop has a legitimate place to stop.
        final_names = sorted(set(window_1) | set(window_2) | set(window_3))
        page = _FakePage([window_1, window_2, window_3, window_3, window_3])

        result = _scroll_until_stable(page)

        self.assertEqual(set(result.keys()), set(final_names))
        # Every name across every window must have been retained, even the
        # ones that unmounted again in a later, smaller window.
        for name in window_2:
            self.assertIn(name, result)

    def test_non_stabilizing_sequence_hits_max_passes_and_warns(self):
        """
        Every nudge introduces a brand-new distinct name that never repeats
        — accumulation never stabilizes, so the loop must exhaust
        LIST_SCROLL_MAX_PASSES and log a WARNING instead of looping forever.
        """
        from onedrive_rpa.config import LIST_SCROLL_MAX_PASSES

        _scroll_until_stable = self._fn()
        # One extra distinct name per snapshot, one snapshot per pass plus
        # the initial read — never repeats, so new_count is never 0.
        snapshots = [
            [f"item-{i}" for i in range(n)]
            for n in range(1, LIST_SCROLL_MAX_PASSES + 3)
        ]
        page = _FakePage(snapshots)

        with mock.patch("onedrive_rpa.rpa._navigation.logger") as mock_logger:
            result = _scroll_until_stable(page)
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            self.assertIn("SCROLL_MAX_PASSES_REACHED", warning_msg)

        # Initial read (snapshot[0]) + LIST_SCROLL_MAX_PASSES nudges lands on
        # snapshot[LIST_SCROLL_MAX_PASSES], which has MAX_PASSES + 1 names.
        self.assertEqual(len(result), LIST_SCROLL_MAX_PASSES + 1)

    def test_single_stable_read_pair_after_growth(self):
        """A short growing-then-flat sequence stops as soon as two equal reads occur."""
        _scroll_until_stable = self._fn()
        names_5 = [f"item-{i}" for i in range(5)]
        page = _FakePage([names_5, names_5, names_5])

        result = _scroll_until_stable(page)

        self.assertEqual(set(result.keys()), set(names_5))


class TestNamesMatch(unittest.TestCase):
    """Tests for names_match() — folder/file name comparison.

    OneDrive item names are compared against names typed by a human in
    folders.json. SharePoint itself treats item names case-insensitively
    (two items differing only in case cannot coexist in one folder), so the
    comparison must not be a raw `==`.
    """

    def _fn(self):
        from onedrive_rpa.rpa._navigation import names_match
        return names_match

    def test_exact_match(self):
        names_match = self._fn()
        self.assertTrue(names_match("Bz23ii", "Bz23ii"))

    def test_case_insensitive_match(self):
        """The real 2026-08-31 failure: folders.json says 'BZ23ii', the DOM
        row reads 'Bz23ii'. Navigation works (SharePoint URLs ignore case)
        but the row lookup used to miss it forever."""
        names_match = self._fn()
        self.assertTrue(names_match("Bz23ii", "BZ23ii"))
        self.assertTrue(names_match("BZ24KK", "bz24kk"))

    def test_surrounding_whitespace_ignored(self):
        names_match = self._fn()
        self.assertTrue(names_match("  Bz23ii ", "Bz23ii"))

    def test_unicode_composition_ignored(self):
        """'Tecnología' typed on macOS (NFD) must match the NFC form OneDrive
        renders — otherwise two visually identical names never compare equal."""
        names_match = self._fn()
        nfc = "Tecnolog\u00eda"          # í as a single code point
        nfd = "Tecnologi\u0301a"         # i + combining acute
        self.assertTrue(names_match(nfc, nfd))

    def test_different_names_do_not_match(self):
        names_match = self._fn()
        self.assertFalse(names_match("Bz23ii", "Bz24kk"))

    def test_empty_never_matches_non_empty(self):
        names_match = self._fn()
        self.assertFalse(names_match("", "Bz23ii"))


if __name__ == "__main__":
    unittest.main()
