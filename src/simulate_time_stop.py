from pathlib import Path
import os
import json
import time
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

# Hardcoded Rank 2 tickers and metrics from our previous full scan on the past week
rank2_selections = {
    "2026-06-08": {"ticker": "GMHS", "gap": 0.5708, "op": 1.4750, "pc": 0.9390},
    "2026-06-09": {"ticker": "CHAI", "gap": 3.3537, "op": 3.5700, "pc": 0.8200},
    "2026-06-10": {"ticker": "VSME", "gap": 3.4957, "op": 3.7000, "pc": 0.8230},
    "2026-06-11": {"ticker": "GLXG", "gap": 1.6127, "op": 2.5500, "pc": 0.9760},
    "2026-06-12": {"ticker": "DSY", "gap": 0.7732, "op": 6.8800, "pc": 3.8800}
}

past_week_dates = ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]

capital_all_in = 100.0
capital_half = 100.0
pt = 0.40
sl = 0.20
gap_limit = 2.00  # +200% limit

log_entries = []

print("Running simulation with +200% Gap Limit and 30-Min Time Stop...")

for date_str in past_week_dates:
    sel = rank2_selections[date_str]
    ticker = sel["ticker"]
    gap = sel["gap"]
    op = sel["op"]
    pc = sel["pc"]
    
    # 1. Check if gap-up is >= 200%
    if gap >= gap_limit:
        print(f"[{date_str}] Skipped {ticker} - Gap {gap*100:+.2f}% is >= 200%.")
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
            "Exit Time": "N/A"
        })
        continue
        
    # Download 1m data
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
        
    if df_1m is not None and len(df_1m) > 0:
        entry_price = float(df_1m.iloc[0]['Open'])
        initial_stop = entry_price * (1 - sl)
        target_price = entry_price * (1 + pt)
        
        exit_price = None
        exit_type = None
        exit_time = None
        
        # We only loop for the first 30 minutes (09:30 to 10:00)
        # RTH start is 09:30. 30 minutes means up to 10:00 (index ~ 30)
        start_time = df_1m.iloc[0]['timestamp'] if 'timestamp' in df_1m.columns else df_1m.index[0]
        start_time = pd.to_datetime(start_time)
        time_limit = start_time.replace(hour=10, minute=0, second=0)
        
        for i in range(len(df_1m)):
            current_time = df_1m.iloc[i]['timestamp'] if 'timestamp' in df_1m.columns else df_1m.index[i]
            current_time = pd.to_datetime(current_time)
            row = df_1m.iloc[i]
            
            # Check Time Stop first: if current bar is past 10:00 AM
            if current_time > time_limit:
                # Exit at the close of the 10:00 candle (which is the previous one or current one)
                # We exit at the Open of current_time or Close of previous row
                exit_price = float(df_1m.iloc[i]['Open'])  # exit at the open of 10:01
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
                
        # If the day ended before 10:00 (highly unlikely but for safety)
        if exit_price is None:
            exit_price = float(df_1m.iloc[-1]['Close'])
            exit_type = "EOD"
            exit_time = "16:00"
            
        ret = (exit_price - entry_price) / entry_price
        source = "1M_DATA"
    else:
        # Fall back to daily data (conservative worst case)
        # Since we don't have 1m data, we can't do exact 30-min time stop,
        # so we conservatively assume EOD Close or SL (worst case)
        source = "DAILY_FALLBACK"
        try:
            d_df = yf.download(ticker, start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="1d", progress=False)
            if isinstance(d_df.columns, pd.MultiIndex):
                d_df.columns = [col[0] for col in d_df.columns]
            row = d_df.iloc[0]
            entry_price = float(row['Open'])
            high_val = float(row['High'])
            low_val = float(row['Low'])
            close_val = float(row['Close'])
        except Exception:
            entry_price = op
            high_val = op
            low_val = op
            close_val = op
            
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
        "Exit Time": exit_time
    })
    print(f"[{date_str}] {ticker}: Return {ret*100:+.2f}% ({exit_type} @ {exit_time}). All-in: {old_all_in:.2f}->{capital_all_in:.2f} | 50%: {old_half:.2f}->{capital_half:.2f}")

# Save to Markdown report
md = f"# 📊 시작가 +200% 제한 및 30분 타임컷 청산 시초가 매수 시뮬레이션 결과\n\n"
md += f"**분석 기간**: 2026-06-08 ~ 2026-06-12 (지난 1주일)\n"
md += f"**선정 종목**: 매일 아침 09:30 기준 전체 시장 갭상승률 **2위 종목 단독 진입**\n"
md += f"**진입 필터**: 시초가 갭상승률 **+200% 미만일 때만 진입 (이상일 경우 거래 없음)**\n"
md += f"**청산 규칙**: 목표 익절 **+40.0%** / 손절 한도 **-20.0%** / **진입 30분 후인 10:00에 강제 타임컷 청산**\n\n"

md += f"## 🏆 최종 자금 결과\n"
md += f"| 구분 | 1. 전액 복리 All-in (100% 베팅) | 2. 50% 투자 + 50% 현금 예치 (50% 베팅) |\n"
md += f"| :--- | :---: | :---: |\n"
md += f"| **최종 자금** (100원 시작) | **{capital_all_in:.2f}원** | **{capital_half:.2f}원** |\n"
md += f"| **최종 누적 수익률** | **{((capital_all_in - 100)/100)*100:+.2f}%** | **{((capital_half - 100)/100)*100:+.2f}%** |\n\n"

md += f"## 📈 매일매일 종목 및 자금 흐름 상세 이력\n\n"
md += "| 날짜 | 종목명 | 갭상승률 | 당일 수익률 | All-in 자금 | 50% 베팅 자금 | 결과 유형 | 청산 시간 |\n"
md += "| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"

for r in log_entries:
    md += f"| {r['Date']} | {r['Ticker']} | {r['Gap']*100:+.2f}% | {r['Return']*100:+.2f}% | {r['New All-in']:.2f}원 | {r['New Half']:.2f}원 | {r['Type']} | {r['Exit Time']} |\n"

output_md_path = str(Path(__file__).resolve().parent.parent / "results" / "time_stop_results.md")
with open(output_md_path, "w", encoding="utf-8") as f:
    f.write(md)
print(f"Saved results to {output_md_path}")
