import os
from io import BytesIO

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from data.fetch_data import fetch_stock_data
from data.stock_master import load_stock_master, refresh_stock_master
from indicators.moving_average import calculate_ma
from indicators.rsi import calculate_rsi
from indicators.macd import calculate_macd
from indicators.bollinger_band import bollinger_band
from indicators.adx import calculate_adx
from analysis.recommendation import generate_recommendation, calculate_volume
from fundamentals.ratio import (
    get_fundamental_data, recalculate_fundamental_data, get_cache_info,
    BharatStockRateLimitError, BharatStockDailyBudgetError,
)
from fundamentals.helpers import (
    performance_returns, risk_metrics, rows_to_frame, format_statement_frame, statement_excel_frame,
)
from ui.charts import plot_price_chart
from utils.formatters import format_large_number


st.set_page_config(page_title="SmartStocks AI", layout="wide")
st.title("SmartStocks AI")
st.sidebar.title("📊 SmartStocks AI")
st.sidebar.subheader("Chart indicators")

show_ma20 = st.sidebar.checkbox("MA20", key="show_ma20")
show_ma50 = st.sidebar.checkbox("MA50", value=True, key="show_ma50")
show_ma100 = st.sidebar.checkbox("MA100", key="show_ma100")
show_bollinger = st.sidebar.checkbox("Bollinger Bands", key="show_bollinger")
show_adx = st.sidebar.checkbox("ADX", key="show_adx")

stocks = load_stock_master("stocks.csv")
for col in ["SYMBOL", "NAME OF COMPANY", "EXCHANGE", "SECURITY_CODE"]:
    if col not in stocks.columns:
        stocks[col] = ""
    stocks[col] = stocks[col].fillna("").astype(str).str.strip()

st.sidebar.divider()
st.sidebar.caption(f"Stock master: {len(stocks):,} securities")
if st.sidebar.button("🔄 Refresh NSE + BSE Stock List", use_container_width=True):
    with st.spinner("Refreshing exchange lists..."):
        try:
            refreshed = refresh_stock_master("stocks.csv")
            st.sidebar.success(
                f"{refreshed['total']:,} securities: "
                f"{refreshed['nse']:,} NSE / {refreshed['bse']:,} BSE"
            )
            for exchange, message in refreshed["messages"].items():
                st.sidebar.caption(f"{exchange}: {message}")
            st.rerun()
        except Exception as exc:
            st.sidebar.error(str(exc))

# Search and stock selection
search = st.text_input(
    "🔎 Search Stock",
    placeholder="Enter ticker, company name or BSE scrip code",
    key="stock_search",
)
matches = stocks.iloc[0:0].copy()
if search.strip():
    q = search.strip().lower()
    matches = stocks[
        stocks["SYMBOL"].str.lower().str.contains(q, na=False)
        | stocks["NAME OF COMPANY"].str.lower().str.contains(q, na=False)
        | stocks["SECURITY_CODE"].str.lower().str.contains(q, na=False)
    ].head(25).copy()

if not matches.empty:
    matches["DISPLAY"] = matches.apply(
        lambda r: f"{r['SYMBOL']} — {r['NAME OF COMPANY']} [{r['EXCHANGE']}]"
        + (f" | Code: {r['SECURITY_CODE']}" if r["SECURITY_CODE"] else ""),
        axis=1,
    )
    display_options = matches["DISPLAY"].tolist()
    previous_display = st.session_state.get("selected_stock_display")
    default_index = display_options.index(previous_display) if previous_display in display_options else 0
    selected = st.selectbox("Select a stock", display_options, index=default_index, key="selected_stock")
    selected_row = matches.loc[matches["DISPLAY"] == selected].iloc[0]
    ticker = selected_row["SYMBOL"]
    exchange = selected_row["EXCHANGE"]
    security_code = selected_row["SECURITY_CODE"]
    st.session_state["selected_stock_display"] = selected
else:
    ticker = search.strip().upper()
    exchange, security_code = "NSE", ""

time_period = st.selectbox("Select price history", ["6mo", "1y", "5y", "max"], index=1, key="price_period")

if ticker and exchange == "BSE":
    st.info(
        f"BSE security selected: {ticker} (scrip code {security_code or 'N/A'}). "
        "BSE discovery/search is enabled; BSE historical-price integration is not yet connected."
    )

# Fetch only computes and saves the analysis. All display sections are outside this button.
if st.button("Fetch Data", type="primary", key="fetch_stock_data"):
    if not ticker:
        st.warning("Search for a stock first.")
    elif exchange == "BSE":
        st.warning(
            "BSE historical prices are not yet connected. The stock is available in "
            "the combined master, but price charts and technical analysis currently require NSE data."
        )
    else:
        with st.spinner(f"Fetching {ticker} market data..."):
            try:
                df, actual_ticker = fetch_stock_data(ticker, period=time_period)
                if df is None or df.empty or "Close" not in df.columns:
                    raise ValueError(f"No usable price history was returned for {ticker}.")

                df = df.dropna(subset=["Close"]).sort_index()
                if df.empty:
                    raise ValueError(f"No valid closing prices were returned for {ticker}.")

                for enabled, window in [(show_ma20, 20), (show_ma50, 50), (show_ma100, 100)]:
                    if enabled or window == 50:
                        df = calculate_ma(df, window)
                df = calculate_rsi(df, 14)
                df = calculate_macd(df)
                df = bollinger_band(df)
                df = calculate_volume(df)
                df = calculate_adx(df)

                result = generate_recommendation(df)
                risk = risk_metrics(df)

                st.session_state["smartstock_analysis"] = {
                    "ticker": ticker,
                    "actual_ticker": actual_ticker,
                    "exchange": exchange,
                    "period": time_period,
                    "df": df,
                    "result": result,
                    "risk": risk,
                }
                # Changing the selected company clears old company-specific data.
                st.session_state.pop(f"fundamentals_{ticker}", None)
                st.session_state.pop(f"peers_{ticker}", None)
                st.success(f"Analysis loaded for {ticker}.")
            except ValueError as exc:
                st.error(f"Unable to fetch/analyse this stock: {exc}")
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")

# Render the dashboard from saved session state, not from the Fetch Data button click.
analysis = st.session_state.get("smartstock_analysis")
if analysis:
    ticker_loaded = analysis["ticker"]
    df = analysis["df"]
    result = analysis["result"]
    risk = analysis["risk"]
    loaded_period = analysis["period"]

    if ticker_loaded != ticker:
        st.info(f"Analysis currently loaded for {ticker_loaded}. Click Fetch Data to load {ticker}.")
    else:
        st.subheader(f"{ticker_loaded} — Stock Analysis")

        current_price = float(df["Close"].iloc[-1])
        previous_price = float(df["Close"].iloc[-2]) if len(df) > 1 else None
        price_change = current_price - previous_price if previous_price is not None else None
        pct_change = price_change / previous_price * 100 if previous_price else None

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "📈 Current Price",
            f"₹{current_price:,.2f}",
            delta=f"{price_change:+.2f} ({pct_change:+.2f}%)" if pct_change is not None else "Insufficient history",
        )
        c2.metric(
            "📊 Latest Volume",
            format_large_number(df["Volume"].iloc[-1]) if "Volume" in df.columns else "N/A",
        )
        c3.metric("⬆️ High in selected period", f"₹{df['High'].max():,.2f}" if "High" in df.columns else "N/A")
        c4.metric("⬇️ Low in selected period", f"₹{df['Low'].min():,.2f}" if "Low" in df.columns else "N/A")

        overview, technical, performance, risk_tab, fundamentals, valuation, peers, reports = st.tabs([
            "📊 Overview", "📈 Technical", "💰 Performance", "⚠️ Risk",
            "🔎 Fundamentals", "💎 Valuation", "🆚 Peer Comparison", "📄 Reports",
        ])

        with overview:
            st.subheader("Technical Signal")
            st.caption(result["Method"] + " Scores are descriptive indicators, not guaranteed predictions.")
            signal = result["Signal"]
            if signal == "BUY":
                st.success(f"BUY — Score {result['Score']}/10")
            elif signal == "SELL":
                st.error(f"SELL — Score {result['Score']}/10")
            else:
                st.warning(f"HOLD — Score {result['Score']}/10")
            st.write(
                f"**Confidence proxy:** {result['Confidence']:.1f}% "
                "(absolute score divided by maximum score; not a statistical probability)"
            )
            st.write("**Reasons**")
            for reason in result["Reasons"]:
                st.write(f"• {reason}")
            st.write("**Indicator score breakdown**")
            score_frame = pd.DataFrame([
                {"Indicator": key, "Points": value}
                for key, value in result["IndicatorScores"].items()
            ])
            st.dataframe(score_frame, hide_index=True, use_container_width=True)
            st.caption(
                "Scoring: RSI ±2, MACD ±2, 50-day MA ±2, Bollinger ±2, Volume ±1, ADX ±1. "
                "BUY ≥ +3; SELL ≤ −3; otherwise HOLD."
            )

        with technical:
            st.subheader("Technical Analysis")
            try:
                fig = plot_price_chart(
                    df, analysis["actual_ticker"], show_ma20, show_ma50,
                    show_ma100, show_bollinger, show_adx,
                )
                st.plotly_chart(fig, use_container_width=True)
            except Exception as exc:
                st.warning(f"Unable to draw the technical chart: {exc}")

        with performance:
            st.subheader("Historical Performance")
            returns = performance_returns(df)
            cols = st.columns(5)
            for col, label in zip(cols, ["1D", "1W", "1M", "6M", "1Y"]):
                val = returns[label]
                col.metric(label, f"{val:+.2f}%" if val is not None else "N/A")
            st.caption(
                "Returns use the latest available close and the last available close on or before "
                "each calendar lookback. N/A means insufficient history."
            )

        with risk_tab:
            st.subheader("Risk Metrics")
            r1, r2 = st.columns(2)
            r1.metric(
                "Annualized Volatility",
                f"{risk['annualized_volatility']:.2f}%"
                if risk["annualized_volatility"] is not None else "N/A",
            )
            r2.metric(
                "Maximum Drawdown",
                f"{risk['maximum_drawdown']:.2f}%"
                if risk["maximum_drawdown"] is not None else "N/A",
            )
            st.caption(
                f"Volatility annualized using daily close-to-close returns × √252. "
                f"Calculated over selected {loaded_period} history."
            )
            st.caption("Maximum drawdown is the largest peak-to-trough decline in the selected history.")

        load_dotenv()
        try:
            api_key = st.secrets.get("BHARATSTOCK_API_KEY", "")
        except Exception:
            api_key = ""
        if not api_key:
            api_key = os.getenv("BHARATSTOCK_API_KEY", "")

        with fundamentals:
            st.subheader("Fundamental Analysis")
            if api_key:
                cache_info = get_cache_info(ticker_loaded, api_key)
                cache_label = "Fresh local cache available" if cache_info["fresh"] else (
                    "Older local cache available" if cache_info["cached"] else "No local cache yet"
                )
                st.caption(
                    f"BharatStock cache: {cache_label} · SmartStock API calls today: "
                    f"{cache_info['calls_today']}/{cache_info['daily_limit']} calls today · {cache_info['calls_remaining']} remaining"
                )
            load_col, refresh_col = st.columns(2)
            load_clicked = load_col.button("Load Fundamental Data", key=f"load_fundamentals_{ticker_loaded}")
            refresh_clicked = refresh_col.button("↻ Refresh Statements", key=f"refresh_fundamentals_{ticker_loaded}", help="Bypass the 24-hour statement cache. Uses one BharatStock annual-financials request.")
            if load_clicked or refresh_clicked:
                if not api_key:
                    st.error("BHARATSTOCK_API_KEY not found in Streamlit Secrets or local .env.")
                else:
                    try:
                        with st.spinner(f"Loading annual statements for {ticker_loaded} and calculating ratios..."):
                            data = get_fundamental_data(
                                ticker_loaded, api_key, force_refresh=refresh_clicked,
                                market_price=current_price, price_history=df,
                            )
                        st.session_state[f"fundamentals_{ticker_loaded}"] = data
                        st.success(f"Statements loaded · {data.get('api_calls_for_fetch', 0)} API call(s) used · cache {data.get('cache_status', 'MISS')}")
                    except BharatStockDailyBudgetError as exc:
                        st.warning(str(exc))
                    except BharatStockRateLimitError as exc:
                        st.warning(f"{exc} Try again tomorrow; avoid repeated clicks.")
                    except Exception as exc:
                        st.error(f"BharatStock request failed: {exc}")

            fdata = st.session_state.get(f"fundamentals_{ticker_loaded}")
            if fdata:
                st.caption(
                    f"Annual financial statements · {fdata.get('financial_rows', 0)} year(s) returned by BharatStock. "
                    + fdata.get("financial_history_limit_note", "")
                )
                st.caption(f"Calculation source: {fdata.get('ratio_source', 'SmartStocks local calculations')} · Financial period: {fdata.get('financial_period') or 'Not supplied'} · TejHQ closing price date: {fdata.get('market_price_date') or 'Not supplied'}")
                pnl = rows_to_frame(fdata.get("profit_and_loss", []))
                bs = rows_to_frame(fdata.get("balance_sheet", []))
                cf = rows_to_frame(fdata.get("cash_flow", []))
                st.caption("BharatStock supplies annual financial statements only. SmartStocks calculates every displayed ratio locally; no BharatStock valuation/ratios endpoint is used. Statement amounts are ₹ crore; per-share values are ₹/share.")
                with st.expander("Profit & Loss — Annual history", expanded=True):
                    if not pnl.empty:
                        st.dataframe(format_statement_frame(pnl), use_container_width=True, hide_index=True)
                    else:
                        st.info("Profit & Loss history is unavailable for this company.")
                with st.expander("Balance Sheet — Annual history"):
                    if not bs.empty:
                        st.dataframe(format_statement_frame(bs), use_container_width=True, hide_index=True)
                    else:
                        st.info("Balance Sheet history is unavailable for this company.")
                with st.expander("Cash Flow — Annual history"):
                    if not cf.empty:
                        st.dataframe(format_statement_frame(cf), use_container_width=True, hide_index=True)
                    else:
                        st.info("Cash Flow history is unavailable for this company.")
            else:
                st.info("Load BharatStock data for the selected company. API coverage may vary.")

        fdata = st.session_state.get(f"fundamentals_{ticker_loaded}")
        with valuation:
            st.subheader("Valuation")
            refresh_market_col, market_status_col = st.columns([1, 2])
            refresh_market_clicked = refresh_market_col.button(
                "↻ Refresh Market Data", key=f"refresh_market_{ticker_loaded}",
                help="Fetch the latest available TejHQ closing price and recalculate valuation ratios. This does not refresh annual statements."
            )
            if refresh_market_clicked:
                try:
                    with st.spinner("Refreshing latest available market prices..."):
                        market_df, market_actual_ticker = fetch_stock_data(ticker_loaded, period="1y")
                        if market_df is None or market_df.empty or "Close" not in market_df.columns:
                            raise ValueError("No usable market-price history was returned.")
                        market_df = market_df.dropna(subset=["Close"]).sort_index()
                        if market_df.empty:
                            raise ValueError("No valid closing prices were returned.")
                        for enabled, window in [(show_ma20, 20), (show_ma50, 50), (show_ma100, 100)]:
                            if enabled or window == 50:
                                market_df = calculate_ma(market_df, window)
                        market_df = calculate_rsi(market_df, 14)
                        market_df = calculate_macd(market_df)
                        market_df = bollinger_band(market_df)
                        market_df = calculate_volume(market_df)
                        market_df = calculate_adx(market_df)
                        refreshed_analysis = dict(analysis)
                        refreshed_analysis.update({
                            "actual_ticker": market_actual_ticker,
                            "period": "1y",
                            "df": market_df,
                            "result": generate_recommendation(market_df),
                            "risk": risk_metrics(market_df),
                        })
                        st.session_state["smartstock_analysis"] = refreshed_analysis
                    st.rerun()
                except Exception as exc:
                    st.error(f"Market-data refresh failed: {exc}")

            # Recompute valuation ratios from cached annual statements and the
            # latest available close on every rerun. No BharatStock call occurs.
            if fdata:
                fdata = recalculate_fundamental_data(
                    fdata, market_price=current_price, price_history=df
                )
                st.session_state[f"fundamentals_{ticker_loaded}"] = fdata
                ratios = fdata.get("top_ratios", {}) or {}
                st.caption(
                    f"Financial statements: {fdata.get('financial_period') or 'period unavailable'} "
                    f"(previous period: {fdata.get('previous_financial_period') or 'unavailable'}); "
                    f"market close date: {fdata.get('market_price_date') or 'unavailable'}. "
                    "Price-sensitive valuation metrics are recalculated on each rerun using the latest available TejHQ close. "
                    "Use Refresh Market Data to fetch a newer close. This is not an intraday/live quote. "
                    "P/E is annual, not TTM. Market cap is an estimate based on paid-up share capital and face value."
                )
                groups = {
                    "Market & valuation": ["Market Cap (Estimated)", "Current Price", "P/E (Annual)", "P/B", "Price-to-Sales", "Earnings Yield", "EPS", "Book Value per Share", "Face Value", "52-Week High", "52-Week Low"],
                    "Profitability & returns": ["ROE", "ROCE", "ROA", "Revenue Growth", "EPS Growth", "Net Profit Margin", "Operating Margin", "EBITDA Margin", "PBT Margin", "Dividend per Share", "Dividend Yield"],
                    "Debt & liquidity": ["Debt-to-Equity", "Current Ratio", "Interest Coverage"],
                    "Efficiency & cash flow": ["Asset Turnover", "Operating Cash Flow / Net Profit", "Cash Flow Margin"],
                }
                percent_names = {"ROE", "ROCE", "ROA", "Revenue Growth", "EPS Growth", "Net Profit Margin", "Operating Margin", "EBITDA Margin", "PBT Margin", "Dividend Yield", "Earnings Yield", "Cash Flow Margin"}
                currency_names = {"Current Price", "EPS", "Book Value per Share", "Face Value", "Dividend per Share", "52-Week High", "52-Week Low"}
                multiple_names = {"P/E (Annual)", "P/B", "Price-to-Sales", "Debt-to-Equity", "Current Ratio", "Interest Coverage", "Asset Turnover", "Operating Cash Flow / Net Profit"}
                crore_names = {"Market Cap (Estimated)"}
                ratio_help = {
                    "Market Cap (Estimated)": "Latest TejHQ closing price × estimated shares outstanding. Shares are estimated from paid-up/issued equity share capital ÷ face value; authorised capital is not used. Verify against the latest share count.",
                    "Current Price": "Latest available TejHQ closing price. Price-sensitive valuation ratios are recalculated whenever market data is refreshed; this is not an intraday quote.",
                    "Face Value": "Face value per equity share from the annual financial statement.",
                    "Dividend per Share": "Latest annual dividend per share found in the statement; N/A if not supplied.",
                    "P/E (Annual)": "SmartStocks calculation: latest TejHQ closing price ÷ latest full-year EPS. This is annual P/E, not TTM P/E. Quarterly data is not currently requested, so TTM P/E is not shown.",
                    "P/B": "SmartStocks calculation: latest TejHQ closing price ÷ book value per share attributable to parent ordinary shareholders. Consolidated non-controlling interests are excluded; P/B is unavailable if parent equity cannot be isolated.",
                    "Price-to-Sales": "Market value relative to annual revenue. Compare mainly within the same industry.",
                    "Earnings Yield": "Earnings per share divided by market price, expressed as a percentage. It is the inverse of P/E when inputs are consistent.",
                    "EPS": "Earnings Per Share: profit attributable to each ordinary share.",
                    "Book Value per Share": "Net assets attributable to ordinary shareholders divided by shares outstanding.",
                    "52-Week High": "Highest recorded market price over the last 52 weeks.",
                    "52-Week Low": "Lowest recorded market price over the last 52 weeks.",
                    "ROE": "Annual profit attributable to owners of the parent ÷ average opening and closing parent-attributable equity.",
                    "ROCE": "EBIT (or operating profit if EBIT is absent) ÷ average opening and closing capital employed. Capital employed = total assets − current liabilities.",
                    "ROA": "Consolidated profit for the period ÷ average opening and closing consolidated total assets.",
                    "ROA": "Return on Assets: profit relative to total assets.",
                    "Revenue Growth": "Year-on-year change in revenue. Positive growth means revenue increased versus the prior period.",
                    "EPS Growth": "Year-on-year change in earnings per share. Can be volatile when prior-period EPS is small or negative.",
                    "Net Profit Margin": "Net profit divided by revenue. Shows how much profit remains from each rupee of sales.",
                    "Operating Margin": "Operating profit divided by revenue. Measures profitability from core operations.",
                    "EBITDA Margin": "EBITDA divided by revenue. Measures operating earnings before interest, tax, depreciation and amortisation as a share of sales.",
                    "PBT Margin": "Profit before tax divided by revenue.",
                    "Dividend Yield": "Annual dividend per share divided by current share price. The yield can change as the share price moves.",
                    "Debt-to-Equity (Calculated)": "Calculated interest-bearing debt divided by shareholders' equity. Confirm the debt and equity definitions and reporting basis.",
                    "Current Ratio": "Current assets divided by current liabilities. A measure of short-term liquidity.",
                    "Interest Coverage": "SmartStocks calculation: EBIT (or operating profit if EBIT is absent) ÷ interest expense (finance costs only if explicit interest fields are absent).",
                    "Debt Service Coverage (Calculated)": "Cash available for debt service divided by scheduled principal and interest payments. Requires complete, consistently defined inputs.",
                    "Asset Turnover": "Revenue divided by average or reported total assets. Measures how efficiently assets generate sales.",
                    "Operating Cash Flow / Net Profit": "Operating cash flow divided by net profit. Helps compare cash generation with accounting earnings.",
                    "Cash Flow Margin": "Operating cash flow divided by revenue. Shows the share of sales converted into operating cash flow.",
                }
                any_metric = False
                for group_name, names in groups.items():
                    present = [(name, ratios[name]) for name in names if name in ratios and isinstance(ratios[name], (int, float))]
                    if not present:
                        continue
                    any_metric = True
                    st.markdown(f"#### {group_name}")
                    cols = st.columns(3)
                    for i, (name, value) in enumerate(present):
                        shown = f"{value:,.2f}%" if name in percent_names else (f"₹{value:,.2f} Cr." if name in crore_names else (f"₹{value:,.2f}" if name in currency_names else (f"{value:,.2f}x" if name in multiple_names else f"{value:,.2f}")))
                        help_text = ratio_help.get(name, "Financial metric returned by the data source. Review its definition and reporting period before comparing companies.")
                        cols[i % 3].metric(f"ⓘ {name}", shown, help=help_text)
                if not any_metric:
                    st.info("Valuation and ratio data is not available for this company in the current API response.")
            else:
                st.info("Load BharatStock data in Fundamentals first.")

        with peers:
            st.subheader("Peer Comparison")
            st.caption("Search by company name or symbol, then select one or more companies. You do not need to know the ticker.")
            peer_universe = stocks.copy()
            peer_universe = peer_universe[peer_universe["SYMBOL"].ne(ticker_loaded)]
            peer_universe = peer_universe[peer_universe["EXCHANGE"].str.upper().eq("NSE")]
            peer_universe = peer_universe.drop_duplicates(subset=["SYMBOL"], keep="first")
            peer_universe["PEER_LABEL"] = peer_universe.apply(
                lambda r: f"{r['NAME OF COMPANY']} ({r['SYMBOL']})", axis=1
            )
            peer_labels = peer_universe["PEER_LABEL"].drop_duplicates().tolist()
            selected_peer_labels = st.multiselect(
                "Find and select peer companies",
                options=peer_labels,
                key=f"peer_select_{ticker_loaded}",
                placeholder="Type a company name or ticker to search...",
            )
            if st.button("Compare Selected Companies", key=f"compare_peers_{ticker_loaded}"):
                if not api_key:
                    st.error("BHARATSTOCK_API_KEY not found in Streamlit Secrets or local .env.")
                elif not selected_peer_labels:
                    st.warning("Search for and select at least one peer company.")
                else:
                    label_to_symbol = dict(zip(peer_universe["PEER_LABEL"], peer_universe["SYMBOL"]))
                    symbols = list(dict.fromkeys([ticker_loaded] + [label_to_symbol[x] for x in selected_peer_labels]))
                    company_names = dict(zip(stocks["SYMBOL"], stocks["NAME OF COMPANY"]))
                    company_names.setdefault(ticker_loaded, ticker_loaded)
                    rows = []
                    progress = st.progress(0)
                    peer_errors = []
                    # Keep the comparison table focused on the requested metrics.
                    ratio_columns = [
                        "Face Value", "EPS", "Book Value per Share", "PBT Margin",
                        "P/E (Annual)", "P/B", "ROE", "ROCE", "ROA",
                    ]

                    def _latest_close(frame):
                        if frame is None or getattr(frame, "empty", True):
                            return None
                        close_col = next((c for c in ("Close", "close", "CLOSE", "Adj Close") if c in frame.columns), None)
                        if close_col is None:
                            return None
                        values = pd.to_numeric(frame[close_col], errors="coerce").dropna()
                        return float(values.iloc[-1]) if not values.empty else None

                    for index, peer in enumerate(symbols, start=1):
                        company_label = f"{company_names.get(peer, peer)} ({peer})"
                        row = {"Company": company_label, "Share Price": None}
                        peer_prices = None
                        peer_price = None

                        # Fetch market price independently; do not silently discard
                        # provider errors because that made every price appear as N/A.
                        try:
                            peer_prices, _ = fetch_stock_data(peer, period="1y")
                            peer_price = _latest_close(peer_prices)
                            if peer_price is None:
                                peer_errors.append(f"{peer}: market feed returned no usable closing price.")
                        except Exception as exc:
                            peer_errors.append(f"{peer}: market price lookup failed ({type(exc).__name__}: {exc}).")

                        # For the currently loaded company, reuse the chart dataframe
                        # if the separate peer lookup did not return a close.
                        if peer_price is None and peer == ticker_loaded:
                            try:
                                peer_price = _latest_close(df)
                                if peer_price is not None:
                                    peer_prices = df
                            except Exception:
                                pass
                        row["Share Price"] = peer_price

                        try:
                            peer_data = get_fundamental_data(
                                peer, api_key, market_price=peer_price, price_history=peer_prices
                            )
                            ratios = peer_data.get("top_ratios") or {}
                            for column in ratio_columns:
                                row[column] = ratios.get(column)
                            if not ratios:
                                peer_errors.append(f"{peer}: BharatStock returned financial statements but no calculated ratios.")
                        except (BharatStockDailyBudgetError, BharatStockRateLimitError) as exc:
                            peer_errors.append(f"{peer}: {exc}")
                            for column in ratio_columns:
                                row[column] = None
                            rows.append(row)
                            if isinstance(exc, BharatStockDailyBudgetError):
                                remaining = {"Company": "Remaining peers", "Share Price": None}
                                remaining.update({column: None for column in ratio_columns})
                                rows.append(remaining)
                                break
                        except Exception as exc:
                            peer_errors.append(f"{peer}: financial data lookup/calculation failed ({type(exc).__name__}: {exc}).")
                            for column in ratio_columns:
                                row[column] = None
                        rows.append(row)
                        progress.progress(index / len(symbols))

                    if peer_errors:
                        with st.expander("Peer data diagnostics", expanded=True):
                            for message in peer_errors:
                                st.warning(message)
                    peer_frame = pd.DataFrame(rows)
                    # Share Price follows Company. Display units explicitly so
                    # percentages and valuation multiples cannot be confused.
                    currency_columns = ["Share Price", "Face Value", "EPS", "Book Value per Share"]
                    percentage_columns = ["PBT Margin", "ROE", "ROCE", "ROA"]
                    multiple_columns = ["P/E (Annual)", "P/B"]
                    for column in currency_columns:
                        if column in peer_frame.columns:
                            peer_frame[column] = peer_frame[column].apply(
                                lambda value: f"₹{float(value):,.2f}" if pd.notna(value) else "N/A"
                            )
                    for column in percentage_columns:
                        if column in peer_frame.columns:
                            peer_frame[column] = peer_frame[column].apply(
                                lambda value: f"{float(value):.2f}%" if pd.notna(value) else "N/A"
                            )
                    for column in multiple_columns:
                        if column in peer_frame.columns:
                            peer_frame[column] = peer_frame[column].apply(
                                lambda value: f"{float(value):.2f}x" if pd.notna(value) else "N/A"
                            )
                    preferred_columns = ["Company", "Share Price"] + ratio_columns
                    peer_frame = peer_frame.reindex(columns=preferred_columns)
                    st.session_state[f"peers_{ticker_loaded}"] = peer_frame
            peer_frame = st.session_state.get(f"peers_{ticker_loaded}")
            if peer_frame is not None:
                st.dataframe(peer_frame, use_container_width=True, hide_index=True)

        with reports:
            st.subheader("Reports & Exports")
            st.download_button(
                "Download CSV",
                df.to_csv(index=True).encode("utf-8"),
                file_name=f"{ticker_loaded}_SmartStock.csv",
                mime="text/csv",
                key=f"download_csv_{ticker_loaded}",
            )
            try:
                excel_buffer = BytesIO()
                with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                    df.to_excel(writer, sheet_name="Price History")
                    pd.DataFrame([
                        {"Metric": key, "Value": value} for key, value in risk.items()
                    ]).to_excel(writer, sheet_name="Risk", index=False)
                    pd.DataFrame([
                        {"Indicator": key, "Score": value}
                        for key, value in result["IndicatorScores"].items()
                    ]).to_excel(writer, sheet_name="Technical Score", index=False)
                    if fdata:
                        pd.DataFrame(
                            list((fdata.get("top_ratios", {}) or {}).items()),
                            columns=["Ratio", "Value"],
                        ).to_excel(writer, sheet_name="Fundamentals", index=False)
                        for sheet, key in (("Profit & Loss", "profit_and_loss"),
                                           ("Balance Sheet", "balance_sheet"),
                                           ("Cash Flow", "cash_flow")):
                            statement_frame = rows_to_frame(fdata.get(key, []))
                            if not statement_frame.empty:
                                excel_frame = statement_excel_frame(statement_frame)
                                excel_frame.to_excel(writer, sheet_name=sheet, index=False)
                                worksheet = writer.sheets[sheet]
                                for col_idx, header_cell in enumerate(worksheet[1], start=1):
                                    header = str(header_cell.value or "")
                                    if "(₹ Cr.)" in header:
                                        for row_idx in range(2, worksheet.max_row + 1):
                                            worksheet.cell(row=row_idx, column=col_idx).number_format = '"₹ "#,##0.00" Cr."'
                                    elif "(₹/share)" in header:
                                        for row_idx in range(2, worksheet.max_row + 1):
                                            worksheet.cell(row=row_idx, column=col_idx).number_format = '"₹ "#,##0.00'
                    peer_frame = st.session_state.get(f"peers_{ticker_loaded}")
                    if peer_frame is not None:
                        peer_frame.to_excel(writer, sheet_name="Peer Comparison", index=False)
                st.download_button(
                    "Download Excel Report",
                    excel_buffer.getvalue(),
                    file_name=f"{ticker_loaded}_SmartStock.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_excel_{ticker_loaded}",
                )
            except Exception as exc:
                st.warning(f"Excel export unavailable: {exc}")

            try:
                from xml.sax.saxutils import escape
                from reportlab.lib import colors
                from reportlab.lib.pagesizes import A4, landscape
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib.units import mm
                from reportlab.platypus import (
                    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                    PageBreak, KeepTogether,
                )

                pdf_buffer = BytesIO()
                document = SimpleDocTemplate(
                    pdf_buffer, pagesize=landscape(A4),
                    rightMargin=12 * mm, leftMargin=12 * mm,
                    topMargin=12 * mm, bottomMargin=12 * mm,
                )
                styles = getSampleStyleSheet()
                small = ParagraphStyle("SmallCell", parent=styles["BodyText"], fontSize=7, leading=8)
                story = [
                    Paragraph(f"SmartStocks AI — {escape(str(ticker_loaded))} Report", styles["Title"]),
                    Paragraph(
                        f"Generated {pd.Timestamp.now().strftime('%d %b %Y, %I:%M %p')} · "
                        f"Price history: {escape(str(loaded_period))}", styles["Normal"]
                    ),
                    Spacer(1, 8),
                    Paragraph("Market Snapshot", styles["Heading2"]),
                ]
                snapshot = [
                    ["Current Price", "Latest Volume", "Period High", "Period Low", "Signal", "Score"],
                    [f"₹{current_price:,.2f}",
                     format_large_number(df["Volume"].iloc[-1]) if "Volume" in df.columns else "N/A",
                     f"₹{df['High'].max():,.2f}" if "High" in df.columns else "N/A",
                     f"₹{df['Low'].min():,.2f}" if "Low" in df.columns else "N/A",
                     str(result["Signal"]), f"{result['Score']}/10"],
                ]
                story.append(Table(snapshot, repeatRows=1, hAlign="LEFT", style=TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF3")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("PADDING", (0, 0), (-1, -1), 5),
                ])))
                story += [Spacer(1, 8), Paragraph("Technical Signal", styles["Heading2"])]
                story.append(Paragraph(escape(str(result.get("Method", ""))), small))
                story.append(Paragraph("Reasons: " + escape("; ".join(result.get("Reasons", []))), small))
                score_rows = [["Indicator", "Points"]] + [
                    [escape(str(k)), str(v)] for k, v in result.get("IndicatorScores", {}).items()
                ]
                story.append(Table(score_rows, repeatRows=1, style=TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF3")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ])))

                story += [Spacer(1, 8), Paragraph("Performance & Risk", styles["Heading2"])]
                returns = performance_returns(df)
                perf_rows = [["Period", "Return"]] + [
                    [period, f"{value:+.2f}%" if value is not None else "N/A"]
                    for period, value in returns.items()
                ]
                risk_rows = [["Risk Metric", "Value"],
                    ["Annualized Volatility", f"{risk['annualized_volatility']:.2f}%" if risk["annualized_volatility"] is not None else "N/A"],
                    ["Maximum Drawdown", f"{risk['maximum_drawdown']:.2f}%" if risk["maximum_drawdown"] is not None else "N/A"]]
                story.append(Table(perf_rows, repeatRows=1, style=TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF3")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8)
                ])))
                story.append(Spacer(1, 5))
                story.append(Table(risk_rows, repeatRows=1, style=TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF3")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8)
                ])))

                if fdata:
                    story += [Spacer(1, 10), Paragraph("Key Ratios & Valuation", styles["Heading2"])]
                    pdf_percent_metrics = {
                        "Revenue Growth", "Net Profit Margin", "Operating Margin", "EBITDA Margin",
                        "PBT Margin", "ROA", "ROE", "ROCE", "Dividend Yield",
                        "Cash Flow Margin", "EPS Growth", "Earnings Yield",
                    }
                    pdf_currency_metrics = {"Current Price", "52-Week High", "52-Week Low", "Book Value per Share", "EPS", "Face Value", "Dividend per Share"}
                    pdf_multiple_metrics = {
                        "P/E (Annual)", "P/B", "Debt-to-Equity", "Current Ratio", "Asset Turnover",
                        "Interest Coverage", "Operating Cash Flow / Net Profit", "Price-to-Sales",
                    }
                    pdf_crore_metrics = {"Market Cap (Estimated)"}
                    ratio_rows = [["Metric", "Value"]]
                    for k, v in (fdata.get("top_ratios", {}) or {}).items():
                        if isinstance(v, (int, float)):
                            shown_value = f"{v:,.2f}%" if k in pdf_percent_metrics else (
                                f"₹{v:,.2f} Cr." if k in pdf_crore_metrics else (
                                    f"₹{v:,.2f}" if k in pdf_currency_metrics else (
                                        f"{v:,.2f}x" if k in pdf_multiple_metrics else f"{v:,.2f}"
                                    )
                                )
                            )
                        else:
                            shown_value = escape(str(v))
                        ratio_rows.append([escape(str(k)), shown_value])
                    story.append(Table(ratio_rows, repeatRows=1, colWidths=[75 * mm, 35 * mm], style=TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF3")),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                        ("FONTSIZE", (0, 0), (-1, -1), 8), ("PADDING", (0, 0), (-1, -1), 4),
                    ])))
                    notes = fdata.get("ratio_calculation_notes", {}) or {}
                    if notes:
                        story += [Spacer(1, 5), Paragraph("Ratio calculation methodology", styles["Heading3"])]
                        note_rows = [["Metric", "SmartStocks formula / basis"]] + [
                            [escape(str(metric)), Paragraph(escape(str(method)), small)]
                            for metric, method in notes.items()
                        ]
                        story.append(Table(note_rows, repeatRows=1, colWidths=[48 * mm, 205 * mm], style=TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF3")),
                            ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
                            ("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("PADDING", (0, 0), (-1, -1), 4),
                        ])))
                    input_values = fdata.get("ratio_input_values", {}) or {}
                    if input_values:
                        story += [Spacer(1, 5), Paragraph("Key calculation inputs", styles["Heading3"])]
                        input_rows = [["Input", "Value"]]
                        for input_name, input_value in input_values.items():
                            if input_value is None:
                                display_input = "N/A"
                            elif isinstance(input_value, (int, float)):
                                display_input = f"{input_value:,.4f}"
                            else:
                                display_input = str(input_value)
                            input_rows.append([escape(str(input_name).replace("_", " ").title()), escape(display_input)])
                        story.append(Table(input_rows, repeatRows=1, colWidths=[75 * mm, 45 * mm], style=TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF3")),
                            ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
                            ("FONTSIZE", (0, 0), (-1, -1), 7), ("PADDING", (0, 0), (-1, -1), 3),
                        ])))
                    for title, key in (("Profit & Loss — Annual", "profit_and_loss"),
                                       ("Balance Sheet — Annual", "balance_sheet"),
                                       ("Cash Flow — Annual", "cash_flow")):
                        frame = rows_to_frame(fdata.get(key, []))
                        if frame.empty:
                            continue
                        story += [Spacer(1, 10), Paragraph(title + " (monetary values shown as ₹ Cr.; per-share figures retain ₹/share)", styles["Heading2"])]
                        # Keep the PDF readable by limiting very wide statements to key columns.
                        preferred = [c for c in [
                            "fiscal_year", "revenue", "total_income", "operating_profit", "ebitda",
                            "profit_before_tax", "net_profit", "net_profit_attributable_to_owners", "eps",
                            "total_assets", "total_equity", "equity_attributable_to_owners_of_parent",
                            "non_controlling_interests", "paid_up_equity_capital", "face_value",
                            "total_liabilities", "current_assets", "current_liabilities",
                            "cash_flow_operating", "cash_flow_investing", "cash_flow_financing", "capex",
                        ] if c in frame.columns]
                        view = frame[preferred] if preferred else frame.iloc[:, :8]
                        data = [[Paragraph(escape(str(c).replace("_", " ").title()), small) for c in view.columns]]
                        for _, record in view.iterrows():
                            line = []
                            for value in record.tolist():
                                if pd.isna(value):
                                    line.append("—")
                                elif isinstance(value, (int, float)):
                                    non_monetary = {"eps", "diluted_eps", "basic_eps", "earnings_per_share", "face_value_per_share", "face_value", "dividend_per_share", "dividend_per_share_amount", "annual_dividend_per_share", "pe_ratio", "pb_ratio", "debt_equity_ratio", "debt_to_equity_ratio", "interest_service_coverage_ratio", "interest_coverage_ratio", "debt_service_coverage_ratio", "dscr"}
                                    line.append(f"{value:,.2f}" if str(view.columns[len(line)]).lower() in non_monetary else f"₹ {value:,.2f} Cr.")
                                else:
                                    line.append(Paragraph(escape(str(value)), small))
                            data.append(line)
                        widths = [max(24 * mm, 255 * mm / max(1, len(view.columns)))] * len(view.columns)
                        story.append(Table(data, repeatRows=1, colWidths=widths, style=TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF3")),
                            ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
                            ("FONTSIZE", (0, 0), (-1, -1), 6),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("PADDING", (0, 0), (-1, -1), 3),
                        ])))

                story += [Spacer(1, 10), Paragraph(
                    "Data note: BharatStock supplies annual financial statement inputs only. SmartStocks calculates all displayed ratios locally; no BharatStock valuation/ratios endpoint is used. "
                    "Market price and 52-week range use the latest available TejHQ historical closing prices. Price-sensitive valuation ratios are recalculated when market data is refreshed; this is not an intraday quote. "
                    "Market cap and book value per share depend on estimated shares from paid-up capital and face value. "
                    "Ratios requiring unavailable inputs are omitted rather than inferred. This report is for educational "
                    "purposes and is not investment advice.", small
                )]
                document.build(story)
                st.download_button(
                    "Download Complete PDF Report", pdf_buffer.getvalue(),
                    file_name=f"{ticker_loaded}_SmartStocks_Report.pdf",
                    mime="application/pdf", key=f"download_pdf_{ticker_loaded}",
                )
            except Exception as exc:
                st.warning(f"PDF export unavailable: {exc}")
else:
    st.info("Search for an NSE stock and click Fetch Data to open the analysis dashboard.")

st.divider()
st.caption("SmartStocks AI • Phase 2 • Educational purposes only. Not investment advice.")
