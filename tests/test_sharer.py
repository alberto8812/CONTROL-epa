"""
tests/test_sharer.py — Unit tests for pure helpers in rpa/sharer.py.

Covered:
    folder_key(folder_path: str) -> str
    _format_expiry(dt: datetime) -> str
    ShareStats dataclass default state and list operations
"""

import unittest
from datetime import datetime


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


if __name__ == "__main__":
    unittest.main()
