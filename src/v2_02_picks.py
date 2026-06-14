"""5197 종목의 일봉을 받아 매일 갭 2위(필터 적용) 선정."""
import pandas as pd, yfinance as yf, sys, time, pathlib

project_dir = pathlib.Path(__file__).resolve().parent.parent
tickers_path = project_dir / 'data' / 'universe_v2.txt'
tickers = tickers_path.read_text().splitlines()
print(f'Universe: {len(tickers)}')

START = '2026-04-29'
END   = '2026-06-13'

CHUNK = 200
frames = []
for i in range(0, len(tickers), CHUNK):
    batch = tickers[i:i+CHUNK]
    sys.stdout.write(f'  batch {i//CHUNK+1}/{(len(tickers)+CHUNK-1)//CHUNK}... ')
    sys.stdout.flush()
    try:
        df = yf.download(batch, start=START, end=END, interval='1d',
                         auto_adjust=False, progress=False, threads=True,
                         group_by='ticker')
    except Exception as e:
        print('ERR', e); continue
    if isinstance(df.columns, pd.MultiIndex):
        for t in batch:
            if t not in df.columns.get_level_values(0): continue
            sub = df[t][['Open','High','Low','Close','Volume']].dropna(how='all').copy()
            if sub.empty: continue
            sub['ticker'] = t
            frames.append(sub)
    print(f'ok')
    time.sleep(0.3)

big = pd.concat(frames).reset_index().rename(columns={'Date':'date'})
big.columns = [c.lower() for c in big.columns]
big = big.sort_values(['ticker','date'])
big['prev_close']  = big.groupby('ticker')['close'].shift(1)
big['prev_volume'] = big.groupby('ticker')['volume'].shift(1)
big['prev_turnover'] = big['prev_close'] * big['prev_volume']
big['gap'] = big['open']/big['prev_close'] - 1

big = big[(big['date'] >= '2026-05-01') & (big['date'] <= '2026-06-12')].copy()

# 필터
filt = big[
    (big['open'] >= 1.0) & (big['open'] <= 10.0) &
    (big['prev_turnover'] >= 50_000) &
    big['gap'].notna()
].copy()

# 매일 갭 1·2위
picks = []
for d, day in filt.groupby('date'):
    ranked = day.sort_values('gap', ascending=False)
    if len(ranked) < 2: continue
    p1, p2 = ranked.iloc[0], ranked.iloc[1]
    picks.append({
        'date': d.strftime('%Y-%m-%d'),
        'p1_ticker': p1['ticker'], 'p1_gap': round(p1['gap'],4),
        'p2_ticker': p2['ticker'], 'p2_gap': round(p2['gap'],4),
        'p2_open': round(p2['open'],4),
        'p2_prev_close': round(p2['prev_close'],4),
        'p2_prev_turnover': int(p2['prev_turnover']),
        'no_trade': p2['gap'] >= 2.0,
    })

out = pd.DataFrame(picks)
output_path = project_dir / 'data' / 'picks_v2.csv'
out.to_csv(output_path, index=False)
print(f'\nDays: {len(out)}, No-trade: {out["no_trade"].sum()}')
print(out.to_string(index=False))
print(f'Picks saved to {output_path}')
