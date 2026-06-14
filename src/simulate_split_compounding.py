from pathlib import Path
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# List of tickers and dates
ticker_dates = [
    ("GLXG", "2026-06-11"),
    ("GELS", "2026-06-11"),
    ("TGHL", "2026-06-11"),
    ("AHMA", "2026-06-09"),
    ("SLGB", "2026-06-09"),
    ("COCH", "2026-06-09"),
    ("GMHS", "2026-06-09"),
    ("NOTV", "2026-06-05"),
    ("RMSG", "2026-06-05"),
    ("TGHL", "2026-06-01"),
    ("ABTS", "2026-06-01"),
    ("GNTA", "2026-06-01")
]

def load_data(ticker, date_str):
    start_date = datetime.strptime(date_str, "%Y-%m-%d")
    end_date = start_date + timedelta(days=1)
    df = yf.download(ticker, start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"), interval="1m", progress=False)
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC').tz_convert('US/Eastern')
    else:
        df.index = df.index.tz_convert('US/Eastern')
    return df.between_time('09:30', '16:00')

print("Loading data...")
data_dict = {}
for ticker, date_str in ticker_dates:
    df = load_data(ticker, date_str)
    if df is not None:
        data_dict[(ticker, date_str)] = df

# Group tickers by date
days = sorted(list(set([d for t, d in ticker_dates])))

capital = 100.0
target_pct = 0.30
stop_pct = 0.15

trade_log = []

for date_str in days:
    day_tickers = [t for t, d in ticker_dates if d == date_str]
    
    # Sort tickers by opening volume (09:30) descending
    ticker_vols = []
    for ticker in day_tickers:
        df = data_dict.get((ticker, date_str))
        if df is not None and not df.empty:
            ticker_vols.append((ticker, df.iloc[0]['Volume']))
            
    # Select top 3 tickers by volume
    ticker_vols = sorted(ticker_vols, key=lambda x: x[1], reverse=True)
    selected_tickers = [t[0] for t in ticker_vols[:3]]
    
    if not selected_tickers:
        print(f"[{date_str}] No data available for any ticker.")
        continue
        
    num_splits = len(selected_tickers)
    returns = []
    positions_info = []
    
    for ticker in selected_tickers:
        df = data_dict[(ticker, date_str)]
        entry_price = df.iloc[0]['Open']
        target_price = entry_price * (1 + target_pct)
        stop_price = entry_price * (1 - stop_pct)
        
        exit_price = None
        exit_type = None
        exit_time = None
        
        for i in range(len(df)):
            current_time = df.index[i]
            row = df.iloc[i]
            
            # Check Stop Loss
            if row['Low'] <= stop_price:
                exit_price = stop_price
                exit_type = "SL"
                exit_time = current_time.strftime("%H:%M")
                break
                
            # Check Profit Target
            if row['High'] >= target_price:
                exit_price = target_price
                exit_type = "PT"
                exit_time = current_time.strftime("%H:%M")
                break
                
        if exit_price is None:
            exit_price = df.iloc[-1]['Close']
            exit_type = "EOD"
            exit_time = "16:00"
            
        ret = (exit_price - entry_price) / entry_price
        returns.append(ret)
        
        positions_info.append({
            "ticker": ticker,
            "vol": int(df.iloc[0]['Volume']),
            "ret": ret,
            "type": exit_type,
            "exit_time": exit_time
        })
        
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

# Print Results
print("\n=== 3-SPLIT CHRONOLOGICAL COMPOUNDING SIMULATION ===")
for t in trade_log:
    print(f"Date: {t['Date']} | Avg Day Return: {t['Avg Return']*100:+.2f}%")
    print(f"  Capital: {t['Old Capital']:.2f} ➡️ {t['New Capital']:.2f}")
    for p in t['Positions']:
        print(f"    - {p['ticker']} (Vol: {p['vol']:,}): Return {p['ret']*100:+.2f}% ({p['type']} @ {p['exit_time']})")
    print("-" * 50)
print(f"Final Capital: {capital:.2f}")

# Generate Markdown
markdown_content = "# 🛡️ 3분할 복리 적용 시초가 매수 전략 시뮬레이션 결과\n\n"
markdown_content += "자금을 **최대 3개 종목으로 분할(3-Split)**하여 분산 투자하고, 하루 마감 시점의 평균 수익률로 복리 계산한 결과입니다.\n\n"
markdown_content += "## ⚙️ 시뮬레이션 세팅\n"
markdown_content += "* **시작 자금**: 100원\n"
markdown_content += "* **진입 규칙**: 매일 아침 09:30 기준 **거래량이 가장 큰 상위 3개 종목**에 자금을 1/3씩 균등 분할 투자\n"
markdown_content += "* **청산 규칙**: 목표 익절 **+30%** / 손절 제한 **-15%** / 장마감(EOD) 청산\n\n"

markdown_content += "## 📊 일자별 매매 상세 이력\n\n"

for t in trade_log:
    markdown_content += f"### 📌 {t['Date']} (일일 평균 수익률: **{t['Avg Return']*100:+.2f}%**)\n"
    markdown_content += f"* **자금 변화**: {t['Old Capital']:.2f}원 ➡️ **{t['New Capital']:.2f}원**\n"
    markdown_content += "| 종목명 | 시초 거래량 | 결과 유형 | 수익률 | 비고 |\n"
    markdown_content += "| :---: | :---: | :---: | :---: | :--- |\n"
    for p in t['Positions']:
        markdown_content += f"| {p['ticker']} | {p['vol']:,} | {p['type']} | {p['ret']*100:+.2f}% | {p['exit_time']} 청산 |\n"
    markdown_content += "\n"

markdown_content += f"## 🏆 최종 자금 결과\n"
markdown_content += f"100원으로 시작한 자금은 3분할 분산 투자 후 최종 **{capital:.2f}원**이 되었습니다. (수익률: **{((capital - 100)/100)*100:+.2f}%**)\n"

output_path = str(Path(__file__).resolve().parent.parent / "results" / "split_compounding_results.md")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(markdown_content)
print(f"Saved results to {output_path}")
