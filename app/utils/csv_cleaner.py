"""Utilities for cleaning raw CSV transaction data."""

import re
from datetime import date
from typing import Any

import pandas as pd

from app.core.logging import get_logger

logger = get_logger(__name__)

# Date normalisation

_DATE_FORMATS = [
    "%d-%m-%Y",   # 04-09-2024
    "%Y/%m/%d",   # 2024/02/05
    "%Y-%m-%d",   # 2024-02-05  (already ISO)
    "%d/%m/%Y",   # 04/09/2024
] # Business rule: support these date formats.



def _parse_date(raw: Any) -> date | None:
    """
    Try each known date format in order.
    Returns a Python date or None if nothing matches.
    """
    if pd.isna(raw) or not str(raw).strip():
        return None

    value = str(raw).strip()

    for fmt in _DATE_FORMATS:
        try:
            return pd.to_datetime(value, format=fmt).date()
        except (ValueError, TypeError):
            continue

    # Final fallback: let pandas infer the format
    try:
        return pd.to_datetime(value, infer_datetime_format=True).date()
    except Exception:
        logger.warning("Could not parse date value", extra={"raw_date": value})
        return None

_CURRENCY_SYMBOL_RE = re.compile(r"[^\d.\-]")


def _parse_amount(raw: Any) -> float | None:
    """
    Strip any non-numeric characters (e.g. '$') and return a float.
    Returns None for blank or unparseable values.
    """
    if pd.isna(raw):
        return None
    cleaned = _CURRENCY_SYMBOL_RE.sub("", str(raw).strip())
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        logger.warning("Could not parse amount", extra={"raw_amount": raw})
        return None

REQUIRED_COLUMNS = {
    "txn_id", "date", "merchant", "amount",
    "currency", "status", "category", "account_id", "notes",
}


def validate_csv_columns(df: pd.DataFrame) -> list[str]:
    """
    Return a list of missing required column names.
    Comparison is case-insensitive.
    """
    normalised_cols = {c.lower().strip() for c in df.columns}
    return [col for col in REQUIRED_COLUMNS if col not in normalised_cols]


def clean_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Apply all cleaning steps to the raw DataFrame.

    Steps (in order):
      1. Normalise column names to lowercase/stripped
      2. Normalise date values to ISO 8601
      3. Strip currency symbols from amounts and cast to float
      4. Normalise currency casing to uppercase
      5. Normalise status casing to uppercase
      6. Fill missing category with 'Uncategorised'
      7. Remove exact duplicate rows

    Returns:
        (cleaned_df, raw_row_count)
        where raw_row_count is the count BEFORE deduplication.
    """
    raw_count = len(df)
    logger.info("Starting data cleaning", extra={"raw_rows": raw_count})
    
    df.columns = [c.lower().strip() for c in df.columns]
    
    df["date"] = df["date"].apply(_parse_date)
    logger.debug("Date normalisation complete")
    
    df["amount"] = df["amount"].apply(_parse_amount)
    logger.debug("Amount cleaning complete")
    
    df["currency"] = (
        df["currency"]
        .astype(str)
        .str.strip()
        .str.upper()
        .replace("NAN", pd.NA)  # Pandas behavior: 'NAN' string can appear
    )
    df["status"] = (
        df["status"]
        .astype(str)
        .str.strip()
        .str.upper()
        .replace("NAN", pd.NA)
    )
    df["category"] = df["category"].fillna("Uncategorised").str.strip()
    # Blank strings (e.g., whitespace-only) should also be filled (business rule)
    df["category"] = df["category"].replace("", "Uncategorised")
    
    before_dedup = len(df)
    df = df.drop_duplicates()
    dupes_removed = before_dedup - len(df)
    if dupes_removed:
        logger.info(
            "Duplicate rows removed",
            extra={"duplicates_removed": dupes_removed},
        )
    df = df.reset_index(drop=True)

    logger.info(
        "Data cleaning complete",
        extra={"raw_rows": raw_count, "clean_rows": len(df)},
    )
    return df, raw_count
