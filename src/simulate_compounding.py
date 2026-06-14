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

# Group tickers by date to simulate day-by-day trading
days = sorted(list(set([d for t, d in ticker_dates])))

capital = 100.0
target_pct = 0.30
stop_pct = 0.15

trade_log = []

for date_str in days:
    # Get all tickers available on this day
    day_tickers = [t for t, d in ticker_dates if d == date_str]
    
    # Select the ticker with the highest volume in the first minute (09:30)
    selected_ticker = None
    max_opening_volume = -1
    
    for ticker in day_tickers:
        df = data_dict.get((ticker, date_str))
        if df is not None and not df.empty:
            opening_vol = df.iloc[0]['Volume']
            if opening_vol > max_opening_volume:
                max_opening_volume = opening_vol
                selected_ticker = ticker
                
    if selected_ticker is None:
        print(f"[{date_str}] No data available for any ticker.")
        continue
        
    df = data_dict[(selected_ticker, date_str)]
    entry_price = df.iloc[0]['Open']
    target_price = entry_price * (1 + target_pct)
    stop_price = entry_price * (1 - stop_pct)
    
    # Run trade simulation
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
        # Exit at Close
        exit_price = df.iloc[-1]['Close']
        exit_type = "EOD"
        exit_time = "16:00"
        
    ret = (exit_price - entry_price) / entry_price
    old_capital = capital
    capital = capital * (1 + ret)
    
    trade_log.append({
        "Date": date_str,
        "Ticker": selected_ticker,
        "Opening Vol": int(max_opening_volume),
        "Entry Time": "09:30",
        "Entry Price": entry_price,
        "Exit Time": exit_time,
        "Exit Price": exit_price,
        "Type": exit_type,
        "Return": ret,
        "Old Capital": old_capital,
        "New Capital": capital
    })

# Print step-by-step simulation
print("\n=== CHRONOLOGICAL COMPOUNDING SIMULATION ===")
for t in trade_log:
    print(f"Date: {t['Date']} | Ticker: {t['Ticker']} (Vol: {t['Opening Vol']:,})")
    print(f"  Entry: {t['Entry Time']} @ ${t['Entry Price']:.4f}")
    print(f"  Exit:  {t['Exit Time']} @ ${t['Exit Price']:.4f} ({t['Type']})")
    print(f"  Return: {t['Return']*100:+.2f}% | Capital: {t['Old Capital']:.2f} ➡️ {t['New Capital']:.2f}")
    print("-" * 50)
print(f"Final Capital: {capital:.2f}")

# Generate Markdown file
markdown_content = "# 📈 복리 적용 시초가 매수 전략 시뮬레이션 결과 (미래데이터 차단)\n\n"
markdown_content += "장이 열리는 시점(09:30)에 거래량이 가장 많이 터진 종목을 선택하여 **전액(All-in) 복리 투자**를 진행한 결과입니다.\n\n"
markdown_content += "## ⚙️ 시뮬레이션 세팅\n"
markdown_content += "* **시작 자금**: 100원\n"
markdown_content += "* **진입 규칙**: 매일 아침 09:30분 기준 **첫 1분봉 거래량이 가장 큰 종목**에 100% 진입 (미래데이터 배제)\n"
markdown_content += "* **청산 규칙**: 목표 익절 **+30%** / 손절 제한 **-15%** / 장마감(EOD) 청산\n\n"

markdown_content += "## 📊 일자별 매매 상세 이력\n\n"
markdown_content += "| 일자 | 종목명 | 시초 거래량 | 진입가 | 청산 시간 | 청산가 | 결과 유형 | 수익률 | 자금 변화 |\n"
markdown_content += "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"

for t in trade_log:
    markdown_content += f"| {t['Date']} | **{t['Ticker']}** | {t['Opening Vol']:,} | ${t['Entry Price']:.4f} | {t['Exit Time']} | ${t['Exit Price']:.4f} | {t['Type']} | {t['Return']*100:+.2f}% | {t['Old Capital']:.2f}원 ➡️ **{t['New Capital']:.2f}원** |\n"

markdown_content += f"\n## 🏆 최종 자금 결과\n"
markdown_content += f"100원으로 시작한 자금은 4일간의 거래 후 최종 **{capital:.2f}원**이 되었습니다. (수익률: **{((capital - 100)/100)*100:+.2f}%**)\n"

output_path = str(Path(__file__).resolve().parent.parent / "results" / "compounding_results.md")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(markdown_content)
print(f"Saved compounding results to {output_path}")
