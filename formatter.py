def format_no_trade(result: dict) -> str:
    """Format a NO TRADE result with reasons — like TradeVisor's 'Sit this one out'."""
    pair = result.get("pair", "")
    direction = result.get("direction", "")
    conviction = result.get("conviction", 0)
    reasons = result.get("reasons", [])
    d_emoji = DIR_EMOJI.get(direction, "—")

    reasons_text = "\n".join(f"  • {r}" for r in reasons)

    return (
        f"🚫 *NO TRADE — {pair}*\n"
        f"Sit this one out.\n\n"
        f"Attempted direction: {d_emoji} {direction}\n"
        f"Conviction: *{conviction}%*\n\n"
        f"*Reasons:*\n{reasons_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ _Auto-scan retries in 30 min_"
    )