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


def run_all(assets, predictions, shown_keys, signals, summary):
    checks = [
        check_bars_complete(assets),
        check_no_duplicates(predictions),
        check_required_assets(shown_keys),
        check_entry_reference(signals),
        check_scoring_sanity(summary),
    ]
    ng = [c for c in checks if not c["ok"]]
    return {
        "checks": checks,
        "ok": not ng,
        "failed": len(ng),
        "checked_at": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds"),
    }
