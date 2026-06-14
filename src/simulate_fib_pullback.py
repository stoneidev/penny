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
    return df.between_time('09:30', '16:00')

def simulate_fib_pullback(df, min_runup_pct=0.20, fib_low=0.786, fib_high=0.50, vol_dry_mult=0.20, target_pct=0.03, stop_pct=0.015):
    """
    Fibonacci Retracement Pullback / ABCD Strategy:
    1. Detect swing low A and swing high B (run-up of at least min_runup_pct)
    2. Monitor pullback into the Fibonacci zone: B - fib_low * (B - A) to B - fib_high * (B - A)
    3. Check volume dry-up: 1m volume is < vol_dry_mult times the peak volume of the A-B run-up
    4. Enter on green reversal candle (Close > Open)
    5. Exit on target_pct, stop_pct, or at EOD
    """
    trades = []
    in_position = False
    entry_price = 0
    entry_time = None
    
    # State tracking
    swing_low_a = None
    swing_high_b = None
    max_vol_runup = 0
    runup_detected = False
    
    for i in range(1, len(df)):
        current_time = df.index[i]
        row = df.iloc[i]
        
        if not in_position:
            # 1. Swing Detection
            # We look for a minimum runup_pct from the daily low
            rolling_low = df.iloc[:i+1]['Low'].min()
            rolling_high = df.iloc[:i+1]['High'].max()
            
            # Check if runup condition met
            runup_pct = (rolling_high - rolling_low) / rolling_low
            if runup_pct >= min_runup_pct:
                if not runup_detected or rolling_high > (swing_high_b or 0):
                    # Reset or update swing points
                    swing_low_a = rolling_low
                    swing_high_b = rolling_high
                    
                    # Find maximum volume during this run-up phase
                    runup_df = df.iloc[:i+1]
                    runup_df = runup_df[runup_df['High'] <= swing_high_b]
                    max_vol_runup = runup_df['Volume'].max()
                    
                    runup_detected = True
            
            # 2. Check for Pullback Setup
            if runup_detected and swing_low_a and swing_high_b:
                swing_range = swing_high_b - swing_low_a
                
                # Compute Fibonacci levels
                price_fib_high = swing_high_b - fib_high * swing_range
                price_fib_low = swing_high_b - fib_low * swing_range
                
                # Condition: Price is inside the Fib Zone
                in_fib_zone = price_fib_low <= row['Low'] <= price_fib_high or price_fib_low <= row['Close'] <= price_fib_high
                
                # Condition: Volume dry-up (current volume is less than vol_dry_mult of the peak run-up volume)
                vol_dried = row['Volume'] < vol_dry_mult * max_vol_runup if max_vol_runup > 0 else False
                
                # Condition: Green confirmation candle
                is_green = row['Close'] > row['Open']
                
                if in_fib_zone and vol_dried and is_green:
                    entry_price = row['Close']
                    entry_time = current_time
                    in_position = True
                    # Reset runup detection so we don't double entry immediately
                    runup_detected = False
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

# Parameter grid
# min_runup = 20% or 30%
# fib_zones = (0.786, 0.50) [Golden Pocket/Base zone]
# vol_dry = 0.20 (20% of peak), 0.30 (30% of peak)
# target/stop combinations
configs = [
    # (min_runup, fib_low, fib_high, vol_dry, PT, SL)
    (0.20, 0.786, 0.50, 0.20, 0.02, 0.015),
    (0.20, 0.786, 0.50, 0.20, 0.03, 0.015),
    (0.20, 0.786, 0.50, 0.20, 0.03, 0.02),
    (0.20, 0.786, 0.50, 0.30, 0.03, 0.015),
    (0.30, 0.786, 0.50, 0.20, 0.03, 0.015),
    (0.30, 0.786, 0.50, 0.20, 0.05, 0.02),
    (0.30, 0.786, 0.50, 0.30, 0.05, 0.02),
    (0.20, 0.618, 0.382, 0.20, 0.02, 0.015), # Shallowed pullback (38.2% - 61.8%)
    (0.20, 0.618, 0.382, 0.20, 0.03, 0.015),
]

results = []
for runup, f_low, f_high, vol_dry, pt, sl in configs:
    all_trades = []
    for (ticker, date_str), df in data_dict.items():
        trades = simulate_fib_pullback(df, runup, f_low, f_high, vol_dry, pt, sl)
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
            "Runup": f"{runup*100:.0f}%",
            "Fib Zone": f"{f_high*100:.1f}%-{f_low*100:.1f}%",
            "Vol Dry": f"<{vol_dry*100:.0f}%",
            "PT / SL": f"PT={pt*100:.1f}%, SL={sl*100:.1f}%",
            "Trades": len(all_trades),
            "Win Rate": f"{win_rate*100:.1f}%",
            "Avg Return": f"{avg_ret*100:.2f}%",
            "Profit Factor": f"{pf:.2f}" if pf != float('inf') else "INF",
            "Raw_Avg": avg_ret
        })

res_df = pd.DataFrame(results)
res_df = res_df.sort_values(by="Raw_Avg", ascending=False)

print("\n=== FIBONACCI RETRACEMENT PULLBACK SIMULATION ===")
print(res_df.drop(columns=["Raw_Avg"]).to_string(index=False))
print("==================================================")

# Generate Markdown file
markdown_content = "# 📐 피보나치 되돌림 눌림목(ABCD) 백테스트 시뮬레이션 결과\n\n"
markdown_content += "거래량이 급감하며 피보나치 지지선(Golden Pocket)까지 하락한 덤프 구간에서 반등을 포착해 진입하는 전략 시뮬레이션 결과입니다.\n\n"
markdown_content += "## 📈 시뮬레이션 결과 목록\n\n"
markdown_content += "| 상승폭 조건 | 피보나치 존 | 거래량 감소 필터 | 익절/손절 | 거래 횟수 | 승률 | 평균 수익률 | 손익비 |\n"
markdown_content += "| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"

for idx, row in res_df.iterrows():
    markdown_content += f"| {row['Runup']} | {row['Fib Zone']} | {row['Vol Dry']} | {row['PT / SL']} | {row['Trades']} | {row['Win Rate']} | {row['Avg Return']} | {row['Profit Factor']} |\n"

output_path = str(Path(__file__).resolve().parent.parent / "results" / "fib_pullback_results.md")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(markdown_content)
print(f"Saved results to {output_path}")
