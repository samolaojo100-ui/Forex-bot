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
            f"  Trend:    {regime.get('trend', '—')}\n"
            f"  Phase:    {regime.get('phase', '—')} (ADX {regime.get('adx', '—')})\n"
            f"  Volatility: {regime.get('volatility', '—')}\n"
            f"  Session:  {regime.get('session', '—')} — Quality: {regime.get('session_quality', '—')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
    else:
        regime_block = ""

    tf_blocks = "\n\n".join(fmt_tf_block(t, i) for i, t in enumerate(sig.tf_signals, 1))

    return (
        f"📊 *{sig.pair}* {d_emoji} *{sig.direction}*\n"
        f"⏰ {now}\n"
        f"Conviction: {c_emoji} *{sig.confidence}* ({conviction}%) — {sig.tfs_agreed}/{sig.total_tfs} TFs\n"
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