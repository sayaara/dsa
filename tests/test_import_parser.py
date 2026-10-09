# -*- coding: utf-8 -*-
"""Tests for import_parser.

Covers:
- CSV/Excel/text parsing
- Column mapping (code, name aliases)
- Encoding (utf-8, gbk)
- Name-to-code resolution (mocked)
- No-header mode (col 0 = code, col 1 = name)
- File size and text size limits
"""

import io
import pytest
from unittest.mock import patch

from src.services.import_parser import (
    parse_import_from_bytes,
    parse_import_from_text,
    MAX_FILE_BYTES,
    MAX_TEXT_BYTES,
)


# ---------------------------------------------------------------------------
# parse_import_from_bytes - CSV
# ---------------------------------------------------------------------------

class TestParseImportFromBytesCsv:
    def test_parses_csv_with_header(self):
        data = "code,name\nAAPL,Apple\nRY.TO,Royal Bank".encode("utf-8")
        result = parse_import_from_bytes(data, "a.csv")
        assert len(result) == 2
        assert result[0] == ("AAPL", "Apple", "medium")
        assert result[1] == ("RY.TO", "Royal Bank", "medium")

    def test_parses_csv_chinese_column_names(self):
        data = "股票代码,股票名称\nAAPL,Apple".encode("utf-8")
        result = parse_import_from_bytes(data, "a.csv")
        assert result[0] == ("AAPL", "Apple", "medium")

    def test_parses_utf8_bom_csv_header(self):
        data = "\ufeffcode,name\nAAPL,".encode("utf-8")
        result = parse_import_from_bytes(data, "a.csv")
        assert result == [("AAPL", None, "medium")]

    def test_parses_csv_no_header(self):
        data = "AAPL,Apple\nMSFT,Microsoft".encode("utf-8")
        result = parse_import_from_bytes(data, "a.csv")
        assert len(result) == 2
        assert result[0] == ("AAPL", "Apple", "medium")
        assert result[1] == ("MSFT", "Microsoft", "medium")

    def test_skips_empty_rows(self):
        data = "code,name\nAAPL,Apple\n\nRY.TO,Royal Bank".encode("utf-8")
        result = parse_import_from_bytes(data, "a.csv")
        assert len(result) == 2

    def test_tab_separated(self):
        data = "code\tname\nAAPL\tApple".encode("utf-8")
        result = parse_import_from_bytes(data, "paste.txt")
        assert result[0] == ("AAPL", "Apple", "medium")

    @patch("src.services.import_parser.resolve_name_to_code")
    def test_resolves_name_when_code_empty(self, mock_resolve):
        mock_resolve.return_value = "AAPL"
        # code column empty, name column has value
        data = "code,name\n,Apple Inc.".encode("utf-8")
        result = parse_import_from_bytes(data, "a.csv")
        assert result[0] == ("AAPL", "Apple Inc.", "medium")
        mock_resolve.assert_called_with("Apple Inc.")

    @patch("src.services.import_parser.resolve_name_to_code")
    def test_returns_none_code_when_resolution_fails(self, mock_resolve):
        mock_resolve.return_value = None
        data = "code,name\n,不存在的股票".encode("utf-8")
        result = parse_import_from_bytes(data, "a.csv")
        assert result[0] == (None, "不存在的股票", "medium")


# ---------------------------------------------------------------------------
# parse_import_from_bytes - Excel
# ---------------------------------------------------------------------------

class TestParseImportFromBytesExcel:
    def test_parses_xlsx(self):
        try:
            import openpyxl  # noqa: F401  (availability check)
        except ImportError:
            pytest.skip("openpyxl not installed")
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["code", "name"])
        ws.append(["AAPL", "Apple"])
        ws.append(["MSFT", "Microsoft"])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        data = buf.read()
        result = parse_import_from_bytes(data, "a.xlsx")
        assert len(result) == 2
        assert result[0] == ("AAPL", "Apple", "medium")
        assert result[1] == ("MSFT", "Microsoft", "medium")

    def test_parses_xlsx_without_header(self):
        """Header-less Excel: first data row must NOT be consumed as column names."""
        try:
            import openpyxl  # noqa: F401  (availability check)
        except ImportError:
            pytest.skip("openpyxl not installed")
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["AAPL", "Apple"])
        ws.append(["RY.TO", "Royal Bank"])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        data = buf.read()
        result = parse_import_from_bytes(data, "noheader.xlsx")
        assert len(result) == 2, f"Expected 2 rows, got {len(result)} — first row may have been eaten as header"
        codes = [r[0] for r in result]
        assert "AAPL" in codes
        assert "RY.TO" in codes

    def test_rejects_xls(self):
        data = b"dummy"
        with pytest.raises(ValueError, match="Only .xlsx is supported"):
            parse_import_from_bytes(data, "a.xls")

    def test_excel_error_includes_actionable_hint(self):
        """Excel parse failure should include hints for common causes."""
        # Invalid/corrupt xlsx (zip magic but bad content)
        data = b"PK\x03\x04" + b"x" * 100
        with pytest.raises(ValueError) as exc_info:
            parse_import_from_bytes(data, "a.xlsx")
        msg = str(exc_info.value)
        assert "Check that" in msg or ".xlsx" in msg


# ---------------------------------------------------------------------------
# Limits and encoding
# ---------------------------------------------------------------------------

class TestParseImportLimits:
    def test_rejects_file_over_limit(self):
        data = b"x" * (MAX_FILE_BYTES + 1)
        with pytest.raises(ValueError, match="exceeds"):
            parse_import_from_bytes(data, "a.csv")

    def test_rejects_text_over_limit(self):
        text = "x" * (MAX_TEXT_BYTES + 1)
        with pytest.raises(ValueError, match="exceeds"):
            parse_import_from_text(text)

    def test_csv_parser_error_raises_helpful_message(self):
        """Malformed CSV (e.g. unclosed quote) should raise with actionable hint."""
        data = 'code,name\nAAPL,"Apple'.encode("utf-8")
        with pytest.raises(ValueError) as exc_info:
            parse_import_from_bytes(data, "a.csv")
        msg = str(exc_info.value)
        assert "CSV parsing failed" in msg
        assert "delimiter" in msg or "quote" in msg

    def test_accepts_gbk_encoded_csv(self):
        # Build CSV with Chinese in GBK encoding
        data = ("code,name\nAAPL," + "苹果公司").encode("gbk")
        result = parse_import_from_bytes(data, "a.csv")
        assert len(result) == 1
        assert result[0][0] == "AAPL"
        assert result[0][1] == "苹果公司"


# ---------------------------------------------------------------------------
# parse_import_from_text
# ---------------------------------------------------------------------------

class TestParseImportFromText:
    def test_parses_pasted_text(self):
        text = "AAPL,Apple\nMSFT,Microsoft"
        result = parse_import_from_text(text)
        assert len(result) == 2
        assert result[0] == ("AAPL", "Apple", "medium")

    def test_parses_single_column_codes(self):
        text = "RY.TO\nAAPL"
        result = parse_import_from_text(text)
        assert len(result) == 2
        assert result[0] == ("RY.TO", None, "medium")
        assert result[1] == ("AAPL", None, "medium")

    def test_parses_single_column_with_header(self):
        text = "code\nRY.TO"
        result = parse_import_from_text(text)
        assert len(result) == 1
        assert result[0] == ("RY.TO", None, "medium")

    def test_parses_space_separated_code_name_lines(self):
        text = "MSFT Microsoft\nSHOP.TO Shopify"
        result = parse_import_from_text(text)
        assert len(result) == 2
        assert result[0] == ("MSFT", "Microsoft", "medium")
        assert result[1] == ("SHOP.TO", "Shopify", "medium")
