from datetime import datetime, timezone
from signal_agents import generate_agents_async, AgentReport

DIR_EMOJI = {"BUY": "🟢 BULLISH", "SELL": "🔴 BEARISH"}
IND_EMOJI = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}


def fmt_indicator(name: str, value: str, signal: str) -> str:
    return f"  {IND_EMOJI.get(signal, '⚪')} {name}: {value} [{signal}]"


async def format_signal(sig, index: int = 1, total: int = 1) -> str:
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d      = DIR_EMOJI.get(sig.direction, sig.direction)
    mtf    = "Aligned" if sig.mtf_aligned else "Mixed"
    agents = await generate_agents_async(sig)

    # Confidence label
    if sig.confidence >= 85:   conf_label = "ELITE"
    elif sig.confidence >= 75: conf_label = "VERY HIGH"
    elif sig.confidence >= 60: conf_label = "HIGH"
    elif sig.confidence >= 45: conf_label = "MEDIUM"
    else:                      conf_label = "LOW"

    candle_line = f"\nPattern: {sig.candle_pattern}" if sig.candle_pattern else ""

    warn_block = ""
    if sig.warnings:
        warn_lines = "\n".join(f"  {w}" for w in sig.warnings)
        warn_block = f"\nWarnings:\n{warn_lines}\n"

    dq     = agents.data_quality
    filled = int(dq / 10)
    dq_bar = "█" * filled + "░" * (10 - filled)

    # Verdict emoji
    verdict_emoji = {"FIRE": "🔥", "CAUTION": "⚠️", "NO TRADE": "🚫"}.get(agents.verdict, "❓")

    msg = (
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*{sig.pair}* — {d}\n"
        f"{now} | {sig.asset_type}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n"
        f"Confidence: *{sig.confidence}%* — {conf_label}\n"
        f"Signal Health: *{agents.health}* {agents.health_emoji}\n"
        f"Confluence: *{sig.confluence}/8* indicators\n"
        f"MTF: {mtf}\n"
        f"Data Quality: [{dq_bar}] {dq}%\n"
        f"{candle_line}\n"
        f"{warn_block}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Trade Plan* | R:R {sig.rr_ratio}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  TP3:         {sig.tp3} ({sig.tp3_pips}p)\n"
        f"  TP2:         {sig.tp2} ({sig.tp2_pips}p)\n"
        f"  TP1:         {sig.tp1} ({sig.tp1_pips}p)\n"
        f"  Partial TP:  {sig.partial_tp}\n"
        f"  Entry:       {sig.entry}\n"
        f"  SL:          {sig.sl} ({sig.sl_pips}p)\n"
        f"  Invalidation:{sig.invalidation}\n"
        f"\n"
        f"Lot: {sig.lot_size} | Risk: ${sig.risk_usd}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Market Regime*\n"
        f"  Trend:      {sig.trend}\n"
        f"  Volatility: {sig.volatility}\n"
        f"  Session:    {sig.session} ({sig.session_quality})\n"
        f"  ADX:        {sig.adx}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Technical Indicators*\n"
        f"{fmt_indicator('RSI(14)',     f'{sig.rsi}',  'BUY' if sig.rsi < 50 else 'SELL')}\n"
        f"{fmt_indicator('MACD',        '',            sig.macd_signal)}\n"
        f"{fmt_indicator('Stoch',       '',            sig.stoch_signal)}\n"
        f"{fmt_indicator('BB',          '',            sig.bb_signal)}\n"
        f"{fmt_indicator('ADX',         f'{sig.adx}',  'BUY' if sig.adx > 25 else 'NEUTRAL')}\n"
        f"{fmt_indicator('CCI',         '',            sig.cci_signal)}\n"
        f"{fmt_indicator('Williams R',  '',            sig.williams_signal)}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*7 Agent Analysis*\n"
        f"\n"
        f"*Technical Agent:*\n"
        f"{agents.technical}\n"
        f"\n"
        f"*Risk Agent:*\n"
        f"{agents.risk}\n"
        f"\n"
        f"*Session Agent:*\n"
        f"{agents.session}\n"
        f"\n"
        f"*Devils Advocate:*\n"
        f"{agents.devils_advocate}\n"
        f"\n"
        f"*News Sentiment:*\n"
        f"{agents.news_sentiment}\n"
        f"\n"
        f"*Fundamental Agent:*\n"
        f"{agents.fundamental}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Coordinator Verdict:* {verdict_emoji} *{agents.verdict}*\n"
        f"_{agents.verdict_reason}_\n"
        f"\n"
        f"{agents.coordinator}\n"
        f"\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Signal {index}/{total} — TrendGuard AI\n"
        f"Not financial advice. Manage your risk."
    )

    if sig.news_reason:
        msg = f"News: {sig.news_reason}\n\n" + msg

    return msg


def format_no_trade(sig) -> str:
    reasons = "\n".join(f"  - {r}" for r in sig.no_trade_reasons)
    d = DIR_EMOJI.get(sig.direction, sig.direction)
    return (
        f"NO TRADE — {sig.pair}\n"
        f"Sit this one out.\n\n"
        f"Attempted: {d} | Confidence: {sig.confidence}%\n\n"
        f"Reasons:\n{reasons}\n\n"
        f"Auto-scan retries in 30 min"
    )


def format_no_signal() -> str:
    return (
        "Scan Complete\n\n"
        "No qualifying signals right now.\n"
        "All pairs filtered by quality gates.\n\n"
        "Auto-scan retries in 30 min."
    )


def format_scanning(crypto_only: bool = False) -> str:
    pairs = "4 crypto pairs" if crypto_only else "7 forex + 4 crypto pairs"
    return (
        f"Scanning {pairs}\n\n"
        f"Running 8 indicators x 4 timeframes.\n"
        f"7 AI agents loading...\n\n"
        f"Please wait..."
    )


def format_status(session: str, active: bool, mins: int,
                  bal: str, upcoming: list = None) -> str:
    st = "ACTIVE" if active else "INACTIVE"

    events_text = ""
    if upcoming:
        lines = []
        for e in upcoming[:5]:
            t = e["time"].strftime("%H:%M UTC")
            lines.append(f"  {e['currency']} — {e['event']} @ {t}")
        events_text = "\n\nUpcoming HIGH events:\n" + "\n".join(lines)

    return (
        f"TrendGuard AI — Status\n\n"
        f"{session} — {st}\n"
        f"Next scan: {mins} min\n"
        f"Balance: {bal}"
        f"{events_text}\n\n"
        f"Forex: EUR/USD GBP/USD USD/JPY + more\n"
        f"Gold: XAU/USD\n"
        f"Crypto: BTC ETH BNB SOL + more\n"
        f"Stocks: AAPL TSLA NVDA AMZN + more\n"
        f"Oil: USO BNO UNG\n"
        f"Commodities: SLV PPLT CPER"
    )