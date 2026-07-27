"""
tests/test_cleaner.py — Unit tests for pure/offline logic in rpa/cleaner.py.

Covered:
    CleanStats.incomplete (default, merge, incomplete_count)
    _diff_listing(pending, remaining) -> (confirmed_deleted, still_pending, newly_appeared)
    FolderCleaner._process_items() file branch — verify-and-redo loop

No Playwright dependency: the loop tests use unittest.mock.patch to stub
list_items() and _bulk_delete_files() at module level, and a bare Mock() as
the "page" object (never touches a real browser).
"""

import unittest
from unittest import mock


# ---------------------------------------------------------------------------
# CleanStats
# ---------------------------------------------------------------------------


class TestCleanStats(unittest.TestCase):
    """Tests for CleanStats.incomplete / merge() / incomplete_count."""

    def _cls(self):
        from onedrive_rpa.rpa.cleaner import CleanStats
        return CleanStats

    def test_incomplete_defaults_empty(self):
        CleanStats = self._cls()
        stats = CleanStats()
        self.assertEqual(stats.incomplete, [])

    def test_incomplete_count_zero_by_default(self):
        CleanStats = self._cls()
        stats = CleanStats()
        self.assertEqual(stats.incomplete_count, 0)

    def test_incomplete_count_matches_length(self):
        CleanStats = self._cls()
        stats = CleanStats(incomplete=["a/b", "c/d", "e/f"])
        self.assertEqual(stats.incomplete_count, 3)

    def test_merge_concatenates_incomplete(self):
        CleanStats = self._cls()
        a = CleanStats(incomplete=["a/b"])
        b = CleanStats(incomplete=["c/d"])
        a.merge(b)
        self.assertEqual(a.incomplete, ["a/b", "c/d"])

    def test_merge_does_not_mutate_other(self):
        CleanStats = self._cls()
        a = CleanStats(incomplete=["a/b"])
        b = CleanStats(incomplete=["c/d"])
        a.merge(b)
        self.assertEqual(b.incomplete, ["c/d"])


# ---------------------------------------------------------------------------
# _diff_listing (pure)
# ---------------------------------------------------------------------------


class TestDiffListing(unittest.TestCase):
    """Tests for _diff_listing() — pure set comparison, no Playwright."""

    def _fn(self):
        from onedrive_rpa.rpa.cleaner import _diff_listing
        return _diff_listing

    def test_all_deleted(self):
        """Nothing remains → everything pending is confirmed deleted."""
        _diff_listing = self._fn()
        pending = {"a.pdf", "b.pdf", "c.pdf"}
        remaining = set()
        confirmed, still_pending, appeared = _diff_listing(pending, remaining)
        self.assertEqual(confirmed, ["a.pdf", "b.pdf", "c.pdf"])
        self.assertEqual(still_pending, set())
        self.assertEqual(appeared, [])

    def test_none_deleted(self):
        """Remaining == pending → nothing confirmed, everything still pending."""
        _diff_listing = self._fn()
        pending = {"a.pdf", "b.pdf"}
        remaining = {"a.pdf", "b.pdf"}
        confirmed, still_pending, appeared = _diff_listing(pending, remaining)
        self.assertEqual(confirmed, [])
        self.assertEqual(still_pending, {"a.pdf", "b.pdf"})
        self.assertEqual(appeared, [])

    def test_partial_deletion(self):
        """Some names disappear, others remain."""
        _diff_listing = self._fn()
        pending = {"a.pdf", "b.pdf", "c.pdf"}
        remaining = {"b.pdf"}
        confirmed, still_pending, appeared = _diff_listing(pending, remaining)
        self.assertEqual(confirmed, ["a.pdf", "c.pdf"])
        self.assertEqual(still_pending, {"b.pdf"})
        self.assertEqual(appeared, [])

    def test_newly_appeared_not_counted_as_deleted_or_pending(self):
        """A name in remaining but not in pending (concurrent upload) is
        reported separately — it is neither a confirmed deletion nor
        something to retry, since it was never part of the delete request."""
        _diff_listing = self._fn()
        pending = {"a.pdf"}
        remaining = {"a.pdf", "new_upload.pdf"}
        confirmed, still_pending, appeared = _diff_listing(pending, remaining)
        self.assertEqual(confirmed, [])
        self.assertEqual(still_pending, {"a.pdf"})
        self.assertEqual(appeared, ["new_upload.pdf"])

    def test_empty_inputs(self):
        _diff_listing = self._fn()
        confirmed, still_pending, appeared = _diff_listing(set(), set())
        self.assertEqual(confirmed, [])
        self.assertEqual(still_pending, set())
        self.assertEqual(appeared, [])


# ---------------------------------------------------------------------------
# FolderCleaner._process_items() — verify-and-redo loop
# ---------------------------------------------------------------------------


class TestProcessItemsVerifyLoop(unittest.TestCase):
    """
    Tests the bounded verify-and-redo loop in _process_items()'s file branch.

    list_items() and _bulk_delete_files() are patched at module level so no
    Playwright/browser dependency is required. `page` is a bare Mock().
    """

    def _make_items(self, n: int, prefix: str = "file"):
        from onedrive_rpa.rpa._navigation import ItemInfo
        return [ItemInfo(name=f"{prefix}_{i}.pdf", is_folder=False) for i in range(n)]

    def _make_cleaner(self):
        from onedrive_rpa.rpa.cleaner import FolderCleaner
        page = mock.Mock()
        return FolderCleaner(page, dry_run=False), page

    def test_converging_sequence_deletes_all_and_marks_complete(self):
        """
        Scripted listing sequence 103 -> 60 -> 20 -> 0 (empty) must end with
        all 103 files in stats.deleted and stats.incomplete == [].
        """
        from onedrive_rpa.rpa import cleaner as cleaner_mod

        initial_items = self._make_items(103)
        listings = [
            initial_items,          # 1) top-level items() scan
            initial_items,          # 2) current_items (files at this level)
            self._make_items(60),   # 3) remaining after pass 1
            self._make_items(20),   # 4) remaining after pass 2
            [],                     # 5) remaining after pass 3 -> converged
        ]

        cleaner, page = self._make_cleaner()
        stats_cls = cleaner_mod.CleanStats
        stats = stats_cls()

        with mock.patch.object(cleaner_mod, "list_items", side_effect=listings), \
             mock.patch.object(cleaner_mod, "_bulk_delete_files", return_value=None), \
             mock.patch.object(cleaner_mod, "check_session_expired", return_value=None):
            cleaner._process_items("Camion/ADMIN/Bz13ff", stats)

        self.assertEqual(len(stats.deleted), 103)
        self.assertEqual(stats.incomplete, [])
        self.assertEqual(stats.errors, [])

    def test_non_converging_sequence_marks_incomplete_with_single_error_entry(self):
        """
        A listing that never shrinks must exhaust MAX_EMPTY_VERIFY_PASSES and
        mark the folder incomplete — with exactly ONE entry in stats.errors
        (the folder path), not one per remaining file.
        """
        from onedrive_rpa.rpa import cleaner as cleaner_mod
        from onedrive_rpa.config import MAX_EMPTY_VERIFY_PASSES

        same_items = self._make_items(103)
        # 2 initial scans + one re-listing per verify pass, all identical.
        listings = [same_items] * (2 + MAX_EMPTY_VERIFY_PASSES)

        cleaner, page = self._make_cleaner()
        stats_cls = cleaner_mod.CleanStats
        stats = stats_cls()

        with mock.patch.object(cleaner_mod, "list_items", side_effect=listings), \
             mock.patch.object(cleaner_mod, "_bulk_delete_files", return_value=None), \
             mock.patch.object(cleaner_mod, "check_session_expired", return_value=None):
            cleaner._process_items("Camion/ADMIN/Bz13ff", stats)

        self.assertEqual(stats.incomplete, ["Camion/ADMIN/Bz13ff"])
        self.assertEqual(stats.errors, ["Camion/ADMIN/Bz13ff"])
        self.assertEqual(stats.deleted, [])

    def test_empty_folder_returns_early_without_touching_stats(self):
        """An empty folder (no files) must return without any deleted/incomplete entries."""
        from onedrive_rpa.rpa import cleaner as cleaner_mod

        cleaner, page = self._make_cleaner()
        stats = cleaner_mod.CleanStats()

        with mock.patch.object(cleaner_mod, "list_items", side_effect=[[], []]), \
             mock.patch.object(cleaner_mod, "check_session_expired", return_value=None):
            cleaner._process_items("Empty/Folder", stats)

        self.assertEqual(stats.deleted, [])
        self.assertEqual(stats.incomplete, [])

    def test_dry_run_lists_would_delete_without_verify_loop(self):
        """dry_run=True must populate would_delete and skip the delete/verify loop entirely."""
        from onedrive_rpa.rpa import cleaner as cleaner_mod

        page = mock.Mock()
        cleaner = cleaner_mod.FolderCleaner(page, dry_run=True)
        stats = cleaner_mod.CleanStats()
        items = self._make_items(5)

        with mock.patch.object(cleaner_mod, "list_items", side_effect=[items, items]), \
             mock.patch.object(cleaner_mod, "check_session_expired", return_value=None), \
             mock.patch.object(cleaner_mod, "_bulk_delete_files") as bulk_delete:
            cleaner._process_items("Some/Folder", stats)
            bulk_delete.assert_not_called()

        self.assertEqual(len(stats.would_delete), 5)
        self.assertEqual(stats.deleted, [])
        self.assertEqual(stats.incomplete, [])

    def test_exception_mid_loop_breaks_and_records_error_once_per_pending_file(self):
        """
        A hard exception during a verify pass must stop the loop (not keep
        hammering delete) and land in stats.errors/stats.incomplete.
        """
        from onedrive_rpa.rpa import cleaner as cleaner_mod

        items = self._make_items(3)
        cleaner, page = self._make_cleaner()
        stats = cleaner_mod.CleanStats()

        with mock.patch.object(cleaner_mod, "list_items", side_effect=[items, items]), \
             mock.patch.object(cleaner_mod, "check_session_expired", return_value=None), \
             mock.patch.object(
                 cleaner_mod, "_bulk_delete_files", side_effect=RuntimeError("boom")
             ):
            cleaner._process_items("Broken/Folder", stats)

        self.assertEqual(stats.incomplete, ["Broken/Folder"])
        self.assertEqual(len(stats.errors), 3)
        self.assertEqual(stats.deleted, [])


# ---------------------------------------------------------------------------
# FolderCleaner._process_items() — empty-subfolder deletion (ADR-11)
# ---------------------------------------------------------------------------


class TestEmptySubfolderDeletion(unittest.TestCase):
    """
    Tests for the bottom-up "delete now-empty subfolder" behavior added in
    ADR-11: a subfolder found inside the root passed to clean() gets deleted
    once its own content (files + subfolders) is fully removed. The root
    itself is never deleted — only descendants are.
    """

    def _make_items(self, n: int, prefix: str = "file"):
        from onedrive_rpa.rpa._navigation import ItemInfo
        return [ItemInfo(name=f"{prefix}_{i}.pdf", is_folder=False) for i in range(n)]

    def _folder_item(self, name: str):
        from onedrive_rpa.rpa._navigation import ItemInfo
        return ItemInfo(name=name, is_folder=True)

    def _make_cleaner(self, dry_run: bool = False):
        from onedrive_rpa.rpa.cleaner import FolderCleaner
        page = mock.Mock()
        return FolderCleaner(page, dry_run=dry_run), page

    def test_subfolder_emptied_then_deleted_not_root(self):
        """
        Root contains only a subfolder ("test") with 3 files. Once those
        files are deleted, "test" itself must be deleted — but the root
        path must never be passed to the folder-delete call.
        """
        from onedrive_rpa.rpa import cleaner as cleaner_mod

        files = self._make_items(3)
        listings = [
            [self._folder_item("test")],  # 1) root scan: only "test" folder
            files,                         # 2) child "test" scan: 3 files, no subfolders
            files,                         # 3) child current_files check
            [],                             # 4) remaining after bulk delete -> converged
            [],                             # 5) root current_files check (test now removed)
        ]

        cleaner, page = self._make_cleaner()
        stats = cleaner_mod.CleanStats()

        with mock.patch.object(cleaner_mod, "list_items", side_effect=listings), \
             mock.patch.object(cleaner_mod, "_bulk_delete_files", return_value=None), \
             mock.patch.object(cleaner_mod, "check_session_expired", return_value=None), \
             mock.patch.object(cleaner_mod, "_enter_folder", return_value=None), \
             mock.patch.object(cleaner_mod, "_go_back", return_value=None), \
             mock.patch.object(cleaner_mod, "_delete_single_row", return_value=None) as delete_item:
            result = cleaner._process_items("Bz13ff", stats)

        delete_item.assert_called_once_with(page, "test")
        self.assertEqual(stats.deleted_folders, ["Bz13ff/test"])
        self.assertEqual(len(stats.deleted), 3)
        self.assertTrue(result)

    def test_incomplete_subfolder_is_not_deleted(self):
        """A subfolder whose files never fully delete must NOT be removed,
        and this must propagate up as "not empty" to the caller."""
        from onedrive_rpa.rpa import cleaner as cleaner_mod
        from onedrive_rpa.config import MAX_EMPTY_VERIFY_PASSES

        same_files = self._make_items(3)
        listings = [
            [self._folder_item("test")],           # 1) root scan
            same_files,                              # 2) child scan
            same_files,                              # 3) child current_files check
        ] + [same_files] * MAX_EMPTY_VERIFY_PASSES + [
            [],                                        # root's own current_files check
        ]

        cleaner, page = self._make_cleaner()
        stats = cleaner_mod.CleanStats()

        with mock.patch.object(cleaner_mod, "list_items", side_effect=listings), \
             mock.patch.object(cleaner_mod, "_bulk_delete_files", return_value=None), \
             mock.patch.object(cleaner_mod, "check_session_expired", return_value=None), \
             mock.patch.object(cleaner_mod, "_enter_folder", return_value=None), \
             mock.patch.object(cleaner_mod, "_go_back", return_value=None), \
             mock.patch.object(cleaner_mod, "_delete_single_row", return_value=None) as delete_item:
            result = cleaner._process_items("Bz13ff", stats)

        delete_item.assert_not_called()
        self.assertEqual(stats.deleted_folders, [])
        self.assertIn("Bz13ff/test", stats.incomplete)
        self.assertFalse(result)

    def test_dry_run_reports_would_delete_folder_without_deleting(self):
        """dry_run=True must log/report the subfolder as would-be-deleted
        without ever calling the real single-item delete."""
        from onedrive_rpa.rpa import cleaner as cleaner_mod

        files = self._make_items(2)
        listings = [
            [self._folder_item("test")],  # 1) root scan
            files,                         # 2) child scan
            files,                         # 3) child current_files check (dry-run WOULD_DELETE)
            [],                             # 4) root current_files check
        ]

        cleaner, page = self._make_cleaner(dry_run=True)
        stats = cleaner_mod.CleanStats()

        with mock.patch.object(cleaner_mod, "list_items", side_effect=listings), \
             mock.patch.object(cleaner_mod, "check_session_expired", return_value=None), \
             mock.patch.object(cleaner_mod, "_enter_folder", return_value=None), \
             mock.patch.object(cleaner_mod, "_go_back", return_value=None), \
             mock.patch.object(cleaner_mod, "_delete_single_row", return_value=None) as delete_item, \
             mock.patch.object(cleaner_mod, "_bulk_delete_files") as bulk_delete:
            result = cleaner._process_items("Bz13ff", stats)

        delete_item.assert_not_called()
        bulk_delete.assert_not_called()
        self.assertIn("Bz13ff/test", stats.would_delete)
        self.assertTrue(result)

    def test_clean_never_deletes_the_root_folder_itself(self):
        """Even when the root ends up fully empty, clean() must discard the
        returned bool and never call the folder-delete path on it."""
        from onedrive_rpa.rpa import cleaner as cleaner_mod

        cleaner, page = self._make_cleaner()

        with mock.patch.object(cleaner_mod, "navigate_to_folder", return_value=None), \
             mock.patch.object(cleaner_mod, "list_items", side_effect=[[], []]), \
             mock.patch.object(cleaner_mod, "check_session_expired", return_value=None), \
             mock.patch.object(cleaner_mod, "_delete_single_row", return_value=None) as delete_item:
            stats = cleaner.clean("Bz13ff")

        delete_item.assert_not_called()
        self.assertEqual(stats.deleted_folders, [])


if __name__ == "__main__":
    unittest.main()
