from datetime import datetime, timezone

DIR_EMOJI = {"BUY": "🟢 BULLISH", "SELL": "🔴 BEARISH"}
IND_EMOJI = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}


def fmt_indicator(name: str, value: str, signal: str) -> str:
    return f"  {IND_EMOJI.get(signal, '⚪')} {name}: {value} [{signal}]"


def format_signal(sig, index: int = 1, total: int = 1) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d   = DIR_EMOJI.get(sig.direction, sig.direction)
    mtf = "✅ Aligned" if sig.mtf_aligned else "⚠️ Mixed"

    # Confidence label
    if sig.confidence >= 75:
        conf_label = "VERY HIGH ✅"
    elif sig.confidence >= 60:
        conf_label = "HIGH 🟢"
    elif sig.confidence >= 45:
        conf_label = "MEDIUM 🟡"
    else:
        conf_label = "LOW 🔴"

    # Candle pattern line
    candle_line = f"\n🕯️ Pattern: *{sig.candle_pattern}*" if sig.candle_pattern else ""

    msg = (
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *{sig.pair}* — {d}\n"
        f"⏰ {now} | {sig.asset_type}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"🎯 *Confidence: {sig.confidence}%* — {conf_label}\n"
        f"📐 Confluence: *{sig.confluence}/8* indicators confirm\n"
        f"🔀 MTF: {mtf}\n"
        f"{candle_line}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *Trade Plan* | R:R {sig.rr_ratio}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  🟢 TP3:         `{sig.tp3}` ({sig.tp3_pips}p)\n"
        f"  🟢 TP2:         `{sig.tp2}` ({sig.tp2_pips}p)\n"
        f"  🟢 TP1:         `{sig.tp1}` ({sig.tp1_pips}p)\n"
        f"  🟡 Partial TP:  `{sig.partial_tp}`\n"
        f"  🔵 Entry:       `{sig.entry}`\n"
        f"  🔴 SL:          `{sig.sl}` ({sig.sl_pips}p)\n"
        f"  ⚫ Invalidation:`{sig.invalidation}`\n"
        f"\n"
        f"💰 Lot: `{sig.lot_size}` | Risk: `${sig.risk_usd}`\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 *Market Regime*\n"
        f"  Trend:      {sig.trend}\n"
        f"  Volatility: {sig.volatility}\n"
        f"  Session:    {sig.session} ({sig.session_quality})\n"
        f"  ADX:        {sig.adx}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔬 *Technical Indicators*\n"
        f"{fmt_indicator('RSI(14)',      f'{sig.rsi}',           'BUY' if sig.rsi < 50 else 'SELL')}\n"
        f"{fmt_indicator('MACD(12,26)',  '',                     sig.macd_signal)}\n"
        f"{fmt_indicator('Stoch(9,6)',   '',                     sig.stoch_signal)}\n"
        f"{fmt_indicator('BB %B',        '',                     sig.bb_signal)}\n"
        f"{fmt_indicator('ADX(14)',      f'{sig.adx}',           'BUY' if sig.adx > 25 else 'NEUTRAL')}\n"
        f"{fmt_indicator('CCI(14)',      '',                     sig.cci_signal)}\n"
        f"{fmt_indicator('Williams %R',  '',                     sig.williams_signal)}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 _Signal {index}/{total} — TrendGuard AI_"
    )

    if sig.news_reason:
        msg = f"📰 *News context:* _{sig.news_reason}_\n\n" + msg

    return msg


def format_no_trade(sig) -> str:
    reasons = "\n".join(f"  • {r}" for r in sig.no_trade_reasons)
    d = DIR_EMOJI.get(sig.direction, sig.direction)
    return (
        f"🚫 *NO TRADE — {sig.pair}*\n"
        f"_Sit this one out._\n\n"
        f"Attempted: {d} | Confidence: *{sig.confidence}%*\n\n"
        f"*Reasons:*\n{reasons}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ _Auto-scan retries in 30 min_"
    )


def format_no_signal() -> str:
    return (
        "🔍 *Scan Complete*\n\n"
        "No qualifying signals right now.\n"
        "All pairs filtered by quality gates.\n\n"
        "⏳ Auto-scan retries in 30 min."
    )


def format_scanning(crypto_only: bool = False) -> str:
    pairs = "4 crypto pairs" if crypto_only else "7 forex + 4 crypto pairs"
    return (
        f"🔄 *Scanning {pairs}…*\n\n"
        f"Running 8 indicators × 4 timeframes.\n\n"
        f"⏳ Please wait…"
    )


def format_status(session: str, active: bool, mins: int,
                  bal: str, upcoming: list = None) -> str:
    st = "🟢 ACTIVE" if active else "🔴 INACTIVE"

    events_text = ""
    if upcoming:
        lines = []
        for e in upcoming[:5]:
            t = e["time"].strftime("%H:%M UTC")
            lines.append(f"  ⚠️ {e['currency']} — {e['event']} @ {t}")
        events_text = "\n\n*📅 Upcoming HIGH events:*\n" + "\n".join(lines)

    return (
        f"📡 *TrendGuard AI — Status*\n\n"
        f"🕐 *{session}* — {st}\n"
        f"⏱ Next scan: *{mins} min*\n"
        f"💰 Balance: *{bal}*"
        f"{events_text}\n\n"
        f"💱 Forex: EUR/USD GBP/USD USD/JPY USD/CHF AUD/USD USD/CAD\n"
        f"🥇 Gold: XAU/USD\n"
        f"₿ Crypto: BTC ETH BNB SOL"
    )
