"""
╔══════════════════════════════════════════════════════════════╗
║         AI-X ELITE PRO — LIVE BOT v2                        ║
║         SL/TP محسوب لكل زوج × فريم                         ║
╠══════════════════════════════════════════════════════════════╣
║  BTC/USD:  1m=150  5m=250  15m=400  1H=600   4H=1000       ║
║  ETH/USD:  1m=10   5m=18   15m=28   1H=45    4H=80         ║
║  GBP/USD:  1m=8p   5m=12p  15m=18p  1H=30p   4H=50p        ║
║  EUR/USD:  1m=8p   5m=12p  15m=18p  1H=30p   4H=50p        ║
║  XAU/USD:  1m=2    5m=4    15m=6    1H=10    4H=18         ║
║  QQQ:      1m=0.8  5m=1.5  15m=2.5  1H=4     4H=7          ║
╚══════════════════════════════════════════════════════════════╝
"""
import os, time, requests, threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ═══════════════════════════════════════════
# HEALTH SERVER
# ═══════════════════════════════════════════
START_TIME     = time.time()
SIGNAL_COUNTER = [0]

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        uptime = int(time.time()-START_TIME)
        self.wfile.write(
            f"AI-X ELITE PRO ✅ | uptime:{uptime}s | signals:{SIGNAL_COUNTER[0]}".encode())
    def log_message(self, *args): pass

def run_health():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

# ═══════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN",  "8793787115:AAFR0t6vkAKQphhCz4xeniqgekCGqdJ9SVg")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID","8241439090")
TWELVE_KEY     = os.environ.get("TWELVE_KEY",      "4004d90981ad45c3ab3314d9d7bde791")

CHECK_INTERVAL = 900    # 15 دقيقة
ACCOUNT_SIZE   = 1000
RISK_PCT       = 1.0

# ═══════════════════════════════════════════
# SL / TP لكل زوج × فريم (بالنقاط)
# RR ثابت = 1:2 دائماً
# ═══════════════════════════════════════════
SL_POINTS = {
    #         1m     5m    15m    1H    4H
    "BTC/USD":[150,  250,  400,  600, 1000],
    "ETH/USD":[ 10,   18,   28,   45,   80],
    "GBP/USD":[  8,   12,   18,   30,   50],  # pips (0.0001)
    "EUR/USD":[  8,   12,   18,   30,   50],  # pips
    "XAU/USD":[  2,    4,    6,   10,   18],  # دولار
    "QQQ":    [0.8,  1.5,  2.5,    4,    7],  # دولار
}
# الفريمات — الترتيب مهم (نفس ترتيب SL_POINTS)
TF_INDEX = {"1m":0, "5m":1, "15m":2, "1H":3, "4H":4}

def get_sl_tp(pair, tf_label):
    """يرجع (sl_size, tp_size) بالنقاط"""
    idx    = TF_INDEX.get(tf_label, 2)
    sl     = SL_POINTS.get(pair, SL_POINTS["BTC/USD"])[idx]
    tp     = sl * 2   # RR 1:2 دائماً
    return sl, tp

# ═══════════════════════════════════════════
# الأزواج والفريمات
# ═══════════════════════════════════════════
PAIRS = {
    "BTC/USD": {"src":"binance", "sym":"BTCUSDT"},
    "ETH/USD": {"src":"binance", "sym":"ETHUSDT"},
    "GBP/USD": {"src":"twelve",  "sym":"GBP/USD"},
    "EUR/USD": {"src":"twelve",  "sym":"EUR/USD"},
    "XAU/USD": {"src":"twelve",  "sym":"XAU/USD"},
    "QQQ":     {"src":"twelve",  "sym":"QQQ"},
}

TIMEFRAMES = [
    {"label":"1m",  "binance":"1m",  "twelve":"1min",  "limit":200},
    {"label":"5m",  "binance":"5m",  "twelve":"5min",  "limit":200},
    {"label":"15m", "binance":"15m", "twelve":"15min", "limit":200},
    {"label":"1H",  "binance":"1h",  "twelve":"1h",    "limit":200},
    {"label":"4H",  "binance":"4h",  "twelve":"4h",    "limit":200},
]

# ═══════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════
def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id":TELEGRAM_CHAT,"text":msg,"parse_mode":"HTML"},
            timeout=15)
    except Exception as e:
        print(f"TG error: {e}")

def tg_signal(pair, tf, direction, price, sl, tp, sl_pts, reason, sess):
    emoji  = "🟢 BUY"  if direction=="L" else "🔴 SELL"
    rr     = 2
    risk   = round(ACCOUNT_SIZE * RISK_PCT / 100, 2)
    reward = round(risk * rr, 2)
    now    = datetime.now(tz=timezone.utc).strftime("%H:%M UTC")

    # تحديد وحدة النقاط
    if pair in ["GBP/USD","EUR/USD"]: unit = "pip"
    elif pair in ["BTC/USD"]:         unit = "pt"
    else:                              unit = "$"

    msg = (
        f"⚡ <b>AI-X ELITE PRO</b> ⚡\n"
        f"{'─'*30}\n"
        f"{emoji}  <b>{pair}</b>  [{tf}]\n"
        f"💰 دخول:  <b>{price:.5f}</b>\n"
        f"🛑 SL:    {sl:.5f}  ({sl_pts}{unit})\n"
        f"🎯 TP:    {tp:.5f}  ({sl_pts*2}{unit})\n"
        f"📊 RR:    1:{rr}\n"
        f"{'─'*30}\n"
        f"📍 جلسة:  {sess}\n"
        f"🔍 إشارة: {reason}\n"
        f"💵 ريسك:  ${risk}  →  ربح: ${reward}\n"
        f"⏰ {now}\n"
        f"{'─'*30}\n"
        f"⚠️ <i>تحقق من الشارت قبل الدخول</i>"
    )
    tg(msg)
    SIGNAL_COUNTER[0] += 1
    print(f"  📡 {direction} {pair} [{tf}] @ {price:.5f}  SL:{sl_pts}{unit}")

# ═══════════════════════════════════════════
# FETCH
# ═══════════════════════════════════════════
def fetch_binance(sym, iv, lim=200):
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol":sym,"interval":iv,"limit":lim},
            timeout=20).json()
        if not isinstance(r, list): return []
        return [{"time":x[0]/1000,"open":float(x[1]),"high":float(x[2]),
                 "low":float(x[3]),"close":float(x[4]),"volume":float(x[5])}
                for x in r]
    except: return []

def fetch_twelve(sym, iv, lim=200):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={"symbol":sym,"interval":iv,"outputsize":lim,
                    "apikey":TWELVE_KEY,"format":"JSON","order":"ASC"},
            timeout=30).json()
        if r.get("status") != "ok": return []
        candles = []
        for v in r.get("values",[]):
            ds = v["datetime"]
            if len(ds)==10: ds += " 00:00:00"
            try:
                ts = int(datetime.strptime(ds,"%Y-%m-%d %H:%M:%S")
                         .replace(tzinfo=timezone.utc).timestamp())
                candles.append({
                    "time":ts, "open":float(v["open"]),
                    "high":float(v["high"]), "low":float(v["low"]),
                    "close":float(v["close"]),
                    "volume":float(v.get("volume") or 0)})
            except: pass
        return candles
    except: return []

# ═══════════════════════════════════════════
# INDICATORS — Pine Script Logic
# ═══════════════════════════════════════════
def sma(v, p):
    return sum(v[-p:])/p if len(v)>=p else (sum(v)/len(v) if v else 0)

def ema_series(v, p):
    if not v: return []
    k = 2/(p+1); r = [v[0]]
    for x in v[1:]: r.append(x*k + r[-1]*(1-k))
    return r

def in_sess(ts):
    """London 08:00-16:30 UTC | NY 13:30-20:00 UTC"""
    m = datetime.fromtimestamp(ts,tz=timezone.utc).hour*60 + \
        datetime.fromtimestamp(ts,tz=timezone.utc).minute
    return 8*60 <= m < 16*60+30 or 13*60+30 <= m < 20*60

def sess_name(ts):
    m = datetime.fromtimestamp(ts,tz=timezone.utc).hour*60 + \
        datetime.fromtimestamp(ts,tz=timezone.utc).minute
    l = 8*60 <= m < 16*60+30
    n = 13*60+30 <= m < 20*60
    return "London+NY" if l and n else ("London" if l else ("NY" if n else "Other"))

# ═══════════════════════════════════════════
# SIGNAL ENGINE
# ═══════════════════════════════════════════
def check_signal(candles, pair, tf_label):
    """
    Pine Script Logic حرفي:
    L_sig = (crossover OR low_sq)  AND volume>1.5×SMA AND close > EMA50
    S_sig = (crossunder OR high_sq) AND volume>1.5×SMA AND close < EMA50
    """
    if len(candles) < 55: return None

    LOOK   = 20
    closes = [c["close"] for c in candles]
    ema50  = ema_series(closes, 50)

    i  = len(candles)-1
    c  = candles[i]
    ts = c["time"]

    # جلسة + عطلة
    if not in_sess(ts): return None
    if datetime.fromtimestamp(ts,tz=timezone.utc).weekday() >= 5: return None

    # المؤشرات
    ph   = [candles[j]["high"]   for j in range(i-LOOK, i)]
    pl   = [candles[j]["low"]    for j in range(i-LOOK, i)]
    pvol = [candles[j]["volume"] for j in range(i-LOOK, i)]
    if not ph: return None

    h20   = max(ph)
    l20   = min(pl)
    avg_v = sma(pvol, LOOK)
    hi_v  = c["volume"] > avg_v*1.5 if avg_v > 0 else False
    ef    = ema50[i]
    pc    = candles[i-1]["close"]

    # Pine Script conditions
    low_sq  = c["low"]  < l20 and c["close"] > l20
    high_sq = c["high"] > h20 and c["close"] < h20
    cup     = pc <= h20 and c["close"] > h20
    cdn     = pc >= l20 and c["close"] < l20

    L_sig = (cup  or low_sq)  and hi_v and c["close"] > ef
    S_sig = (cdn  or high_sq) and hi_v and c["close"] < ef

    if not L_sig and not S_sig: return None

    direction = "L" if L_sig else "S"

    # SL/TP حسب الزوج والفريم
    sl_pts, tp_pts = get_sl_tp(pair, tf_label)
    price = c["close"]

    if direction == "L":
        sl = price - sl_pts
        tp = price + tp_pts
    else:
        sl = price + sl_pts
        tp = price - tp_pts

    reason = ""
    if direction == "L":
        reason = "Sweep↑ (Low Sweep)"  if low_sq  else "Breakout↑ (High Break)"
    else:
        reason = "Sweep↓ (High Sweep)" if high_sq else "Breakout↓ (Low Break)"

    return {
        "direction": direction,
        "price":     price,
        "sl":        sl,
        "tp":        tp,
        "sl_pts":    sl_pts,
        "reason":    reason,
        "sess":      sess_name(ts),
    }

# ═══════════════════════════════════════════
# DATA CACHE — تحديث كل ساعة
# ═══════════════════════════════════════════
_cache    = {}
_last_f   = {}
CACHE_TTL = 3600

def get_candles(pair, tf_info):
    cfg = PAIRS[pair]
    key = f"{pair}_{tf_info['label']}"
    now = time.time()

    if now - _last_f.get(key, 0) < CACHE_TTL:
        return _cache.get(key, [])

    if cfg["src"] == "binance":
        c = fetch_binance(cfg["sym"], tf_info["binance"], tf_info["limit"])
    else:
        c = fetch_twelve(cfg["sym"], tf_info["twelve"], tf_info["limit"])
        time.sleep(8)  # Twelve Data rate limit

    if c:
        _cache[key]  = c
        _last_f[key] = now
    return _cache.get(key, [])

# ═══════════════════════════════════════════
# COOLDOWN — إشارة واحدة لكل زوج/فريم كل 4 ساعات
# ═══════════════════════════════════════════
_last_sig = {}
COOLDOWN  = 4 * 3600

def is_cooled(pair, tf):
    return time.time() - _last_sig.get(f"{pair}_{tf}", 0) >= COOLDOWN

def mark_signal(pair, tf):
    _last_sig[f"{pair}_{tf}"] = time.time()

# ═══════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════
def main():
    print("╔"+"═"*56+"╗")
    print("║"+" AI-X ELITE PRO v2 — LIVE ".center(56)+"║")
    print("║"+" 6 أزواج × 5 فريمات — SL/TP محسوب ".center(56)+"║")
    print("╚"+"═"*56+"╝")

    print(f"\n  SL بالنقاط:")
    print(f"  {'زوج':<10} {'1m':>6} {'5m':>6} {'15m':>6} {'1H':>6} {'4H':>6}")
    print(f"  {'─'*42}")
    for pair, vals in SL_POINTS.items():
        unit = "pip" if pair in ["GBP/USD","EUR/USD"] else ("$" if pair=="QQQ" else "pt")
        print(f"  {pair:<10} {vals[0]:>5}{unit} {vals[1]:>5}{unit} {vals[2]:>5}{unit} {vals[3]:>5}{unit} {vals[4]:>5}{unit}")

    # HTTP Health Server
    threading.Thread(target=run_health, daemon=True).start()
    print(f"\n  🌐 Health server PORT {os.environ.get('PORT',8080)}")

    # منع spam عند restart
    time.sleep(15)
    skip_start = False
    try:
        with open("/tmp/aix_ls.txt") as f:
            if time.time() - float(f.read().strip()) < 300:
                skip_start = True
                print("  ⏭️ restart سريع — تخطي رسالة البداية")
    except: pass
    try:
        with open("/tmp/aix_ls.txt","w") as f: f.write(str(time.time()))
    except: pass

    if not skip_start:
        now_str = datetime.now(tz=timezone.utc).strftime("%H:%M UTC")
        tg(
            f"🚀 <b>AI-X ELITE PRO v2 شغّال!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 BTC · ETH · GBP · EUR · XAU · QQQ\n"
            f"⏱️ 1m · 5m · 15m · 1H · 4H\n"
            f"🎯 SL/TP محسوب لكل زوج × فريم\n"
            f"📍 London + NY Sessions فقط\n"
            f"⏰ بدأ: {now_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>AI-X ELITE PRO — Pine Script Logic</i>"
        )
    elif skip_start:
        time.sleep(CHECK_INTERVAL)

    scan_count   = 0
    signal_today = 0
    daily_sent   = set()

    # استرجاع آخر تقرير
    try:
        with open("/tmp/aix_report.txt") as f:
            daily_sent.add(f.read().strip())
    except: pass

    while True:
        now_utc    = datetime.now(tz=timezone.utc)
        scan_count += 1
        sess_now   = sess_name(time.time())

        print(f"\n{'─'*52}")
        print(f"  🔍 #{scan_count} — {now_utc.strftime('%H:%M UTC')} | {sess_now}")

        # عطلة
        if now_utc.weekday() >= 5:
            print("  💤 عطلة نهاية الأسبوع")
            time.sleep(CHECK_INTERVAL)
            continue

        signals_found = 0

        for pair in PAIRS:
            for tf_info in TIMEFRAMES:
                tf = tf_info["label"]

                if not is_cooled(pair, tf):
                    continue

                candles = get_candles(pair, tf_info)
                if len(candles) < 55:
                    continue

                sig = check_signal(candles, pair, tf)

                if sig:
                    signals_found += 1
                    signal_today  += 1
                    mark_signal(pair, tf)
                    tg_signal(
                        pair, tf,
                        sig["direction"],
                        sig["price"],
                        sig["sl"],
                        sig["tp"],
                        sig["sl_pts"],
                        sig["reason"],
                        sig["sess"],
                    )
                else:
                    print(f"  — {pair:<8} [{tf}]: لا إشارة")

        if signals_found == 0:
            print(f"  ✓ لا إشارات | إجمالي: {SIGNAL_COUNTER[0]}")

        # تقرير يومي 21:00 UTC
        today_str  = now_utc.strftime('%Y-%m-%d')
        bot_uptime = time.time() - START_TIME
        if now_utc.hour == 21 and today_str not in daily_sent and bot_uptime > 300:
            daily_sent.add(today_str)
            try:
                with open("/tmp/aix_report.txt","w") as f: f.write(today_str)
            except: pass
            tg(
                f"📊 <b>تقرير يومي — {today_str}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔍 فحوصات: {scan_count}\n"
                f"📡 إشارات اليوم: {signal_today}\n"
                f"📡 إجمالي: {SIGNAL_COUNTER[0]}\n"
                f"⏰ 21:00 UTC"
            )
            signal_today = 0

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
