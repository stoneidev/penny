from pathlib import Path
import os
import json
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

# Ticker Rank 2 selections from June 8 to June 12, 2026
rank2_selections = {
    "2026-06-08": {"ticker": "GMHS", "gap": 0.5708, "op": 1.63, "pc": 1.04},
    "2026-06-09": {"ticker": "CHAI", "gap": 3.3537, "op": 3.31, "pc": 0.76},
    "2026-06-10": {"ticker": "VSME", "gap": 3.4957, "op": 3.48, "pc": 0.77},
    "2026-06-11": {"ticker": "GLXG", "gap": 1.6127, "op": 1.75, "pc": 0.67},
    "2026-06-12": {"ticker": "DSY", "gap": 0.7732, "op": 1.88, "pc": 1.06}
}

past_week_dates = ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]

# Download 1m data for the past week
cached_1m = {}
for date_str in past_week_dates:
    sel = rank2_selections[date_str]
    ticker = sel["ticker"]
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)
    
    print(f"Downloading 1-minute data for {ticker} on {date_str}...")
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
            cached_1m[(ticker, date_str)] = df_1m
            print(f"Successfully loaded {len(df_1m)} rows.")
        else:
            cached_1m[(ticker, date_str)] = None
            print("No data returned.")
    except Exception as e:
        cached_1m[(ticker, date_str)] = None
        print(f"Failed to download: {e}")

def run_simulation(strategy_type, pt_val, sl_val, ts_val, use_time_stop, use_gap_filter):
    capital_all_in = 100.0
    capital_half = 100.0
    
    log = []
    
    for date_str in past_week_dates:
        sel = rank2_selections[date_str]
        ticker = sel["ticker"]
        gap = sel["gap"]
        
        # 1. Apply gap filter if active
        if use_gap_filter and gap >= 2.00:
            log.append({
                "Date": date_str, "Ticker": ticker, "Gap": gap, "Type": "SKIP", "Return": 0.0,
                "Cap_All": capital_all_in, "Cap_Half": capital_half, "ExitTime": "N/A"
            })
            continue
            
        df_1m = cached_1m.get((ticker, date_str))
        
        if df_1m is not None and len(df_1m) > 0:
            entry_price = float(df_1m.iloc[0]['Open'])
            initial_stop = entry_price * (1 - sl_val)
            
            exit_price = None
            exit_type = None
            exit_time = None
            
            # Setup time stop limit (10:00 AM)
            start_time = pd.to_datetime(df_1m.index[0])
            time_limit = start_time.replace(hour=10, minute=0, second=0)
            
            if strategy_type == "FIXED_PT":
                target_price = entry_price * (1 + pt_val)
                for i in range(len(df_1m)):
                    row = df_1m.iloc[i]
                    current_time = df_1m.iloc[i]['timestamp'] if 'timestamp' in df_1m.columns else df_1m.index[i]
            current_time = pd.to_datetime(current_time)
                    
                    if use_time_stop and current_time > time_limit:
                        exit_price = float(row['Open'])
                        exit_type = "TIME"
                        exit_time = "10:00"
                        break
                        
                    low_val = float(row['Low'])
                    high_val = float(row['High'])
                    
                    # Check SL and PT
                    if low_val <= initial_stop and high_val >= target_price:
                        exit_price = initial_stop
                        exit_type = "SL"
                        exit_time = current_time.strftime("%H:%M")
                        break
                    elif low_val <= initial_stop:
                        exit_price = initial_stop
                        exit_type = "SL"
                        exit_time = current_time.strftime("%H:%M")
                        break
                    elif high_val >= target_price:
                        exit_price = target_price
                        exit_type = "PT"
                        exit_time = current_time.strftime("%H:%M")
                        break
                        
                if exit_price is None:
                    exit_price = float(df_1m.iloc[-1]['Close'])
                    exit_type = "EOD"
                    exit_time = "16:00"
                    
            elif strategy_type == "TRAILING_STOP":
                high_max = entry_price
                for i in range(len(df_1m)):
                    row = df_1m.iloc[i]
                    current_time = df_1m.iloc[i]['timestamp'] if 'timestamp' in df_1m.columns else df_1m.index[i]
            current_time = pd.to_datetime(current_time)
                    
                    if use_time_stop and current_time > time_limit:
                        exit_price = float(row['Open'])
                        exit_type = "TIME"
                        exit_time = "10:00"
                        break
                        
                    low_val = float(row['Low'])
                    high_val = float(row['High'])
                    
                    current_stop = max(initial_stop, high_max * (1 - ts_val))
                    if low_val <= current_stop:
                        exit_price = current_stop
                        exit_type = "TS" if current_stop > initial_stop else "SL"
                        exit_time = current_time.strftime("%H:%M")
                        break
                    high_max = max(high_max, high_val)
                    
                if exit_price is None:
                    exit_price = float(df_1m.iloc[-1]['Close'])
                    exit_type = "EOD"
                    exit_time = "16:00"
            
            ret = (exit_price - entry_price) / entry_price
        else:
            # Daily data fallback (worst-case assumption)
            # Fetch daily data
            try:
                start_dt = datetime.strptime(date_str, "%Y-%m-%d")
                end_dt = start_dt + timedelta(days=1)
                d_df = yf.download(ticker, start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="1d", progress=False)
                row = d_df.iloc[0]
                entry_price = float(row['Open'])
                high_val = float(row['High'])
                low_val = float(row['Low'])
                close_val = float(row['Close'])
            except Exception:
                entry_price = sel["op"]
                high_val = sel["op"]
                low_val = sel["op"]
                close_val = sel["op"]
                
            initial_stop = entry_price * (1 - sl_val)
            
            if strategy_type == "FIXED_PT":
                target_price = entry_price * (1 + pt_val)
                if low_val <= initial_stop:
                    exit_price = initial_stop
                    exit_type = "SL"
                elif high_val >= target_price:
                    exit_price = target_price
                    exit_type = "PT"
                else:
                    exit_price = close_val
                    exit_type = "EOD"
            elif strategy_type == "TRAILING_STOP":
                trailing_stop = high_val * (1 - ts_val)
                if low_val <= initial_stop:
                    exit_price = initial_stop
                    exit_type = "SL"
                elif low_val <= trailing_stop:
                    exit_price = trailing_stop
                    exit_type = "TS"
                else:
                    exit_price = close_val
                    exit_type = "EOD"
            ret = (exit_price - entry_price) / entry_price
            exit_time = "Daily Fallback"
            
        capital_all_in *= (1 + ret)
        capital_half *= (1 + 0.5 * ret)
        
        log.append({
            "Date": date_str, "Ticker": ticker, "Gap": gap, "Type": exit_type, "Return": ret,
            "Cap_All": capital_all_in, "Cap_Half": capital_half, "ExitTime": exit_time
        })
        
    return capital_all_in, capital_half, log

# We will test configurations:
# 1. PT +40%, SL -20%, Time Stop, With Gap Filter
# 2. PT +40%, SL -20%, Time Stop, No Gap Filter (What was run before, wait - before was EOD close. Let's compare with Time Stop and No Gap Filter)
# 3. PT +30%, SL -20%, Time Stop, With Gap Filter
# 4. Trailing Stop 20%, SL -20%, Time Stop, With Gap Filter
# 5. Trailing Stop 10%, SL -20%, Time Stop, With Gap Filter
# 6. Trailing Stop 20%, SL -20%, EOD Close, No Gap Filter (This was Option A in full_trailing_stop_comparison.md)

configs = [
    {"type": "FIXED_PT", "pt": 0.40, "sl": 0.20, "ts": 0.0, "time_stop": True, "gap_filter": True, "name": "Fixed PT +40% / SL -20% / Time Stop / Gap Filter < 200%"},
    {"type": "FIXED_PT", "pt": 0.40, "sl": 0.20, "ts": 0.0, "time_stop": True, "gap_filter": False, "name": "Fixed PT +40% / SL -20% / Time Stop / No Gap Filter"},
    {"type": "FIXED_PT", "pt": 0.30, "sl": 0.20, "ts": 0.0, "time_stop": True, "gap_filter": True, "name": "Fixed PT +30% / SL -20% / Time Stop / Gap Filter < 200%"},
    {"type": "TRAILING_STOP", "pt": 0.0, "sl": 0.20, "ts": 0.20, "time_stop": True, "gap_filter": True, "name": "Trailing Stop 20% / SL -20% / Time Stop / Gap Filter < 200%"},
    {"type": "TRAILING_STOP", "pt": 0.0, "sl": 0.20, "ts": 0.10, "time_stop": True, "gap_filter": True, "name": "Trailing Stop 10% / SL -20% / Time Stop / Gap Filter < 200%"},
    {"type": "TRAILING_STOP", "pt": 0.0, "sl": 0.20, "ts": 0.20, "time_stop": False, "gap_filter": False, "name": "Trailing Stop 20% / SL -20% / EOD Close / No Gap Filter"},
]

results = []
for config in configs:
    all_in, half, log = run_simulation(config["type"], config["pt"], config["sl"], config["ts"], config["time_stop"], config["gap_filter"])
    results.append({
        "name": config["name"],
        "all_in": all_in,
        "half": half,
        "log": log
    })

# Format the output report
report = """# 📊 지난 1주일 (6/8 ~ 6/12) 2등 종목 필터 및 전략 시뮬레이션 결과

**분석 기간**: 2026-06-08 ~ 2026-06-12 (5개 거래일)  
**선정 종목**: 매일 아침 09:30 기준 전체 시장 갭상승률 **2위 종목 단독 진입**  
**시작 자금**: 100.0원

---

## 🏆 각 전략별 최종 자금 비교

| 전략 이름 | All-in 최종 자금 | 50% 베팅 최종 자금 | 실제 진입 종목 일수 |
| :--- | :---: | :---: | :---: |
"""

for r in results:
    trade_days = sum(1 for item in r["log"] if item["Type"] != "SKIP")
    report += f"| {r['name']} | **{r['all_in']:.2f}원** ({r['all_in']-100:+.2f}%) | **{r['half']:.2f}원** ({r['half']-100:+.2f}%) | {trade_days}일 |\n"

report += "\n---\n\n## 📈 상세 거래 이력 및 자금 흐름 비교\n\n"

for r in results:
    report += f"### 🔍 {r['name']}\n\n"
    report += "| 날짜 | 종목명 | 갭상승률 | 체결 유형 | 당일 수익률 | All-in 잔고 | 50% 베팅 잔고 | 청산 시간 |\n"
    report += "| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
    
    for item in r["log"]:
        ret_pct = f"{item['Return']*100:+.2f}%" if item["Type"] != "SKIP" else "N/A"
        report += f"| {item['Date']} | {item['Ticker']} | {item['Gap']*100:+.2f}% | {item['Type']} | {ret_pct} | {item['Cap_All']:.2f}원 | {item['Cap_Half']:.2f}원 | {item['ExitTime']} |\n"
    report += "\n"

output_path = str(Path(__file__).resolve().parent.parent / "results" / "past_week_comprehensive_results.md")
with open(output_path, "w") as f:
    f.write(report)

print(f"Saved results to {output_path}")
