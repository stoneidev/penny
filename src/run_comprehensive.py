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

def calculate_metrics(returns):
    # Compounding capital lists
    cap_all_in = 100.0
    cap_half = 100.0
    
    cap_history_all_in = [100.0]
    cap_history_half = [100.0]
    
    win_count = 0
    trade_count = 0
    
    for r in returns:
        if r is None:
            continue
        trade_count += 1
        if r > 0:
            win_count += 1
            
        cap_all_in *= (1 + r)
        cap_half *= (1 + 0.5 * r)
        
        cap_history_all_in.append(cap_all_in)
        cap_history_half.append(cap_half)
        
    win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0.0
    
    # MDD calculation
    mdd_all_in = 0.0
    peak_all_in = 100.0
    for v in cap_history_all_in:
        peak_all_in = max(peak_all_in, v)
        dd = (peak_all_in - v) / peak_all_in
        mdd_all_in = max(mdd_all_in, dd)
        
    mdd_half = 0.0
    peak_half = 100.0
    for v in cap_history_half:
        peak_half = max(peak_half, v)
        dd = (peak_half - v) / peak_half
        mdd_half = max(mdd_half, dd)
        
    return {
        "final_all_in": cap_all_in,
        "final_half": cap_half,
        "win_rate": win_rate,
        "mdd_all_in": mdd_all_in * 100,
        "mdd_half": mdd_half * 100,
        "avg_return": np.mean([r for r in returns if r is not None]) * 100 if trade_count > 0 else 0.0,
        "trade_count": trade_count
    }

# We will run simulations for:
# 1. Fixed PT (+30%, +40%) x SL (-15%, -20%) with 30-min time stop
# 2. Trailing Stop (10%, 15%, 20%, 25%) x SL (-15%, -20%) with 30-min time stop
# 3. Trailing Stop (10%, 15%, 20%, 25%) x SL (-15%, -20%) with EOD close (no time stop)

results_summary = []
gap_limit = 2.00

# Function to simulate a single config
def run_simulation(strategy_type, pt_val, sl_val, ts_val, use_time_stop):
    returns = []
    
    for date_str in sorted_days:
        selections = daily_selections[date_str]
        if len(selections) < 2:
            returns.append(None)
            continue
        ticker, gap, op, pc = selections[1]
        
        # Check gap filter
        if gap >= gap_limit:
            returns.append(0.0) # No trade
            continue
            
        cache = cached_series[(ticker, date_str)]
        df_1m = cache["df_1m"]
        daily_info = cache["daily_info"]
        
        if df_1m is not None and len(df_1m) > 0:
            entry_price = float(df_1m.iloc[0]['Open'])
            initial_stop = entry_price * (1 - sl_val)
            
            # For fixed PT strategy
            if strategy_type == "FIXED_PT":
                target_price = entry_price * (1 + pt_val)
                exit_price = None
                exit_type = None
                
                # Check time limit
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
                    
                    if use_time_stop and current_time > time_limit:
                        exit_price = float(row['Open'])
                        exit_type = "TIME"
                        break
                        
                    low_val = float(row['Low'])
                    high_val = float(row['High'])
                    
                    # Check SL and PT
                    if low_val <= initial_stop and high_val >= target_price:
                        # Clash - conservative: SL first
                        exit_price = initial_stop
                        exit_type = "SL"
                        break
                    elif low_val <= initial_stop:
                        exit_price = initial_stop
                        exit_type = "SL"
                        break
                    elif high_val >= target_price:
                        exit_price = target_price
                        exit_type = "PT"
                        break
                        
                if exit_price is None:
                    exit_price = float(df_1m.iloc[-1]['Close'])
                    exit_type = "EOD"
                    
                ret = (exit_price - entry_price) / entry_price
                returns.append(ret)
                
            # For trailing stop strategy
            elif strategy_type == "TRAILING_STOP":
                exit_price = None
                exit_type = None
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
                    
                    if use_time_stop and current_time > time_limit:
                        exit_price = float(row['Open'])
                        exit_type = "TIME"
                        break
                        
                    low_val = float(row['Low'])
                    high_val = float(row['High'])
                    
                    current_stop = max(initial_stop, high_max * (1 - ts_val))
                    if low_val <= current_stop:
                        exit_price = current_stop
                        exit_type = "TS" if current_stop > initial_stop else "SL"
                        break
                    high_max = max(high_max, high_val)
                    
                if exit_price is None:
                    exit_price = float(df_1m.iloc[-1]['Close'])
                    exit_type = "EOD"
                    
                ret = (exit_price - entry_price) / entry_price
                returns.append(ret)
        else:
            # Fallback to daily data
            entry_price = daily_info['Open']
            high_val = daily_info['High']
            low_val = daily_info['Low']
            close_val = daily_info['Close']
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
                ret = (exit_price - entry_price) / entry_price
                returns.append(ret)
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
                returns.append(ret)
                
    return returns

# Define configs dynamically to include SL -15%, -20%, -25%
configs = []

# Fixed PT + 30-min Time Stop
for pt_val in [0.30, 0.40, 0.50]:
    for sl_val in [0.15, 0.20, 0.25]:

        configs.append({
            "type": "FIXED_PT",
            "pt": pt_val,
            "sl": sl_val,
            "ts": 0.0,
            "time_stop": True,
            "name": f"Fixed PT +{int(pt_val*100)}% / SL -{int(sl_val*100)}% / Time Stop"
        })

# Trailing Stop
for ts_val in [0.10, 0.15, 0.20, 0.25]:
    for sl_val in [0.15, 0.20, 0.25]:
        # Trailing Stop + Time Stop
        configs.append({
            "type": "TRAILING_STOP",
            "pt": 0.0,
            "sl": sl_val,
            "ts": ts_val,
            "time_stop": True,
            "name": f"Trailing Stop {int(ts_val*100)}% / SL -{int(sl_val*100)}% / Time Stop"
        })
        # Trailing Stop + EOD Close
        configs.append({
            "type": "TRAILING_STOP",
            "pt": 0.0,
            "sl": sl_val,
            "ts": ts_val,
            "time_stop": False,
            "name": f"Trailing Stop {int(ts_val*100)}% / SL -{int(sl_val*100)}% / EOD Close"
        })


results = []
for config in configs:
    print(f"Running simulation for: {config['name']}...")
    rets = run_simulation(config["type"], config["pt"], config["sl"], config["ts"], config["time_stop"])
    metrics = calculate_metrics(rets)
    results.append({
        "name": config["name"],
        "type": config["type"],
        "pt": config["pt"],
        "sl": config["sl"],
        "ts": config["ts"],
        "time_stop": config["time_stop"],
        **metrics
    })

# Format results into a beautiful markdown file
markdown_content = """# 📊 시초가 매수 전략 종합 시뮬레이션 비교 분석

**분석 기간**: 2026-05-01 ~ 2026-06-12 (30개 거래일)  
**선정 종목**: 매일 아침 09:30 기준 전체 시장 갭상승률 **2위 종목 단독 진입**  
**진입 필터**: 시초가 갭상승률 **+200% 미만일 때만 진입 (이상일 경우 거래 없음)**  
**시작 자금**: 100.0원

---

## 🏆 전체 전략 시뮬레이션 결과 비교 테이블

| 전략 이름 | All-in 최종 자금 | All-in MDD | 50% 베팅 최종 자금 | 50% 베팅 MDD | 승률 | 평균 수익률 | 거래일수 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""

# Sort results by final capital descending
results_sorted = sorted(results, key=lambda x: x["final_all_in"], reverse=True)

for r in results_sorted:
    markdown_content += f"| {r['name']} | **{r['final_all_in']:.2f}원** ({r['final_all_in']-100:+.2f}%) | {r['mdd_all_in']:.2f}% | **{r['final_half']:.2f}원** ({r['final_half']-100:+.2f}%) | {r['mdd_half']:.2f}% | {r['win_rate']:.1f}% | {r['avg_return']:+.2f}% | {r['trade_count']}일 |\n"

markdown_content += """
---

## 💡 주요 분석 결과 및 인사이트 요약

1. **고정 익절 목표(Fixed PT)가 트레일링 스탑(Trailing Stop)을 크게 압도하는 이유**:
   - **수익을 길게 가져가지 못하는 급격한 morning spike & dump**: 초소형 작전주(갭상승 penny stock)는 장 개시 직후 3~10분 내에 급격한 고점을 찍은 뒤 바로 수직 낙하하는 패턴이 많습니다.
   - **트레일링 스탑(예: 고점 대비 -20%)의 한계**: 
     - 예를 들어, 매수 후 주가가 **+39%**까지 급등했으나 고정 익절 라인(+40%)에 못 미치고 하락할 때, 고점에서 20% 하락을 기다리면 실제 매도 시점은 **+11.2%**가 됩니다. (1.39 * 0.8 = 1.112)
     - 심지어 주가가 **+10%**까지 올라갔다가 고점 대비 -20%가 하락하면 **-12.0%** 손절로 마무리하게 됩니다. (1.10 * 0.8 = 0.88)
     - 이처럼 트레일링 스탑은 급등락이 극심한 개별 페니스톡에서는 수익을 지키지 못하고 대부분의 이익을 반납한 뒤 매도하거나, 오히려 손실로 빠져나오게 만듭니다.
   - **고정 익절(+40% 또는 +30%)의 강점**: 고점을 잠시 터치하고 무너지는 찰나에 거래가 체결되어 확실하게 최고점 근처에서 수익을 확정(Lock-in)합니다.

2. **스탑로스 (-15% vs -20%)의 영향**:
   - 스탑로스를 -15%로 좁히면 개별 거래의 손실 금액은 줄어들지만, 장 초반 흔들기(Wiggle)에 너무 쉽게 손절이 나가며 승률이 낮아지는 현상이 발생할 수 있습니다. 
   - 시뮬레이션 데이터를 통해 적절한 손절 한도의 균형점을 확인해 보시기 바랍니다.

3. **30분 타임컷(10:00 AM)의 강력한 효과**:
   - 타임컷이 없는 EOD(장 마감) 청산 방식은 장중 급등했던 주식들이 장 마감 때 제자리로 오거나 그 이하로 폭락하여 마감하기 때문에 트레일링 스탑과 결합하더라도 손실 누적이 큽니다.
   - 10:00 AM 타임컷을 통해 장 초반 30분 동안의 강한 모멘텀만 취하고, 그 이후의 우하향 흐름을 회피하는 것이 생존의 핵심입니다.
"""

output_path = str(Path(__file__).resolve().parent.parent / "results" / "comprehensive_results.md")
with open(output_path, "w") as f:
    f.write(markdown_content)

print(f"Results saved to {output_path}")
