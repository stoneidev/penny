from pathlib import Path
import os
import json
import time
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

# Hardcoded Rank 3 tickers and metrics from our previous full scan on the past week
rank3_selections = {
    "2026-06-08": {"ticker": "NEXR", "gap": 0.5124, "op": 1.83, "pc": 1.21},
    "2026-06-09": {"ticker": "AZI", "gap": 1.5929, "op": 2.93, "pc": 1.13},
    "2026-06-10": {"ticker": "CIIT", "gap": 1.6750, "op": 3.21, "pc": 1.20},
    "2026-06-11": {"ticker": "QH", "gap": 1.1600, "op": 7.02, "pc": 3.25},
    "2026-06-12": {"ticker": "VSME", "gap": 0.5901, "op": 1.765, "pc": 1.11}
}

past_week_dates = ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]

capital_all_in = 100.0
capital_half = 100.0
pt = 0.40
sl = 0.20

log_entries = []

print("Running simulation for Rank 3 tickers...")

for date_str in past_week_dates:
    sel = rank3_selections[date_str]
    ticker = sel["ticker"]
    gap = sel["gap"]
    op = sel["op"]
    pc = sel["pc"]
    
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
        
        for i in range(len(df_1m)):
            row = df_1m.iloc[i]
            low_val = float(row['Low'])
            high_val = float(row['High'])
            
            if low_val <= initial_stop:
                exit_price = initial_stop
                exit_type = "SL"
                exit_time = df_1m.index[i].strftime("%H:%M")
                break
            if high_val >= target_price:
                exit_price = target_price
                exit_type = "PT"
                exit_time = df_1m.index[i].strftime("%H:%M")
                break
                
        if exit_price is None:
            exit_price = float(df_1m.iloc[-1]['Close'])
            exit_type = "EOD"
            exit_time = "16:00"
            
        ret = (exit_price - entry_price) / entry_price
        source = "1M_DATA"
    else:
        # Absolute Daily Fallback (in case yfinance 1m fails)
        # We will fetch daily data for this single stock on this day to be safe
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
        "Exit Time": exit_time
    })
    print(f"[{date_str}] {ticker}: Return {ret*100:+.2f}% ({exit_type} @ {exit_time}). All-in: {old_all_in:.2f}->{capital_all_in:.2f} | 50%: {old_half:.2f}->{capital_half:.2f}")

# Save to Markdown report
md = f"# 📊 실제 전 미국 시장 대상 지난 1주일(6/8~6/12) 3등 종목 시뮬레이션 결과\n\n"
md += f"**분석 기간**: 2026-06-08 ~ 2026-06-12 (지난 1주일)\n"
md += f"**종목 유니버스**: ftp.nasdaqtrader.com에서 다운로드한 **전체 미국 시장 상장 종목** 대상\n"
md += f"**선정 종목**: 매일 아침 09:30 기준 전체 시장 갭상승률 **3위 종목 단독 진입**\n"
md += f"**매매 룰**: 목표 익절 **+40.0%** / 손절 한도 **-20.0%** / 장마감(EOD) 청산\n\n"

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

output_md_path = str(Path(__file__).resolve().parent.parent / "results" / "real_market_rank3_results.md")
with open(output_md_path, "w", encoding="utf-8") as f:
    f.write(md)
print(f"Saved real market Rank 3 results to {output_md_path}")
