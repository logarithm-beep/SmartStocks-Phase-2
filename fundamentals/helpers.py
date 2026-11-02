"""Reusable calculations and safe parsing for SmartStock Phase 2."""
import re
import pandas as pd


def performance_returns(df):
    close = df["Close"].dropna()
    result = {}
    for label, calendar_days in [("1D", 1), ("1W", 7), ("1M", 30), ("6M", 182), ("1Y", 365)]:
        if len(close) < 2:
            result[label] = None
            continue
        cutoff = close.index[-1] - pd.Timedelta(days=calendar_days)
        prior = close.loc[close.index <= cutoff]
        result[label] = ((close.iloc[-1] / prior.iloc[-1]) - 1) * 100 if not prior.empty else None
    return result


def risk_metrics(df):
    close = df["Close"].dropna()
    returns = close.pct_change().dropna()
    volatility = returns.std() * (252 ** 0.5) * 100 if len(returns) > 1 else None
    drawdown = (close / close.cummax()) - 1 if not close.empty else pd.Series(dtype=float)
    max_drawdown = drawdown.min() * 100 if not drawdown.empty else None
    return {"annualized_volatility": volatility, "maximum_drawdown": max_drawdown}


def parse_numeric(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("₹", "").replace("%", "").strip()
    text = re.sub(r"[^0-9.\\-]", "", text)
    try:
        return float(text) if text not in ("", ".", "-", "-.") else None
    except ValueError:
        return None


def rows_to_frame(rows):
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    if isinstance(rows[0], list):
        headers = [str(x).strip() for x in rows[0]]
        body = rows[1:]
        width = min(len(headers), max((len(r) for r in body if isinstance(r, list)), default=0))
        return pd.DataFrame([r[:width] for r in body if isinstance(r, list)], columns=headers[:width])
    if isinstance(rows[0], dict):
        return pd.DataFrame(rows)
    return pd.DataFrame()


# Statement payloads have already been converted to INR crore by fundamentals/ratio.py.
# Keep per-share and ratio fields in their native units when formatting for display.
STATEMENT_NON_MONETARY_FIELDS = {
    "fiscal_year", "period_end_date", "period_type", "consolidation_type", "statement_format",
    "eps", "diluted_eps", "basic_eps", "earnings_per_share", "face_value_per_share", "face_value",
    "dividend_per_share", "dividend_per_share_amount", "annual_dividend_per_share", "pe_ratio", "pb_ratio",
    "debt_equity_ratio", "debt_to_equity_ratio", "interest_service_coverage_ratio",
    "interest_coverage_ratio", "debt_service_coverage_ratio", "dscr",
    "roe", "roce", "roa", "dividend_yield", "revenue_growth",
}


def format_statement_frame(frame):
    """Return a display-only copy with explicit ₹ Cr. prefixes on monetary amounts."""
    if frame is None or frame.empty:
        return frame
    display = frame.copy()
    for column in display.columns:
        key = str(column).strip().lower()
        if key in STATEMENT_NON_MONETARY_FIELDS:
            continue
        display[column] = display[column].map(
            lambda value: f"₹ {value:,.2f} Cr."
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else value
        )
    return display


def statement_excel_frame(frame):
    """Return numeric statement data with explicit unit-bearing column labels."""
    if frame is None or frame.empty:
        return frame
    renamed = {}
    for column in frame.columns:
        key = str(column).strip().lower()
        if key in STATEMENT_NON_MONETARY_FIELDS:
            if key in {"eps", "diluted_eps", "basic_eps", "earnings_per_share", "face_value_per_share", "face_value", "dividend_per_share", "dividend_per_share_amount", "annual_dividend_per_share"}:
                renamed[column] = f"{column} (₹/share)"
            elif key not in {"fiscal_year", "period_end_date", "period_type", "consolidation_type", "statement_format"}:
                renamed[column] = f"{column} (ratio)"
        else:
            renamed[column] = f"{column} (₹ Cr.)"
    return frame.rename(columns=renamed).copy()
