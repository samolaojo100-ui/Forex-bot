from datetime import datetime, timezone

DIRECTION_EMOJI  = {"BUY": "🟢", "SELL": "🔴"}
CONFIDENCE_EMOJI = {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "⚠️"}


def format_signal(sig, index: int = 1, total: int = 1) -> str:
    d_emoji = DIRECTION_EMOJI.get(sig.direction, "")
    c_emoji = CONFIDENCE_EMOJI.get(sig.confidence, "")
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    reasons = "\n".join(f"  {r}" for r in sig.reasons[:4])

    return (
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{d_emoji} *{sig.direction} {sig.pair}* {c_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Signal Score:* `{sig.score}/10` — {sig.confidence}\n"
        f"🕐 *Timeframes:*   `{', '.join(sig.timeframes)}`\n\n"
        f"💹 *Entry Price:*  `{sig.entry}`\n"
        f"🛑 *Stop Loss:*    `{sig.stop_loss}` ({sig.sl_pips} pips)\n"
        f"🎯 *Take Profit:*  `{sig.take_profit}` ({sig.tp_pips} pips)\n"
        f"⚖️ *Risk:Reward:*  `1:{sig.rr_ratio}`\n"
        f"📦 *Lot Size:*     `{sig.lot_size}` lots\n"
        f"💰 *$ at Risk:*    `${sig.risk_amount:,.2f}` (1% of balance)\n\n"
        f"📝 *Confirmations:*\n{reasons}\n\n"
        f"🕐 _{now}_\n"
        f"📌 _Signal {index}/{total}_"
    )


def format_no_signal() -> str:
    return (
        "🔍 *Market Scan Complete*\n\n"
        "No high-confidence signals found right now.\n\n"
        "📌 _All 3 timeframes (15m / 1h / 4h) must align._\n"
        "⏳ _Try during London or New York sessions for best results._"
    )


def format_scanning() -> str:
    return (
        "🔄 *Scanning the market…*\n\n"
        "Checking 47 pairs across `15min` / `1h` / `4h`\n\n"
        "⏳ This takes 20–40 seconds…"
    )


def format_status(session_name: str, is_active: bool, next_scan_min: int, balance_text: str) -> str:
    status = "🟢 ACTIVE" if is_active else "🔴 INACTIVE"
    return (
        f"📡 *Bot Status*\n\n"
        f"🕐 Session: *{session_name}* — {status}\n"
        f"⏱ Next auto-scan in: *{next_scan_min} min*\n"
        f"💰 Balance: *{balance_text}*\n\n"
        f"_Use /signal to scan manually anytime._"
    )
