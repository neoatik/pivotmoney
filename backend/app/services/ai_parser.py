"""
Google Gemini Flash AI-assisted PDF parser.

This module sends the raw text extracted from a brokerage statement to the
``gemini-1.5-flash`` model and asks it to return structured JSON.  It is
intended to run before the regex parser and provides a high-confidence
extraction path when the statement format is novel or complex.

Features
--------
* Carefully crafted prompt with an embedded JSON schema so the model knows
  exactly what to return.
* JSON-only output enforcement via ``response_mime_type``.
* Retry logic (2 retries with a 1-second delay between attempts).
* Graceful degradation: returns ``None`` on any error so the caller can
  fall through to the regex parser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a financial document parser specialised in brokerage account statements.
Extract all available structured data from the statement text provided by the user and return it
as a single valid JSON object — NO markdown fences, NO prose, ONLY the JSON object.

Return exactly this schema (use null for missing values):

{
  "account_number": "<string or null>",
  "account_name": "<string or null>",
  "broker_name": "<string or null>",
  "statement_date": "<YYYY-MM-DD string or null>",
  "currency": "<ISO 4217 code, default USD>",
  "overall_confidence": <float 0-1>,
  "field_confidence": {
    "account_number": <float 0-1>,
    "account_name": <float 0-1>,
    "broker_name": <float 0-1>,
    "statement_date": <float 0-1>,
    "holdings": <float 0-1>
  },
  "holdings": [
    {
      "name": "<full security name>",
      "ticker": "<ticker symbol or null>",
      "asset_type": "<stock|etf|bond|cash|mutual_fund|other>",
      "quantity": <number or null>,
      "market_value": <number or null>,
      "cost_basis": <number or null>,
      "price_per_share": <number or null>,
      "currency": "<ISO 4217 or null>",
      "confidence": <float 0-1>
    }
  ]
}

Rules:
- All monetary values must be plain numbers (no $ signs, no commas).
- Dates must be in YYYY-MM-DD format.
- asset_type must be exactly one of: stock, etf, bond, cash, mutual_fund, other.
- overall_confidence reflects your certainty about the extracted data as a whole (0 = no data found, 1 = all data found with certainty).
- Return an empty array for holdings if none are found.
"""

_USER_PROMPT_TEMPLATE = """Please extract the financial data from the following brokerage statement text:

---BEGIN STATEMENT---
{text}
---END STATEMENT---
"""

# Maximum characters sent to the model to stay within context limits
_MAX_TEXT_CHARS = 30_000


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> Optional[Dict[str, Any]]:
    """Attempt to extract a JSON object from a raw string.

    The model is instructed to return raw JSON, but occasionally wraps the
    output in markdown code fences.  This function handles both cases.
    """
    # Strip markdown fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # Find the outermost JSON object
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None

    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("JSON decode error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_with_ai(
    raw_text: str,
    gemini_api_key: str,
    max_retries: int = 2,
) -> Optional[Dict[str, Any]]:
    """Send *raw_text* to Gemini Flash and return parsed financial data.

    Args:
        raw_text:       Full text extracted from the PDF.
        gemini_api_key: Google Generative AI API key.
        max_retries:    Number of retry attempts on transient failures.

    Returns:
        A dictionary matching the JSON schema above, or ``None`` on failure.
        The dictionary always contains the key ``overall_confidence``.
    """
    if not gemini_api_key or not raw_text.strip():
        return None

    # Lazy import to avoid mandatory dependency when AI parsing is disabled
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        logger.error(
            "google-generativeai is not installed.  "
            "Install it with: pip install google-generativeai"
        )
        return None

    genai.configure(api_key=gemini_api_key)

    # Truncate text to avoid exceeding model context window
    text_to_send = raw_text[:_MAX_TEXT_CHARS]
    user_prompt = _USER_PROMPT_TEMPLATE.format(text=text_to_send)

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=_SYSTEM_PROMPT,
        generation_config=genai.types.GenerationConfig(
            temperature=0.1,          # low temperature for deterministic extraction
            top_p=0.95,
            max_output_tokens=8192,
            response_mime_type="application/json",
        ),
    )

    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            logger.info(
                "Sending %d chars to Gemini Flash (attempt %d/%d).",
                len(text_to_send),
                attempt + 1,
                max_retries + 1,
            )

            response = await asyncio.to_thread(
                model.generate_content,
                user_prompt,
            )

            raw_response = response.text if hasattr(response, "text") else ""

            parsed = _extract_json(raw_response)
            if parsed is None:
                logger.warning(
                    "Gemini returned non-JSON output (attempt %d): %.200s",
                    attempt + 1,
                    raw_response,
                )
                last_error = ValueError("Non-JSON response from Gemini.")
                await asyncio.sleep(1)
                continue

            # Ensure overall_confidence exists and is a float
            parsed.setdefault("overall_confidence", 0.5)
            parsed["overall_confidence"] = float(parsed["overall_confidence"])

            # Ensure holdings is a list
            if not isinstance(parsed.get("holdings"), list):
                parsed["holdings"] = []

            logger.info(
                "Gemini extraction succeeded: %d holdings, confidence=%.2f",
                len(parsed["holdings"]),
                parsed["overall_confidence"],
            )
            return parsed

        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Gemini API error on attempt %d: %s",
                attempt + 1,
                exc,
            )
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(1)

    logger.error(
        "Gemini parsing failed after %d attempts.  Last error: %s",
        max_retries + 1,
        last_error,
    )
    return None


def parse_with_ai_sync(
    raw_text: str,
    gemini_api_key: str,
    max_retries: int = 2,
) -> Optional[Dict[str, Any]]:
    """Synchronous wrapper around :func:`parse_with_ai`.

    Useful when calling from a non-async context such as a Celery task or a
    CLI script.
    """
    return asyncio.run(parse_with_ai(raw_text, gemini_api_key, max_retries))
