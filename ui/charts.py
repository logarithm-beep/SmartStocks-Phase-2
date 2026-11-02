import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np


def plot_price_chart(df,ticker,show_ma20,show_ma50,show_ma100,show_bollinger,show_adx):
      fig = make_subplots(
          rows = 5,
          cols = 1,
          shared_xaxes= True,
          vertical_spacing= 0.05,
          row_heights=[0.55,0.15,0.15,0.12,0.08]
    )

      fig.add_trace(
        go.Candlestick(
            x = df.index,
            open = df["Open"],
            close = df["Close"],
            high = df["High"],
            low = df["Low"],
            name = "Candlestick"
        ),
        row = 1,
        col = 1
    )
      if show_ma20:
         fig.add_trace(
            go.Scatter(
                    x = df.index,
                    y = df["MA20"],
                    mode = "lines",
                    name = "Moving average 20"
                ),
                row = 1,
                col = 1
        )

      if show_ma50:
            fig.add_trace(
                go.Scatter(
                        x = df.index,
                        y = df["MA50"],
                        mode = "lines",
                        name = "Moving average 50"
                    ),
                    row = 1,
                    col = 1
            )

      if show_ma100:
            fig.add_trace(
                go.Scatter(
                        x = df.index,
                        y = df["MA100"],
                        mode = "lines",
                        name = "Moving average 100"
                    ),
                    row = 1,
                    col = 1
            )

      if show_bollinger:
            fig.add_trace(
                go.Scatter(
                      x = df.index,
                      y = df["Upper"],
                      mode = "lines",
                      name = "Upper Bollinger Band"
                ),
                row = 1,
                col = 1
            )
            fig.add_trace(
                  go.Scatter(
                        x = df.index,
                        y = df["Lower"],
                        mode = "lines",
                        name = "Lower Bollinger Band"
                  ),
                  row = 1,
                  col = 1
            )
      if show_adx:
            fig.add_trace(
                  go.Scatter(
                        x = df.index,
                        y = df["+DI"],
                        mode = "lines",
                        name = "+DI"
                  ),
                  row = 5,
                  col = 1
            )
            fig.add_trace(
                  go.Scatter(
                        x = df.index,
                        y = df["-DI"],
                        mode = "lines",
                        name = "-DI"
                  ),
                  row = 5,
                  col = 1
            )
      colors_vol = np.where(
      df["Close"] >= df["Open"],
      "green",
      "red"
    )
      colors_macd = np.where(
          df["Histogram"]>=0,
          "green",
          "red"
      )
      fig.add_trace(
          go.Bar(
                x = df.index,
                y = df["Volume"],
                name = "Volume",
                marker_color = colors_vol
          ),
          row = 2,
          col = 1
    )
    
      fig.add_trace(
          go.Scatter(
                x = df.index,
                y = df["RSI"],
                mode = "lines",
                name = "RSI"
          ),
          row = 3,
          col = 1
    )
      fig.add_trace(
          go.Scatter(
                x = df.index,
                y = df['MACD'],
                mode='lines',
                name = 'MACD',
                line=dict(color='cyan')
          ),
          row = 4,
          col = 1,                
    )
      fig.add_trace(
          go.Scatter(
                x = df.index,
                y = df['Signal'],
                mode = 'lines',
                name = 'Signal',
                line=dict(color='orange')
          ),
          row = 4,
          col = 1
    )
      fig.add_trace(
          go.Bar(
                x = df.index,
                y = df["Histogram"],
                name = "Histogram",
                marker_color = colors_macd
          ),
          row = 4,
          col = 1
    )
      fig.add_hline(
            y = 50,
            line_dash = 'dash',
            line_color = 'gray',
            line_width = 1,
            row = 3,
            col = 1  
        )
      fig.add_hline(
            y = 70,
            line_dash = 'dash',
            line_color = 'red',
            line_width = 2,
            row = 3,
            col = 1  
        )
      fig.add_hline(
        y = 30,
        line_dash = 'dash',
        line_color = 'lime',
        line_width = 2,
        row = 3,
        col = 1  
    )
      fig.add_hline(
        y = 0,
        line_dash = "dash",
        line_color = "gray",
        row = 4,
        col = 1
    )
      fig.add_hline(
            y = 25,
            line_dash = "dash",
            row = 5,
            col = 1
      )

      fig.update_layout(
        height = 900,
        xaxis_rangeslider_visible = False,
        title = f"{ticker} Stock Analysis",
        template="plotly_dark"
    )
      fig.update_yaxes(
          showgrid=False,
          title_text="Price",
          row=1,
          col=1
    )
      fig.update_yaxes(
            showgrid=False,
            title_text="Volume",
            row=2,
            col=1
        )
      fig.update_yaxes(
          title_text = "RSI",
          range = [0,100],
          tickvals = [0,30,50,70,100],
          row = 3,
          col = 1
    )
      fig.update_yaxes(
          title_text = "MACD",
          row = 4,
          col = 1
    )
      fig.update_yaxes(
            title_text = "ADX",
            row = 5,
            col = 1
    )
      fig.update_xaxes(
          title_text = "Date",
          row=4,
          col=1
    )
      

      return fig