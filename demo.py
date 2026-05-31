from datetime import datetime, timezone
from signal_engine import Signal, TFSignal


def make_tf(tf, direction, entry, sl, tp, sl_p, tp_p, lot, inds, conf, rsi, stoch, macd, agrees):
    return TFSignal(
        tf=tf, direction=direction, entry=entry, stop_loss=sl, take_profit=tp,
        sl_pips=sl_p, tp_pips=tp_p, lot_size=lot, indicators=inds,
        confirmed=conf, rsi=rsi, stoch=stoch, macd=macd, agrees=agrees,
    )


def generate_demo_signals():
    entry = 1.16526
    signals = []

    # EUR/USD BUY demo
    tf_sigs = [
        make_tf("5min",  "BUY",  entry, 1.16476, 1.16609, 5.0,  8.3,  2.00, 3, ["EMA","MACD","RSI"],        58.23, 76.74, 0.00005,  True),
        make_tf("15min", "SELL", entry, 1.16626, 1.16359, 10.0, 16.7, 1.00, 3, ["MACD","Bollinger","Stochastic"], 69.34, 82.43, 0.00018, False),
        make_tf("1h",    "BUY",  entry, 1.16286, 1.16886, 24.0, 36.0, 0.42, 3, ["EMA","MACD","RSI"],        72.22, 86.71, 0.00075,  True),
        make_tf("4h",    "BUY",  entry, 1.16116, 1.17141, 41.0, 61.5, 0.24, 3, ["EMA","MACD","RSI"],        59.44, 88.25, 0.00051,  True),
        make_tf("1day",  "BUY",  entry, 1.15453, 1.18243, 107.3,171.7,0.09, 3, ["MACD","RSI","Bollinger"],  56.47, 87.95,-0.00228,  True),
    ]
    signals.append(Signal(
        pair="EUR/USD", direction="BUY", entry=entry,
        score=15, confidence="VERY HIGH", tfs_agreed=4, total_tfs=5,
        tf_signals=tf_sigs, asset_type="FOREX", risk_amount=0.20,
    ))

    # BTC/USD BUY demo
    btc_entry = 67842.00
    tf_sigs_btc = [
        make_tf("5min",  "BUY",  btc_entry, 67100.00, 68900.00, 742,  1058, 0.0003, 4, ["EMA","MACD","RSI","Stochastic"], 52.1, 61.3, 12.50, True),
        make_tf("15min", "BUY",  btc_entry, 66800.00, 69200.00, 1042, 1358, 0.0002, 3, ["EMA","MACD","Bollinger"],        48.3, 55.7, 18.20, True),
        make_tf("1h",    "BUY",  btc_entry, 66100.00, 71326.00, 1742, 3484, 0.0001, 3, ["EMA","MACD","RSI"],              45.2, 52.4, 25.80, True),
        make_tf("4h",    "SELL", btc_entry, 68900.00, 65200.00, 1058, 2642, 0.0001, 2, ["MACD","Stochastic"],             61.4, 72.1, -8.40, False),
        make_tf("1day",  "BUY",  btc_entry, 64000.00, 74000.00, 3842, 6158, 0.0000, 3, ["EMA","RSI","Bollinger"],         43.8, 48.9, 45.20, True),
    ]
    signals.append(Signal(
        pair="BTC/USD", direction="BUY", entry=btc_entry,
        score=15, confidence="HIGH", tfs_agreed=4, total_tfs=5,
        tf_signals=tf_sigs_btc, asset_type="CRYPTO", risk_amount=0.20,
    ))

    return signals


def format_demo_signal(sig, index: int, total: int) -> str:
    from formatter import format_signal
    msg = format_signal(sig, index, total)
    # mark as demo
    msg = msg.replace("📌 _Signal", "📌 _\\[DEMO\\] Signal")
    return msg
