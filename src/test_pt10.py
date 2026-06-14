import os
import json
import glob
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta

# Paths
cache_dir = Path(os.environ.get("PRICE_CACHE_DIR", "/Users/stoni/Downloads/pennysniper_validation/price_cache"))
minute_cache_dir = Path(os.environ.get("MINUTE_CACHE_DIR", "/Users/stoni/Downloads/pennysniper_validation/polygon_minute_cache"))
selections_path = str(Path(__file__).resolve().parent.parent / "data" / "daily_selections.json")

with open(selections_path, "r") as f:
    daily_selections = json.load(f)

# Load daily data for fallback and checking
csv_files = glob.glob(os.path.join(cache_dir, "*.csv"))
tickers = [os.path.splitext(os.path.basename(f))[0] for f in csv_files]
start_date = "2026-04-28"
end_date = "2026-06-13"
daily_data = yf.download(tickers, start=start_date, end=end_date, interval="1d", group_by="ticker", progress=False)

def load_minute_from_json(ticker, date_str):
    f = minute_cache_dir / f"{ticker}_{date_str}.json"
    if not f.exists():
        return None
    with open(f) as fp:
        d = json.load(fp)
    if not d.get("results"):
        return None
    df = pd.DataFrame(d["results"])
    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    df = df.sort_values("timestamp").reset_index(drop=True)
    rth = df[
        (df["timestamp"].dt.time >= pd.Timestamp("09:30").time())
        & (df["timestamp"].dt.time < pd.Timestamp("16:00").time())
    ].reset_index(drop=True)
    return rth if len(rth) > 0 else None

cached_series = {}
sorted_days = sorted(list(daily_selections.keys()))

for date_str in sorted_days:
    selections = daily_selections[date_str]
    if len(selections) < 2:
        continue
    ticker, gap, op, pc = selections[1]  # 2nd stock (index 1)
    current_date = pd.Timestamp(date_str)
    
    df_1m = load_minute_from_json(ticker, date_str)
    if df_1m is None:
        days_ago = (datetime(2026, 6, 14) - datetime.strptime(date_str, "%Y-%m-%d")).days
        if days_ago <= 28:
            start_dt = datetime.strptime(date_str, "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=1)
            try:
                df_1m = yf.download(ticker, start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="1m", progress=False)
                if not df_1m.empty:
                    if isinstance(df_1m.columns, pd.MultiIndex):
                        df_1m.columns = [col[0] for col in df_1m.columns]
                    if df_1m.index.tz is None:
                        df_1m.index = df_1m.index.tz_localize('UTC').tz_convert('US/Eastern')
                    else:
                        df_1m.index = df_1m.index.tz_convert('US/Eastern')
                    df_1m = df_1m.between_time('09:30', '16:00')
                else:
                    df_1m = None
            except Exception:
                df_1m = None
                
    daily_info = None
    try:
        ticker_df = daily_data[ticker]
        day_row = ticker_df.loc[current_date]
        daily_info = {
            "Open": float(day_row['Open']),
            "High": float(day_row['High']),
            "Low": float(day_row['Low']),
            "Close": float(day_row['Close'])
        }
    except Exception:
        daily_info = {"Open": op, "High": op, "Low": op, "Close": op}
        
    cached_series[(ticker, date_str)] = {
        "df_1m": df_1m,
        "daily_info": daily_info
    }

# Run simulation for PT = 10%, SL = 20%
pt_val = 0.10
sl_val = 0.20
gap_limit = 2.00

returns = []
trade_count = 0
win_count = 0

for date_str in sorted_days:
    selections = daily_selections[date_str]
    if len(selections) < 2:
        continue
    ticker, gap, op, pc = selections[1]
    
    if gap >= gap_limit:
        continue
        
    cache = cached_series[(ticker, date_str)]
    df_1m = cache["df_1m"]
    daily_info = cache["daily_info"]
    
    trade_count += 1
    
    if df_1m is not None and len(df_1m) > 0:
        entry_price = float(df_1m.iloc[0]['Open'])
        initial_stop = entry_price * (1 - sl_val)
        target_price = entry_price * (1 + pt_val)
        
        exit_price = None
        exit_type = None
        
        # Setup time stop limit (10:00 AM)
        start_time = df_1m.iloc[0]['timestamp'] if 'timestamp' in df_1m.columns else df_1m.index[0]
        start_time = pd.to_datetime(start_time)
        time_limit = start_time.replace(hour=10, minute=0, second=0)
        
        for i in range(len(df_1m)):
            row = df_1m.iloc[i]
            current_time = df_1m.iloc[i]['timestamp'] if 'timestamp' in df_1m.columns else df_1m.index[i]
            current_time = pd.to_datetime(current_time)
            
            if current_time > time_limit:
                exit_price = float(row['Open'])
                exit_type = "TIME"
                break
                
            low_val = float(row['Low'])
            high_val = float(row['High'])
            
            if low_val <= initial_stop and high_val >= target_price:
                exit_price = initial_stop
                exit_type = "SL"
                break
            elif low_val <= initial_stop:
                exit_price = initial_stop
                exit_type = "SL"
                break
            elif high_val >= target_price:
                exit_price = target_price
                exit_type = "PT"
                break
                
        if exit_price is None:
            exit_price = float(df_1m.iloc[-1]['Close'])
            exit_type = "EOD"
            
        ret = (exit_price - entry_price) / entry_price
        
    else:
        # Fallback to daily
        entry_price = daily_info['Open']
        high_val = daily_info['High']
        low_val = daily_info['Low']
        close_val = daily_info['Close']
        initial_stop = entry_price * (1 - sl_val)
        target_price = entry_price * (1 + pt_val)
        
        if low_val <= initial_stop:
            exit_price = initial_stop
            exit_type = "SL"
        elif high_val >= target_price:
            exit_price = target_price
            exit_type = "PT"
        else:
            exit_price = close_val
            exit_type = "EOD"
        ret = (exit_price - entry_price) / entry_price
        
    returns.append(ret)
    if ret > 0:
        win_count += 1

# Compounding capital
cap_all_in = 100.0
cap_half = 100.0
cap_history_all_in = [100.0]
cap_history_half = [100.0]

for r in returns:
    cap_all_in *= (1 + r)
    cap_half *= (1 + 0.5 * r)
    cap_history_all_in.append(cap_all_in)
    cap_history_half.append(cap_half)

win_rate = (win_count / trade_count) * 100 if trade_count > 0 else 0.0

# MDD
mdd_all_in = 0.0
peak_all_in = 100.0
for v in cap_history_all_in:
    peak_all_in = max(peak_all_in, v)
    dd = (peak_all_in - v) / peak_all_in
    mdd_all_in = max(mdd_all_in, dd)

mdd_half = 0.0
peak_half = 100.0
for v in cap_history_half:
    peak_half = max(peak_half, v)
    dd = (peak_half - v) / peak_half
    mdd_half = max(mdd_half, dd)

print(f"RESULTS FOR PT = +10% / SL = -20%:")
print(f"Total Trades: {trade_count}")
print(f"Win Rate: {win_rate:.2f}%")
print(f"All-in Final Capital: {cap_all_in:.2f}원 ({cap_all_in-100:+.2f}%)")
print(f"50% Bet Final Capital: {cap_half:.2f}원 ({cap_half-100:+.2f}%)")
print(f"All-in MDD: {mdd_all_in*100:.2f}%")
print(f"50% Bet MDD: {mdd_half*100:.2f}%")
print(f"Average Return per Trade: {np.mean(returns)*100:+.2f}%")
