import json
import os
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
OKX_BASE = os.environ.get("OKX_API_BASE", "https://www.okx.com")
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL_SECONDS", "300"))
WORKERS = int(os.environ.get("SCAN_WORKERS", "8"))
EMA_PERIODS = (20, 50, 200)

state_lock = threading.Lock()
scan_state = {
    "status": "starting", "started_at": None, "updated_at": None,
    "total": 0, "completed": 0, "error": None,
    "rows": {"1H": [], "4H": []}, "last_duration_seconds": None,
}


def okx_get(path, params=None, retries=3):
    query = urllib.parse.urlencode(params or {})
    url = f"{OKX_BASE}{path}" + (f"?{query}" if query else "")
    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OKX-EMA-Scanner/1.0"})
            with urllib.request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("code") != "0":
                raise RuntimeError(payload.get("msg") or f"OKX error code {payload.get('code')}")
            return payload.get("data", [])
        except Exception as exc:
            last_error = exc
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(str(last_error))


def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = alpha * value + (1 - alpha) * current
    return current


def analyze_candles(inst, bar):
    raw = okx_get("/api/v5/market/candles", {"instId": inst, "bar": bar, "limit": "300"})
    # OKX returns newest first. Use closed candles only to prevent flickering signals.
    candles = [r for r in raw if len(r) >= 9 and str(r[8]) == "1"]
    candles.sort(key=lambda r: int(r[0]))
    closes = []
    for candle in candles:
        try:
            closes.append(float(candle[4]))
        except (ValueError, TypeError):
            continue
    if len(closes) < 200:
        return None
    price = closes[-1]
    e20, e50, e200 = (ema(closes, p) for p in EMA_PERIODS)
    if not price or not all(v is not None for v in (e20, e50, e200)):
        return None
    max_ema, min_ema = max(e20, e50, e200), min(e20, e50, e200)
    cluster_pct = (max_ema - min_ema) / price * 100
    distance_pct = abs(e20 - e50) / price * 100

    # Compare recent closed-candle EMA20/EMA50 distances for convergence.
    recent = []
    for end in range(max(200, len(closes) - 4), len(closes) + 1):
        sub = closes[:end]
        a, b = ema(sub, 20), ema(sub, 50)
        if a is not None and b is not None:
            recent.append(abs(a - b) / sub[-1] * 100)
    shrinking = len(recent) >= 3 and recent[-1] < recent[-2] < recent[-3]
    crossed_up = e20 > e50
    # Use the previous candle to detect a fresh crossover on the latest closed candle.
    prev20, prev50 = ema(closes[:-1], 20), ema(closes[:-1], 50)
    crossed_now_up = prev20 is not None and prev50 is not None and prev20 <= prev50 and e20 > e50
    crossed_now_down = prev20 is not None and prev50 is not None and prev20 >= prev50 and e20 < e50
    if crossed_now_up:
        meeting = "已金叉"
        direction = "偏多"
    elif crossed_now_down:
        meeting = "已死叉"
        direction = "偏空"
    elif shrinking and e20 < e50:
        meeting = "可能金叉"
        direction = "偏多"
    elif shrinking and e20 > e50:
        meeting = "可能死叉"
        direction = "偏空"
    elif e20 < e50:
        meeting = "距離未持續縮小"
        direction = "偏空"
    elif e20 > e50:
        meeting = "距離未持續縮小"
        direction = "偏多"
    else:
        meeting = "均線重合"
        direction = "中性"

    # Transparent ranking score: closeness is the core; persistent convergence adds a modest bonus.
    cluster_score = max(0.0, min(100.0, 100 - cluster_pct * 20))
    meeting_score = max(0.0, min(100.0, 100 - distance_pct * 35 + (15 if shrinking else 0)))
    return {
        "symbol": inst.replace("-USDT-SWAP", "-USDT"), "instId": inst,
        "price": price, "ema20": e20, "ema50": e50, "ema200": e200,
        "cluster_pct": cluster_pct, "distance_pct": distance_pct,
        "cluster_score": cluster_score, "meeting_score": meeting_score,
        "shrinking": shrinking, "meeting": meeting, "direction": direction,
        "price_change_24h": None,
    }


def scan_one(inst):
    results = {}
    errors = []
    for label, bar in (("1H", "1H"), ("4H", "4H")):
        try:
            results[label] = analyze_candles(inst, bar)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            results[label] = None
    return inst, results, errors


def perform_scan():
    started = time.time()
    with state_lock:
        if scan_state["status"] == "scanning":
            return
        scan_state.update({"status": "scanning", "started_at": datetime.now(timezone.utc).isoformat(), "completed": 0, "error": None})
    try:
        instruments = okx_get("/api/v5/public/instruments", {"instType": "SWAP"})
        symbols = sorted({x.get("instId") for x in instruments if x.get("state") == "live" and x.get("instId", "").endswith("-USDT-SWAP") and x.get("settleCcy") == "USDT"})
        with state_lock:
            scan_state["total"] = len(symbols)
            scan_state["rows"] = {"1H": [], "4H": []}
        rows = {"1H": [], "4H": []}
        errors_count = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(scan_one, symbol) for symbol in symbols]
            for future in as_completed(futures):
                try:
                    _, result, errs = future.result()
                    errors_count += len(errs)
                    for timeframe in ("1H", "4H"):
                        if result.get(timeframe):
                            rows[timeframe].append(result[timeframe])
                except Exception:
                    errors_count += 1
                with state_lock:
                    scan_state["completed"] += 1
                    scan_state["rows"] = {k: sorted(v, key=lambda x: x["cluster_score"], reverse=True) for k, v in rows.items()}
        for timeframe in ("1H", "4H"):
            rows[timeframe].sort(key=lambda x: x["cluster_score"], reverse=True)
        # Cross-timeframe intersection: both periods have a tight EMA cluster or active convergence.
        one = {r["instId"]: r for r in rows["1H"]}
        four = {r["instId"]: r for r in rows["4H"]}
        resonance = []
        for symbol in one.keys() & four.keys():
            a, b = one[symbol], four[symbol]
            cluster_both = a["cluster_pct"] <= 1.0 and b["cluster_pct"] <= 1.0
            converging_both = a["shrinking"] and b["shrinking"]
            if cluster_both or converging_both:
                resonance.append({
                    "symbol": a["symbol"], "instId": symbol, "price": a["price"],
                    "score": round((a["cluster_score"] + b["cluster_score"]) / 2, 2),
                    "one_hour_cluster_pct": a["cluster_pct"], "four_hour_cluster_pct": b["cluster_pct"],
                    "one_hour_meeting": a["meeting"], "four_hour_meeting": b["meeting"],
                    "one_hour_direction": a["direction"], "four_hour_direction": b["direction"],
                    "same_direction": a["direction"] == b["direction"] and a["direction"] != "中性",
                })
        resonance.sort(key=lambda x: (x["same_direction"], x["score"]), reverse=True)
        with state_lock:
            scan_state.update({
                "status": "ready", "updated_at": datetime.now(timezone.utc).isoformat(),
                "rows": rows, "resonance": resonance,
                "last_duration_seconds": round(time.time() - started, 1),
                "error": f"部分資料讀取失敗：{errors_count} 次" if errors_count else None,
            })
    except Exception as exc:
        with state_lock:
            scan_state["status"] = "error"
            scan_state["error"] = str(exc)
            scan_state["last_duration_seconds"] = round(time.time() - started, 1)


def scan_loop():
    while True:
        perform_scan()
        time.sleep(max(60, SCAN_INTERVAL))


threading.Thread(target=scan_loop, daemon=True).start()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    with state_lock:
        return jsonify({k: v for k, v in scan_state.items() if k not in ("rows", "resonance")})


@app.route("/api/scan")
def api_scan():
    with state_lock:
        payload = dict(scan_state)
    timeframe = request.args.get("tf", "1H").upper()
    if timeframe not in ("1H", "4H"):
        timeframe = "1H"
    mode = request.args.get("mode", "cluster")
    rows = payload.get("rows", {}).get(timeframe, [])
    if mode == "meeting":
        rows = sorted(rows, key=lambda x: x["meeting_score"], reverse=True)
    elif mode == "converging":
        rows = [x for x in rows if x["shrinking"]]
        rows.sort(key=lambda x: x["meeting_score"], reverse=True)
    else:
        rows = sorted(rows, key=lambda x: x["cluster_score"], reverse=True)
    q = request.args.get("q", "").strip().upper()
    if q:
        rows = [x for x in rows if q in x["symbol"].upper()]
    with state_lock:
        meta = {k: v for k, v in scan_state.items() if k not in ("rows", "resonance")}
        resonance = payload.get("resonance", [])
    return jsonify({"meta": meta, "timeframe": timeframe, "mode": mode, "rows": rows, "resonance": resonance})


@app.route("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), debug=False)
