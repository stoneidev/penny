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
print("Downloading daily data for all tickers to ensure fresh daily stats...")
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

# Pre-cache selected ticker-dates (only the 2nd one since we do Skip #1 = True and Num Splits = 1)
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

# Option A: Trailing Stop 20% (No Time Stop)
capital_all_in_A = 100.0
capital_half_A = 100.0

# Option B: Trailing Stop 20% + 30-Min Time Stop
capital_all_in_B = 100.0
capital_half_B = 100.0

sl = 0.20
ts = 0.20
gap_limit = 2.00

log_entries = []

for date_str in sorted_days:
    selections = daily_selections[date_str]
    if len(selections) < 2:
        continue
    ticker, gap, op, pc = selections[1]
    
    # Check if gap is >= 200%
    if gap >= gap_limit:
        log_entries.append({
            "Date": date_str,
            "Ticker": ticker,
            "Gap": gap,
            "Ret_A": 0.0,
            "Ret_B": 0.0,
            "Type_A": "SKIP",
            "Type_B": "SKIP",
            "Cap_All_A": capital_all_in_A,
            "Cap_Half_A": capital_half_A,
            "Cap_All_B": capital_all_in_B,
            "Cap_Half_B": capital_half_B
        })
        continue
        
    cache = cached_series[(ticker, date_str)]
    df_1m = cache["df_1m"]
    daily_info = cache["daily_info"]
    
    # Run Option A (No Time Stop)
    if df_1m is not None and len(df_1m) > 0:
        entry_price = float(df_1m.iloc[0]['Open'])
        initial_stop = entry_price * (1 - sl)
        
        exit_price_A = None
        exit_type_A = None
        high_max = entry_price
        
        for i in range(len(df_1m)):
            row = df_1m.iloc[i]
            low_val = float(row['Low'])
            high_val = float(row['High'])
            
            current_stop = max(initial_stop, high_max * (1 - ts))
            if low_val <= current_stop:
                exit_price_A = current_stop
                exit_type_A = "TS" if current_stop > initial_stop else "SL"
                break
            high_max = max(high_max, high_val)
            
        if exit_price_A is None:
            exit_price_A = float(df_1m.iloc[-1]['Close'])
            exit_type_A = "EOD"
        ret_A = (exit_price_A - entry_price) / entry_price
    else:
        # Fall back to daily data
        entry_price = daily_info['Open']
        high_val = daily_info['High']
        low_val = daily_info['Low']
        close_val = daily_info['Close']
        initial_stop = entry_price * (1 - sl)
        trailing_stop = high_val * (1 - ts)
        
        if low_val <= initial_stop:
            exit_price_A = initial_stop
            exit_type_A = "SL"
        elif low_val <= trailing_stop:
            exit_price_A = trailing_stop
            exit_type_A = "TS"
        else:
            exit_price_A = close_val
            exit_type_A = "EOD"
        ret_A = (exit_price_A - entry_price) / entry_price
        
    # Run Option B (30-Min Time Stop)
    if df_1m is not None and len(df_1m) > 0:
        entry_price = float(df_1m.iloc[0]['Open'])
        initial_stop = entry_price * (1 - sl)
        
        exit_price_B = None
        exit_type_B = None
        high_max = entry_price
        
        if 'timestamp' in df_1m.columns:
            start_time = df_1m.iloc[0]['timestamp']
        else:
            start_time = df_1m.index[0]
        start_time = pd.to_datetime(start_time)
        time_limit = start_time.replace(hour=10, minute=0, second=0)
        
        for i in range(len(df_1m)):
            row = df_1m.iloc[i]
            if 'timestamp' in df_1m.columns:
                current_time = row['timestamp']
            else:
                current_time = df_1m.iloc[i]['timestamp'] if 'timestamp' in df_1m.columns else df_1m.index[i]
            current_time = pd.to_datetime(current_time)
            current_time = pd.to_datetime(current_time)
            
            if current_time > time_limit:
                exit_price_B = float(row['Open'])
                exit_type_B = "TIME"
                break
                
            low_val = float(row['Low'])
            high_val = float(row['High'])
            
            current_stop = max(initial_stop, high_max * (1 - ts))
            if low_val <= current_stop:
                exit_price_B = current_stop
                exit_type_B = "TS" if current_stop > initial_stop else "SL"
                break
            high_max = max(high_max, high_val)
            
        if exit_price_B is None:
            exit_price_B = float(df_1m.iloc[-1]['Close'])
            exit_type_B = "EOD"
        ret_B = (exit_price_B - entry_price) / entry_price
    else:
        # For daily data, Time Stop behaves similarly to EOD close fallback
        entry_price = daily_info['Open']
        high_val = daily_info['High']
        low_val = daily_info['Low']
        close_val = daily_info['Close']
        initial_stop = entry_price * (1 - sl)
        trailing_stop = high_val * (1 - ts)
        
        if low_val <= initial_stop:
            exit_price_B = initial_stop
            exit_type_B = "SL"
        elif low_val <= trailing_stop:
            exit_price_B = trailing_stop
            exit_type_B = "TS"
        else:
            exit_price_B = close_val
            exit_type_B = "EOD"
        ret_B = (exit_price_B - entry_price) / entry_price
        
    # Apply compounding
    capital_all_in_A *= (1 + ret_A)
    capital_half_A *= (1 + 0.5 * ret_A)
    
    capital_all_in_B *= (1 + ret_B)
    capital_half_B *= (1 + 0.5 * ret_B)
    
    log_entries.append({
        "Date": date_str,
        "Ticker": ticker,
        "Gap": gap,
        "Ret_A": ret_A,
        "Ret_B": ret_B,
        "Type_A": exit_type_A,
        "Type_B": exit_type_B,
        "Cap_All_A": capital_all_in_A,
        "Cap_Half_A": capital_half_A,
        "Cap_All_B": capital_all_in_B,
        "Cap_Half_B": capital_half_B
    })
    print(f"[{date_str}] {ticker}: Ret A {ret_A*100:+.2f}% ({exit_type_A}) | Ret B {ret_B*100:+.2f}% ({exit_type_B})")

# Print overall summary
print("\n=== OVERALL SIMULATION SUMMARY ===")
print(f"Option A (No Time Stop) All-in:  {capital_all_in_A:.2f} (+{capital_all_in_A-100:.2f}%)")
print(f"Option A (No Time Stop) 50% Bet: {capital_half_A:.2f} (+{capital_half_A-100:.2f}%)")
print(f"Option B (Time Stop 30m) All-in:  {capital_all_in_B:.2f} (+{capital_all_in_B-100:.2f}%)")
print(f"Option B (Time Stop 30m) 50% Bet: {capital_half_B:.2f} (+{capital_half_B-100:.2f}%)")

# Save to Markdown
md = f"# 📊 트레일링 스탑 적용 시초가 매수 시뮬레이션 결과 비교\n\n"
md += f"**분석 기간**: 2026-05-01 ~ 2026-06-12 (30개 거래일)\n"
md += f"**선정 종목**: 매일 아침 09:30 기준 전체 시장 갭상승률 **2위 종목 단독 진입**\n"
md += f"**진입 필터**: 시초가 갭상승률 **+200% 미만일 때만 진입 (이상일 경우 거래 없음)**\n"
md += f"**청산 규칙**: 초기 손절 한도 **-20.0%** / 고점 대비 **-20.0% 하락 시 트레일링 스탑(TS) 청산**\n\n"

md += f"## 🏆 최종 자금 결과\n"
md += f"| 구분 | Option A: 트레일링 스탑 단독 (EOD 마감) | Option B: 트레일링 스탑 + 30분 타임컷 (10:00 마감) |\n"
md += f"| :--- | :---: | :---: |\n"
md += f"| **All-in 최종 자금** | **{capital_all_in_A:.2f}원** (+{capital_all_in_A-100:.2f}%) | **{capital_all_in_B:.2f}원** (+{capital_all_in_B-100:.2f}%) |\n"
md += f"| **50% 베팅 최종 자금** | **{capital_half_A:.2f}원** (+{capital_half_A-100:.2f}%) | **{capital_half_B:.2f}원** (+{capital_half_B-100:.2f}%) |\n\n"

md += f"## 📈 매일매일 종목 및 자금 흐름 상세 이력\n\n"
md += "| 날짜 | 종목명 | 갭상승률 | Option A 수익률 | Option A 잔고 | Option B 수익률 | Option B 잔고 |\n"
md += "| :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"

for r in log_entries:
    md += f"| {r['Date']} | {r['Ticker']} | {r['Gap']*100:+.2f}% | {r['Ret_A']*100:+.2f}% ({r['Type_A']}) | {r['Cap_All_A']:.2f}원 | {r['Ret_B']*100:+.2f}% ({r['Type_B']}) | {r['Cap_All_B']:.2f}원 |\n"

output_md_path = str(Path(__file__).resolve().parent.parent / "results" / "full_trailing_stop_comparison.md")
with open(output_md_path, "w", encoding="utf-8") as f:
    f.write(md)
print(f"Saved full trailing stop results to {output_md_path}")
