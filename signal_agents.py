"""
signal_agents.py — TrendGuard AI
7-Agent AI-powered signal reasoning using Google Gemini API.

Agents:
  1. Technical      — indicator analysis
  2. Risk           — R:R, volatility, lot sizing
  3. Session        — timing and liquidity
  4. Devil's Advocate — challenges the signal
  5. News Sentiment — scores headlines, flags event risk
  6. Fundamental    — macro context, DXY, yields, sentiment
  7. Coordinator    — synthesizes all agents, final verdict (FIRE / NO TRADE / CAUTION)
"""

import os
import asyncio
import aiohttp
from dataclasses import dataclass, field

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent?key=" + GEMINI_API_KEY
)


# ── Agent Report ──────────────────────────────────────────────────────────────

@dataclass
class AgentReport:
    technical:        str
    risk:             str
    session:          str
    devils_advocate:  str
    news_sentiment:   str
    fundamental:      str
    coordinator:      str
    verdict:          str   # FIRE / CAUTION / NO TRADE
    verdict_reason:   str
    health:           str   # STRONG / MODERATE / CAUTION / WEAK
    health_emoji:     str
    data_quality:     int   # 0-100


# ── Health & Data Quality ─────────────────────────────────────────────────────

def _health(confidence, confluence, mtf, warnings):
    score = 0
    if confidence >= 80:   score += 3
    elif confidence >= 70: score += 2
    elif confidence >= 55: score += 1
    if confluence >= 6:    score += 3
    elif confluence >= 4:  score += 2
    elif confluence >= 3:  score += 1
    if mtf:                score += 2
    score -= len(warnings)
    if score >= 7:   return "STRONG",   "💚"
    elif score >= 5: return "MODERATE", "🟡"
    elif score >= 3: return "CAUTION",  "🟠"
    else:            return "WEAK",     "🔴"


def _data_quality(confluence, mtf, adx):
    q = 50
    q += confluence * 5
    if mtf:      q += 10
    if adx > 25: q += 10
    return min(q, 100)


# ── Gemini API call ───────────────────────────────────────────────────────────

async def _ask_gemini(prompt, fallback, max_tokens=120):
    if not GEMINI_API_KEY:
        return fallback
    try:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": max_tokens}
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GEMINI_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=12)
            ) as resp:
                if resp.status != 200:
                    return fallback
                data = await resp.json()
                text = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", fallback)
                    .strip()
                )
                return text if text else fallback
    except Exception:
        return fallback


# ── Signal summary ────────────────────────────────────────────────────────────

def _build_summary(sig):
    pair = getattr(sig, "symbol", sig.pair)
    news_part = (
        f"News Bullish: {getattr(sig,'news_bullish',0)} | "
        f"News Bearish: {getattr(sig,'news_bearish',0)} | "
        f"News Sentiment: {getattr(sig,'news_sentiment','NEUTRAL')} | "
    )
    tp_part = (
        f"TP Reachable: {getattr(sig,'tp_reachable',True)} | "
        f"TP Issue: {getattr(sig,'tp_reach_reason','None')} | "
    )
    return (
        f"Pair: {pair} | Direction: {sig.direction} | "
        f"Confidence: {sig.confidence}% | Confluence: {sig.confluence}/8 | "
        f"RSI: {sig.rsi} | MACD: {sig.macd_signal} | Stoch: {sig.stoch_signal} | "
        f"BB: {sig.bb_signal} | CCI: {sig.cci_signal} | Williams: {sig.williams_signal} | "
        f"ADX: {sig.adx} | Trend: {sig.trend} | MTF Aligned: {sig.mtf_aligned} | "
        f"Volatility: {sig.volatility} | Session: {sig.session} | "
        f"Session Quality: {sig.session_quality} | R:R: {sig.rr_ratio} | "
        f"Risk: ${sig.risk_usd} | Candle: {getattr(sig,'candle_pattern','None')} | "
        f"{news_part}{tp_part}"
        f"Warnings: {sig.warnings} | News Event: {getattr(sig,'news_reason','None')}"
    )


# ── Agent 1: Technical ────────────────────────────────────────────────────────

def _technical_prompt(sig, summary):
    return (
        f"You are the Technical Analysis Agent for TrendGuard AI.\n"
        f"Signal data: {summary}\n\n"
        f"In 2-3 sentences, explain WHY the indicators support this "
        f"{sig.direction} signal on {getattr(sig,'symbol',sig.pair)}. "
        f"Mention strongest confirming indicators and counter-signals. "
        f"Concise, professional, no bullet points."
    )

def _fallback_technical(sig):
    d = sig.direction
    b, s = [], []
    if sig.rsi < 35:                b.append("RSI deeply oversold")
    elif sig.rsi > 65:              s.append("RSI overbought")
    if sig.macd_signal == "BUY":    b.append("MACD bullish crossover")
    elif sig.macd_signal == "SELL": s.append("MACD bearish crossover")
    if sig.bb_signal == "BUY":      b.append("price near lower BB")
    elif sig.bb_signal == "SELL":   s.append("price near upper BB")
    factors = b if d == "BUY" else s
    counter = s if d == "BUY" else b
    txt = f"{'Bullish' if d=='BUY' else 'Bearish'} case: {', '.join(factors[:3]) or 'limited confirmation'}."
    if counter: txt += f" Counter: {', '.join(counter[:2])}."
    txt += " MTF aligned ✅." if sig.mtf_aligned else " Mixed timeframes ⚠️."
    return txt


# ── Agent 2: Risk ─────────────────────────────────────────────────────────────

def _risk_prompt(sig, summary):
    return (
        f"You are the Risk Management Agent for TrendGuard AI.\n"
        f"Signal data: {summary}\n\n"
        f"In 2-3 sentences, assess risk profile. Comment on R:R ({sig.rr_ratio}), "
        f"volatility ({sig.volatility}), TP reachability, and warnings. "
        f"Recommend lot size discipline. Concise, no bullet points."
    )

def _fallback_risk(sig):
    rr  = "Excellent R:R." if sig.rr_ratio >= 2.5 else ("Acceptable R:R." if sig.rr_ratio >= 1.5 else "Tight R:R — reduce lot.")
    vol = "High volatility — widen SL." if "High" in sig.volatility else ("Low volatility — slow TP." if "Low" in sig.volatility else "Normal volatility.")
    tp  = f" TP concern: {getattr(sig,'tp_reach_reason','')}." if not getattr(sig,'tp_reachable',True) else ""
    warn = f" Note: {sig.warnings[0]}" if sig.warnings else ""
    return f"{rr} {vol}{tp}{warn} Risk: 1% (${sig.risk_usd})."


# ── Agent 3: Session ──────────────────────────────────────────────────────────

def _session_prompt(sig, summary):
    return (
        f"You are the Session Timing Agent for TrendGuard AI.\n"
        f"Signal data: {summary}\n\n"
        f"In 2 sentences, assess if session ({sig.session}, quality: {sig.session_quality}) "
        f"is favourable for {getattr(sig,'symbol',sig.pair)}. Concise, no bullet points."
    )

def _fallback_session(sig):
    tips = {
        "London": "London session — strong EUR/GBP moves likely.",
        "New York": "NY session — high liquidity for USD pairs.",
        "London/NY Overlap": "Peak overlap — highest volume.",
        "Tokyo": "Tokyo session — best for JPY/AUD pairs.",
        "Sydney": "Sydney session — lighter volume.",
    }
    for k, v in tips.items():
        if k in sig.session: return v
    return "Off-peak hours — slower price action expected."


# ── Agent 4: Devil's Advocate ─────────────────────────────────────────────────

def _devil_prompt(sig, summary):
    return (
        f"You are the Devil's Advocate Agent for TrendGuard AI.\n"
        f"Signal data: {summary}\n\n"
        f"In 2-3 sentences, identify the biggest risks in this "
        f"{sig.direction} setup on {getattr(sig,'symbol',sig.pair)}. "
        f"Include news risk and TP concerns if relevant. Honest and sharp. No bullet points."
    )

def _fallback_devil(sig):
    risks = []
    if not sig.mtf_aligned:      risks.append("timeframes not aligned")
    if sig.adx < 20:             risks.append("ADX below 20 — weak trend")
    if "Ranging" in sig.trend:   risks.append("market is ranging")
    if "High" in sig.volatility: risks.append("high volatility risk")
    if sig.confluence < 5:       risks.append(f"only {sig.confluence}/8 indicators confirm")
    if not getattr(sig,"tp_reachable",True):
        risks.append(f"TP concern: {getattr(sig,'tp_reach_reason','')}")
    sent = getattr(sig,"news_sentiment","NEUTRAL")
    if (sent == "BEARISH" and sig.direction == "BUY") or \
       (sent == "BULLISH" and sig.direction == "SELL"):
        risks.append(f"news sentiment conflicts with {sig.direction}")
    if risks:
        return f"Caution: {'; '.join(risks[:3])}. Respect your SL."
    return "No major red flags. Setup looks clean — stick to the plan."


# ── Agent 5: News Sentiment ───────────────────────────────────────────────────

def _news_prompt(sig, summary):
    return (
        f"You are the News Sentiment Agent for TrendGuard AI.\n"
        f"News: {getattr(sig,'news_bullish',0)} bullish, "
        f"{getattr(sig,'news_bearish',0)} bearish headlines. "
        f"Overall: {getattr(sig,'news_sentiment','NEUTRAL')}. "
        f"Upcoming event: {getattr(sig,'news_reason','None')}.\n"
        f"Signal: {getattr(sig,'symbol',sig.pair)} {sig.direction}\n\n"
        f"In 2-3 sentences, assess how news affects this {sig.direction} trade. "
        f"Flag high-impact events. Direct, no bullet points."
    )

def _fallback_news(sig):
    b = getattr(sig,"news_bullish",0)
    s = getattr(sig,"news_bearish",0)
    sent = getattr(sig,"news_sentiment","NEUTRAL")
    event = getattr(sig,"news_reason","")
    if sent == "NEUTRAL":
        base = "News sentiment is neutral — no significant headline bias."
    elif sent == "BULLISH":
        base = f"Bullish news sentiment ({b} headlines)."
        if sig.direction == "SELL": base += " Conflicts with SELL — caution."
    elif sent == "BEARISH":
        base = f"Bearish news sentiment ({s} headlines)."
        if sig.direction == "BUY": base += " Conflicts with BUY — caution."
    else:
        base = f"Mixed sentiment ({b} bullish, {s} bearish) — no clear bias."
    if event: base += f" Event nearby: {event}."
    return base


# ── Agent 6: Fundamental ──────────────────────────────────────────────────────

def _fundamental_prompt(sig, summary):
    pair = getattr(sig,"symbol",sig.pair)
    if "XAU" in pair.upper():
        ctx = "Gold is driven by USD strength, real yields, safe-haven demand, Fed policy, geopolitics."
    elif any(c in pair.upper() for c in ["BTC","ETH","BNB","SOL","XRP"]):
        ctx = "Crypto is driven by risk appetite, BTC dominance, macro liquidity, regulatory news."
    else:
        ctx = "Forex is driven by rate differentials, central bank policy, economic data, DXY."
    return (
        f"You are the Fundamental Analysis Agent for TrendGuard AI.\n"
        f"{ctx}\nSignal data: {summary}\n\n"
        f"In 2-3 sentences, assess the macro backdrop for this {sig.direction} "
        f"trade on {pair}. Consider news sentiment "
        f"({getattr(sig,'news_sentiment','NEUTRAL')}), upcoming events, "
        f"and whether macro supports {sig.direction}. Professional, no bullet points."
    )

def _fallback_fundamental(sig):
    pair = getattr(sig,"symbol",sig.pair)
    sent = getattr(sig,"news_sentiment","NEUTRAL")
    d    = sig.direction
    if "XAU" in pair.upper():
        return (
            f"Gold macro: {'USD weakness and risk-off mood supports BUY.' if d=='BUY' else 'USD strength and risk-on mood pressures gold SELL.'} "
            f"News sentiment is {sent}."
        )
    align = "aligns with" if (
        (sent=="BULLISH" and d=="BUY") or (sent=="BEARISH" and d=="SELL")
    ) else "conflicts with" if sent in ("BULLISH","BEARISH") else "is neutral for"
    return (
        f"Macro backdrop: news sentiment {sent} {align} the {d} signal on {pair}. "
        f"Monitor upcoming events for volatility risk."
    )


# ── Agent 7: Coordinator ──────────────────────────────────────────────────────

def _coordinator_prompt(sig, summary, tech, risk, session, devil, news, fundamental):
    pair = getattr(sig,"symbol",sig.pair)
    return (
        f"You are the Coordinator Agent for TrendGuard AI. "
        f"Synthesize all agents and give the FINAL verdict.\n\n"
        f"Signal: {pair} {sig.direction} | Confidence: {sig.confidence}% | "
        f"TP Reachable: {getattr(sig,'tp_reachable',True)}\n\n"
        f"TECHNICAL: {tech}\n"
        f"RISK: {risk}\n"
        f"SESSION: {session}\n"
        f"DEVIL'S ADVOCATE: {devil}\n"
        f"NEWS SENTIMENT: {news}\n"
        f"FUNDAMENTAL: {fundamental}\n\n"
        f"Respond in EXACTLY this format:\n"
        f"VERDICT: [FIRE / CAUTION / NO TRADE]\n"
        f"REASON: [one sentence]\n"
        f"SUMMARY: [2-3 sentences synthesizing all agents]\n\n"
        f"Rules:\n"
        f"- FIRE: strong alignment across technical, fundamental, and news\n"
        f"- CAUTION: valid signal but meaningful risks or conflicts\n"
        f"- NO TRADE: TP unreachable, major conflict, or news blocks trade\n"
        f"Be decisive."
    )

def _fallback_coordinator(sig, health):
    tp_ok = getattr(sig,"tp_reachable",True)
    sent  = getattr(sig,"news_sentiment","NEUTRAL")
    conflict = (
        (sent=="BEARISH" and sig.direction=="BUY") or
        (sent=="BULLISH" and sig.direction=="SELL")
    )
    if not tp_ok:
        return (
            "TP is unreachable — trade structurally unfireable despite directional edge.",
            "NO TRADE",
            getattr(sig,"tp_reach_reason","TP blocked")
        )
    if conflict and sig.confidence < 75:
        return (
            f"News conflicts with {sig.direction} and confidence below 75% — stand down.",
            "NO TRADE",
            f"News sentiment conflicts with {sig.direction}"
        )
    if health in ("STRONG","MODERATE") and not conflict:
        return (
            f"Technical and fundamental alignment supports {sig.direction}. "
            f"Health is {health}. Proceed with standard risk management.",
            "FIRE",
            f"{health} signal — {sig.confidence}% confidence"
        )
    return (
        "Signal has merit but carries meaningful risks. Reduce lot size and monitor carefully.",
        "CAUTION",
        "Mixed signals — trade with caution"
    )

def _parse_coordinator(text):
    verdict = "CAUTION"
    reason  = ""
    upper   = text.upper()
    if "VERDICT: FIRE" in upper:         verdict = "FIRE"
    elif "VERDICT: NO TRADE" in upper:   verdict = "NO TRADE"
    elif "VERDICT: CAUTION" in upper:    verdict = "CAUTION"
    for line in text.split("\n"):
        if line.upper().startswith("REASON:"):
            reason = line.split(":",1)[-1].strip()
            break
    return text, verdict, reason


# ── Main ──────────────────────────────────────────────────────────────────────

async def generate_agents_async(sig) -> AgentReport:
    summary = _build_summary(sig)

    # Agents 1-6 run concurrently
    tech, risk, sess, devil, news, fundamental = await asyncio.gather(
        _ask_gemini(_technical_prompt(sig, summary),  _fallback_technical(sig)),
        _ask_gemini(_risk_prompt(sig, summary),       _fallback_risk(sig)),
        _ask_gemini(_session_prompt(sig, summary),    _fallback_session(sig)),
        _ask_gemini(_devil_prompt(sig, summary),      _fallback_devil(sig)),
        _ask_gemini(_news_prompt(sig, summary),       _fallback_news(sig)),
        _ask_gemini(_fundamental_prompt(sig, summary),_fallback_fundamental(sig)),
    )

    # Agent 7: Coordinator (needs agents 1-6 output)
    coord_raw = await _ask_gemini(
        _coordinator_prompt(sig, summary, tech, risk, sess, devil, news, fundamental),
        fallback="",
        max_tokens=200,
    )

    health, health_emoji = _health(sig.confidence, sig.confluence, sig.mtf_aligned, sig.warnings)
    dq = _data_quality(sig.confluence, sig.mtf_aligned, sig.adx)

    if coord_raw:
        coord_text, verdict, verdict_reason = _parse_coordinator(coord_raw)
    else:
        coord_text, verdict, verdict_reason = _fallback_coordinator(sig, health)

    return AgentReport(
        technical=tech, risk=risk, session=sess,
        devils_advocate=devil, news_sentiment=news,
        fundamental=fundamental, coordinator=coord_text,
        verdict=verdict, verdict_reason=verdict_reason,
        health=health, health_emoji=health_emoji, data_quality=dq,
    )


def generate_agents(sig) -> AgentReport:
    """Sync wrapper — drop-in replacement."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, generate_agents_async(sig))
                return future.result()
        else:
            return loop.run_until_complete(generate_agents_async(sig))
    except Exception:
        health, health_emoji = _health(sig.confidence, sig.confluence, sig.mtf_aligned, sig.warnings)
        dq = _data_quality(sig.confluence, sig.mtf_aligned, sig.adx)
        coord_text, verdict, verdict_reason = _fallback_coordinator(sig, health)
        return AgentReport(
            technical=_fallback_technical(sig),
            risk=_fallback_risk(sig),
            session=_fallback_session(sig),
            devils_advocate=_fallback_devil(sig),
            news_sentiment=_fallback_news(sig),
            fundamental=_fallback_fundamental(sig),
            coordinator=coord_text,
            verdict=verdict, verdict_reason=verdict_reason,
            health=health, health_emoji=health_emoji, data_quality=dq,
        )