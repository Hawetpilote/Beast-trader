"""
╔══════════════════════════════════════════════════════════════╗
║           BEAST TRADER v6 — LIVE BOT                        ║
║           Railway 24/7 + Telegram Alerts                    ║
╠══════════════════════════════════════════════════════════════╣
║  الإعدادات المثبتة:                                          ║
║  ETH  → S/R+Sweep | London  07-10 UTC | BUY | 1:2          ║
║  BTC  → S/R+Sweep | NY_PM   18:30 UTC | BUY | 1:2          ║
║  GBP  → MTF+Sweep | NY_PM   18:30 UTC | BUY | 1:2          ║
║  QQQ  → MTF+CHoCH | NY_Open 14:30 UTC | BUY | 1:2          ║
║  XAU  → Sweep     | NY_PM   18:30 UTC | B+S | 1:2          ║
║                                                              ║
║  يفحص كل 15 دقيقة تلقائياً                                  ║
╚══════════════════════════════════════════════════════════════╝
"""
import os, time, requests
from datetime import datetime, timezone
from collections import defaultdict

# ═══════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN",  "8793787115:AAFR0t6vkAKQphhCz4xeniqgekCGqdJ9SVg")
TELEGRAM_CHAT   = os.environ.get("TELEGRAM_CHAT_ID","8241439090")
TWELVE_KEY      = os.environ.get("TWELVE_KEY",      "4004d90981ad45c3ab3314d9d7bde791")

CHECK_INTERVAL  = 900   # 15 دقيقة
RISK_PERCENT    = 1.0   # 1% لكل صفقة
ACCOUNT_SIZE    = 1000  # Demo Exness

PAIR_CONFIG = {
    "ETH/USD": {"sessions":["London"],          "strategy":"SR_SWEEP",  "buy_only":True,  "rr":2.0, "src":"binance", "sym":"ETHUSDT"},
    "BTC/USD": {"sessions":["NY_PM"],            "strategy":"SR_SWEEP",  "buy_only":True,  "rr":2.0, "src":"binance", "sym":"BTCUSDT"},
    "GBP/USD": {"sessions":["NY_PM"],            "strategy":"MTF_SWEEP", "buy_only":True,  "rr":2.0, "src":"twelve",  "sym":"GBP/USD"},
    "QQQ":     {"sessions":["NY_Open"],          "strategy":"MTF_CHOCH", "buy_only":True,  "rr":2.0, "src":"twelve",  "sym":"QQQ"},
    "XAU/USD": {"sessions":["NY_PM","NY_Open"],  "strategy":"SWEEP_ONLY","buy_only":False, "rr":2.0, "src":"twelve",  "sym":"XAU/USD"},
}

# ═══════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════
def tg_send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def tg_signal(pair, direction, price, sl, tp, rr, strategy, sess, bias, reason):
    dir_emoji = "🟢 BUY" if direction == "BUY" else "🔴 SELL"
    risk_amt   = round(ACCOUNT_SIZE * RISK_PERCENT / 100, 2)
    reward_amt = round(risk_amt * rr, 2)
    sl_pips    = round(abs(price - sl), 5)
    tp_pips    = round(abs(tp - price), 5)
    now        = datetime.now(tz=timezone.utc).strftime("%H:%M UTC")

    msg = (
        f"⚡ <b>BEAST TRADER v6</b> ⚡\n"
        f"{'─'*30}\n"
        f"{dir_emoji}  <b>{pair}</b>\n"
        f"💰 دخول:  <b>{price:.5f}</b>\n"
        f"🛑 SL:    {sl:.5f}  ({sl_pips:.5f})\n"
        f"🎯 TP:    {tp:.5f}  ({tp_pips:.5f})\n"
        f"📊 RR:    1:{int(rr)}\n"
        f"{'─'*30}\n"
        f"📍 جلسة:  {sess}\n"
        f"📈 Bias:  {bias}\n"
        f"🔍 إشارة: {strategy} → {reason}\n"
        f"💵 ريسك:  ${risk_amt}  →  ربح محتمل: ${reward_amt}\n"
        f"⏰ {now}\n"
        f"{'─'*30}\n"
        f"⚠️ <i>للديمو فقط — تحقق يدوياً قبل الدخول</i>"
    )
    tg_send(msg)
    print(f"✅ إشارة أُرسلت: {direction} {pair} @ {price:.5f}")

def tg_status(msg):
    tg_send(f"ℹ️ Beast Trader v6\n{msg}")

# ═══════════════════════════════════════════
# FETCH
# ═══════════════════════════════════════════
def fetch_binance(symbol, interval, limit=500):
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=20).json()
        if not isinstance(r, list): return []
        return [{"time": x[0]/1000, "open": float(x[1]), "high": float(x[2]),
                 "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])}
                for x in r]
    except Exception as e:
        print(f"Binance error {symbol} {interval}: {e}")
        return []

def fetch_binance_multi(symbol):
    """جلب كل الفريمات مرة واحدة"""
    return {
        "daily": fetch_binance(symbol, "1d",  500),
        "h4":    fetch_binance(symbol, "4h",  500),
        "h1":    fetch_binance(symbol, "1h",  500),
        "m15":   fetch_binance(symbol, "15m", 300),
    }

def fetch_twelve_tf(symbol, interval, limit=300):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={"symbol": symbol, "interval": interval,
                    "outputsize": limit, "apikey": TWELVE_KEY,
                    "format": "JSON", "order": "ASC"},
            timeout=30).json()
        if r.get("status") != "ok": return []
        candles = []
        for v in r.get("values", []):
            dt_str = v["datetime"]
            if len(dt_str) == 10: dt_str += " 00:00:00"
            try:
                ts = int(datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                         .replace(tzinfo=timezone.utc).timestamp())
                candles.append({
                    "time": ts, "open": float(v["open"]),
                    "high": float(v["high"]), "low": float(v["low"]),
                    "close": float(v["close"]),
                    "volume": float(v.get("volume") or 0)})
            except: pass
        return candles
    except Exception as e:
        print(f"Twelve error {symbol} {interval}: {e}")
        return []

def fetch_twelve_multi(symbol):
    h1 = fetch_twelve_tf(symbol, "1h", 500)
    time.sleep(9)
    h4 = build_tf(h1, 4)
    daily = fetch_twelve_tf(symbol, "1day", 300)
    time.sleep(9)
    m15 = fetch_twelve_tf(symbol, "15min", 300)
    return {"daily": daily, "h4": h4, "h1": h1, "m15": m15}

def build_tf(candles, n):
    r = []
    for i in range(0, len(candles)-n+1, n):
        g = candles[i:i+n]
        r.append({"time": g[0]["time"], "open": g[0]["open"],
                  "high": max(x["high"] for x in g),
                  "low":  min(x["low"]  for x in g),
                  "close": g[-1]["close"],
                  "volume": sum(x["volume"] for x in g)})
    return r

# ═══════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════
def calc_atr(c, p=14):
    if len(c) < p+1: return 0.001
    tr = [max(c[i]["high"]-c[i]["low"],
              abs(c[i]["high"]-c[i-1]["close"]),
              abs(c[i]["low"] -c[i-1]["close"]))
          for i in range(1, len(c))]
    return sum(tr[-p:]) / p

def calc_rsi(c, p=14):
    if len(c) < p+2: return 50
    cl = [x["close"] for x in c]
    g  = [max(cl[i]-cl[i-1], 0) for i in range(1, len(cl))]
    l  = [max(cl[i-1]-cl[i], 0) for i in range(1, len(cl))]
    ag = sum(g[-p:])/p; al = sum(l[-p:])/p
    return 50 if al == 0 else 100 - 100/(1+ag/al)

def get_sess(ts):
    h = datetime.fromtimestamp(ts, tz=timezone.utc).hour
    m = datetime.fromtimestamp(ts, tz=timezone.utc).minute
    if 7 <= h < 10:                          return "London"
    if (h == 14 and m >= 30) or h == 15:     return "NY_Open"
    if (h == 18 and m >= 30) or 19 <= h <= 20: return "NY_PM"
    return "Other"

def get_daily_bias(daily, target_ts):
    past = [c for c in daily if c["time"] <= target_ts]
    if len(past) < 20: return "NEUTRAL"
    w = past[-20:]
    highs = [w[i]["high"] for i in range(2, len(w)-2)
             if w[i]["high"] > w[i-1]["high"] and w[i]["high"] > w[i+1]["high"]]
    lows  = [w[i]["low"]  for i in range(2, len(w)-2)
             if w[i]["low"]  < w[i-1]["low"]  and w[i]["low"]  < w[i+1]["low"]]
    if len(highs) < 2 or len(lows) < 2: return "NEUTRAL"
    if highs[-1] > highs[-2] and lows[-1] > lows[-2]: return "BULL"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]: return "BEAR"
    return "NEUTRAL"

def build_sr_zones(candles, lookback=200):
    if len(candles) < 20: return []
    a   = calc_atr(candles[-14:])
    tol = a * 0.5
    w   = candles[-lookback:] if len(candles) > lookback else candles
    sh  = [w[i]["high"] for i in range(4, len(w)-4)
           if all(w[i]["high"] >= w[j]["high"] for j in range(i-4, i+5) if j != i)]
    sl  = [w[i]["low"]  for i in range(4, len(w)-4)
           if all(w[i]["low"]  <= w[j]["low"]  for j in range(i-4, i+5) if j != i)]
    raw = sh + sl
    if not raw: return []
    zones = []; used = [False]*len(raw)
    for i in range(len(raw)):
        if used[i]: continue
        group = [raw[i]]
        for j in range(i+1, len(raw)):
            if not used[j] and abs(raw[j]-raw[i]) <= tol*2:
                group.append(raw[j]); used[j] = True
        if len(group) >= 2:
            zones.append({"level": sum(group)/len(group), "tol": tol, "touches": len(group)})
        used[i] = True
    return zones

def near_sr(price, zones, mult=1.5):
    for z in zones:
        if abs(price - z["level"]) <= z["tol"] * mult:
            return True, z
    return False, None

def find_poi(h4, h1, target_ts, bias):
    pois = []
    for tf_label, tf_c in [("4H", h4), ("1H", h1)]:
        past = [c for c in tf_c if c["time"] <= target_ts][-60:]
        for i in range(2, len(past)):
            if bias == "BULL" and past[i]["low"] > past[i-2]["high"]:
                pois.append({"top": past[i]["low"], "bot": past[i-2]["high"], "tf": tf_label, "type": "FVG"})
            elif bias == "BEAR" and past[i]["high"] < past[i-2]["low"]:
                pois.append({"top": past[i-2]["low"], "bot": past[i]["high"], "tf": tf_label, "type": "FVG"})
        for i in range(1, len(past)-2):
            curr = past[i]; nxt = past[i+1]
            bc = abs(curr["close"]-curr["open"]); bn = abs(nxt["close"]-nxt["open"])
            if bc < 0.0001: continue
            if (bias == "BULL" and curr["close"] < curr["open"] and bn > bc*0.6 and nxt["close"] > nxt["open"]):
                pois.append({"top": curr["open"], "bot": curr["low"], "tf": tf_label, "type": "OB"})
            elif (bias == "BEAR" and curr["close"] > curr["open"] and bn > bc*0.6 and nxt["close"] < nxt["open"]):
                pois.append({"top": curr["high"], "bot": curr["close"], "tf": tf_label, "type": "OB"})
    return pois[-8:]

def at_poi(price, pois, atr_val):
    for poi in pois:
        tol = atr_val * 0.4
        if poi["bot"]-tol <= price <= poi["top"]+tol:
            return True, poi
    return False, None

def detect_sweep(candles, bias, atr_val, lookback=15):
    if len(candles) < lookback+2: return False, ""
    c = candles[-1]; w = candles[-lookback-1:-1]
    if bias == "BULL":
        key        = min(x["low"] for x in w)
        swept      = c["low"] < key
        recovered  = c["close"] > key
        pierce     = key - c["low"]
        lower_wick = min(c["open"],c["close"]) - c["low"]
        body       = abs(c["close"]-c["open"])
        wick_ok    = lower_wick > body*0.35 if body > 0.0001 else False
        ok = swept and recovered and atr_val*0.05 <= pierce <= atr_val*2.0 and (c["close"]>c["open"] or wick_ok)
        return ok, f"Sweep↑ كسر {key:.5f}"
    else:
        key        = max(x["high"] for x in w)
        swept      = c["high"] > key
        recovered  = c["close"] < key
        pierce     = c["high"] - key
        upper_wick = c["high"] - max(c["open"],c["close"])
        body       = abs(c["close"]-c["open"])
        wick_ok    = upper_wick > body*0.35 if body > 0.0001 else False
        ok = swept and recovered and atr_val*0.05 <= pierce <= atr_val*2.0 and (c["close"]<c["open"] or wick_ok)
        return ok, f"Sweep↓ كسر {key:.5f}"

def detect_bos_choch(candles, bias, lookback=30):
    past = candles[-lookback:]
    if len(past) < 8: return False, "NONE", ""
    last = past[-1]; prev = past[-2]
    highs = [past[j]["high"] for j in range(2, len(past)-1)
             if past[j]["high"] > past[j-1]["high"] and past[j]["high"] > past[j+1]["high"]]
    lows  = [past[j]["low"]  for j in range(2, len(past)-1)
             if past[j]["low"]  < past[j-1]["low"]  and past[j]["low"]  < past[j+1]["low"]]
    if bias == "BULL":
        if highs and last["close"] > highs[-1]:
            return True, "BOS",   f"BOS فوق {highs[-1]:.5f}"
        if last["close"] > last["open"] and last["close"] > prev["high"]:
            return True, "CHoCH", f"CHoCH فوق {prev['high']:.5f}"
    else:
        if lows  and last["close"] < lows[-1]:
            return True, "BOS",   f"BOS تحت {lows[-1]:.5f}"
        if last["close"] < last["open"] and last["close"] < prev["low"]:
            return True, "CHoCH", f"CHoCH تحت {prev['low']:.5f}"
    return False, "NONE", ""

# ═══════════════════════════════════════════
# SIGNAL ENGINE
# ═══════════════════════════════════════════
def check_signal(name, data, cfg):
    """
    يفحص زوجاً واحداً الآن
    يرجع signal dict أو None
    """
    daily = data.get("daily", [])
    h4    = data.get("h4",    [])
    h1    = data.get("h1",    [])
    m15   = data.get("m15",   [])

    if len(m15) < 50 or len(daily) < 20: return None

    # ── الوقت الحالي ──
    now_ts  = time.time()
    sess    = get_sess(now_ts)
    if sess not in cfg["sessions"]: return None

    dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    if dt.weekday() >= 5: return None  # عطلة

    # ── آخر شمعة 15m ──
    last = m15[-1]
    a    = calc_atr(m15[-14:])
    if not a: return None

    price = last["close"]

    # ── RSI ──
    rsi_val = calc_rsi(m15[-16:])

    # ── Daily Bias ──
    bias = get_daily_bias(daily, now_ts)
    if bias == "NEUTRAL": return None

    direction = "BUY" if bias == "BULL" else "SELL"
    if cfg["buy_only"] and direction == "SELL": return None

    # RSI فلتر
    if direction == "BUY"  and rsi_val > 72: return None
    if direction == "SELL" and rsi_val < 28: return None

    strategy  = cfg["strategy"]
    entry     = False
    reason    = ""

    if strategy == "SR_SWEEP":
        sr_zones    = build_sr_zones(h1)
        sr_hit, _   = near_sr(price, sr_zones)
        sw_hit, sw_r = detect_sweep(m15, bias, a)
        if sr_hit and sw_hit:
            entry  = True
            reason = f"S/R Zone + {sw_r}"
        elif sw_hit:
            entry  = True
            reason = sw_r

    elif strategy == "MTF_SWEEP":
        pois        = find_poi(h4, h1, now_ts, bias)
        poi_hit, _  = at_poi(price, pois, a*5)
        sw_hit, sw_r = detect_sweep(m15, bias, a)
        if poi_hit and sw_hit:
            entry  = True
            reason = f"POI + {sw_r}"

    elif strategy == "MTF_CHOCH":
        pois        = find_poi(h4, h1, now_ts, bias)
        poi_hit, _  = at_poi(price, pois, a*5)
        bos_hit, sig, bos_r = detect_bos_choch(m15, bias)
        if poi_hit and bos_hit and sig == "CHoCH":
            entry  = True
            reason = f"POI + {bos_r}"

    elif strategy == "SWEEP_ONLY":
        sw_hit, sw_r = detect_sweep(m15, bias, a)
        if sw_hit:
            entry  = True
            reason = sw_r

    if not entry: return None

    # ── حساب SL / TP ──
    sl_size = a * 1.2
    if direction == "BUY":
        sl = price - sl_size
        tp = price + sl_size * cfg["rr"]
    else:
        sl = price + sl_size
        tp = price - sl_size * cfg["rr"]

    return {
        "pair":      name,
        "direction": direction,
        "price":     price,
        "sl":        sl,
        "tp":        tp,
        "rr":        cfg["rr"],
        "strategy":  strategy,
        "sess":      sess,
        "bias":      bias,
        "reason":    reason,
        "rsi":       round(rsi_val, 1),
        "atr":       round(a, 5),
        "time":      datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

# ═══════════════════════════════════════════
# COOLDOWN MANAGER
# ═══════════════════════════════════════════
last_signal_time = {}  # {pair: timestamp}
COOLDOWN = 4 * 3600    # 4 ساعات بين كل إشارتين لنفس الزوج

def is_cooled(pair):
    last = last_signal_time.get(pair, 0)
    return (time.time() - last) >= COOLDOWN

def mark_signal(pair):
    last_signal_time[pair] = time.time()

# ═══════════════════════════════════════════
# DATA CACHE — نجدد كل ساعة
# ═══════════════════════════════════════════
data_cache    = {}
last_fetch    = {}
FETCH_INTERVAL = 3600  # ساعة

def refresh_data(name, cfg):
    now = time.time()
    if now - last_fetch.get(name, 0) < FETCH_INTERVAL:
        return data_cache.get(name, {})
    print(f"  📥 جلب بيانات {name}...")
    try:
        if cfg["src"] == "binance":
            d = fetch_binance_multi(cfg["sym"])
        else:
            d = fetch_twelve_multi(cfg["sym"])
        if d.get("m15"):
            data_cache[name]  = d
            last_fetch[name]  = now
            print(f"  ✅ {name}: {len(d['m15'])} شمعة 15m")
        return data_cache.get(name, {})
    except Exception as e:
        print(f"  ⚠️ خطأ جلب {name}: {e}")
        return data_cache.get(name, {})

# ═══════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════
def main():
    print("╔"+"═"*56+"╗")
    print("║" + " BEAST TRADER v6 — LIVE ".center(56) + "║")
    print("║" + " يفحص كل 15 دقيقة — Railway 24/7 ".center(56) + "║")
    print("╚"+"═"*56+"╝")
    print(f"\n  الأزواج: {', '.join(PAIR_CONFIG.keys())}")
    print(f"  الحساب:  Demo Exness ${ACCOUNT_SIZE}")
    print(f"  الريسك:  {RISK_PERCENT}% لكل صفقة\n")

    # إشعار بدء التشغيل
    tg_send(
        "🚀 <b>Beast Trader v6 شغّال!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 الأزواج: ETH · BTC · GBP · QQQ · XAU\n"
        "⏱️ فحص كل 15 دقيقة\n"
        "🎯 Kill Zones فقط\n"
        "💰 Demo Exness\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <i>بناءً على 3 أشهر بحث + ICT منهجية الحربي</i>"
    )

    scan_count   = 0
    signal_count = 0

    while True:
        now_utc = datetime.now(tz=timezone.utc)
        scan_count += 1
        print(f"\n{'─'*50}")
        print(f"  🔍 فحص #{scan_count} — {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
        sess_now = get_sess(time.time())
        print(f"  📍 الجلسة: {sess_now}")
        if now_utc.weekday() >= 5:
            print("  💤 عطلة نهاية الأسبوع — لا تداول")
            time.sleep(CHECK_INTERVAL); continue

        signals_found = []

        for name, cfg in PAIR_CONFIG.items():
            # تحقق سريع من الجلسة قبل جلب البيانات
            if sess_now not in cfg["sessions"] and sess_now != "Other":
                continue
            if not is_cooled(name):
                remaining = int((COOLDOWN - (time.time() - last_signal_time.get(name,0)))/60)
                print(f"  ⏳ {name}: cooldown {remaining}min")
                continue

            # جلب / تحديث البيانات
            data = refresh_data(name, cfg)
            if not data:
                continue

            # فحص الإشارة
            sig = check_signal(name, data, cfg)
            if sig:
                signals_found.append(sig)
                mark_signal(name)
                signal_count += 1
                print(f"  🎯 إشارة! {name} {sig['direction']} @ {sig['price']:.5f}")
                tg_signal(
                    sig["pair"], sig["direction"], sig["price"],
                    sig["sl"],   sig["tp"],        sig["rr"],
                    sig["strategy"], sig["sess"],  sig["bias"],
                    sig["reason"]
                )
            else:
                print(f"  — {name}: لا إشارة ({sess_now})")

        if not signals_found:
            print(f"  ✓ لا إشارات — إجمالي الإشارات: {signal_count}")

        # تقرير يومي الساعة 21:00 UTC
        if now_utc.hour == 21 and now_utc.minute < 15:
            tg_send(
                f"📊 <b>تقرير يومي</b>\n"
                f"عمليات الفحص: {scan_count}\n"
                f"إشارات اليوم: {signal_count}\n"
                f"⏰ {now_utc.strftime('%Y-%m-%d')}"
            )

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
