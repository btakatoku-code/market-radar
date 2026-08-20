# -*- coding: utf-8 -*-
"""無料データソース。APIキー不要。

- Yahoo Finance : 株 / ETF / 貴金属先物 / FX / 指数
- Binance       : 暗号資産（日足・時間足）
- alternative.me: 暗号資産 Fear & Greed 指数
"""
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".cache")
CACHE_TTL = 60 * 60 * 6   # 6時間


def _get(url, timeout=20, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise                       # 銘柄が存在しない: 再試行しない
            time.sleep(1.5 * (attempt + 1))
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def _cache_path(key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
    return os.path.join(CACHE_DIR, safe + ".json")


def _cached(key, fn, use_cache=True):
    path = _cache_path(key)
    if use_cache and os.path.exists(path):
        if time.time() - os.path.getmtime(path) < CACHE_TTL:
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    data = fn()
    if data is not None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass
    return data


def fetch_yahoo(symbol, rng="10y", interval="1d", use_cache=True):
    """Yahoo Finance から OHLCV を取得。株式分割は明示的に遡及調整する。

    Yahoo の close / adjclose は日本株の分割が反映されていない場合があるため、
    events=split で返る分割履歴を使って自前で遡及調整する。
    """
    def _do():
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               f"?range={rng}&interval={interval}&includePrePost=false&events=div,split")
        try:
            d = _get(url)
        except Exception:
            return None
        try:
            res = d["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            ts = res["timestamp"]
            bars = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
            for i in range(len(ts)):
                o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                if o is None or h is None or l is None or c is None or c <= 0:
                    continue            # 欠損足はスキップ
                v = q.get("volume", [None] * len(ts))[i] or 0
                bars["t"].append(ts[i])
                bars["o"].append(float(o)); bars["h"].append(float(h))
                bars["l"].append(float(l)); bars["c"].append(float(c))
                bars["v"].append(float(v))
            if len(bars["c"]) < 30:
                return None
            splits = []
            for ev in (res.get("events", {}).get("splits", {}) or {}).values():
                try:
                    num = float(ev.get("numerator"))
                    den = float(ev.get("denominator"))
                    if num > 0 and den > 0:
                        splits.append((int(ev["date"]), num / den))
                except Exception:
                    continue
            bars["splits"] = sorted(splits)
            divs = []
            for ev in (res.get("events", {}).get("dividends", {}) or {}).values():
                try:
                    divs.append((int(ev["date"]), float(ev["amount"])))
                except Exception:
                    continue
            bars["dividends"] = sorted(divs)
            bars["currency"] = res["meta"].get("currency")
            bars["source"] = "yahoo"
            return bars
        except Exception:
            return None
    return _cached(f"yh_{symbol}_{rng}_{interval}_v3", _do, use_cache)


def fetch_binance(symbol, interval="1d", limit=3000, use_cache=True):
    """Binance の公開APIからローソク足を取得。

    1リクエスト1000本が上限なので、必要本数に達するまで遡ってつなぐ。
    """
    def _do():
        bars = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
        end = None
        seen = set()
        while len(bars["c"]) < limit:
            url = ("https://api.binance.com/api/v3/klines"
                   f"?symbol={symbol}&interval={interval}&limit=1000")
            if end is not None:
                url += f"&endTime={end}"
            try:
                rows = _get(url)
            except Exception:
                break
            if not rows:
                break
            chunk = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
            for r in rows:
                ts = int(r[0])
                if ts in seen:
                    continue
                seen.add(ts)
                chunk["t"].append(ts // 1000)
                chunk["o"].append(float(r[1])); chunk["h"].append(float(r[2]))
                chunk["l"].append(float(r[3])); chunk["c"].append(float(r[4]))
                chunk["v"].append(float(r[5]))
            if not chunk["t"]:
                break
            for k in ("t", "o", "h", "l", "c", "v"):
                bars[k] = chunk[k] + bars[k]
            end = int(rows[0][0]) - 1
            if len(rows) < 1000:
                break
        if len(bars["c"]) < 30:
            return None
        bars["currency"] = "USD"
        bars["source"] = "binance"
        return bars
    return _cached(f"bn_{symbol}_{interval}_{limit}", _do, use_cache)


def fetch_fear_greed(use_cache=True):
    """暗号資産の Fear & Greed 指数（0=極度の恐怖, 100=極度の強欲）"""
    def _do():
        try:
            d = _get("https://api.alternative.me/fng/?limit=30")
            return [{"value": int(x["value"]), "label": x["value_classification"],
                     "t": int(x["timestamp"])} for x in d["data"]]
        except Exception:
            return None
    return _cached("fng", _do, use_cache)


def fetch_many(specs, workers=6, use_cache=True, progress=True):
    """複数銘柄を並列取得。

    specs: [(key, kind, symbol)]  kind は "yahoo" か "binance"
    戻り値: {key: bars または None}
    """
    out, done = {}, [0]
    total = len(specs)

    def one(spec):
        key, kind, sym = spec
        bars = (fetch_binance(sym, use_cache=use_cache) if kind == "binance"
                else fetch_yahoo(sym, use_cache=use_cache))
        done[0] += 1
        if progress and done[0] % 25 == 0:
            print(f"    取得 {done[0]}/{total}", flush=True)
        return key, bars

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for key, bars in ex.map(one, specs):
            out[key] = bars
    return out
