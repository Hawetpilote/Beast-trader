import requests
import os
import json
import time
from datetime import datetime, timezone

GROQ_KEY = os.environ.get("GROQ_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except:
        pass

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
            return False, f"MARKET CLOSED - US market opens at 13:30 UTC"
        else:
            return False, "MARKET CLOSED - US market closed for today"
    return True, ""

def ask_groq(prompt):
    headers = {"Authorization": "Bearer " + GROQ_KEY, "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 500, "temperature": 0.1}
    r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
    return r.json()['choices'][0]['message']['content']

def get_klines_futures(symbol, interval, limit=100):
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/klines", params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        if r.status_code == 200:
            return [{"time": datetime.fromtimestamp(c[0]/1000).strftime('%m/%d %H:%M'), "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])} for c in r.json()]
    except:
        pass
    return []

def get_klines_spot(symbol, interval, limit=100):
    try:
        r = requests.get("https://api.binance.com/api/v3/klines", params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        if r.status_code == 200:
            return [{"time": datetime.fromtimestamp(c[0]/1000).strftime('%m/%d %H:%M'), "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])} for c in r.json()]
    except:
        pass
    return []

def get_real_gold_price():
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
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
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return float(r.json()['chart']['result'][0]['meta']['regularMarketPrice'])
    except:
        return None

def get_funding(symbol):
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/fundingRate", params={"symbol": symbol, "limit": 1}, timeout=10)
        return round(float(r.json()[-1]['fundingRate']) * 100, 4)
    except:
        return 0

def get_pressure(symbol):
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/depth", params={"symbol": symbol, "limit": 10}, timeout=10)
        d = r.json()
        bids = sum(float(b[1]) for b in d['bids'])
        asks = sum(float(a[1]) for a in d['asks'])
        return "BUY PRESSURE" if bids > asks else "SELL PRESSURE"
    except:
        return "NEUTRAL"

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
            fvgs.append({"type": "Bullish_FVG", "low": ph, "high": cl, "mid": round((cl+ph)/2, 5)})
        elif ch < pl:
            fvgs.append({"type": "Bearish_FVG", "low": ch, "high": pl, "mid": round((ch+pl)/2, 5)})
    return fvgs

def find_obs(candles):
    obs = []
    for i in range(1, len(candles)-1):
        c = candles[i]
        n = candles[i+1]
        bc = abs(c['close'] - c['open'])
        bn = abs(n['close'] - n['open'])
        if c['close'] > c['open'] and n['close'] < n['open'] and bn > bc * 1.5:
            obs.append({"type": "Bearish_OB", "high": c['high'], "low": c['low'], "mid": round((c['high']+c['low'])/2, 5)})
        elif c['close'] < c['open'] and n['close'] > n['open'] and bn > bc * 1.5:
            obs.append({"type": "Bullish_OB", "high": c['high'], "low": c['low'], "mid": round((c['high']+c['low'])/2, 5)})
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

def kill_zone():
    hour = datetime.now(timezone.utc).hour
    if 7 <= hour <= 9:
        return "LONDON OPEN - BEST TIME"
    elif 12 <= hour <= 14:
        return "NEW YORK OPEN - BEST TIME"
    elif 20 <= hour <= 22:
        return "ASIAN OPEN"
    return f"OUTSIDE KILL ZONE (UTC {hour}:00)"

def analyze(pair, price, m1, m15, h4, extra=""):
    rsi_1m = calc_rsi(m1) if m1 else "N/A"
    rsi_15m = calc_rsi(m15) if m15 else "N/A"
    rsi_4h = calc_rsi(h4) if h4 else "N/A"
    struct = get_structure(m15) if m15 else "N/A"
    pd = get_pd(price, h4) if h4 else "N/A"
    fvg = find_fvg(m15) if m15 else []
    obs = find_obs(m15) if m15 else []
    near_fvg = sorted(fvg, key=lambda x: abs(x['mid']-price))[:3]
    near_obs = sorted(obs, key=lambda x: abs(x['mid']-price))[:2]
    last5 = m15[-5:] if m15 else []
    prompt = f"""You are a professional ICT trader. Analyze and give precise signal.
Pair: {pair} | Price: {price}
Kill Zone: {kill_zone()}
RSI: 1m={rsi_1m} | 15m={rsi_15m} | 4H={rsi_4h}
Structure: {struct} | Zone: {pd}
{extra}
FVG zones: {json.dumps(near_fvg)}
Order Blocks: {json.dumps(near_obs)}
Last 5 candles 15m: {json.dumps(last5)}
Reply ONLY this exact format:
DIRECTION: [BUY/SELL/WAIT]
ENTRY: [price]
SL: [price]
TP1: [price]
TP2: [price]
RR: [ratio]
SIGNAL: [1-10]
TIMING: [Good/Neutral/Bad]
WIN PROBABILITY: [x%]
REASON: [one sentence max]"""
    return ask_groq(prompt)

def run():
    now = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"  BEAST TRADER v4.0 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  {kill_zone()}")
    print(f"{'='*60}")
    results = []

    for symbol, name in [("BTCUSDT", "BTC/USD"), ("ETHUSDT", "ETH/USD")]:
        try:
            print(f"\n[*] {name}...")
            m1 = get_klines_futures(symbol, "1m", 60)
            m15 = get_klines_futures(symbol, "15m", 100)
            h4 = get_klines_futures(symbol, "4h", 100)
            price = m1[-1]['close']
            extra = f"Funding Rate: {get_funding(symbol)}% | Orderbook: {get_pressure(symbol)}"
            res = analyze(name, price, m1, m15, h4, extra)
            results.append((name, price, res))
            print(f"    Price: {price}")
        except Exception as e:
            print(f"    [ERROR] {e}")

    for sym, name, source, forex_pair in [("EURUSDT","EUR/USD","binance_spot","EURUSD"),("GBPUSDT","GBP/USD","binance_spot","GBPUSD"),(None,"USD/JPY","forex_api","USDJPY"),(None,"USD/CHF","forex_api","USDCHF")]:
        open_status, closed_msg = is_market_open("forex")
        print(f"\n[*] {name}...")
        if not open_status:
            results.append((name, "N/A", f"MARKET CLOSED"))
            continue
        try:
            if source == "binance_spot" and sym:
                m1 = get_klines_spot(sym, "1m", 60)
                m15 = get_klines_spot(sym, "15m", 100)
                h4 = get_klines_spot(sym, "4h", 100)
                price = m1[-1]['close'] if m1 else get_forex_price(forex_pair)
            else:
                price = get_forex_price(forex_pair)
                m1, m15, h4 = [], [], []
            if price:
                res = analyze(name, price, m1, m15, h4)
                results.append((name, price, res))
                print(f"    Price: {price}")
        except Exception as e:
            print(f"    [ERROR] {e}")

    print(f"\n[*] XAU/USD...")
    open_status, closed_msg = is_market_open("gold")
    if not open_status:
        results.append(("XAU/USD", "N/A", "MARKET CLOSED"))
    else:
        try:
            price = get_real_gold_price()
            if price:
                res = analyze("XAU/USD", price, [], [], [])
                results.append(("XAU/USD", price, res))
                print(f"    Price: {price}")
        except Exception as e:
            print(f"    [ERROR] XAU/USD: {e}")

    for ticker, name in [("^NDX","USTEC"),("^DJI","US30")]:
        print(f"\n[*] {name}...")
        open_status, closed_msg = is_market_open("index")
        if not open_status:
            results.append((name, "N/A", "MARKET CLOSED"))
            continue
        try:
            price = get_yahoo_price(ticker)
            if price:
                res = analyze(name, price, [], [], [])
                results.append((name, price, res))
                print(f"    Price: {price}")
        except Exception as e:
            print(f"    [ERROR] {name}: {e}")

    print(f"\n{'='*60}")
    print(f"  SIGNALS | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    msg = f"🤖 <b>BEAST TRADER</b>\n⏰ {datetime.now().strftime('%H:%M')} UTC | {kill_zone()}\n\n"
    for name, price, analysis in results:
        print(f"\n{name} | {price}\n{analysis}")
        if "MARKET CLOSED" not in str(analysis):
            msg += f"<b>{name}</b> | {price}\n{analysis}\n\n{'─'*20}\n\n"

    send_telegram(msg)
    print(f"\n  Next update: 15 min\n")

if __name__ == "__main__":
    while True:
        run()
        time.sleep(900)
