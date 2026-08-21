# -*- coding: utf-8 -*-
"""CFTC 建玉報告（COT）— 通貨先物の投機筋ポジション。

米商品先物取引委員会が毎週公表している公式データ。APIキー不要。
「毎週火曜時点の建玉を、その週の金曜に公表」という仕組みなので、
先読みを防ぐには公表日を守って使う必要がある。ここでは安全側に倒して、
報告日（火曜）から5日後（翌日曜）以降でないと参照できないようにしている。

テクニカル指標とは種類の違う情報（誰がどれだけ持っているか＝需給）なので
期待して測ったが、**効果は確認できず、アプリでは使っていない**。

主要5ペアでは逆張り条件が3期間そろって改善したものの（59.6/59.8/62.2%）、
条件作りに使っていない残り10ペアで測ると3つとも「条件なし」を下回った
（49.0/50.4/51.3% 対 54.3/54.7/52.6%）。8通り×5ペアを試して
良く見えたものを拾っていただけだった。

取得部分は正しく動くので、別の使い道が見つかったとき用に残してある。
検証は tests/run_cot.py と tests/run_cot2.py。
"""
import datetime
import urllib.parse

import sources

API = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# 通貨ごとの銘柄名。取引所の名称変更で複数の表記が存在するため候補を並べる。
MARKETS = {
    "JPY": ["JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE"],
    "EUR": ["EURO FX - CHICAGO MERCANTILE EXCHANGE"],
    "GBP": ["BRITISH POUND - CHICAGO MERCANTILE EXCHANGE",
            "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE"],
    "AUD": ["AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE"],
    "CAD": ["CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE"],
    "CHF": ["SWISS FRANC - CHICAGO MERCANTILE EXCHANGE"],
    "NZD": ["NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE",
            "NZ DOLLAR - CHICAGO MERCANTILE EXCHANGE"],
}

PUBLISH_LAG_DAYS = 5      # 火曜の状態 → 金曜公表。安全側に翌日曜まで待つ。
ZSCORE_WINDOW = 104       # 過去2年（週次）で偏りの大きさを測る


def _fetch_market(name):
    q = ("$select=report_date_as_yyyy_mm_dd,noncomm_positions_long_all,"
         "noncomm_positions_short_all,open_interest_all"
         "&$where=market_and_exchange_names='{}'"
         "&$order=report_date_as_yyyy_mm_dd ASC&$limit=5000").format(name.replace("'", "''"))
    url = API + "?" + urllib.parse.quote(q, safe="$=&',")
    return sources._get(url, timeout=45)


def series(currency, use_cache=True):
    """通貨1つ分の週次系列を返す。

    各要素: {"date": 報告日, "usable_from": 参照解禁日, "net_pct": 建玉比の買い越し}
    net_pct が正なら投機筋はその通貨を買い越している（＝対ドルで強気）。
    """
    rows = []
    for name in MARKETS.get(currency, []):
        key = "cot_{}_{}".format(currency, name[:18].replace(" ", ""))
        got = sources._cached(key, lambda n=name: _fetch_market(n), use_cache)
        if got:
            rows.extend(got)
    out = {}
    for r in rows:
        try:
            oi = float(r["open_interest_all"])
            if oi <= 0:
                continue
            d = datetime.date.fromisoformat(r["report_date_as_yyyy_mm_dd"][:10])
            net = (float(r["noncomm_positions_long_all"])
                   - float(r["noncomm_positions_short_all"])) / oi
        except (KeyError, TypeError, ValueError):
            continue
        out[d] = net                       # 名称違いの重複は後勝ちで1本化
    items = sorted(out.items())
    res = []
    for i, (d, net) in enumerate(items):
        hist = [v for _, v in items[max(0, i - ZSCORE_WINDOW):i]]
        z = None
        if len(hist) >= 52:
            m = sum(hist) / len(hist)
            var = sum((x - m) ** 2 for x in hist) / (len(hist) - 1)
            if var > 0:
                z = (net - m) / (var ** 0.5)
        res.append({
            "date": d,
            "usable_from": d + datetime.timedelta(days=PUBLISH_LAG_DAYS),
            "net_pct": net,
            "z": z,                                     # 過去2年に対する偏り
            "change": net - items[i - 1][1] if i else 0.0,   # 前週からの変化
        })
    return res


def load(currencies=None, use_cache=True):
    cur = currencies or list(MARKETS)
    return {c: series(c, use_cache) for c in cur}


def as_of(ser, on_date):
    """その日に参照してよい最新の1回を返す（公表前のものは使わない）。"""
    ok = [x for x in ser if x["usable_from"] <= on_date]
    return ok[-1] if ok else None
