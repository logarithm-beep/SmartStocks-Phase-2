import requests
import pandas as pd
from datetime import datetime, timedelta


def fetch_stock_data(ticker, period):
    today = datetime.today()

    if period == "6mo":
        start_date = today - timedelta(days=180)

    elif period == "1y":
        start_date = today - timedelta(days=365)

    elif period == "5y":
        start_date = today - timedelta(days=1825)

    elif period == "max":
        start_date = datetime(2010, 1, 1)

    else:
        raise ValueError("Invalid period selected.")


    from_date = start_date.strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    
    print("Period: ", period)
    print("From date: ", from_date)
    print("To date: ", to_date)

    url = (
        f"https://api.tejhq.dev/v1/ohlcv/nse/"
        f"{ticker}?from={from_date}&to={to_date}"
    )
    print("URL:", url)

    response = requests.get(url, timeout=20)

    if response.status_code != 200:
        print("Status code:", response.status_code)
        print("URL:", url)
        print("Response:", response.text)
        raise ValueError("Unable to fetch stock data.")

    try:
        payload = response.json()
        data = payload.get("data", [])
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid price-data response for {ticker}.") from exc

    if not data:
        raise ValueError(
            f"No historical data found for {ticker}. The stock may be newly listed "
            "or not yet available from the NSE price-data provider."
        )

    df = pd.DataFrame(data)
    if "date" not in df.columns or "close" not in df.columns:
        raise ValueError(f"Price-data response for {ticker} is missing date/close fields.")

    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume"
    })

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")

    return df, ticker