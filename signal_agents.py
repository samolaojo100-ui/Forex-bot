"""
signal_agents.py — TrendGuard AI
Generates plain-English reasoning for each signal.
Four agents: Technical, Risk, Session, Devil's Advocate.
"""

from dataclasses import dataclass


@dataclass
class AgentReport:
    technical:    str
    risk:         str
    session:      str
    devils_advocate: str
    health:       str   # STRONG / MODERATE / CAUTION / WEAK
    health_emoji: str
    data_quality: int   # 0-100


def _health(confidence: int, confluence: int, mtf: bool, warnings: list) -> tuple:
    score = 0
    if confidence >= 80: score += 3
    elif confidence >= 70: score += 2
    elif confidence >= 55: score += 1

    if confluence >= 6: score += 3
    elif confluence >= 4: score += 2
    elif confluence >= 3: score += 1

    if mtf: score += 2
    score -= len(warnings)

    if score >= 7:   return "STRONG",   "💚"
    elif score >= 5: return "MODERATE", "🟡"
    elif score >= 3: return "CAUTION",  "🟠"
    else:            return "WEAK",     "🔴"


def _data_quality(confluence: int, mtf: bool, adx: float) -> int:
    q = 50
    q += confluence * 5
    if mtf:    q += 10
    if adx > 25: q += 10
    return min(q, 100)


def generate_agents(sig) -> AgentReport:
    d   = sig.direction
    opp = "SELL" if d == "BUY" else "BUY"

    # ── Technical Agent ───────────────────────────────────────
    bullish = []
    bearish = []

    if sig.rsi < 35:   bullish.append("RSI deeply oversold")
    elif sig.rsi > 65: bearish.append("RSI overbought")

    if sig.macd_signal == "BUY":    bullish.append("MACD bullish crossover")
    elif sig.macd_signal == "SELL": bearish.append("MACD bearish crossover")

    if sig.stoch_signal == "BUY":    bullish.append("Stochastic turning up")
    elif sig.stoch_signal == "SELL": bearish.append("Stochastic turning down")

    if sig.bb_signal == "BUY":    bullish.append("price near lower Bollinger Band")
    elif sig.bb_signal == "SELL": bearish.append("price near upper Bollinger Band")

    if sig.cci_signal == "BUY":    bullish.append("CCI oversold reversal")
    elif sig.cci_signal == "SELL": bearish.append("CCI overbought reversal")

    if sig.williams_signal == "BUY":    bullish.append("Williams %R oversold")
    elif sig.williams_signal == "SELL": bearish.append("Williams %R overbought")

    if sig.adx > 30: bullish.append(f"strong trend momentum (ADX {sig.adx})")

    if sig.candle_pattern:
        if d == "BUY":  bullish.append(f"{sig.candle_pattern} candle pattern")
        else:           bearish.append(f"{sig.candle_pattern} candle pattern")

    factors = bullish if d == "BUY" else bearish
    counter = bearish if d == "BUY" else bullish

    if factors:
        tech_text = f"{'Bullish' if d == 'BUY' else 'Bearish'} case supported by: {', '.join(factors[:3])}."
    else:
        tech_text = f"Indicators lean {d} but with limited confirmation."

    if counter:
        tech_text += f" Counter-signals: {', '.join(counter[:2])}."

    if sig.mtf_aligned:
        tech_text += " Multi-timeframe alignment confirmed ✅."
    else:
        tech_text += " Mixed signals across timeframes ⚠️."

    # ── Risk Agent ────────────────────────────────────────────
    rr_comment = ""
    if sig.rr_ratio >= 2.5:   rr_comment = "Excellent R:R ratio."
    elif sig.rr_ratio >= 1.5: rr_comment = "Acceptable R:R ratio."
    else:                      rr_comment = "R:R is tight — reduce lot size."

    vol_comment = ""
    if "High" in sig.volatility:   vol_comment = "High volatility — widen SL slightly or reduce lot."
    elif "Low" in sig.volatility:  vol_comment = "Low volatility — TP may take longer to reach."
    else:                          vol_comment = "Normal volatility conditions."

    warn_comment = ""
    if sig.warnings:
        warn_comment = f" Note: {sig.warnings[0]}"

    risk_text = f"{rr_comment} {vol_comment}{warn_comment} Risk fixed at 1% of balance (${sig.risk_usd})."

    # ── Session Agent ─────────────────────────────────────────
    session_tips = {
        "London":          "London session — strong EUR/GBP moves likely.",
        "New York":        "NY session — high liquidity, best for USD pairs.",
        "London/NY Overlap": "Peak session overlap — highest volume and momentum.",
        "Tokyo":           "Tokyo session — best for JPY and AUD pairs.",
        "Sydney":          "Sydney session — lighter volume, wider spreads possible.",
    }
    s_tip = ""
    for key, tip in session_tips.items():
        if key in sig.session:
            s_tip = tip
            break
    if not s_tip:
        s_tip = "Off-peak hours — expect slower price action."

    quality_tip = {
        "High ✅": "Optimal time to trade.",
        "Medium":  "Decent liquidity.",
        "Low":     "Consider waiting for a better session.",
    }.get(sig.session_quality, "")

    session_text = f"{s_tip} {quality_tip}"

    # ── Devil's Advocate ──────────────────────────────────────
    risks = []
    if not sig.mtf_aligned:
        risks.append("timeframes are not fully aligned")
    if sig.adx < 20:
        risks.append("ADX below 20 — trend may be too weak")
    if "Ranging" in sig.trend:
        risks.append("market is ranging — breakout risk")
    if "High" in sig.volatility:
        risks.append("high volatility can spike SL")
    if sig.news_reason:
        risks.append(f"news event nearby: {sig.news_reason}")
    if sig.confluence < 5:
        risks.append(f"only {sig.confluence}/8 indicators confirm")

    if risks:
        devil_text = f"Be cautious: {'; '.join(risks[:3])}. Always respect your SL."
    else:
        devil_text = "No major red flags. Setup looks clean — stick to the plan."

    # ── Health & Data Quality ─────────────────────────────────
    health, health_emoji = _health(sig.confidence, sig.confluence, sig.mtf_aligned, sig.warnings)
    dq = _data_quality(sig.confluence, sig.mtf_aligned, sig.adx)

    return AgentReport(
        technical=tech_text,
        risk=risk_text,
        session=session_text,
        devils_advocate=devil_text,
        health=health,
        health_emoji=health_emoji,
        data_quality=dq,
    )
