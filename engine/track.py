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
    return out


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
    return dict(n=n, hit_rate=hits / n, mean_pred=mean_pred,
                mean_actual=mean_actual, mean_abs_error=mean_abs_err,
                mean_gain=sum(gains) / n,
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
