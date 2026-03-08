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
MIN_ADX = 25

# ========== TELEGRAM ==========
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except:
        pass

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
            return False, "MARKET CLOSED - Weekend (Sunday, opens at 22:00 UTC)"
        if weekday == 4 and hour >= 22:
            return False, "MARKET CLOSED - Weekend starts Friday 22:00 UTC"
        return True, ""
    if pair_type == "index":
        if weekday >= 5:
            return False, "MARKET CLOSED - Weekend"
        if 13 <= hour < 20:
            return True, ""
        elif hour < 13:
            return False, "MARKET CLOSED - US market opens at 13:30 UTC"
        else:
            return False, "MARKET CLOSED - US market closed for today"
    return True, ""

def kill_zone():
    hour = datetime.now(timezone.utc).hour
    if 7 <= hour <= 9:
        return "🟢 LONDON OPEN - BEST TIME"
    elif 12 <= hour <= 14:
        return "🟢 NEW YORK OPEN - BEST TIME"
    elif 20 <= hour <= 22:
        return "🟡 ASIAN OPEN"
    return f"⚪ OUTSIDE KILL ZONE (UTC {hour}:00)"

def is_kill_zone():
    hour = datetime.now(timezone.utc).hour
    return (7 <= hour <= 9) or (12 <= hour <= 14)

# ========== DATA SOURCES ==========
def get_klines_futures(symbol, interval, limit=200):
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        if r.status_code == 200:
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
        if r.status_code == 200:
            return [{"time": datetime.fromtimestamp(c[0]/1000).strftime('%m/%d %H:%M'),
                     "open": float(c[1]), "high": float(c[2]),
                     "low": float(c[3]), "close": float(c[4]),
                     "volume": float(c[5])} for c in r.json()]
    except:
        pass
    return []

def get_real_gold_price():
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return float(r.json()['chart']['result'][0]['meta']['regularMarketPrice'])
    except:
        return None

def get_forex_price(pair):
    try:
        base = pair[:3]
        quote = pair[3:]
        r = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=10)
        return float(r.json()['rates'][quote])
    except:
        return None

def get_yahoo_price(ticker):
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return float(r.json()['chart']['result'][0]['meta']['regularMarketPrice'])
    except:
        return None

def get_funding(symbol):
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": symbol, "limit": 1}, timeout=10)
        return round(float(r.json()[-1]['fundingRate']) * 100, 4)
    except:
        return 0

def get_pressure(symbol):
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/depth",
            params={"symbol": symbol, "limit": 20}, timeout=10)
        d = r.json()
        bids = sum(float(b[1]) for b in d['bids'])
        asks = sum(float(a[1]) for a in d['asks'])
        ratio = round(bids / (bids + asks) * 100, 1)
        if ratio > 55:
            return f"🟢 BUY PRESSURE ({ratio}%)"
        elif ratio < 45:
            return f"🔴 SELL PRESSURE ({ratio}%)"
        return f"⚪ NEUTRAL ({ratio}%)"
    except:
        return "NEUTRAL"

def get_yahoo_candles(ticker, interval, range_):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()['chart']['result'][0]
        times = data['timestamp']
        ohlcv = data['indicators']['quote'][0]
        candles = []
        for i in range(len(times)):
            try:
                candles.append({
                    "time": datetime.fromtimestamp(times[i]).strftime('%m/%d %H:%M'),
                    "open": float(ohlcv['open'][i]),
                    "high": float(ohlcv['high'][i]),
                    "low": float(ohlcv['low'][i]),
                    "close": float(ohlcv['close'][i]),
                    "volume": float(ohlcv['volume'][i] if ohlcv['volume'][i] else 0)
                })
            except:
                pass
        return candles
    except:
        return []

# ========== INDICATORS ==========
def calc_rsi(candles, period=14):
    if len(candles) < period + 1:
        return 50
    closes = [c['close'] for c in candles]
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
    closes = [c['close'] for c in candles]
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 5)

def calc_macd(candles):
    if len(candles) < 35:
        return None, None, None
    closes = [c['close'] for c in candles]
    def ema_series(data, period):
        k = 2 / (period + 1)
        ema = sum(data[:period]) / period
        result = [ema]
        for p in data[period:]:
            ema = p * k + ema * (1 - k)
            result.append(ema)
        return result
    ema12 = ema_series(closes, 12)
    ema26_data = closes[14:]
    if len(ema26_data) < 26:
        return None, None, None
    ema26 = ema_series(ema26_data, 26)
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
        h = candles[i]['high']
        l = candles[i]['low']
        pc = candles[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return round(sum(trs[-period:]) / period, 5)

def calc_adx(candles, period=14):
    if len(candles) < period * 2:
        return 0
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        h_diff = candles[i]['high'] - candles[i-1]['high']
        l_diff = candles[i-1]['low'] - candles[i]['low']
        plus_dm.append(h_diff if h_diff > l_diff and h_diff > 0 else 0)
        minus_dm.append(l_diff if l_diff > h_diff and l_diff > 0 else 0)
        h = candles[i]['high']
        l = candles[i]['low']
        pc = candles[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
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
        dx_list.append(100 * abs(pdi - ndi) / (pdi + ndi))
    if not dx_list:
        return 0
    return round(sum(dx_list[-period:]) / min(len(dx_list), period), 2)

def calc_volume_analysis(candles, period=20):
    if len(candles) < period + 1:
        return "N/A", 0
    vols = [c['volume'] for c in candles[-period-1:-1]]
    avg_vol = sum(vols) / len(vols)
    curr_vol = candles[-1]['volume']
    ratio = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 0
    if ratio >= 2.0:
        label = f"🔥 VERY HIGH ({ratio}x avg)"
    elif ratio >= 1.5:
        label = f"📈 HIGH ({ratio}x avg)"
    elif ratio >= 0.8:
        label = f"➡️ NORMAL ({ratio}x avg)"
    else:
        label = f"📉 LOW ({ratio}x avg)"
    return label, ratio

def calc_bollinger(candles, period=20, std_dev=2):
    if len(candles) < period:
        return None, None, None
    closes = [c['close'] for c in candles[-period:]]
    mid = sum(closes) / period
    variance = sum((p - mid) ** 2 for p in closes) / period
    std = variance ** 0.5
    upper = round(mid + std_dev * std, 5)
    lower = round(mid - std_dev * std, 5)
    mid = round(mid, 5)
    return upper, mid, lower

def get_structure(candles):
    if len(candles) < 20:
        return "INSUFFICIENT DATA"
    h = [c['high'] for c in candles[-20:]]
    l = [c['low'] for c in candles[-20:]]
    if max(h[-5:]) < max(h[-10:-5]) and min(l[-5:]) < min(l[-10:-5]):
        return "BEARISH"
    elif max(h[-5:]) > max(h[-10:-5]) and min(l[-5:]) > min(l[-10:-5]):
        return "BULLISH"
    return "RANGING"

def find_fvg(candles):
    fvgs = []
    for i in range(2, len(candles)):
        ph = candles[i-2]['high']
        pl = candles[i-2]['low']
        ch = candles[i]['high']
        cl = candles[i]['low']
        if cl > ph:
            fvgs.append({"type": "Bullish_FVG", "low": ph, "high": cl,
                         "mid": round((cl+ph)/2, 5)})
        elif ch < pl:
            fvgs.append({"type": "Bearish_FVG", "low": ch, "high": pl,
                         "mid": round((ch+pl)/2, 5)})
    return fvgs

def find_obs(candles):
    obs = []
    for i in range(1, len(candles)-1):
        c = candles[i]
        n = candles[i+1]
        bc = abs(c['close'] - c['open'])
        bn = abs(n['close'] - n['open'])
        if c['close'] > c['open'] and n['close'] < n['open'] and bn > bc * 1.5:
            obs.append({"type": "Bearish_OB", "high": c['high'], "low": c['low'],
                        "mid": round((c['high']+c['low'])/2, 5)})
        elif c['close'] < c['open'] and n['close'] > n['open'] and bn > bc * 1.5:
            obs.append({"type": "Bullish_OB", "high": c['high'], "low": c['low'],
                        "mid": round((c['high']+c['low'])/2, 5)})
    return obs

def get_pd(price, candles):
    if len(candles) < 10:
        return "N/A"
    h = max(c['high'] for c in candles[-50:])
    l = min(c['low'] for c in candles[-50:])
    mid = (h + l) / 2
    if price > mid * 1.01:
        return "PREMIUM - prefer SELL"
    elif price < mid * 0.99:
        return "DISCOUNT - prefer BUY"
    return "EQUILIBRIUM"

def check_tf_alignment(struct_m1, struct_m15, struct_h1, struct_h4):
    structs = [struct_m1, struct_m15, struct_h1, struct_h4]
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
    return r.json()['choices'][0]['message']['content']

# ========== MAIN ANALYSIS ==========
def analyze(pair, price, m1, m5, m15, h1, h4, extra=""):
    # RSI multi-tf
    rsi_1m  = calc_rsi(m1,  period=7)  if m1  else "N/A"
    rsi_5m  = calc_rsi(m5,  period=7)  if m5  else "N/A"
    rsi_15m = calc_rsi(m15, period=14) if m15 else "N/A"
    rsi_1h  = calc_rsi(h1,  period=14) if h1  else "N/A"
    rsi_4h  = calc_rsi(h4,  period=14) if h4  else "N/A"

    # EMA
    ema50_1m  = calc_ema(m1,  50)  if m1  else None
    ema200_1m = calc_ema(m1,  200) if m1  else None
    ema50_h4  = calc_ema(h4,  50)  if h4  else None
    ema200_h4 = calc_ema(h4,  200) if h4  else None

    ema_trend = "N/A"
    if ema50_h4 and ema200_h4:
        ema_trend = "BULLISH (EMA50 > EMA200)" if ema50_h4 > ema200_h4 else "BEARISH (EMA50 < EMA200)"

    # MACD on 5m
    macd, signal, hist = calc_macd(m5) if m5 else (None, None, None)
    macd_str = f"{macd} / Signal: {signal} / Hist: {hist}" if macd else "N/A"
    macd_bias = "BULLISH" if hist and hist > 0 else "BEARISH" if hist and hist < 0 else "N/A"

    # ATR for SL/TP
    atr_1m = calc_atr(m1, 14) if m1 else None
    atr_15m = calc_atr(m15, 14) if m15 else None
    sl_suggestion = round(price - atr_1m * 1.5, 5) if atr_1m else "N/A"
    tp1_suggestion = round(price + atr_1m * 2, 5) if atr_1m else "N/A"
    tp2_suggestion = round(price + atr_1m * 4, 5) if atr_1m else "N/A"

    # ADX
    adx_1m  = calc_adx(m1,  14) if m1  else 0
    adx_15m = calc_adx(m15, 14) if m15 else 0
    adx_str = f"1m={adx_1m} | 15m={adx_15m}"
    trending = adx_1m >= MIN_ADX or adx_15m >= MIN_ADX

    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = calc_bollinger(m1, 20) if m1 else (None, None, None)
    bb_str = f"Upper={bb_upper} | Mid={bb_mid} | Lower={bb_lower}" if bb_upper else "N/A"
    bb_position = "N/A"
    if bb_upper and bb_lower:
        if price > bb_upper:
            bb_position = "ABOVE UPPER - overbought / potential reversal"
        elif price < bb_lower:
            bb_position = "BELOW LOWER - oversold / potential reversal"
        elif price > bb_mid:
            bb_position = "UPPER HALF - bullish bias"
        else:
            bb_position = "LOWER HALF - bearish bias"

    # Volume
    vol_label_1m,  vol_ratio_1m  = calc_volume_analysis(m1,  20) if m1  else ("N/A", 0)
    vol_label_15m, vol_ratio_15m = calc_volume_analysis(m15, 20) if m15 else ("N/A", 0)

    # Structure multi-tf
    struct_m1  = get_structure(m1)  if m1  else "N/A"
    struct_m15 = get_structure(m15) if m15 else "N/A"
    struct_h1  = get_structure(h1)  if h1  else "N/A"
    struct_h4  = get_structure(h4)  if h4  else "N/A"
    tf_align, align_count = check_tf_alignment(struct_m1, struct_m15, struct_h1, struct_h4)

    # ICT
    pd_zone = get_pd(price, h4) if h4 else "N/A"
    fvg = find_fvg(m1) if m1 else []
    obs = find_obs(m1) if m1 else []
    near_fvg = sorted(fvg, key=lambda x: abs(x['mid']-price))[:3]
    near_obs = sorted(obs, key=lambda x: abs(x['mid']-price))[:2]
    last5_1m  = m1[-5:]  if m1  else []
    last5_15m = m15[-5:] if m15 else []

    prompt = f"""You are an elite ICT scalping trader. Analyze this setup for a SCALP trade (entry on 1m).

═══ PAIR & PRICE ═══
Pair: {pair} | Price: {price}
Kill Zone: {kill_zone()}

═══ TREND (Higher TF) ═══
EMA Trend (H4): {ema_trend}
EMA50/200 on 1m: {ema50_1m} / {ema200_1m}
TF Alignment: {tf_align} ({align_count}/4 timeframes agree)
Structure: M1={struct_m1} | M15={struct_m15} | H1={struct_h1} | H4={struct_h4}
PD Zone (H4): {pd_zone}

═══ MOMENTUM ═══
RSI: 1m={rsi_1m} | 5m={rsi_5m} | 15m={rsi_15m} | 1H={rsi_1h} | 4H={rsi_4h}
MACD (5m): {macd_str} → {macd_bias}
ADX: {adx_str} | Trending: {trending}

═══ VOLATILITY ═══
ATR 1m: {atr_1m} | ATR 15m: {atr_15m}
Bollinger (1m): {bb_str}
BB Position: {bb_position}
ATR-based SL suggestion: {sl_suggestion}
ATR-based TP1/TP2: {tp1_suggestion} / {tp2_suggestion}

═══ VOLUME ═══
Volume 1m: {vol_label_1m}
Volume 15m: {vol_label_15m}

═══ ICT SETUPS ═══
FVG zones (1m): {json.dumps(near_fvg)}
Order Blocks (1m): {json.dumps(near_obs)}
Last 5 candles 1m: {json.dumps(last5_1m)}
Last 5 candles 15m: {json.dumps(last5_15m)}
{extra}

SCALPING RULES:
- Only BUY if price is DISCOUNT + BULLISH structure + volume confirms
- Only SELL if price is PREMIUM + BEARISH structure + volume confirms  
- Use ATR-based SL/TP provided above as reference
- Entry must be on 1m after confluence
- No trade if ADX < 25 and volume is LOW

Reply ONLY in this exact format:
DIRECTION: [BUY/SELL/WAIT]
ENTRY: [price]
SL: [price] ([pips/points] risk)
TP1: [price] ([pips/points])
TP2: [price] ([pips/points])
RR: [ratio]
SIGNAL: [1-10]
TIMING: [Good/Neutral/Bad]
WIN PROBABILITY: [x%]
CONFLUENCE: [list main confirming factors]
REASON: [one sentence]"""

    return ask_groq(prompt)

# ========== SIGNAL FILTER ==========
def parse_signal_score(analysis):
    try:
        for line in analysis.split('\n'):
            if 'SIGNAL:' in line:
                score = int(''.join(filter(str.isdigit, line.split(':')[1][:3])))
                return score
    except:
        pass
    return 0

def parse_win_prob(analysis):
    try:
        for line in analysis.split('\n'):
            if 'WIN PROBABILITY:' in line:
                prob = int(''.join(filter(str.isdigit, line.split(':')[1][:5])))
                return prob
    except:
        pass
    return 0

def format_signal_message(name, price, analysis, extra_info=""):
    score = parse_signal_score(analysis)
    prob = parse_win_prob(analysis)

    direction = "⚪"
    for line in analysis.split('\n'):
        if 'DIRECTION:' in line:
            if 'BUY' in line:
                direction = "🟢 BUY"
            elif 'SELL' in line:
                direction = "🔴 SELL"
            elif 'WAIT' in line:
                direction = "⚪ WAIT"

    stars = "⭐" * min(score, 10)
    msg = f"{'─'*30}\n"
    msg += f"<b>{name}</b> | <b>{price}</b>\n"
    msg += f"{direction} | Score: {score}/10 {stars}\n"
    msg += f"Win Prob: {prob}%\n"
    if extra_info:
        msg += f"{extra_info}\n"
    msg += f"\n{analysis}\n"
    return msg, score, prob

# ========== RUN ==========
def run():
    now = datetime.now(timezone.utc)
    kz = kill_zone()
    print(f"\n{'='*60}")
    print(f"  BEAST TRADER v5.0 | {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  {kz}")
    print(f"{'='*60}")

    # Kill Zone alert
    if is_kill_zone():
        send_telegram(f"⚡ <b>KILL ZONE ACTIVE</b>\n{kz}\n🎯 Focus! High probability setups incoming!")

    strong_signals = []
    all_results = []

    # ===== CRYPTO =====
    for symbol, name in [("BTCUSDT", "BTC/USD"), ("ETHUSDT", "ETH/USD")]:
        try:
            print(f"\n[*] {name}...")
            m1  = get_klines_futures(symbol, "1m",  200)
            m5  = get_klines_futures(symbol, "5m",  200)
            m15 = get_klines_futures(symbol, "15m", 200)
            h1  = get_klines_futures(symbol, "1h",  200)
            h4  = get_klines_futures(symbol, "4h",  200)
            price = m1[-1]['close'] if m1 else 0
            vol_label, vol_ratio = calc_volume_analysis(m1, 20)
            adx_val = calc_adx(m1, 14)
            funding = get_funding(symbol)
            pressure = get_pressure(symbol)
            extra = f"Funding: {funding}% | OB: {pressure}"

            # Skip low volume + low ADX
            if vol_ratio < 0.5 and adx_val < MIN_ADX:
                print(f"    SKIP - Low volume ({vol_ratio}x) + Low ADX ({adx_val})")
                continue

            res = analyze(name, price, m1, m5, m15, h1, h4, extra)
            extra_info = f"Vol: {vol_label} | ADX: {adx_val} | {pressure}"
            msg, score, prob = format_signal_message(name, price, res, extra_info)
            all_results.append((name, price, res, score, prob, msg))
            print(f"    Price: {price} | Score: {score} | Prob: {prob}% | Vol: {vol_label}")

        except Exception as e:
            print(f"    [ERROR] {name}: {e}")

    # ===== FOREX =====
    forex_list = [
        ("EURUSDT", "EUR/USD", "binance_spot", "EURUSD"),
        ("GBPUSDT", "GBP/USD", "binance_spot", "GBPUSD"),
        (None,      "USD/JPY", "forex_api",    "USDJPY"),
        (None,      "USD/CHF", "forex_api",    "USDCHF"),
    ]
    for sym, name, source, forex_pair in forex_list:
        open_status, closed_msg = is_market_open("forex")
        print(f"\n[*] {name}...")
        if not open_status:
            print(f"    {closed_msg}")
            continue
        try:
            if source == "binance_spot" and sym:
                m1  = get_klines_spot(sym, "1m",  200)
                m5  = get_klines_spot(sym, "5m",  200)
                m15 = get_klines_spot(sym, "15m", 200)
                h1  = get_klines_spot(sym, "1h",  200)
                h4  = get_klines_spot(sym, "4h",  200)
                price = m1[-1]['close'] if m1 else get_forex_price(forex_pair)
            else:
                price = get_forex_price(forex_pair)
                m1 = m5 = m15 = h1 = h4 = []

            if not price:
                continue

            vol_label, vol_ratio = calc_volume_analysis(m1, 20) if m1 else ("N/A", 0)
            adx_val = calc_adx(m1, 14) if m1 else 0

            if m1 and vol_ratio < 0.5 and adx_val < MIN_ADX:
                print(f"    SKIP - Low volume + Low ADX")
                continue

            res = analyze(name, price, m1, m5, m15, h1, h4)
            extra_info = f"Vol: {vol_label} | ADX: {adx_val}" if m1 else ""
            msg, score, prob = format_signal_message(name, price, res, extra_info)
            all_results.append((name, price, res, score, prob, msg))
            print(f"    Price: {price} | Score: {score} | Prob: {prob}%")

        except Exception as e:
            print(f"    [ERROR] {name}: {e}")

    # ===== GOLD =====
    print(f"\n[*] XAU/USD...")
    open_status, _ = is_market_open("gold")
    if open_status:
        try:
            price = get_real_gold_price()
            if price:
                m15_raw = get_yahoo_candles("GC%3DF", "15m", "5d")
                m1_raw  = get_yahoo_candles("GC%3DF", "1m",  "1d")
                vol_label, vol_ratio = calc_volume_analysis(m1_raw, 20) if m1_raw else ("N/A", 0)
                adx_val = calc_adx(m1_raw, 14) if m1_raw else 0
                res = analyze("XAU/USD", price, m1_raw, [], m15_raw, [], [])
                extra_info = f"Vol: {vol_label} | ADX: {adx_val}"
                msg, score, prob = format_signal_message("XAU/USD", price, res, extra_info)
                all_results.append(("XAU/USD", price, res, score, prob, msg))
                print(f"    Price: {price} | Score: {score} | Prob: {prob}%")
        except Exception as e:
            print(f"    [ERROR] XAU/USD: {e}")

    # ===== INDICES =====
    for ticker, name in [("^NDX", "USTEC"), ("^DJI", "US30")]:
        print(f"\n[*] {name}...")
        open_status, _ = is_market_open("index")
        if not open_status:
            continue
        try:
            price = get_yahoo_price(ticker)
            if price:
                m15_raw = get_yahoo_candles(ticker, "15m", "5d")
                m1_raw  = get_yahoo_candles(ticker, "1m",  "1d")
                res = analyze(name, price, m1_raw, [], m15_raw, [], [])
                msg, score, prob = format_signal_message(name, price, res)
                all_results.append((name, price, res, score, prob, msg))
                print(f"    Price: {price} | Score: {score} | Prob: {prob}%")
        except Exception as e:
            print(f"    [ERROR] {name}: {e}")

    # ===== FILTER & SEND =====
    print(f"\n{'='*60}")
    print(f"  FILTERING SIGNALS (min score={MIN_SIGNAL_SCORE}, min prob={MIN_WIN_PROB}%)")
    print(f"{'='*60}")

    # Header
    header = (
        f"🤖 <b>BEAST TRADER v5.0</b>\n"
        f"⏰ {now.strftime('%H:%M')} UTC\n"
        f"📍 {kz}\n"
        f"{'─'*30}"
    )

    filtered = [(n, p, r, s, prob, m) for n, p, r, s, prob, m in all_results
                if s >= MIN_SIGNAL_SCORE and prob >= MIN_WIN_PROB]

    if filtered:
        kz_tag = "⚡ <b>KILL ZONE SIGNAL</b>\n" if is_kill_zone() else ""
        send_telegram(kz_tag + header + f"\n🎯 <b>{len(filtered)} SIGNAL(S) — ACT NOW</b>")
        for name, price, res, score, prob, msg in filtered:
            send_telegram(msg)
            print(f"  ✅ SENT: {name} | Score:{score} | Prob:{prob}%")
    else:
        print(f"  No strong signals this cycle — nothing sent")

    print(f"\n  Next update: 15 min\n")

# ========== ENTRY POINT ==========
if __name__ == "__main__":
    send_telegram("🚀 <b>BEAST TRADER v5.0 STARTED</b>\n✅ All systems online\n⚙️ Scalping mode active")
    while True:
        try:
            run()
        except Exception as e:
            print(f"[CRITICAL ERROR] {e}")
            send_telegram(f"⚠️ Beast Trader error: {e}")
        time.sleep(900)
