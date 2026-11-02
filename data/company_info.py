"""Company information helpers without Yahoo Finance dependencies."""


def fetch_company_info(ticker, stocks_df=None, financial_data=None):
    """Build the company summary from the local stock master and BharatStock data.

    Sector and industry are left unavailable unless a future source supplies them;
    this function deliberately does not call Yahoo Finance.
    """
    name = ticker
    if stocks_df is not None and not stocks_df.empty:
        matches = stocks_df[stocks_df["SYMBOL"].astype(str).str.upper() == str(ticker).upper()]
        if not matches.empty:
            name = matches.iloc[0].get("NAME OF COMPANY", ticker)

    ratios = (financial_data or {}).get("top_ratios", {})
    return {
        "name": name,
        "sector": "N/A",
        "industry": "N/A",
        "market_cap": ratios.get("Market Cap", "N/A"),
        "pe_ratio": ratios.get("P/E", "N/A"),
        "dividend_yield": ratios.get("Dividend Yield", "N/A"),
        "current_price": ratios.get("Current Price", "N/A"),
    }
