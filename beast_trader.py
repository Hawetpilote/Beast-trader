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
HEARTBEAT_INTERVAL = 2  # Send status every 2 cycles (2 x 15min = 30min)

# Global cycle counter
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
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except:
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

    # SL/TP suggestions
    if atr_1m:
        sl_buy  = round(price - atr_1m * 1.5, 5)
        sl_sell = round(price + atr_1m * 1.5, 5)
        tp1     = round(price + atr_1m * 2, 5) if "BUY" in str(pd_zone) else round(price - atr_1m * 2, 5)
        tp2     = round(price + atr_1m * 4, 5) if "BUY" in str(pd_zone) else round(price - atr_1m * 4, 5)
    else:
        sl_buy = sl_sell = tp1 = tp2 = "N/A"

    prompt = f"""You are an elite ICT scalping trader. Analyze this live setup.

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
ATR 1m={atr_1m} | ATR 15m={atr_15m}
ATR SL (BUY)={sl_buy} | ATR SL (SELL)={sl_sell}
ATR TP1={tp1} | ATR TP2={tp2}

VOLUME: {vol_label}

ICT:
FVG (1m): {json.dumps(near_fvg)}
OB (1m): {json.dumps(near_obs)}
Last 5 candles 1m: {json.dumps(m1[-5:] if m1 else [])}
Last 5 candles 15m: {json.dumps(m15[-5:] if m15 else [])}
{extra}

Reply ONLY in this exact format:
DIRECTION: [BUY/SELL/WAIT]
ENTRY: [price]
SL: [price]
TP1: [price]
TP2: [price]
RR: [ratio]
SIGNAL: [1-10]
TIMING: [Good/Neutral/Bad]
WIN PROBABILITY: [x%]
CONFLUENCE: [factors]
REASON: [one sentence]"""

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
            funding = get_funding(symbol)
            pressure = get_pressure(symbol)
            extra = f"Funding: {funding}% | Orderbook: {pressure}"
            res = analyze(name, price, m1, m5, m15, h1, h4, extra)
            extra_info = f"Vol: {vol_label} | ADX: {adx_val} | {pressure}"
            msg, score, prob = format_message(name, price, res, extra_info)
            all_results.append((name, price, res, score, prob, msg))
            print(f"    Price: {price} | Score: {score} | Prob: {prob}% | Vol: {vol_label}")
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
                vol_label, _ = calc_volume_analysis(m1, 20) if m1 else ("N/A", 0)
                adx_val = calc_adx(m1, 14) if m1 else 0
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
            f"🤖 <b>BEAST TRADER v5.1</b>\n"
            f"⏰ {now.strftime('%H:%M')} UTC | {kz}\n"
            f"🎯 <b>{len(filtered)} SIGNAL(S)</b>\n"
            f"{'─'*30}"
        )
        send_telegram(kz_tag + header)
        for name, price, res, score, prob, msg in filtered:
            send_telegram(msg)
            print(f"  SENT: {name} | Score:{score} | Prob:{prob}%")
    else:
        print(f"  No strong signals — nothing sent")

    print(f"\n  Next update: 15 min\n")
    return all_results


# ========== ENTRY POINT ==========
if __name__ == "__main__":
    send_telegram(
        "🚀 <b>BEAST TRADER v5.1 STARTED</b>\n"
        "✅ Fixed: GBP/USD real price\n"
        "✅ Fixed: XAU/USD real spot price\n"
        "✅ Fixed: USD/JPY + USD/CHF analysis\n"
        "📡 Status report every 30 minutes\n"
        "⚙️ Scanning every 15 minutes..."
    )
    cycle_count = 0
    while True:
        try:
            all_results = run()
            cycle_count += 1
            # Send status report every 2 cycles = 30 min
            if cycle_count % HEARTBEAT_INTERVAL == 0:
                send_status_report(all_results)
        except Exception as e:
            print(f"[CRITICAL] {e}")
            send_telegram(f"⚠️ Error: {e}")
        time.sleep(900)
