"""
tests/test_reporter.py — Unit tests for pure functions in rpa/reporter.py.

These tests are written in RED phase (PR 1). The implementation lives in PR 2.
All tests are expected to FAIL until reporter.py is implemented.

Tested functions:
    generate_password(length: int = REPORT_PASSWORD_LENGTH) -> str
    build_report_rows(folder_names: list[str], now: datetime | None) -> list[dict]
    write_excel(rows: list[dict]) -> BytesIO
    build_report_filename(dt: datetime | None) -> str
"""

import re
import unittest
from datetime import datetime
from io import BytesIO

from onedrive_rpa.config import REPORT_PASSWORD_LENGTH, REPORT_PASSWORD_ALPHABET


class TestGeneratePassword(unittest.TestCase):
    """Tests for generate_password()."""

    def _import(self):
        from onedrive_rpa.rpa.reporter import generate_password
        return generate_password

    def test_generate_password_length(self):
        """Generated password must have exactly REPORT_PASSWORD_LENGTH characters."""
        generate_password = self._import()
        pwd = generate_password()
        self.assertEqual(len(pwd), REPORT_PASSWORD_LENGTH)

    def test_generate_password_alphabet(self):
        """Every character in the password must be from REPORT_PASSWORD_ALPHABET."""
        generate_password = self._import()
        pwd = generate_password()
        allowed = set(REPORT_PASSWORD_ALPHABET)
        for ch in pwd:
            self.assertIn(ch, allowed, f"Character {ch!r} is not in allowed alphabet")

    def test_generate_password_no_quotes_10k_samples(self):
        """Over 10 000 iterations the password must never contain \" or '."""
        generate_password = self._import()
        for _ in range(10_000):
            pwd = generate_password()
            self.assertNotIn('"', pwd)
            self.assertNotIn("'", pwd)

    def test_generate_password_min_length_raises(self):
        """generate_password(15) must raise ValueError (minimum is 16)."""
        generate_password = self._import()
        with self.assertRaises(ValueError):
            generate_password(15)


class TestBuildReportRows(unittest.TestCase):
    """Tests for build_report_rows()."""

    def _import(self):
        from onedrive_rpa.rpa.reporter import build_report_rows
        return build_report_rows

    def test_build_report_rows_count(self):
        """3 folder names must produce exactly 3 rows."""
        build_report_rows = self._import()
        names = ["alpha", "beta", "gamma"]
        rows = build_report_rows(names)
        self.assertEqual(len(rows), 3)

    def test_build_report_rows_keys(self):
        """Each row dict must contain folder_name, password, and creation_date keys."""
        build_report_rows = self._import()
        rows = build_report_rows(["alpha"])
        self.assertIn("folder_name", rows[0])
        self.assertIn("password", rows[0])
        self.assertIn("creation_date", rows[0])

    def test_build_report_rows_injected_now(self):
        """creation_date in each row must equal the injected 'now' parameter."""
        build_report_rows = self._import()
        fixed_now = datetime(2026, 5, 22, 10, 30, 0)
        rows = build_report_rows(["alpha", "beta"], now=fixed_now)
        for row in rows:
            self.assertEqual(row["creation_date"], fixed_now)


class TestWriteExcel(unittest.TestCase):
    """Tests for write_excel()."""

    def _import(self):
        from onedrive_rpa.rpa.reporter import write_excel
        return write_excel

    def test_write_excel_round_trip(self):
        """
        write_excel must return a BytesIO that openpyxl can read back.
        The workbook must contain the expected header and at least one data row.
        """
        import openpyxl

        write_excel = self._import()

        rows = [
            {"folder_name": "alpha", "password": "abc123", "creation_date": datetime(2026, 5, 22)},
            {"folder_name": "beta",  "password": "xyz789", "creation_date": datetime(2026, 5, 22)},
        ]
        result = write_excel(rows)

        self.assertIsInstance(result, BytesIO)

        # Should be seeked to 0 so openpyxl can read from the start
        wb = openpyxl.load_workbook(result)
        ws = wb.active

        # Header row
        headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        self.assertIn("Folder Name", headers)
        self.assertIn("Password", headers)
        self.assertIn("Creation Date", headers)

        # Data rows (should have 2)
        data_rows = list(ws.iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(data_rows), 2)


class TestBuildReportFilename(unittest.TestCase):
    """Tests for build_report_filename()."""

    def _import(self):
        from onedrive_rpa.rpa.reporter import build_report_filename
        return build_report_filename

    def test_build_report_filename_format(self):
        """Filename must match the pattern reporte_YYYYMMDD_HHMMSS.xlsx."""
        build_report_filename = self._import()
        filename = build_report_filename()
        pattern = r"^reporte_\d{8}_\d{6}\.xlsx$"
        self.assertRegex(filename, pattern, f"Filename {filename!r} does not match expected pattern")


if __name__ == "__main__":
    unittest.main()
