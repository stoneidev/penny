import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# List of tickers and dates
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

def load_data(ticker, date_str):
    start_date = datetime.strptime(date_str, "%Y-%m-%d")
    end_date = start_date + timedelta(days=1)
    df = yf.download(ticker, start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"), interval="1m", progress=False)
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC').tz_convert('US/Eastern')
    else:
        df.index = df.index.tz_convert('US/Eastern')
    return df.between_time('09:30', '16:00')

def simulate_selective_orb(df, target_pct, stop_pct, min_vol_5m=500000, max_entry_time_minutes=30):
    """
    Selective ORB Strategy:
    - 5-min opening range (9:30 - 9:35)
    - Stricter Filters:
        1. Opening 5m volume must be > min_vol_5m (only trade high liquidity)
        2. Entry only between 9:35 AM and 10:00 AM (max_entry_time_minutes = 30 from 9:30)
    - Buy breakout of the 5m high
    - Exit on small targets (scalping) and tight stops
    """
    if len(df) < 5:
        return []
        
    open_range = df.iloc[:5]
    orb_high = open_range['High'].max()
    total_5m_volume = open_range['Volume'].sum()
    
    # Filter 1: Liquidity Filter
    if total_5m_volume < min_vol_5m:
        return []
        
    trades = []
    in_position = False
    entry_price = 0
    entry_time = None
    
    # Filter 2: Entry Time window (9:35 AM to 10:00 AM)
    entry_end_time = df.index[0].replace(hour=10, minute=0)
    
    for i in range(5, len(df)):
        current_time = df.index[i]
        row = df.iloc[i]
        
        if not in_position:
            # Check for entry
            if current_time <= entry_end_time and row['High'] > orb_high:
                entry_price = orb_high + 0.01
                if entry_price < row['Low']:
                    entry_price = row['Open']
                elif entry_price > row['High']:
                    entry_price = row['Close']
                entry_time = current_time
                in_position = True
        else:
            # Position management
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
            
            if row['Low'] <= stop_price:
                trades.append({
                    "entry_time": entry_time,
                    "entry_price": entry_price,
                    "exit_time": current_time,
                    "exit_price": stop_price,
                    "return": -stop_pct,
                    "type": "SL"
                })
                in_position = False
            elif row['High'] >= target_price:
                trades.append({
                    "entry_time": entry_time,
                    "entry_price": entry_price,
                    "exit_time": current_time,
                    "exit_price": target_price,
                    "return": target_pct,
                    "type": "PT"
                })
                in_position = False
            elif i == len(df) - 1 or current_time.hour == 15 and current_time.minute == 59:
                exit_price = row['Close']
                ret = (exit_price - entry_price) / entry_price
                trades.append({
                    "entry_time": entry_time,
                    "entry_price": entry_price,
                    "exit_time": current_time,
                    "exit_price": exit_price,
                    "return": ret,
                    "type": "EOD"
                })
                in_position = False
                break
                
    return trades

print("Loading data...")
data_dict = {}
for ticker, date_str in ticker_dates:
    df = load_data(ticker, date_str)
    if df is not None:
        data_dict[(ticker, date_str)] = df

# Test combinations of smaller targets, tight stops, and strict volume filters
configurations = [
    # (PT, SL, min_vol_5m)
    (0.015, 0.010, 500000),  # PT=1.5%, SL=1.0%, Vol=500k
    (0.020, 0.010, 500000),  # PT=2.0%, SL=1.0%, Vol=500k
    (0.020, 0.015, 500000),  # PT=2.0%, SL=1.5%, Vol=500k
    (0.030, 0.015, 500000),  # PT=3.0%, SL=1.5%, Vol=500k
    (0.015, 0.010, 1000000), # PT=1.5%, SL=1.0%, Vol=1M (Super selective)
    (0.020, 0.010, 1000000), # PT=2.0%, SL=1.0%, Vol=1M
    (0.020, 0.015, 1000000), # PT=2.0%, SL=1.5%, Vol=1M
    (0.030, 0.015, 1000000), # PT=3.0%, SL=1.5%, Vol=1M
    (0.020, 0.020, 1000000), # PT=2.0%, SL=2.0%, Vol=1M
]

results = []
for pt, sl, min_vol in configurations:
    all_trades = []
    for (ticker, date_str), df in data_dict.items():
        trades = simulate_selective_orb(df, pt, sl, min_vol_5m=min_vol)
        all_trades.extend(trades)
        
    if all_trades:
        returns = [t['return'] for t in all_trades]
        wins = [1 for t in all_trades if t['return'] > 0]
        win_rate = len(wins) / len(all_trades)
        avg_ret = np.mean(returns)
        
        gains = sum([t['return'] for t in all_trades if t['return'] > 0])
        losses = sum([-t['return'] for t in all_trades if t['return'] < 0])
        profit_factor = gains / losses if losses > 0 else float('inf')
        
        results.append({
            "Volume Filter": f">{min_vol/1000:.0f}K",
            "PT / SL": f"PT={pt*100:.1f}%, SL={sl*100:.1f}%",
            "Total Trades": len(all_trades),
            "Win Rate": f"{win_rate*100:.1f}%",
            "Avg Return": f"{avg_ret*100:.2f}%",
            "Profit Factor": f"{profit_factor:.2f}" if profit_factor != float('inf') else "INF",
            "Raw_Avg_Ret": avg_ret
        })

res_df = pd.DataFrame(results)
res_df = res_df.sort_values(by="Raw_Avg_Ret", ascending=False).drop(columns=["Raw_Avg_Ret"])
print("\n=== SELECTIVE SCALPING RESULTS ===")
print(res_df.to_string(index=False))
print("==================================")
