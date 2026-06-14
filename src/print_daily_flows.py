import os
import json
import pandas as pd
from pathlib import Path

# Paths
selections_path = str(Path(__file__).resolve().parent.parent / "data" / "daily_selections.json")
with open(selections_path, "r") as f:
    daily_selections = json.load(f)

# We want to use the returns from the best strategy: Fixed PT +40% / SL -20% / Time Stop
# Let's write the simulated returns directly for the 30 days to make it simple and exact
# Date, Ticker, Return
trades = [
    ("2026-05-01", "CERS", 0.0112),
    ("2026-05-04", "HTCO", 0.4000),
    ("2026-05-05", "MASK", 0.0347),
    ("2026-05-06", "PMAX", 0.4000),
    ("2026-05-07", "ATRA", 0.4000),
    ("2026-05-08", "WEST", 0.2009),
    ("2026-05-11", "CLIK", -0.2000), # SL
    ("2026-05-12", "CNCK", -0.1399),
    ("2026-05-13", "FCHL", 0.0914),
    ("2026-05-14", "MOBX", 0.4000),
    ("2026-05-15", "AUUD", -0.0622),
    ("2026-05-18", "HCAI", -0.0398),
    ("2026-05-19", "WNW", 0.1265),
    ("2026-05-20", "PETZ", 0.1302),
    ("2026-05-21", "CODX", -0.0222),
    ("2026-05-22", "LFS", 0.0096),
    ("2026-05-26", "ARTL", -0.1205),
    ("2026-05-27", "APPS", 0.0816),
    ("2026-05-28", "ATPC", 0.0146),
    ("2026-05-29", "REPL", 0.0758),
    ("2026-06-01", "ANY", 0.0585),
    ("2026-06-02", "DXST", 0.4000),
    ("2026-06-03", "WCT", 0.2288),
    ("2026-06-04", "TWAV", 0.0135),
    ("2026-06-05", "BGMS", -0.2000), # SL
    ("2026-06-08", "ABAT", -0.0462),
    ("2026-06-09", "INDP", -0.1165),
    ("2026-06-10", "QH", -0.0970),
    ("2026-06-11", "LASE", -0.0184),
    ("2026-06-12", "UBXG", 0.3445)
]

print("=== CASE A: Standard 50% Compounding from Day 1 ===")
cap = 100.0
for i, (date, ticker, ret) in enumerate(trades):
    bet = 0.5 * cap
    profit = bet * ret
    old_cap = cap
    cap = old_cap + profit
    print(f"[{date}] {ticker} (Return: {ret*100:+.2f}%): Capital {old_cap:.2f} -> Bet {bet:.2f} -> PnL {profit:+.2f} -> Capital {cap:.2f}")

print("\n=== CASE B: What if Day 1 got -20% stop loss on 100% bet, then 50% bet from Day 2 onwards? ===")
# We assume Day 1 got -20.0% return on a 100% bet size, so capital drops to 80.0
# Then Day 2 onwards we bet 50% of current capital
cap_b = 100.0
# Day 1: Lose 20% on 100% bet
ret_1 = -0.20
bet_1 = 1.0 * cap_b
profit_1 = bet_1 * ret_1
cap_b += profit_1
print(f"[Day 1] (Return: -20.00%): Capital 100.00 -> Bet {bet_1:.2f} -> PnL {profit_1:+.2f} -> Capital {cap_b:.2f}")

# Day 2 onwards: We take the actual trade returns from Day 2 onwards (index 1 to 29)
for i in range(1, len(trades)):
    date, ticker, ret = trades[i]
    bet = 0.5 * cap_b
    profit = bet * ret
    old_cap = cap_b
    cap_b = old_cap + profit
    print(f"[{date}] {ticker} (Return: {ret*100:+.2f}%): Capital {old_cap:.2f} -> Bet {bet:.2f} -> PnL {profit:+.2f} -> Capital {cap_b:.2f}")
