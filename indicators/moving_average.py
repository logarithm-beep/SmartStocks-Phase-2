import streamlit as st
import pandas as pd
import plotly.graph_objects as go

def calculate_ma(df,period):

    df[f"MA{period}"] = df["Close"].rolling(window=period).mean()
    return df


