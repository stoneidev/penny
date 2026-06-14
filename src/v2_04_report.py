"""베팅 50% & 100% 두 가지로 누적 수익률 보고."""
import pandas as pd, pathlib

project_dir = pathlib.Path(__file__).resolve().parent.parent
trades_path = project_dir / 'data' / 'trades_v2.csv'
df = pd.read_csv(trades_path)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)

# 자본 흐름
cap_full = 100.0     # 전액 베팅
cap_half = 100.0     # 50%만 투자
hist = []
for _, r in df.iterrows():
    if r['action'].startswith('NO TRADE'):
        # 거래 없음 — 자본 변화 없음
        hist.append({'date': r['date'].date(), 'ticker': r['ticker'],
                     'gap': r['gap'], 'reason': r['action'], 'ret': 0.0,
                     'cap_full': round(cap_full,2), 'cap_half': round(cap_half,2),
                     'data': r['data']})
        continue
    if r['action'] != 'TRADE':
        hist.append({'date': r['date'].date(), 'ticker': r['ticker'],
                     'gap': r['gap'], 'reason': r['action'], 'ret': 0.0,
                     'cap_full': round(cap_full,2), 'cap_half': round(cap_half,2),
                     'data': r['data']})
        continue
    ret = float(r['ret'])
    cap_full *= (1 + ret)
    cap_half *= (1 + 0.5*ret)   # 50% 베팅
    hist.append({'date': r['date'].date(), 'ticker': r['ticker'],
                 'gap': round(r['gap'],4),
                 'entry': r['entry'], 'reason': r['reason'],
                 'ret': round(ret,4),
                 'cap_full': round(cap_full,2),
                 'cap_half': round(cap_half,2),
                 'data': r['data']})

H = pd.DataFrame(hist)
print(H.to_string(index=False))

traded = df[df['action'] == 'TRADE'].copy()
traded['ret'] = traded['ret'].astype(float)

print('\n=========== 요약 ===========')
print(f'총 거래일수:  {len(df)}')
print(f'실거래:       {len(traded)}')
print(f'NO TRADE:    {(df["action"].str.startswith("NO TRADE")).sum()} (갭 +200% 이상)')
print(f'NO DATA:     {(df["action"]=="NO DATA").sum()}')
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

# 데이터 신뢰도
print('\n데이터 분포:')
print(df['data'].value_counts())

output_path = project_dir / 'data' / 'equity_v2.csv'
H.to_csv(output_path, index=False)
print(f'Equity curve saved to {output_path}')
