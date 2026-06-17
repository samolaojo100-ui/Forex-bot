async def analyze_pair(pair: str, tf_data: dict, account_balance: float):
    """
    Now async because news_filter uses async HTTP.
    Returns Signal on valid trade, or dict {"no_trade": True, "reasons": [...]} 
    when conditions aren't right, or None to silently skip.
    """
    from news_filter import check_news_block

    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    no_trade_reasons = []

    # ── GATE 1: News filter ─────────────────────────────────────────
    news_blocked, news_reason = await check_news_block(pair)
    if news_blocked:
        no_trade_reasons.append(news_reason)

    # ── GATE 2: Daily trend must agree ──────────────────────────────
    d_trend = daily_trend(processed)
    o_dir = overall_direction(tf_data, processed)
    if d_trend is not None and d_trend != o_dir:
        no_trade_reasons.append(
            f"📉 Daily trend is {d_trend} but signal is {o_dir} — counter-trend"
        )

    tf_sigs = []
    total_ind = 0
    for tf, df in processed.items():
        tfs = analyze_tf(df, pair, tf, account_balance, o_dir)
        tf_sigs.append(tfs)
        total_ind += tfs.indicators

    agreed = sum(1 for t in tf_sigs if t.agrees)
    score = total_ind

    # ── GATE 3: Score too low ────────────────────────────────────────
    if score < 6:
        no_trade_reasons.append(f"📊 Signal score too low ({score}/25 — need ≥6)")

    # ── GATE 4: Not enough TFs agree ─────────────────────────────────
    if agreed < 2:
        no_trade_reasons.append(
            f"🔀 MTF alignment weak ({agreed}/{len(tf_sigs)} TFs agree)"
        )

    # ── GATE 5: S/R proximity ────────────────────────────────────────
    main_tf = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])
    sr_ref_df = processed.get("1h") or processed.get("4h") or list(processed.values())[-1]
    sr_warning = check_sr_proximity(main_tf.entry, o_dir, sr_ref_df)
    if sr_warning:
        score = max(0, score - 3)
        if score < 6:
            no_trade_reasons.append(f"🧱 Entry too close to structure — {sr_warning}")

    # ── If ANY gate fired → return NO TRADE ─────────────────────────
    if no_trade_reasons:
        return {
            "no_trade": True,
            "pair": pair,
            "direction": o_dir,
            "reasons": no_trade_reasons,
            "conviction": round((agreed / len(tf_sigs)) * 100),
        }

    # ── All gates passed → valid signal ─────────────────────────────
    conf_pct = agreed / len(tf_sigs)
    if conf_pct >= 0.8:   confidence = "VERY HIGH"
    elif conf_pct >= 0.6: confidence = "HIGH"
    elif conf_pct >= 0.4: confidence = "MEDIUM"
    else:                 confidence = "LOW"

    risk_usd = round(account_balance * RISK_PERCENT / 100, 2)

    return Signal(
        pair=pair, direction=o_dir,
        entry=main_tf.entry, score=score,
        confidence=confidence,
        tfs_agreed=agreed, total_tfs=len(tf_sigs),
        tf_signals=tf_sigs,
        asset_type="CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount=risk_usd,
        sr_warning=sr_warning,
    )