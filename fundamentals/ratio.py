"""BharatStock fundamentals client with cached annual statements and valuation ratios.

Each uncached company uses two provider requests: annual financial statements and
current ratios. Both are cached together for 24 hours. Derived metrics are only
shown when the required source values are present.
"""
import hashlib
import json
import sqlite3
import time
from datetime import date
from pathlib import Path

import requests

BASE_URL = "https://bharatstockapi.com"
CACHE_TTL_SECONDS = 24 * 60 * 60
STATEMENT_AMOUNT_DIVISOR = 10_000_000  # BharatStock statement amounts are returned in INR; display in INR crore.
DATA_SCHEMA_VERSION = 5
DAILY_APP_BUDGET = 55
CACHE_DIR = Path(".smartstock_cache")
DB_PATH = CACHE_DIR / "bharatstock_cache.sqlite"


class BharatStockRateLimitError(RuntimeError):
    pass


class BharatStockDailyBudgetError(RuntimeError):
    pass


def _connect():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("""CREATE TABLE IF NOT EXISTS fundamentals (
        cache_key TEXT PRIMARY KEY, ticker TEXT NOT NULL,
        payload TEXT NOT NULL, fetched_at REAL NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS request_log (
        request_day TEXT NOT NULL, requested_at REAL NOT NULL
    )""")
    conn.commit()
    return conn


def _key(ticker, api_key):
    fingerprint = hashlib.sha256(api_key.encode()).hexdigest()
    return hashlib.sha256(f"bharatstock-fundamentals-v5:{fingerprint}:{ticker.upper()}".encode()).hexdigest()


def get_cache_info(ticker, api_key):
    key = _key(ticker, api_key)
    with _connect() as conn:
        row = conn.execute("SELECT fetched_at FROM fundamentals WHERE cache_key=?", (key,)).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE request_day=?", (date.today().isoformat(),)
        ).fetchone()[0]
    age = max(0, time.time() - row[0]) if row else None
    return {
        "cached": bool(row), "fresh": bool(row and age <= CACHE_TTL_SECONDS),
        "age_hours": age / 3600 if age is not None else None,
        "calls_today": count, "daily_limit": DAILY_APP_BUDGET,
        "calls_remaining": max(0, DAILY_APP_BUDGET - count),
    }


def _request_json(ticker, endpoint, api_key, params=None):
    with _connect() as conn:
        used = conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE request_day=?", (date.today().isoformat(),)
        ).fetchone()[0]
        if used >= DAILY_APP_BUDGET:
            raise BharatStockDailyBudgetError(
                f"SmartStock reached its local {DAILY_APP_BUDGET}-request daily safety limit. "
                "Cached data remains available; try again tomorrow."
            )
        conn.execute("INSERT INTO request_log VALUES (?, ?)", (date.today().isoformat(), time.time()))
        conn.commit()

    try:
        response = requests.get(
            f"{BASE_URL}/v1/stocks/{ticker}/{endpoint}" if endpoint else f"{BASE_URL}/v1/stocks/{ticker}",
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            params=params, timeout=25,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"BharatStock network error: {type(exc).__name__}.") from None
    if response.status_code == 429:
        raise BharatStockRateLimitError(
            "BharatStock returned HTTP 429 (daily quota/rate limit). No automatic retry was attempted."
        )
    if response.status_code in (401, 403):
        raise RuntimeError(
            f"BharatStock authentication/permission error (HTTP {response.status_code}). "
            "Check the API key and plan access."
        )
    if not response.ok:
        raise RuntimeError(f"BharatStock returned HTTP {response.status_code} for the {endpoint or 'company'} endpoint.")
    try:
        return response.json()
    except ValueError:
        raise RuntimeError("BharatStock returned invalid JSON.") from None


def _rows(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for name in ("data", "items", "results", "financials", "ratios"):
            if isinstance(data.get(name), list):
                return data[name]
        return [data] if data else []
    return []


def _number(row, *keys):
    for key in keys:
        value = row.get(key) if isinstance(row, dict) else None
        try:
            if value is not None and value != "":
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _ratio(numerator, denominator, multiplier=1.0):
    if numerator is None or denominator in (None, 0):
        return None
    return round((numerator / denominator) * multiplier, 2)


def _first_record(payload):
    rows = _rows(payload)
    return next((r for r in rows if isinstance(r, dict)), {})


def _normalise(ticker, financial_payload, ratios_payload):
    rows = [r for r in _rows(financial_payload) if isinstance(r, dict)]
    rows.sort(key=lambda r: str(r.get("period_end_date") or r.get("fiscal_year") or ""), reverse=True)
    if not rows:
        raise RuntimeError(f"BharatStock returned no annual financial records for {ticker}.")

    pnl_fields = {
        "revenue", "total_income", "total_expenses", "cost_of_materials_consumed",
        "employee_benefit_expense", "finance_costs", "depreciation_and_amortisation",
        "operating_profit", "ebitda", "profit_before_tax", "tax_expense", "net_profit",
        "net_profit_attributable_to_owners", "eps", "diluted_eps", "other_income",
        "other_expenses", "exceptional_items", "pe_ratio", "debt_equity_ratio",
        "interest_service_coverage_ratio", "interest_coverage_ratio", "debt_service_coverage_ratio",
        "ebit", "interest_expense", "interest_on_borrowings", "interest_cost",
        "cash_available_for_debt_service", "cash_available_for_debt_servicing",
        "principal_repayment", "principal_repayments", "debt_repayment",
        "total_debt", "gross_debt", "short_term_borrowings", "long_term_borrowings",
    }
    balance_fields = {
        "total_assets", "total_equity", "total_liabilities", "current_assets",
        "current_liabilities", "non_current_assets", "non_current_liabilities",
        "borrowings_current", "borrowings_non_current", "cash_and_cash_equivalents",
        "inventories", "trade_receivables_current", "trade_payables_current",
        "paid_up_equity_capital", "other_equity", "goodwill", "property_plant_equipment",
        "total_borrowings", "total_debt", "gross_debt", "short_term_borrowings",
        "long_term_borrowings", "borrowings", "equity_attributable_to_owners",
        "equity_attributable_to_owners", "provisions_current", "current_investments",
    }
    cash_fields = {
        "cash_flow_operating", "cash_flow_investing", "cash_flow_financing",
        "net_change_in_cash", "capex",
    }
    meta_fields = ("fiscal_year", "period_end_date", "period_type", "consolidation_type", "statement_format")

    # BharatStock's annual statement payload expresses monetary statement values in INR.
    # Convert statement amounts to INR crore once, before calculations and display.
    # Per-share fields (EPS, face value), prices and ratio/multiple fields are excluded.
    monetary_fields = pnl_fields | balance_fields | cash_fields
    monetary_fields -= {"eps", "diluted_eps", "face_value_per_share", "pe_ratio",
                        "debt_equity_ratio", "interest_service_coverage_ratio",
                        "interest_coverage_ratio", "debt_service_coverage_ratio"}
    for row in rows:
        for field in monetary_fields:
            value = row.get(field)
            if isinstance(value, (int, float)):
                row[field] = value / STATEMENT_AMOUNT_DIVISOR

    def pick(row, allowed):
        return {**{k: row.get(k) for k in meta_fields if row.get(k) is not None},
                **{k: row.get(k) for k in allowed if row.get(k) is not None}}

    latest = rows[0]
    previous = rows[1] if len(rows) > 1 else {}
    market = _first_record(ratios_payload)
    ratios = {}

    # Current market/valuation ratios supplied by BharatStock.
    provider_map = {
        "price": "Current Price", "pe_ratio": "P/E", "pb_ratio": "P/B",
        "roe": "ROE", "roce": "ROCE", "dividend_yield": "Dividend Yield",
        "week_52_high": "52-Week High", "week_52_low": "52-Week Low",
    }
    for field, label in provider_map.items():
        value = _number(market, field)
        if value is None:
            value = _number(latest, field)
        if value is not None:
            ratios[label] = round(value, 2)

    revenue = _number(latest, "revenue", "total_income")
    prior_revenue = _number(previous, "revenue", "total_income")
    net_profit = _number(latest, "net_profit_attributable_to_owners", "net_profit")
    op_profit = _number(latest, "operating_profit")
    ebitda = _number(latest, "ebitda")
    pbt = _number(latest, "profit_before_tax")
    finance_cost = _number(latest, "finance_costs")
    total_assets = _number(latest, "total_assets")
    prior_assets = _number(previous, "total_assets")
    equity = _number(latest, "equity_attributable_to_owners", "total_equity")
    prior_equity = _number(previous, "equity_attributable_to_owners", "total_equity")
    current_assets = _number(latest, "current_assets")
    current_liabilities = _number(latest, "current_liabilities")
    borrowings = sum(v for v in [
        _number(latest, "borrowings_current"), _number(latest, "borrowings_non_current")
    ] if v is not None) if any(_number(latest, k) is not None for k in ("borrowings_current", "borrowings_non_current")) else None
    if borrowings is None:
        borrowings = _number(latest, "total_debt")
    avg_assets = (total_assets + prior_assets) / 2 if total_assets is not None and prior_assets is not None else None
    avg_equity = (equity + prior_equity) / 2 if equity is not None and prior_equity is not None else None

    def add(label, value):
        if value is not None:
            ratios[label] = value

    add("Revenue Growth", _ratio(revenue - prior_revenue if revenue is not None and prior_revenue is not None else None, prior_revenue, 100))
    add("Net Profit Margin", _ratio(net_profit, revenue, 100))
    add("Operating Margin", _ratio(op_profit, revenue, 100))
    add("EBITDA Margin", _ratio(ebitda, revenue, 100))
    add("PBT Margin", _ratio(pbt, revenue, 100))
    add("ROA", _ratio(net_profit, avg_assets, 100))
    add("ROE (Calculated)", _ratio(net_profit, avg_equity, 100))
    add("Current Ratio", _ratio(current_assets, current_liabilities))
    add("Asset Turnover", _ratio(revenue, avg_assets))
    add("Operating Cash Flow / Net Profit", _ratio(_number(latest, "cash_flow_operating"), net_profit))
    add("Cash Flow Margin", _ratio(_number(latest, "cash_flow_operating"), revenue, 100))
    add("EPS Growth", _ratio(
        _number(latest, "eps") - _number(previous, "eps")
        if _number(latest, "eps") is not None and _number(previous, "eps") is not None else None,
        _number(previous, "eps"), 100))

    # Keep provider-reported values in an audit-only collection initially.
    # They are promoted to headline cards only after validation.
    reported_specs = (
        (("debt_equity_ratio", "debt_to_equity_ratio"), "Debt-to-Equity"),
        (("interest_service_coverage_ratio", "interest_coverage_ratio"), "Interest Coverage"),
        (("debt_service_coverage_ratio", "dscr"), "Debt Service Coverage"),
    )
    reported_values = {}
    for keys, name in reported_specs:
        value = _number(market, *keys)
        source = "ratios endpoint"
        if value is None:
            value = _number(latest, *keys)
            source = "financial statements"
        if value is not None:
            reported_values[name] = {"value": round(value, 2), "source": source}

    # Prefer explicit total-debt fields; otherwise sum current and non-current
    # borrowings only when at least one component is present.
    if borrowings is None:
        borrowings = _number(latest, "total_borrowings", "total_debt", "gross_debt", "borrowings")
    if borrowings is None:
        short_debt = _number(latest, "short_term_borrowings")
        long_debt = _number(latest, "long_term_borrowings")
        if short_debt is not None or long_debt is not None:
            borrowings = (short_debt or 0) + (long_debt or 0)

    # Recalculate leverage after checking all supported debt field names.
    calculated_de = _ratio(borrowings, equity)
    if calculated_de is not None:
        ratios["Debt-to-Equity (Calculated)"] = calculated_de

    # Interest coverage: use explicit EBIT and interest expense where available.
    # Operating profit / total finance costs are disclosed as a proxy only.
    # Strict calculation only: do not substitute operating profit or total finance
    # costs for EBIT / interest expense. Those proxies can materially misstate coverage.
    ebit = _number(latest, "ebit")
    ebit_source = "EBIT"
    interest_expense = _number(latest, "interest_expense", "interest_on_borrowings", "interest_cost")
    interest_source = "Interest expense"
    calculated_ic = _ratio(ebit, interest_expense)
    if calculated_ic is not None:
        ratios["Interest Coverage (Calculated)"] = calculated_ic

    # DSCR is only calculated when the provider supplies all three required inputs.
    cash_available = _number(latest, "cash_available_for_debt_service", "cash_available_for_debt_servicing")
    principal = _number(latest, "principal_repayment", "principal_repayments", "debt_repayment")
    dscr_interest = _number(latest, "interest_expense", "interest_on_borrowings", "interest_cost")
    if cash_available is not None and principal is not None and dscr_interest is not None:
        calculated_dscr = _ratio(cash_available, principal + dscr_interest)
        if calculated_dscr is not None:
            ratios["Debt Service Coverage (Calculated)"] = calculated_dscr

    validation = []
    ratio_quality = {}
    comparison_specs = (
        ("Debt-to-Equity", "Debt-to-Equity (Calculated)"),
        ("Interest Coverage", "Interest Coverage (Calculated)"),
        ("Debt Service Coverage", "Debt Service Coverage (Calculated)"),
    )
    for display_name, calculated_label in comparison_specs:
        reported_entry = reported_values.get(display_name)
        calculated = ratios.get(calculated_label)
        if not reported_entry:
            ratio_quality[display_name] = {
                "status": "Calculated only" if calculated is not None else "Insufficient Data",
                "headline": f"{calculated:.2f}x (calculated)" if calculated is not None else "N/A",
                "message": "No provider-reported value was supplied; headline uses the statement calculation." if calculated is not None else "Neither a provider value nor sufficient statement inputs are available.",
            }
            continue
        reported = reported_entry["value"]
        if calculated is None:
            ratio_quality[display_name] = {"status": "Unverified", "headline": "N/A",
                                           "message": "Provider value retained in audit details; required statement inputs are unavailable."}
            validation.append({"metric": display_name, "reported": reported, "calculated": None,
                               "difference_pct": None, "status": "Unverified",
                               "message": "Not shown as a headline metric because SmartStocks cannot independently reproduce it from available statement inputs."})
            continue
        difference = abs(calculated - reported) / max(abs(reported), abs(calculated), 0.01) * 100
        if difference > 20:
            ratio_quality[display_name] = {"status": "Discrepancy", "headline": f"{calculated:.2f}x (calculated)",
                                           "message": "Reported value hidden from headline cards because it differs materially from the calculated value."}
            validation.append({"metric": display_name, "calculated": calculated, "reported": reported,
                               "difference_pct": round(difference, 1), "status": "Discrepancy",
                               "message": "Reported and calculated values differ by more than 20%. Check field mapping, financial year and standalone/consolidated basis."})
        else:
            ratio_quality[display_name] = {"status": "Consistent", "headline": f"{calculated:.2f}x (calculated)",
                                           "message": "Reported and calculated values are within the 20% comparison tolerance. The calculated value is used in the headline display."}

    ratio_notes = {
        "Interest Coverage (Calculated)": f"{ebit_source} ÷ {interest_source}" if calculated_ic is not None else "Insufficient EBIT/interest data",
        "Debt Service Coverage (Calculated)": "Cash available for debt service ÷ (principal repayments + interest)" if "Debt Service Coverage (Calculated)" in ratios else "Not calculated: cash available, principal repayment and interest expense are not all available",
        "Debt-to-Equity (Calculated)": "Total borrowings ÷ equity attributable to owners" if calculated_de is not None else "Not calculated: debt or equity input unavailable",
    }

    # Per-share valuation measures when paid-up capital and face value allow share count estimation.
    paid_up = _number(latest, "paid_up_equity_capital")
    face_value = _number(latest, "face_value_per_share")
    shares = paid_up / face_value if paid_up is not None and face_value else None
    book_value = _ratio(equity, shares) if shares else None
    if book_value is not None:
        ratios["Book Value per Share"] = book_value
    eps = _number(latest, "eps")
    if eps is not None:
        ratios["EPS"] = round(eps, 2)
    price = ratios.get("Current Price")
    if price is not None and revenue is not None and shares:
        market_cap = price * shares
        add("Price-to-Sales", _ratio(market_cap, revenue))
    pe = ratios.get("P/E")
    if pe and pe > 0:
        ratios["Earnings Yield"] = round(100 / pe, 2)

    return {
        "provider": "BharatStock", "symbol": ticker, "data_schema_version": DATA_SCHEMA_VERSION,
        "statement_currency": "INR", "statement_display_unit": "₹ crore",
        "statement_amount_divisor": STATEMENT_AMOUNT_DIVISOR, "top_ratios": ratios,
        "profit_and_loss": [pick(row, pnl_fields) for row in rows[:5]],
        "balance_sheet": [pick(row, balance_fields) for row in rows[:5]],
        "cash_flow": [pick(row, cash_fields) for row in rows[:5]],
        "financial_period": latest.get("fiscal_year"),
        "consolidation_type": latest.get("consolidation_type"),
        "ratio_as_of_date": market.get("as_of_date"),
        "financial_rows": len(rows[:5]), "available_financial_rows": len(rows),
        "financial_history_limit_note": (
            "BharatStock Free plan returns about two annual financial periods; deeper history requires a plan with historical financial access."
            if len(rows) <= 2 else "Provider returned the available annual financial history for this request."
        ),
        "ratio_rows": len(_rows(ratios_payload)), "api_calls_for_fetch": 2,
        "ratio_source": "BharatStock current ratios + locally calculated statement ratios",
        "ratio_validation_warnings": validation,
        "ratio_quality": ratio_quality,
        "ratio_reported_audit": reported_values,
        "ratio_calculation_notes": ratio_notes,
        "ratio_input_values": {
            "gross_debt": borrowings, "equity_attributable_to_owners": equity,
            "ebit_or_operating_profit_proxy": ebit, "interest_expense_or_finance_cost_proxy": interest_expense,
            "cash_available_for_debt_service": cash_available,
            "principal_repayments": principal, "dscr_interest_expense": dscr_interest,
        },
    }


def get_fundamental_data(ticker, api_key, force_refresh=False):
    ticker = str(ticker).strip().upper()
    if not ticker:
        raise ValueError("A stock ticker is required.")
    if not api_key:
        raise ValueError("BHARATSTOCK_API_KEY is not configured.")
    key = _key(ticker, api_key)
    with _connect() as conn:
        row = conn.execute("SELECT payload, fetched_at FROM fundamentals WHERE cache_key=?", (key,)).fetchone()

    if row and not force_refresh and time.time() - row[1] <= CACHE_TTL_SECONDS:
        try:
            cached = json.loads(row[0])
            cached["cache_status"] = "HIT"
            cached["api_calls_for_fetch"] = 0
            return cached
        except json.JSONDecodeError:
            pass

    try:
        # Request exactly the two annual periods supported by the configured
        # BharatStock Free-plan history entitlement. Do not advertise five years.
        financials = _request_json(
            ticker, "financials", api_key,
            {"period_type": "annual", "page": 1, "page_size": 2}
        )
        ratios = _request_json(ticker, "ratios", api_key)
        result = _normalise(ticker, financials, ratios)
        with _connect() as conn:
            conn.execute(
                """INSERT INTO fundamentals VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET ticker=excluded.ticker,
                payload=excluded.payload, fetched_at=excluded.fetched_at""",
                (key, ticker, json.dumps(result), time.time()),
            )
            conn.commit()
        result["cache_status"] = "MISS"
        return result
    except (BharatStockRateLimitError, BharatStockDailyBudgetError, RuntimeError):
        if row:
            try:
                stale = json.loads(row[0])
                stale["cache_status"] = "STALE_FALLBACK"
                stale["api_calls_for_fetch"] = 0
                return stale
            except json.JSONDecodeError:
                pass
        raise
