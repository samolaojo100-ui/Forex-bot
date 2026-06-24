"""
signal_agents.py — TrendGuard AI
Generates AI-powered reasoning for each signal using Google Gemini API.
Four agents: Technical, Risk, Session, Devil's Advocate.
"""

import os
import json
import asyncio
import aiohttp
from dataclasses import dataclass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent?key=" + GEMINI_API_KEY
)


@dataclass
class AgentReport:
    technical:       str
    risk:            str
    session:         str
    devils_advocate: str
    health:          str   # STRONG / MODERATE / CAUTION / WEAK
    health_emoji:    str
    data_quality:    int   # 0-100


# ── Helpers (kept as fallback) ────────────────────────────────────────────────

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
    if mtf:       q += 10
    if adx > 25:  q += 10
    return min(q, 100)


# ── Gemini API call ───────────────────────────────────────────────────────────

async def _ask_gemini(prompt: str, fallback: str) -> str:
    """Call Gemini API. Returns fallback string if anything fails."""
    if not GEMINI_API_KEY:
        return fallback
    try:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 120,
            }
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GEMINI_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10)
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
    return (
        f"Pair: {sig.symbol} | Direction: {sig.direction} | "
        f"Confidence: {sig.confidence}% | Confluence: {sig.confluence}/8 | "
        f"RSI: {sig.rsi} | MACD: {sig.macd_signal} | Stoch: {sig.stoch_signal} | "
        f"BB: {sig.bb_signal} | CCI: {sig.cci_signal} | Williams: {sig.williams_signal} | "
        f"ADX: {sig.adx} | ATR: {getattr(sig, 'atr', 'N/A')} | "
        f"Trend: {sig.trend} | MTF Aligned: {sig.mtf_aligned} | "
        f"Volatility: {sig.volatility} | Session: {sig.session} | "
        f"Session Quality: {sig.session_quality} | R:R Ratio: {sig.rr_ratio} | "
        f"Risk USD: ${sig.risk_usd} | Candle Pattern: {getattr(sig, 'candle_pattern', 'None')} | "
        f"Warnings: {sig.warnings} | News: {getattr(sig, 'news_reason', 'None')}"
    )


# ── Four agent prompts ────────────────────────────────────────────────────────

def _technical_prompt(sig, summary: str) -> str:
    return (
        f"You are the Technical Analysis Agent for TrendGuard AI, a forex/crypto trading signals bot.\n"
        f"Signal data: {summary}\n\n"
        f"In 2-3 sentences max, explain WHY the technical indicators support this {sig.direction} signal. "
        f"Mention the strongest confirming indicators and any counter-signals. "
        f"Be specific, concise, and professional. No bullet points."
    )


def _risk_prompt(sig, summary: str) -> str:
    return (
        f"You are the Risk Management Agent for TrendGuard AI.\n"
        f"Signal data: {summary}\n\n"
        f"In 2-3 sentences max, assess the risk profile of this trade. "
        f"Comment on the R:R ratio ({sig.rr_ratio}), volatility ({sig.volatility}), "
        f"and any warnings. Recommend lot size discipline. "
        f"Be concise and direct. No bullet points."
    )


def _session_prompt(sig, summary: str) -> str:
    return (
        f"You are the Session Timing Agent for TrendGuard AI.\n"
        f"Signal data: {summary}\n\n"
        f"In 2 sentences max, comment on whether the current session ({sig.session}, "
        f"quality: {sig.session_quality}) is favourable for trading {sig.symbol}. "
        f"Be concise. No bullet points."
    )


def _devil_prompt(sig, summary: str) -> str:
    return (
        f"You are the Devil's Advocate Agent for TrendGuard AI. Your job is to challenge the signal.\n"
        f"Signal data: {summary}\n\n"
        f"In 2-3 sentences max, identify the biggest risks or weaknesses in this {sig.direction} setup. "
        f"What could go wrong? Be honest and sharp. No bullet points."
    )


# ── Fallback rule-based texts (used if Gemini fails) ─────────────────────────

def _fallback_technical(sig) -> str:
    d = sig.direction
    bullish, bearish = [], []
    if sig.rsi < 35:              bullish.append("RSI deeply oversold")
    elif sig.rsi > 65:            bearish.append("RSI overbought")
    if sig.macd_signal == "BUY":  bullish.append("MACD bullish crossover")
    elif sig.macd_signal == "SELL": bearish.append("MACD bearish crossover")
    if sig.bb_signal == "BUY":    bullish.append("price near lower BB")
    elif sig.bb_signal == "SELL": bearish.append("price near upper BB")
    factors = bullish if d == "BUY" else bearish
    counter = bearish if d == "BUY" else bullish
    txt = f"{'Bullish' if d=='BUY' else 'Bearish'} case: {', '.join(factors[:3]) or 'limited confirmation'}."
    if counter: txt += f" Counter-signals: {', '.join(counter[:2])}."
    txt += " MTF aligned ✅." if sig.mtf_aligned else " Mixed timeframes ⚠️."
    return txt


def _fallback_risk(sig) -> str:
    rr = "Excellent R:R." if sig.rr_ratio >= 2.5 else ("Acceptable R:R." if sig.rr_ratio >= 1.5 else "Tight R:R — reduce lot.")
    vol = "High volatility — widen SL." if "High" in sig.volatility else ("Low volatility — TP may be slow." if "Low" in sig.volatility else "Normal volatility.")
    warn = f" Note: {sig.warnings[0]}" if sig.warnings else ""
    return f"{rr} {vol}{warn} Risk fixed at 1% (${sig.risk_usd})."


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


def _fallback_devil(sig) -> str:
    risks = []
    if not sig.mtf_aligned:        risks.append("timeframes not aligned")
    if sig.adx < 20:               risks.append("ADX below 20 — weak trend")
    if "Ranging" in sig.trend:     risks.append("market is ranging")
    if "High" in sig.volatility:   risks.append("high volatility risk")
    if sig.confluence < 5:         risks.append(f"only {sig.confluence}/8 indicators confirm")
    if risks:
        return f"Be cautious: {'; '.join(risks[:3])}. Always respect your SL."
    return "No major red flags. Setup looks clean — stick to the plan."


# ── Main entry point ──────────────────────────────────────────────────────────

async def generate_agents_async(sig) -> AgentReport:
    """Async version — calls Gemini for all 4 agents concurrently."""
    summary = _build_summary(sig)

    tech_task   = _ask_gemini(_technical_prompt(sig, summary), _fallback_technical(sig))
    risk_task   = _ask_gemini(_risk_prompt(sig, summary),      _fallback_risk(sig))
    sess_task   = _ask_gemini(_session_prompt(sig, summary),   _fallback_session(sig))
    devil_task  = _ask_gemini(_devil_prompt(sig, summary),     _fallback_devil(sig))

    tech, risk, sess, devil = await asyncio.gather(
        tech_task, risk_task, sess_task, devil_task
    )

    health, health_emoji = _health(sig.confidence, sig.confluence, sig.mtf_aligned, sig.warnings)
    dq = _data_quality(sig.confluence, sig.mtf_aligned, sig.adx)

    return AgentReport(
        technical=tech,
        risk=risk,
        session=sess,
        devils_advocate=devil,
        health=health,
        health_emoji=health_emoji,
        data_quality=dq,
    )


def generate_agents(sig) -> AgentReport:
    """Sync wrapper — drop-in replacement for the old function."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already inside an async context (e.g. bot polling)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, generate_agents_async(sig))
                return future.result()
        else:
            return loop.run_until_complete(generate_agents_async(sig))
    except Exception:
        # Full fallback — pure rule-based, no API
        health, health_emoji = _health(sig.confidence, sig.confluence, sig.mtf_aligned, sig.warnings)
        dq = _data_quality(sig.confluence, sig.mtf_aligned, sig.adx)
        return AgentReport(
            technical=_fallback_technical(sig),
            risk=_fallback_risk(sig),
            session=_fallback_session(sig),
            devils_advocate=_fallback_devil(sig),
            health=health,
            health_emoji=health_emoji,
            data_quality=dq,
        )
