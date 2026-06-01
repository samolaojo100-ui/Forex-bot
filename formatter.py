from datetime import datetime, timezone

DIR_EMOJI  = {"BUY": "🟢", "SELL": "🔴"}
CONF_EMOJI = {
    "VERY HIGH ⭐⭐⭐": "✅",
    "HIGH ⭐⭐":        "🟢",
    "MEDIUM ⭐":        "🟡",
    "LOW":              "🔴",
}
TF_LABEL = {
    "5min":  "5M",
    "15min": "15M",
    "1h":    "1H",
    "4h":    "4H",
    "1day":  "Daily",
}


def _fmt_tf(tfs) -> str:
    agree  = "✅" if tfs.agrees else "⬜"
    label  = TF_LABEL.get(tfs.tf, tfs.tf.upper())
    confs  = ", ".join(tfs.confirmed) if tfs.confirmed else "None"
    macd_s = f"{tfs.macd:.5f}" if abs(tfs.macd) < 0.01 else f"{tfs.macd:.4f}"
    return (
        f"{agree} *{label}* — *{tfs.direction}* | {tfs.indicators}/5 indicators\n"
        f"   ✔ {confs}\n"
        f"   Entry `{tfs.entry}` | SL `{tfs.stop_loss}` | TP `{tfs.take_profit}`\n"
        f"   SL {tfs.sl_pips}p / TP {tfs.tp_pips}p | Lot `{tfs.lot_size}`\n"
        f"   RSI {tfs.rsi} | Stoch {tfs.stoch} | MACD {macd_s} | ADX {tfs.adx}"
    )


def format_signal(sig, index: int = 1, total: int = 1) -> str:
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d_em     = DIR_EMOJI.get(sig.direction, "")
    c_em     = CONF_EMOJI.get(sig.confidence, "")
    a_label  = "₿ CRYPTO" if sig.asset_type == "CRYPTO" else "💱 FOREX"
    tf_text  = "\n\n".join(_fmt_tf(t) for t in sig.tf_signals)

    return (
        f"📊 *{sig.pair}* {d_em} *{sig.direction}*\n"
        f"⏰ {now}\n"
        f"Confidence: {c_em} *{sig.confidence}* — {sig.tfs_agreed}/{sig.total_tfs} TFs agree\n"
        f"Score: *{sig.score}/10* | {a_label}\n"
        f"💰 Risk: `${sig.risk_amount}` (1% of balance)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{tf_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 _Signal {index}/{total}_"
    )


def format_no_signal() -> str:
    return (
        "🔍 *Scan Complete — No Signals*\n\n"
        "Market conditions don't meet the threshold right now.\n"
        "⏳ Auto-scan retries in 30 min.\n\n"
        "_Try /crypto for 24/7 crypto signals._"
    )


def format_scanning(crypto_only: bool = False) -> str:
    scope = "crypto pairs" if crypto_only else "forex + crypto pairs"
    return (
        f"🔄 *Scanning {scope}…*\n\n"
        f"Running {3} timeframes × 5 indicators per pair.\n"
        f"⏳ Please wait 60–90 seconds…"
    )


def format_status(session: str, active: bool, mins: int, bal: str) -> str:
    st = "🟢 ACTIVE" if active else "🔴 INACTIVE"
    return (
        f"📡 *Bot Status*\n\n"
        f"🕐 *{session}* — {st}\n"
        f"⏱ Next auto-scan: *{mins} min*\n"
        f"💰 Balance: *{bal}*\n\n"
        f"₿ /crypto — 24/7 crypto signals\n"
        f"💱 /signal — forex (weekdays only)"
    )
