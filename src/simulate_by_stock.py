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

def simulate_strategy_b(df, min_runup_pct=0.30, vol_dry_mult=0.20, target_pct=0.03, stop_pct=0.015):
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
            # Swing detection
            rolling_low = df.iloc[:i+1]['Low'].min()
            rolling_high = df.iloc[:i+1]['High'].max()
            
            runup_pct = (rolling_high - rolling_low) / rolling_low
            if runup_pct >= min_runup_pct:
                if not runup_detected or rolling_high > (swing_high_b or 0):
                    swing_low_a = rolling_low
                    swing_high_b = rolling_high
                    
                    runup_df = df.iloc[:i+1]
                    runup_df = runup_df[runup_df['High'] <= swing_high_b]
                    max_vol_runup = runup_df['Volume'].max()
                    
                    runup_detected = True
            
            # Strategy B check
            if runup_detected and swing_low_a and swing_high_b:
                swing_range = swing_high_b - swing_low_a
                fib_382 = swing_high_b - 0.382 * swing_range
                fib_500 = swing_high_b - 0.500 * swing_range
                
                in_fib_zone = fib_500 <= row['Low'] <= fib_382 or fib_500 <= row['Close'] <= fib_382
                vol_dried = row['Volume'] < vol_dry_mult * max_vol_runup if max_vol_runup > 0 else False
                
                touches_vwap = row['Low'] <= row['VWAP'] * 1.005 and row['Close'] >= row['VWAP'] * 0.995
                touches_ema10 = row['Low'] <= row['EMA10'] * 1.005 and row['Close'] >= row['EMA10'] * 0.995
                touches_support = touches_vwap or touches_ema10
                
                body = abs(row['Close'] - row['Open'])
                candle_range = row['High'] - row['Low']
                is_doji = body <= 0.15 * candle_range if candle_range > 0 else False
                
                lower_shadow = min(row['Open'], row['Close']) - row['Low']
                has_lower_shadow = lower_shadow >= 0.40 * candle_range if candle_range > 0 else False
                is_green = row['Close'] > row['Open']
                
                has_support_candle = is_doji or has_lower_shadow or is_green
                
                if in_fib_zone and vol_dried and touches_support and has_support_candle:
                    entry_price = row['Close']
                    entry_time = current_time
                    in_position = True
                    runup_detected = False
        else:
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
            
            if row['Low'] <= stop_price:
                trades.append({
                    "entry_time": entry_time.strftime("%H:%M"),
                    "entry_price": entry_price,
                    "exit_time": current_time.strftime("%H:%M"),
                    "exit_price": stop_price,
                    "return": -stop_pct,
                    "type": "SL"
                })
                in_position = False
            elif row['High'] >= target_price:
                trades.append({
                    "entry_time": entry_time.strftime("%H:%M"),
                    "entry_price": entry_price,
                    "exit_time": current_time.strftime("%H:%M"),
                    "exit_price": target_price,
                    "return": target_pct,
                    "type": "PT"
                })
                in_position = False
            elif i == len(df) - 1 or current_time.hour == 15 and current_time.minute == 59:
                ret = (row['Close'] - entry_price) / entry_price
                trades.append({
                    "entry_time": entry_time.strftime("%H:%M"),
                    "entry_price": entry_price,
                    "exit_time": current_time.strftime("%H:%M"),
                    "exit_price": row['Close'],
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

# Best Parameter Set: Min Runup=30%, Vol Dry=<20%, PT=3%, SL=1.5%
results_by_stock = []
for (ticker, date_str), df in data_dict.items():
    trades = simulate_strategy_b(df, min_runup_pct=0.30, vol_dry_mult=0.20, target_pct=0.03, stop_pct=0.015)
    
    total_trades = len(trades)
    wins = len([t for t in trades if t['return'] > 0])
    losses = len([t for t in trades if t['return'] < 0])
    win_rate = wins / total_trades if total_trades > 0 else 0
    avg_ret = np.mean([t['return'] for t in trades]) if total_trades > 0 else 0
    
    gains = sum([t['return'] for t in trades if t['return'] > 0])
    l_sum = sum([-t['return'] for t in trades if t['return'] < 0])
    pf = gains / l_sum if l_sum > 0 else (float('inf') if gains > 0 else 1.0)
    
    results_by_stock.append({
        "Ticker": ticker,
        "Date": date_str,
        "Trades": total_trades,
        "Win Rate": f"{win_rate*100:.1f}%" if total_trades > 0 else "N/A",
        "Avg Return": f"{avg_ret*100:+.2f}%" if total_trades > 0 else "0.00%",
        "PF": f"{pf:.2f}" if pf != float('inf') else "INF",
        "Raw_Return": avg_ret * total_trades, # Cumulative return of the day
        "Detail": trades
    })

# Format results into a nice markdown structure
markdown_content = "# 🔍 종목별 전략 B (1st Dip Reversion) 시뮬레이션 상세 결과\n\n"
markdown_content += "각 종목의 세부 거래 일지 및 일자별 성과 분석 결과입니다.\n\n"
markdown_content += "## 📊 일자/종목별 성과 요약\n\n"
markdown_content += "| 종목명 (티커) | 날짜 | 총 거래 횟수 | 승률 | 일일 누적 수익률 | 손익비 |\n"
markdown_content += "| :--- | :--- | :---: | :---: | :---: | :---: |\n"

for r in results_by_stock:
    markdown_content += f"| **{r['Ticker']}** | {r['Date']} | {r['Trades']}회 | {r['Win Rate']} | {r['Raw_Return']*100:+.2f}% | {r['PF']} |\n"

markdown_content += "\n## 📝 세부 거래 일지 (Detailed Trade Logs)\n\n"
for r in results_by_stock:
    markdown_content += f"### 📌 {r['Ticker']} ({r['Date']})\n"
    if r['Trades'] == 0:
        markdown_content += "* 해당 일에는 거래 조건(상승폭 30% 이상 및 거래량 급감 등)이 발생하지 않았습니다.\n\n"
    else:
        markdown_content += "| 진입 시간 | 진입 가격 | 청산 시간 | 청산 가격 | 수익률 | 유형 |\n"
        markdown_content += "| :---: | :---: | :---: | :---: | :---: | :---: |\n"
        for t in r['Detail']:
            markdown_content += f"| {t['entry_time']} | ${t['entry_price']:.4f} | {t['exit_time']} | ${t['exit_price']:.4f} | {t['return']*100:+.2f}% | {t['type']} |\n"
        markdown_content += "\n"

output_path = str(Path(__file__).resolve().parent.parent / "results" / "stock_by_stock_results.md")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(markdown_content)
print(f"Saved results to {output_path}")
