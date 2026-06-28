"""Service for interacting with the Google Gemini LLM for transaction classification and summary generation."""

import json
import re
import time
from typing import Any, Optional

import google.generativeai as genai

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

ALLOWED_CATEGORIES = [
    "Food",
    "Shopping",
    "Travel",
    "Transport",
    "Utilities",
    "Cash Withdrawal",
    "Entertainment",
    "Other",
]
ALLOWED_RISK_LEVELS = {"low", "medium", "high"}


def _get_gemini_client() -> genai.GenerativeModel:
    """Initialise and return the Gemini model client."""
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel(model_name=settings.gemini_model)


def _call_with_retry(prompt: str) -> Optional[str]:
    """
    Call the Gemini API with exponential backoff on failure.

    Returns the raw text response, or None if all retries are exhausted.

    Retry schedule (base_delay=2s, 3 retries):
        Attempt 1: immediate
        Attempt 2: wait 2s
        Attempt 3: wait 4s
        → give up, return None
    """
    model = _get_gemini_client()
    last_exception: Exception | None = None

    for attempt in range(1, settings.llm_max_retries + 1):
        try:
            logger.debug(
                "Calling Gemini API",
                extra={"attempt": attempt, "max_retries": settings.llm_max_retries},
            )
            response = model.generate_content(prompt)
            return response.text

        except Exception as exc:
            import traceback

            last_exception = exc

            print("\n========== GEMINI EXCEPTION ==========")
            print(type(exc).__name__)
            print(str(exc))
            traceback.print_exc()
            print("======================================\n")

            wait = settings.llm_retry_base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Gemini API call failed, will retry",
                extra={
                    "attempt": attempt,
                    "error": str(exc),
                    "wait_seconds": wait,
                },
            )
            if attempt < settings.llm_max_retries:
                time.sleep(wait)

    logger.error(
        "All Gemini retries exhausted",
        extra={"error": str(last_exception)},
    )
    return None


def _extract_json(raw_text: str) -> Any:
    if not raw_text:
        raise ValueError("Empty response from LLM")

    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()
    cleaned = cleaned.replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fall back: find the first {...} or [...] block
    for pattern in (r"(\{.*\})", r"(\[.*\])"):
        match = re.search(pattern, cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    raise ValueError(f"No valid JSON found in LLM response: {raw_text[:200]!r}")

def classify_transactions_batch(
    transactions: list[dict[str, Any]],
) -> tuple[dict[int, str], str | None, bool]:
    if not transactions: return {}, None, False

    allowed = ", ".join(ALLOWED_CATEGORIES) # Business rule: only these categories are allowed

    # Build a compact transaction list for the prompt
    txn_lines = "\n".join(
        f"  [{t['index']}] merchant={t['merchant']!r} amount={t['amount']} "
        f"currency={t['currency']} notes={t['notes']!r}"
        for t in transactions
    )

    prompt = f"""You are a financial transaction classifier.

Classify each transaction below into EXACTLY one of these categories:
{allowed}

Rules:
- Use ONLY the categories listed above. Do not invent new categories.
- Base your decision on the merchant name, amount, currency, and notes.
- If uncertain, use "Other".

Transactions (format: [index] merchant amount currency notes):
{txn_lines}

Respond with ONLY a valid JSON object mapping each index (as a string key)
to its predicted category string. No explanation, no markdown, no extra text.

Example format:
{{"0": "Food", "1": "Shopping", "3": "Transport"}}
"""

    raw_text = _call_with_retry(prompt)

    if raw_text is None:
        logger.error("LLM classification failed for entire batch")
        return {}, None, True

    try:
        parsed: dict[str, str] = _extract_json(raw_text)
        # Convert string keys back to int and validate categories
        category_map: dict[int, str] = {} # Design decision: map results back to original DataFrame indices.
        for key, cat in parsed.items():
            try:
                idx = int(key)
            except ValueError:
                logger.warning("Non-integer key in LLM response", extra={"key": key})
                continue
            if cat in ALLOWED_CATEGORIES:
                category_map[idx] = cat
            else:
                logger.warning(
                    "LLM returned unknown category, defaulting to 'Other'",
                    extra={"returned_category": cat},
                )
                category_map[idx] = "Other"

        logger.info(
            "LLM batch classification complete",
            extra={"classified": len(category_map), "total": len(transactions)},
        )
        return category_map, raw_text, False

    except (ValueError, KeyError) as exc:
        logger.error(
            "Failed to parse LLM classification response",
            extra={"error": str(exc), "raw_response": raw_text[:500]},
        )
        return {}, raw_text, True


def generate_job_summary(
    transactions: list[dict[str, Any]],
    anomaly_count: int,
) -> tuple[dict[str, Any] | None, bool]:
    if not transactions: return None, False

    # Summarise the data for the prompt to avoid token bloat (design decision)
    total_inr = sum(
        float(t.get("amount", 0) or 0)
        for t in transactions
        if str(t.get("currency", "")).upper() == "INR"
    )
    total_usd = sum(
        float(t.get("amount", 0) or 0)
        for t in transactions
        if str(t.get("currency", "")).upper() == "USD"
    )

    from collections import Counter
    merchant_counts = Counter(
        str(t.get("merchant", "Unknown")) for t in transactions
    )
    # Business rule: show top 5 merchants.
    top_merchants_text = ", ".join(f"{m} ({c} txns)" for m, c in merchant_counts.most_common(5))

    # Category distribution for context
    category_counts = Counter(
        str(t.get("category", "Uncategorised")) for t in transactions
    )
    category_text = ", ".join(
        f"{cat}: {cnt}" for cat, cnt in category_counts.most_common()
    )

    prompt = f"""You are a financial analyst generating a spending report.

Transaction dataset summary:
- Total transactions: {len(transactions)}
- Total INR spend: {total_inr:.2f}
- Total USD spend: {total_usd:.2f}
- Top merchants by frequency: {top_merchants_text}
- Category distribution: {category_text}
- Anomalies flagged: {anomaly_count}

Generate a structured JSON summary with these EXACT keys:
{{
  "total_spend_inr": <float>,
  "total_spend_usd": <float>,
  "top_merchants": [
    {{"merchant": "<name>", "total": <float spend for this merchant>}},
    {{"merchant": "<name>", "total": <float>}},
    {{"merchant": "<name>", "total": <float>}}
  ],
  "category_breakdown": {{
    "<category>": <total float spend in this category>,
    ...
  }},
  "anomaly_count": <integer>,
  "narrative": "<2–3 sentence spending narrative describing patterns, risks, and observations>",
  "risk_level": "<low|medium|high>"
}}

Risk level guidelines:
- "high"   if anomaly_count >= 5 or any single transaction is unusually large
- "medium" if anomaly_count is 2–4 or there are suspicious patterns
- "low"    otherwise

Respond with ONLY valid JSON. No markdown, no preamble, no explanation.
"""

    raw_text = _call_with_retry(prompt)

    if raw_text is None:
        logger.error("LLM summary generation failed after all retries")
        return None, True

    try:
        parsed = _extract_json(raw_text)

        # Validate and normalise the risk level (business rule)
        risk = str(parsed.get("risk_level", "low")).lower()
        if risk not in ALLOWED_RISK_LEVELS:
            risk = "low"
        parsed["risk_level"] = risk

        # Design decision: prefer internal count over LLM's.
        parsed["anomaly_count"] = anomaly_count

        logger.info("LLM summary generation complete", extra={"risk_level": risk})
        return parsed, False

    except (ValueError, KeyError) as exc:
        logger.error(
            "Failed to parse LLM summary response",
            extra={"error": str(exc), "raw_response": raw_text[:500]},
        )
        return None, True
