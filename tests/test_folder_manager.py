"""
tests/test_folder_manager.py — Unit tests for pure functions in folder_manager.py.

Covers:
    validate_path(raw) -> str
    load_folders(path) -> dict
    save_folders(path, model) -> None

These tests do NOT mock questionary or Rich — the interaction layer (run(),
_add_folder(), etc.) is excluded by design (pure/interaction split).

Written in TDD RED phase. Tests fail against stubs (pass bodies), then go
GREEN after Phase 3 implementation.
"""

import json
import unittest
from pathlib import Path


# ---------------------------------------------------------------------------
# validate_path
# ---------------------------------------------------------------------------


class TestValidatePath(unittest.TestCase):
    """Task 2.1 — validate_path scenarios from FM-2."""

    def _fn(self):
        from novahome.modules.folder_manager import validate_path
        return validate_path

    def test_valid_relative_path_returned(self):
        """A valid relative path is returned stripped."""
        validate_path = self._fn()
        result = validate_path("  pruebas/archivos_1  ")
        self.assertEqual(result, "pruebas/archivos_1")

    def test_valid_simple_path_returned(self):
        """A simple single-component path is returned unchanged."""
        validate_path = self._fn()
        result = validate_path("Documents")
        self.assertEqual(result, "Documents")

    def test_absolute_path_raises(self):
        """Absolute paths must raise FolderValidationError."""
        from novahome.modules.folder_manager import FolderValidationError
        validate_path = self._fn()
        with self.assertRaises(FolderValidationError):
            validate_path("/absolute/path")

    def test_dotdot_component_raises(self):
        """Paths with '..' in any component must raise FolderValidationError."""
        from novahome.modules.folder_manager import FolderValidationError
        validate_path = self._fn()
        with self.assertRaises(FolderValidationError):
            validate_path("../sibling")

    def test_dotdot_in_middle_raises(self):
        """Paths with '..' in the middle must raise FolderValidationError."""
        from novahome.modules.folder_manager import FolderValidationError
        validate_path = self._fn()
        with self.assertRaises(FolderValidationError):
            validate_path("foo/../bar")

    def test_empty_string_raises(self):
        """Empty string must raise FolderValidationError."""
        from novahome.modules.folder_manager import FolderValidationError
        validate_path = self._fn()
        with self.assertRaises(FolderValidationError):
            validate_path("")

    def test_whitespace_only_raises(self):
        """Whitespace-only string must raise FolderValidationError."""
        from novahome.modules.folder_manager import FolderValidationError
        validate_path = self._fn()
        with self.assertRaises(FolderValidationError):
            validate_path("   ")


# ---------------------------------------------------------------------------
# load_folders
# ---------------------------------------------------------------------------


class TestLoadFolders(unittest.TestCase):
    """Task 2.2 — load_folders scenarios from FM-1, FM-6."""

    def _fn(self):
        from novahome.modules.folder_manager import load_folders
        return load_folders

    def test_missing_file_returns_empty_model(self, tmp_path=None):
        """Missing folders.json → {"clean": [], "report": None}."""
        import tempfile, os
        load_folders = self._fn()
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "folders.json"
            result = load_folders(missing)
        self.assertEqual(result["clean"], [])
        self.assertIsNone(result["report"])

    def test_legacy_array_of_strings(self):
        """Legacy JSON array of plain strings → clean list, report=None."""
        import tempfile
        load_folders = self._fn()
        data = ["pruebas/folder_a", "pruebas/folder_b"]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f)
            path = Path(f.name)
        try:
            result = load_folders(path)
            self.assertEqual(result["clean"], ["pruebas/folder_a", "pruebas/folder_b"])
            self.assertIsNone(result["report"])
        finally:
            path.unlink(missing_ok=True)

    def test_legacy_array_of_path_dicts(self):
        """Legacy JSON array of {'path': ...} dicts → clean list, report=None."""
        import tempfile
        load_folders = self._fn()
        data = [{"path": "pruebas/folder_a"}, {"path": "pruebas/folder_b"}]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f)
            path = Path(f.name)
        try:
            result = load_folders(path)
            self.assertEqual(result["clean"], ["pruebas/folder_a", "pruebas/folder_b"])
            self.assertIsNone(result["report"])
        finally:
            path.unlink(missing_ok=True)

    def test_modern_object_with_report(self):
        """Modern object with report section → full model."""
        import tempfile
        load_folders = self._fn()
        data = {
            "clean": [{"path": "pruebas/folder_a"}],
            "report": {
                "source_folder": "Documents/registros",
                "destination_folder": "Documents/reportes",
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f)
            path = Path(f.name)
        try:
            result = load_folders(path)
            self.assertEqual(result["clean"], ["pruebas/folder_a"])
            self.assertIsNotNone(result["report"])
            self.assertEqual(result["report"]["source_folder"], "Documents/registros")
            self.assertEqual(result["report"]["destination_folder"], "Documents/reportes")
        finally:
            path.unlink(missing_ok=True)

    def test_modern_object_without_report(self):
        """Modern object with only 'clean' key → report=None."""
        import tempfile
        load_folders = self._fn()
        data = {"clean": [{"path": "pruebas/folder_a"}]}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f)
            path = Path(f.name)
        try:
            result = load_folders(path)
            self.assertEqual(result["clean"], ["pruebas/folder_a"])
            self.assertIsNone(result["report"])
        finally:
            path.unlink(missing_ok=True)

    def test_modern_object_null_report(self):
        """Modern object with 'report': null → report=None."""
        import tempfile
        load_folders = self._fn()
        data = {"clean": [{"path": "pruebas/folder_a"}], "report": None}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f)
            path = Path(f.name)
        try:
            result = load_folders(path)
            self.assertIsNone(result["report"])
        finally:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# save_folders
# ---------------------------------------------------------------------------


class TestSaveFolders(unittest.TestCase):
    """Task 2.3 — save_folders scenarios from FM-6 (upgrade-on-save)."""

    def _fn(self):
        from novahome.modules.folder_manager import save_folders, load_folders
        return save_folders, load_folders

    def test_round_trip_writes_modern_schema(self):
        """save + load round-trip always produces modern object schema."""
        import tempfile
        save_folders, load_folders = self._fn()
        model = {"clean": ["pruebas/folder_a", "pruebas/folder_b"], "report": None}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "folders.json"
            save_folders(path, model)
            # Verify raw JSON uses modern object schema
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(written, dict)
            self.assertIn("clean", written)
            self.assertIsInstance(written["clean"], list)
            for entry in written["clean"]:
                self.assertIsInstance(entry, dict)
                self.assertIn("path", entry)

    def test_report_none_key_omitted(self):
        """When report is None, the 'report' key must NOT appear in the written JSON."""
        import tempfile
        save_folders, _ = self._fn()
        model = {"clean": ["pruebas/folder_a"], "report": None}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "folders.json"
            save_folders(path, model)
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("report", written)

    def test_report_dict_key_present(self):
        """When report is a dict, it must appear in the written JSON."""
        import tempfile
        save_folders, _ = self._fn()
        report = {"source_folder": "Src", "destination_folder": "Dst"}
        model = {"clean": ["pruebas/folder_a"], "report": report}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "folders.json"
            save_folders(path, model)
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("report", written)
            self.assertEqual(written["report"]["source_folder"], "Src")
            self.assertEqual(written["report"]["destination_folder"], "Dst")

    def test_upgrade_legacy_on_save(self):
        """save of a model loaded from legacy format writes modern schema."""
        import tempfile
        save_folders, load_folders = self._fn()
        # Write a legacy JSON array
        legacy_data = ["pruebas/folder_a", "pruebas/folder_b"]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "folders.json"
            path.write_text(json.dumps(legacy_data), encoding="utf-8")
            # Load and re-save (simulates the upgrade-on-save behaviour)
            model = load_folders(path)
            save_folders(path, model)
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(written, dict)
            self.assertIn("clean", written)
            self.assertEqual(len(written["clean"]), 2)
            for entry in written["clean"]:
                self.assertIn("path", entry)


# FM-7 (empty clean list confirmation gate in _remove_folder) is interaction-layer
# behavior — it requires questionary prompts and is covered by manual smoke test 6.2.

if __name__ == "__main__":
    unittest.main()
