"""
tests/test_config_loader.py — Unit tests for _load_folders() in main.py.

These tests are written in RED phase (PR 1). The updated implementation of
_load_folders (and the FoldersConfig / ReportConfig types) lives in PR 2.
All tests are expected to FAIL until main.py is updated.

Tested:
    FoldersConfig — NamedTuple/dataclass with fields: clean, report
    ReportConfig  — NamedTuple/dataclass with fields: source_folder, subfolders
    _load_folders(config_path: str) -> FoldersConfig
    ConfigError   — exception for invalid configuration
"""

import json
import tempfile
import os
import unittest


def _write_json(data) -> str:
    """Write data as JSON to a temp file and return the file path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class TestLoadFoldersLegacyArrayFormat(unittest.TestCase):
    """Legacy format: JSON array of objects with 'path' key."""

    def _import(self):
        from onedrive_rpa.main import _load_folders, FoldersConfig
        return _load_folders, FoldersConfig

    def test_legacy_array_format(self):
        """
        A plain JSON array (legacy format) must be parsed into
        FoldersConfig(clean=[...], report=None).
        """
        _load_folders, FoldersConfig = self._import()
        data = [{"path": "pruebas/folder_a"}, {"path": "pruebas/folder_b"}]
        path = _write_json(data)
        try:
            result = _load_folders(path)
            self.assertIsInstance(result, FoldersConfig)
            self.assertEqual(result.clean, ["pruebas/folder_a", "pruebas/folder_b"])
            self.assertIsNone(result.report)
        finally:
            os.unlink(path)


class TestLoadFoldersModernObjectFormat(unittest.TestCase):
    """Modern format: JSON object with 'clean' and optional 'report' keys."""

    def _import(self):
        from onedrive_rpa.main import _load_folders, FoldersConfig, ReportConfig
        return _load_folders, FoldersConfig, ReportConfig

    def test_modern_object_format(self):
        """
        A JSON object with both 'clean' and 'report' keys must produce a
        FoldersConfig with both fields populated.
        """
        _load_folders, FoldersConfig, ReportConfig = self._import()
        data = {
            "clean": [{"path": "pruebas/folder_a"}],
            "report": {
                "source_folder": "Documents/registros",
                "destination_folder": "Documents/reportes",
            },
        }
        path = _write_json(data)
        try:
            result = _load_folders(path)
            self.assertIsInstance(result, FoldersConfig)
            self.assertEqual(result.clean, ["pruebas/folder_a"])
            self.assertIsNotNone(result.report)
            self.assertIsInstance(result.report, ReportConfig)
            self.assertEqual(result.report.source_folder, "Documents/registros")
            self.assertEqual(result.report.destination_folder, "Documents/reportes")
        finally:
            os.unlink(path)

    def test_modern_no_report_key(self):
        """
        A JSON object with only the 'clean' key (no 'report') must produce
        FoldersConfig with report=None.
        """
        _load_folders, FoldersConfig, ReportConfig = self._import()
        data = {"clean": [{"path": "pruebas/folder_a"}]}
        path = _write_json(data)
        try:
            result = _load_folders(path)
            self.assertIsInstance(result, FoldersConfig)
            self.assertIsNone(result.report)
        finally:
            os.unlink(path)

    def test_modern_null_report(self):
        """
        A JSON object with 'report': null must produce FoldersConfig with report=None.
        """
        _load_folders, FoldersConfig, ReportConfig = self._import()
        data = {"clean": [{"path": "pruebas/folder_a"}], "report": None}
        path = _write_json(data)
        try:
            result = _load_folders(path)
            self.assertIsInstance(result, FoldersConfig)
            self.assertIsNone(result.report)
        finally:
            os.unlink(path)


class TestLoadFoldersErrorCases(unittest.TestCase):
    """Invalid configurations that must raise ConfigError."""

    def _import(self):
        from onedrive_rpa.main import _load_folders, ConfigError
        return _load_folders, ConfigError

    def test_half_configured_report_raises(self):
        """
        A 'report' object with only 'source_folder' (missing 'destination_folder') must
        raise ConfigError.
        """
        _load_folders, ConfigError = self._import()
        data = {
            "clean": [{"path": "pruebas/folder_a"}],
            "report": {"source_folder": "Documents/registros"},
        }
        path = _write_json(data)
        try:
            with self.assertRaises(ConfigError):
                _load_folders(path)
        finally:
            os.unlink(path)

    def test_missing_clean_raises(self):
        """
        A JSON object without the required 'clean' key must raise ConfigError.
        """
        _load_folders, ConfigError = self._import()
        data = {
            "report": {
                "source_folder": "Reportes",
                "subfolders": ["sub_a"],
            }
        }
        path = _write_json(data)
        try:
            with self.assertRaises(ConfigError):
                _load_folders(path)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
