import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

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
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    df = yf.download(ticker, start=start_str, end=end_str, interval="1m", progress=False)
    if df.empty:
        return None
    
    # Flatten MultiIndex if exists
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
        
    df = df.copy()
    
    # Ensure Index is Datetime and local timezone is US/Eastern
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC').tz_convert('US/Eastern')
    else:
        df.index = df.index.tz_convert('US/Eastern')
        
    # Filter for regular market hours (9:30 AM to 4:00 PM EST)
    df = df.between_time('09:30', '16:00')
    
    # Compute Typical Price and cumulative VWAP
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    df['VWAP'] = (tp * df['Volume']).cumsum() / df['Volume'].cumsum()
    
    return df

def simulate_orb(df, target_pct, stop_pct, range_minutes=5):
    """
    Opening Range Breakout Strategy:
    - Determine high/low of first range_minutes (9:30 - 9:35)
    - Buy if price crosses above high (9:35 - 11:30)
    - Exit on target_pct, stop_pct, or at 15:59 (Time Stop)
    """
    if len(df) < range_minutes:
        return []
    
    # Opening range (9:30 to 9:35)
    open_range = df.iloc[:range_minutes]
    orb_high = open_range['High'].max()
    orb_low = open_range['Low'].min()
    
    trades = []
    in_position = False
    entry_price = 0
    entry_time = None
    
    # We look for entry between 9:35 AM and 11:30 AM
    entry_end_time = df.index[0].replace(hour=11, minute=30)
    
    for i in range(range_minutes, len(df)):
        current_time = df.index[i]
        row = df.iloc[i]
        
        if not in_position:
            # Check for entry (must be before 11:30 AM)
            if current_time <= entry_end_time and row['High'] > orb_high:
                entry_price = orb_high + 0.01 # Buy stop order at high + 1 cent
                # Make sure entry price is within the candle range
                if entry_price < row['Low']:
                    entry_price = row['Open']
                elif entry_price > row['High']:
                    entry_price = row['Close']
                entry_time = current_time
                in_position = True
        else:
            # We are in position. Check exit conditions
            # Check Stop Loss first (worst case)
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
            
            if row['Low'] <= stop_price:
                # Stopped out
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
                # Target hit
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
                # End of day time stop
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

def simulate_climax(df, drop_pct, vol_mult, target_pct, stop_pct):
    """
    Panic Climax Bounce Strategy:
    - Drop from daily high is at least drop_pct
    - 1m Volume is vol_mult times the average of the last 15 mins
    - Buy at close of that candle
    - Exit on target_pct, stop_pct, or at EOD
    """
    trades = []
    in_position = False
    entry_price = 0
    entry_time = None
    
    # Calculate rolling daily high
    rolling_high = df['High'].cummax()
    # Calculate rolling 15m average volume
    rolling_avg_vol = df['Volume'].rolling(window=15).mean()
    
    for i in range(15, len(df)):
        current_time = df.index[i]
        row = df.iloc[i]
        
        if not in_position:
            # Condition 1: Drop from high
            high_price = rolling_high.iloc[i]
            current_drop = (high_price - row['Low']) / high_price
            
            # Condition 2: Volume spike
            avg_vol = rolling_avg_vol.iloc[i-1]
            vol_ratio = row['Volume'] / avg_vol if avg_vol > 0 else 0
            
            # We only buy during active morning hours (9:35 to 11:30 AM) when volume is high
            is_active_hours = current_time.hour == 9 and current_time.minute >= 35 or current_time.hour == 10 or (current_time.hour == 11 and current_time.minute <= 30)
            
            if is_active_hours and current_drop >= drop_pct and vol_ratio >= vol_mult:
                entry_price = row['Close']
                entry_time = current_time
                in_position = True
        else:
            # We are in position. Check exit conditions
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

def simulate_vwap(df, target_pct, stop_pct):
    """
    VWAP Pullback Bounce Strategy:
    - Price has been trading above VWAP
    - Pulls back to VWAP (Low touches/crosses below VWAP, but Close is above VWAP)
    - Next candle closes green (Close > Open)
    - Buy at Close of green candle
    - Exit on target_pct, stop_pct, or at EOD
    """
    trades = []
    in_position = False
    entry_price = 0
    entry_time = None
    
    # We need a state variable to track if pullback occurred
    pullback_ready = False
    
    for i in range(1, len(df)):
        current_time = df.index[i]
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        
        if not in_position:
            # Check for pullback setup:
            # 1. Previously price was comfortably above VWAP
            # 2. Current or previous candle Low touches/goes below VWAP, but Close is above VWAP
            was_above = prev_row['Close'] > prev_row['VWAP']
            touches_vwap = row['Low'] <= row['VWAP'] * 1.005 and row['Close'] > row['VWAP']
            
            if was_above and touches_vwap:
                pullback_ready = True
                continue
                
            # If setup was ready, check if this is a green confirmation candle
            if pullback_ready:
                is_green = row['Close'] > row['Open']
                is_above_vwap = row['Close'] > row['VWAP']
                
                # Active hours check (9:45 AM to 11:30 AM)
                is_active = (current_time.hour == 9 and current_time.minute >= 45) or current_time.hour == 10 or (current_time.hour == 11 and current_time.minute <= 30)
                
                if is_green and is_above_vwap and is_active:
                    entry_price = row['Close']
                    entry_time = current_time
                    in_position = True
                    pullback_ready = False
                else:
                    # Pullback setup expires if next candle is not green or slips too far below VWAP
                    if row['Close'] < row['VWAP'] * 0.99:
                        pullback_ready = False
        else:
            # In position
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

print("Downloading data for simulation...")
data_dict = {}
for ticker, date_str in ticker_dates:
    df = load_data(ticker, date_str)
    if df is not None:
        data_dict[(ticker, date_str)] = df
print(f"Data loaded successfully for {len(data_dict)} instances.")

# Parameter grids to search
orb_params = [
    # (target, stop)
    (0.02, 0.02), (0.03, 0.02), (0.05, 0.03), (0.05, 0.02), (0.08, 0.03), (0.10, 0.05)
]

climax_params = [
    # (drop, vol_mult, target, stop)
    (0.15, 2.0, 0.02, 0.02),
    (0.20, 2.0, 0.03, 0.02),
    (0.20, 3.0, 0.03, 0.02),
    (0.25, 3.0, 0.03, 0.02),
    (0.25, 3.0, 0.05, 0.03),
    (0.30, 3.0, 0.05, 0.03),
]

vwap_params = [
    # (target, stop)
    (0.02, 0.02), (0.03, 0.02), (0.05, 0.03), (0.05, 0.02)
]

results = []

# 1. ORB Simulation
for pt, sl in orb_params:
    all_trades = []
    for (ticker, date_str), df in data_dict.items():
        trades = simulate_orb(df, pt, sl)
        all_trades.extend(trades)
        
    if all_trades:
        returns = [t['return'] for t in all_trades]
        wins = [1 for t in all_trades if t['return'] > 0]
        losses = [1 for t in all_trades if t['return'] < 0]
        win_rate = len(wins) / len(all_trades) if all_trades else 0
        avg_ret = np.mean(returns)
        
        gains = sum([t['return'] for t in all_trades if t['return'] > 0])
        total_losses = sum([-t['return'] for t in all_trades if t['return'] < 0])
        profit_factor = gains / total_losses if total_losses > 0 else float('inf')
        
        results.append({
            "Strategy": "ORB",
            "Parameters": f"PT={pt*100:.1f}%, SL={sl*100:.1f}%",
            "Trades": len(all_trades),
            "Win Rate": f"{win_rate*100:.1f}%",
            "Avg Return": f"{avg_ret*100:.2f}%",
            "Profit Factor": f"{profit_factor:.2f}" if profit_factor != float('inf') else "INF",
            "Raw_Win_Rate": win_rate,
            "Raw_Avg_Ret": avg_ret
        })

# 2. Climax Simulation
for drop, vol, pt, sl in climax_params:
    all_trades = []
    for (ticker, date_str), df in data_dict.items():
        trades = simulate_climax(df, drop, vol, pt, sl)
        all_trades.extend(trades)
        
    if all_trades:
        returns = [t['return'] for t in all_trades]
        wins = [1 for t in all_trades if t['return'] > 0]
        win_rate = len(wins) / len(all_trades) if all_trades else 0
        avg_ret = np.mean(returns)
        
        gains = sum([t['return'] for t in all_trades if t['return'] > 0])
        total_losses = sum([-t['return'] for t in all_trades if t['return'] < 0])
        profit_factor = gains / total_losses if total_losses > 0 else float('inf')
        
        results.append({
            "Strategy": "Panic Climax",
            "Parameters": f"Drop={drop*100:.0f}%, Vol={vol}x, PT={pt*100:.1f}%, SL={sl*100:.1f}%",
            "Trades": len(all_trades),
            "Win Rate": f"{win_rate*100:.1f}%",
            "Avg Return": f"{avg_ret*100:.2f}%",
            "Profit Factor": f"{profit_factor:.2f}" if profit_factor != float('inf') else "INF",
            "Raw_Win_Rate": win_rate,
            "Raw_Avg_Ret": avg_ret
        })

# 3. VWAP Pullback Simulation
for pt, sl in vwap_params:
    all_trades = []
    for (ticker, date_str), df in data_dict.items():
        trades = simulate_vwap(df, pt, sl)
        all_trades.extend(trades)
        
    if all_trades:
        returns = [t['return'] for t in all_trades]
        wins = [1 for t in all_trades if t['return'] > 0]
        win_rate = len(wins) / len(all_trades) if all_trades else 0
        avg_ret = np.mean(returns)
        
        gains = sum([t['return'] for t in all_trades if t['return'] > 0])
        total_losses = sum([-t['return'] for t in all_trades if t['return'] < 0])
        profit_factor = gains / total_losses if total_losses > 0 else float('inf')
        
        results.append({
            "Strategy": "VWAP Pullback",
            "Parameters": f"PT={pt*100:.1f}%, SL={sl*100:.1f}%",
            "Trades": len(all_trades),
            "Win Rate": f"{win_rate*100:.1f}%",
            "Avg Return": f"{avg_ret*100:.2f}%",
            "Profit Factor": f"{profit_factor:.2f}" if profit_factor != float('inf') else "INF",
            "Raw_Win_Rate": win_rate,
            "Raw_Avg_Ret": avg_ret
        })

# Print Results in formatted table
res_df = pd.DataFrame(results)
res_df = res_df.sort_values(by="Raw_Avg_Ret", ascending=False).drop(columns=["Raw_Win_Rate", "Raw_Avg_Ret"])
print("\n=== BACKTEST SIMULATION RESULTS ===")
print(res_df.to_string(index=False))
print("====================================")
