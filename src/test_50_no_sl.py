"""손절선(SL)이 없는 +50% 익절 전략 시뮬레이션:
익절 타겟 +50%만 존재하고 손절은 설정하지 않음.
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
    print("\nData loaded. Running simulation...")

    trades = []
    tp_pct = 0.50

    for _, row in picks.iterrows():
        d = row['date'].date()
        d_str = d.isoformat()
        tkr = row['p2_ticker']
        gap = row['p2_gap']

        if row['no_trade']:
            trades.append({'date': d_str, 'ticker': tkr, 'gap': gap, 'action': 'SKIP', 'ret': 0.0, 'reason': 'FILTER'})
            continue

        cache_key = (tkr, d_str)
        if cache_key not in data_cache:
            trades.append({'date': d_str, 'ticker': tkr, 'gap': gap, 'action': 'NO_DATA', 'ret': 0.0, 'reason': 'NO_DATA'})
            continue

        rth_full, interval = data_cache[cache_key]
        entry = float(rth_full.iloc[0]['Open'])
        tp = entry * (1 + tp_pct)

        if interval.startswith('1m'):
            win = rth_full.between_time('09:30', '09:59')
        else:
            win = rth_full.between_time('09:30', '09:55')

        exit_price = exit_reason = exit_time = None
        for ts, b in win.iterrows():
            hi = float(b['High'])
            if hi >= tp:
                exit_price, exit_reason, exit_time = tp, 'TP', ts; break
        
        if exit_price is None:
            exit_price = float(win.iloc[-1]['Close'])
            exit_reason = 'TIME(10:00)'
            exit_time = win.index[-1]

        ret = exit_price/entry - 1
        trades.append({
            'date': d_str,
            'ticker': tkr,
            'gap': gap,
            'entry': entry,
            'exit_price': exit_price,
            'reason': exit_reason,
            'exit_time': str(exit_time)[:19],
            'ret': ret,
            'action': 'TRADE'
        })

    # Calculate compounding returns
    df = pd.DataFrame(trades)
    cap_full = 100.0
    cap_half = 100.0
    hist = []
    
    for _, r in df.iterrows():
        if r['action'] != 'TRADE':
            hist.append({
                'date': r['date'], 'ticker': r['ticker'], 'gap': r['gap'], 'reason': r['reason'], 'ret': 0.0,
                'cap_full': round(cap_full, 2), 'cap_half': round(cap_half, 2)
            })
            continue
        ret = float(r['ret'])
        cap_full *= (1 + ret)
        cap_half *= (1 + 0.5 * ret)
        hist.append({
            'date': r['date'], 'ticker': r['ticker'], 'gap': r['gap'], 'reason': r['reason'], 'ret': ret,
            'cap_full': round(cap_full, 2), 'cap_half': round(cap_half, 2)
        })

    H = pd.DataFrame(hist)
    print(H.to_string(index=False))

    traded = df[df['action'] == 'TRADE'].copy()
    traded['ret'] = traded['ret'].astype(float)

    print('\n=========== TP +50% / No SL 요약 ===========')
    print(f'총 거래일수:  {len(df)}')
    print(f'실거래:       {len(traded)}')
    print(f'NO TRADE:    {(df["action"].str.startswith("SKIP")).sum()}')
    print()
    print(f'승률 (실거래): {(traded["ret"]>0).mean():.1%}')
    print(f'TP hits:     {(traded["reason"]=="TP").sum()}')
    print(f'Time-cut:    {traded["reason"].str.startswith("TIME").sum()}')
    print(f'평균 수익률:   {traded["ret"].mean():+.2%}')
    print(f'최고/최저:    {traded["ret"].max():+.2%} / {traded["ret"].min():+.2%}')
    print()
    print(f'누적 (100% 베팅):  {cap_full-100:+.2f}원  →  {cap_full:.2f}원  ({cap_full/100-1:+.2%})')
    print(f'누적 (50% 베팅):   {cap_half-100:+.2f}원  →  {cap_half:.2f}원  ({cap_half/100-1:+.2%})')

if __name__ == "__main__":
    main()
