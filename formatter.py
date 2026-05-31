from datetime import datetime, timezone

TF_EMOJI = {
    "5min":  "⚡",
    "15min": "🔸",
    "1h":    "🔵",
    "4h":    "🟣",
    "1day":  "🟡",
}
CONF_EMOJI = {
    "VERY HIGH": "✅",
    "HIGH":      "🟢",
    "MEDIUM":    "🟡",
    "LOW":       "🔴",
}
DIR_EMOJI = {"BUY": "🟢", "SELL": "🔴"}


def fmt_tf_block(tfs, index: int) -> str:
    """Format one timeframe block exactly like the example."""
    agrees_emoji = "✅" if tfs.agrees else "⬜"
    confirmed_str = ", ".join(tfs.confirmed) if tfs.confirmed else "None"
    label = tfs.tf.upper().replace("1DAY", "Daily").replace("MIN", "M")

    macd_str = f"{tfs.macd:.5f}" if abs(tfs.macd) < 0.01 else f"{tfs.macd:.2f}"

    return (
        f"{agrees_emoji} *{label}* | *{tfs.direction}* | {tfs.indicators}/5 indicators\n"
        f"   ✔ {confirmed_str}\n"
        f"   Entry: `{tfs.entry}` | TP: `{tfs.take_profit}` | SL: `{tfs.stop_loss}`\n"
        f"   SL {tfs.sl_pips}p / TP {tfs.tp_pips}p | Lot: `{tfs.lot_size}`\n"
        f"   RSI: {tfs.rsi} | Stoch: {tfs.stoch} | MACD: {macd_str}"
    )


def format_signal(sig, index: int = 1, total: int = 1) -> str:
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d_emoji  = DIR_EMOJI.get(sig.direction, "")
    c_emoji  = CONF_EMOJI.get(sig.confidence, "")
    a_label  = "₿ CRYPTO" if sig.asset_type == "CRYPTO" else "💱 FOREX"

    tf_blocks = "\n\n".join(fmt_tf_block(t, i) for i, t in enumerate(sig.tf_signals, 1))

    return (
        f"📊 *{sig.pair}* {d_emoji} *{sig.direction}*\n"
        f"⏰ {now}\n"
        f"Confidence: {c_emoji} *{sig.confidence}* — {sig.tfs_agreed}/{sig.total_tfs} TFs\n"
        f"Pair Score: *{sig.score}/25* | {a_label}\n"
        f"💰 Risk: `${sig.risk_amount}` (1% of balance)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{tf_blocks}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 _Signal {index}/{total}_"
    )


def format_no_signal() -> str:
    return (
        "🔍 *Scan Complete*\n\n"
        "No qualifying signals right now.\n"
        "⏳ Auto-scan retries in 30 min."
    )


def format_scanning(crypto_only: bool = False) -> str:
    scope = "12 crypto pairs" if crypto_only else "47 forex + 12 crypto"
    return (
        f"🔄 *Scanning {scope}…*\n\n"
        f"Running 5 timeframes × 5 indicators per pair.\n\n"
        f"⏳ Please wait 30–60 seconds…"
    )


def format_status(session: str, active: bool, mins: int, bal: str) -> str:
    st = "🟢 ACTIVE" if active else "🔴 INACTIVE"
    return (
        f"📡 *Bot Status*\n\n"
        f"🕐 *{session}* — {st}\n"
        f"⏱ Next scan: *{mins} min*\n"
        f"💰 Balance: *{bal}*\n\n"
        f"₿ Crypto 24/7 · 💱 Forex weekdays"
    )
