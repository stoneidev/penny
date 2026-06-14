import os
import glob
import json
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

# 1. Load ticker list from the price_cache folder
cache_dir = os.environ.get("PRICE_CACHE_DIR", "/Users/stoni/Downloads/pennysniper_validation/price_cache")
csv_files = glob.glob(os.path.join(cache_dir, "*.csv"))
tickers = [os.path.splitext(os.path.basename(f))[0] for f in csv_files]
print(f"Loaded {len(tickers)} tickers from price cache.")

# 2. Download daily historical data for the period
start_date = "2026-04-28"  # Buffer to calculate previous close for 2026-05-01
end_date = "2026-06-13"

print("Downloading daily data for all tickers...")
# Download daily data in a single batch
daily_data = yf.download(tickers, start=start_date, end=end_date, interval="1d", group_by="ticker", progress=False)

# 3. Process daily data to compute daily gap-ups and select top 3
trading_days = []
# Find all unique trading days starting from 2026-05-01
# We can check dates from daily_data index
temp_df = daily_data[tickers[0]]
dates_after_may1 = temp_df.index[temp_df.index >= "2026-05-01"]
dates_after_may1 = [d.strftime("%Y-%m-%d") for d in dates_after_may1]
print(f"Trading days after 2026-05-01: {dates_after_may1}")

daily_selections = {}

for date_str in dates_after_may1:
    day_gaps = []
    current_date = pd.Timestamp(date_str)
    
    for ticker in tickers:
        try:
            ticker_df = daily_data[ticker]
            if ticker_df.empty or date_str not in ticker_df.index.strftime("%Y-%m-%d"):
                continue
            
            # Find the row for today
            today_row = ticker_df.loc[current_date]
            
            # Find the row for yesterday (previous trading day)
            earlier_rows = ticker_df[ticker_df.index < current_date]
            if earlier_rows.empty:
                continue
            prev_row = earlier_rows.iloc[-1]
            
            open_price = today_row['Open']
            prev_close = prev_row['Close']
            volume = today_row['Volume']
            
            # Basic validation
            if pd.isna(open_price) or pd.isna(prev_close) or open_price <= 0 or prev_close <= 0:
                continue
                
            # Filter: open price between $1.00 and $10.00 (penny stock range)
            if not (1.0 <= open_price <= 10.0):
                continue
                
            # Liquidity filter: previous day dollar volume > $50,000 to avoid illiquid wicks
            prev_dollar_vol = prev_row['Close'] * prev_row['Volume']
            if prev_dollar_vol < 50000:
                continue
                
            gap_pct = (open_price - prev_close) / prev_close
            day_gaps.append((ticker, gap_pct, open_price, prev_close))
        except Exception as e:
            continue
            
    # Sort by gap percentage descending
    day_gaps = sorted(day_gaps, key=lambda x: x[1], reverse=True)
    
    # Take top 3
    top_3 = day_gaps[:3]
    if top_3:
        daily_selections[date_str] = top_3
        print(f"[{date_str}] Top 3 Selected:")
        for idx, (t, gap, op, pc) in enumerate(top_3):
            print(f"  {idx+1}. {t}: Gap {gap*100:+.2f}% (Open: {op:.4f}, Prev Close: {pc:.4f})")

# Save selections to JSON for verification
with open("daily_selections.json", "w") as f:
    json.dump(daily_selections, f, indent=4)
print("Saved daily selections.")
