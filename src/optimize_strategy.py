import os
import json
import time
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
print("Downloading daily data for all tickers...")
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

# Pre-cache all selection data (1m and daily fallback) to speed up grid search
cached_series = {}
sorted_days = sorted(list(daily_selections.keys()))

print("Pre-caching selection data for grid search...")
for date_str in sorted_days:
    selections = daily_selections[date_str]
    current_date = pd.Timestamp(date_str)
    
    for ticker, gap, op, pc in selections:
        # Check if already cached
        key = (ticker, date_str)
        if key in cached_series:
            continue
            
        # Try 1m cache
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
                    
        # Load daily fallback info
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
            daily_info = {
                "Open": op,
                "High": op,
                "Low": op,
                "Close": op
            }
            
        cached_series[key] = {
            "df_1m": df_1m,
            "daily_info": daily_info
        }
    # Small delay between days to prevent rate limits
    time.sleep(0.1)

print("Pre-caching complete.")

# 4. Grid Search Optimization
best_capital = 0
best_params = {}
all_results = []

# Parameter grids
pt_grid = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
sl_grid = [0.05, 0.075, 0.10, 0.125, 0.15, 0.20]
ts_grid = [None, 0.05, 0.10, 0.15, 0.20]  # None means fixed PT, float is trailing stop percentage
skip_first_grid = [False, True]  # skip the highest gap-up stock?
splits_grid = [1, 2, 3]  # how many splits

print("Starting grid search...")
total_runs = len(pt_grid) * len(sl_grid) * len(ts_grid) * len(skip_first_grid) * len(splits_grid)
run_count = 0

for skip_first in skip_first_grid:
    for num_splits in splits_grid:
        for sl in sl_grid:
            for pt in pt_grid:
                for ts in ts_grid:
                    run_count += 1
                    capital = 100.0
                    
                    for date_str in sorted_days:
                        selections = daily_selections[date_str]
                        
                        # Apply skip first and num_splits logic
                        day_selections = selections[1:] if skip_first else selections
                        day_selections = day_selections[:num_splits]
                        
                        if not day_selections:
                            continue
                            
                        returns = []
                        current_date = pd.Timestamp(date_str)
                        
                        for ticker, gap, op, pc in day_selections:
                            cache = cached_series[(ticker, date_str)]
                            df_1m = cache["df_1m"]
                            daily_info = cache["daily_info"]
                            
                            # Simulate trade
                            if df_1m is not None and len(df_1m) > 0:
                                entry_price = float(df_1m.iloc[0]['Open'])
                                initial_stop = entry_price * (1 - sl)
                                target_price = entry_price * (1 + pt)
                                
                                exit_price = None
                                high_max = entry_price
                                
                                for i in range(len(df_1m)):
                                    row = df_1m.iloc[i]
                                    low_val = float(row['Low'])
                                    high_val = float(row['High'])
                                    
                                    if ts is not None:
                                        # Trailing stop logic
                                        current_stop = max(initial_stop, high_max * (1 - ts))
                                        if low_val <= current_stop:
                                            exit_price = current_stop
                                            break
                                        high_max = max(high_max, high_val)
                                    else:
                                        # Fixed PT/SL logic
                                        if low_val <= initial_stop:
                                            exit_price = initial_stop
                                            break
                                        if high_val >= target_price:
                                            exit_price = target_price
                                            break
                                            
                                if exit_price is None:
                                    exit_price = float(df_1m.iloc[-1]['Close'])
                                ret = (exit_price - entry_price) / entry_price
                            else:
                                # Fall back to daily data (conservative worst case)
                                entry_price = daily_info['Open']
                                high_val = daily_info['High']
                                low_val = daily_info['Low']
                                close_val = daily_info['Close']
                                
                                initial_stop = entry_price * (1 - sl)
                                target_price = entry_price * (1 + pt)
                                trailing_stop = high_val * (1 - ts) if ts is not None else 0
                                
                                if ts is not None:
                                    if low_val <= initial_stop:
                                        exit_price = initial_stop
                                    elif low_val <= trailing_stop:
                                        exit_price = trailing_stop
                                    else:
                                        exit_price = close_val
                                else:
                                    if low_val <= initial_stop:
                                        exit_price = initial_stop
                                    elif high_val >= target_price:
                                        exit_price = target_price
                                    else:
                                        exit_price = close_val
                                ret = (exit_price - entry_price) / entry_price
                                
                            returns.append(ret)
                            
                        day_avg_return = np.mean(returns) if returns else 0.0
                        capital = capital * (1 + day_avg_return)
                        
                    all_results.append({
                        "pt": pt,
                        "sl": sl,
                        "ts": ts,
                        "skip_first": skip_first,
                        "splits": num_splits,
                        "final_capital": capital
                    })

# Sort results by final capital descending
all_results = sorted(all_results, key=lambda x: x['final_capital'], reverse=True)

# Best parameter set
best = all_results[0]
print("\n=== OPTIMIZATION COMPLETE ===")
print(f"Best Final Capital: {best['final_capital']:.2f} (Return: {((best['final_capital']-100)/100)*100:+.2f}%)")
print(f"Parameters:")
print(f"  - Profit Target:  {best['pt']*100:.1f}%")
print(f"  - Stop Loss:      {best['sl']*100:.1f}%")
ts_str = f"{best['ts']*100:.1f}%" if best['ts'] is not None else 'None'
print(f"  - Trailing Stop:  {ts_str}")
print(f"  - Skip #1 Stock:  {best['skip_first']}")
print(f"  - Num Splits:     {best['splits']}")

# Save top 20 results in a markdown artifact
md = f"# 🏆 시초가 매수 전략 파라미터 최적화 결과 리포트\n\n"
md += f"**분석 기간**: 2026-05-01 ~ 2026-06-12 (30개 거래일)\n\n"
md += f"## 📊 최적 파라미터 세트\n"
md += f"* **최고 최종 자금**: **{best['final_capital']:.2f}원** (수익률: **{((best['final_capital']-100)/100)*100:+.2f}%**)\n"
md += f"* **익절 목표 (Profit Target)**: **{best['pt']*100:.1f}%**\n"
md += f"* **손절 한도 (Stop Loss)**: **{best['sl']*100:.1f}%**\n"
best_ts_str = f"{best['ts']*100:.1f}%" if best['ts'] is not None else '사용 안 함 (고정 익절 적용)'
md += f"* **트레일링 스탑 버퍼 (Trailing Stop)**: **{best_ts_str}**\n"
md += f"* **1위 갭상승 종목 제외 여부 (Skip #1)**: **{best['skip_first']}**\n"
md += f"* **자금 분할 수 (Num Splits)**: **{best['splits']}분할**\n\n"

md += f"## 📈 상위 20개 최적화 조합 리스트\n\n"
md += "| 순위 | 익절 목표 (PT) | 손절 한도 (SL) | 트레일링 스탑 (TS) | 1위 종목 제외 | 분할 수 | 최종 자금 | 누적 수익률 |\n"
md += "| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"

for idx, r in enumerate(all_results[:20]):
    ts_str = f"{r['ts']*100:.1f}%" if r['ts'] is not None else "N/A"
    skip_str = "예" if r['skip_first'] else "아니오"
    md += f"| {idx+1} | {r['pt']*100:.1f}% | {r['sl']*100:.1f}% | {ts_str} | {skip_str} | {r['splits']} | {r['final_capital']:.2f}원 | {((r['final_capital']-100)/100)*100:+.2f}% |\n"

output_md_path = str(Path(__file__).resolve().parent.parent / "results" / "optimized_results.md")
with open(output_md_path, "w", encoding="utf-8") as f:
    f.write(md)
print(f"Saved results to {output_md_path}")
