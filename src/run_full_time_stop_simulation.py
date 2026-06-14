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

capital_all_in = 100.0
capital_half = 100.0
pt = 0.40
sl = 0.20
gap_limit = 2.00  # +200% limit

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
            "Type": "SKIP",
            "Return": 0.0,
            "Old All-in": capital_all_in,
            "New All-in": capital_all_in,
            "Old Half": capital_half,
            "New Half": capital_half,
            "Exit Time": "N/A",
            "Source": "FILTER"
        })
        print(f"[{date_str}] Skipped {ticker} - Gap {gap*100:+.2f}% >= 200%.")
        continue
        
    cache = cached_series[(ticker, date_str)]
    df_1m = cache["df_1m"]
    daily_info = cache["daily_info"]
    
    if df_1m is not None and len(df_1m) > 0:
        entry_price = float(df_1m.iloc[0]['Open'])
        initial_stop = entry_price * (1 - sl)
        target_price = entry_price * (1 + pt)
        
        exit_price = None
        exit_type = None
        exit_time = None
        
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
                exit_price = float(row['Open'])
                exit_type = "TIME"
                exit_time = "10:00"
                break
                
            low_val = float(row['Low'])
            high_val = float(row['High'])
            
            if low_val <= initial_stop:
                exit_price = initial_stop
                exit_type = "SL"
                exit_time = current_time.strftime("%H:%M")
                break
            if high_val >= target_price:
                exit_price = target_price
                exit_type = "PT"
                exit_time = current_time.strftime("%H:%M")
                break
                
        if exit_price is None:
            exit_price = float(df_1m.iloc[-1]['Close'])
            exit_type = "EOD"
            exit_time = "16:00"
            
        ret = (exit_price - entry_price) / entry_price
        source = "1M_DATA"
    else:
        # Fall back to daily data
        source = "DAILY_FALLBACK"
        entry_price = daily_info['Open']
        high_val = daily_info['High']
        low_val = daily_info['Low']
        close_val = daily_info['Close']
        
        initial_stop = entry_price * (1 - sl)
        target_price = entry_price * (1 + pt)
        
        if low_val <= initial_stop:
            exit_price = initial_stop
            exit_type = "SL"
            exit_time = "Intraday"
        elif high_val >= target_price:
            exit_price = target_price
            exit_type = "PT"
            exit_time = "Intraday"
        else:
            exit_price = close_val
            exit_type = "EOD"
            exit_time = "16:00"
        ret = (exit_price - entry_price) / entry_price
        
    old_all_in = capital_all_in
    capital_all_in = capital_all_in * (1 + ret)
    
    old_half = capital_half
    capital_half = capital_half * (1 + 0.5 * ret)
    
    log_entries.append({
        "Date": date_str,
        "Ticker": ticker,
        "Gap": gap,
        "Type": exit_type,
        "Return": ret,
        "Old All-in": old_all_in,
        "New All-in": capital_all_in,
        "Old Half": old_half,
        "New Half": capital_half,
        "Exit Time": exit_time,
        "Source": source
    })
    print(f"[{date_str}] {ticker}: Return {ret*100:+.2f}% ({exit_type} @ {exit_time}). All-in: {old_all_in:.2f}->{capital_all_in:.2f} | 50%: {old_half:.2f}->{capital_half:.2f}")

# Save to Markdown report
md = f"# 📊 시작가 +200% 제한 및 30분 타임컷 청산 시초가 매수 시뮬레이션 결과 (전체 기간)\n\n"
md += f"**분석 기간**: 2026-05-01 ~ 2026-06-12 (30개 거래일)\n"
md += f"**선정 종목**: 매일 아침 09:30 기준 전체 시장 갭상승률 **2위 종목 단독 진입**\n"
md += f"**진입 필터**: 시초가 갭상승률 **+200% 미만일 때만 진입 (이상일 경우 거래 없음)**\n"
md += f"**청산 규칙**: 목표 익절 **+40.0%** / 손절 한도 **-20.0%** / **진입 30분 후인 10:00에 강제 타임컷 청산**\n\n"

md += f"## 🏆 최종 자금 결과\n"
md += f"| 구분 | 1. 전액 복리 All-in (100% 베팅) | 2. 50% 투자 + 50% 현금 예치 (50% 베팅) |\n"
md += f"| :--- | :---: | :---: |\n"
md += f"| **최종 자금** (100원 시작) | **{capital_all_in:.2f}원** | **{capital_half:.2f}원** |\n"
md += f"| **최종 누적 수익률** | **{((capital_all_in - 100)/100)*100:+.2f}%** | **{((capital_half - 100)/100)*100:+.2f}%** |\n\n"

md += f"## 📈 매일매일 종목 및 자금 흐름 상세 이력\n\n"
md += "| 날짜 | 종목명 | 갭상승률 | 당일 수익률 | All-in 자금 | 50% 베팅 자금 | 결과 유형 | 청산 시간 | 소스 |\n"
md += "| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"

for r in log_entries:
    md += f"| {r['Date']} | {r['Ticker']} | {r['Gap']*100:+.2f}% | {r['Return']*100:+.2f}% | {r['New All-in']:.2f}원 | {r['New Half']:.2f}원 | {r['Type']} | {r['Exit Time']} | {r['Source']} |\n"

output_md_path = str(Path(__file__).resolve().parent.parent / "results" / "full_time_stop_results.md")
with open(output_md_path, "w", encoding="utf-8") as f:
    f.write(md)
print(f"Saved full time stop results to {output_md_path}")
