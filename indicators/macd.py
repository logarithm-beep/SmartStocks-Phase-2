def calculate_macd(df):
    df["EMA12"] = df["Close"].ewm(span=12, adjust=False).mean()
    df["EMA26"] = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = df["EMA12"]-df["EMA26"]
    df["Signal"] = df["MACD"].ewm(span=9,adjust=False).mean()
    df["Histogram"] = df["MACD"] - df["Signal"]
    return df