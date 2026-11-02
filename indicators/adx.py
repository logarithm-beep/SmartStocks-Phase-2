import numpy as np

def calculate_adx(df):
    up_move = df["High"].diff()
    down_move = -df["Low"].diff()
    df["+DM"] = np.where(
        (up_move>down_move) & (up_move>0),
        up_move,
        0
    )
    df["-DM"] = np.where(
        (down_move > up_move) & (down_move > 0),
        down_move,
        0
    )

    tr1 = df["High"] - df["Low"]
    tr2 = abs(df["High"] - df["Close"].shift(1))
    tr3 = abs(df["Low"] - df["Close"].shift(1))

    df["TR"] = np.maximum(
        tr1,
        np.maximum(tr2, tr3)
    )
    df["+DI"] = (df["+DM"].rolling(window=14).mean()/df["TR"].rolling(window=14).mean())*100
    df["-DI"] = (df["-DM"].rolling(window=14).mean()/df["TR"].rolling(window=14).mean())*100

    df["DX"] = (abs(df["+DI"] - df["-DI"]) / (df["+DI"] + df["-DI"])) * 100

    df["ADX"] = df["DX"].rolling(window=14).mean()
    return df