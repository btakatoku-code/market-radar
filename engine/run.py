# -*- coding: utf-8 -*-
"""本番の実行入口。

データ取得 → 分析 → 予測の記録と採点 → アプリが読むJSONの書き出し。
GitHub Actions から1日数回呼ばれる。

config.PINNED の銘柄だけは常時表示し、それ以外はスコア順のランキングで出す。
予測値はそのまま見せず、必ず売買コストを引いた値を併記する。
"""
import datetime
import json
import math
import os
import sys
import time

import accuracy
import analog
import config
import costs
import dataset
import events
import fx as fxmod
import market
import risk
import scoring
import sources
import track

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "public", "data")
JST = datetime.timezone(datetime.timedelta(hours=9))
CHART_BARS = 120


def _jst(ts):
    return datetime.datetime.fromtimestamp(ts, JST)


def _business_days_later(ts, n):
    d = _jst(ts)
    added = 0
    while added < n:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return int(d.timestamp())


def _label(kind):
    return {"us_stock": "米国株", "us_etf": "米国ETF", "jp_stock": "日本株",
            "jp_etf": "国内ETF", "jp_reit": "REIT", "metal": "貴金属",
            "crypto": "暗号資産", "fx": "FX", "index": "指数"}.get(kind, kind)


def _note(a):
    if a.get("note"):
        return a["note"]
    if a["kind"] in ("us_stock", "us_etf", "jp_stock", "jp_etf", "jp_reit"):
        return "PayPay証券で購入可"
    return ""


def _chart(a, n=CHART_BARS):
    bars, ind = a["bars"], a["ind"]
    c, t = bars["c"][-n:], bars["t"][-n:]
    r = 4 if (c and c[-1] < 10) else 2
    return {
        "t0": t[0] if t else None, "t1": t[-1] if t else None,
        "c": [round(x, r) for x in c],
        "sma20": [None if x is None else round(x, r) for x in ind["sma20"][-n:]],
        "sma50": [None if x is None else round(x, r) for x in ind["sma50"][-n:]],
    }


def _ind_chart(a, n=CHART_BARS):
    ind = a["ind"]

    def cut(key, r=4):
        return [None if v is None else round(v, r) for v in ind[key][-n:]]

    return {"macd": cut("macd"), "macd_signal": cut("macd_signal"),
            "macd_hist": cut("macd_hist"), "rsi": cut("rsi14", 1),
            "stoch_k": cut("stoch_k", 1), "bb_pctb": cut("bb_pctb", 3)}


def _write_json(name, obj):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return os.path.getsize(path)


class Ctx:
    """1回の実行で共通して使う情報をまとめて持ち回る。"""

    def __init__(self, acc, usdjpy_fc, usdjpy_rate, calendar, due_long):
        self.acc = acc
        self.usdjpy_fc = usdjpy_fc          # ドル円の1か月予測（円建て換算に使う）
        self.usdjpy = usdjpy_rate
        self.calendar = calendar
        self.due_long = due_long


def _pack(a, fc, comp, ctx, rank=None, extra_fc=None, chart_bars=CHART_BARS):
    hist = (ctx.acc or {}).get(a["key"])
    kind = a["kind"]
    gross = fc["expected_return"]

    # ---- 売買コスト ----
    cb = costs.breakdown(kind, ctx.usdjpy)
    net = costs.net_return(gross, kind, ctx.usdjpy)

    # ---- 為替の影響（米ドル建ての資産を円で持つ場合）----
    fx_effect = None
    gross_jpy = gross
    if kind in ("us_stock", "us_etf", "metal", "crypto") and ctx.usdjpy_fc:
        fx_effect = ctx.usdjpy_fc["expected_return"]
        gross_jpy = (1 + gross) * (1 + fx_effect) - 1
    net_jpy = costs.net_return(gross_jpy, kind, ctx.usdjpy)

    item = {
        "key": a["key"], "code": a.get("code", a["key"]), "name": a["name"],
        "kind": kind, "kind_label": _label(kind), "note": _note(a),
        "price": round(a["price"], 4), "currency": a.get("currency"),
        "expected_return": gross,
        "expected_return_jpy": gross_jpy,
        "expected_net": net,
        "expected_net_jpy": net_jpy,
        "fx_effect": fx_effect,
        "cost": cb,
        "breakeven": cb["round_trip"],
        "hold_months": costs.hold_months_to_justify(gross, kind, ctx.usdjpy),
        "prob_up": fc["prob_up"], "low": fc["low"], "high": fc["high"],
        "samples": fc["n"], "n_eff": fc["n_eff"], "horizon": fc["horizon"],
        "rsi": round(comp["rsi"], 1), "adx": round(comp["adx"], 1),
        "trend": round(comp["trend"], 3), "momentum": round(comp["momentum"], 3),
        "rel": round(comp["rel"], 3), "volume_score": round(comp["volume"], 3),
        "macd_hist": round(comp["macd"], 3),
        "daily_vol": fc.get("daily_vol"),
        "annual_vol": (fc.get("daily_vol") or 0) * math.sqrt(252),
        "score": round(scoring.total_score(comp, fc), 3),
        "rank": rank,
        "hit_rate": hist["hit_rate"] if hist else None,
        "hit_n": hist["n"] if hist else None,
        "hit_gain": hist["mean_gain"] if hist else None,
        "chart": _chart(a, chart_bars),
    }

    # ---- 下方リスク ----
    item["risk"] = risk.profile(a["bars"], fc, config.HORIZON_LONG)

    # ---- 損切りとポジションサイズ ----
    atr = comp["atr"]
    if atr and a["price"]:
        stop = a["price"] - atr * config.STOCK_STOP_ATR_MULT
        sz = risk.position_size(config.STOCK_CAPITAL_JPY,
                                config.STOCK_RISK_PER_TRADE, a["price"], stop)
        item["stop"] = round(stop, 4)
        item["stop_pct"] = (a["price"] - stop) / a["price"]
        item["sizing"] = sz

    # ---- 複数期間 ----
    if extra_fc:
        item["horizons"] = [
            {"days": h, "label": config.HORIZON_LABELS.get(h, "{}営業日".format(h)),
             "expected_return": f["expected_return"],
             "expected_net": costs.net_return(f["expected_return"], kind, ctx.usdjpy),
             "prob_up": f["prob_up"]}
            for h, f in sorted(extra_fc.items())
        ]

    # ---- 決算・配当 ----
    events.annotate(item, a, ctx.calendar, ctx.due_long)
    return item


def _reasons(item):
    out = []
    if item["trend"] > 0.3:
        out.append("上昇トレンドが続いている")
    elif item["trend"] < -0.3:
        out.append("下降トレンドの中にある")
    if item["momentum"] > 0.25:
        out.append("勢いが強まっている")
    if item["rel"] > 0.3:
        out.append("市場平均より強い")
    if item["adx"] >= 25:
        out.append("方向感がはっきりしている")
    if item["rsi"] > 75:
        out.append("買われすぎの水準（反落に注意）")
    elif item["rsi"] < 30:
        out.append("売られすぎの水準")
    if item["volume_score"] > 0.3:
        out.append("出来高が伴っている")
    if item["hit_rate"] is not None and item["hit_n"] and item["hit_n"] >= 40:
        if item["hit_rate"] >= 0.55:
            out.append("この銘柄は過去の的中率が高い")
        elif item["hit_rate"] < 0.45:
            out.append("この銘柄は過去の的中率が低い")
    if item.get("dividend_yield"):
        out.append("配当利回り{:.1f}%".format(item["dividend_yield"] * 100))
    if not out:
        out.append("過去の類似局面が上昇に偏っている")
    return out


def _warnings(item):
    """買う前に知っておくべきことを短く出す"""
    w = []
    rt = item["cost"]["round_trip"]
    if rt and item["expected_net"] is not None:
        if item["expected_net"] <= 0:
            w.append("往復コスト{:.2f}%を引くと期待値がマイナスです".format(rt * 100))
        elif item["expected_net"] < item["expected_return"] * 0.4:
            w.append("期待値の6割以上が往復コストで消えます")
    if item.get("fx_effect") is not None and item["fx_effect"] < -0.005:
        w.append("ドル円が{:.2f}%下がる予測のため、円建てでは目減りします".format(
            item["fx_effect"] * 100))
    if item.get("earnings_in_horizon"):
        w.append("予測期間内に決算があります（{}）。テクニカルでは読めない変動が起きます".format(
            item["earnings_date"]))
    r = item.get("risk") or {}
    if r.get("worst_hold") is not None and r["worst_hold"] < -0.25:
        w.append("過去3年で同じ期間を保有した最悪値は{:.0f}%です".format(
            r["worst_hold"] * 100))
    if not item["cost"]["tradable"]:
        w.append("PayPay証券では購入できません（情報表示のみ）")
    return w


def build(use_cache=False, verbose=True):
    t0 = time.time()
    if verbose:
        print("1) データ取得")
    assets = dataset.load_all(use_cache=use_cache, progress=verbose)
    by_key = dataset.by_key(assets)
    now = int(time.time())
    due_long = _business_days_later(now, config.HORIZON_LONG)
    due_fx = _business_days_later(now, config.HORIZON_FX)

    if verbose:
        print("2) 銘柄別の的中率")
    acc_data = accuracy.ensure(assets, verbose=verbose)
    acc = (acc_data or {}).get("assets", {})

    if verbose:
        print("3) 決算カレンダー")
    calendar = events.earnings_calendar(days=40, use_cache=use_cache)
    if verbose:
        print("   {} 銘柄の決算予定を取得".format(len(calendar)))

    if verbose:
        print("4) 長期枠の分析")
    universe = [a for a in assets
                if a["kind"] not in ("index", "fx") and not a["leveraged"]
                and a["bars_count"] >= config.MIN_BARS]
    fx_assets = [a for a in assets if a["kind"] == "fx"
                 and a["bars_count"] >= config.MIN_BARS]

    pools = {config.HORIZON_LONG: analog.build_pool(universe, config.HORIZON_LONG)}
    for h in config.HORIZONS_EXTRA:
        pools[h] = analog.build_pool(universe, h)
    pool_long = pools[config.HORIZON_LONG]

    # ドル円の1か月予測（米ドル建て資産の円換算に使う）
    usdjpy = by_key.get("USDJPY=X")
    usdjpy_rate = usdjpy["price"] if usdjpy else None
    usdjpy_fc = None
    if usdjpy:
        pool_fx_long = analog.build_pool(fx_assets, config.HORIZON_LONG)
        usdjpy_fc = analog.forecast(usdjpy["bars"], usdjpy["ind"], usdjpy["feats"],
                                    pool_fx_long, config.HORIZON_LONG, use_knn=True,
                                    regime=usdjpy.get("regime"))

    ctx = Ctx(acc, usdjpy_fc, usdjpy_rate, calendar, due_long)

    scored = []
    for a in universe:
        fc = analog.forecast(a["bars"], a["ind"], a["feats"], pool_long,
                             config.HORIZON_LONG, use_knn=False, regime=a.get("regime"))
        if fc is None:
            continue
        br = scoring.bench_roc20(by_key, a["kind"])
        comp = scoring.components(a, len(a["bars"]["c"]) - 1, br)
        if comp is None:
            continue
        scored.append((a, fc, comp))
    scored.sort(key=lambda x: -scoring.total_score(x[2], x[1]))

    def investable(a, fc, comp):
        if a["kind"] in ("us_stock", "us_etf", "jp_stock", "jp_etf", "jp_reit"):
            if a["adv"] < config.MIN_DOLLAR_VOLUME:
                return False
            if comp["daily_vol"] * math.sqrt(252) > config.MAX_ANNUAL_VOL:
                return False
        if fc["expected_return"] <= config.MIN_EXPECTED_RETURN:
            return False
        if fc["prob_up"] < config.MIN_PROB_UP:
            return False
        return True

    def refine(items, limit):
        out = []
        for a, fc, comp in items[:limit]:
            fc2 = analog.forecast(a["bars"], a["ind"], a["feats"], pool_long,
                                  config.HORIZON_LONG, use_knn=True,
                                  regime=a.get("regime")) or fc
            out.append((a, fc2, comp))
        out.sort(key=lambda x: -scoring.total_score(x[2], x[1]))
        return out

    def extras(a):
        out = {}
        for h in config.HORIZONS_EXTRA:
            f = analog.forecast(a["bars"], a["ind"], a["feats"], pools[h], h,
                                use_knn=False, regime=a.get("regime"))
            if f:
                out[h] = f
        return out

    def make(a, fc, comp, rank=None, chart_bars=CHART_BARS):
        it = _pack(a, fc, comp, ctx, rank=rank, extra_fc=extras(a),
                   chart_bars=chart_bars)
        it["reasons"] = _reasons(it)
        it["warnings"] = _warnings(it)
        return it

    # ---- 総合の上位候補（値動きが重複しないように選ぶ）----
    buyable = [x for x in scored
               if x[0]["kind"] in ("us_stock", "us_etf", "jp_stock", "jp_etf", "jp_reit")
               and investable(*x)]
    refined = [x for x in refine(buyable, 60) if investable(*x)]
    picked, skipped = risk.diversify(refined, config.TOP_N,
                                     config.CORR_LIMIT, key=lambda x: x[0])
    top5 = [make(a, fc, comp, rank=i + 1) for i, (a, fc, comp) in enumerate(picked)]
    diversification = risk.concentration_warning(top5, [x[0] for x in picked])
    if diversification is not None:
        diversification["excluded"] = [
            {"name": c[0]["name"], "similar_to": w["name"], "corr": round(v, 2)}
            for c, w, v in skipped[:5]]

    # ---- 常時表示 ----
    by_code = {}
    for a, fc, comp in scored:
        by_code.setdefault(a.get("code", a["key"]), (a, fc, comp))
        by_code.setdefault(a["key"], (a, fc, comp))
    pinned = []
    for code in config.PINNED:
        hit = by_code.get(code)
        if not hit:
            continue
        a, fc, comp = hit
        fc = analog.forecast(a["bars"], a["ind"], a["feats"], pool_long,
                             config.HORIZON_LONG, use_knn=True,
                             regime=a.get("regime")) or fc
        it = make(a, fc, comp, rank=len(pinned) + 1)
        it["pinned"] = True
        pinned.append(it)

    # ---- カテゴリ別ランキング ----
    categories = []
    for kind, label, count in config.CATEGORIES:
        pool = [x for x in scored if x[0]["kind"] == kind]
        if kind in ("us_stock", "jp_stock", "us_etf", "jp_etf"):
            pool = [x for x in pool if x[0]["adv"] >= config.MIN_DOLLAR_VOLUME]
        items = [make(a, fc, comp, rank=i + 1, chart_bars=90)
                 for i, (a, fc, comp) in enumerate(refine(pool, count + 4)[:count])]
        if items:
            categories.append({"kind": kind, "label": label, "items": items})

    # ---- FX ----
    if verbose:
        print("5) FXの分析")
    pool_fx = analog.build_pool(fx_assets, config.HORIZON_FX)
    fx_signals = fxmod.signals(fx_assets, pool_fx)
    fx_plan = fxmod.plan()
    fx_plan["lines"] = fxmod.summary_lines(fx_plan)
    fx_by_key = {a["key"]: a for a in fx_assets}
    for s in fx_signals:
        notional, margin, lev, ok = fxmod.position_size(
            config.FX_CAPITAL_JPY, config.FX_RISK_PER_TRADE, s["stop_pct"], s["price"])
        hist = acc.get(s["key"])
        a = fx_by_key.get(s["key"])
        s.update(notional=notional, margin=margin, leverage=lev, leverage_ok=ok,
                 risk_jpy=config.FX_CAPITAL_JPY * config.FX_RISK_PER_TRADE,
                 hit_rate=hist["hit_rate"] if hist else None,
                 hit_n=hist["n"] if hist else None,
                 hit_gain=hist["mean_gain"] if hist else None,
                 chart=_chart(a) if a else None,
                 ind_chart=_ind_chart(a) if a else None)
        s["reward_jpy"] = s["risk_jpy"] * s["risk_reward"]
        # スプレッドを引いた実質の期待変動
        s["expected_net"] = abs(s["expected_move"]) - s["spread_pct"] * 2

    # ---- 市場環境 ----
    context = []
    for sym, name in list(config.MARKET_CONTEXT) + list(config.REGIME_SYMBOLS):
        a = by_key.get(sym)
        if not a:
            continue
        c, ind = a["bars"]["c"], a["ind"]
        context.append({
            "key": sym, "name": name, "price": round(c[-1], 4),
            "change": (c[-1] / c[-2] - 1) if len(c) > 1 else 0.0,
            "change5": (c[-1] / c[-6] - 1) if len(c) > 5 else 0.0,
            "rsi": round(ind["rsi14"][-1], 1) if ind["rsi14"][-1] else None,
            "above_sma50": bool(ind["sma50"][-1] and c[-1] > ind["sma50"][-1]),
            "above_sma200": bool(ind["sma200"][-1] and c[-1] > ind["sma200"][-1]),
            "chart": _chart(a, 90),
        })

    regime = market.build(assets, config.REGIME_MODE_FX)
    snap = market.snapshot(assets, regime)
    fng = sources.fetch_fear_greed(use_cache=use_cache)

    # ---- 予測の記録と採点 ----
    if verbose:
        print("6) 予測の記録と採点")
    preds = track.load_predictions()
    n_scored = track.score(preds, by_key, now)
    today = _jst(now).strftime("%Y-%m-%d")
    rec = []

    def add(items, bucket, due, horizon):
        for it in items:
            rec.append(dict(date=today, ts=now, key=it["key"], name=it["name"],
                            bucket=bucket, horizon=horizon, price=it["price"],
                            pred=it.get("expected_return", it.get("expected_move")),
                            prob=it.get("prob_up", it.get("confidence")),
                            rank=it.get("rank"), due=due, actual=None))

    add(top5, "top5", due_long, config.HORIZON_LONG)
    add(pinned, "pinned", due_long, config.HORIZON_LONG)
    for cat in categories:
        add(cat["items"][:3], "category", due_long, config.HORIZON_LONG)
    add([s for s in fx_signals if s["tradeable"]], "fx", due_fx, config.HORIZON_FX)
    add([s for s in fx_signals if not s["tradeable"]], "fx_watch", due_fx, config.HORIZON_FX)

    n_added = track.append_predictions(rec)
    preds = track.load_predictions()
    track.score(preds, by_key, now)
    track.rewrite(preds)
    acc_live = track.summary(preds)
    if verbose:
        print("   採点 {} 件 / 新規記録 {} 件 / 累計 {} 件".format(
            n_scored, n_added, len(preds)))

    # 保有ポジションの照合に使う索引。件数が多く本体を重くするので別ファイルにし、
    # 保有タブを開いたときだけ読み込ませる。キー名も短くして容量を抑える。
    directory = []
    for a, fc, comp in scored:
        g = fc["expected_return"]
        jpy = ((1 + g) * (1 + usdjpy_fc["expected_return"]) - 1
               if (usdjpy_fc and a["kind"] in ("us_stock", "us_etf", "metal", "crypto"))
               else g)
        directory.append({
            "c": a.get("code", a["key"]), "n": a["name"],
            "l": _label(a["kind"]),
            "p": round(a["price"], 4), "u": a.get("currency"),
            "e": round(costs.net_return(g, a["kind"], usdjpy_rate), 5),
            "j": round(costs.net_return(jpy, a["kind"], usdjpy_rate), 5),
            "b": round(fc["prob_up"], 3),
            "h": (acc.get(a["key"]) or {}).get("hit_rate"),
        })
    directory.sort(key=lambda x: x["n"])
    _write_json("directory.json", {"generated_at": _jst(now).isoformat(),
                                   "items": directory})

    generated = _jst(now)
    return {
        "directory_count": len(directory),
        "generated_at": generated.isoformat(),
        "generated_label": generated.strftime("%Y年%m月%d日 %H:%M"),
        "next_update": "毎日 7:00 / 12:00 / 22:00（日本時間）",
        "top5": top5, "pinned": pinned, "categories": categories,
        "diversification": diversification,
        "fx": {"signals": fx_signals, "plan": fx_plan},
        "context": context, "regime": snap,
        "fear_greed": fng[0] if fng else None,
        "accuracy": acc_live,
        "baseline_long": (acc_data or {}).get("baseline_long"),
        "baseline_fx": (acc_data or {}).get("baseline_fx"),
        "asset_accuracy_built": (acc_data or {}).get("built_at"),
        "asset_accuracy_n": len(acc),
        "usdjpy": {"rate": usdjpy_rate,
                   "expected_return": usdjpy_fc["expected_return"] if usdjpy_fc else None,
                   "prob_up": usdjpy_fc["prob_up"] if usdjpy_fc else None},
        "costs": {"jp": costs.SPREAD_JP, "us_regular": costs.SPREAD_US_REGULAR,
                  "us_off": costs.SPREAD_US_OFF, "fx_fee_yen": costs.FX_FEE_YEN,
                  "tax_rate": costs.TAX_RATE,
                  "us_in_hours": costs.us_market_open()},
        "stock_defaults": {"capital": config.STOCK_CAPITAL_JPY,
                           "risk": config.STOCK_RISK_PER_TRADE,
                           "stop_atr": config.STOCK_STOP_ATR_MULT},
        "universe_size": len(universe), "pool_size": pool_long.size(),
        "horizon_long": config.HORIZON_LONG, "horizon_fx": config.HORIZON_FX,
        "horizon_long_label": config.HORIZON_LONG_LABEL,
        "horizon_fx_label": config.HORIZON_FX_LABEL,
        "fx_min_confidence": config.FX_MIN_CONFIDENCE,
        "fx_signal_pairs": len(config.FX_SIGNAL_PAIRS),
        "fx_pool_pairs": len(fx_assets),
        "fx_confirmed": fxmod.CONFIRMED,
        "earnings_known": len(calendar),
        "elapsed": round(time.time() - t0, 1),
    }


def write(payload, verbose=True):
    n = _write_json("latest.json", payload)
    if verbose:
        d = os.path.join(OUT_DIR, "directory.json")
        print("   latest.json {:.0f} KB / directory.json {:.0f} KB".format(
            n / 1024, (os.path.getsize(d) / 1024) if os.path.exists(d) else 0))


if __name__ == "__main__":
    payload = build(use_cache="--cache" in sys.argv)
    write(payload)
    print()
    print("完了: {} 秒".format(payload["elapsed"]))
    print("  総合上位 {} 件 / 常時表示 {} 件 / カテゴリ {} 区分 / FXシグナル {} 件".format(
        len(payload["top5"]), len(payload["pinned"]), len(payload["categories"]),
        sum(1 for x in payload["fx"]["signals"] if x["tradeable"])))
    d = payload.get("diversification")
    if d:
        print("  分散: 平均相関 {:.2f} / 最大 {:.2f}{}".format(
            d["mean"], d["max"], "" if d["ok"] else " ← 警告あり"))
    u = payload["usdjpy"]
    if u["expected_return"] is not None:
        print("  ドル円1か月予測: {:+.2f}%（米ドル建て資産の円換算に反映）".format(
            u["expected_return"] * 100))
