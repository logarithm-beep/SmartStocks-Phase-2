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


def _pick(row, *keys):
    """Read a numeric field from a BharatStock row using common aliases."""
    normalized = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in row.items()}
    for key in keys:
        value = normalized.get(re.sub(r"[^a-z0-9]", "", key.lower()))
        number = parse_numeric(value)
        if number is not None:
            return number
    return None


def _ratio(numerator, denominator, scale=1.0):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * scale


def _year_label(row):
    value = row.get("fiscal_year") or row.get("period_end_date") or "N/A"
    return str(value)


def _year_prices(row, price_history):
    """Return FY-end and FY-average close when price history covers that year."""
    if price_history is None or getattr(price_history, "empty", True) or "Close" not in price_history:
        return None, None
    end_value = row.get("period_end_date")
    try:
        if end_value:
            end = pd.Timestamp(end_value)
        else:
            # BharatStock may provide only a fiscal-year label such as 2024-25.
            # Indian listed-company financial years normally end on 31 March.
            fiscal_year = str(row.get("fiscal_year") or "").strip()
            match = re.match(r"^(\d{4})\s*[-/–]\s*(\d{2}|\d{4})$", fiscal_year)
            if not match:
                return None, None
            end_year = int(match.group(1)) + 1
            end = pd.Timestamp(year=end_year, month=3, day=31)
        start = end - pd.DateOffset(years=1) + pd.Timedelta(days=1)
        close = price_history["Close"].dropna().copy()
        close.index = pd.to_datetime(close.index)
        close = close.sort_index()
        fy = close.loc[(close.index >= start) & (close.index <= end)]
        prior = close.loc[close.index <= end]
        year_end = float(prior.iloc[-1]) if not prior.empty and (end - prior.index[-1]).days <= 7 else None
        # Require meaningful coverage before presenting an average as an annual average.
        average = float(fy.mean()) if len(fy) >= 100 else None
        return year_end, average
    except Exception:
        return None, None


def build_annual_analysis_tables(pnl_rows, bs_rows, cf_rows, price_history=None):
    """Build the requested annual-analysis tables from annual statements.

    Price-dependent figures are left blank when the supplied market history does
    not cover the relevant fiscal year; no historical prices are fabricated.
    Statement amounts are already INR crore from ratio.py.
    """
    pnl = pnl_rows if isinstance(pnl_rows, list) else []
    bs = bs_rows if isinstance(bs_rows, list) else []
    cf = cf_rows if isinstance(cf_rows, list) else []
    count = max(len(pnl), len(bs), len(cf))
    pnl_table, bs_table, cf_table = [], [], []

    for i in range(count):
        p = pnl[i] if i < len(pnl) else {}
        b = bs[i] if i < len(bs) else {}
        c = cf[i] if i < len(cf) else {}
        year = _year_label(p or b or c)
        year_end, avg_price = _year_prices(p or b or c, price_history)
        revenue = _pick(p, "revenue", "total_income")
        prior_revenue = _pick(pnl[i+1], "revenue", "total_income") if i+1 < len(pnl) else None
        gross_profit = _pick(p, "gross_profit")
        if gross_profit is None:
            gross_profit = (revenue - _pick(p, "cost_of_materials_consumed", "cost_of_goods_sold")) if revenue is not None and _pick(p, "cost_of_materials_consumed", "cost_of_goods_sold") is not None else None
        operating_profit = _pick(p, "ebit", "operating_profit")
        net_profit = _pick(p, "net_profit", "profit_after_tax", "profit_for_the_period")
        prior_net = _pick(pnl[i+1], "net_profit", "profit_after_tax", "profit_for_the_period") if i+1 < len(pnl) else None
        ebitda = _pick(p, "ebitda")
        eps = _pick(p, "diluted_eps", "eps", "basic_eps", "earnings_per_share")
        paid_up = _pick(b or p, "paid_up_equity_capital", "paid_up_share_capital", "paid_up_capital", "share_capital", "equity_share_capital")
        face = _pick(p or b, "face_value_per_share", "face_value")
        shares_cr = paid_up / face if paid_up is not None and face not in (None, 0) else None
        market_cap = year_end * shares_cr if year_end is not None and shares_cr is not None else None
        pnl_table.append({
            "Year": year, "Fiscal Year-End Share Price (₹)": year_end,
            "Average Annual Share Price (₹)": avg_price,
            "Gross Profit Margin (%)": _ratio(gross_profit, revenue, 100),
            "Operating Margin (EBIT Margin) (%)": _ratio(operating_profit, revenue, 100),
            "Net Profit Margin (%)": _ratio(net_profit, revenue, 100),
            "EBITDA Margin (%)": _ratio(ebitda, revenue, 100),
            "YoY Revenue Growth (%)": _ratio(revenue-prior_revenue, prior_revenue, 100) if revenue is not None and prior_revenue is not None else None,
            "YoY Net Income Growth (%)": _ratio(net_profit-prior_net, prior_net, 100) if net_profit is not None and prior_net is not None else None,
            "P/E (x)": _ratio(year_end, eps), "P/S (x)": _ratio(market_cap, revenue),
        })

        assets = _pick(b, "total_assets")
        equity = _pick(b, "equity_attributable_to_owners", "equity_attributable_to_owners_of_parent", "total_equity", "total_shareholders_equity")
        current_assets = _pick(b, "current_assets")
        current_liabilities = _pick(b, "current_liabilities")
        debt = _pick(b, "total_borrowings", "total_debt", "gross_debt", "borrowings")
        if debt is None:
            short_debt = _pick(b, "borrowings_current", "short_term_borrowings") or 0
            long_debt = _pick(b, "borrowings_non_current", "long_term_borrowings") or 0
            debt = short_debt + long_debt if short_debt or long_debt else None
        cash = _pick(b, "cash_and_cash_equivalents")
        prev_b = bs[i+1] if i+1 < len(bs) else {}
        prev_assets = _pick(prev_b, "total_assets")
        prev_equity = _pick(prev_b, "equity_attributable_to_owners", "equity_attributable_to_owners_of_parent", "total_equity", "total_shareholders_equity")
        prev_cl = _pick(prev_b, "current_liabilities")
        ce = assets-current_liabilities if assets is not None and current_liabilities is not None else None
        prev_ce = prev_assets-prev_cl if prev_assets is not None and prev_cl is not None else None
        net_owner_profit = _pick(p, "net_profit_attributable_to_owners", "profit_attributable_to_owners") or net_profit
        roce_base = ((ce+prev_ce)/2) if ce is not None and prev_ce is not None else None
        bvps = _ratio(equity, shares_cr)
        ev = market_cap + debt - cash if market_cap is not None and debt is not None and cash is not None else None
        bs_table.append({
            "Year": year, "Year-End Share Price (₹)": year_end,
            "Book Value per Share (₹)": bvps,
            "Current Ratio (x)": _ratio(current_assets, current_liabilities),
            "Debt-to-Equity (x)": _ratio(debt, equity),
            "Debt-to-Assets (%)": _ratio(debt, assets, 100),
            "Financial Leverage Ratio (x)": _ratio(assets, equity),
            "Return on Equity (ROE) (%)": _ratio(net_owner_profit, (equity+prev_equity)/2, 100) if equity is not None and prev_equity is not None else None,
            "Return on Assets (ROA) (%)": _ratio(net_profit, (assets+prev_assets)/2, 100) if assets is not None and prev_assets is not None else None,
            "Return on Capital Employed (ROCE) (%)": _ratio(operating_profit, roce_base, 100),
            "Price-to-Book (P/B) (x)": _ratio(year_end, bvps),
            "Enterprise Value (₹ Cr.)": ev,
        })

        operating_cf = _pick(c, "cash_flow_operating", "operating_cash_flow", "net_cash_from_operating_activities")
        capex = _pick(c, "capex", "capital_expenditure", "purchase_of_property_plant_equipment")
        free_cash_flow = operating_cf - abs(capex) if operating_cf is not None and capex is not None else None
        ev_cf = ev
        cf_table.append({
            "Year": year, "Market Cap (₹ Cr.)": market_cap,
            "Enterprise Value (EV) (₹ Cr.)": ev,
            "Cash Flow Margin (%)": _ratio(operating_cf, revenue, 100),
            "Free Cash Flow (₹ Cr.)": free_cash_flow,
            "Price-to-Cash Flow (x)": _ratio(market_cap, operating_cf),
            "Price-to-Free Cash Flow (x)": _ratio(market_cap, free_cash_flow),
            "EV-to-Free Cash Flow (x)": _ratio(ev_cf, free_cash_flow),
        })

    # Keep unavailable values explicit and consistent in the UI. Never replace
    # missing financial data with zero, which would imply a real reported value.
    def display_na(rows):
        frame = pd.DataFrame(rows)
        return frame.astype(object).where(pd.notna(frame), "N/A")

    return display_na(pnl_table), display_na(bs_table), display_na(cf_table)


def annual_table_column_config(table_kind):
    """Streamlit column configs with compact ratio explanations on hover."""
    import streamlit as st
    help_text = {
        "Year": "Financial year reported by BharatStock.",
        "Fiscal Year-End Share Price (₹)": "Last available TejHQ closing price on or immediately before the fiscal year-end. Blank if history is unavailable.",
        "Average Annual Share Price (₹)": "Average daily TejHQ closing price during the fiscal year. Requires sufficient historical price coverage.",
        "Gross Profit Margin (%)": "Gross profit divided by revenue × 100. Gross profit is sourced directly or estimated as revenue less cost of goods sold/materials when available.",
        "Operating Margin (EBIT Margin) (%)": "EBIT divided by revenue × 100.",
        "Net Profit Margin (%)": "Net profit divided by revenue × 100.",
        "EBITDA Margin (%)": "EBITDA divided by revenue × 100.",
        "YoY Revenue Growth (%)": "(Current-year revenue − prior-year revenue) ÷ prior-year revenue × 100.",
        "YoY Net Income Growth (%)": "(Current-year net income − prior-year net income) ÷ prior-year net income × 100.",
        "P/E (x)": "Fiscal year-end share price divided by that year's EPS.",
        "P/S (x)": "Fiscal year-end market capitalisation divided by annual revenue.",
        "Year-End Share Price (₹)": "Last available TejHQ closing price on or immediately before the fiscal year-end.",
        "Book Value per Share (₹)": "Equity attributable to ordinary shareholders divided by estimated shares outstanding.",
        "Current Ratio (x)": "Current assets divided by current liabilities.",
        "Debt-to-Equity (x)": "Interest-bearing borrowings divided by shareholders' equity.",
        "Debt-to-Assets (%)": "Interest-bearing borrowings divided by total assets × 100.",
        "Financial Leverage Ratio (x)": "Total assets divided by shareholders' equity.",
        "Return on Equity (ROE) (%)": "Annual net income attributable to owners divided by average opening and closing equity × 100.",
        "Return on Assets (ROA) (%)": "Annual net income divided by average opening and closing total assets × 100.",
        "Return on Capital Employed (ROCE) (%)": "EBIT divided by average capital employed × 100; capital employed = total assets − current liabilities.",
        "Price-to-Book (P/B) (x)": "Fiscal year-end share price divided by book value per share.",
        "Enterprise Value (₹ Cr.)": "Market capitalisation + interest-bearing debt − cash and cash equivalents.",
        "Market Cap (₹ Cr.)": "Fiscal year-end share price × estimated shares outstanding.",
        "Enterprise Value (EV) (₹ Cr.)": "Market capitalisation + interest-bearing debt − cash and cash equivalents.",
        "Cash Flow Margin (%)": "Cash flow from operating activities divided by revenue × 100.",
        "Free Cash Flow (₹ Cr.)": "Cash flow from operating activities minus capital expenditure.",
        "Price-to-Cash Flow (x)": "Market capitalisation divided by cash flow from operating activities.",
        "Price-to-Free Cash Flow (x)": "Market capitalisation divided by free cash flow.",
        "EV-to-Free Cash Flow (x)": "Enterprise value divided by free cash flow.",
    }
    return {col: st.column_config.Column(col, help=help_text.get(col, "Financial metric.")) for col in help_text if col in {
        "Year", "Fiscal Year-End Share Price (₹)", "Average Annual Share Price (₹)",
        "Gross Profit Margin (%)", "Operating Margin (EBIT Margin) (%)", "Net Profit Margin (%)", "EBITDA Margin (%)",
        "YoY Revenue Growth (%)", "YoY Net Income Growth (%)", "P/E (x)", "P/S (x)",
        "Year-End Share Price (₹)", "Book Value per Share (₹)", "Current Ratio (x)", "Debt-to-Equity (x)",
        "Debt-to-Assets (%)", "Financial Leverage Ratio (x)", "Return on Equity (ROE) (%)", "Return on Assets (ROA) (%)",
        "Return on Capital Employed (ROCE) (%)", "Price-to-Book (P/B) (x)", "Enterprise Value (₹ Cr.)",
        "Market Cap (₹ Cr.)", "Enterprise Value (EV) (₹ Cr.)", "Cash Flow Margin (%)", "Free Cash Flow (₹ Cr.)",
        "Price-to-Cash Flow (x)", "Price-to-Free Cash Flow (x)", "EV-to-Free Cash Flow (x)"
    }}
