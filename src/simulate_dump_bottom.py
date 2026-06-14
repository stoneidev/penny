from pathlib import Path
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
    df = df.between_time('09:30', '16:00')
    
    # Pre-calculate Indicators
    df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['Daily_High'] = df['High'].cummax()
    
    return df

# ==========================================
# 📊 STRATEGY SIMULATIONS
# ==========================================

def simulate_pure_drop(df, drop_pct, target_pct, stop_pct):
    """
    Strategy A: Pure Drop Target
    - Buy as soon as price drops by drop_pct from the daily high
    """
    trades = []
    in_position = False
    entry_price = 0
    entry_time = None
    
    for i in range(1, len(df)):
        current_time = df.index[i]
        row = df.iloc[i]
        
        if not in_position:
            high_so_far = row['Daily_High']
            current_drop = (high_so_far - row['Low']) / high_so_far
            
            # Entry condition
            if current_drop >= drop_pct:
                # Enter at the drop target price
                entry_price = high_so_far * (1 - drop_pct)
                # Ensure entry price is realistic (within candle range)
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
                trades.append({"return": -stop_pct, "type": "SL"})
                in_position = False
            elif row['High'] >= target_price:
                trades.append({"return": target_pct, "type": "PT"})
                in_position = False
            elif i == len(df) - 1 or current_time.hour == 15 and current_time.minute == 59:
                ret = (row['Close'] - entry_price) / entry_price
                trades.append({"return": ret, "type": "EOD"})
                in_position = False
                break
    return trades

def simulate_drop_consolidation(df, drop_pct, target_pct, stop_pct, window=10, max_range=0.02):
    """
    Strategy B: Drop + Consolidation
    - Price has dropped by at least drop_pct from the daily high
    - Over the last 'window' minutes, the high/low range is less than max_range (consolidating)
    - Buy on the breakout of the consolidation high
    """
def simulate_drop_consolidation(df, drop_pct, target_pct, stop_pct, window=5, max_range=0.05):
    """
    Strategy B: Drop + Consolidation
    - Price has dropped by at least drop_pct from the daily high
    - Over the last 'window' minutes, the high/low range is less than max_range (consolidating)
    - Buy on the breakout of the consolidation high
    """
    trades = []
    in_position = False
    entry_price = 0
    entry_time = None
    
    drop_triggered = False
    
    for i in range(1, len(df)):
        current_time = df.index[i]
        row = df.iloc[i]
        
        if not in_position:
            high_so_far = row['Daily_High']
            current_drop = (high_so_far - row['Low']) / high_so_far
            
            if current_drop >= drop_pct:
                drop_triggered = True
                
            if drop_triggered:
                if i >= window:
                    recent_bars = df.iloc[i-window:i]
                    recent_high = recent_bars['High'].max()
                    recent_low = recent_bars['Low'].min()
                    recent_range = (recent_high - recent_low) / recent_low
                    
                    if recent_range <= max_range:
                        # Enter immediately on consolidation close
                        entry_price = row['Close']
                        entry_time = current_time
                        in_position = True
                        drop_triggered = False  # Reset trigger for next trade
        else:
            # Position management
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
            
            if row['Low'] <= stop_price:
                trades.append({"return": -stop_pct, "type": "SL"})
                in_position = False
            elif row['High'] >= target_price:
                trades.append({"return": target_pct, "type": "PT"})
                in_position = False
            elif i == len(df) - 1 or current_time.hour == 15 and current_time.minute == 59:
                ret = (row['Close'] - entry_price) / entry_price
                trades.append({"return": ret, "type": "EOD"})
                in_position = False
                break
    return trades

def simulate_drop_ema_cross(df, drop_pct, target_pct, stop_pct):
    """
    Strategy C: Drop + EMA9 Crossover
    - Price has dropped by at least drop_pct from the daily high
    - Price has been trading below EMA9
    - Buy when the current minute close crosses above the EMA9
    """
    trades = []
    in_position = False
    entry_price = 0
    entry_time = None
    
    for i in range(5, len(df)):
        current_time = df.index[i]
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        
        if not in_position:
            high_so_far = row['Daily_High']
            current_drop = (high_so_far - row['Low']) / high_so_far
            
            if current_drop >= drop_pct:
                # Check EMA crossover: previous close was below EMA9, current close is above EMA9
                was_below = prev_row['Close'] < prev_row['EMA9']
                is_above = row['Close'] > row['EMA9']
                
                if was_below and is_above:
                    entry_price = row['Close']
                    entry_time = current_time
                    in_position = True
        else:
            # Position management
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
            
            if row['Low'] <= stop_price:
                trades.append({"return": -stop_pct, "type": "SL"})
                in_position = False
            elif row['High'] >= target_price:
                trades.append({"return": target_pct, "type": "PT"})
                in_position = False
            elif i == len(df) - 1 or current_time.hour == 15 and current_time.minute == 59:
                ret = (row['Close'] - entry_price) / entry_price
                trades.append({"return": ret, "type": "EOD"})
                in_position = False
                break
    return trades


print("Loading data...")
data_dict = {}
for ticker, date_str in ticker_dates:
    df = load_data(ticker, date_str)
    if df is not None:
        data_dict[(ticker, date_str)] = df

# Parameter Grids
drops = [0.40, 0.50, 0.60] # 40%, 50%, 60% drop from high
targets = [0.015, 0.02, 0.03] # PT = 1.5%, 2%, 3%
stops = [0.01, 0.015, 0.02]   # SL = 1%, 1.5%, 2%

results = []

# 1. Pure Drop Backtest
for d in drops:
    for pt in targets:
        for sl in stops:
            all_trades = []
            for (ticker, date_str), df in data_dict.items():
                trades = simulate_pure_drop(df, d, pt, sl)
                all_trades.extend(trades)
            if all_trades:
                returns = [t['return'] for t in all_trades]
                wins = [1 for t in all_trades if t['return'] > 0]
                win_rate = len(wins) / len(all_trades)
                avg_ret = np.mean(returns)
                g = sum([t['return'] for t in all_trades if t['return'] > 0])
                l = sum([-t['return'] for t in all_trades if t['return'] < 0])
                pf = g / l if l > 0 else float('inf')
                
                results.append({
                    "Strategy": "A: Pure Drop",
                    "Params": f"Drop={d*100:.0f}%, PT={pt*100:.1f}%, SL={sl*100:.1f}%",
                    "Trades": len(all_trades),
                    "Win Rate": f"{win_rate*100:.1f}%",
                    "Avg Return": f"{avg_ret*100:.2f}%",
                    "Profit Factor": f"{pf:.2f}" if pf != float('inf') else "INF",
                    "Raw_Avg": avg_ret
                })

# 2. Consolidation Breakout Backtest
for d in drops:
    for pt in targets:
        for sl in stops:
            all_trades = []
            for (ticker, date_str), df in data_dict.items():
                trades = simulate_drop_consolidation(df, d, pt, sl, window=5, max_range=0.05)
                all_trades.extend(trades)
            if all_trades:
                returns = [t['return'] for t in all_trades]
                wins = [1 for t in all_trades if t['return'] > 0]
                win_rate = len(wins) / len(all_trades)
                avg_ret = np.mean(returns)
                g = sum([t['return'] for t in all_trades if t['return'] > 0])
                l = sum([-t['return'] for t in all_trades if t['return'] < 0])
                pf = g / l if l > 0 else float('inf')
                
                results.append({
                    "Strategy": "B: Drop + Consolidation",
                    "Params": f"Drop={d*100:.0f}%, PT={pt*100:.1f}%, SL={sl*100:.1f}%",
                    "Trades": len(all_trades),
                    "Win Rate": f"{win_rate*100:.1f}%",
                    "Avg Return": f"{avg_ret*100:.2f}%",
                    "Profit Factor": f"{pf:.2f}" if pf != float('inf') else "INF",
                    "Raw_Avg": avg_ret
                })

# 3. EMA Cross Backtest
for d in drops:
    for pt in targets:
        for sl in stops:
            all_trades = []
            for (ticker, date_str), df in data_dict.items():
                trades = simulate_drop_ema_cross(df, d, pt, sl)
                all_trades.extend(trades)
            if all_trades:
                returns = [t['return'] for t in all_trades]
                wins = [1 for t in all_trades if t['return'] > 0]
                win_rate = len(wins) / len(all_trades)
                avg_ret = np.mean(returns)
                g = sum([t['return'] for t in all_trades if t['return'] > 0])
                l = sum([-t['return'] for t in all_trades if t['return'] < 0])
                pf = g / l if l > 0 else float('inf')
                
                results.append({
                    "Strategy": "C: Drop + EMA9 Cross",
                    "Params": f"Drop={d*100:.0f}%, PT={pt*100:.1f}%, SL={sl*100:.1f}%",
                    "Trades": len(all_trades),
                    "Win Rate": f"{win_rate*100:.1f}%",
                    "Avg Return": f"{avg_ret*100:.2f}%",
                    "Profit Factor": f"{pf:.2f}" if pf != float('inf') else "INF",
                    "Raw_Avg": avg_ret
                })

res_df = pd.DataFrame(results)
res_df = res_df.sort_values(by="Raw_Avg", ascending=False)

# Print top 20 in terminal
print("\n=== DEFLATED DUMP BOTTOM SIMULATION ===")
print(res_df.drop(columns=["Raw_Avg"]).head(20).to_string(index=False))
print("========================================")

# Generate Markdown file
markdown_content = "# 📉 덤프(Dump) 지점 공략 백테스트 시뮬레이션 결과\n\n"
markdown_content += "거품이 빠진 덤프 지점에서 매수한 후 당일 청산하는 단타 전략의 시뮬레이션 전체 결과입니다.\n\n"
markdown_content += "## 📈 전체 시뮬레이션 결과 목록\n\n"
markdown_content += "| 전략명 | 파라미터 | 거래 횟수 | 승률 | 평균 수익률 | 손익비 |\n"
markdown_content += "| :--- | :--- | :---: | :---: | :---: | :---: |\n"

for idx, row in res_df.iterrows():
    markdown_content += f"| {row['Strategy']} | {row['Params']} | {row['Trades']} | {row['Win Rate']} | {row['Avg Return']} | {row['Profit Factor']} |\n"

output_path = str(Path(__file__).resolve().parent.parent / "results" / "dump_bottom_results.md")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(markdown_content)
print(f"Saved complete results to {output_path}")
