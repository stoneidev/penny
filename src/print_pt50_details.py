import os
import json
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

# Run simulation for PT = 50%, SL = 20%
pt_val = 0.50
sl_val = 0.20
gap_limit = 2.00

capital_all_in = 100.0
capital_half = 100.0
log_entries = []

for date_str in sorted_days:
    selections = daily_selections[date_str]
    if len(selections) < 2:
        continue
    ticker, gap, op, pc = selections[1]
    
    if gap >= gap_limit:
        log_entries.append({
            "Date": date_str, "Ticker": ticker, "Gap": gap, "Type": "SKIP", "Return": 0.0,
            "ExitTime": "N/A", "Cap_All": capital_all_in, "Cap_Half": capital_half, "Source": "FILTER"
        })
        continue
        
    cache = cached_series[(ticker, date_str)]
    df_1m = cache["df_1m"]
    daily_info = cache["daily_info"]
    
    if df_1m is not None and len(df_1m) > 0:
        entry_price = float(df_1m.iloc[0]['Open'])
        initial_stop = entry_price * (1 - sl_val)
        target_price = entry_price * (1 + pt_val)
        
        exit_price = None
        exit_type = None
        exit_time = None
        
        # Setup time stop limit (10:00 AM)
        start_time = df_1m.iloc[0]['timestamp'] if 'timestamp' in df_1m.columns else df_1m.index[0]
        start_time = pd.to_datetime(start_time)
        time_limit = start_time.replace(hour=10, minute=0, second=0)
        
        for i in range(len(df_1m)):
            row = df_1m.iloc[i]
            current_time = df_1m.iloc[i]['timestamp'] if 'timestamp' in df_1m.columns else df_1m.index[i]
            current_time = pd.to_datetime(current_time)
            
            if current_time > time_limit:
                exit_price = float(row['Open'])
                exit_type = "TIME"
                exit_time = "10:00"
                break
                
            low_val = float(row['Low'])
            high_val = float(row['High'])
            
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
            
        ret = (exit_price - entry_price) / entry_price
        source = "1M_DATA"
    else:
        # Fallback to daily
        entry_price = daily_info['Open']
        high_val = daily_info['High']
        low_val = daily_info['Low']
        close_val = daily_info['Close']
        initial_stop = entry_price * (1 - sl_val)
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
        ret = (exit_price - entry_price) / entry_price
        exit_time = "Intraday"
        source = "DAILY_FALLBACK"
        
    capital_all_in *= (1 + ret)
    capital_half *= (1 + 0.5 * ret)
    
    log_entries.append({
        "Date": date_str, "Ticker": ticker, "Gap": gap, "Type": exit_type, "Return": ret,
        "ExitTime": exit_time, "Cap_All": capital_all_in, "Cap_Half": capital_half, "Source": source
    })

# Write markdown report
active_trades = [item for item in log_entries if item["Type"] != "SKIP"]
win_count = sum(1 for item in active_trades if item["Return"] > 0)
loss_count = sum(1 for item in active_trades if item["Return"] < 0)
total_active = len(active_trades)
win_rate = (win_count / total_active * 100) if total_active > 0 else 0.0

# Calculate MDD
cap_history_all = [100.0]
cap_history_half = [100.0]
c_all = 100.0
c_half = 100.0
for item in log_entries:
    c_all *= (1 + item["Return"])
    c_half *= (1 + 0.5 * item["Return"])
    cap_history_all.append(c_all)
    cap_history_half.append(c_half)

mdd_all = 0.0
peak_all = 100.0
for v in cap_history_all:
    peak_all = max(peak_all, v)
    dd = (peak_all - v) / peak_all
    mdd_all = max(mdd_all, dd)

mdd_half = 0.0
peak_half = 100.0
for v in cap_history_half:
    peak_half = max(peak_half, v)
    dd = (peak_half - v) / peak_half
    mdd_half = max(mdd_half, dd)

report_content = f"""# 📊 갭상승 2위 종목 Fixed PT +50% / SL -20% / 30분 타임컷 상세 시뮬레이션 결과

**분석 기간**: 2026-05-01 ~ 2026-06-12 (30개 거래일)  
**선정 종목**: 매일 아침 09:30 기준 전체 시장 갭상승률 **2위 종목 단독 진입**  
**진입 필터**: 시초가 갭상승률 **+200% 미만일 때만 진입 (이상일 경우 거래 없음)**  
**청산 규칙**: 목표 익절 **+50.0%** / 손절 한도 **-20.0%** / **10:00 AM 강제 타임컷 청산**  
**시작 자금**: 100.0원

---

## 🏆 최종 자금 결과
| 구분 | 1. 전액 복리 All-in (100% 베팅) | 2. 50% 투자 + 50% 현금 예치 (50% 베팅) |
| :--- | :---: | :---: |
| **최종 자금** | **{c_all:.2f}원** | **{c_half:.2f}원** |
| **누적 수익률** | **+{c_all - 100:.2f}%** | **+{c_half - 100:.2f}%** |
| **최대 낙폭(MDD)** | **{mdd_all * 100:.2f}%** | **{mdd_half * 100:.2f}%** |
| **승률 (필터 스킵 제외)** | **{win_rate:.1f}%** ({win_count}승 {loss_count}패) | **{win_rate:.1f}%** ({win_count}승 {loss_count}패) |

---

## 📈 매일매일 종목 및 자금 흐름 상세 이력

| 날짜 | 종목명 | 갭상승률 | 당일 수익률 | All-in 자금 | 50% 베팅 자금 | 결과 유형 | 청산 시간 | 데이터 소스 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""

for item in log_entries:
    ret_pct = f"{item['Return']*100:+.2f}%" if item["Type"] != "SKIP" else "N/A"
    report_content += f"| {item['Date']} | {item['Ticker']} | {item['Gap']*100:+.2f}% | {ret_pct} | {item['Cap_All']:.2f}원 | {item['Cap_Half']:.2f}원 | {item['Type']} | {item['ExitTime']} | {item['Source']} |\n"

output_path = str(Path(__file__).resolve().parent.parent / "results" / "full_pt50_simulation_results.md")
with open(output_path, "w") as f:
    f.write(report_content)

print(f"Results saved to {output_path}")
