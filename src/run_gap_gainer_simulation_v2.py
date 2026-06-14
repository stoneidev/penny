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

print(f"Loaded selections for {len(daily_selections)} days.")

# 1. Load daily data for fallback and checking
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

capital = 100.0
target_pct = 0.30
stop_pct = 0.15

trade_log = []
sorted_days = sorted(list(daily_selections.keys()))

for date_str in sorted_days:
    selections = daily_selections[date_str]
    returns = []
    positions_info = []
    
    print(f"Processing {date_str} (Capital: {capital:.2f})...")
    current_date = pd.Timestamp(date_str)
    
    for ticker, gap, op, pc in selections:
        # Try loading 1-minute data from local JSON cache first
        df_1m = load_minute_from_json(ticker, date_str)
        source = "JSON_CACHE"
        
        # If not in local JSON cache and within 30 days, try yfinance 1m
        if df_1m is None:
            # Check if date is within 30 days of today (June 14, 2026)
            days_ago = (datetime(2026, 6, 14) - datetime.strptime(date_str, "%Y-%m-%d")).days
            if days_ago <= 28:
                start_dt = datetime.strptime(date_str, "%Y-%m-%d")
                end_dt = start_dt + timedelta(days=1)
                try:
                    df_1m = yf.download(ticker, start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="1m", progress=False)
                    if not df_1m.empty:
                        source = "YFINANCE_1M"
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
            # We have 1-minute data
            entry_price = float(df_1m.iloc[0]['Open'])
            target_price = entry_price * (1 + target_pct)
            stop_price = entry_price * (1 - stop_pct)
            
            exit_price = None
            exit_type = None
            exit_time = None
            
            for i in range(len(df_1m)):
                row = df_1m.iloc[i]
                if 'timestamp' in df_1m.columns:
                    current_time = row['timestamp']
                else:
                    current_time = df_1m.iloc[i]['timestamp'] if 'timestamp' in df_1m.columns else df_1m.index[i]
            current_time = pd.to_datetime(current_time)
                
                try:
                    exit_time_str = pd.to_datetime(current_time).strftime("%H:%M")
                except Exception:
                    exit_time_str = "Intraday"
                    
                low_val = float(row['Low'])
                high_val = float(row['High'])
                
                # Check Stop Loss first (worst case)
                if low_val <= stop_price:
                    exit_price = stop_price
                    exit_type = "SL"
                    exit_time = exit_time_str
                    break
                    
                # Check Profit Target
                if high_val >= target_price:
                    exit_price = target_price
                    exit_type = "PT"
                    exit_time = exit_time_str
                    break
                    
            if exit_price is None:
                exit_price = float(df_1m.iloc[-1]['Close'])
                exit_type = "EOD"
                exit_time = "16:00"
                
            ret = (exit_price - entry_price) / entry_price
        else:
            # Fall back to daily data (conservative worst case)
            source = "DAILY_FALLBACK"
            try:
                ticker_df = daily_data[ticker]
                day_row = ticker_df.loc[current_date]
                entry_price = float(day_row['Open'])
                high_val = float(day_row['High'])
                low_val = float(day_row['Low'])
                close_val = float(day_row['Close'])
                
                target_price = entry_price * (1 + target_pct)
                stop_price = entry_price * (1 - stop_pct)
                
                # Conservative logic: if it hit both, assume SL was hit
                if low_val <= stop_price:
                    exit_price = stop_price
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
            except Exception as e:
                # Absolute fallback if daily download failed
                print(f"    [WARN] No daily data for {ticker} on {date_str}. Using 0% return.")
                ret = 0.0
                exit_type = "ERROR"
                exit_time = "N/A"
                entry_price = op
                
        returns.append(ret)
        positions_info.append({
            "ticker": ticker,
            "gap": gap,
            "ret": ret,
            "type": exit_type,
            "exit_time": exit_time,
            "source": source
        })
        print(f"  - {ticker}: Gap {gap*100:+.2f}%, Return {ret*100:+.2f}% ({exit_type} @ {exit_time}, Source: {source})")
        
    day_avg_return = np.mean(returns) if returns else 0.0
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
md += f"* **청산 규칙**: 목표 익절 **+30%** / 손절 제한 **-15%** / 미도달 시 16:00 장마감(EOD) 청산\n"
md += f"  * *보수적 백테스트*: 1분봉 데이터가 없을 경우 일봉 데이터로 대체하며, 당일 고가(+30%)와 저가(-15%) 조건에 모두 해당되면 **손절(-15%) 처리**하는 보수적 방식을 적용했습니다.\n\n"

md += f"## 🏆 최종 자금 결과\n"
md += f"* **최종 자금**: **{capital:.2f}원** (수익률: **{((capital - 100)/100)*100:+.2f}%**)\n\n"

md += f"## 📊 일자별 매매 상세 이력\n\n"
for t in trade_log:
    md += f"### 📌 {t['Date']} (일일 평균 수익률: **{t['Avg Return']*100:+.2f}%**)\n"
    md += f"* **자금 변화**: {t['Old Capital']:.2f}원 ➡️ **{t['New Capital']:.2f}원**\n"
    md += "| 종목명 | 갭상승률 | 결과 유형 | 수익률 | 데이터 소스 | 비고 |\n"
    md += "| :---: | :---: | :---: | :---: | :---: | :--- |\n"
    for p in t['Positions']:
        md += f"| {p['ticker']} | {p['gap']*100:+.2f}% | {p['type']} | {p['ret']*100:+.2f}% | {p['source']} | {p['exit_time']} 청산 |\n"
    md += "\n"

output_md_path = str(Path(__file__).resolve().parent.parent / "results" / "gap_gainer_results.md")
with open(output_md_path, "w", encoding="utf-8") as f:
    f.write(md)
print(f"Saved results to {output_md_path}")
