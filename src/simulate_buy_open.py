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

def simulate_buy_open(df, target_pct=0.30, stop_pct=None):
    """
    Buy at Open Strategy:
    - Enter at Open price of first 1m candle (09:30)
    - Exit if price hits target_pct (+30%)
    - Exit if price hits stop_pct (if defined)
    - Otherwise exit at EOD
    """
    if df.empty:
        return None
        
    entry_price = df.iloc[0]['Open']
    target_price = entry_price * (1 + target_pct)
    stop_price = entry_price * (1 - stop_pct) if stop_pct is not None else None
    
    for i in range(len(df)):
        current_time = df.index[i]
        row = df.iloc[i]
        
        # Check Stop Loss first (worst case)
        if stop_price is not None and row['Low'] <= stop_price:
            return {"return": -stop_pct, "type": "SL", "exit_time": current_time.strftime("%H:%M")}
            
        # Check Profit Target
        if row['High'] >= target_price:
            return {"return": target_pct, "type": "PT", "exit_time": current_time.strftime("%H:%M")}
            
    # Exit at Close
    exit_price = df.iloc[-1]['Close']
    ret = (exit_price - entry_price) / entry_price
    return {"return": ret, "type": "EOD", "exit_time": "16:00"}

print("Loading data...")
data_dict = {}
for ticker, date_str in ticker_dates:
    df = load_data(ticker, date_str)
    if df is not None:
        data_dict[(ticker, date_str)] = df

# Test different stop loss settings
stop_settings = [None, 0.05, 0.10, 0.15] # No stop, -5%, -10%, -15%

results = []
for sl in stop_settings:
    trades = []
    for (ticker, date_str), df in data_dict.items():
        res = simulate_buy_open(df, target_pct=0.30, stop_pct=sl)
        if res:
            res["ticker"] = ticker
            res["date"] = date_str
            trades.append(res)
            
    returns = [t['return'] for t in trades]
    wins = [1 for t in trades if t['return'] > 0]
    win_rate = len(wins) / len(trades)
    avg_ret = np.mean(returns)
    g = sum([t['return'] for t in trades if t['return'] > 0])
    l = sum([-t['return'] for t in trades if t['return'] < 0])
    pf = g / l if l > 0 else float('inf')
    
    sl_label = f"-{sl*100:.1f}%" if sl is not None else "None (Hold to EOD)"
    results.append({
        "Stop Loss": sl_label,
        "Trades": len(trades),
        "Win Rate": f"{win_rate*100:.1f}%",
        "Avg Return": f"{avg_ret*100:+.2f}%",
        "Profit Factor": f"{pf:.2f}" if pf != float('inf') else "INF",
        "Details": trades
    })

res_df = pd.DataFrame(results)
print("\n=== BUY OPEN & SELL AT +30% SIMULATION ===")
print(res_df.drop(columns=["Details"]).to_string(index=False))
print("==========================================")

# Generate detailed stock breakdown for None and -10% stop loss
markdown_content = "# 🚀 시초가 매수 후 +30% 청산 전략 백테스트 결과\n\n"
markdown_content += "장이 열리자마자 시초가에 무조건 매수하여 +30% 수익 달성 시 청산하고, 달성하지 못하면 손절선 또는 장 마감 때 청산하는 화끈한 전략의 결과입니다.\n\n"

markdown_content += "## 📊 손절선 기준별 성과 비교\n\n"
markdown_content += "| 손절 조건 | 거래 횟수 | 승률 | 평균 수익률 | 손익비 (Profit Factor) |\n"
markdown_content += "| :--- | :---: | :---: | :---: | :---: |\n"
for r in results:
    markdown_content += f"| {r['Stop Loss']} | {r['Trades']}회 | {r['Win Rate']} | {r['Avg Return']} | {r['Profit Factor']} |\n"

# Details for No Stop Loss
markdown_content += "\n## 📝 상세 거래 분석 (손절선 없음 - 장마감 청산 기준)\n\n"
markdown_content += "| 종목명 (티커) | 날짜 | 진입가 (Open) | 최고가 (High) | 결과 가격 | 최종 수익률 | 유형 (PT/EOD) |\n"
markdown_content += "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |\n"

no_stop_details = results[0]["Details"]
for t in no_stop_details:
    ticker = t["ticker"]
    date_str = t["date"]
    # get actual prices from data
    df = data_dict[(ticker, date_str)]
    op = df.iloc[0]['Open']
    hi = df['High'].max()
    cl = df.iloc[-1]['Close']
    ex_price = op * 1.30 if t["type"] == "PT" else cl
    markdown_content += f"| **{ticker}** | {date_str} | ${op:.4f} | ${hi:.4f} | ${ex_price:.4f} | {t['return']*100:+.2f}% | {t['type']} ({t['exit_time']}) |\n"

output_path = str(Path(__file__).resolve().parent.parent / "results" / "buy_open_30pct_results.md")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(markdown_content)
print(f"Saved results to {output_path}")
