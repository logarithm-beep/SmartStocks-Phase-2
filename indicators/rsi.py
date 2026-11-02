
def calculate_rsi(df,period=14):
    change = df['Close'].diff()
    gain = change.clip(lower=0)
    loss = -change.clip(upper=0)
    average_gain = gain.rolling(window=period).mean()
    average_loss = loss.rolling(window=period).mean()
    rs = average_gain/average_loss
    df['RSI'] = 100 - (100/(1+rs))
    return df
