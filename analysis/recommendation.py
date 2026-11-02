"""Transparent rule-based technical recommendation engine."""
import pandas as pd


def calculate_volume(df):
    df = df.copy()
    df["Volume_MA20"] = df["Volume"].rolling(window=20, min_periods=1).mean()
    return df


def generate_recommendation(df):
    work = df.copy()
    if "Volume_MA20" not in work.columns:
        work = calculate_volume(work)
    required = ["Close", "Open", "Volume", "RSI", "MACD", "Signal", "MA50",
                "Lower", "Upper", "ADX", "+DI", "-DI", "Volume_MA20"]
    missing = [column for column in required if column not in work.columns]
    if missing:
        raise ValueError("Insufficient indicator data: " + ", ".join(missing))
    valid = work.dropna(subset=required)
    if valid.empty:
        raise ValueError("Not enough price history to calculate a reliable technical signal.")
    latest = valid.iloc[-1]

    scores = {}
    reasons = []

    # Each indicator has an explicit bounded contribution; total range is -10 to +10.
    rsi_score = 2 if latest["RSI"] < 30 else (-2 if latest["RSI"] > 70 else 0)
    scores["RSI"] = rsi_score
    if rsi_score: reasons.append("RSI suggests an oversold condition" if rsi_score > 0 else "RSI suggests an overbought condition")

    macd_score = 2 if latest["MACD"] > latest["Signal"] else (-2 if latest["MACD"] < latest["Signal"] else 0)
    scores["MACD"] = macd_score
    if macd_score: reasons.append("MACD is above its signal line" if macd_score > 0 else "MACD is below its signal line")

    ma_score = 2 if latest["Close"] > latest["MA50"] else (-2 if latest["Close"] < latest["MA50"] else 0)
    scores["MA50"] = ma_score
    if ma_score: reasons.append("Price is above the 50-day moving average" if ma_score > 0 else "Price is below the 50-day moving average")

    bb_score = 2 if latest["Close"] < latest["Lower"] else (-2 if latest["Close"] > latest["Upper"] else 0)
    scores["Bollinger"] = bb_score
    if bb_score: reasons.append("Price is below the lower Bollinger Band" if bb_score > 0 else "Price is above the upper Bollinger Band")

    volume_score = 0
    if latest["Volume"] > latest["Volume_MA20"]:
        volume_score = 1 if latest["Close"] > latest["Open"] else (-1 if latest["Close"] < latest["Open"] else 0)
    scores["Volume"] = volume_score
    if volume_score: reasons.append("Above-average volume supports today's bullish move" if volume_score > 0 else "Above-average volume supports today's bearish move")

    adx_score = 0
    if latest["ADX"] > 25:
        adx_score = 1 if latest["+DI"] > latest["-DI"] else (-1 if latest["-DI"] > latest["+DI"] else 0)
    scores["ADX"] = adx_score
    if adx_score: reasons.append("ADX confirms a strong bullish trend" if adx_score > 0 else "ADX confirms a strong bearish trend")

    total = int(sum(scores.values()))
    signal = "BUY" if total >= 3 else ("SELL" if total <= -3 else "HOLD")
    confidence = round(abs(total) / 10 * 100, 1)
    if not reasons:
        reasons.append("Indicators are mixed or neutral; no strong directional setup is present.")

    return {"Signal": signal, "Score": total, "Confidence": confidence,
            "Reasons": reasons, "IndicatorScores": scores,
            "ScoreRange": "-10 to +10", "Method": "Six rule-based indicators; weighted contributions shown below."}
