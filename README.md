<<<<<<< HEAD
# SmartStocks-Phase-2
=======
# 📊 SmartStocks AI

SmartStocks AI is a Python-based stock analysis dashboard built with Streamlit.

It allows users to search for stocks, visualize historical price data from TejHQ, analyze technical indicators, evaluate historical performance, and understand basic risk metrics through an interactive dashboard.

## 🚀 Features

- 🔎 Stock search by ticker or company name
- 🇮🇳 Automatic NSE/BSE ticker resolution
- 🕯️ Interactive candlestick charts
- 📈 Moving Averages — MA20, MA50, MA100
- 📊 Volume analysis
- 📉 RSI
- 📈 MACD
- 📏 Bollinger Bands
- 📐 ADX with +DI and -DI
- 🤖 Rule-based technical trading signal
- 📊 Indicator score breakdown
- 💰 Historical performance — 1D, 1W, 1M, 6M, 1Y
- 📈 ₹10,000 normalized performance chart
- ⚠️ Annualized volatility
- 📉 Maximum drawdown
- 🏢 Basic company information

## 🛠️ Tech Stack

- Python
- Streamlit
- Pandas
- NumPy
- TejHQ market-data API (historical OHLCV)
- BharatStock API (fundamental financial data)
- Plotly

## 📁 Project Structure

```text
SmartStockAI/
│
├── app.py
├── requirements.txt
├── stocks.csv
│
├── data/
│   ├── fetch_data.py
│   └── company_info.py
│
├── indicators/
│   ├── moving_average.py
│   ├── rsi.py
│   ├── macd.py
│   ├── bollinger_band.py
│   └── adx.py
│
├── analysis/
│   └── recommendation.py
│
├── ui/
│   └── charts.py
│
└── utils/
    └── formatters.py

## Combined NSE + BSE Stock Master (Phase 2)

SmartStock now has an exchange-aware stock master.

- Use **🔄 Refresh NSE + BSE Stock List** in the sidebar to refresh the local `stocks.csv`.
- NSE equity symbols are sourced from the official NSE equity-segment CSV.
- BSE securities are sourced from the BSE equity scrip master ZIP.
- The combined file keeps the original columns and adds:
  - `EXCHANGE` (`NSE` or `BSE`)
  - `SECURITY_CODE` (BSE scrip code where available)
- Search supports symbol, company name, and BSE scrip code.
- The refresh writes a temporary file first and replaces `stocks.csv` only after a successful merge. If one exchange download fails, the previous records for that exchange are retained and the failure is shown in the sidebar.

**Important:** This change adds BSE discovery and exchange-aware selection. The existing historical OHLCV connector is still NSE-oriented. Selecting a BSE entry displays a clear message instead of sending its symbol to the NSE price endpoint. BSE historical-price integration is a separate follow-up.

Official source references:
- NSE: https://www.nseindia.com/static/market-data/securities-available-for-trading
- BSE scrip master format: https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=e99e2ca5-95d7-4173-83da-7774412bbb2d&id=20220531-44

## Phase 2 consolidated update

This build consolidates the requested Phase 2 work into one project folder.

### Stock universe
- Combined NSE + BSE stock-master refresh button in the sidebar.
- Exchange-aware search by symbol, company name and BSE scrip code.
- Existing NSE CSV columns retained, with `EXCHANGE` and `SECURITY_CODE` added.
- Failed exchange downloads do not intentionally replace the stock master with an empty response.
- BSE discovery is included; BSE historical price retrieval is not yet connected.

### Market analysis
- Removed yfinance from source code and requirements.
- Existing TejHQ NSE OHLCV connector retained, with request timeout and clearer empty-response validation.
- Newly listed/short-history securities no longer trigger a previous-close index error.
- Technical score uses six explicit contributions: RSI ±2, MACD ±2, MA50 ±2, Bollinger ±2, Volume ±1 and ADX ±1. Total range is -10 to +10; BUY at +3 or more, SELL at -3 or less, otherwise HOLD.
- Performance tab reports 1D, 1W, 1M, 6M and 1Y returns where sufficient history exists.
- Risk tab reports annualized volatility and maximum drawdown.

### Fundamental and reporting tabs
- Fundamental Analysis uses the configured BharatStock API key from `.env`; shows available ratios, annual P&L and balance-sheet data.
- Valuation tab surfaces available P/E, P/B, book value, ROE, ROCE, dividend yield, market cap and current price fields.
- Reports tab exports price/indicator CSV, Excel workbook and PDF summary.
- Added `openpyxl` and `reportlab` dependencies for exports.

### Configuration
Create a `.env` file in the project root:
`BHARATSTOCK_API_KEY=your_api_key_here`

Install dependencies:
`pip install -r requirements.txt`

Run:
`streamlit run app.py`

**Known integration limitation:** BSE stock discovery/search is enabled, but the historical OHLCV provider in this build remains NSE-specific. A BSE result is clearly identified and is not incorrectly sent to the NSE endpoint. BSE price history requires a separate provider integration.

## BharatStock fundamentals, valuation and reports

- SmartStock requests exactly **two annual periods** from BharatStock, matching the Free-plan history limit configured for this build. It displays only the periods actually returned; missing history is never invented.
- Each uncached company fetch uses **two API requests**: annual financial statements and current ratios. The 24-hour SQLite cache means a fresh repeat fetch uses zero API requests.
- The app displays available P/E, P/B, ROE, ROCE, dividend yield, current price and 52-week range, plus locally calculated margins, growth, leverage, liquidity, coverage, asset efficiency and cash-flow ratios when the required inputs are present.
- Debt-to-Equity is shown when supplied by BharatStock; otherwise it is calculated from borrowings and equity when both are available.
- Fundamentals include annual Profit & Loss, Balance Sheet and Cash Flow tables.
- Reports can be downloaded as CSV, Excel and a complete PDF report containing the market snapshot, technical signal, performance, risk, ratios/valuation and available annual statements.

Create a `.env` file in the project root:
`BHARATSTOCK_API_KEY=your_api_key_here`

Install dependencies:
`pip install -r requirements.txt`

Run:
`streamlit run app.py`

The local request safety limit is 55 requests per local calendar day. It only counts calls made by this SmartStock installation; the provider's quota and reset timezone remain authoritative. A cache refresh after 24 hours or a force refresh consumes provider requests. Never share your `.env` file or API key.

## Latest UI refinements

- The Fundamentals tab is now focused on the annual Profit & Loss, Balance Sheet and Cash Flow statements, each in its own expandable section.
- Annual statements request two periods. The interface and PDF describe this as a two-year history; unavailable periods are not fabricated.
- The Valuation tab contains the available market, valuation, profitability, leverage, liquidity, efficiency and cash-flow ratios in grouped sections. Percentage metrics retain the familiar `%` display.

### Ratio validation and calculation transparency
- Debt-to-Equity, Interest Coverage and Debt Service Coverage are kept as separate reported and calculated metrics when both are available; one never silently replaces the other.
- Debt-to-Equity is calculated as total borrowings divided by equity attributable to owners, when both inputs are available.
- Interest Coverage uses explicit EBIT and interest expense when supplied. If EBIT or interest expense is not separately available, operating profit and/or finance costs may be used as clearly labelled proxies.
- Debt Service Coverage is calculated only when cash available for debt service, principal repayments and interest expense are all present. Otherwise the calculated metric is omitted and the app explains which inputs are missing.
- Material differences between reported and calculated ratios are flagged in Valuation and in the PDF report. Check the fiscal year, standalone/consolidated basis and provider definitions before relying on either value.
- Missing inputs are not replaced with zero. Provider-reported values remain labelled as reported values.

## Ratio validation and statement units (latest update)

- Reported Debt-to-Equity, Interest Coverage and Debt Service Coverage values are retained in the audit details; they are not shown as headline figures unless independently supported by statement calculations.
- Calculated Debt-to-Equity and Interest Coverage are shown only when required inputs exist. DSCR is shown only when cash available for debt service, principal repayments and interest expense are all present. Missing calculations display as N/A.
- The Valuation tab includes a ratio validation table with status, calculated value and provider-reported audit value.
- BharatStock annual statement monetary fields are converted from INR to INR crore by dividing by 10,000,000. EPS and other per-share fields, market prices and ratio fields are not converted.
- Profit & Loss, Balance Sheet and Cash Flow tables, Excel exports and PDF reports use INR crore for monetary statement figures.
- Cache schema is versioned so older cached statement values are not reused after the unit conversion. Existing `.env` API key can be retained.

Note: The conversion follows the BharatStock payload's INR-denominated values observed in the supplied sample response. If the provider changes its units or adds an explicit unit indicator, the conversion should be revisited.

## Financial statement display units

- BharatStock annual monetary statement values are normalized to INR crore before calculations.
- Streamlit statement tables and PDF reports prefix monetary amounts with `₹ Cr.` so the unit is visible beside each figure.
- Excel statement sheets keep numeric values for sorting and formulas, label monetary columns `(₹ Cr.)`, and apply a visible `₹ Cr.` number format. Per-share fields such as EPS remain in rupees per share; ratio fields remain in their native units.
- The statement display formatter is presentation-only and does not convert the normalized values a second time.
>>>>>>> 217903b (Deploy phase 2)

## Fundamental ratio methodology (current build)

SmartStocks requests annual financial statements from BharatStock only. It does **not** call the BharatStock valuation/ratios endpoint and does not display provider-supplied P/E, P/B, ROE, ROCE or dividend-yield values. Ratios are calculated locally from the annual statement inputs plus the latest TejHQ closing price.

- P/E = latest TejHQ close / latest annual EPS.
- Book value per share = equity attributable to owners / estimated shares outstanding.
- P/B = latest TejHQ close / calculated book value per share.
- Market capitalisation = latest TejHQ close × estimated shares outstanding (₹ crore).
- ROE = annual net profit attributable to owners / average opening and closing equity.
- ROA = annual net profit / average opening and closing total assets.
- ROCE = EBIT (or operating profit when EBIT is not supplied) / closing capital employed (total assets less current liabilities).
- Dividend yield = annual dividend per share / latest TejHQ close; omitted when dividend-per-share input is unavailable.

Share count is estimated from paid-up equity capital / face value. Metrics requiring missing inputs are omitted. The 52-week high/low is shown only when the fetched price history covers approximately one year. The dashboard includes a statement refresh control to bypass the 24-hour local statement cache.

## Ratio methodology update (Phase 2 audit)

- Market Cap is labelled **Estimated** and uses the latest TejHQ close multiplied by shares estimated from paid-up/issued equity share capital divided by face value. Authorised capital is not used. Reconcile this estimate with the issuer's latest outstanding share count before relying on it.
- P/E is explicitly labelled **P/E (Annual)** and uses the latest full-year EPS. TTM P/E is not displayed because this integration currently requests annual statements only; it does not fabricate quarterly EPS.
- P/B uses parent-attributable consolidated equity, excluding non-controlling interests, divided by estimated ordinary shares. If parent equity cannot be isolated, P/B is unavailable.
- ROE uses profit attributable to owners divided by average parent equity.
- ROA uses consolidated profit for the period divided by average consolidated total assets.
- ROCE uses EBIT (or operating profit if EBIT is unavailable) divided by average capital employed. Capital employed is total assets less current liabilities for each of the two annual periods.
- EPS growth compares the same EPS field (diluted, EPS, basic, or earnings per share) across the two annual periods.
- The dashboard and PDF show the financial period and market-price date. The PDF includes key calculation inputs and methodology notes.

These formulas were tested with synthetic financial statement data. Live BharatStock field mapping and company-specific reported values still require verification against the provider response.

## Dynamic market valuation

- Fundamental analysis remains based on the latest completed annual financial statements.
- The Valuation tab recalculates price-sensitive metrics from the cached annual statements and the latest available TejHQ close on each rerun.
- Use **Refresh Market Data** to fetch a newer available closing price. This does not call BharatStock again.
- This is latest-available closing-price data, not an intraday/live quote. Market data availability depends on the TejHQ feed.
- Annual P/E remains annual EPS-based; TTM P/E is not shown until quarterly statements are integrated.
