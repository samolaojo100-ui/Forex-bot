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
  7. Coordinator    — synthesizes all agents, final verdict (FIRE / NO TRADE)
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
    news_sentiment:   str   # NEW
    fundamental:      str   # NEW
    coordinator:      str   # NEW
    verdict:          str   # FIRE / NO TRADE / CAUTION
    verdict_reason:   str   # one-line reason
    health:           str   # STRONG / MODERATE / CAUTION / WEAK
    health_emoji:     str
    data_quality:     int   # 0-100


# ── Health & Data Quality ─────────────────────────────────────────────────────

def _health(confidence: int, confluence: int, mtf: bool, warnings: list) -> tuple:
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


def _data_quality(confluence: int, mtf: bool, adx: float) -> int:
    q = 50
    q += confluence * 5
    if mtf:      q += 10
    if adx > 25: q += 10
    return min(q, 100)


# ── Gemini API call ───────────────────────────────────────────────────────────

async def _ask_gemini(prompt: str, fallback: str, max_tokens: int = 120) -> str:
    if not GEMINI_API_KEY:
        return fallback
    try:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": max_tokens,
            }
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


# ── Signal summary builder ────────────────────────────────────────────────────

def _build_summary(sig) -> str:
    news_part = ""
    if hasattr(sig, "news_bullish"):
        news_part = (
            f"News Bullish Headlines: {sig.news_bullish} | "
            f"News Bearish Headlines: {sig.news_bearish} | "
            f"News Sentiment: {sig.news_sentiment} | "
        )
    tp_part = ""
    if hasattr(sig, "tp_reachable"):
        tp_part = (
            f"TP Reachable: {sig.tp_reachable} | "
            f"TP Reach Reason: {getattr(sig, 'tp_reach_reason', 'N/A')} | "
        )
    return (
        f"Pair: {getattr(sig, 'symbol', sig.pair)} | "
        f"Direction: {sig.direction} | "
        f"Confidence: {sig.confidence}% | "
        f"Confluence: {sig.confluence}/8 | "
        f"RSI: {sig.rsi} | MACD: {sig.macd_signal} | "
        f"Stoch: {sig.stoch_signal} | BB: {sig.bb_signal} | "
        f"CCI: {sig.cci_signal} | Williams: {sig.williams_signal} | "
        f"ADX: {sig.adx} | Trend: {sig.trend} | "
        f"MTF Aligned: {sig.mtf_aligned} | "
        f"Volatility: {sig.volatility} | Session: {sig.session} | "
        f"Session Quality: {sig.session_quality} | "
        f"R:R Ratio: {sig.rr_ratio} | Risk USD: ${sig.risk_usd} | "
        f"Candle Pattern: {getattr(sig, 'candle_pattern', 'None')} | "
        f"{news_part}"
        f"{tp_part}"
        f"Warnings: {sig.warnings} | "
        f"News Event: {getattr(sig, 'news_reason', 'None')}"
    )


# ── Agent 1: Technical ────────────────────────────────────────────────────────

def _technical_prompt(sig, summary: str) -> str:
    return (
        f"You are the Technical Analysis Agent for TrendGuard AI.\n"
        f"Signal data: {summary}\n\n"
        f"In 2-3 sentences, explain WHY the technical indicators support "
        f"this {sig.direction} signal on {getattr(sig, 'symbol', sig.pair)}. "
        f"Mention the strongest confirming indicators and any counter-signals. "
        f"Be specific, concise, and professional. No bullet points."
    )

def _fallback_technical(sig) -> str:
    d = sig.direction
    bullish, bearish = [], []
    if sig.rsi < 35:                bullish.append("RSI deeply oversold")
    elif sig.rsi > 65:              bearish.append("RSI overbought")
    if sig.macd_signal == "BUY":    bullish.append("MACD bullish crossover")
    elif sig.macd_signal == "SELL": bearish.append("MACD bearish crossover")
    if sig.bb_signal == "BUY":      bullish.append("price near lower BB")
    elif sig.bb_signal == "SELL":   bearish.append("price near upper BB")
    factors = bullish if d == "BUY" else bearish
    counter = bearish if d == "BUY" else bullish
    txt = f"{'Bullish' if d=='BUY' else 'Bearish'} case: {', '.join(factors[:3]) or 'limited confirmation'}."
    if counter: txt += f" Counter-signals: {', '.join(counter[:2])}."
    txt += " MTF aligned ✅." if sig.mtf_aligned else " Mixed timeframes ⚠️."
    return txt


# ── Agent 2: Risk ─────────────────────────────────────────────────────────────

def _risk_prompt(sig, summary: str) -> str:
    return (
        f"You are the Risk Management Agent for TrendGuard AI.\n"
        f"Signal data: {summary}\n\n"
        f"In 2-3 sentences, assess the risk profile of this trade. "
        f"Comment on R:R ratio ({sig.rr_ratio}), volatility ({sig.volatility}), "
        f"TP reachability, and any warnings. Recommend lot size discipline. "
        f"Be concise and direct. No bullet points."
    )

def _fallback_risk(sig) -> str:
    rr  = "Excellent R:R." if sig.rr_ratio >= 2.5 else ("Acceptable R:R." if sig.rr_ratio >= 1.5 else "Tight R:R — reduce lot.")
    vol = "High volatility — widen SL." if "High" in sig.volatility else ("Low volatility — TP may be slow." if "Low" in sig.volatility else "Normal volatility.")
    tp  = f" ⚠️ TP concern: {sig.tp_reach_reason}." if hasattr(sig, "tp_reachable") and not sig.tp_reachable else ""
    warn = f" Note: {sig.warnings[0]}" if sig.warnings else ""
    return f"{rr} {vol}{tp}{warn} Risk fixed at 1% (${sig.risk_usd})."


# ── Agent 3: Session ──────────────────────────────────────────────────────────

def _session_prompt(sig, summary: str) -> str:
    return (
        f"You are the Session Timing Agent for TrendGuard AI.\n"
        f"Signal data: {summary}\n\n"
        f"In 2 sentences, comment on whether the current session "
        f"({sig.session}, quality: {sig.session_quality}) is favourable "
        f"for trading {getattr(sig, 'symbol', sig.pair)}. "
        f"Be concise. No bullet points."
    )

def _fallback_session(sig) -> str:
    tips = {
        "London": "London session — strong EUR/GBP moves likely.",
        "New York": "NY session — high liquidity for USD pairs.",
        "London/NY Overlap": "Peak overlap — highest volume.",
        "Tokyo": "Tokyo session — best for JPY/AUD pairs.",
        "Sydney": "Sydney session — lighter volume.",
    }
    for k, v in tips.items():
        if k in sig.session:
            return v
    return "Off-peak hours — expect slower price action."


# ── Agent 4: Devil's Advocate ─────────────────────────────────────────────────

def _devil_prompt(sig, summary: str) -> str:
    return (
        f"You are the Devil's Advocate Agent for TrendGuard AI. "
        f"Your job is to challenge the signal and protect the trader.\n"
        f"Signal data: {summary}\n\n"
        f"In 2-3 sentences, identify the biggest risks or weaknesses "
        f"in this {sig.direction} setup on {getattr(sig, 'symbol', sig.pair)}. "
        f"Include news risk and TP reachability if relevant. "
        f"Be honest and sharp. No bullet points."
    )

def _fallback_devil(sig) -> str:
    risks = []
    if not sig.mtf_aligned:      risks.append("timeframes not aligned")
    if sig.adx < 20:             risks.append("ADX below 20 — weak trend")
    if "Ranging" in sig.trend:   risks.append("market is ranging")
    if "High" in sig.volatility: risks.append("high volatility risk")
    if sig.confluence < 5:       risks.append(f"only {sig.confluence}/8 indicators confirm")
    if hasattr(sig, "tp_reachable") and not sig.tp_reachable:
        risks.append(f"TP may be unreachable: {sig.tp_reach_reason}")
    if hasattr(sig, "news_sentiment") and sig.news_sentiment in ("BEARISH", "BULLISH"):
        if (sig.news_sentiment == "BEARISH" and sig.direction == "BUY") or \
           (sig.news_sentiment == "BULLISH" and sig.direction == "SELL"):
            risks.append(f"news sentiment conflicts with {sig.direction}")
    if risks:
        return f"Be cautious: {'; '.join(risks[:3])}. Always respect your SL."
    return "No major red flags. Setup looks clean — stick to the plan."


# ── Agent 5: News Sentiment ───────────────────────────────────────────────────

def _news_sentiment_prompt(sig, summary: str) -> str:
    bullish  = getattr(sig, "news_bullish", 0)
    bearish  = getattr(sig, "news_bearish", 0)
    sentiment = getattr(sig, "news_sentiment", "NEUTRAL")
    news_event = getattr(sig, "news_reason", "None")
    return (
        f"You are the News Sentiment Agent for TrendGuard AI.\n"
        f"Signal: {getattr(sig, 'symbol', sig.pair)} {sig.direction}\n"
        f"News data: {bullish} bullish headlines, {bearish} bearish headlines, "
        f"overall sentiment: {sentiment}. Upcoming event: {news_event}.\n"
        f"Full context: {summary}\n\n"
        f"In 2-3 sentences, assess how current news sentiment affects this "
        f"{sig.direction} trade. Flag any high-impact upcoming events. "
        f"Be direct. No bullet points."
    )

def _fallback_news_sentiment(sig) -> str:
    bullish   = getattr(sig, "news_bullish", 0)
    bearish   = getattr(sig, "news_bearish", 0)
    sentiment = getattr(sig, "news_sentiment", "NEUTRAL")
    event     = getattr(sig, "news_reason", "")

    if sentiment == "NEUTRAL":
        base = "News sentiment is neutral — no significant headline bias."
    elif sentiment == "BULLISH":
        base = f"News sentiment is bullish ({bullish} headlines)."
        if sig.direction == "SELL":
            base += " This conflicts with the SELL signal — caution advised."
    elif sentiment == "BEARISH":
        base = f"News sentiment is bearish ({bearish} headlines)."
        if sig.direction == "BUY":
            base += " This conflicts with the BUY signal — caution advised."
    else:
        base = f"Mixed news sentiment ({bullish} bullish, {bearish} bearish) — no clear bias."

    if event:
        base += f" High-impact event nearby: {event}."
    return base


# ── Agent 6: Fundamental ──────────────────────────────────────────────────────

def _fundamental_prompt(sig, summary: str) -> str:
    pair = getattr(sig, "symbol", sig.pair)
    is_gold   = "XAU" in pair.upper()
    is_crypto = any(c in pair.upper() for c in ["BTC", "ETH", "BNB", "SOL", "XRP"])

    if is_gold:
        context = (
            "Gold is influenced by: USD strength (DXY), real yields, "
            "safe-haven demand, Fed policy, and geopolitical risk."
        )
    elif is_crypto:
        context = (
            "Crypto is influenced by: risk appetite, BTC dominance, "
            "regulatory news, macro liquidity, and sentiment."
        )
    else:
        context = (
            "Forex is influenced by: interest rate differentials, "
            "central bank policy, economic data, and DXY strength."
        )

    return (
        f"You are the Fundamental Analysis Agent for TrendGuard AI.\n"
        f"{context}\n"
        f"Signal data: {summary}\n\n"
        f"In 2-3 sentences, assess the fundamental/macro backdrop for this "
        f"{sig.direction} trade on {pair}. Consider news sentiment "
        f"({getattr(sig, 'news_sentiment', 'NEUTRAL')}), upcoming events, "
        f"and whether macro conditions support the {sig.direction} direction. "
        f"Be specific and professional. No bullet points."
    )

def _fallback_fundamental(sig) -> str:
    pair      = getattr(sig, "symbol", sig.pair)
    sentiment = getattr(sig, "news_sentiment", "NEUTRAL")
    direction = sig.direction
    is_gold   = "XAU" in pair.upper()

    if is_gold:
        if direction == "BUY":
            return (
                f"Gold fundamentals: assess USD weakness and safe-haven demand. "
                f"News sentiment is {sentiment}. "
                f"BUY valid if DXY is weak and risk-off mood persists."
            )
        else:
            return (
                f"Gold fundamentals: USD strength and risk-on mood pressures gold. "
                f"News sentiment is {sentiment}. "
                f"SELL valid if DXY strengthens and yields rise."
            )
    else:
        if sentiment in ("BEARISH", "BULLISH"):
            align = "aligns with" if (
                (sentiment == "BULLISH" and direction == "BUY") or
                (sentiment == "BEARISH" and direction == "SELL")
            ) else "conflicts with"
            return (
                f"Macro backdrop: news sentiment is {sentiment}, which {align} "
                f"the {direction} signal on {pair}. "
                f"Monitor upcoming economic events for volatility risk."
            )
        return (
            f"Macro backdrop is neutral for {pair}. "
            f"No strong fundamental bias detected. "
            f"Technical edge is the primary driver for this {direction} signal."
        )


# ── Agent 7: Coordinator ──────────────────────────────────────────────────────

def _coordinator_prompt(
    sig, summary: str,
    tech: str, risk: str, session: str,
    devil: str, news: str, fundamental: str
) -> str:
    return (
        f"You are the Coordinator Agent for TrendGuard AI. "
        f"Your job is to synthesize all other agents and make the FINAL trading verdict.\n\n"
        f"Signal: {getattr(sig, 'symbol', sig.pair)} {sig.direction} | "
        f"Confidence: {sig.confidence}% | TP Reachable: {getattr(sig, 'tp_reachable', True)}\n\n"
        f"TECHNICAL AGENT: {tech}\n"
        f"RISK AGENT: {risk}\n"
        f"SESSION AGENT: {session}\n"
        f"DEVIL'S ADVOCATE: {devil}\n"
        f"NEWS SENTIMENT AGENT: {news}\n"
        f"FUNDAMENTAL AGENT: {fundamental}\n\n"
        f"Full data: {summary}\n\n"
        f"Based on ALL agents above, give your final verdict in this EXACT format:\n"
        f"VERDICT: [FIRE / CAUTION / NO TRADE]\n"
        f"REASON: [one sentence explaining why]\n"
        f"SUMMARY: [2-3 sentences synthesizing the key points from all agents]\n\n"
        f"Rules:\n"
        f"- FIRE: strong alignment across technical, fundamental, and news\n"
        f"- CAUTION: signal is valid but has meaningful risks or conflicts\n"
        f"- NO TRADE: TP unreachable, major agent conflict, or news blocks the trade\n"
        f"Be decisive. No hedging."
    )

def _fallback_coordinator(sig, health: str) -> tuple:
    """Returns (coordinator_text, verdict, verdict_reason)"""
    tp_ok     = getattr(sig, "tp_reachable", True)
    sentiment = getattr(sig, "news_sentiment", "NEUTRAL")
    conflicts = (
        (sentiment == "BEARISH" and sig.direction == "BUY") or
        (sentiment == "BULLISH" and sig.direction == "SELL")
    )

    if not tp_ok:
        return (
            f"TP is unreachable — trade structurally unfireable despite directional edge.",
            "NO TRADE",
            getattr(sig, "tp_reach_reason", "TP blocked")
        )
    if conflicts and sig.confidence < 75:
        return (
            f"News sentiment conflicts with {sig.direction} and confidence is below 75%. "
            f"Directional edge is unclear — stand down.",
            "NO TRADE",
            f"News sentiment conflicts with {sig.direction}"
        )
    if health in ("STRONG", "MODERATE") and not conflicts:
        return (
            f"Technical and fundamental alignment supports {sig.direction}. "
            f"Signal health is {health}. Proceed with standard risk management.",
            "FIRE",
            f"{health} signal with {sig.confidence}% confidence"
        )
    return (
        f"Signal has merit but carries meaningful risks. "
        f"Reduce lot size and monitor price action carefully.",
        "CAUTION",
        f"Mixed signals — trade with caution"
    )


def _parse_coordinator_response(text: str) -> tuple:
    """Parse Gemini coordinator response into (full_text, verdict, reason)."""
    verdict = "CAUTION"
    reason  = ""

    lines = text.upper()
    if "VERDICT: FIRE" in lines:       verdict = "FIRE"
    elif "VERDICT: NO TRADE" in lines: verdict = "NO TRADE"
    elif "VERDICT: CAUTION" in lines:  verdict = "CAUTION"

    # Extract REASON line
    for line in text.split("\n"):
        if line.upper().startswith("REASON:"):
            reason = line.split(":", 1)[-1].strip()
            break

    return text, verdict, reason


# ── Main async entry point ────────────────────────────────────────────────────

async def generate_agents_async(sig) -> AgentReport:
    """Calls all 7 agents — first 6 concurrently, then Coordinator."""
    summary = _build_summary(sig)

    # ── Run agents 1-6 concurrently ──────────────────────────────────
    (
        tech, risk, sess, devil, news_text, fundamental_text
    ) = await asyncio.gather(
        _ask_gemini(_technical_prompt(sig, summary),       _fallback_technical(sig)),
        _ask_gemini(_risk_prompt(sig, summary),            _fallback_risk(sig)),
        _ask_gemini(_session_prompt(sig, summary),         _fallback_session(sig)),
        _ask_gemini(_devil_prompt(sig, summary),           _fallback_devil(sig)),
        _ask_gemini(_news_sentiment_prompt(sig, summary),  _fallback_news_sentiment(sig)),
        _ask_gemini(_fundamental_prompt(sig, summary),     _fallback_fundamental(sig)),
    )

    # ── Agent 7: Coordinator (needs other agents' output) ────────────
    coord_raw = await _ask_gemini(
        _coordinator_prompt(sig, summary, tech, risk, sess, devil, news_text, fundamental_text),
        fallback="",
        max_tokens=200,
    )

    health, health_emoji = _health(sig.confidence, sig.confluence, sig.mtf_aligned, sig.warnings)
    dq = _data_quality(sig.confluence, sig.mtf_aligned, sig.adx)

    if coord_raw:
        coord_text, verdict, verdict_reason = _parse_coordinator_response(coord_raw)
    else:
        coord_text, verdict, verdict_reason = _fallback_coordinator(sig, health)

    return AgentReport(
        technical=tech,
        risk=risk,
        session=sess,
        devils_advocate=devil,
        news_sentiment=news_text,
        fundamental=fundamental_text,
        coordinator=coord_text,
        verdict=verdict,
        verdict_reason=verdict_reason,
        health=health,
