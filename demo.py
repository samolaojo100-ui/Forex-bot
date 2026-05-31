from datetime import datetime, timezone
from signal_engine import Signal

DEMO_PAIRS = [
    ("BTC/USD", "BUY",  67842.00, 66100.00, 71326.00, 8.4, "HIGH",   "CRYPTO"),
    ("ETH/USD", "BUY",  3124.50,  3050.00,  3273.50,  7.6, "HIGH",   "CRYPTO"),
    ("EUR/USD", "BUY",  1.08542,  1.08212,  1.09202,  8.7, "HIGH",   "FOREX"),
    ("GBP/JPY", "SELL", 196.840,  197.540,  195.440,  7.9, "HIGH",   "FOREX"),
    ("SOL/USD", "BUY",  148.30,   143.50,   157.90,   7.2, "MEDIUM", "CRYPTO"),
]

DEMO_REASONS = {
    "BUY": [
        "[15min] ✅ EMA fully aligned — bullish",
        "[1h] ✅ MACD confirms upward direction",
        "[4h] ✅ ADX 28.4 — strong trend",
        "[1h] ✅ Volume spike 1.9×",
    ],
    "SELL": [
        "[15min] ✅ EMA fully aligned — bearish",
        "[1h] ✅ MACD confirms downward direction",
        "[4h] ✅ ADX 31.2 — strong trend",
        "[1h] ✅ Volume spike 2.1×",
    ],
}


def generate_demo_signals():
    signals = []
    for pair, direction, entry, sl, tp, score, conf, atype in DEMO_PAIRS:
        ps      = 1.0 if atype == "CRYPTO" else (0.01 if "JPY" in pair else 0.0001)
        sl_pips = round(abs(entry - sl) / ps, 1)
        tp_pips = round(abs(entry - tp) / ps, 1)
        rr      = round(tp_pips / sl_pips, 2)
        lot     = round((100 * 0.01) / max(sl_pips, 1), 4 if atype == "CRYPTO" else 2)
        lot     = max(0.01, lot)
        sig = Signal(
            pair=pair, direction=direction, entry=entry,
            stop_loss=sl, take_profit=tp, lot_size=lot,
            sl_pips=sl_pips, tp_pips=tp_pips, rr_ratio=rr,
            score=score, risk_amount=1.00, asset_type=atype,
            reasons=DEMO_REASONS[direction],
            timeframes=["15min", "1h", "4h"],
            confidence=conf,
        )
        signals.append(sig)
    return signals


def format_demo_signal(sig, index: int, total: int) -> str:
    d_emoji = "🟢" if sig.direction == "BUY" else "🔴"
    c_emoji = "🔥" if sig.confidence == "HIGH" else "⚡"
    a_emoji = "₿" if sig.asset_type == "CRYPTO" else "💱"
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    reasons = "\n".join(f"  {r}" for r in sig.reasons)
    sl_label  = f"${sig.sl_pips:.0f}" if sig.asset_type == "CRYPTO" else f"{sig.sl_pips} pips"
    tp_label  = f"${sig.tp_pips:.0f}" if sig.asset_type == "CRYPTO" else f"{sig.tp_pips} pips"
    lot_label = f"`{sig.lot_size}` units" if sig.asset_type == "CRYPTO" else f"`{sig.lot_size}` lots"

    return (
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{d_emoji} *{sig.direction} {sig.pair}* {c_emoji} {a_emoji} `[DEMO]`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Signal Score:* `{sig.score}/10` — {sig.confidence}\n"
        f"🕐 *Timeframes:* `15min, 1h, 4h`\n\n"
        f"💹 *Entry Price:*  `{sig.entry}`\n"
        f"🛑 *Stop Loss:*    `{sig.stop_loss}` ({sl_label})\n"
        f"🎯 *Take Profit:*  `{sig.take_profit}` ({tp_label})\n"
        f"⚖️ *Risk:Reward:*  `1:{sig.rr_ratio}`\n"
        f"📦 *Position:*     {lot_label}\n\n"
        f"📝 *Confirmations:*\n{reasons}\n\n"
        f"🕐 _{now}_\n"
        f"📌 _Demo Signal {index}/{total} · Live signals fire automatically_"
    )
