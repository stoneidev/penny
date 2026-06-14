"""정밀 시뮬: 1분봉(가능시) / 5분봉(폴백). TP/SL/10:00 타임컷.
TZ는 ET로 정확히 변환. 베팅 50%."""
import pandas as pd, yfinance as yf, sys, time, datetime as dt, pathlib
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
TODAY = dt.date(2026, 6, 14)
ONE_MIN_CUTOFF = TODAY - dt.timedelta(days=29)  # yfinance 1m 30-day window

project_dir = pathlib.Path(__file__).resolve().parent.parent
picks_path = project_dir / 'data' / 'picks_v2.csv'
picks = pd.read_csv(picks_path, parse_dates=['date'])

trades = []
for _, row in picks.iterrows():
    d = row['date'].date()
    tkr = row['p2_ticker']
    gap = row['p2_gap']

    if row['no_trade']:
        trades.append({'date': d.isoformat(), 'ticker': tkr, 'gap': gap,
                       'action':'NO TRADE (gap>=200%)', 'ret': 0.0,
                       'data': '-'})
        continue

    interval = '1m' if d >= ONE_MIN_CUTOFF else '5m'

    bars = yf.download(tkr, start=d.strftime('%Y-%m-%d'),
                       end=(d + dt.timedelta(days=1)).strftime('%Y-%m-%d'),
                       interval=interval, auto_adjust=False, progress=False,
                       prepost=False, threads=False)
    if bars is None or bars.empty:
        # 1m 실패 시 5m 시도
        if interval == '1m':
            bars = yf.download(tkr, start=d.strftime('%Y-%m-%d'),
                               end=(d + dt.timedelta(days=1)).strftime('%Y-%m-%d'),
                               interval='5m', auto_adjust=False, progress=False,
                               prepost=False, threads=False)
            interval = '5m(fallback)'
        if bars is None or bars.empty:
            trades.append({'date': d.isoformat(), 'ticker': tkr, 'gap': gap,
                           'action':'NO DATA', 'ret': 0.0, 'data': 'none'})
            continue
    if isinstance(bars.columns, pd.MultiIndex):
        bars.columns = bars.columns.get_level_values(0)
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize('UTC')
    bars.index = bars.index.tz_convert('America/New_York')

    rth_full = bars.between_time('09:30', '15:55')
    if rth_full.empty:
        trades.append({'date': d.isoformat(), 'ticker': tkr, 'gap': gap,
                       'action':'NO RTH', 'ret': 0.0, 'data': interval})
        continue

    entry = float(rth_full.iloc[0]['Open'])
    tp = entry * 1.5
    sl = entry * 0.8

    # 09:30:00 ~ 09:59:59 (1분봉이면 09:30~09:59 = 30개봉, 5분봉이면 09:30~09:55 = 6개봉)
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
            # 같은 봉 내 동시 도달 — 보수적: SL 먼저
            exit_price, exit_reason, exit_time = sl, 'SL(both)', ts; break
        if hit_tp:
            exit_price, exit_reason, exit_time = tp, 'TP', ts; break
        if hit_sl:
            exit_price, exit_reason, exit_time = sl, 'SL', ts; break
    if exit_price is None:
        # 10:00 시장가 청산 = 마지막 봉의 close
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
    time.sleep(0.15)

print()
df = pd.DataFrame(trades)
output_path = project_dir / 'data' / 'trades_v2.csv'
df.to_csv(output_path, index=False)
print(f'Trades saved to {output_path}')
