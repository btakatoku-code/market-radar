# -*- coding: utf-8 -*-
"""予測の記録と採点。

配信した予測をすべて残し、期限が来たものから実際の値動きと突き合わせる。
当たったか外れたかが積み上がらないと精度は上げられないので、この記録が
アプリの中で一番地味で一番重要な部分になる。

記録は追記のみ。過去の予測を書き換えることはしない。
"""
import json
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
    return dict(n=n, hit_rate=hits / n, mean_pred=mean_pred,
                mean_actual=mean_actual, mean_abs_error=mean_abs_err,
                mean_gain=mg, sd_gain=sd,
                pending=sum(1 for r in rows if r.get("actual") is None))


def summary(predictions):
    """枠ごと・直近の的中率をまとめる。"""
    out = {"overall": _stats(predictions)}
    for bucket in ("top5", "pinned", "category", "fx", "fx_watch"):
        rows = [r for r in predictions if r["bucket"] == bucket]
        out[bucket] = _stats(rows)
    # 直近30件・90件
    done = [r for r in predictions if r.get("actual") is not None]
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
    out["total_logged"] = len(predictions)
    return out


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
