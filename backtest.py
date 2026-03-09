"""
BEAST TRADER — BACKTEST ENGINE
يجلب بيانات تاريخية ويحاكي البوت عليها
"""
import requests
import json
from datetime import datetime, timezone, timedelta

# ========== CONFIG ==========
BACKTEST_DAYS = 30       # عدد الأيام للاختبار
ATR_SL_MULT   = 2.0
ATR_TP1_MULT  = 2.0
ATR_TP2_MULT  = 4.0
MIN_SCORE     = 9

# ========== FETCH HISTORICAL DATA ==========
def fetch_binance_history(symbol, interval, limit=1000):
    url = f"https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        candles = []
        for d in data:
            candles.append({
                "time":   d[0] / 1000,
                "open":   float(d[1]),
                "high":   float(d[2]),
                "low":    float(d[3]),
                "close":  float(d[4]),
                "volume": float(d[5])
            })
        return candles
    except Exception as e:
        print(f"  [ERROR] {symbol} {interval}: {e}")
        return []


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

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i-1]["close"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs[-period:]) / period

def calc_adx(candles, period=14):
    if len(candles) < period * 2:
        return 0
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        h_diff = candles[i]["high"] - candles[i-1]["high"]
        l_diff = candles[i-1]["low"] - candles[i]["low"]
        plus_dm.append(h_diff if h_diff > l_diff and h_diff > 0 else 0)
        minus_dm.append(l_diff if l_diff > h_diff and l_diff > 0 else 0)
        h, l = candles[i]["high"], candles[i]["low"]
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

def find_fvg(candles):
    fvgs = []
    for i in range(2, len(candles)):
        if candles[i]["low"] > candles[i-2]["high"]:
            mid = (candles[i]["low"] + candles[i-2]["high"]) / 2
            fvgs.append({"type": "BULL", "mid": mid, "top": candles[i]["low"], "bot": candles[i-2]["high"]})
        elif candles[i]["high"] < candles[i-2]["low"]:
            mid = (candles[i]["high"] + candles[i-2]["low"]) / 2
            fvgs.append({"type": "BEAR", "mid": mid, "top": candles[i-2]["low"], "bot": candles[i]["high"]})
    return fvgs[-10:] if len(fvgs) > 10 else fvgs

def find_obs(candles):
    obs = []
    for i in range(1, len(candles)-1):
        body = abs(candles[i]["close"] - candles[i]["open"])
        prev_body = abs(candles[i-1]["close"] - candles[i-1]["open"])
        if body > prev_body * 1.5:
            mid = (candles[i]["high"] + candles[i]["low"]) / 2
            obs.append({"type": "BULL" if candles[i]["close"] > candles[i]["open"] else "BEAR", "mid": mid})
    return obs[-5:] if len(obs) > 5 else obs

def is_kill_zone(ts):
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    h = dt.hour
    return (7 <= h < 9) or (12 <= h < 14) or (20 <= h < 22)

def calc_score(candles_h4, candles_h1, candles_m15, price):
    score = 0
    ict_confirmed = False

    rsi = calc_rsi(candles_m15, 14)
    adx = calc_adx(candles_m15, 14)

    if rsi < 30 or rsi > 70:
        score += 2
    elif rsi < 40 or rsi > 60:
        score += 1

    if adx > 25:
        score += 2
    elif adx > 20:
        score += 1

    # ICT H4
    for fvg in find_fvg(candles_h4):
        if abs(fvg["mid"] - price) / price * 100 < 0.5:
            score += 3
            ict_confirmed = True
            break
    for ob in find_obs(candles_h4):
        if abs(ob["mid"] - price) / price * 100 < 0.5:
            score += 3
            ict_confirmed = True
            break

    # ICT H1
    for fvg in find_fvg(candles_h1):
        if abs(fvg["mid"] - price) / price * 100 < 0.3:
            score += 2
            ict_confirmed = True
            break
    for ob in find_obs(candles_h1):
        if abs(ob["mid"] - price) / price * 100 < 0.3:
            score += 2
            ict_confirmed = True
            break

    # ICT M15
    for fvg in find_fvg(candles_m15):
        if abs(fvg["mid"] - price) / price * 100 < 0.2:
            score += 1
            ict_confirmed = True
            break

    if not ict_confirmed:
        return 0

    return score

# ========== BACKTEST ENGINE ==========
def backtest_pair(name, candles_h4, candles_m15, min_candles=100):
    if len(candles_m15) < min_candles:
        print(f"  {name}: بيانات غير كافية ({len(candles_m15)} شمعة)")
        return []

    trades = []
    cooldown = {}
    COOLDOWN = 30 * 60  # 30 دقيقة

    print(f"  {name}: {len(candles_m15)} شمعة M15 | {len(candles_h4)} شمعة H4")

    for i in range(50, len(candles_m15) - 20):
        candle     = candles_m15[i]
        price      = candle["close"]
        ts         = candle["time"]

        # Cooldown
        if name in cooldown and ts - cooldown[name] < COOLDOWN:
            continue

        # اختصار H1 من M15 (كل 4 شموع M15 = 1 شمعة H1)
        h1_idx = i // 4
        candles_h1 = candles_m15[max(0, i-80):i:4]

        # H4 المناسبة
        h4_i = min(i // 16, len(candles_h4) - 1)
        ch4 = candles_h4[max(0, h4_i-50):h4_i]

        score = calc_score(ch4, candles_h1, candles_m15[max(0,i-50):i], price)

        if score < MIN_SCORE:
            continue

        atr = calc_atr(candles_m15[max(0,i-20):i])
        if not atr:
            continue

        rsi = calc_rsi(candles_m15[max(0,i-20):i])
        ema = sum(c["close"] for c in candles_m15[max(0,i-50):i][-50:]) / min(50, i)
        direction = "BUY" if price > ema else "SELL"

        sl  = atr * ATR_SL_MULT
        tp1 = atr * ATR_TP1_MULT
        tp2 = atr * ATR_TP2_MULT

        sl_price  = price - sl  if direction == "BUY" else price + sl
        tp1_price = price + tp1 if direction == "BUY" else price - tp1
        tp2_price = price + tp2 if direction == "BUY" else price - tp2

        # محاكاة النتيجة على الشموع التالية
        result = "OPEN"
        hit_tp1 = False
        for j in range(i+1, min(i+50, len(candles_m15))):
            future = candles_m15[j]
            if direction == "BUY":
                if future["low"] <= sl_price:
                    result = "LOSS"
                    break
                if future["high"] >= tp1_price:
                    hit_tp1 = True
                if hit_tp1 and future["high"] >= tp2_price:
                    result = "WIN"
                    break
            else:
                if future["high"] >= sl_price:
                    result = "LOSS"
                    break
                if future["low"] <= tp1_price:
                    hit_tp1 = True
                if hit_tp1 and future["low"] <= tp2_price:
                    result = "WIN"
                    break

        if result == "OPEN":
            continue

        kz = "🔥 KZ" if is_kill_zone(ts) else ""
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

        trades.append({
            "pair":      name,
            "time":      dt,
            "direction": direction,
            "price":     price,
            "score":     score,
            "result":    result,
            "kz":        bool(is_kill_zone(ts))
        })

        cooldown[name] = ts

    return trades

# ========== MAIN ==========
def run_backtest():
    print("=" * 60)
    print("  BEAST TRADER — BACKTEST ENGINE")
    print(f"  آخر {BACKTEST_DAYS} يوم | MIN_SCORE={MIN_SCORE}")
    print("=" * 60)

    pairs = [
        ("BTC/USD",  "BTCUSDT"),
        ("ETH/USD",  "ETHUSDT"),
    ]

    all_trades = []

    for name, symbol in pairs:
        print(f"\n📊 {name} — جلب البيانات...")
        m15 = fetch_binance_history(symbol, "15m", limit=1000)
        h4  = fetch_binance_history(symbol, "4h",  limit=200)
        if m15 and h4:
            trades = backtest_pair(name, h4, m15)
            all_trades.extend(trades)

    # Forex من Binance
    forex_pairs = [
        ("EUR/USD", "EURUSDT"),
        ("BNB/USD", "BNBUSDT"),
        ("SOL/USD", "SOLUSDT"),
    ]
    for name, symbol in forex_pairs:
        print(f"\n📊 {name} — جلب البيانات...")
        m15 = fetch_binance_history(symbol, "15m", limit=1000)
        h4  = fetch_binance_history(symbol, "4h",  limit=200)
        if m15 and h4:
            trades = backtest_pair(name, h4, m15)
            all_trades.extend(trades)

    if not all_trades:
        print("\n❌ لا توجد صفقات — تحقق من الاتصال")
        return

    # ========== النتائج ==========
    wins   = [t for t in all_trades if t["result"] == "WIN"]
    losses = [t for t in all_trades if t["result"] == "LOSS"]
    total  = len(all_trades)
    wr     = round(len(wins) / total * 100, 1) if total > 0 else 0

    print("\n" + "=" * 60)
    print("  📊 النتائج الكاملة")
    print("=" * 60)
    print(f"  إجمالي الصفقات : {total}")
    print(f"  ✅ فوز         : {len(wins)}")
    print(f"  ❌ خسارة       : {len(losses)}")
    print(f"  🎯 Win Rate    : {wr}%")

    # نتائج حسب الزوج
    print("\n  📈 حسب الزوج:")
    pairs_seen = set(t["pair"] for t in all_trades)
    for pair in sorted(pairs_seen):
        pt = [t for t in all_trades if t["pair"] == pair]
        pw = [t for t in pt if t["result"] == "WIN"]
        pwr = round(len(pw)/len(pt)*100, 1) if pt else 0
        print(f"    {pair:10} | {len(pt):3} صفقة | ✅{len(pw)} ❌{len(pt)-len(pw)} | WR: {pwr}%")

    # نتائج Kill Zone vs خارجها
    kz_trades  = [t for t in all_trades if t["kz"]]
    nkz_trades = [t for t in all_trades if not t["kz"]]
    kz_wr  = round(len([t for t in kz_trades  if t["result"]=="WIN"]) / len(kz_trades)  * 100, 1) if kz_trades  else 0
    nkz_wr = round(len([t for t in nkz_trades if t["result"]=="WIN"]) / len(nkz_trades) * 100, 1) if nkz_trades else 0

    print(f"\n  ⚡ داخل Kill Zone  : {len(kz_trades):3} صفقة | WR: {kz_wr}%")
    print(f"  🕐 خارج Kill Zone  : {len(nkz_trades):3} صفقة | WR: {nkz_wr}%")

    # حفظ النتائج
    with open("backtest_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "summary": {"total": total, "wins": len(wins), "losses": len(losses), "win_rate": wr},
            "trades": all_trades
        }, f, ensure_ascii=False, indent=2)

    print(f"\n  💾 النتائج محفوظة في: backtest_results.json")
    print("=" * 60)

if __name__ == "__main__":
    run_backtest()
