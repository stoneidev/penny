"""손절선(SL)이 없는 시뮬레이션:
익절 타겟 +10%, +20%만 존재하고 손절은 설정하지 않음.
익절 미도달 시 10:00 AM에 무조건 강제 청산."""
import pandas as pd, yfinance as yf, sys, time, datetime as dt, pathlib
from zoneinfo import ZoneInfo
import numpy as np

ET = ZoneInfo('America/New_York')
TODAY = dt.date(2026, 6, 14)
ONE_MIN_CUTOFF = TODAY - dt.timedelta(days=29)

def main():
    project_dir = pathlib.Path(__file__).resolve().parent.parent
    picks_path = project_dir / 'data' / 'picks_v2.csv'
    picks = pd.read_csv(picks_path, parse_dates=['date'])

    # 1. 캐시 데이터 로드
    print("Downloading intraday data...")
    data_cache = {}
    for _, row in picks.iterrows():
        if row['no_trade']:
            continue
        d = row['date'].date()
        tkr = row['p2_ticker']
        interval = '1m' if d >= ONE_MIN_CUTOFF else '5m'
        
        bars = yf.download(tkr, start=d.strftime('%Y-%m-%d'),
                           end=(d + dt.timedelta(days=1)).strftime('%Y-%m-%d'),
                           interval=interval, auto_adjust=False, progress=False,
                           prepost=False, threads=False)
        if bars is None or bars.empty:
            if interval == '1m':
                bars = yf.download(tkr, start=d.strftime('%Y-%m-%d'),
                                   end=(d + dt.timedelta(days=1)).strftime('%Y-%m-%d'),
                                   interval='5m', auto_adjust=False, progress=False,
                                   prepost=False, threads=False)
                interval = '5m(fallback)'
        
        if bars is not None and not bars.empty:
            if isinstance(bars.columns, pd.MultiIndex):
                bars.columns = bars.columns.get_level_values(0)
            if bars.index.tz is None:
                bars.index = bars.index.tz_localize('UTC')
            bars.index = bars.index.tz_convert('America/New_York')
            rth_full = bars.between_time('09:30', '15:55')
            if not rth_full.empty:
                data_cache[(tkr, d.isoformat())] = (rth_full, interval)
        sys.stdout.write('.')
        sys.stdout.flush()
        time.sleep(0.1)
    print("\nData loaded. Running simulations...")

    tps = [0.10, 0.20]
    results = []

    for tp_pct in tps:
        trades = []
        for _, row in picks.iterrows():
            d = row['date'].date()
            d_str = d.isoformat()
            tkr = row['p2_ticker']
            gap = row['p2_gap']

            if row['no_trade']:
                trades.append({'action': 'SKIP', 'ret': 0.0, 'reason': 'FILTER'})
                continue

            cache_key = (tkr, d_str)
            if cache_key not in data_cache:
                trades.append({'action': 'NO_DATA', 'ret': 0.0, 'reason': 'NO_DATA'})
                continue

            rth_full, interval = data_cache[cache_key]
            entry = float(rth_full.iloc[0]['Open'])
            tp = entry * (1 + tp_pct)

            if interval.startswith('1m'):
                win = rth_full.between_time('09:30', '09:59')
            else:
                win = rth_full.between_time('09:30', '09:55')

            exit_price = exit_reason = None
            for ts, b in win.iterrows():
                hi = float(b['High'])
                if hi >= tp:
                    exit_price, exit_reason = tp, 'TP'; break
            
            if exit_price is None:
                exit_price = float(win.iloc[-1]['Close'])
                exit_reason = 'TIME(10:00)'

            ret = exit_price/entry - 1
            trades.append({
                'action': 'TRADE',
                'ret': ret,
                'reason': exit_reason
            })

        # Calculate compounding returns
        cap_full = 100.0
        cap_half = 100.0
        tp_hits = 0
        time_cuts = 0
        trade_count = 0
        ret_list = []

        for t in trades:
            if t['action'] != 'TRADE':
                continue
            trade_count += 1
            ret = t['ret']
            ret_list.append(ret)
            cap_full *= (1 + ret)
            cap_half *= (1 + 0.5 * ret)

            if t['reason'] == 'TP':
                tp_hits += 1
            elif t['reason'].startswith('TIME'):
                time_cuts += 1

        win_rate = (tp_hits / trade_count * 100) if trade_count > 0 else 0.0
        avg_ret = np.mean(ret_list) * 100 if len(ret_list) > 0 else 0.0

        results.append({
            'tp': f"+{int(tp_pct*100)}%",
            'win_rate': f"{win_rate:.1f}%",
            'tp_hits': tp_hits,
            'time_cuts': time_cuts,
            'avg_ret': f"{avg_ret:+.2f}%",
            'min_ret': f"{min(ret_list)*100:+.2f}%",
            'cap_full': f"{cap_full:.2f}원 ({cap_full-100:+.2f}%)",
            'cap_half': f"{cap_half:.2f}원 ({cap_half-100:+.2f}%)"
        })

    # Print markdown table
    print("\n| TP 수준 | 승률 (실거래) | TP 익절 | 손절(SL) | 타임컷 청산 | 평균 수익률 | 최대 당일손실 | 50% 베팅 자금 | 100% 베팅 자금 |")
    print("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in results:
        print(f"| {r['tp']} (No SL) | {r['win_rate']} | {r['tp_hits']}회 | 없음 | {r['time_cuts']}회 | {r['avg_ret']} | {r['min_ret']} | **{r['cap_half']}** | {r['cap_full']} |")

if __name__ == "__main__":
    main()
