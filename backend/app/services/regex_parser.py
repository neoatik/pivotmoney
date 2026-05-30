"""
Regex Parser Service — pdfplumber + Pattern Matching
=====================================================
A structural parser that extracts financial data from PDF text using
regular expressions and table-detection heuristics.
Supports multiple brokerage statement layouts (3-col to 6-col tables).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─── Regex Patterns ──────────────────────────────────────────────────────────

# Account number patterns (various brokerage formats)
_ACCOUNT_NUMBER_PATTERNS = [
    r"account\s+(?:number|#|no\.?)\s*[:\-]?\s*([A-Z0-9\-]{4,20})",
    r"acct\.?\s*(?:number|#|no\.?)\s*[:\-]?\s*([A-Z0-9\-]{4,20})",
    r"\baccount\b.*?(\d{3,4}[-\s]?\d{4,8})",
    r"(?:account|acct)[\s\S]{0,30}?(\d{8,12})",
    r"(?:xxxx|x{4}|last\s+\d+\s+digits?).*?(\d{4,6})",
]

# Statement date patterns
_DATE_PATTERNS = [
    r"(?:statement|period|as\s+of)\s+(?:date|ending|end)?\s*[:\-]?\s*"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4})",
    r"(?:statement|period|as\s+of)\s+(?:date|ending)?\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})",
    r"(?:statement|period|as\s+of)\s+(?:date|ending)?\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})",
    r"for\s+the\s+period\s+.*?through\s+"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4})",
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}",
]

# Known brokerage names
_BROKER_PATTERNS = [
    r"(fidelity(?:\s+investments)?)",
    r"(charles\s+schwab(?:\s+&\s+co\.?)?)",
    r"(td\s+ameritrade)",
    r"(e\*?trade(?:\s+financial)?)",
    r"(merrill\s+(?:lynch|edge))",
    r"(morgan\s+stanley)",
    r"(ubs\s+(?:financial\s+services)?)",
    r"(wells\s+fargo\s+(?:advisors)?)",
    r"(vanguard(?:\s+group)?)",
    r"(interactive\s+brokers)",
    r"(robinhood(?:\s+securities)?)",
    r"(webull(?:\s+financial)?)",
    r"(jp\s*morgan(?:\s+chase)?)",
    r"(raymond\s+james)",
    r"(edward\s+jones)",
]

# Dollar amount: handles $1,234.56 | 1,234.56 | (1,234.56) | -1,234.56
_AMOUNT_PATTERN = r"\(?\$?\s*([\d,]+(?:\.\d+)?)\)?"

# Ticker symbol patterns (1-5 uppercase letters, optionally with class like .A)
_TICKER_PATTERN = r"\b([A-Z]{1,5}(?:\.[A-Z])?)(?:\s|$|\)|\])"

# Known ETF/fund suffixes for asset type classification
_ETF_KEYWORDS = {"etf", "fund", "ishares", "vanguard", "spdr", "invesco", "ark", "qqq", "spy"}
_BOND_KEYWORDS = {"bond", "note", "treasury", "tbill", "tips", "fixed income", "corp"}
_CASH_KEYWORDS = {"cash", "money market", "mmf", "mmkt", "settlement", "liquid"}
_MF_KEYWORDS = {"mutual fund", "class a", "class b", "class c", "class i", "class r"}


class RegexParser:
    """
    Multi-layout regex parser for US brokerage statements.

    Tries multiple column layout strategies to extract holdings tables.
    Works with: Fidelity, Schwab, TD Ameritrade, E*TRADE, Vanguard, and others.
    """

    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []

    def _log(
        self,
        level: str,
        message: str,
        field_name: str | None = None,
        raw_value: str | None = None,
    ) -> None:
        self.logs.append(
            {"level": level, "message": message, "field_name": field_name, "raw_value": raw_value}
        )

    # ── Metadata Extraction ──────────────────────────────────────────────────

    def _extract_account_number(self, text: str) -> str | None:
        for pattern in _ACCOUNT_NUMBER_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                acct = m.group(1).strip()
                self._log("info", f"Found account number: {acct}", "account_number", acct)
                return acct
        self._log("warning", "Could not find account number", "account_number")
        return None

    def _extract_statement_date(self, text: str) -> str | None:
        for pattern in _DATE_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                date_str = m.group(1) if m.lastindex else m.group(0)
                self._log("info", f"Found statement date: {date_str}", "statement_date", date_str)
                return date_str.strip()
        self._log("warning", "Could not find statement date", "statement_date")
        return None

    def _extract_broker_name(self, text: str) -> str | None:
        # Check first 500 chars (header area)
        header = text[:500].lower()
        for pattern in _BROKER_PATTERNS:
            m = re.search(pattern, header, re.IGNORECASE)
            if m:
                broker = m.group(1).strip().title()
                self._log("info", f"Found broker: {broker}", "broker_name", broker)
                return broker
        self._log("warning", "Could not identify broker from header", "broker_name")
        return None

    def _extract_account_name(self, text: str) -> str | None:
        """Look for account holder name near 'Name:' or similar labels."""
        patterns = [
            r"(?:account\s+name|account\s+holder|client\s+name|name)\s*[:\-]\s*([A-Z][A-Za-z\s,]+?)(?:\n|$)",
            r"(?:for|prepared\s+for)\s*:?\s*([A-Z][A-Za-z\s,]+?)(?:\n|$)",
        ]
        for pat in patterns:
            m = re.search(pat, text[:2000], re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if 2 < len(name) < 60:  # Sanity check on name length
                    self._log("info", f"Found account name: {name}", "account_name", name)
                    return name
        return None

    # ── Holdings Table Extraction ────────────────────────────────────────────

    def _parse_amount(self, text: str) -> float | None:
        """Parse a dollar/number string into a float."""
        if not text:
            return None
        text = text.strip().replace(",", "").replace("$", "").replace(" ", "")
        negative = False
        if text.startswith("(") and text.endswith(")"):
            negative = True
            text = text[1:-1]
        elif text.startswith("-"):
            negative = True
            text = text[1:]
        try:
            val = float(text)
            return -val if negative else val
        except ValueError:
            return None

    def _extract_ticker_from_name(self, text: str) -> str | None:
        """Extract ticker symbol from parentheses: 'Apple Inc (AAPL)'."""
        m = re.search(r"[\(\[]([A-Z]{1,5})[\)\]]", text)
        if m:
            return m.group(1)
        return None

    def _try_table_extraction_pdfplumber(self, file_path: str) -> list[dict[str, Any]]:
        """Use pdfplumber's built-in table detection to extract holdings."""
        holdings = []
        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    tables = page.extract_tables()
                    for table in tables:
                        if not table or len(table) < 2:
                            continue
                        rows = self._parse_table(table, page_num)
                        holdings.extend(rows)
        except Exception as e:
            self._log("warning", f"pdfplumber table extraction failed: {e}")
        return holdings

    def _parse_table(self, table: list[list[str | None]], page_num: int) -> list[dict[str, Any]]:
        """
        Parse a raw pdfplumber table into holdings dicts.
        Tries to identify column layout from the header row.
        """
        if not table:
            return []

        # Find header row (first row with column names)
        header_row_idx = 0
        header = [str(c or "").lower().strip() for c in table[0]]

        # Column mapping: look for recognizable column headers
        col_map = self._identify_columns(header)

        if not col_map:
            # Try second row as header (some statements have multi-row headers)
            if len(table) > 1:
                header = [str(c or "").lower().strip() for c in table[1]]
                col_map = self._identify_columns(header)
                header_row_idx = 1

        if not col_map and "name" not in col_map:
            self._log(
                "warning",
                f"Could not identify column layout on page {page_num+1}, trying heuristic",
            )
            return self._heuristic_table_parse(table, header_row_idx)

        holdings = []
        for row in table[header_row_idx + 1 :]:
            if not row or all(c is None or str(c).strip() == "" for c in row):
                continue
            holding = self._row_to_holding(row, col_map)
            if holding:
                holdings.append(holding)

        return holdings

    def _identify_columns(self, header: list[str]) -> dict[str, int]:
        """Map semantic column names to their indices in the header row."""
        col_map: dict[str, int] = {}
        mappings = {
            "name": ["description", "security", "investment", "name", "fund", "asset", "holding"],
            "ticker": ["ticker", "symbol", "cusip"],
            "quantity": ["quantity", "qty", "shares", "units"],
            "price": ["price", "unit price", "price/share", "market price", "close price"],
            "market_value": [
                "market value",
                "value",
                "total value",
                "current value",
                "mkt value",
                "estimated value",
            ],
            "cost_basis": ["cost basis", "cost", "book value", "adjusted cost", "total cost"],
            "gain_loss": ["gain/loss", "unrealized", "gain", "g/l", "p&l"],
        }
        for semantic, keywords in mappings.items():
            for i, col in enumerate(header):
                if any(kw in col for kw in keywords):
                    col_map[semantic] = i
                    break
        return col_map

    def _row_to_holding(
        self, row: list[str | None], col_map: dict[str, int]
    ) -> dict[str, Any] | None:
        """Convert a table row to a holding dict using the column map."""

        def safe_get(col_key: str) -> str:
            idx = col_map.get(col_key)
            if idx is not None and idx < len(row):
                return str(row[idx] or "").strip()
            return ""

        name_raw = safe_get("name")
        if not name_raw or len(name_raw) < 2:
            return None

        # Skip header-like rows that appear mid-table
        if any(
            kw in name_raw.lower()
            for kw in ["total", "subtotal", "summary", "description", "security"]
        ):
            return None

        ticker = safe_get("ticker") or self._extract_ticker_from_name(name_raw)
        if ticker:
            ticker = re.sub(r"[^A-Z.]", "", ticker.upper())

        qty = self._parse_amount(safe_get("quantity"))
        price = self._parse_amount(safe_get("price"))
        mkt_val = self._parse_amount(safe_get("market_value"))
        cost = self._parse_amount(safe_get("cost_basis"))

        # Skip rows with no numeric data
        if all(v is None for v in [qty, price, mkt_val]):
            return None

        return {
            "name": name_raw,
            "ticker": ticker if ticker else None,
            "quantity": qty,
            "price_per_share": price,
            "market_value": mkt_val,
            "cost_basis": cost,
            "currency": "USD",
        }

    def _heuristic_table_parse(
        self, table: list[list[str | None]], start_row: int
    ) -> list[dict[str, Any]]:
        """
        Fallback: try to extract holdings from a table without a clear header
        by looking for rows that follow the pattern: text, optional ticker, numbers.
        """
        holdings = []
        for row in table[start_row + 1 :]:
            if not row or len(row) < 2:
                continue

            # Find first non-empty cell (should be the name)
            name = None
            numbers = []
            for cell in row:
                cell_str = str(cell or "").strip()
                if not cell_str:
                    continue
                if name is None and re.search(r"[A-Za-z]{3,}", cell_str):
                    name = cell_str
                else:
                    val = self._parse_amount(cell_str)
                    if val is not None:
                        numbers.append(val)

            if not name or not numbers:
                continue

            # Heuristic assignment: last number is usually market value
            mkt_val = numbers[-1] if numbers else None
            qty = numbers[0] if len(numbers) >= 2 else None

            holding = {
                "name": name,
                "ticker": self._extract_ticker_from_name(name),
                "quantity": qty,
                "market_value": mkt_val,
                "cost_basis": None,
                "price_per_share": None,
                "currency": "USD",
            }
            holdings.append(holding)

        return holdings

    def _extract_holdings_from_text(self, text: str) -> list[dict[str, Any]]:
        """
        Last-resort: scan raw text lines for holding patterns.
        Looks for lines with a security name followed by numbers.
        """
        holdings = []
        lines = text.split("\n")

        # Pattern: NAME (TICKER) ... numbers
        holding_line = re.compile(
            r"^(.{5,60?}?)\s+"  # Name (5-60 chars)
            r"(?:\(([A-Z]{1,5})\))?\s*"  # Optional (TICKER)
            r"([\d,]+\.?\d*)\s+"  # quantity or price
            r".*?([\d,]+\.\d{2})",  # market value (has cents)
            re.IGNORECASE,
        )

        for line in lines:
            line = line.strip()
            if len(line) < 10:
                continue
            m = holding_line.match(line)
            if m:
                name = m.group(1).strip()
                ticker = m.group(2)
                # Try to avoid parsing non-holding lines
                if any(
                    kw in name.lower()
                    for kw in ["total", "page", "account", "date", "period"]
                ):
                    continue
                qty_or_price = self._parse_amount(m.group(3))
                mkt_val = self._parse_amount(m.group(4))
                if mkt_val and mkt_val > 0:
                    holdings.append(
                        {
                            "name": name,
                            "ticker": ticker,
                            "quantity": qty_or_price if qty_or_price and qty_or_price < 1e6 else None,
                            "market_value": mkt_val,
                            "cost_basis": None,
                            "price_per_share": None,
                            "currency": "USD",
                        }
                    )

        return holdings

    # ── Main Entry Point ─────────────────────────────────────────────────────

    def parse(self, raw_text: str, file_path: str | None = None) -> dict[str, Any]:
        """
        Parse a brokerage statement from its raw text (and optionally re-open the PDF
        for table extraction via pdfplumber).

        Args:
            raw_text: Full extracted text of the PDF.
            file_path: Path to the PDF file (enables pdfplumber table detection).

        Returns:
            Dict with account metadata, holdings list, confidence score, and logs.
        """
        self.logs = []

        # Extract metadata
        account_number = self._extract_account_number(raw_text)
        statement_date = self._extract_statement_date(raw_text)
        broker_name = self._extract_broker_name(raw_text)
        account_name = self._extract_account_name(raw_text)

        # Extract holdings — try multiple strategies
        holdings: list[dict[str, Any]] = []

        # Strategy 1: pdfplumber table detection (most reliable)
        if file_path and Path(file_path).exists():
            self._log("info", "Trying pdfplumber table detection")
            tbl_holdings = self._try_table_extraction_pdfplumber(file_path)
            if tbl_holdings:
                self._log("info", f"pdfplumber tables found {len(tbl_holdings)} rows")
                holdings = tbl_holdings

        # Strategy 2: Regex line-by-line fallback
        if not holdings:
            self._log("info", "Falling back to regex text scanning")
            holdings = self._extract_holdings_from_text(raw_text)
            self._log("info", f"Regex text scan found {len(holdings)} rows")

        # Deduplicate by name
        seen_names: set[str] = set()
        unique_holdings = []
        for h in holdings:
            name_key = h.get("name", "").lower().strip()
            if name_key and name_key not in seen_names:
                seen_names.add(name_key)
                unique_holdings.append(h)

        # Compute confidence score
        score = 0.0
        if account_number:
            score += 0.15
        if statement_date:
            score += 0.15
        if broker_name:
            score += 0.10
        if unique_holdings:
            score += min(0.60, len(unique_holdings) * 0.06)

        return {
            "account_number": account_number,
            "account_name": account_name,
            "broker_name": broker_name,
            "statement_date": statement_date,
            "currency": "USD",
            "holdings": unique_holdings,
            "activities": self._extract_activities(raw_text),
            "asset_allocation": self._extract_asset_allocation(raw_text),
            "confidence": round(score, 3),
            "logs": self.logs,
        }

    def _extract_activities(self, text: str) -> list[dict[str, Any]]:
        activities = []
        lines = text.split("\n")
        in_activity = False
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            # Look for activity header
            if "activity" in line_str.lower() and "trade date" in line_str.lower():
                in_activity = True
                continue
            if in_activity:
                # End of activity section conditions
                if any(sec in line_str for sec in ["Important Information", "Holdings", "Asset Allocation Summary"]):
                    in_activity = False
                    continue
                # Match row pattern
                m = re.match(
                    r"^(\d{2}/\d{2}/\d{4})\s+"  # date
                    r"(BUY|SELL|DIVIDEND|DEPOSIT|WITHDRAWAL|INTEREST|OTHER)\s+"  # type
                    r"(.+?)\s+"  # description
                    r"([\d\.\-]+|-)\s+"  # quantity
                    r"(\$?[\d\.\,]+|-)\s+"  # price / rate
                    r"(\(?\$?[\d\.\,]+\)?)$",  # amount
                    line_str,
                    re.IGNORECASE
                )
                if m:
                    date_val = m.group(1)
                    type_val = m.group(2)
                    desc_val = m.group(3)
                    qty_val = m.group(4)
                    rate_val = m.group(5)
                    amt_val = m.group(6)
                    
                    activities.append({
                        "trade_date": date_val,
                        "activity_type": type_val,
                        "description": desc_val,
                        "quantity": qty_val if qty_val != "-" else None,
                        "price": rate_val if rate_val != "-" else None,
                        "amount": amt_val,
                    })
        return activities

    def _extract_asset_allocation(self, text: str) -> dict[str, float | None]:
        alloc = {"cash": None, "equities": None, "etfs": None, "other": None}
        
        cash_match = re.search(r"Cash\s*&\s*Cash\s*Equivalents\s*\$?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
        equities_match = re.search(r"Equities\s*\$?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
        etfs_match = re.search(r"ETFs\s*\$?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
        other_match = re.search(r"Other\s*Assets\s*\$?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
        
        if cash_match:
            alloc["cash"] = self._parse_amount(cash_match.group(1))
        if equities_match:
            alloc["equities"] = self._parse_amount(equities_match.group(1))
        if etfs_match:
            alloc["etfs"] = self._parse_amount(etfs_match.group(1))
        if other_match:
            alloc["other"] = self._parse_amount(other_match.group(1))
            
        return alloc


def extract_best_text(pdf_path: str) -> tuple[str, str]:
    """Extract raw text from PDF using both pdfplumber and PyMuPDF, returning the best/longest result."""
    plumber_text = ""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            plumber_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        logger.warning("pdfplumber text extraction failed: %s", e)

    fitz_text = ""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        fitz_text = "\n".join(page.get_text() or "" for page in doc)
        doc.close()
    except Exception as e:
        logger.warning("PyMuPDF text extraction failed: %s", e)

    if len(fitz_text) >= len(plumber_text):
        return fitz_text, "PyMuPDF"
    return plumber_text, "pdfplumber"


def parse_pdf_with_regex(pdf_path: str) -> dict[str, Any]:
    """Helper function to run the RegexParser on a PDF file path."""
    raw_text, _ = extract_best_text(pdf_path)
    parser = RegexParser()
    return parser.parse(raw_text, pdf_path)
