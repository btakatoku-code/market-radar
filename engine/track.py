# -*- coding: utf-8 -*-
"""予測の記録と採点。

配信した予測をすべて残し、期限が来たものから実際の値動きと突き合わせる。
当たったか外れたかが積み上がらないと精度は上げられないので、この記録が
アプリの中で一番地味で一番重要な部分になる。

記録は追記のみ。過去の予測を書き換えることはしない。
"""
import json

import config
import os

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(HERE, "..", "data", "history")
PRED_FILE = os.path.join(HISTORY_DIR, "predictions.jsonl")


def _ensure():
    os.makedirs(HISTORY_DIR, exist_ok=True)


def _dedupe(rows):
    """同じ日・同じ銘柄・同じ枠は1件にまとめる。最初に記録した予測を残す。

    追記の時点では重複を防いでいるが、GitHub Actions と手元の実行が
    ぶつかって履歴を統合したときに、実行時刻の違う同じ予測が並んで
    残ったことがある（426行のうち126行が余分だった）。
    統合の仕方に関係なく集計が狂わないよう、読み込み時にも潰しておく。

    最初のものを残すのは、予測してから待つ、という実際の順序に合うため。
    """
    seen = {}
    for r in sorted(rows, key=lambda x: (x.get("ts") or 0)):
        k = (r.get("date"), r.get("key"), r.get("bucket"))
        if k in seen:
            # 採点済みの結果だけは引き継ぐ（後の行にしか入っていない場合がある）
            if seen[k].get("actual") is None and r.get("actual") is not None:
                seen[k]["actual"] = r["actual"]
            continue
        seen[k] = r
    return list(seen.values())


def load_predictions():
    _ensure()
    if not os.path.exists(PRED_FILE):
        return []
    out = []
    with open(PRED_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return _dedupe(out)


def append_predictions(records):
    """新しい予測を追記する。同じ日・同じ銘柄・同じ枠は重複させない。"""
    _ensure()
    existing = load_predictions()
    seen = {(r["date"], r["key"], r["bucket"]) for r in existing}
    added = 0
    with open(PRED_FILE, "a", encoding="utf-8") as f:
        for r in records:
            k = (r["date"], r["key"], r["bucket"])
            if k in seen:
                continue
            seen.add(k)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            added += 1
    return added


def _price_at_or_after(bars, ts):
    """ts 以降で最初のバーの終値。まだ無ければ None。"""
    t, c = bars["t"], bars["c"]
    for i in range(len(t)):
        if t[i] >= ts:
            return c[i], t[i]
    return None, None


LONG_BUCKETS = ("top5", "pinned", "category")


def _close_at_or_before(bars, ts):
    """ts 以前で最後のバーの終値（予測した時点の値段）。無ければ None。"""
    from bisect import bisect_right
    t = bars["t"]
    i = bisect_right(t, ts) - 1
    return bars["c"][i] if i >= 0 else None


def _close_at_or_after(bars, ts):
    from bisect import bisect_left
    t = bars["t"]
    i = bisect_left(t, ts)
    return bars["c"][i] if i < len(t) else None


def bench_return(assets_by_key, ts, due):
    """同じ期間に、対象の全銘柄（指数・FX・レバレッジ型を除く）を均等に持った場合の平均リターン。

    **株の TOP5 の比べる相手。** 「何もせず全部を持っていたら」より良くなければ、選んだ意味は無い。
    （2026-10-18 に追加。それまでは比べる相手が無く、相場全体の上げ下げと区別できなかった）"""
    rets = []
    for a in assets_by_key.values():
        if a.get("kind") in ("index", "fx") or a.get("leveraged"):
            continue
        bars = a.get("bars")
        if not bars or not bars.get("t"):
            continue
        p0, p1 = _close_at_or_before(bars, ts), _close_at_or_after(bars, due)
        if p0 and p1:
            rets.append(p1 / p0 - 1)
    return (sum(rets) / len(rets), len(rets)) if len(rets) >= 20 else (None, len(rets))


def add_bench(predictions, assets_by_key):
    """採点済みの株の予測に、同じ期間の全銘柄平均（bench）を付ける。付いていないものだけ。"""
    cache = {}
    added = 0
    for r in predictions:
        if r.get("bucket") not in LONG_BUCKETS or r.get("actual") is None or r.get("bench") is not None:
            continue
        k = (r.get("ts"), r.get("due"))
        if k not in cache:
            cache[k] = bench_return(assets_by_key, r["ts"], r["due"])
        b, n = cache[k]
        if b is not None:
            r["bench"], r["bench_n"] = b, n
            added += 1
    return added


def score(predictions, assets_by_key, now_ts):
    """期限が来た予測を採点する。predictions は破壊的に更新される。"""
    scored = 0
    for r in predictions:
        if r.get("actual") is not None:
            continue
        if now_ts < r["due"]:
            continue
        a = assets_by_key.get(r["key"])
        if not a:
            continue
        px, at = _price_at_or_after(a["bars"], r["due"])
        if px is None or not r.get("price"):
            continue
        actual = px / r["price"] - 1
        r["actual"] = actual
        r["actual_at"] = at
        pred = r["pred"]
        r["hit"] = bool((pred > 0) == (actual > 0)) if pred != 0 else None
        r["error"] = actual - pred
        scored += 1
    add_bench(predictions, assets_by_key)
    return scored


def rewrite(predictions):
    """採点結果を反映してファイルを書き直す。"""
    _ensure()
    tmp = PRED_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in predictions:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, PRED_FILE)


def _stats(rows):
    done = [r for r in rows if r.get("actual") is not None and r.get("hit") is not None]
    if not done:
        return None
    n = len(done)
    hits = sum(1 for r in done if r["hit"])
    mean_pred = sum(r["pred"] for r in done) / n
    mean_actual = sum(r["actual"] for r in done) / n
    mean_abs_err = sum(abs(r["error"]) for r in done) / n
    # 予測方向にポジションを取った場合の平均損益
    gains = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in done]
    mg = sum(gains) / n
    # 損益のばらつき。的中率だけでなく損益も監視するのに使う。
    sd = (sum((g - mg) ** 2 for g in gains) / (n - 1)) ** 0.5 if n > 1 else 0.0
    out = dict(n=n, hit_rate=hits / n, mean_pred=mean_pred,
               mean_actual=mean_actual, mean_abs_error=mean_abs_err,
               mean_gain=mg, sd_gain=sd,
               pending=sum(1 for r in rows if r.get("actual") is None))
    out.update(_by_day(done))
    return out


def _cluster(values_by_day):
    """日ごとの平均を1件と数えて、平均と95%の幅（日数が2以上のとき）。"""
    vals = list(values_by_day.values())
    d = len(vals)
    if d == 0:
        return None, None, None
    m = sum(vals) / d
    if d < 2:
        return m, None, None
    sd = (sum((v - m) ** 2 for v in vals) / (d - 1)) ** 0.5
    w = 1.96 * sd / d ** 0.5
    return m, m - w, m + w


def _by_day(done):
    """**同じ日の予測はまとめて1回と数える**（2026-10-18 追加）。

    同じ日に出した予測は、同じ相場の動きに一緒に引きずられる。株の TOP5 は68件あっても
    判断した日は9日しかなく、1件ずつ数えると確かさを実際より大きく見せてしまう。
    ここでは日ごとの平均を1件とし、その日数で95%の幅を出す。
    全銘柄平均（bench）が付いていれば、それとの差（超過）も同じ数え方で出す。"""
    days = {}
    for r in done:
        days.setdefault(r.get("date"), []).append(r)
    hit = {k: sum(1 for r in v if r["hit"]) / len(v) for k, v in days.items()}
    gain = {k: sum(r["actual"] * (1 if r["pred"] > 0 else -1) for r in v) / len(v) for k, v in days.items()}
    out = {"days": len(days)}
    out["hit_day"], out["hit_day_lo"], out["hit_day_hi"] = _cluster(hit)
    out["gain_day"], out["gain_day_lo"], out["gain_day_hi"] = _cluster(gain)
    with_b = {k: [r for r in v if r.get("bench") is not None] for k, v in days.items()}
    ex = {k: sum(r["actual"] - r["bench"] for r in v) / len(v) for k, v in with_b.items() if v}
    if ex:
        out["bench_days"] = len(ex)
        out["bench_mean"] = sum(sum(r["bench"] for r in v) / len(v) for v in with_b.values() if v) / len(ex)
        out["excess_day"], out["excess_day_lo"], out["excess_day_hi"] = _cluster(ex)
        allb = [r for v in with_b.values() for r in v]
        out["beat_rate"] = sum(1 for r in allb if r["actual"] > r["bench"]) / len(allb)
    return out


def _after_fix(rows):
    """不具合の修正より後の予測だけを返す。

    修正前は未確定の足を使っており、モデルが誤った入力で予測していた。
    その結果を混ぜたままだと、直した後の成績が永久に汚れる。
    古い分は捨てずに別枠で見せる（隠すためではなく、分けるため）。
    """
    import datetime
    try:
        cut = datetime.datetime.fromisoformat(config.PIPELINE_FIXED_AT).timestamp()
    except Exception:
        return rows
    return [r for r in rows if (r.get("ts") or 0) >= cut]


def summary(predictions):
    """枠ごと・直近の的中率をまとめる。"""
    # 不具合の修正より後の予測だけで採点する。混ぜると直した後の成績が汚れる。
    valid = _after_fix(predictions)
    valid_ids = {id(r) for r in valid}
    # 修正前の分は捨てずに別枠で持つ（隠すためではなく、分けるため）
    before = [r for r in predictions if id(r) not in valid_ids]
    # **週末に記録されたFXの予測は数えない**（2026-10-18）。日足のまま金曜のシグナルが出続け、
    # 金曜〜月曜の同じ値動きを2〜3回数えていた。記録は残し（追記のみの約束）、集計から外して件数を示す。
    weekend_fx = [r for r in valid if r["bucket"] in ("fx", "fx_watch") and _is_weekend(r.get("date"))]
    we_ids = {id(r) for r in weekend_fx}
    valid = [r for r in valid if id(r) not in we_ids]
    # **「全体」から指定銘柄（常に表示する大型株）を外す**（2026-10-18）。指定銘柄はスコアに
    # 関係なく毎回表示するので、相場全体が上がれば「当たり」になる。混ぜるとモデルの的中率が
    # 実力より良く見える（実際、9/8 以降で指定銘柄は91%、TOP5 は31%だった）。
    out = {"overall": _stats([r for r in valid if r["bucket"] != "pinned"]),
           "overall_note": "全体は指定銘柄を除く（指定銘柄は相場全体の上げ下げで当たり外れが決まるため）"}
    for bucket in ("top5", "pinned", "category", "fx", "fx_watch"):
        rows = [r for r in valid if r["bucket"] == bucket]
        out[bucket] = _stats(rows)
    out["before_fix"] = {
        "fx": _stats([r for r in before if r["bucket"] == "fx"]),
        "overall": _stats(before),
        "note": config.PIPELINE_FIX_NOTE,
        "fixed_at": config.PIPELINE_FIXED_AT,
    }
    # 直近30件・90件
    done = [r for r in valid if r.get("actual") is not None]
    done.sort(key=lambda r: r.get("actual_at") or r["due"])
    out["recent30"] = _stats(done[-30:]) if len(done) >= 5 else None
    out["recent90"] = _stats(done[-90:]) if len(done) >= 5 else None
    # 銘柄別（実績が5件以上あるもの）
    per = {}
    for r in done:
        per.setdefault(r["key"], []).append(r)
    per_asset = []
    for key, rows in per.items():
        st = _stats(rows)
        if st and st["n"] >= 5:
            per_asset.append(dict(key=key, name=rows[-1].get("name", key), **st))
    per_asset.sort(key=lambda x: -x["hit_rate"])
    out["per_asset"] = per_asset[:40]
    out["total_logged"] = len(valid)
    out["total_before_fix"] = len(before)
    out["fx_weekend_excluded"] = sum(1 for r in weekend_fx if r["bucket"] == "fx")
    out["fx_bias"] = direction_bias([r for r in valid if r["bucket"] == "fx"])
    return out


def _is_weekend(date_str):
    import datetime
    try:
        return datetime.date.fromisoformat(str(date_str)).weekday() >= 5
    except ValueError:
        return False


def direction_bias(rows):
    """FXの予測の向きの偏り（2026-10-18）。上と下の件数・それぞれの的中率・実際に上がった割合。

    9/8 以降の平日、予測は上50件・下7件と大きく偏っていた。実際に上がったのは49%で、上の予測の
    的中は52%。偏りが相場（上げが続いた）によるのか、モデルの癖なのかを見分けるために並べる。"""
    done = [r for r in rows if r.get("actual") is not None and r.get("hit") is not None]
    if not done:
        return None
    up = [r for r in done if r["pred"] > 0]
    dn = [r for r in done if r["pred"] < 0]
    return {"n": len(done), "up_n": len(up), "down_n": len(dn),
            "up_hit": (sum(r["hit"] for r in up) / len(up)) if up else None,
            "down_hit": (sum(r["hit"] for r in dn) / len(dn)) if dn else None,
            "actual_up_share": sum(1 for r in done if r["actual"] > 0) / len(done)}


RUNS_FILE = os.path.join(HISTORY_DIR, "runs.jsonl")


def log_run(ts, counts):
    """実行のたびに1行だけ記録する。動いている証拠として画面に出すため。"""
    _ensure()
    with open(RUNS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, **counts}, ensure_ascii=False) + "\n")


def recent_runs(limit=12):
    _ensure()
    if not os.path.exists(RUNS_FILE):
        return []
    out = []
    with open(RUNS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out[-limit:][::-1]


def progress(predictions, assets_by_key, now_ts, limit=24):
    """まだ期限が来ていない予測の途中経過。

    「予測は+1.4%、いまのところ+0.5%、残り18営業日」のように、
    採点を待たずに動きが見える形にする。数日たたないと何も出ないと、
    アプリが生きているのか分からないため。
    """
    open_rows = [r for r in predictions if r.get("actual") is None]
    rows = []
    for r in open_rows:
        a = assets_by_key.get(r["key"])
        if not a or not r.get("price"):
            continue
        cur = a["bars"]["c"][-1]
        actual = cur / r["price"] - 1
        pred = r.get("pred") or 0.0
        left = max(0, int((r["due"] - now_ts) // 86400))
        rows.append({
            "key": r["key"], "name": r.get("name", r["key"]),
            "bucket": r["bucket"], "date": r["date"],
            "pred": pred, "so_far": actual,
            "price": r["price"], "now": round(cur, 4),
            "days_left": left,
            "on_track": bool((pred > 0) == (actual > 0)) if pred else None,
        })
    if not rows:
        return None
    judged = [x for x in rows if x["on_track"] is not None]
    agg = {
        "open": len(rows),
        "on_track": sum(1 for x in judged if x["on_track"]),
        "judged": len(judged),
        "mean_pred": sum(x["pred"] for x in rows) / len(rows),
        "mean_so_far": sum(x["so_far"] for x in rows) / len(rows),
    }
    agg["on_track_rate"] = (agg["on_track"] / agg["judged"]) if agg["judged"] else None
    # 期限が近い順に並べ、画面に出す分だけ残す
    rows.sort(key=lambda x: (x["days_left"], -abs(x["pred"])))
    return {"summary": agg, "items": rows[:limit]}
