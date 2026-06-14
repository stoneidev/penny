import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# List of tickers and dates to fetch
# Format: (ticker, date_str)
ticker_dates = [
    ("GLXG", "2026-06-11"),
    ("GELS", "2026-06-11"),
    ("TGHL", "2026-06-11"),
    ("AHMA", "2026-06-09"),
    ("SLGB", "2026-06-09"),
    ("COCH", "2026-06-09"),
    ("GMHS", "2026-06-09"),
    ("NOTV", "2026-06-05"),
    ("RMSG", "2026-06-05"),
    ("TGHL", "2026-06-01"),
    ("ABTS", "2026-06-01"),
    ("GNTA", "2026-06-01")
]

print("Starting download test...")
for ticker, date_str in ticker_dates:
    # yfinance download expects start and end date
    # Start: date_str, End: date_str + 1 day
    start_date = datetime.strptime(date_str, "%Y-%m-%d")
    end_date = start_date + timedelta(days=1)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    try:
        print(f"Downloading {ticker} for {date_str}...")
        df = yf.download(ticker, start=start_str, end=end_str, interval="1m")
        if df.empty:
            print(f"  --> [EMPTY] No data for {ticker} on {date_str}")
        else:
            print(f"  --> [SUCCESS] {len(df)} rows downloaded for {ticker}. Columns: {list(df.columns)}")
            print(f"      Price range: High={df['High'].max().values[0] if isinstance(df['High'].max(), pd.Series) else df['High'].max():.4f}, Low={df['Low'].min().values[0] if isinstance(df['Low'].min(), pd.Series) else df['Low'].min():.4f}")
    except Exception as e:
        print(f"  --> [ERROR] Failed to download {ticker}: {e}")
