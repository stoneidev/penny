from pathlib import Path
import os
import json
import time
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

# Load daily selections
selections_path = str(Path(__file__).resolve().parent.parent / "data" / "daily_selections.json")
with open(selections_path, "r") as f:
    daily_selections = json.load(f)

print(f"Loaded selections for {len(daily_selections)} days.")

capital = 100.0
target_pct = 0.30
stop_pct = 0.15

trade_log = []
daily_returns_summary = []

# Loop through days chronologically
sorted_days = sorted(list(daily_selections.keys()))

for date_str in sorted_days:
    selections = daily_selections[date_str]
    # selections is a list of [ticker, gap, open_price, prev_close]
    
    returns = []
    positions_info = []
    
    print(f"Processing {date_str} (Capital: {capital:.2f})...")
    
    for ticker, gap, op, pc in selections:
        # Download 1-minute data for the day
        start_date = datetime.strptime(date_str, "%Y-%m-%d")
        end_date = start_date + timedelta(days=1)
        
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        
        # Download data
        df = None
        for attempt in range(3):
            try:
                df = yf.download(ticker, start=start_str, end=end_str, interval="1m", progress=False)
                if not df.empty:
                    break
            except Exception as e:
                time.sleep(0.5)
        
        if df is None or df.empty:
            print(f"  --> [NO DATA] {ticker} on {date_str}. Using 0% return.")
            returns.append(0.0)
            positions_info.append({
                "ticker": ticker,
                "gap": gap,
                "ret": 0.0,
                "type": "NO_DATA",
                "exit_time": "N/A"
            })
            continue
            
        # Flatten MultiIndex if exists
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
            
        # Ensure Eastern timezone
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC').tz_convert('US/Eastern')
        else:
            df.index = df.index.tz_convert('US/Eastern')
            
        df = df.between_time('09:30', '16:00')
        
        if len(df) == 0:
            print(f"  --> [EMPTY RTH] {ticker} on {date_str}. Using 0% return.")
            returns.append(0.0)
            positions_info.append({
                "ticker": ticker,
                "gap": gap,
                "ret": 0.0,
                "type": "EMPTY_RTH",
                "exit_time": "N/A"
            })
            continue
            
        entry_price = float(df.iloc[0]['Open'])
        target_price = entry_price * (1 + target_pct)
        stop_price = entry_price * (1 - stop_pct)
        
        exit_price = None
        exit_type = None
        exit_time = None
        
        for i in range(len(df)):
            current_time = df.index[i]
            row = df.iloc[i]
            low_val = float(row['Low'])
            high_val = float(row['High'])
            
            # Check Stop Loss first (worst case)
            if low_val <= stop_price:
                exit_price = stop_price
                exit_type = "SL"
                exit_time = current_time.strftime("%H:%M")
                break
                
            # Check Profit Target
            if high_val >= target_price:
                exit_price = target_price
                exit_type = "PT"
                exit_time = current_time.strftime("%H:%M")
                break
                
        if exit_price is None:
            exit_price = float(df.iloc[-1]['Close'])
            exit_type = "EOD"
            exit_time = "16:00"
            
        ret = (exit_price - entry_price) / entry_price
        returns.append(ret)
        
        positions_info.append({
            "ticker": ticker,
            "gap": gap,
            "ret": ret,
            "type": exit_type,
            "exit_time": exit_time
        })
        print(f"  - {ticker}: Gap {gap*100:+.2f}%, Return {ret*100:+.2f}% ({exit_type} @ {exit_time})")
        
        # Polite delay to prevent rate limits
        time.sleep(0.1)
        
    if not returns:
        day_avg_return = 0.0
    else:
        day_avg_return = np.mean(returns)
        
    old_capital = capital
    capital = capital * (1 + day_avg_return)
    
    trade_log.append({
        "Date": date_str,
        "Positions": positions_info,
        "Avg Return": day_avg_return,
        "Old Capital": old_capital,
        "New Capital": capital
    })
    print(f"==> Day Return: {day_avg_return*100:+.2f}%. Capital: {old_capital:.2f} -> {capital:.2f}\n")

# Print overall summary
print("\n=== OVERALL SIMULATION SUMMARY ===")
print(f"Start Capital: 100.00")
print(f"End Capital:   {capital:.2f}")
print(f"Total Return:  {((capital - 100)/100)*100:+.2f}%")

# Generate report markdown
md = f"# 📊 시초가 갭상승 종목 3분할 복리 시뮬레이션 결과\n\n"
md += f"**분석 기간**: 2026-05-01 ~ 2026-06-12 (저번주 금요일)\n\n"
md += f"## ⚙️ 시뮬레이션 규칙 설정\n"
md += f"* **시작 자금**: 100원 (복리 적용)\n"
md += f"* **종목 선정**: 매일 아침 장시작(09:30) 기준 **전일 종가 대비 갭상승률이 가장 큰 상위 3개 종목**에 자금을 1/3씩 균등 분할 투자\n"
md += f"  * *유니버스*: 650개 역사적 페니/급등 주식 대상\n"
md += f"  * *필터*: 시초가 $1.00 이상 $10.00 이하, 전일 거래대금 $50,000 이상 (거래가 마이너한 잡주 배제)\n"
md += f"* **청산 규칙**: 목표 익절 **+30%** / 손절 제한 **-15%** / 미도달 시 16:00 장마감(EOD) 청산\n\n"

md += f"## 🏆 최종 자금 결과\n"
md += f"* **최종 자금**: **{capital:.2f}원** (수익률: **{((capital - 100)/100)*100:+.2f}%**)\n\n"

md += f"## 📊 일자별 매매 상세 이력\n\n"
for t in trade_log:
    md += f"### 📌 {t['Date']} (일일 평균 수익률: **{t['Avg Return']*100:+.2f}%**)\n"
    md += f"* **자금 변화**: {t['Old Capital']:.2f}원 ➡️ **{t['New Capital']:.2f}원**\n"
    md += f"| 종목명 | 갭상승률 | 결과 유형 | 수익률 | 비고 |\n"
    md += f"| :---: | :---: | :---: | :---: | :--- |\n"
    for p in t['Positions']:
        md += f"| {p['ticker']} | {p['gap']*100:+.2f}% | {p['type']} | {p['ret']*100:+.2f}% | {p['exit_time']} 청산 |\n"
    md += "\n"

output_md_path = str(Path(__file__).resolve().parent.parent / "results" / "gap_gainer_results.md")
with open(output_md_path, "w", encoding="utf-8") as f:
    f.write(md)
print(f"Saved results to {output_md_path}")
