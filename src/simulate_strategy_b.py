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
    df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    df['VWAP'] = (tp * df['Volume']).cumsum() / df['Volume'].cumsum()
    df['Daily_High'] = df['High'].cummax()
    
    return df

def simulate_strategy_b(df, min_runup_pct=0.20, vol_dry_mult=0.30, target_pct=0.03, stop_pct=0.015):
    """
    Strategy B: The 1st Dip Reversion
    - Pullback to 38.2% - 50.0% Fibonacci retracement of the swing.
    - Volume dries up during pullback (< vol_dry_mult of peak runup volume).
    - VWAP or EMA10 support test (Low touches or comes close to VWAP/EMA10, Close is above).
    - Candle is a Doji, has a long lower shadow (밑꼬리), or closes green.
    """
    trades = []
    in_position = False
    entry_price = 0
    entry_time = None
    
    # Swing tracking
    swing_low_a = None
    swing_high_b = None
    max_vol_runup = 0
    runup_detected = False
    
    for i in range(1, len(df)):
        current_time = df.index[i]
        row = df.iloc[i]
        
        if not in_position:
            # 1. Swing Detection
            rolling_low = df.iloc[:i+1]['Low'].min()
            rolling_high = df.iloc[:i+1]['High'].max()
            
            runup_pct = (rolling_high - rolling_low) / rolling_low
            if runup_pct >= min_runup_pct:
                if not runup_detected or rolling_high > (swing_high_b or 0):
                    swing_low_a = rolling_low
                    swing_high_b = rolling_high
                    
                    # Peak volume during run-up
                    runup_df = df.iloc[:i+1]
                    runup_df = runup_df[runup_df['High'] <= swing_high_b]
                    max_vol_runup = runup_df['Volume'].max()
                    
                    runup_detected = True
            
            # 2. Check Strategy B criteria
            if runup_detected and swing_low_a and swing_high_b:
                swing_range = swing_high_b - swing_low_a
                
                # Fibonacci zone (38.2% to 50.0% retracement)
                fib_382 = swing_high_b - 0.382 * swing_range
                fib_500 = swing_high_b - 0.500 * swing_range
                
                # Check price is in zone
                in_fib_zone = fib_500 <= row['Low'] <= fib_382 or fib_500 <= row['Close'] <= fib_382
                
                # Check volume dry-up
                vol_dried = row['Volume'] < vol_dry_mult * max_vol_runup if max_vol_runup > 0 else False
                
                # Check VWAP or EMA10 touch/support (within 0.5% threshold)
                touches_vwap = row['Low'] <= row['VWAP'] * 1.005 and row['Close'] >= row['VWAP'] * 0.995
                touches_ema10 = row['Low'] <= row['EMA10'] * 1.005 and row['Close'] >= row['EMA10'] * 0.995
                touches_support = touches_vwap or touches_ema10
                
                # Check candle pattern (Doji, Lower Shadow, or Green rebound)
                body = abs(row['Close'] - row['Open'])
                candle_range = row['High'] - row['Low']
                is_doji = body <= 0.15 * candle_range if candle_range > 0 else False
                
                lower_shadow = min(row['Open'], row['Close']) - row['Low']
                has_lower_shadow = lower_shadow >= 0.40 * candle_range if candle_range > 0 else False
                
                is_green = row['Close'] > row['Open']
                
                has_support_candle = is_doji or has_lower_shadow or is_green
                
                is_after_950 = (current_time.hour == 9 and current_time.minute >= 50) or current_time.hour >= 10
                if in_fib_zone and vol_dried and touches_support and has_support_candle and is_after_950:
                    entry_price = row['Close']
                    entry_time = current_time
                    in_position = True
                    runup_detected = False # Reset for next cycle
        else:
            # Position management
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
            
            if row['Low'] <= stop_price:
                trades.append({"return": -stop_pct, "type": "SL"})
                in_position = False
                break  # Max 1 trade per day
            elif row['High'] >= target_price:
                trades.append({"return": target_pct, "type": "PT"})
                in_position = False
                break  # Max 1 trade per day
            elif i == len(df) - 1 or current_time.hour == 15 and current_time.minute == 59:
                ret = (row['Close'] - entry_price) / entry_price
                trades.append({"return": ret, "type": "EOD"})
                in_position = False
                break  # Max 1 trade per day
                
    return trades

print("Loading data...")
data_dict = {}
for ticker, date_str in ticker_dates:
    df = load_data(ticker, date_str)
    if df is not None:
        data_dict[(ticker, date_str)] = df

# Parameters to test
configs = [
    # (min_runup, vol_dry, PT, SL)
    (0.20, 0.20, 0.02, 0.015),
    (0.20, 0.20, 0.03, 0.015),
    (0.20, 0.30, 0.02, 0.015),
    (0.20, 0.30, 0.03, 0.015),
    (0.20, 0.30, 0.02, 0.010), # Tight stop
    (0.30, 0.20, 0.03, 0.015), # Stronger runup
    (0.30, 0.30, 0.03, 0.015),
    (0.30, 0.30, 0.05, 0.020), # Higher targets
]

results = []
for runup, vol_dry, pt, sl in configs:
    all_trades = []
    for (ticker, date_str), df in data_dict.items():
        trades = simulate_strategy_b(df, runup, vol_dry, pt, sl)
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
            "Min Runup": f"{runup*100:.0f}%",
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

print("\n=== STRATEGY B (1ST DIP REVERSION) SIMULATION ===")
print(res_df.drop(columns=["Raw_Avg"]).to_string(index=False))
print("==================================================")

# Generate Markdown file
markdown_content = "# 🛡️ 전략 B (1st Dip Reversion) 백테스트 시뮬레이션 결과\n\n"
markdown_content += "급등주 첫 번째 눌림목(38.2%~50% 되돌림)에서 거래량 급감 및 VWAP/EMA10 지지를 확인하고 진입하는 전략 시뮬레이션 결과입니다.\n\n"
markdown_content += "## 📈 시뮬레이션 결과 목록\n\n"
markdown_content += "| 상승폭 조건 | 거래량 감소 필터 | 익절/손절 | 거래 횟수 | 승률 | 평균 수익률 | 손익비 |\n"
markdown_content += "| :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"

for idx, row in res_df.iterrows():
    markdown_content += f"| {row['Min Runup']} | {row['Vol Dry']} | {row['PT / SL']} | {row['Trades']} | {row['Win Rate']} | {row['Avg Return']} | {row['Profit Factor']} |\n"

output_path = str(Path(__file__).resolve().parent.parent / "results" / "strategy_b_results.md")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(markdown_content)
print(f"Saved results to {output_path}")
