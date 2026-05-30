"""
Data Normalizer Service
========================
Utility functions for normalizing and validating extracted financial data.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional


# ─── Amount Normalization ─────────────────────────────────────────────────────

def normalize_amount(value: str) -> Optional[float]:
    """
    Parse a monetary string into a float.

    Handles:
        - $1,234.56  →  1234.56
        - (1,234.56) →  -1234.56  (parentheses = negative)
        - -1,234.56  →  -1234.56
        - 1234       →  1234.0
        - ''         →  None
    """
    if not value:
        return None
    text = str(value).strip().replace(",", "").replace("$", "").replace(" ", "").replace("\xa0", "")
    if not text or text in ("-", "—", "N/A", "n/a", "--", "N.A."):
        return None

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
    except (ValueError, TypeError):
        return None


# ─── Date Normalization ───────────────────────────────────────────────────────

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DATE_FORMATS = [
    "%Y-%m-%d",       # ISO: 2024-01-31
    "%m/%d/%Y",       # US: 01/31/2024
    "%m-%d-%Y",       # US dashes: 01-31-2024
    "%d/%m/%Y",       # UK: 31/01/2024
    "%B %d, %Y",      # Month Day, Year: January 31, 2024
    "%B %d %Y",       # Month Day Year: January 31 2024
    "%b %d, %Y",      # Abbr: Jan 31, 2024
    "%b %d %Y",       # Abbr: Jan 31 2024
    "%B %Y",          # Month Year (no day): January 2024
    "%m/%Y",          # 01/2024
]


def normalize_date(value: str) -> Optional[date]:
    """
    Parse a date string from a brokerage statement into a Python date object.
    Tries multiple format patterns.

    Args:
        value: Raw date string from the parser.

    Returns:
        Python date, or None if parsing fails.
    """
    if not value:
        return None
    value = str(value).strip()

    # Remove ordinal suffixes: "31st" → "31", "1st" → "1"
    value = re.sub(r"(\d+)(?:st|nd|rd|th)\b", r"\1", value, flags=re.IGNORECASE)

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    # Try parsing "Month DD YYYY" with varying spacing
    m = re.match(
        r"(january|february|march|april|may|june|july|august|september|october|november|december"
        r"|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)"
        r"\s+(\d{1,2}),?\s+(\d{4})",
        value,
        re.IGNORECASE,
    )
    if m:
        month = _MONTH_MAP.get(m.group(1).lower())
        day = int(m.group(2))
        year = int(m.group(3))
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    return None


# ─── Ticker Normalization ─────────────────────────────────────────────────────

def normalize_ticker(value: str) -> Optional[str]:
    """
    Clean and validate a ticker symbol.

    Args:
        value: Raw ticker string (e.g. '(AAPL)', 'aapl', 'SPY.A')

    Returns:
        Uppercase ticker string, or None if invalid.
    """
    if not value:
        return None
    # Strip enclosing brackets/parens
    ticker = re.sub(r"[\(\)\[\]\s]", "", str(value)).upper()
    # Keep only alphanumeric and dot (for share classes like BRK.A)
    ticker = re.sub(r"[^A-Z0-9.]", "", ticker)
    # Validate length (1-6 chars is typical for US tickers)
    if 1 <= len(ticker) <= 6:
        return ticker
    return None


# ─── Asset Type Classification ────────────────────────────────────────────────

_ETF_NAMES = {
    "ishares", "vanguard", "spdr", "invesco", "schwab", "wisdomtree",
    "ark", "proshares", "direxion", "global x", "amplify", "vaneck",
}
_ETF_TICKERS = {
    "SPY", "QQQ", "IVV", "VOO", "VTI", "GLD", "SLV", "TLT", "HYG",
    "LQD", "EEM", "IWM", "XLF", "XLE", "XLK", "XLV", "ARKK", "ARKW",
}
_BOND_KEYWORDS = {"bond", "note", "treasury", "bill", "tips", "bnd", "fixed income", "corp note"}
_CASH_KEYWORDS = {"cash", "money market", "mmf", "mmkt", "settlement", "liquid", "fdic"}
_MF_KEYWORDS = {"class a", "class b", "class c", "class i", "class r", "investor shares"}


def normalize_asset_type(name: str, ticker: str) -> str:
    """
    Classify a holding into an asset type based on its name and ticker.

    Returns one of: 'stock', 'etf', 'bond', 'mutual_fund', 'cash', 'other'
    """
    name_lower = name.lower()
    ticker_upper = (ticker or "").upper()

    # Check cash/money market first
    if any(kw in name_lower for kw in _CASH_KEYWORDS):
        return "cash"

    # Check bonds
    if any(kw in name_lower for kw in _BOND_KEYWORDS):
        return "bond"

    # Check mutual funds (usually have share class in name)
    if any(kw in name_lower for kw in _MF_KEYWORDS):
        return "mutual_fund"

    # Check ETFs
    if "etf" in name_lower:
        return "etf"
    if any(kw in name_lower for kw in _ETF_NAMES):
        return "etf"
    if ticker_upper in _ETF_TICKERS:
        return "etf"

    # Default to stock if there's a valid ticker
    if ticker_upper and 1 <= len(ticker_upper) <= 5:
        return "stock"

    return "other"


# ─── Currency Normalization ───────────────────────────────────────────────────

_VALID_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "INR"}


def normalize_currency(value: str) -> str:
    """
    Normalize a currency string to a 3-letter ISO code.
    Defaults to 'USD' if unrecognized.
    """
    if not value:
        return "USD"
    currency = str(value).strip().upper()
    if currency in _VALID_CURRENCIES:
        return currency
    # Handle symbols
    symbol_map = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
    return symbol_map.get(currency, "USD")


# ─── Holding Validation ───────────────────────────────────────────────────────

def validate_holding(holding: dict) -> tuple[bool, list[str]]:
    """
    Validate a holding dict for required fields and data integrity.

    Args:
        holding: Dict with holding data.

    Returns:
        (is_valid, list_of_error_messages)
    """
    errors: list[str] = []

    name = (holding.get("asset_name") or holding.get("name") or "").strip()
    if not name:
        errors.append("Missing required field: asset_name/name")

    mkt_val = holding.get("market_value")
    if mkt_val is not None:
        try:
            val = float(mkt_val)
            if val < 0:
                errors.append(f"Suspicious negative market_value: {val}")
        except (TypeError, ValueError):
            errors.append(f"Invalid market_value: {mkt_val}")

    return len(errors) == 0, errors


# ─── Financial Calculations ───────────────────────────────────────────────────

def compute_unrealized_gl(
    market_value: Optional[float], cost_basis: Optional[float]
) -> Optional[float]:
    """Compute unrealized gain/loss = market_value - cost_basis."""
    if market_value is None or cost_basis is None:
        return None
    return round(market_value - cost_basis, 2)


def compute_weight(
    holding_value: Optional[float], total_portfolio_value: float
) -> Optional[float]:
    """Compute portfolio weight as a percentage."""
    if holding_value is None or total_portfolio_value <= 0:
        return None
    return round((holding_value / total_portfolio_value) * 100, 4)
