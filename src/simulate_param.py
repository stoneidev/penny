"""정밀 시뮬레이션: 파라미터화 버전 (TP/SL 조절 가능).
1분봉(가능시) / 5분봉(폴백). TP/SL/10:00 타임컷."""
import pandas as pd, yfinance as yf, sys, time, datetime as dt, pathlib
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
TODAY = dt.date(2026, 6, 14)
ONE_MIN_CUTOFF = TODAY - dt.timedelta(days=29)

def run_backtest(tp_pct=0.40, sl_pct=0.20):
    project_dir = pathlib.Path(__file__).resolve().parent.parent
    picks_path = project_dir / 'data' / 'picks_v2.csv'
    picks = pd.read_csv(picks_path, parse_dates=['date'])

    trades = []
    print(f"Running simulation with TP = +{tp_pct*100:.1f}%, SL = -{sl_pct*100:.1f}%...")
    
    for _, row in picks.iterrows():
        d = row['date'].date()
        tkr = row['p2_ticker']
        gap = row['p2_gap']

        if row['no_trade']:
            trades.append({'date': d.isoformat(), 'ticker': tkr, 'gap': gap,
                           'action':'NO TRADE (gap>=200%)', 'ret': 0.0,
                           'reason': 'FILTER_SKIP', 'data': '-'})
            continue

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
            if bars is None or bars.empty:
                trades.append({'date': d.isoformat(), 'ticker': tkr, 'gap': gap,
                               'action':'NO DATA', 'ret': 0.0, 'reason': 'NO_DATA', 'data': 'none'})
                continue
        if isinstance(bars.columns, pd.MultiIndex):
            bars.columns = bars.columns.get_level_values(0)
        if bars.index.tz is None:
            bars.index = bars.index.tz_localize('UTC')
        bars.index = bars.index.tz_convert('America/New_York')

        rth_full = bars.between_time('09:30', '15:55')
        if rth_full.empty:
            trades.append({'date': d.isoformat(), 'ticker': tkr, 'gap': gap,
                           'action':'NO RTH', 'ret': 0.0, 'reason': 'NO_RTH', 'data': interval})
            continue

        entry = float(rth_full.iloc[0]['Open'])
        tp = entry * (1 + tp_pct)
        sl = entry * (1 - sl_pct)

        if interval.startswith('1m'):
            win = rth_full.between_time('09:30', '09:59')
        else:
            win = rth_full.between_time('09:30', '09:55')

        exit_price = exit_reason = exit_time = None
        for ts, b in win.iterrows():
            hi, lo = float(b['High']), float(b['Low'])
            hit_tp = hi >= tp
            hit_sl = lo <= sl
            if hit_tp and hit_sl:
                exit_price, exit_reason, exit_time = sl, 'SL(both)', ts; break
            if hit_tp:
                exit_price, exit_reason, exit_time = tp, 'TP', ts; break
            if hit_sl:
                exit_price, exit_reason, exit_time = sl, 'SL', ts; break
        if exit_price is None:
            exit_price = float(win.iloc[-1]['Close'])
            exit_reason = 'TIME(10:00)'
            exit_time = win.index[-1]

        ret = exit_price/entry - 1
        trades.append({
            'date': d.isoformat(),
            'ticker': tkr,
            'gap': round(gap, 4),
            'entry': round(entry, 4),
            'exit_price': round(exit_price, 4),
            'reason': exit_reason,
            'exit_time': str(exit_time)[:19],
            'ret': round(ret, 4),
            'action': 'TRADE',
            'data': interval,
        })
        sys.stdout.write('.'); sys.stdout.flush()
        time.sleep(0.1)

    print()
    df = pd.DataFrame(trades)
    
    # Calculate returns
    cap_full = 100.0
    cap_half = 100.0
    hist = []
    
    for _, r in df.iterrows():
        if r['action'] != 'TRADE':
            hist.append({
                'date': r['date'], 'ticker': r['ticker'], 'gap': r['gap'], 'reason': r['action'], 'ret': 0.0,
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
    traded = df[df['action'] == 'TRADE'].copy()
    traded['ret'] = traded['ret'].astype(float)
    
    print('\n=========== 요약 ===========')
    print(f'총 거래일수:  {len(df)}')
    print(f'실거래:       {len(traded)}')
    print(f'NO TRADE:    {(df["action"].str.startswith("NO TRADE")).sum()} (갭 +200% 이상)')
    print()
    print(f'승률 (실거래): {(traded["ret"]>0).mean():.1%}')
    print(f'TP hits:     {(traded["reason"]=="TP").sum()}')
    print(f'SL hits:     {traded["reason"].str.startswith("SL").sum()}')
    print(f'Time-cut:    {(traded["reason"]=="TIME(10:00)").sum()}')
    print(f'평균 수익률:   {traded["ret"].mean():+.2%}')
    print(f'최고/최저:    {traded["ret"].max():+.2%} / {traded["ret"].min():+.2%}')
    print()
    print(f'누적 (100% 베팅):  {cap_full-100:+.2f}원  →  {cap_full:.2f}원  ({cap_full/100-1:+.2%})')
    print(f'누적 (50% 베팅):   {cap_half-100:+.2f}원  →  {cap_half:.2f}원  ({cap_half/100-1:+.2%})')
    
    # Save the files
    df.to_csv(project_dir / 'data' / f'trades_v2_tp{int(tp_pct*100)}.csv', index=False)
    H.to_csv(project_dir / 'data' / f'equity_v2_tp{int(tp_pct*100)}.csv', index=False)
    print(f"Results saved to data/trades_v2_tp{int(tp_pct*100)}.csv and data/equity_v2_tp{int(tp_pct*100)}.csv")

if __name__ == "__main__":
    tp = 0.40
    sl = 0.20
    if len(sys.argv) > 1:
        tp = float(sys.argv[1])
    if len(sys.argv) > 2:
        sl = float(sys.argv[2])
    run_backtest(tp, sl)
