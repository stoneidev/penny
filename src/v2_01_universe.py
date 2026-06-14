"""US 보통주 유니버스 구축: NASDAQ + NYSE + AMEX, 보통주만."""
import urllib.request, json, pathlib

def fetch(exchange):
    url = (f'https://api.nasdaq.com/api/screener/stocks'
           f'?tableonly=true&limit=10000&exchange={exchange}')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())['data']['table']['rows']

all_rows = []
for ex in ['NASDAQ', 'NYSE', 'AMEX']:
    rows = fetch(ex)
    print(f'{ex}: {len(rows)}')
    for r in rows: r['_exchange'] = ex
    all_rows.extend(rows)

print(f'Total raw: {len(all_rows)}')

# 보통주 필터링: 종목명·심볼 패턴으로 ETF/우선주/워런트/SPAC 제외
def is_common_stock(row):
    sym = row['symbol'].strip()
    name = row.get('name','').lower()
    # 심볼 형식: ABC, ABC.A 정도만 허용
    if any(c in sym for c in ('^', '/', '$')): return False
    # 흔한 접미사
    if any(sym.endswith(s) for s in ('W','WS','U','R','P','PR','PRA','PRB','PRC','PRD','PRE')):
        # 단, 그냥 4글자 보통주들 (예: NVDA, AAPL, BIDU)는 살려야 함
        # 이걸 가르려면 심볼 길이 + 명칭 모두 확인
        if len(sym) <= 4 and not any(k in name for k in ('warrant','preferred','units','depositary','rights')):
            pass  # 보통주 가능성 — keep
        else:
            return False
    if any(k in name for k in ('warrant','preferred','units','depositary','etf',
                                'fund','trust','spac','rights','subordinat')):
        return False
    return True

common = [r for r in all_rows if is_common_stock(r)]
syms = sorted(set(r['symbol'].strip() for r in common))

# Relative path output
project_dir = pathlib.Path(__file__).resolve().parent.parent
output_path = project_dir / 'data' / 'universe_v2.txt'
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text('\n'.join(syms))

print(f'Common stock filtered: {len(syms)}')
print('Sample:', syms[:10])
print(f'Universe saved to {output_path}')
