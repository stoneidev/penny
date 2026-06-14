from pathlib import Path
import os
import ftplib
import time
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

# 1. Connect to FTP and download symbol lists
print("Connecting to ftp.nasdaqtrader.com...")
try:
    ftp = ftplib.FTP("ftp.nasdaqtrader.com")
    ftp.login("anonymous", "")
    ftp.cwd("SymbolDirectory")
    
    for filename in ["nasdaqlisted.txt", "otherlisted.txt"]:
        print(f"Downloading {filename}...")
        with open(filename, 'wb') as fp:
            ftp.retrbinary(f"RETR {filename}", fp.write)
    ftp.quit()
    print("Downloaded symbols successfully.")
except Exception as e:
    print(f"FTP download failed: {e}")

# 2. Parse symbols
tickers = []
if os.path.exists("nasdaqlisted.txt"):
    df_nasdaq = pd.read_csv("nasdaqlisted.txt", sep="|")
    # Ticker symbol is in the first column
    symbols = df_nasdaq.iloc[:-1, 0].tolist()  # Exclude last footer line
    for s in symbols:
        if isinstance(s, str) and s.isalpha() and len(s) <= 5:
            tickers.append(s)

if os.path.exists("otherlisted.txt"):
    df_other = pd.read_csv("otherlisted.txt", sep="|")
    symbols = df_other.iloc[:-1, 0].tolist()
    for s in symbols:
        if isinstance(s, str) and s.isalpha() and len(s) <= 5:
            tickers.append(s)

tickers = sorted(list(set(tickers)))
print(f"Extracted {len(tickers)} valid tickers for scanning.")

# 3. Download daily data for past week in chunks
# Period: June 1, 2026 to June 13, 2026 (covers June 8 to June 12 with buffer)
start_date = "2026-06-01"
end_date = "2026-06-13"

chunk_size = 500
daily_dfs = []

print(f"Downloading daily data in chunks of {chunk_size}...")
for i in range(0, len(tickers), chunk_size):
    chunk = tickers[i:i+chunk_size]
    print(f"Downloading chunk {i // chunk_size + 1}/{len(tickers) // chunk_size + 1} ({len(chunk)} tickers)...")
    try:
        df = yf.download(chunk, start=start_date, end=end_date, interval="1d", group_by="ticker", progress=False)
        daily_dfs.append(df)
    except Exception as e:
        print(f"Error downloading chunk: {e}")
    time.sleep(1.0)  # Polite delay

# Combine all data
print("Combining daily data...")
# We will create a combined dictionary for easy lookup: (ticker, date) -> OHLCV
daily_lookup = {}

for df in daily_dfs:
    # Get all tickers in this chunk from the columns
    if df.empty:
        continue
    # yfinance columns are MultiIndex (Ticker, Metric)
    if isinstance(df.columns, pd.MultiIndex):
        chunk_tickers = list(set([col[0] for col in df.columns]))
        for t in chunk_tickers:
            try:
                t_df = df[t]
                for idx, row in t_df.iterrows():
                    date_str = idx.strftime("%Y-%m-%d")
                    daily_lookup[(t, date_str)] = {
                        "Open": row["Open"],
                        "High": row["High"],
                        "Low": row["Low"],
                        "Close": row["Close"],
                        "Volume": row["Volume"]
                    }
            except Exception:
                continue

# Save daily lookup to JSON to avoid re-downloading if needed
print("Daily lookup build complete.")

# 4. Find the actual top gap-up stocks for the past week: June 8 to June 12
past_week_dates = ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]
real_selections = {}

# We need the previous trading days for each date
trading_days = sorted(list(set([k[1] for k in daily_lookup.keys()])))

for date_str in past_week_dates:
    if date_str not in trading_days:
        print(f"[{date_str}] Date not in trading days.")
        continue
        
    current_idx = trading_days.index(date_str)
    if current_idx == 0:
        continue
    prev_date_str = trading_days[current_idx - 1]
    
    day_gaps = []
    
    # Check all tickers
    unique_tickers = list(set([k[0] for k in daily_lookup.keys()]))
    for t in unique_tickers:
        today_info = daily_lookup.get((t, date_str))
        prev_info = daily_lookup.get((t, prev_date_str))
        
        if today_info is None or prev_info is None:
            continue
            
        op = today_info["Open"]
        pc = prev_info["Close"]
        vol = today_info["Volume"]
        prev_vol = prev_info["Volume"]
        
        if pd.isna(op) or pd.isna(pc) or op <= 0 or pc <= 0:
            continue
            
        # Filters:
        # 1. Open price between $1.00 and $10.00
        if not (1.0 <= op <= 10.0):
            continue
            
        # 2. Previous day dollar volume >= $50,000
        prev_dollar_vol = pc * prev_vol
        if pd.isna(prev_dollar_vol) or prev_dollar_vol < 50000:
            continue
            
        gap = (op - pc) / pc
        day_gaps.append((t, gap, op, pc, today_info["High"], today_info["Low"], today_info["Close"]))
        
    # Sort by gap percentage descending
    day_gaps = sorted(day_gaps, key=lambda x: x[1], reverse=True)
    
    # Select top 3
    top_3 = day_gaps[:3]
    real_selections[date_str] = top_3
    print(f"[{date_str}] Real Top 3 in Market:")
    for idx, (t, gap, op, pc, h, l, c) in enumerate(top_3):
        print(f"  {idx+1}. {t}: Gap {gap*100:+.2f}% (Open: {op:.4f}, Prev Close: {pc:.4f})")

# 5. Run the trailing stop / fixed PT simulation for the 2nd stock on each day
capital_all_in = 100.0
capital_half = 100.0
pt = 0.40
sl = 0.20

log_entries = []

for date_str in past_week_dates:
    selections = real_selections.get(date_str, [])
    if len(selections) < 2:
        print(f"[{date_str}] Less than 2 stocks selected.")
        continue
    ticker, gap, op, pc, high_d, low_d, close_d = selections[1]  # Rank 2
    
    # Try downloading 1m data for this specific day
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)
    
    df_1m = None
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
        
    # Simulate trade
    if df_1m is not None and len(df_1m) > 0:
        entry_price = float(df_1m.iloc[0]['Open'])
        initial_stop = entry_price * (1 - sl)
        target_price = entry_price * (1 + pt)
        
        exit_price = None
        exit_type = None
        
        for i in range(len(df_1m)):
            row = df_1m.iloc[i]
            low_val = float(row['Low'])
            high_val = float(row['High'])
            
            if low_val <= initial_stop:
                exit_price = initial_stop
                exit_type = "SL"
                break
            if high_val >= target_price:
                exit_price = target_price
                exit_type = "PT"
                break
                
        if exit_price is None:
            exit_price = float(df_1m.iloc[-1]['Close'])
            exit_type = "EOD"
            
        ret = (exit_price - entry_price) / entry_price
        source = "1M_DATA"
    else:
        # Daily fallback
        entry_price = op
        initial_stop = entry_price * (1 - sl)
        target_price = entry_price * (1 + pt)
        
        if low_d <= initial_stop:
            exit_price = initial_stop
            exit_type = "SL"
        elif high_d >= target_price:
            exit_price = target_price
            exit_type = "PT"
        else:
            exit_price = close_d
            exit_type = "EOD"
        ret = (exit_price - entry_price) / entry_price
        source = "DAILY_FALLBACK"
        
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
        "Source": source
    })
    print(f"[{date_str}] {ticker}: Return {ret*100:+.2f}% ({exit_type}). All-in: {old_all_in:.2f}->{capital_all_in:.2f} | 50%: {old_half:.2f}->{capital_half:.2f}")

# Save comparison report
md = f"# 📊 실제 전 미국 시장 대상 지난 1주일(6/8~6/12) 2등 종목 시뮬레이션 결과\n\n"
md += f"**분석 기간**: 2026-06-08 ~ 2026-06-12 (지난 1주일)\n"
md += f"**종목 유니버스**: ftp.nasdaqtrader.com에서 실시간 다운로드한 **전체 미국 시장 상장 종목** 대상\n"
md += f"**선정 종목**: 매일 아침 09:30 기준 전체 시장 갭상승률 **2위 종목 단독 진입**\n"
md += f"**매매 룰**: 목표 익절 **+40.0%** / 손절 한도 **-20.0%** / 장마감(EOD) 청산\n\n"

md += f"## 🏆 최종 자금 결과\n"
md += f"| 구분 | 1. 전액 복리 All-in (100% 베팅) | 2. 50% 투자 + 50% 현금 예치 (50% 베팅) |\n"
md += f"| :--- | :---: | :---: |\n"
md += f"| **최종 자금** (100원 시작) | **{capital_all_in:.2f}원** | **{capital_half:.2f}원** |\n"
md += f"| **최종 누적 수익률** | **{((capital_all_in - 100)/100)*100:+.2f}%** | **{((capital_half - 100)/100)*100:+.2f}%** |\n\n"

md += f"## 📈 매일매일 종목 및 자금 흐름 상세 이력\n\n"
md += "| 날짜 | 종목명 | 갭상승률 | 당일 수익률 | All-in 자금 | 50% 베팅 자금 | 결과 유형 | 데이터 소스 |\n"
md += "| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"

for r in log_entries:
    md += f"| {r['Date']} | {r['Ticker']} | {r['Gap']*100:+.2f}% | {r['Return']*100:+.2f}% | {r['New All-in']:.2f}원 | {r['New Half']:.2f}원 | {r['Type']} | {r['Source']} |\n"

output_md_path = str(Path(__file__).resolve().parent.parent / "results" / "real_market_past_week_results.md")
with open(output_md_path, "w", encoding="utf-8") as f:
    f.write(md)
print(f"Saved real market past week results to {output_md_path}")
