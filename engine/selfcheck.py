# -*- coding: utf-8 -*-
"""自己点検。毎回の実行で「壊れていないか」を機械が確かめる。

このアプリでは、静かに壊れる不具合が繰り返し起きた。

  2026-08-22  Binance が米国IPを遮断し、サーバー上だけ暗号資産が消えていた
  2026-09-06  予測の履歴が重複し、的中率の集計が狂っていた
  2026-09-06  アプリが1週間前のデータを表示し続けていた
  2026-09-08  未確定の足を確定した足として使い、予測が逆になっていた

どれも利用者か偶然が見つけたもので、**アプリ自身は一度も気づけなかった**。
最後のものは19日間気づかれず、その間ずっと逆の予測を出し続けた。

だから「気をつける」ではなく、機械が毎回確かめる。破れたら画面に出す。
検査は速いものだけにして、毎回の実行に必ず含める。
"""
import datetime
import time

import config


def _tod(x):
    return x % 86400


def check_bars_complete(assets):
    """未確定の足が混ざっていないか。2026-09-08 の不具合の再発防止。"""
    bad = []
    now = time.time()
    for a in assets:
        t = (a.get("bars") or {}).get("t") or []
        if len(t) < 4:
            continue
        diffs = [t[k + 1] - t[k] for k in range(len(t) - 6, len(t) - 1) if t[k + 1] > t[k]]
        period = min(diffs) if diffs else 0
        irregular = _tod(t[-2]) == _tod(t[-3]) and _tod(t[-1]) != _tod(t[-2])
        too_fresh = bool(period) and (now - t[-1]) < period * 0.5
        if irregular or too_fresh:
            bad.append(a["key"])
    return {
        "name": "未確定の足が混ざっていないか",
        "ok": not bad,
        "detail": ("すべて確定した足です（{}銘柄）。".format(len(assets)) if not bad
                   else "未確定の足が {} 銘柄に混ざっています: {}".format(
                       len(bad), ", ".join(bad[:5]))),
        "why": "確定前の足を使うと、途中の動きを完成した動きと誤認して予測が逆になります。",
    }


def check_no_duplicates(predictions):
    """同じ日・銘柄・枠の記録が重複していないか。2026-09-06 の不具合。"""
    seen = {}
    for r in predictions:
        k = (r.get("date"), r.get("key"), r.get("bucket"))
        seen[k] = seen.get(k, 0) + 1
    dup = sum(1 for v in seen.values() if v > 1)
    return {
        "name": "予測の記録が重複していないか",
        "ok": dup == 0,
        "detail": ("{}件の記録に重複なし。".format(len(predictions)) if dup == 0
                   else "{}組が重複しています。".format(dup)),
        "why": "重複すると、たまたま良かった日・悪かった日が何倍にも数えられます。",
    }


def check_required_assets(shown_keys):
    """必ず表示すべき銘柄が欠けていないか。2026-08-22 の不具合。"""
    missing = [n for k, n in config.REQUIRED_ASSETS if k not in shown_keys]
    return {
        "name": "必須の銘柄が揃っているか",
        "ok": not missing,
        "detail": ("{}銘柄すべて表示できています。".format(len(config.REQUIRED_ASSETS))
                   if not missing else "欠けています: " + "、".join(missing)),
        "why": "取得元の障害で、銘柄が丸ごと消えても気づけないことがありました。",
    }


def check_entry_reference(signals):
    """予測の基準が、確定した終値になっているか。"""
    bad = [s["name"] for s in signals
           if s.get("live_price") and s.get("price")
           and abs(s["live_price"] - s["price"]) < 1e-12]
    return {
        "name": "予測の基準が確定した終値か",
        "ok": not bad,
        "detail": ("基準はすべて確定した終値です。" if not bad
                   else "実勢と同じ値段を基準にしています: " + "、".join(bad)),
        "why": "基準がいまの値段と同じなら、未確定の足を使っている疑いがあります。",
    }


def check_scoring_sanity(summary):
    """採点そのものが壊れていないか。

    優位性がなくても的中率は50%前後になる。大きく外れるなら、
    戦略ではなく採点や入力を疑うべき。
    """
    fx = (summary or {}).get("fx")
    if not fx or fx["n"] < 20:
        return {"name": "採点が壊れていないか", "ok": True,
                "detail": "判定には20件必要です（いま{}件）。".format(fx["n"] if fx else 0),
                "why": "優位性がなくても五分前後になるはずで、大きく外れるなら仕組みを疑います。"}
    off = abs(fx["hit_rate"] - 0.5) > 0.25
    return {
        "name": "採点が壊れていないか",
        "ok": not off,
        "detail": ("的中率{:.1f}%（{}件）。異常な偏りはありません。".format(
            fx["hit_rate"] * 100, fx["n"]) if not off
            else "的中率{:.1f}%（{}件）。五分から離れすぎで、仕組みの不具合が疑われます。".format(
                fx["hit_rate"] * 100, fx["n"])),
        "why": "優位性がないだけなら五分前後です。それより極端なら入力か採点が壊れています。",
    }


def check_parity(fx_assets, offsets=(20, 60, 120)):
    """実運用と検証が、同じ入力に同じ答えを返すか。

    既知の症状を見張る検査は、次の未知の不具合を捕まえられない。これは
    直接の照合で、過去のある日までのデータだけを実運用の経路に渡し、
    検証の経路と同じ予測になるかを見る。

    未確定の足の不具合は、この検査なら初日に見つかった（実際、その状態を
    再現すると5ペアすべてで不一致、向きの食い違いも検出できる）。
    """
    import parity
    if not fx_assets:
        return {"name": "実運用と検証が一致するか", "ok": True,
                "detail": "為替データがありません。", "why": ""}
    base = next((a for a in fx_assets if a["key"] == "USDJPY=X"), fx_assets[0])
    t = base["bars"]["t"]
    results = []
    for off in offsets:
        if len(t) <= off + config.MIN_BARS:
            continue
        ts = t[-off]
        rows = parity.compare(fx_assets, config.FX_SIGNAL_PAIRS,
                              ts, config.HORIZON_FX)
        r = parity.summarize(rows)
        r["offset"] = off
        results.append(r)
    if not results:
        return {"name": "実運用と検証が一致するか", "ok": True,
                "detail": "照合できる時点がありません。", "why": ""}
    ng = [r for r in results if not r["ok"]]
    worst = max((r["max_diff_return"] for r in results), default=0.0)
    return {
        "name": "実運用と検証が一致するか",
        "ok": not ng,
        "detail": ("{}時点すべてで一致（最大差 {:.1e}）。".format(len(results), worst)
                   if not ng else
                   "{}時点中{}時点で食い違い（最大差 {:.1e}、向きの不一致 {}件）。".format(
                       len(results), len(ng), worst,
                       sum(r["direction_mismatch"] for r in ng))),
        "why": ("食い違うなら、検証で測った成績は実運用に当てはまりません。"
                "既知の症状を見張る検査では次の不具合を捕まえられないため、"
                "直接照合しています。"),
        "results": results,
    }


def run_all(assets, predictions, shown_keys, signals, summary):
    checks = [
        check_bars_complete(assets),
        check_no_duplicates(predictions),
        check_required_assets(shown_keys),
        check_entry_reference(signals),
        check_scoring_sanity(summary),
        check_parity([a for a in assets if a.get("kind") == "fx"]),
    ]
    ng = [c for c in checks if not c["ok"]]
    return {
        "checks": checks,
        "ok": not ng,
        "failed": len(ng),
        "checked_at": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds"),
    }
