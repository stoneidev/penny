"""2위, 3위 종목 포트폴리오 시뮬레이션:
매일 아침 09:30 시초가 기준 갭상승률 전체 2위 및 3위 종목 동시 진입.
진입 필터: 각 종목의 갭상승률 < +100% (이상일 경우 해당 종목 제외).
자본 배분: 당일 진입 가능한 종목 수(1개 혹은 2개)로 투자 비중 균등 분할.
TP +50% / SL -20% / 10:00 AM 타임컷 청산."""
import pandas as pd, yfinance as yf, sys, time, datetime as dt, pathlib
from zoneinfo import ZoneInfo
import numpy as np

ET = ZoneInfo('America/New_York')
TODAY = dt.date(2026, 6, 14)
ONE_MIN_CUTOFF = TODAY - dt.timedelta(days=29)

def main():
    project_dir = pathlib.Path(__file__).resolve().parent.parent
    picks_path = project_dir / 'data' / 'picks_v3.csv'
    picks = pd.read_csv(picks_path, parse_dates=['date'])

    # 1. 시뮬레이션에 필요한 모든 종목-일자 다운로드 목록 작성
    download_targets = []
    for _, row in picks.iterrows():
        d_str = row['date'].strftime('%Y-%m-%d')
        
        # Rank 2
        if row['p2_gap'] < 1.00:
            download_targets.append((row['p2_ticker'], d_str))
        # Rank 3
        if row['p3_gap'] < 1.00:
            download_targets.append((row['p3_ticker'], d_str))
            
    unique_targets = list(set(download_targets))
    print(f"Total unique (Ticker, Date) pairs to download: {len(unique_targets)}")

    # 2. 캐시 데이터 로드
    print("Downloading intraday data...")
    data_cache = {}
    for i, (tkr, d_str) in enumerate(unique_targets):
        d = dt.datetime.strptime(d_str, '%Y-%m-%d').date()
        interval = '1m' if d >= ONE_MIN_CUTOFF else '5m'
        
        bars = yf.download(tkr, start=d_str,
                           end=(d + dt.timedelta(days=1)).strftime('%Y-%m-%d'),
                           interval=interval, auto_adjust=False, progress=False,
                           prepost=False, threads=False)
        if bars is None or bars.empty:
            if interval == '1m':
                bars = yf.download(tkr, start=d_str,
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
                data_cache[(tkr, d_str)] = (rth_full, interval)
        sys.stdout.write('.')
        sys.stdout.flush()
        time.sleep(0.1)
    print("\nData loaded. Running simulation...")

    daily_trade_logs = []
    tp_pct = 0.50
    sl_pct = 0.20

    for _, row in picks.iterrows():
        d_str = row['date'].strftime('%Y-%m-%d')
        
        # 진입 가능한 후보 선별 (갭 < 100%)
        active_candidates = []
        if row['p2_gap'] < 1.00:
            active_candidates.append(('Rank2', row['p2_ticker'], row['p2_gap']))
        if row['p3_gap'] < 1.00:
            active_candidates.append(('Rank3', row['p3_ticker'], row['p3_gap']))

        if not active_candidates:
            daily_trade_logs.append({
                'date': d_str,
                'trades_count': 0,
                'tickers': '-',
                'returns': '-',
                'combined_ret': 0.0,
                'reason': 'FILTER_SKIP'
            })
            continue

        # 개별 종목 매매 실행
        day_rets = []
        exit_reasons = []
        traded_tickers = []
        
        for rank_label, tkr, gap in active_candidates:
            cache_key = (tkr, d_str)
            if cache_key not in data_cache:
                continue
                
            rth_full, interval = data_cache[cache_key]
            entry = float(rth_full.iloc[0]['Open'])
            tp = entry * (1 + tp_pct)
            sl = entry * (1 - sl_pct)

            if interval.startswith('1m'):
                win = rth_full.between_time('09:30', '09:59')
            else:
                win = rth_full.between_time('09:30', '09:55')

            exit_price = exit_reason = None
            for ts, b in win.iterrows():
                hi, lo = float(b['High']), float(b['Low'])
                hit_tp = hi >= tp
                hit_sl = lo <= sl
                if hit_tp and hit_sl:
                    exit_price, exit_reason = sl, 'SL(both)'; break
                if hit_tp:
                    exit_price, exit_reason = tp, 'TP'; break
                if hit_sl:
                    exit_price, exit_reason = sl, 'SL'; break
            
            if exit_price is None:
                exit_price = float(win.iloc[-1]['Close'])
                exit_reason = 'TIME(10:00)'

            ret = exit_price/entry - 1
            day_rets.append(ret)
            exit_reasons.append(f"{tkr}:{exit_reason}")
            traded_tickers.append(f"{tkr}({rank_label})")

        if not day_rets:
            daily_trade_logs.append({
                'date': d_str,
                'trades_count': 0,
                'tickers': '-',
                'returns': '-',
                'combined_ret': 0.0,
                'reason': 'NO_DATA'
            })
            continue

        # 균등 분할 수익률 계산 (포트폴리오 수익률)
        combined_ret = np.mean(day_rets)
        
        daily_trade_logs.append({
            'date': d_str,
            'trades_count': len(day_rets),
            'tickers': ', '.join(traded_tickers),
            'returns': ', '.join([f"{r*100:+.2f}%" for r in day_rets]),
            'combined_ret': combined_ret,
            'reason': ', '.join(exit_reasons)
        })

    # 복리 자금 흐름 계산
    df = pd.DataFrame(daily_trade_logs)
    cap_full = 100.0
    cap_half = 100.0
    hist = []
    
    for _, r in df.iterrows():
        ret = r['combined_ret']
        cap_full *= (1 + ret)
        cap_half *= (1 + 0.5 * ret)
        hist.append({
            'date': r['date'],
            'tickers': r['tickers'],
            'returns': r['returns'],
            'combined_ret': f"{ret*100:+.2f}%" if r['trades_count'] > 0 else '-',
            'reason': r['reason'],
            'cap_full': round(cap_full, 2),
            'cap_half': round(cap_half, 2)
        })

    H = pd.DataFrame(hist)
    print(H.to_string(index=False))

    # MDD 계산
    cap_history_all = H['cap_full'].tolist()
    cap_history_half = H['cap_half'].tolist()
    
    mdd_all = 0.0
    peak_all = 100.0
    for v in cap_history_all:
        peak_all = max(peak_all, v)
        dd = (peak_all - v) / peak_all
        mdd_all = max(mdd_all, dd)
        
    mdd_half = 0.0
    peak_half = 100.0
    for v in cap_history_half:
        peak_half = max(peak_half, v)
        dd = (peak_half - v) / peak_half
        mdd_half = max(mdd_half, dd)

    # 전체 통계 분석
    all_trade_rets = []
    total_trades = 0
    tp_hits = 0
    sl_hits = 0
    time_cuts = 0
    
    # 각 종목별 세부 성과 집계
    for log in daily_trade_logs:
        if log['trades_count'] == 0:
            continue
        reasons = log['reason'].split(', ')
        for rs in reasons:
            total_trades += 1
            if 'TP' in rs:
                tp_hits += 1
            elif 'SL' in rs:
                sl_hits += 1
            elif 'TIME' in rs:
                time_cuts += 1

    print('\n=========== 2위 & 3위 포트폴리오 (갭 < 100%) 요약 ===========')
    print(f'총 거래일수:      {len(df)}')
    print(f'총 진입 종목수:    {total_trades}개')
    print(f'NO TRADE 일수:    {sum(1 for x in daily_trade_logs if x["trades_count"] == 0)}일')
    print()
    print(f'개별 거래 승률:    {(tp_hits / total_trades * 100):.1f}% (익절 {tp_hits}회 / 손절 {sl_hits}회 / 타임컷 {time_cuts}회)')
    print(f'최대 낙폭(All-in MDD):   {mdd_all*100:.2f}%')
    print(f'최대 낙폭(50% Bet MDD):  {mdd_half*100:.2f}%')
    print()
    print(f'누적 (100% 베팅):  {cap_full-100:+.2f}원  →  {cap_full:.2f}원  ({cap_full/100-1:+.2%})')
    print(f'누적 (50% 베팅):   {cap_half-100:+.2f}원  →  {cap_half:.2f}원  ({cap_half/100-1:+.2%})')

if __name__ == "__main__":
    main()
