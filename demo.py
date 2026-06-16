"""
demo.py — generates sample signals for the /demo command.
No API calls needed; purely hardcoded example data.
"""
from dataclasses import dataclass


@dataclass
class DemoSignal:
    pair: str
    direction: str
    score: float
    entry: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    lot_size: float
    pips_sl: int
    pips_tp: int
    timeframe_confirmations: list


def generate_demo_signals() -> list:
    return [
        DemoSignal(
            pair="EUR/USD",
            direction="BUY",
            score=8.2,
            entry=1.08542,
            stop_loss=1.08212,
            take_profit=1.09202,
            rr_ratio=2.0,
            lot_size=0.30,
            pips_sl=33,
            pips_tp=66,
            timeframe_confirmations=[
                "✅ [15min] EMA aligned with trend",
                "✅ [1h] MACD confirms direction",
                "✅ [4h] ADX 28.4 — strong trend",
                "✅ [1h] Volume spike 1.8×",
            ],
        ),
        DemoSignal(
            pair="GBP/USD",
            direction="SELL",
            score=7.5,
            entry=1.26834,
            stop_loss=1.27154,
            take_profit=1.26194,
            rr_ratio=2.0,
            lot_size=0.25,
            pips_sl=32,
            pips_tp=64,
            timeframe_confirmations=[
                "✅ [15min] RSI overbought — reversal likely",
                "✅ [1h] MACD bearish crossover",
                "✅ [4h] Price below EMA 50",
            ],
        ),
    ]


def format_demo_signal(sig: DemoSignal, index: int, total: int) -> str:
    emoji = "🟢" if sig.direction == "BUY" else "🔴"
    direction_label = f"{emoji} {sig.direction} {sig.pair}"

    confirmations = "\n".join(f"  {c}" for c in sig.timeframe_confirmations)

    return (
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{direction_label} 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Signal Score: *{sig.score}/10* — HIGH\n"
        f"🕐 Multi-timeframe confirmed\n\n"
        f"💹 Entry Price:  `{sig.entry}`\n"
        f"🛑 Stop Loss:    `{sig.stop_loss}`  ({sig.pips_sl} pips)\n"
        f"🎯 Take Profit:  `{sig.take_profit}`  ({sig.pips_tp} pips)\n"
        f"⚖️ Risk:Reward:  1:{sig.rr_ratio}\n"
        f"📦 Lot Size:     `{sig.lot_size} lots`\n\n"
        f"📝 Confirmations:\n{confirmations}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━"
    )
