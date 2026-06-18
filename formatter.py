# formatter.py
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
    agrees_emoji  = "✅" if tfs.agrees else "⬜"
    confirmed_str = ", ".join(tfs.confirmed) if tfs.confirmed else "None"
    label         = tfs.tf.upper().replace("1DAY", "Daily").replace("MIN", "M")
    macd_str      = f"{tfs.macd:.5f}" if abs(tfs.macd) < 0.01 else f"{tfs.macd:.2f}"

    return (
        f"{agrees_emoji} *{label}* | *{tfs.direction}* | {tfs.indicators}/5 indicators\n"
        f"  ✔ {confirmed_str}\n"
        f"  Entry: `{tfs.entry}` | TP: `{tfs.take_profit}` | SL: `{tfs.stop_loss}`\n"
        f"  SL {tfs.sl_pips}p / TP {tfs.tp_pips}p | Lot: `{tfs.lot_size}`\n"
        f"  RSI: {tfs.rsi} | Stoch: {tfs.stoch} | MACD: {macd_str}"
    )


def format_signal(sig, index: int = 1, total: int = 1) -> str:
    now        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d_emoji    = DIR_EMOJI.get(sig.direction, "")
    c_emoji    = CONF_EMOJI.get(sig.confidence, "")
    a_label    = "₿ CRYPTO" if sig.asset_type == "CRYPTO" else "💱 FOREX"
    conviction = round((sig.tfs_agreed / sig.total_tfs) * 100) if sig.total_tfs else 0
    sr_line    = f"\n{sig.sr_warning}" if getattr(sig, "sr_warning", "") else ""

    # Market Regime block
    regime = getattr(sig, "regime", {})
    if regime:
        regime_block = (
            f"📊 *Market Regime*\n"
            f"  Trend:      {regime.get('trend', '—')}\n"
            f"  Phase:      {regime.get('phase', '—')} (ADX {regime.get('adx', '—')})\n"
            f"  Volatility: {regime.get('volatility', '—')}\n"
            f"  Session:    {regime.get('session', '—')} — Quality: {regime.get('session_quality', '—')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
    else:
        regime_block = ""

    tf_blocks = "\n\n".join(fmt_tf_block(t, i) for i, t in enumerate(sig.tf_signals, 1))

    return (
        f"📊 *{sig.pair}* {d_emoji} *{sig.direction}*\n"
        f"⏰ {now}\n"
        f"Conviction: {c_emoji} *{sig.confidence}* ({conviction}%) — "
        f"{sig.tfs_agreed}/{sig.total_tfs} TFs\n"
        f"Score: *{sig.score}/25* | {a_label}{sr_line}\n"
        f"💰 Risk: `${sig.risk_amount}` (1% of balance)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{regime_block}"
        f"📌 *Trade Plan*\n"
        f"  🎯 TP3 (1:3): `{sig.tp3}`\n"
        f"  🎯 TP2 (1:2): `{sig.tp2}`\n"
        f"  🎯 TP1 (1:1): `{sig.tp1}`\n"
        f"  🔵 Entry:     `{sig.entry}`\n"
        f"  🛑 SL:        `{sig.stop_loss}`\n"
        f"  ⚫ Invalid:   `{sig.invalidation}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{tf_blocks}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 _Signal {index}/{total}_"
    )


def format_no_trade(result: dict) -> str:
    """Shown on manual /signal when a pair is blocked by one of the gates."""
    pair       = result.get("pair", "")
    direction  = result.get("direction", "")
    conviction = result.get("conviction", 0)
    reasons    = result.get("reasons", [])
    d_emoji    = DIR_EMOJI.get(direction, "—")
    reasons_text = "\n".join(f"  • {r}" for r in reasons)

    return (
        f"🚫 *NO TRADE — {pair}*\n"
        f"_Sit this one out._\n\n"
        f"Attempted: {d_emoji} *{direction}* | Conviction: *{conviction}%*\n\n"
        f"*Reasons blocked:*\n{reasons_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ _Auto-scan retries in 30 min_"
    )


def format_no_signal() -> str:
    """Shown when scan finds zero qualifying signals."""
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


def format_status(session: str, active: bool, mins: int, bal: str,
                  upcoming_events: list = None) -> str:
    st = "🟢 ACTIVE" if active else "🔴 INACTIVE"

    events_text = ""
    if upcoming_events:
        lines = []
        for e in upcoming_events[:5]:
            t = e["time"].strftime("%H:%M UTC")
            lines.append(f"  ⚠️ {e['currency']} — {e['event']} @ {t}")
        events_text = "\n\n*📅 Upcoming HIGH events:*\n" + "\n".join(lines)

    return (
        f"📡 *Bot Status*\n\n"
        f"🕐 *{session}* — {st}\n"
        f"⏱ Next scan: *{mins} min*\n"
        f"💰 Balance: *{bal}*"
        f"{events_text}\n\n"
        f"₿ Crypto 24/7 · 💱 Forex weekdays"
    )