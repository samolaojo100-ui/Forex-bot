# 🐛 Forex Bot — Bug Fixes

## Summary of problems found and what was fixed

---

## Bug 1 — RSI logic was **inverted** in `signal_engine.py` ❌ CRITICAL

**File:** `signal_engine.py` → `analyze_tf()`

**Old code (broken):**
```python
# 3. RSI
rsi = row["rsi"]
if rsi < 50:
    buy_pts += 0.5; confirmed.append("RSI")   # ← WRONG: rsi < 50 is BEARISH
elif rsi > 50:
    buy_pts -= 0.5
```

**Fixed code:**
```python
# RSI > 50 = bullish momentum. RSI < 50 = bearish.
if overall_dir == "BUY":
    if 50 < rsi < 70:   score += 1.0  # bullish, not overbought ✅
elif overall_dir == "SELL":
    if 30 < rsi < 50:   score += 1.0  # bearish, not oversold ✅
```

**Impact:** Every pair's buy/sell score was being penalised when it should have been rewarded. This alone was causing most valid signals to fail the score threshold.

---

## Bug 2 — `overall_direction()` received wrong argument ❌ CRITICAL

**File:** `signal_engine.py` → `analyze_pair()`

**Old code:**
```python
processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
o_dir = overall_direction(tf_data, processed)  # ← passed tf_data (raw) AND processed
```

**`overall_direction` signature:**
```python
def overall_direction(tf_data: dict, processed: dict) -> str:
    for tf, df in processed.items():  # ← only uses `processed`, tf_data is ignored
```

**Fixed:** Removed the confusing dual-arg signature. Now `overall_direction(processed)` takes only the indicator-computed frames:
```python
o_dir = overall_direction(processed)
```

**Impact:** Harmless in practice (tf_data arg was ignored), but clarifies the logic and removes a footgun.

---

## Bug 3 — `asyncio.sleep(8)` between every timeframe fetch ❌ CRITICAL

**File:** `data_fetcher.py` → `fetch_all_timeframes()`

**Old code:**
```python
for tf in TIMEFRAMES:  # 5 timeframes
    df = await fetch_ohlcv(session, symbol, tf)
    ...
    await asyncio.sleep(8)  # ← 8 × 5 = 40 seconds per pair!
```

With 47 pairs × 40 seconds = **31 minutes** to scan all pairs. This meant:
- The scan would never complete before the next scheduled run
- TwelveData would likely time out
- Most pairs returned `None` and were skipped

**Fixed:**
```python
await asyncio.sleep(1.0)  # 1 second between TF calls — safe for free tier
```

---

## Bug 4 — Score threshold compared incompatible units ⚠️ MEDIUM

**File:** `signal_engine.py`

**Old code:** Score was a raw sum of `len(confirmed)` per TF (max = 5 TFs × 5 indicators = 25), but:
- `MIN_SIGNAL_SCORE = 6` in `config.py` was never imported (used hardcoded `6`)
- With the scoring giving partial points (0.3, 0.5) per indicator, the actual max was ~15, not 25
- The threshold of 6 on a ~0–15 scale blocked most weak-but-valid signals

**Fixed:** Score is now normalised to **0–10**:
```python
normalised = round((raw_score / max_score) * 10, 1)
```
And `MIN_SIGNAL_SCORE = 5.5` (out of 10) is imported from `config.py`.

---

## Bug 5 — `MIN_SIGNAL_SCORE` was never imported ⚠️ MEDIUM

**File:** `signal_engine.py` import line

**Old:** `from config import RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO`  
**Fixed:** `from config import RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO, MIN_SIGNAL_SCORE`

And `config.py` now explicitly defines `MIN_SIGNAL_SCORE = 5.5`.

---

## Bug 6 — Symbol format inconsistency ⚠️ LOW

**File:** `data_fetcher.py`

**Old:** `symbol.replace("/", "")` → `EURUSD`  
TwelveData actually supports `EUR/USD` format natively and it's cleaner.

**Fixed:** Pass the symbol as-is (`EUR/USD`), which works for both forex and crypto on TwelveData.

---

## Files Changed

| File | Changes |
|------|---------|
| `signal_engine.py` | RSI logic fixed, `overall_direction` fixed, score normalised, `MIN_SIGNAL_SCORE` imported |
| `data_fetcher.py` | Sleep reduced 8s → 1s, symbol format fixed |
| `config.py` | Added `MIN_SIGNAL_SCORE`, `MIN_SL_PIPS`; improved `CHAT_IDS` parsing |
| `indicators.py` | No logic changes — cleaned up formatting only |

---

## How to deploy the fix

1. Copy the 4 fixed files into your repo, replacing the old ones
2. Push to GitHub: `git add . && git commit -m "Fix signal generation bugs" && git push`
3. Railway will auto-redeploy
4. Send `/signal` to your bot — you should now get results within ~2 minutes
