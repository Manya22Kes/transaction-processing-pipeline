"""Rule-based anomaly detection for transaction data."""

import pandas as pd

from app.core.logging import get_logger

logger = get_logger(__name__)

# Merchants that only operate domestically (INR transactions expected, business rule).
DOMESTIC_ONLY_MERCHANTS: set[str] = {"swiggy", "ola", "irctc"}
OUTLIER_MULTIPLIER = 3.0


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply both anomaly detection rules to the cleaned DataFrame.

    Adds / updates two columns in place:
        is_anomaly    (bool)
        anomaly_reason (str | None)

    Returns the modified DataFrame.
    """
    # Initialize columns if not already present.
    df["is_anomaly"] = df.get("is_anomaly", False)
    df["anomaly_reason"] = df.get("anomaly_reason", None)

    df = _apply_rule_statistical_outlier(df)
    df = _apply_rule_currency_merchant_mismatch(df)

    anomaly_count = df["is_anomaly"].sum()
    logger.info(
        "Anomaly detection complete",
        extra={"anomalies_found": int(anomaly_count)},
    )
    return df

def _apply_rule_statistical_outlier(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each account, compute the median transaction amount.
    Flag any transaction whose amount exceeds 3× that median.

    Edge cases handled:
    - account_id is missing → skip (no group to compare against)
    - amount is None / NaN → skip
    - fewer than 2 transactions per account → still apply the rule
      (a single very large transaction against a zero baseline would
      be caught by the USD/merchant rule; here we compute the median
      of whatever data exists)
    """ # Business rule: statistical outlier definition.
    # Ensure amounts are numeric for calculation
    amount_col = pd.to_numeric(df["amount"], errors="coerce") # Non-obvious pandas operation.
    
    # Group by account_id to get per-account medians
    account_medians: dict[str, float] = {} # Non-obvious pandas operation.
    for account_id, group in df.groupby("account_id", dropna=True): # Non-obvious pandas operation.
        amounts = pd.to_numeric(group["amount"], errors="coerce").dropna()
        if not amounts.empty:
            account_medians[str(account_id)] = float(amounts.median())

    flagged_count = 0
    for idx, row in df.iterrows():
        account_id = str(row.get("account_id", "")) if pd.notna(row.get("account_id")) else None # Handle potential NaN account_id
        amount = amount_col.iloc[idx] if idx < len(amount_col) else None # Non-obvious pandas operation.

        if account_id is None or pd.isna(amount):
            continue

        median = account_medians.get(account_id)
        if median is None or median == 0:
            continue

        if amount > OUTLIER_MULTIPLIER * median:
            _flag_anomaly(
                df,
                idx,  # type: ignore[arg-type]
                reason=(
                    f"Amount {amount:.2f} exceeds 3× the account median "
                    f"({median:.2f}) for account {account_id}"
                ),
            )
            flagged_count += 1

    logger.debug(
        "Rule 1 (statistical outlier) applied",
        extra={"flagged": flagged_count},
    )
    return df

def _apply_rule_currency_merchant_mismatch(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag transactions where currency == USD AND the merchant name
    (case-insensitive) matches one of the domestic-only brands.
    """
    flagged_count = 0
    for idx, row in df.iterrows():
        currency = str(row.get("currency", "")).strip().upper()
        merchant_raw = str(row.get("merchant", "")).strip()
        merchant_lower = merchant_raw.lower()

        if currency != "USD": continue
        
        matched_brand = None
        for brand in DOMESTIC_ONLY_MERCHANTS:
            if brand in merchant_lower:
                matched_brand = brand.capitalize()
                break

        if matched_brand:
            _flag_anomaly(
                df,
                idx,  # type: ignore[arg-type]
                reason=(
                    f"Currency is USD but merchant '{merchant_raw}' is a "
                    f"domestic-only Indian brand ({matched_brand})"
                ),
            )
            flagged_count += 1

    logger.debug(
        "Rule 2 (currency/merchant mismatch) applied",
        extra={"flagged": flagged_count},
    )
    return df

def _flag_anomaly(df: pd.DataFrame, idx: int, reason: str) -> None:
    """
    Mark a row as anomalous.  If it was already flagged by a previous
    rule, append the new reason rather than overwriting it.
    """
    existing_reason = df.at[idx, "anomaly_reason"]
    if df.at[idx, "is_anomaly"] and existing_reason:
        df.at[idx, "anomaly_reason"] = f"{existing_reason}; {reason}"
    else:
        df.at[idx, "is_anomaly"] = True
        df.at[idx, "anomaly_reason"] = reason
