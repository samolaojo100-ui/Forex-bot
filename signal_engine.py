import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from indicators import compute_indicators, support_resistance, detect_candle_pattern
from config import (
    RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO,
    CONFIDENCE_THRESHOLD, MIN_CONFLUENCE, REQUIRE_MTF_ALIGNED,
)
from session_manager import get_current_session

logger = logging.getLogger(__name__)

GOLD_PAIRS   = {"XAU/USD", "XAUUSD"}
SILVER_PAIRS = {"XAG/USD", "XAGUSD"}


@dataclass
class Signal:
    pair:             str
    direction:        str
    confidence:       int
    confluence:       int
    mtf_aligned:      bool
    entry:            float
    sl:               float
    tp1:              float
    tp2:              float
    tp3:              float
    partial_tp:       float
    invalidation:     float
    sl_pips:          float
    tp1_pips:         float
    tp2_pips:         float
    tp3_pips:         float
    rr_ratio:         float
    lot_size:         float
    risk_usd:         float
    asset_type:       str
    trend:            str
    volatility:       str
    session:          str
    session_quality:  str
    adx:              float
    rsi:              float
    macd_signal:      str
    stoch_signal:     str
    cci_signal:       str
    williams_signal:  str
    bb_signal:        str
    candle_pattern:   str
    tf_breakdown:     dict = field(default_factory=dict)
    news_blocked:     bool = False
    news_reason:      str  = ""
    news_bullish:     int  = 0
    news_bearish:     int  = 0
    news_sentiment:   str  = ""
    tp_reachable:     bool = True
    tp_reach_reason:  str  = ""
    no_trade:         bool = False
    no_trade_reasons: list = field(default_factory=list)
    warnings:         list = field(default_factory=list)
    symbol:           str  = ""


def is_crypto(pair): return pair in CRYPTO_PAIRS
def is_gold(pair):   return pair.upper().replace("/","") in {"XAUUSD"}
def is_silver(pair): return pair.upper().replace("/","") in {"XAGUSD"}

def pip_value(pair, price):
    if is_crypto(pair): return 1.0
    if is_gold(pair):   return 0.1
    if is_silver(pair): return 0.01
    return 0.01 if "JPY" in pair else 0.0001

def price_to_pips(pair, a, b):
    return round(abs(a-b)/pip_value(pair,(a+b)/2),1)

def calc_lot(pair, sl_pips, balance, price):
    risk_usd = balance * RISK_PERCENT / 100
    if is_crypto(pair): return round(risk_usd/max(sl_pips,0.01),4)
    if is_gold(pair) or is_silver(pair): return max(0.01,round(risk_usd/(sl_pips*1.0),2))
    pip_usd = 10 if "JPY" not in pair else 9.09
    return max(0.01,round(risk_usd/(sl_pips*pip_usd),2))

def decimal_places(pair, price):
    if is_crypto(pair) and price>100: return 2
    if is_gold(pair) or is_silver(pair): return 2
    if "JPY" in pair: return 3
    return 5

def score_indicators(row, direction):
    def get(key):
        val = row[key] if hasattr(row,'__getitem__') else getattr(row,key)
        if isinstance(val, pd.Series): val = val.iloc[0]
        return float(val)
    buy_votes=0; sell_votes=0; signals={}
    rsi=get("rsi")
    if rsi<30:            buy_votes+=1;  signals["rsi"]="BUY"
    elif 30<=rsi<45:      buy_votes+=1;  signals["rsi"]="BUY"
    elif 45<=rsi<=55:     signals["rsi"]="NEUTRAL"
    elif 55<rsi<=70:      buy_votes+=1;  signals["rsi"]="BUY"
    else:                 sell_votes+=1; signals["rsi"]="SELL"
    macd=get("macd"); ms=get("macd_signal"); mh=get("macd_hist")
    if macd>ms and mh>0:  buy_votes+=1;  signals["macd"]="BUY"
    elif macd<ms and mh<0:sell_votes+=1; signals["macd"]="SELL"
    else:                 signals["macd"]="NEUTRAL"
    k=get("stoch_k"); d=get("stoch_d")
    if k>d and k<80:      buy_votes+=1;  signals["stoch"]="BUY"
    elif k<d and k>20:    sell_votes+=1; signals["stoch"]="SELL"
    else:                 signals["stoch"]="NEUTRAL"
    bb=get("bb_pct")
    if bb<0.2:            buy_votes+=1;  signals["bb"]="BUY"
    elif bb>0.8:          sell_votes+=1; signals["bb"]="SELL"
    else:                 signals["bb"]="NEUTRAL"
    signals["atr"]="NEUTRAL"
    adx=get("adx"); pd_=get("plus_di"); md=get("minus_di")
    if adx>25 and pd_>md: buy_votes+=1;  signals["adx"]="BUY"
    elif adx>25 and md>pd_:sell_votes+=1;signals["adx"]="SELL"
    else:                 signals["adx"]="NEUTRAL"
    cci=get("cci")
    if cci<-100:          buy_votes+=1;  signals["cci"]="BUY"
    elif cci>100:         sell_votes+=1; signals["cci"]="SELL"
    else:                 signals["cci"]="NEUTRAL"
    wr=get("williams_r")
    if wr<-80:            buy_votes+=1;  signals["williams"]="BUY"
    elif wr>-20:          sell_votes+=1; signals["williams"]="SELL"
    else:                 signals["williams"]="NEUTRAL"
    return buy_votes, sell_votes, signals