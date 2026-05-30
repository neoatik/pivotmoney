"""
PDF parsing orchestrator.

This module implements the multi-strategy parsing pipeline:

1. **Text extraction** – run both pdfplumber and PyMuPDF; keep the richer result.
2. **AI parser**       – if a Gemini key is configured *and* confidence > 0.7, use
                         the AI result as the primary source of truth.
3. **Regex parser**    – always run as a fallback / validator.
4. **Merge**           – fill gaps in the AI result with regex findings and vice-versa.
5. **Normalise**       – call the normalizer module to clean every field.
6. **Return**          – a :class:`ParseResult` dataclass ready for DB ingestion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.services import ai_parser, regex_parser
from app.services.normalizer import (
    compute_unrealized_gl,
    compute_weight,
    normalize_amount,
    normalize_asset_type,
    normalize_currency,
    normalize_date,
    normalize_ticker,
    validate_holding,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ParsedHolding:
    """A single normalised holding extracted from a statement."""

    asset_name: str
    ticker: Optional[str] = None
    asset_type: Optional[str] = None
    quantity: Optional[float] = None
    market_value: Optional[float] = None
    cost_basis: Optional[float] = None
    price_per_share: Optional[float] = None
    currency: str = "USD"
    unrealized_gl: Optional[float] = None
    weight_pct: Optional[float] = None  # populated after all holdings are known


@dataclass
class ParseResult:
    """Complete result returned by :func:`parse_pdf`."""

    account_number: Optional[str] = None
    account_name: Optional[str] = None
    broker_name: Optional[str] = None
    statement_date: Optional[date] = None
    currency: str = "USD"
    holdings: List[ParsedHolding] = field(default_factory=list)
    activities: List[Dict[str, Any]] = field(default_factory=list)
    asset_allocation: Dict[str, Any] = field(default_factory=dict)
    confidence_score: float = 0.0
    raw_text: str = ""
    logs: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log(
    logs: List[Dict[str, Any]],
    level: str,
    message: str,
    field_name: Optional[str] = None,
    raw_value: Optional[str] = None,
) -> None:
    """Append a structured log entry to *logs*."""
    logs.append({
        "level": level,
        "message": message,
        "field_name": field_name,
        "raw_value": str(raw_value)[:500] if raw_value is not None else None,
    })


def _normalise_holding_dict(
    raw: Dict[str, Any],
    logs: List[Dict[str, Any]],
) -> Optional[ParsedHolding]:
    """Convert a raw holding dict (from either parser) to a :class:`ParsedHolding`.

    Returns ``None`` when the holding fails validation.
    """
    # Name can come from 'name' (AI) or 'asset_name' (regex)
    asset_name = (
        (raw.get("asset_name") or raw.get("name") or "").strip()
    )
    if not asset_name:
        _log(logs, "warning", "Skipping holding with empty name.", "asset_name")
        return None

    # Ticker
    ticker_raw = raw.get("ticker") or raw.get("symbol") or ""
    ticker = normalize_ticker(ticker_raw) if ticker_raw else None

    # Check if this is an asset allocation/category summary row instead of a real position
    name_lower = asset_name.lower().strip()
    category_labels = {
        "equities", "etfs", "exchange traded funds", "bonds", "fixed income",
        "cash & cash equivalents", "cash and cash equivalents", "cash & cash eq",
        "cash & equivalents", "other assets", "asset allocation",
        "mutual funds", "options", "portfolio allocation", "total holdings",
        "total portfolio", "allocation"
    }
    if name_lower in category_labels or (name_lower.startswith("total ") and not ticker) or (name_lower.endswith(" allocation") and not ticker):
        _log(logs, "info", f"Skipping asset allocation summary row: '{asset_name}'", "holding", asset_name)
        return None

    # Asset type — use AI classification if provided, otherwise infer
    asset_type_raw = raw.get("asset_type") or ""
    valid_types = {"stock", "etf", "bond", "cash", "mutual_fund", "other"}
    if asset_type_raw.lower() in valid_types:
        asset_type: Optional[str] = asset_type_raw.lower()
    else:
        asset_type = normalize_asset_type(asset_name, ticker)

    # Monetary / numeric fields
    def _to_float(v: Any) -> Optional[float]:
        """Coerce *v* to float, trying normalize_amount for strings."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        return normalize_amount(str(v))

    quantity = _to_float(raw.get("quantity"))
    market_value = _to_float(raw.get("market_value"))
    cost_basis = _to_float(raw.get("cost_basis"))
    price_per_share = _to_float(raw.get("price_per_share"))
    currency = normalize_currency(raw.get("currency"))
    unrealized_gl = compute_unrealized_gl(market_value, cost_basis)

    # Validate
    is_valid, errors = validate_holding({
        "asset_name": asset_name,
        "market_value": market_value,
        "quantity": quantity,
    })
    if not is_valid:
        for err in errors:
            _log(logs, "warning", err, "holding", asset_name)

    return ParsedHolding(
        asset_name=asset_name,
        ticker=ticker,
        asset_type=asset_type,
        quantity=quantity,
        market_value=market_value,
        cost_basis=cost_basis,
        price_per_share=price_per_share,
        currency=currency,
        unrealized_gl=unrealized_gl,
    )


def _compute_weights(holdings: List[ParsedHolding]) -> None:
    """Populate :attr:`ParsedHolding.weight_pct` in-place."""
    total = sum(
        h.market_value for h in holdings 
        if h.market_value is not None and not (h.asset_type and h.asset_type.startswith("allocation_"))
    )
    for h in holdings:
        if h.asset_type and h.asset_type.startswith("allocation_"):
            h.weight_pct = 0.0
        else:
            h.weight_pct = compute_weight(h.market_value, total)


def _merge_results(
    ai_data: Optional[Dict[str, Any]],
    regex_data: Dict[str, Any],
    logs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge AI and regex results, preferring AI where confidence is high.

    The AI result takes priority for all scalar fields.  For holdings, the AI
    result is used when available; the regex holdings are appended if the AI
    found no holdings at all.
    """
    if ai_data is None:
        _log(logs, "info", "AI parser unavailable; using regex result exclusively.")
        return regex_data

    merged: Dict[str, Any] = {}

    # Scalar fields: prefer AI, fall back to regex
    for key in ("account_number", "account_name", "broker_name", "statement_date", "currency"):
        merged[key] = ai_data.get(key) or regex_data.get(key)

    # Copy activities and asset allocation from regex (since AI doesn't do them currently)
    merged["activities"] = regex_data.get("activities") or []
    merged["asset_allocation"] = regex_data.get("asset_allocation") or {}

    # Holdings: prefer AI list; use regex list as supplement when AI finds nothing
    ai_holdings: List[Dict] = ai_data.get("holdings") or []
    regex_holdings: List[Dict] = regex_data.get("holdings") or []

    if ai_holdings:
        merged["holdings"] = ai_holdings
        _log(
            logs, "info",
            f"Using {len(ai_holdings)} holding(s) from AI parser.",
            "holdings",
        )
    elif regex_holdings:
        merged["holdings"] = regex_holdings
        _log(
            logs, "info",
            f"AI found no holdings; using {len(regex_holdings)} from regex parser.",
            "holdings",
        )
    else:
        merged["holdings"] = []
        _log(logs, "warning", "Neither parser found any holdings.", "holdings")

    # Overall confidence: weighted average favouring AI
    ai_conf = float(ai_data.get("overall_confidence", 0.0))
    regex_conf = float(regex_data.get("confidence", 0.0))
    merged["confidence"] = round(ai_conf * 0.7 + regex_conf * 0.3, 3)

    merged["raw_text"] = regex_data.get("raw_text", "")

    return merged


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_pdf(pdf_path: str) -> ParseResult:
    """Parse a brokerage statement PDF and return structured data.

    Pipeline:
    1. Extract raw text (pdfplumber + fitz; best wins).
    2. Run Gemini AI parser (if API key is set and text is non-empty).
    3. Run regex parser (always).
    4. Merge results.
    5. Normalise every field.
    6. Compute portfolio weights.

    Args:
        pdf_path: Filesystem path to the PDF file.

    Returns:
        :class:`ParseResult` with all extracted and normalised data.
    """
    logs: List[Dict[str, Any]] = []
    settings = get_settings()

    # -----------------------------------------------------------------
    # 1. Text extraction
    # -----------------------------------------------------------------
    _log(logs, "info", f"Starting PDF parsing: {pdf_path}", "pdf_path")

    raw_text, text_source = regex_parser.extract_best_text(pdf_path)
    _log(
        logs, "info",
        f"Text extracted via {text_source} ({len(raw_text)} chars).",
        "raw_text",
    )

    # -----------------------------------------------------------------
    # 2. AI parser
    # -----------------------------------------------------------------
    ai_data: Optional[Dict[str, Any]] = None
    if settings.gemini_api_key and raw_text.strip():
        _log(logs, "info", "Attempting AI extraction with Gemini Flash.", "ai_parser")
        try:
            ai_data = await ai_parser.parse_with_ai(
                raw_text=raw_text,
                gemini_api_key=settings.gemini_api_key,
            )
            if ai_data:
                conf = ai_data.get("overall_confidence", 0.0)
                _log(
                    logs, "info",
                    f"AI extraction succeeded (confidence={conf:.2f}, "
                    f"holdings={len(ai_data.get('holdings', []))}).",
                    "ai_parser",
                )
            else:
                _log(logs, "warning", "AI parser returned no data.", "ai_parser")
        except Exception as exc:
            _log(logs, "error", f"AI parser raised exception: {exc}", "ai_parser")
            ai_data = None
    else:
        _log(
            logs, "info",
            "AI parser skipped (no API key or empty text).",
            "ai_parser",
        )

    # -----------------------------------------------------------------
    # 3. Regex parser
    # -----------------------------------------------------------------
    _log(logs, "info", "Running regex-based parser.", "regex_parser")
    regex_data = regex_parser.parse_pdf_with_regex(pdf_path)
    logs.extend(regex_data.pop("logs", []))

    # -----------------------------------------------------------------
    # 4. Merge results
    # -----------------------------------------------------------------
    merged = _merge_results(ai_data, regex_data, logs)

    # -----------------------------------------------------------------
    # 5. Normalise scalar fields
    # -----------------------------------------------------------------
    account_number: Optional[str] = merged.get("account_number")
    if account_number:
        account_number = account_number.strip() or None

    account_name: Optional[str] = merged.get("account_name")
    if account_name:
        account_name = account_name.strip() or None

    broker_name: Optional[str] = merged.get("broker_name")
    if broker_name:
        broker_name = broker_name.strip() or None

    # Statement date — may be a string or already a date object
    raw_date = merged.get("statement_date")
    statement_date: Optional[date] = None
    if isinstance(raw_date, date):
        statement_date = raw_date
    elif isinstance(raw_date, str) and raw_date:
        statement_date = normalize_date(raw_date)
        if not statement_date:
            _log(
                logs, "warning",
                f"Could not parse statement date: {raw_date!r}",
                "statement_date",
                raw_date,
            )

    currency = normalize_currency(merged.get("currency"))

    # -----------------------------------------------------------------
    # 6. Normalise holdings
    # -----------------------------------------------------------------
    raw_holdings: List[Dict[str, Any]] = merged.get("holdings") or []
    parsed_holdings: List[ParsedHolding] = []

    for raw_h in raw_holdings:
        holding = _normalise_holding_dict(raw_h, logs)
        if holding:
            parsed_holdings.append(holding)

    # Add the official asset allocation summary rows as special holdings
    asset_alloc = merged.get("asset_allocation") or {}
    if asset_alloc:
        if "cash" in asset_alloc and asset_alloc["cash"] is not None:
            parsed_holdings.append(ParsedHolding(
                asset_name="Cash & Cash Equivalents",
                asset_type="allocation_cash",
                market_value=float(asset_alloc["cash"]),
            ))
        if "equities" in asset_alloc and asset_alloc["equities"] is not None:
            parsed_holdings.append(ParsedHolding(
                asset_name="Equities",
                asset_type="allocation_equities",
                market_value=float(asset_alloc["equities"]),
            ))
        if "etfs" in asset_alloc and asset_alloc["etfs"] is not None:
            parsed_holdings.append(ParsedHolding(
                asset_name="ETFs",
                asset_type="allocation_etfs",
                market_value=float(asset_alloc["etfs"]),
            ))
        if "other" in asset_alloc and asset_alloc["other"] is not None:
            parsed_holdings.append(ParsedHolding(
                asset_name="Other Assets",
                asset_type="allocation_other",
                market_value=float(asset_alloc["other"]),
            ))

    _compute_weights(parsed_holdings)
    _log(
        logs, "info",
        f"Normalised {len(parsed_holdings)} holding(s) from {len(raw_holdings)} raw rows.",
        "holdings",
    )

    confidence_score = float(merged.get("confidence", 0.0))

    return ParseResult(
        account_number=account_number,
        account_name=account_name,
        broker_name=broker_name,
        statement_date=statement_date,
        currency=currency,
        holdings=parsed_holdings,
        activities=merged.get("activities") or [],
        asset_allocation=merged.get("asset_allocation") or {},
        confidence_score=confidence_score,
        raw_text=raw_text,
        logs=logs,
    )
