"""Fetch BharatStock annual statements and calculate SmartStocks ratios locally.

No BharatStock valuation/ratio endpoint is requested or used. Market-sensitive
metrics are calculated from the latest TejHQ close supplied by the dashboard.
Statement amounts are converted from INR to INR crore once, before calculations.
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
STATEMENT_AMOUNT_DIVISOR = 10_000_000
DATA_SCHEMA_VERSION = 8
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
    return hashlib.sha256(f"bharatstock-statements-v{DATA_SCHEMA_VERSION}:{fingerprint}:{ticker.upper()}".encode()).hexdigest()


def get_cache_info(ticker, api_key):
    key = _key(ticker, api_key)
    with _connect() as conn:
        row = conn.execute("SELECT fetched_at FROM fundamentals WHERE cache_key=?", (key,)).fetchone()
        count = conn.execute("SELECT COUNT(*) FROM request_log WHERE request_day=?", (date.today().isoformat(),)).fetchone()[0]
    age = max(0, time.time() - row[0]) if row else None
    return {"cached": bool(row), "fresh": bool(row and age <= CACHE_TTL_SECONDS),
            "age_hours": age / 3600 if age is not None else None,
            "calls_today": count, "daily_limit": DAILY_APP_BUDGET,
            "calls_remaining": max(0, DAILY_APP_BUDGET - count)}


def _request_financials(ticker, api_key):
    with _connect() as conn:
        used = conn.execute("SELECT COUNT(*) FROM request_log WHERE request_day=?", (date.today().isoformat(),)).fetchone()[0]
        if used >= DAILY_APP_BUDGET:
            raise BharatStockDailyBudgetError(
                f"SmartStocks reached its local {DAILY_APP_BUDGET}-request daily safety limit. Cached statements remain available; try again tomorrow."
            )
        conn.execute("INSERT INTO request_log VALUES (?, ?)", (date.today().isoformat(), time.time()))
        conn.commit()
    try:
        response = requests.get(
            f"{BASE_URL}/v1/stocks/{ticker}/financials",
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            params={"period_type": "annual", "page": 1, "page_size": 2}, timeout=25,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"BharatStock network error: {type(exc).__name__}.") from None
    if response.status_code == 429:
        raise BharatStockRateLimitError("BharatStock returned HTTP 429 (quota/rate limit). No automatic retry was attempted.")
    if response.status_code in (401, 403):
        raise RuntimeError(f"BharatStock authentication/permission error (HTTP {response.status_code}). Check the API key and plan access.")
    if not response.ok:
        raise RuntimeError(f"BharatStock returned HTTP {response.status_code} for the annual financial statements endpoint.")
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
        for name in ("data", "items", "results", "financials"):
            if isinstance(data.get(name), list):
                return data[name]
        return [data] if data else []
    return []


def _normal_key(value):
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _num(row, *keys):
    """Read numeric statement fields with tolerant key-name matching."""
    if not isinstance(row, dict):
        return None
    normalized = {_normal_key(k): v for k, v in row.items()}
    for key in keys:
        value = row.get(key)
        if value is None:
            value = normalized.get(_normal_key(key))
        if value is None or value == "":
            continue
        try:
            cleaned = str(value).replace(",", "").replace("₹", "").replace("%", "").strip()
            return float(cleaned)
        except (TypeError, ValueError):
            continue
    return None


def _safe_ratio(numerator, denominator, scale=1.0):
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator * scale, 2)


def _first_non_none(*values):
    return next((v for v in values if v is not None), None)


def _calculate(ticker, payload, market_price=None, price_history=None):
    rows = [dict(r) for r in _rows(payload) if isinstance(r, dict)]
    rows.sort(key=lambda r: str(r.get("period_end_date") or r.get("fiscal_year") or ""), reverse=True)
    if not rows:
        raise RuntimeError(f"BharatStock returned no annual financial records for {ticker}.")

    pnl_fields = {
        "revenue", "total_income", "total_expenses", "cost_of_materials_consumed", "employee_benefit_expense",
        "finance_costs", "depreciation_and_amortisation", "operating_profit", "ebitda", "profit_before_tax",
        "tax_expense", "net_profit", "net_profit_attributable_to_owners", "eps", "diluted_eps", "other_income",
        "other_expenses", "exceptional_items", "ebit", "interest_expense", "interest_on_borrowings", "interest_cost",
        "dividend_per_share", "dividend_per_share_amount", "annual_dividend_per_share", "face_value_per_share", "face_value",
        "basic_eps", "earnings_per_share", "paid_up_capital", "share_capital", "equity_share_capital",
    }
    balance_fields = {
        "total_assets", "total_equity", "total_liabilities", "current_assets", "current_liabilities",
        "non_current_assets", "non_current_liabilities", "borrowings_current", "borrowings_non_current",
        "cash_and_cash_equivalents", "inventories", "trade_receivables_current", "trade_payables_current",
        "paid_up_equity_capital", "other_equity", "goodwill", "property_plant_equipment", "total_borrowings",
        "total_debt", "gross_debt", "short_term_borrowings", "long_term_borrowings", "borrowings",
        "equity_attributable_to_owners", "provisions_current", "current_investments",
        "paid_up_capital", "share_capital", "equity_share_capital", "paid_up_share_capital",
        "issued_subscribed_and_paid_up_share_capital", "equity_attributable_to_owners_of_parent",
        "total_equity_attributable_to_owners_of_parent", "shareholders_equity_attributable_to_parent",
        "equity_attributable_to_parent", "parent_shareholders_equity", "owners_equity",
        "non_controlling_interests", "non_controlling_interest", "minority_interest", "minority_interests",
        "equity_attributable_to_non_controlling_interests", "total_shareholders_equity", "total_stockholders_equity",
    }
    cash_fields = {"cash_flow_operating", "cash_flow_investing", "cash_flow_financing", "net_change_in_cash", "capex"}
    meta_fields = ("fiscal_year", "period_end_date", "period_type", "consolidation_type", "statement_format")
    monetary_fields = pnl_fields | balance_fields | cash_fields
    monetary_fields -= {"eps", "diluted_eps", "basic_eps", "earnings_per_share", "face_value_per_share", "face_value", "dividend_per_share", "dividend_per_share_amount", "annual_dividend_per_share"}

    # API statement amounts are INR. Convert once to ₹ crore.
    for row in rows:
        for field in monetary_fields:
            value = row.get(field)
            if value is not None and value != "":
                try:
                    row[field] = float(str(value).replace(",", "").replace("₹", "").strip()) / STATEMENT_AMOUNT_DIVISOR
                except (TypeError, ValueError):
                    pass

    latest = rows[0]
    previous = rows[1] if len(rows) > 1 else {}
    revenue = _first_non_none(_num(latest, "revenue"), _num(latest, "total_income"))
    prior_revenue = _first_non_none(_num(previous, "revenue"), _num(previous, "total_income"))
    # Keep consolidated PAT and parent-attributable PAT separate: use the
    # former for whole-group margins/ROA, and the latter for parent-shareholder ROE.
    net_profit_total = _num(latest, "net_profit", "profit_after_tax", "profit_for_the_period")
    net_profit_owners = _num(latest, "net_profit_attributable_to_owners", "profit_attributable_to_owners")
    operating_profit = _first_non_none(_num(latest, "ebit"), _num(latest, "operating_profit"))
    ebitda = _num(latest, "ebitda")
    pbt = _num(latest, "profit_before_tax")
    total_assets = _num(latest, "total_assets")
    prior_assets = _num(previous, "total_assets")
    # Consolidated common-equity basis: use equity attributable to owners of
    # the parent. If only total equity is supplied, subtract NCI explicitly;
    # never silently include minority interests in parent-shareholder BVPS.
    owner_equity_aliases = (
        "equity_attributable_to_owners", "equity_attributable_to_owners_of_parent",
        "total_equity_attributable_to_owners_of_parent", "shareholders_equity_attributable_to_parent",
        "equity_attributable_to_parent", "parent_shareholders_equity", "owners_equity",
    )
    nci_aliases = ("non_controlling_interests", "non_controlling_interest", "minority_interest",
                   "minority_interests", "equity_attributable_to_non_controlling_interests")
    owner_equity = _first_non_none(*[_num(latest, k) for k in owner_equity_aliases])
    prior_owner_equity = _first_non_none(*[_num(previous, k) for k in owner_equity_aliases])
    total_equity_latest = _num(latest, "total_equity", "total_shareholders_equity", "total_stockholders_equity")
    total_equity_previous = _num(previous, "total_equity", "total_shareholders_equity", "total_stockholders_equity")
    nci_latest = _first_non_none(*[_num(latest, k) for k in nci_aliases])
    nci_previous = _first_non_none(*[_num(previous, k) for k in nci_aliases])
    if owner_equity is None and total_equity_latest is not None and nci_latest is not None:
        owner_equity = total_equity_latest - nci_latest
    if prior_owner_equity is None and total_equity_previous is not None and nci_previous is not None:
        prior_owner_equity = total_equity_previous - nci_previous
    equity = owner_equity
    prior_equity = prior_owner_equity
    current_assets = _num(latest, "current_assets")
    current_liabilities = _num(latest, "current_liabilities")
    finance_cost = _first_non_none(_num(latest, "interest_expense"), _num(latest, "interest_on_borrowings"), _num(latest, "interest_cost"), _num(latest, "finance_costs"))

    debt_parts = [_num(latest, "borrowings_current"), _num(latest, "borrowings_non_current")]
    debt = sum(debt_parts) if any(v is not None for v in debt_parts) else _first_non_none(
        _num(latest, "total_borrowings"), _num(latest, "total_debt"), _num(latest, "gross_debt"), _num(latest, "borrowings")
    )
    if debt is None:
        short_debt, long_debt = _num(latest, "short_term_borrowings"), _num(latest, "long_term_borrowings")
        if short_debt is not None or long_debt is not None:
            debt = (short_debt or 0) + (long_debt or 0)

    avg_assets = (total_assets + prior_assets) / 2 if total_assets is not None and prior_assets is not None else None
    avg_equity = (equity + prior_equity) / 2 if equity is not None and prior_equity is not None else None

    # Capital employed = total assets - current liabilities for each year.
    # ROCE uses the average of opening and closing capital employed, not closing only.
    prior_current_liabilities = _num(previous, "current_liabilities")
    current_capital_employed = (
        total_assets - current_liabilities
        if total_assets is not None and current_liabilities is not None else None
    )
    prior_capital_employed = (
        prior_assets - prior_current_liabilities
        if prior_assets is not None and prior_current_liabilities is not None else None
    )
    avg_capital_employed = (
        (current_capital_employed + prior_capital_employed) / 2
        if current_capital_employed is not None and prior_capital_employed is not None else None
    )

    paid_up_capital = _first_non_none(*[_num(latest, k) for k in (
        "paid_up_equity_capital", "paid_up_share_capital", "paid_up_capital",
        "share_capital", "equity_share_capital", "issued_subscribed_and_paid_up_share_capital"
    )])
    face_value = _first_non_none(*[_num(latest, k) for k in (
        "face_value_per_share", "face_value", "equity_share_face_value"
    )])
    # This is an estimate from issued/paid-up equity share capital, never authorised capital.
    shares_crore = paid_up_capital / face_value if paid_up_capital is not None and face_value not in (None, 0) else None
    # ₹ crore / crore shares = ₹ per share.
    book_value_per_share = _safe_ratio(equity, shares_crore) if shares_crore else None
    eps_key_candidates = ("diluted_eps", "eps", "basic_eps", "earnings_per_share")
    eps_key = next((k for k in eps_key_candidates if _num(latest, k) is not None), None)
    eps = _num(latest, eps_key) if eps_key else None
    prior_eps = _num(previous, eps_key) if eps_key else None
    price = float(market_price) if market_price is not None else None

    ratios = {}
    def put(name, value):
        if value is not None:
            ratios[name] = round(float(value), 2)

    # Entire ratio set below is calculated from statements + TejHQ market close.
    put("Current Price", price)
    put("Market Cap (Estimated)", price * shares_crore if price is not None and shares_crore is not None else None)  # ₹ crore
    put("Face Value", face_value)
    put("EPS", eps)
    put("Book Value per Share", book_value_per_share)
    put("P/E (Annual)", _safe_ratio(price, eps))
    # Quarterly statements are not requested by this integration; do not invent TTM EPS.
    put("P/B", _safe_ratio(price, book_value_per_share))
    put("Price-to-Sales", _safe_ratio(price * shares_crore, revenue) if price is not None and shares_crore and revenue else None)
    put("Earnings Yield", _safe_ratio(eps, price, 100))
    put("Revenue Growth", _safe_ratio(revenue - prior_revenue if revenue is not None and prior_revenue is not None else None, prior_revenue, 100))
    put("EPS Growth", _safe_ratio(eps - prior_eps if eps is not None and prior_eps is not None else None, prior_eps, 100))
    put("Net Profit Margin", _safe_ratio(net_profit_total, revenue, 100))
    put("Operating Margin", _safe_ratio(operating_profit, revenue, 100))
    put("EBITDA Margin", _safe_ratio(ebitda, revenue, 100))
    put("PBT Margin", _safe_ratio(pbt, revenue, 100))
    put("ROE", _safe_ratio(net_profit_owners, avg_equity, 100))
    put("ROA", _safe_ratio(net_profit_total, avg_assets, 100))
    put("ROCE", _safe_ratio(operating_profit, avg_capital_employed, 100))
    put("Debt-to-Equity", _safe_ratio(debt, equity))
    put("Current Ratio", _safe_ratio(current_assets, current_liabilities))
    put("Interest Coverage", _safe_ratio(operating_profit, finance_cost))
    put("Asset Turnover", _safe_ratio(revenue, avg_assets))
    operating_cash_flow = _num(latest, "cash_flow_operating")
    put("Operating Cash Flow / Net Profit", _safe_ratio(operating_cash_flow, net_profit_total))
    put("Cash Flow Margin", _safe_ratio(operating_cash_flow, revenue, 100))

    dividend_per_share = _first_non_none(
        _num(latest, "dividend_per_share"), _num(latest, "dividend_per_share_amount"),
        _num(latest, "annual_dividend_per_share"),
    )
    put("Dividend per Share", dividend_per_share)
    put("Dividend Yield", _safe_ratio(dividend_per_share, price, 100))

    high_52 = low_52 = None
    market_price_date = None
    if price_history is not None and not getattr(price_history, "empty", True):
        try:
            market_price_date = str(price_history.index.max().date())
        except Exception:
            market_price_date = str(price_history.index.max())
        hist = price_history.copy()
        if "Close" in hist.columns:
            try:
                cutoff = hist.index.max() - __import__("pandas").Timedelta(days=365)
                last_year = hist.loc[hist.index >= cutoff]
                # Do not mislabel a 6-month chart range as a 52-week range.
                covered_days = (hist.index.max() - last_year.index.min()).days if not last_year.empty else 0
                if not last_year.empty and covered_days >= 350:
                    high_52 = float(last_year["Close"].max())
                    low_52 = float(last_year["Close"].min())
            except Exception:
                pass
    put("52-Week High", high_52)
    put("52-Week Low", low_52)

    def pick(row, allowed):
        return {**{k: row.get(k) for k in meta_fields if row.get(k) is not None},
                **{k: row.get(k) for k in allowed if row.get(k) is not None}}

    calculation_notes = {
        "P/E (Annual)": "Latest TejHQ closing price ÷ latest full-year EPS. This is annual P/E, not TTM P/E. Quarterly statements are not currently requested, so TTM P/E is intentionally not shown.",
        "P/B": "Latest TejHQ closing price ÷ calculated book value per share.",
        "Book Value per Share": "Consolidated equity attributable to owners of the parent ÷ estimated ordinary shares outstanding. Shares are estimated from paid-up equity share capital ÷ face value. Non-controlling interests are excluded; if parent equity cannot be isolated, BVPS and P/B are N/A.",
        "Market Cap (Estimated)": "Latest TejHQ closing price × estimated shares outstanding. Shares are estimated only from paid-up/issued equity share capital ÷ face value; authorised capital is never used. Treat as estimated until reconciled to the latest share count.",
        "ROE": "Annual profit attributable to owners of the parent ÷ average opening and closing parent-attributable equity. Requires both annual balance sheets and owner-attributable profit.",
        "ROA": "Consolidated profit for the period ÷ average opening and closing consolidated total assets. Requires two annual balance sheets.",
        "ROCE": "EBIT (or operating profit if EBIT is absent) ÷ average opening and closing capital employed, where capital employed = total assets − current liabilities. Requires two annual balance sheets.",
        "Dividend Yield": "Latest annual dividend per share found in statement ÷ latest TejHQ closing price. N/A if dividend/share is not supplied.",
        "Interest Coverage": "EBIT (or operating profit if EBIT absent) ÷ interest expense (finance costs used only if explicit interest fields absent).",
    }
    return {
        "provider": "BharatStock annual statements + TejHQ price history",
        "symbol": ticker, "data_schema_version": DATA_SCHEMA_VERSION,
        "statement_currency": "INR", "statement_display_unit": "₹ crore",
        "statement_amount_divisor": STATEMENT_AMOUNT_DIVISOR,
        "top_ratios": ratios,
        "profit_and_loss": [pick(row, pnl_fields) for row in rows[:5]],
        "balance_sheet": [pick(row, balance_fields) for row in rows[:5]],
        "cash_flow": [pick(row, cash_fields) for row in rows[:5]],
        "financial_period": latest.get("fiscal_year") or latest.get("period_end_date"),
        "previous_financial_period": previous.get("fiscal_year") or previous.get("period_end_date"),
        "market_price_date": market_price_date,
        "consolidation_type": latest.get("consolidation_type"),
        "financial_rows": min(len(rows), 5), "available_financial_rows": len(rows),
        "financial_history_limit_note": "Two annual periods requested; ratios requiring average balance-sheet values are N/A if the prior period is unavailable.",
        "api_calls_for_fetch": 1,
        "ratio_source": "All ratios calculated locally from BharatStock annual statements and TejHQ closing price; BharatStock ratios endpoint is not used.",
        "ratio_calculation_notes": calculation_notes,
        "ratio_input_values": {
            "revenue": revenue, "prior_revenue": prior_revenue,
            "net_profit_total": net_profit_total, "net_profit_attributable_to_owners": net_profit_owners,
            "operating_profit_or_ebit": operating_profit, "ebitda": ebitda,
            "total_assets": total_assets, "prior_total_assets": prior_assets,
            "current_capital_employed": current_capital_employed,
            "prior_capital_employed": prior_capital_employed,
            "average_capital_employed": avg_capital_employed,
            "equity": equity, "prior_equity": prior_equity, "total_equity_latest": total_equity_latest,
            "non_controlling_interests_latest": nci_latest, "equity_basis": "parent owners equity" if owner_equity is not None else "unavailable",
            "debt": debt,
            "paid_up_equity_capital": paid_up_capital, "face_value": face_value,
            "estimated_shares_crore": shares_crore, "eps": eps, "prior_eps": prior_eps,
            "eps_basis_field": eps_key,
            "dividend_per_share": dividend_per_share, "market_price": price,
        },
    }


def get_fundamental_data(ticker, api_key, force_refresh=False, market_price=None, price_history=None):
    ticker = str(ticker).strip().upper()
    if not ticker:
        raise ValueError("A stock ticker is required.")
    if not api_key:
        raise ValueError("BHARATSTOCK_API_KEY is not configured.")
    key = _key(ticker, api_key)
    with _connect() as conn:
        row = conn.execute("SELECT payload, fetched_at FROM fundamentals WHERE cache_key=?", (key,)).fetchone()

    payload = None
    cache_status = "MISS"
    if row and not force_refresh and time.time() - row[1] <= CACHE_TTL_SECONDS:
        try:
            payload = json.loads(row[0])
            cache_status = "HIT"
        except json.JSONDecodeError:
            payload = None
    if payload is None:
        try:
            payload = _request_financials(ticker, api_key)
        except (BharatStockRateLimitError, BharatStockDailyBudgetError, RuntimeError):
            if row:
                try:
                    payload = json.loads(row[0])
                    cache_status = "STALE_FALLBACK"
                except json.JSONDecodeError:
                    raise
            else:
                raise
        else:
            with _connect() as conn:
                conn.execute(
                    """INSERT INTO fundamentals VALUES (?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET ticker=excluded.ticker,
                    payload=excluded.payload, fetched_at=excluded.fetched_at""",
                    (key, ticker, json.dumps(payload), time.time()),
                )
                conn.commit()
    result = _calculate(ticker, payload, market_price=market_price, price_history=price_history)
    # Keep the raw annual statement response in session state so market-sensitive
    # ratios can be recalculated on every price refresh without another API call.
    result["_raw_statement_payload"] = payload
    result["cache_status"] = cache_status
    result["api_calls_for_fetch"] = 1 if cache_status == "MISS" else 0
    return result


def recalculate_fundamental_data(fdata, market_price=None, price_history=None):
    """Recalculate all price-sensitive valuation metrics from cached statements.

    This function makes no network requests. It is safe to call on every
    Streamlit rerun with the latest available market close.
    """
    if not isinstance(fdata, dict) or "_raw_statement_payload" not in fdata:
        return fdata
    payload = fdata["_raw_statement_payload"]
    ticker = fdata.get("symbol", "")
    refreshed = _calculate(
        ticker, payload, market_price=market_price, price_history=price_history
    )
    refreshed["_raw_statement_payload"] = payload
    refreshed["cache_status"] = fdata.get("cache_status", "SESSION")
    refreshed["api_calls_for_fetch"] = 0
    return refreshed
