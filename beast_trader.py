import requests
import os
import json
import time
from datetime import datetime, timezone

# ========== CONFIG ==========
GROQ_KEY = os.environ.get("GROQ_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MIN_SIGNAL_SCORE = 7
MIN_WIN_PROB = 65
MIN_ADX = 20
HEARTBEAT_INTERVAL = 30  # every 30 cycles = 30 min
ALGERIA_UTC_OFFSET = 1   # Algeria = UTC+1

# ========== TRADE TRACKER ==========
active_trades = []  # open trades being monitored
daily_stats = {"date": "", "wins": 0, "losses": 0, "tp1_hits": 0, "tp2_hits": 0, "trades": []}
daily_report_sent = False
cycle_count = 0

# ========== TELEGRAM ==========
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("    [TELEGRAM] Not configured")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        if r.status_code == 200:
            print("    [TELEGRAM] Sent OK")
        else:
            print(f"    [TELEGRAM] Error {r.status_code}")
    except Exception as e:
        print(f"    [TELEGRAM] {e}")

# ========== MARKET HOURS ==========
def is_market_open(pair_type):
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    hour = now.hour
    if pair_type == "crypto":
        return True, ""
    if pair_type in ["forex", "gold"]:
        if weekday == 5:
            return False, "MARKET CLOSED - Weekend (Saturday)"
        if weekday == 6 and hour < 22:
            return False, "MARKET CLOSED - Weekend (Sunday, opens 22:00 UTC)"
        if weekday == 4 and hour >= 22:
            return False, "MARKET CLOSED - Weekend started"
        return True, ""
    if pair_type == "index":
        if weekday >= 5:
            return False, "MARKET CLOSED - Weekend"
        if 13 <= hour < 20:
            return True, ""
        elif hour < 13:
            return False, "MARKET CLOSED - Opens 13:30 UTC"
        else:
            return False, "MARKET CLOSED - US session ended"
    return True, ""

def kill_zone():
    hour = datetime.now(timezone.utc).hour
    if 7 <= hour <= 9:
        return "LONDON OPEN - BEST TIME"
    elif 12 <= hour <= 14:
        return "NEW YORK OPEN - BEST TIME"
    elif 20 <= hour <= 22:
        return "ASIAN OPEN"
    return f"OUTSIDE KILL ZONE (UTC {hour}:00)"

def is_kill_zone():
    hour = datetime.now(timezone.utc).hour
    return (7 <= hour <= 9) or (12 <= hour <= 14)

# ========== DATA SOURCES ==========
def get_klines_futures(symbol, interval, limit=200):
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        if r.status_code == 200 and isinstance(r.json(), list):
            return [{"time": datetime.fromtimestamp(c[0]/1000).strftime('%m/%d %H:%M'),
                     "open": float(c[1]), "high": float(c[2]),
                     "low": float(c[3]), "close": float(c[4]),
                     "volume": float(c[5])} for c in r.json()]
    except:
        pass
    return []

def get_klines_spot(symbol, interval, limit=200):
    try:
        r = requests.get("https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        if r.status_code == 200 and isinstance(r.json(), list):
            return [{"time": datetime.fromtimestamp(c[0]/1000).strftime('%m/%d %H:%M'),
                     "open": float(c[1]), "high": float(c[2]),
                     "low": float(c[3]), "close": float(c[4]),
                     "volume": float(c[5])} for c in r.json()]
    except:
        pass
    return []

def get_yahoo_candles(ticker, interval, range_):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()["chart"]["result"][0]
        times = data["timestamp"]
        ohlcv = data["indicators"]["quote"][0]
        candles = []
        for i in range(len(times)):
            try:
                candles.append({
                    "time": datetime.fromtimestamp(times[i]).strftime('%m/%d %H:%M'),
                    "open": float(ohlcv["open"][i]),
                    "high": float(ohlcv["high"][i]),
                    "low": float(ohlcv["low"][i]),
                    "close": float(ohlcv["close"][i]),
                    "volume": float(ohlcv["volume"][i] if ohlcv["volume"][i] else 0)
                })
            except:
                pass
        return candles
    except:
        return []

def get_yahoo_price(ticker):
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except:
        return None

# ========== FIX: CORRECT FOREX PRICES ==========
def get_forex_price(base, quote):
    """Get real forex price from exchangerate API"""
    try:
        r = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=10)
        return float(r.json()["rates"][quote])
    except:
        return None

# ========== FIX: CORRECT GOLD PRICE ==========
def get_gold_price():
    """Get real XAU/USD spot price ~3100"""
    # Source 1: metals.live (real spot price)
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            price = float(data[0].get("price", 0))
            if 2000 < price < 5000:  # sanity check
                return price
    except:
        pass
    # Source 2: open.er-api XAU
    try:
        r = requests.get("https://open.er-api.com/v6/latest/XAU", timeout=10)
        price = float(r.json()["rates"]["USD"])
        if 2000 < price < 5000:
            return price
    except:
        pass
    # Source 3: Yahoo Finance XAUUSD=X (spot)
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD%3DX",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        price = float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
        if 2000 < price < 5000:
            return price
    except:
        pass
    return None

def get_funding(symbol):
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": symbol, "limit": 1}, timeout=10)
        return round(float(r.json()[-1]["fundingRate"]) * 100, 4)
    except:
        return 0

def get_pressure(symbol):
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/depth",
            params={"symbol": symbol, "limit": 20}, timeout=10)
        d = r.json()
        bids = sum(float(b[1]) for b in d["bids"])
        asks = sum(float(a[1]) for a in d["asks"])
        ratio = round(bids / (bids + asks) * 100, 1)
        if ratio > 55:
            return f"BUY PRESSURE ({ratio}%)"
        elif ratio < 45:
            return f"SELL PRESSURE ({ratio}%)"
        return f"NEUTRAL ({ratio}%)"
    except:
        return "NEUTRAL"

# ========== INDICATORS ==========
def calc_rsi(candles, period=14):
    if len(candles) < period + 1:
        return 50
    closes = [c["close"] for c in candles]
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100
    return round(100 - (100 / (1 + ag/al)), 2)

def calc_ema(candles, period):
    if len(candles) < period:
        return None
    closes = [c["close"] for c in candles]
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 5)

def calc_macd(candles):
    if len(candles) < 35:
        return None, None, None
    closes = [c["close"] for c in candles]
    def ema_series(data, period):
        k = 2 / (period + 1)
        ema = sum(data[:period]) / period
        result = [ema]
        for p in data[period:]:
            ema = p * k + ema * (1 - k)
            result.append(ema)
        return result
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    min_len = min(len(ema12), len(ema26))
    macd_line = [ema12[-min_len+i] - ema26[-min_len+i] for i in range(min_len)]
    if len(macd_line) < 9:
        return None, None, None
    signal_line = ema_series(macd_line, 9)
    macd_val = round(macd_line[-1], 6)
    signal_val = round(signal_line[-1], 6)
    hist = round(macd_val - signal_val, 6)
    return macd_val, signal_val, hist

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i-1]["close"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return round(sum(trs[-period:]) / period, 5)

def calc_adx(candles, period=14):
    if len(candles) < period * 2:
        return 0
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        h_diff = candles[i]["high"] - candles[i-1]["high"]
        l_diff = candles[i-1]["low"] - candles[i]["low"]
        plus_dm.append(h_diff if h_diff > l_diff and h_diff > 0 else 0)
        minus_dm.append(l_diff if l_diff > h_diff and l_diff > 0 else 0)
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i-1]["close"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    def smooth(data, p):
        s = sum(data[:p])
        result = [s]
        for v in data[p:]:
            s = s - s/p + v
            result.append(s)
        return result
    str_ = smooth(trs, period)
    spdm = smooth(plus_dm, period)
    sndm = smooth(minus_dm, period)
    dx_list = []
    for i in range(len(str_)):
        if str_[i] == 0:
            continue
        pdi = 100 * spdm[i] / str_[i]
        ndi = 100 * sndm[i] / str_[i]
        if pdi + ndi == 0:
            continue
        dx_list.append(100 * abs(pdi-ndi) / (pdi+ndi))
    if not dx_list:
        return 0
    return round(sum(dx_list[-period:]) / min(len(dx_list), period), 2)

def calc_volume_analysis(candles, period=20):
    if len(candles) < period + 1:
        return "N/A", 0
    vols = [c["volume"] for c in candles[-period-1:-1]]
    avg_vol = sum(vols) / len(vols)
    curr_vol = candles[-1]["volume"]
    ratio = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 0
    if ratio >= 2.0:
        label = f"VERY HIGH ({ratio}x avg)"
    elif ratio >= 1.5:
        label = f"HIGH ({ratio}x avg)"
    elif ratio >= 0.8:
        label = f"NORMAL ({ratio}x avg)"
    else:
        label = f"LOW ({ratio}x avg)"
    return label, ratio

def get_structure(candles):
    if len(candles) < 20:
        return "INSUFFICIENT DATA"
    h = [c["high"] for c in candles[-20:]]
    l = [c["low"] for c in candles[-20:]]
    if max(h[-5:]) < max(h[-10:-5]) and min(l[-5:]) < min(l[-10:-5]):
        return "BEARISH"
    elif max(h[-5:]) > max(h[-10:-5]) and min(l[-5:]) > min(l[-10:-5]):
        return "BULLISH"
    return "RANGING"

def find_fvg(candles):
    fvgs = []
    for i in range(2, len(candles)):
        ph = candles[i-2]["high"]
        pl = candles[i-2]["low"]
        ch = candles[i]["high"]
        cl = candles[i]["low"]
        if cl > ph:
            fvgs.append({"type": "Bullish_FVG", "low": ph, "high": cl, "mid": round((cl+ph)/2, 5)})
        elif ch < pl:
            fvgs.append({"type": "Bearish_FVG", "low": ch, "high": pl, "mid": round((ch+pl)/2, 5)})
    return fvgs

def find_obs(candles):
    obs = []
    for i in range(1, len(candles)-1):
        c = candles[i]
        n = candles[i+1]
        bc = abs(c["close"] - c["open"])
        bn = abs(n["close"] - n["open"])
        if c["close"] > c["open"] and n["close"] < n["open"] and bn > bc * 1.5:
            obs.append({"type": "Bearish_OB", "high": c["high"], "low": c["low"],
                        "mid": round((c["high"]+c["low"])/2, 5)})
        elif c["close"] < c["open"] and n["close"] > n["open"] and bn > bc * 1.5:
            obs.append({"type": "Bullish_OB", "high": c["high"], "low": c["low"],
                        "mid": round((c["high"]+c["low"])/2, 5)})
    return obs

def get_pd(price, candles):
    if len(candles) < 10:
        return "N/A"
    h = max(c["high"] for c in candles[-50:])
    l = min(c["low"] for c in candles[-50:])
    mid = (h + l) / 2
    if price > mid * 1.005:
        return "PREMIUM - prefer SELL"
    elif price < mid * 0.995:
        return "DISCOUNT - prefer BUY"
    return "EQUILIBRIUM"

def check_tf_alignment(s1, s2, s3, s4):
    structs = [s1, s2, s3, s4]
    bullish = sum(1 for s in structs if s == "BULLISH")
    bearish = sum(1 for s in structs if s == "BEARISH")
    if bullish >= 3:
        return "BULLISH", bullish
    elif bearish >= 3:
        return "BEARISH", bearish
    return "MIXED", max(bullish, bearish)

def calc_support_resistance(candles_m15, candles_h1, candles_h4, price):
    """
    Calculate S/R levels on M15, H1, H4.
    Returns dict with nearest support and resistance on each TF,
    and whether price is near any key level.
    """
    result = {
        "m15": {"support": None, "resistance": None},
        "h1":  {"support": None, "resistance": None},
        "h4":  {"support": None, "resistance": None},
        "near_support": False,
        "near_resistance": False,
        "nearest_level": None,
        "level_type": None,
        "proximity_pct": None
    }

    def find_levels(candles, lookback=50):
        """Find swing highs and lows as S/R levels"""
        if not candles or len(candles) < 10:
            return [], []
        candles = candles[-lookback:]
        supports = []
        resistances = []
        for i in range(2, len(candles) - 2):
            # Swing low = support
            if (candles[i]["low"] < candles[i-1]["low"] and
                candles[i]["low"] < candles[i-2]["low"] and
                candles[i]["low"] < candles[i+1]["low"] and
                candles[i]["low"] < candles[i+2]["low"]):
                supports.append(candles[i]["low"])
            # Swing high = resistance
            if (candles[i]["high"] > candles[i-1]["high"] and
                candles[i]["high"] > candles[i-2]["high"] and
                candles[i]["high"] > candles[i+1]["high"] and
                candles[i]["high"] > candles[i+2]["high"]):
                resistances.append(candles[i]["high"])
        return supports, resistances

    # Also add round numbers as S/R
    def round_numbers(price):
        """Generate round number levels near price"""
        magnitude = 10 ** (len(str(int(price))) - 2)
        base = round(price / magnitude) * magnitude
        return [base - magnitude, base, base + magnitude]

    for tf_name, candles in [("m15", candles_m15), ("h1", candles_h1), ("h4", candles_h4)]:
        supports, resistances = find_levels(candles)

        # Nearest support below price
        sup_below = [s for s in supports if s < price]
        res_above = [r for r in resistances if r > price]

        nearest_sup = max(sup_below) if sup_below else None
        nearest_res = min(res_above) if res_above else None

        result[tf_name]["support"] = round(nearest_sup, 5) if nearest_sup else None
        result[tf_name]["resistance"] = round(nearest_res, 5) if nearest_res else None

    # Check if price is near any level (within 0.15%)
    all_levels = []
    for tf in ["m15", "h1", "h4"]:
        if result[tf]["support"]:
            all_levels.append(("support", result[tf]["support"], tf))
        if result[tf]["resistance"]:
            all_levels.append(("resistance", result[tf]["resistance"], tf))

    # Add round numbers
    for rn in round_numbers(price):
        all_levels.append(("round", rn, "round"))

    if all_levels:
        nearest = min(all_levels, key=lambda x: abs(x[1] - price))
        dist_pct = abs(nearest[1] - price) / price * 100
        result["nearest_level"] = nearest[1]
        result["level_type"] = nearest[0]
        result["proximity_pct"] = round(dist_pct, 4)
        if dist_pct < 0.15:
            if nearest[0] == "support":
                result["near_support"] = True
            elif nearest[0] == "resistance":
                result["near_resistance"] = True
            elif nearest[0] == "round":
                result["near_support"] = True  # treat round numbers as both
                result["near_resistance"] = True

    return result

# ========== GROQ AI ==========
def ask_groq(prompt):
    headers = {"Authorization": "Bearer " + GROQ_KEY, "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600,
        "temperature": 0.1
    }
    r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
    return r.json()["choices"][0]["message"]["content"]

# ========== SMART PRE-FILTER (saves 90% tokens) ==========
def should_call_ai(pair, price, m1, m15, h4, adx_val, vol_ratio, h1=None):
    """
    Check technical conditions BEFORE calling Groq AI.
    Only call AI if at least 3 conditions are met AND ICT confirmed.
    Returns (should_call, score, reasons)
    """
    reasons = []
    score = 0

    # 1. Kill Zone active
    if is_kill_zone():
        reasons.append("Kill Zone active")
        score += 2

    # 2. RSI oversold/overbought
    if m1:
        rsi = calc_rsi(m1, 14)
        if rsi <= 30:
            reasons.append(f"RSI oversold ({rsi})")
            score += 2
        elif rsi >= 70:
            reasons.append(f"RSI overbought ({rsi})")
            score += 2
        elif rsi <= 40 or rsi >= 60:
            reasons.append(f"RSI extreme ({rsi})")
            score += 1

    # 3. ADX trending
    if adx_val >= 25:
        reasons.append(f"ADX trending ({adx_val})")
        score += 2
    elif adx_val >= 20:
        reasons.append(f"ADX building ({adx_val})")
        score += 1

    # 4. Volume spike
    if vol_ratio >= 1.5:
        reasons.append(f"Volume spike ({vol_ratio}x)")
        score += 2
    elif vol_ratio >= 1.2:
        reasons.append(f"Volume high ({vol_ratio}x)")
        score += 1

    # 5. Market structure alignment
    if m15 and h4:
        struct_15 = get_structure(m15)
        struct_h4 = get_structure(h4)
        if struct_15 == struct_h4 and struct_15 != "RANGING":
            reasons.append(f"TF aligned ({struct_15})")
            score += 2

    # 6. Price near FVG or OB (ICT)
    ict_confirmed = False
    if m1:
        fvgs = find_fvg(m1)
        obs  = find_obs(m1)
        if fvgs:
            nearest_fvg = min(fvgs, key=lambda x: abs(x["mid"] - price))
            dist_pct = abs(nearest_fvg["mid"] - price) / price * 100
            if dist_pct < 0.1:
                reasons.append(f"Price at FVG ({dist_pct:.3f}%)")
                score += 2
                ict_confirmed = True
        if obs:
            nearest_ob = min(obs, key=lambda x: abs(x["mid"] - price))
            dist_pct = abs(nearest_ob["mid"] - price) / price * 100
            if dist_pct < 0.1:
                reasons.append(f"Price at OB ({dist_pct:.3f}%)")
                score += 2
                ict_confirmed = True

    # 7. Premium/Discount zone
    if h4:
        pd = get_pd(price, h4)
        if "PREMIUM" in pd or "DISCOUNT" in pd:
            reasons.append(f"PD Zone: {pd.split(' ')[0]}")
            score += 1

    # 8. Support & Resistance levels
    sr = calc_support_resistance(m15, h1 or [], h4, price)
    if sr["near_support"]:
        reasons.append(f"Near Support ({sr['proximity_pct']}% away)")
        score += 2
    elif sr["near_resistance"]:
        reasons.append(f"Near Resistance ({sr['proximity_pct']}% away)")
        score += 2
    elif sr["proximity_pct"] and sr["proximity_pct"] < 0.3:
        reasons.append(f"Near S/R level ({sr['proximity_pct']}%)")
        score += 1

    # ICT MANDATORY — must have FVG or OB
    if not ict_confirmed:
        should_call = False
        reasons.append("❌ NO ICT — signal blocked")
        return should_call, score, reasons

    should_call = score >= 3
    return should_call, score, reasons

# ========== ANALYSIS ==========
def analyze(pair, price, m1, m5, m15, h1, h4, extra=""):
    rsi_1m  = calc_rsi(m1,  7)  if m1  else "N/A"
    rsi_5m  = calc_rsi(m5,  7)  if m5  else "N/A"
    rsi_15m = calc_rsi(m15, 14) if m15 else "N/A"
    rsi_1h  = calc_rsi(h1,  14) if h1  else "N/A"
    rsi_4h  = calc_rsi(h4,  14) if h4  else "N/A"
    ema50_h4  = calc_ema(h4, 50)  if h4 else None
    ema200_h4 = calc_ema(h4, 200) if h4 else None
    ema_trend = "N/A"
    if ema50_h4 and ema200_h4:
        ema_trend = "BULLISH (EMA50>EMA200)" if ema50_h4 > ema200_h4 else "BEARISH (EMA50<EMA200)"
    macd, signal, hist = calc_macd(m5) if m5 else (None, None, None)
    macd_str = f"{macd} / Signal:{signal} / Hist:{hist}" if macd else "N/A"
    atr_1m  = calc_atr(m1,  14) if m1  else None
    atr_15m = calc_atr(m15, 14) if m15 else None
    adx_1m  = calc_adx(m1,  14) if m1  else 0
    adx_15m = calc_adx(m15, 14) if m15 else 0
    struct_m1  = get_structure(m1)  if m1  else "N/A"
    struct_m15 = get_structure(m15) if m15 else "N/A"
    struct_h1  = get_structure(h1)  if h1  else "N/A"
    struct_h4  = get_structure(h4)  if h4  else "N/A"
    tf_align, align_count = check_tf_alignment(struct_m1, struct_m15, struct_h1, struct_h4)
    pd_zone = get_pd(price, h4) if h4 else "N/A"
    fvg = find_fvg(m1) if m1 else []
    obs = find_obs(m1) if m1 else []
    near_fvg = sorted(fvg, key=lambda x: abs(x["mid"]-price))[:3]
    near_obs = sorted(obs, key=lambda x: abs(x["mid"]-price))[:2]
    vol_label, _ = calc_volume_analysis(m1, 20) if m1 else ("N/A", 0)

    # SL/TP suggestions — use H1 ATR for realistic levels (not M1)
    atr_for_sl = atr_15m if atr_15m else atr_1m
    if atr_for_sl:
        # SL = 2x ATR (enough breathing room)
        sl_buy  = round(price - atr_for_sl * 2.0, 5)
        sl_sell = round(price + atr_for_sl * 2.0, 5)
        # TP1 = 2x SL distance (RR 1:2)
        # TP2 = 4x SL distance (RR 1:4)
        sl_dist = atr_for_sl * 2.0
        tp1_buy   = round(price + sl_dist * 2, 5)
        tp1_sell  = round(price - sl_dist * 2, 5)
        tp2_buy   = round(price + sl_dist * 4, 5)
        tp2_sell  = round(price - sl_dist * 4, 5)
        tp1 = tp1_buy if "DISCOUNT" in str(pd_zone) else tp1_sell
        tp2 = tp2_buy if "DISCOUNT" in str(pd_zone) else tp2_sell
    else:
        sl_buy = sl_sell = tp1 = tp2 = "N/A"

    prompt = f"""You are an elite ICT trader. Analyze this setup using PURE ICT methodology.

STRICT RULES:
1. ONLY give BUY/SELL if price is AT or NEAR a valid FVG or Order Block
2. SL must be BEYOND the FVG/OB (not inside it) — minimum 2x ATR distance
3. TP1 minimum RR 1:2 | TP2 minimum RR 1:4
4. If no clear ICT setup → DIRECTION: WAIT
5. Give enough distance for late entry (5-10 minutes to enter)

PAIR: {pair} | PRICE: {price}
KILL ZONE: {kill_zone()}

TREND:
EMA (H4): {ema_trend}
TF Alignment: {tf_align} ({align_count}/4 agree)
Structure: M1={struct_m1} | M15={struct_m15} | H1={struct_h1} | H4={struct_h4}
PD Zone (H4): {pd_zone}

MOMENTUM:
RSI: 1m={rsi_1m} | 5m={rsi_5m} | 15m={rsi_15m} | 1H={rsi_1h} | 4H={rsi_4h}
MACD (5m): {macd_str}
ADX: 1m={adx_1m} | 15m={adx_15m}

VOLATILITY:
ATR 15m={atr_15m} | ATR 1m={atr_1m}
Suggested SL BUY={sl_buy} | SL SELL={sl_sell}
Suggested TP1={tp1} | TP2={tp2}

VOLUME: {vol_label}

ICT (MANDATORY):
FVG (1m): {json.dumps(near_fvg)}
OB (1m): {json.dumps(near_obs)}
Last 5 candles 1m: {json.dumps(m1[-5:] if m1 else [])}
Last 5 candles 15m: {json.dumps(m15[-5:] if m15 else [])}
{extra}

Reply ONLY in this exact format:
DIRECTION: [BUY/SELL/WAIT]
ENTRY: [price]
SL: [price — must be 2x ATR away minimum]
TP1: [price — RR at least 1:2]
TP2: [price — RR at least 1:4]
RR: [ratio e.g. 1:3]
SIGNAL: [1-10]
TIMING: [Good/Neutral/Bad]
WIN PROBABILITY: [x%]
CONFLUENCE: [ICT factors: FVG/OB/PD/Structure/KZ]
REASON: [one sentence mentioning the ICT setup]"""

    return ask_groq(prompt)

# ========== SIGNAL PARSER ==========
def parse_signal_score(text):
    try:
        for line in text.split("\n"):
            if "SIGNAL:" in line:
                return int("".join(filter(str.isdigit, line.split(":")[1][:3])))
    except:
        pass
    return 0

def parse_win_prob(text):
    try:
        for line in text.split("\n"):
            if "WIN PROBABILITY:" in line:
                return int("".join(filter(str.isdigit, line.split(":")[1][:5])))
    except:
        pass
    return 0

def format_message(name, price, analysis, extra_info=""):
    score = parse_signal_score(analysis)
    prob = parse_win_prob(analysis)
    direction = "WAIT"
    for line in analysis.split("\n"):
        if "DIRECTION:" in line:
            if "BUY" in line:
                direction = "BUY"
            elif "SELL" in line:
                direction = "SELL"
    emoji = "BUY" if direction == "BUY" else "SELL" if direction == "SELL" else "WAIT"
    tag = "🟢" if direction == "BUY" else "🔴" if direction == "SELL" else "⚪"
    msg = f"{tag} <b>{name}</b> | {price}\n"
    msg += f"Direction: <b>{emoji}</b> | Score: <b>{score}/10</b> | Win: <b>{prob}%</b>\n"
    if extra_info:
        msg += f"{extra_info}\n"
    msg += f"\n{analysis}"
    return msg, score, prob

# ========== TRADE TRACKER ==========
def algeria_time():
    """Get current Algeria time (UTC+1)"""
    from datetime import timedelta
    return datetime.now(timezone.utc) + timedelta(hours=ALGERIA_UTC_OFFSET)

def reset_daily_stats_if_new_day():
    global daily_stats, daily_report_sent
    today = algeria_time().strftime("%Y-%m-%d")
    if daily_stats["date"] != today:
        daily_stats = {"date": today, "wins": 0, "losses": 0, "tp1_hits": 0, "tp2_hits": 0, "trades": []}
        daily_report_sent = False
        print(f"  [TRACKER] New day: {today}")

def get_current_price(pair):
    """Get live price for any pair"""
    try:
        if pair == "BTC/USD":
            r = requests.get("https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT", timeout=5)
            return float(r.json()["price"])
        elif pair == "ETH/USD":
            r = requests.get("https://fapi.binance.com/fapi/v1/ticker/price?symbol=ETHUSDT", timeout=5)
            return float(r.json()["price"])
        elif pair == "EUR/USD":
            r = requests.get("https://open.er-api.com/v6/latest/EUR", timeout=5)
            return float(r.json()["rates"]["USD"])
        elif pair == "GBP/USD":
            r = requests.get("https://open.er-api.com/v6/latest/GBP", timeout=5)
            return float(r.json()["rates"]["USD"])
        elif pair == "USD/JPY":
            r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
            return float(r.json()["rates"]["JPY"])
        elif pair == "USD/CHF":
            r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
            return float(r.json()["rates"]["CHF"])
        elif pair == "XAU/USD":
            r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            return float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
        elif pair == "USTEC":
            r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ENDX",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            return float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
        elif pair == "US30":
            r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5EDJI",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            return float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except:
        pass
    return None

def add_active_trade(pair, direction, entry, sl, tp1, tp2, score, prob):
    """Add a new trade to monitoring list"""
    global active_trades
    # Remove existing trade for same pair
    active_trades = [t for t in active_trades if t["pair"] != pair]
    active_trades.append({
        "pair":      pair,
        "direction": direction,
        "entry":     entry,
        "sl":        sl,
        "tp1":       tp1,
        "tp2":       tp2,
        "score":     score,
        "prob":      prob,
        "time":      algeria_time().strftime("%H:%M"),
        "hit_tp1":   False,
        "status":    "OPEN"
    })
    print(f"  [TRACKER] Monitoring {pair} {direction} | SL:{sl} TP1:{tp1} TP2:{tp2}")

def check_active_trades():
    """Check all open trades and update status"""
    global active_trades, daily_stats
    if not active_trades:
        return
    for trade in active_trades:
        if trade["status"] != "OPEN":
            continue
        price = get_current_price(trade["pair"])
        if not price:
            continue
        direction = trade["direction"]
        try:
            sl   = float(trade["sl"])
            tp1  = float(trade["tp1"])
            tp2  = float(trade["tp2"])
            entry = float(trade["entry"])
        except:
            continue

        # Check BUY trade
        if direction == "BUY":
            if price <= sl:
                trade["status"] = "LOSS"
                record_result(trade, "LOSS", price)
            elif price >= tp2:
                trade["status"] = "WIN_TP2"
                record_result(trade, "WIN_TP2", price)
            elif price >= tp1 and not trade["hit_tp1"]:
                trade["hit_tp1"] = True
                notify_tp1(trade, price)

        # Check SELL trade
        elif direction == "SELL":
            if price >= sl:
                trade["status"] = "LOSS"
                record_result(trade, "LOSS", price)
            elif price <= tp2:
                trade["status"] = "WIN_TP2"
                record_result(trade, "WIN_TP2", price)
            elif price <= tp1 and not trade["hit_tp1"]:
                trade["hit_tp1"] = True
                notify_tp1(trade, price)

    # Remove closed trades
    active_trades = [t for t in active_trades if t["status"] == "OPEN"]

def notify_tp1(trade, price):
    """Notify when TP1 is hit"""
    daily_stats["tp1_hits"] += 1
    msg = (
        f"🎯 <b>TP1 HIT!</b>\n"
        f"📊 {trade['pair']} | {trade['direction']}\n"
        f"⏰ Entry: {trade['time']} | Now: {algeria_time().strftime('%H:%M')}\n"
        f"✅ TP1 reached: <b>{price}</b>\n"
        f"👀 Watching for TP2: {trade['tp2']}\n"
        f"🛡️ Move SL to entry for free trade!"
    )
    send_telegram(msg)
    print(f"  [TRACKER] TP1 hit: {trade['pair']}")

def record_result(trade, result, price):
    """Record final trade result"""
    now = algeria_time().strftime("%H:%M")
    if result in ["WIN_TP1", "WIN_TP2"]:
        daily_stats["wins"] += 1
        if result == "WIN_TP2":
            daily_stats["tp2_hits"] += 1
        emoji = "✅"
        result_text = "WIN TP2 ✅" if result == "WIN_TP2" else "WIN TP1 ✅"
        msg = (
            f"✅ <b>TRADE CLOSED — WIN!</b>\n"
            f"📊 {trade['pair']} | {trade['direction']}\n"
            f"⏰ Entry: {trade['time']} → Close: {now}\n"
            f"💰 TP2 hit at: <b>{price}</b>\n"
            f"📈 Score was: {trade['score']}/10 | Prob: {trade['prob']}%\n"
            f"🏆 Today: {daily_stats['wins']}W / {daily_stats['losses']}L"
        )
    else:
        daily_stats["losses"] += 1
        emoji = "❌"
        result_text = "LOSS ❌"
        msg = (
            f"❌ <b>TRADE CLOSED — LOSS</b>\n"
            f"📊 {trade['pair']} | {trade['direction']}\n"
            f"⏰ Entry: {trade['time']} → Close: {now}\n"
            f"🛑 SL hit at: <b>{price}</b>\n"
            f"📈 Score was: {trade['score']}/10 | Prob: {trade['prob']}%\n"
            f"📊 Today: {daily_stats['wins']}W / {daily_stats['losses']}L"
        )

    daily_stats["trades"].append({
        "pair":      trade["pair"],
        "direction": trade["direction"],
        "entry":     trade["entry"],
        "close":     price,
        "result":    result_text,
        "time":      now
    })
    send_telegram(msg)
    print(f"  [TRACKER] {trade['pair']} → {result_text} at {price}")

def send_daily_report():
    """Send daily summary at 23:59 Algeria time"""
    global daily_report_sent
    if daily_report_sent:
        return
    now = algeria_time()
    total = daily_stats["wins"] + daily_stats["losses"]
    win_rate = round(daily_stats["wins"] / total * 100) if total > 0 else 0
    bar_filled = int(win_rate / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    lines = []
    lines.append(f"📊 <b>DAILY REPORT — {daily_stats['date']}</b>")
    lines.append(f"{'─'*30}")
    lines.append(f"✅ Wins:   <b>{daily_stats['wins']}</b>")
    lines.append(f"❌ Losses: <b>{daily_stats['losses']}</b>")
    lines.append(f"📈 Total:  <b>{total}</b> trades")
    lines.append(f"🎯 Win Rate: <b>{win_rate}%</b> [{bar}]")
    lines.append(f"🎯 TP1 hits: {daily_stats['tp1_hits']}")
    lines.append(f"🏆 TP2 hits: {daily_stats['tp2_hits']}")
    lines.append(f"{'─'*30}")

    if daily_stats["trades"]:
        lines.append(f"<b>Trade History:</b>")
        for t in daily_stats["trades"]:
            lines.append(f"• {t['pair']} {t['direction']} @ {t['entry']} → {t['result']} ({t['time']})")

    if win_rate >= 70:
        lines.append(f"\n🔥 Excellent day! Keep it up!")
    elif win_rate >= 50:
        lines.append(f"\n👍 Good day! Profitable session.")
    else:
        lines.append(f"\n💪 Tough day. Review and improve tomorrow.")

    send_telegram("\n".join(lines))
    daily_report_sent = True
    print(f"  [TRACKER] Daily report sent")

# ========== STATUS REPORT (every 30 min) ==========
def send_status_report(all_results):
    now = datetime.now(timezone.utc)
    kz = kill_zone()
    open_status_forex, _ = is_market_open("forex")
    open_status_index, _ = is_market_open("index")

    lines = []
    lines.append(f"📡 <b>BEAST TRADER — STATUS REPORT</b>")
    lines.append(f"⏰ {now.strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append(f"📍 {kz}")
    lines.append(f"{'─'*30}")

    if all_results:
        for name, price, res, score, prob, msg in all_results:
            # direction
            direction = "⚪ WAIT"
            for line in res.split("\n"):
                if "DIRECTION:" in line:
                    if "BUY" in line:
                        direction = "🟢 BUY"
                    elif "SELL" in line:
                        direction = "🔴 SELL"
                    break
            bar_filled = int(prob / 10)
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            lines.append(
                f"<b>{name}</b>\n"
                f"  Price: {price}\n"
                f"  {direction} | Score: {score}/10\n"
                f"  Win: {prob}% [{bar}]\n"
            )
    else:
        lines.append("⏳ No data yet this cycle")

    lines.append(f"{'─'*30}")
    lines.append(f"🏦 Forex/Gold: {'🟢 OPEN' if open_status_forex else '🔴 CLOSED'}")
    lines.append(f"📊 Indices: {'🟢 OPEN' if open_status_index else '🔴 CLOSED'}")
    total = daily_stats["wins"] + daily_stats["losses"]
    win_rate = round(daily_stats["wins"] / total * 100) if total > 0 else 0
    lines.append(f"{'─'*30}")
    lines.append(f"📅 Today ({daily_stats['date']}): ✅{daily_stats['wins']}W ❌{daily_stats['losses']}L | WR: {win_rate}%")
    lines.append(f"🔍 Active trades: {len(active_trades)}")
    lines.append(f"⚙️ Bot running normally ✅")

    send_telegram("\n".join(lines))

# ========== MAIN ==========
def run():
    now = datetime.now(timezone.utc)
    kz = kill_zone()
    print(f"\n{'='*60}")
    print(f"  BEAST TRADER v5.1 | {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  {kz} | Day: {now.strftime('%A')}")
    print(f"{'='*60}")

    if is_kill_zone():
        send_telegram(f"⚡ <b>KILL ZONE ACTIVE</b>\n{kz}\n🎯 High probability setups incoming!")

    all_results = []

    # ===== BTC / ETH =====
    for symbol, name in [("BTCUSDT", "BTC/USD"), ("ETHUSDT", "ETH/USD")]:
        try:
            print(f"\n[*] {name}...")
            m1  = get_klines_futures(symbol, "1m",  200)
            m5  = get_klines_futures(symbol, "5m",  200)
            m15 = get_klines_futures(symbol, "15m", 200)
            h1  = get_klines_futures(symbol, "1h",  200)
            h4  = get_klines_futures(symbol, "4h",  200)
            price = m1[-1]["close"] if m1 else 0
            vol_label, vol_ratio = calc_volume_analysis(m1, 20)
            adx_val = calc_adx(m1, 14)

            # PRE-FILTER: check conditions before calling AI
            should_call, pre_score, pre_reasons = should_call_ai(
                name, price, m1, m15, h4, adx_val, vol_ratio)

            if not should_call:
                print(f"    Price: {price} | Pre-score: {pre_score}/3 — SKIP AI (saving tokens)")
                continue

            print(f"    Price: {price} | Pre-score: {pre_score} | Reasons: {', '.join(pre_reasons)}")
            funding = get_funding(symbol)
            pressure = get_pressure(symbol)
            extra = f"Funding: {funding}% | Orderbook: {pressure}"
            res = analyze(name, price, m1, m5, m15, h1, h4, extra)
            extra_info = f"Vol: {vol_label} | ADX: {adx_val} | {pressure}"
            msg, score, prob = format_message(name, price, res, extra_info)
            all_results.append((name, price, res, score, prob, msg))
            print(f"    Score: {score} | Prob: {prob}%")
        except Exception as e:
            print(f"    [ERROR] {name}: {e}")

    # ===== FOREX =====
    # FIX: EUR/USD and GBP/USD use Binance for candles but exchangerate for REAL price
    # FIX: USD/JPY and USD/CHF use exchangerate for price + Yahoo for candles
    forex_configs = [
        # (name, binance_sym, base, quote, yahoo_ticker)
        ("EUR/USD", "EURUSDT", "EUR", "USD", "EURUSD=X"),
        ("GBP/USD", "GBPUSDT", "GBP", "USD", "GBPUSD=X"),
        ("USD/JPY", None,      "USD", "JPY", "JPY=X"),
        ("USD/CHF", None,      "USD", "CHF", "CHF=X"),
    ]

    for name, binance_sym, base, quote, yahoo_ticker in forex_configs:
        open_status, closed_msg = is_market_open("forex")
        print(f"\n[*] {name}...")
        if not open_status:
            print(f"    {closed_msg}")
            continue
        try:
            # REAL price always from exchangerate API
            price = get_forex_price(base, quote)
            if not price:
                print(f"    [ERROR] Could not get price")
                continue

            # Candles from Binance spot if available
            if binance_sym:
                m1  = get_klines_spot(binance_sym, "1m",  200)
                m5  = get_klines_spot(binance_sym, "5m",  200)
                m15 = get_klines_spot(binance_sym, "15m", 200)
                h1  = get_klines_spot(binance_sym, "1h",  200)
                h4  = get_klines_spot(binance_sym, "4h",  200)
            else:
                # Candles from Yahoo Finance for JPY/CHF
                m15 = get_yahoo_candles(yahoo_ticker, "15m", "5d")
                h4  = get_yahoo_candles(yahoo_ticker, "1d",  "1mo")
                m1 = m5 = h1 = []

            vol_label, vol_ratio = calc_volume_analysis(m1, 20) if m1 else ("N/A", 0)
            adx_val = calc_adx(m1, 14) if m1 else 0

            # PRE-FILTER
            should_call, pre_score, pre_reasons = should_call_ai(
                name, price, m1, m15, h4, adx_val, vol_ratio)
            if not should_call:
                print(f"    Price: {price} | Pre-score: {pre_score}/3 — SKIP AI")
                continue

            print(f"    Pre-score: {pre_score} | {', '.join(pre_reasons)}")
            res = analyze(name, price, m1, m5, m15, h1, h4)
            extra_info = f"Vol: {vol_label} | ADX: {adx_val}" if vol_label != "N/A" else ""
            msg, score, prob = format_message(name, price, res, extra_info)
            all_results.append((name, price, res, score, prob, msg))
            print(f"    Price: {price} | Score: {score} | Prob: {prob}%")
        except Exception as e:
            print(f"    [ERROR] {name}: {e}")

    # ===== GOLD - FIX: Real spot price ~3100 =====
    print(f"\n[*] XAU/USD...")
    open_status, _ = is_market_open("gold")
    if open_status:
        try:
            price = get_gold_price()
            if price:
                print(f"    Gold spot price: {price}")
                m15 = get_yahoo_candles("XAUUSD%3DX", "15m", "5d")
                m1  = get_yahoo_candles("XAUUSD%3DX", "1m",  "1d")
                if not m15:
                    m15 = get_yahoo_candles("GC%3DF", "15m", "5d")
                if not m1:
                    m1 = get_yahoo_candles("GC%3DF", "1m", "1d")
                vol_label, vol_ratio = calc_volume_analysis(m1, 20) if m1 else ("N/A", 0)
                adx_val = calc_adx(m1, 14) if m1 else 0

                # PRE-FILTER
                should_call, pre_score, pre_reasons = should_call_ai(
                    "XAU/USD", price, m1, m15, [], adx_val, vol_ratio)
                if not should_call:
                    print(f"    Price: {price} | Pre-score: {pre_score}/3 — SKIP AI")
                else:
                    print(f"    Pre-score: {pre_score} | {', '.join(pre_reasons)}")
                    res = analyze("XAU/USD", price, m1, [], m15, [], [])
                    extra_info = f"Vol: {vol_label} | ADX: {adx_val}"
                    msg, score, prob = format_message("XAU/USD", price, res, extra_info)
                    all_results.append(("XAU/USD", price, res, score, prob, msg))
                    print(f"    Score: {score} | Prob: {prob}%")
            else:
                print(f"    [ERROR] Could not get gold price")
        except Exception as e:
            print(f"    [ERROR] XAU/USD: {e}")
    else:
        print(f"    MARKET CLOSED")

    # ===== INDICES =====
    for ticker, name in [("^NDX", "USTEC"), ("^DJI", "US30")]:
        print(f"\n[*] {name}...")
        open_status, closed_msg = is_market_open("index")
        if not open_status:
            print(f"    {closed_msg}")
            continue
        try:
            price = get_yahoo_price(ticker)
            if price:
                m15 = get_yahoo_candles(ticker, "15m", "5d")
                m1  = get_yahoo_candles(ticker, "1m",  "1d")
                vol_label, vol_ratio = calc_volume_analysis(m1, 20) if m1 else ("N/A", 0)
                adx_val = calc_adx(m1, 14) if m1 else 0

                # PRE-FILTER
                should_call, pre_score, pre_reasons = should_call_ai(
                    name, price, m1, m15, [], adx_val, vol_ratio)
                if not should_call:
                    print(f"    Price: {price} | Pre-score: {pre_score}/3 — SKIP AI")
                    continue

                res = analyze(name, price, m1, [], m15, [], [])
                msg, score, prob = format_message(name, price, res)
                all_results.append((name, price, res, score, prob, msg))
                print(f"    Price: {price} | Score: {score} | Prob: {prob}%")
        except Exception as e:
            print(f"    [ERROR] {name}: {e}")

    # ===== FILTER & SEND =====
    print(f"\n{'='*60}")
    print(f"  FILTER: min score={MIN_SIGNAL_SCORE} | min prob={MIN_WIN_PROB}%")
    print(f"{'='*60}")

    filtered = [(n, p, r, s, pr, m) for n, p, r, s, pr, m in all_results
                if s >= MIN_SIGNAL_SCORE and pr >= MIN_WIN_PROB]

    if filtered:
        kz_tag = "⚡ KILL ZONE SIGNAL\n" if is_kill_zone() else ""
        header = (
            f"🤖 <b>BEAST TRADER v5.2</b>\n"
            f"⏰ {now.strftime('%H:%M')} UTC | {kz}\n"
            f"🎯 <b>{len(filtered)} SIGNAL(S)</b>\n"
            f"{'─'*30}"
        )
        send_telegram(kz_tag + header)
        for name, price, res, score, prob, msg in filtered:
            send_telegram(msg)
            print(f"  SENT: {name} | Score:{score} | Prob:{prob}%")
            # Parse entry/sl/tp from signal and add to tracker
            try:
                direction = "WAIT"
                entry = sl = tp1 = tp2 = None
                for line in res.split("\n"):
                    line = line.strip()
                    if line.startswith("DIRECTION:"):
                        direction = line.split(":")[1].strip().split()[0]
                    elif line.startswith("ENTRY:"):
                        entry = float("".join(c for c in line.split(":")[1] if c.isdigit() or c == "."))
                    elif line.startswith("SL:"):
                        sl = float("".join(c for c in line.split(":")[1].split()[0] if c.isdigit() or c == "."))
                    elif line.startswith("TP1:"):
                        tp1 = float("".join(c for c in line.split(":")[1].split()[0] if c.isdigit() or c == "."))
                    elif line.startswith("TP2:"):
                        tp2 = float("".join(c for c in line.split(":")[1].split()[0] if c.isdigit() or c == "."))
                if direction in ["BUY", "SELL"] and entry and sl and tp1 and tp2:
                    add_active_trade(name, direction, entry, sl, tp1, tp2, score, prob)
            except Exception as e:
                print(f"  [TRACKER] Parse error: {e}")
    else:
        print(f"  No strong signals — nothing sent")

    print(f"\n  Next update: 15 min\n")
    return all_results


# ========== ENTRY POINT ==========
if __name__ == "__main__":
    send_telegram(
        "🚀 <b>BEAST TRADER v5.2 STARTED</b>\n"
        "✅ Trade result tracking added\n"
        "📊 Daily report at 23:59 Algeria time\n"
        "📡 Status report every 30 minutes\n"
        "⚙️ Scanning every 1 minute..."
    )
    cycle_count = 0
    while True:
        try:
            # Reset daily stats if new day
            reset_daily_stats_if_new_day()

            # Check active trades (TP/SL hit?)
            check_active_trades()

            # Run main analysis
            all_results = run()
            cycle_count += 1

            # Status report every 30 min
            if cycle_count % HEARTBEAT_INTERVAL == 0:
                send_status_report(all_results)

            # Daily report at 23:59 Algeria time
            now_alg = algeria_time()
            if now_alg.hour == 23 and now_alg.minute == 59 and not daily_report_sent:
                send_daily_report()

        except Exception as e:
            print(f"[CRITICAL] {e}")
            send_telegram(f"⚠️ Error: {e}")
        time.sleep(60)
