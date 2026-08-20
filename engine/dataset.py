# -*- coding: utf-8 -*-
"""全銘柄のOHLCV取得 → 指標計算 → 特徴量計算 をまとめる層。"""
import clean
import config
import indicators
import market
import analog
import sources
import universe


def _prep(key, name, kind, bars, extra=None):
    ind = indicators.compute_all(bars)
    feats = analog.feature_matrix(bars, ind)
    c, v = bars["c"], bars["v"]
    n = min(20, len(c))
    adv = sum(c[-n:][i] * v[-n:][i] for i in range(n)) / n   # 平均売買代金
    a = {"key": key, "name": name, "kind": kind, "bars": bars,
         "ind": ind, "feats": feats, "adv": adv,
         "price": c[-1], "currency": bars.get("currency"),
         "bars_count": len(c)}
    if extra:
        a.update(extra)
    return a


def load_all(use_cache=True, include_universe=True, progress=True,
             regime_mode=None):
    """[asset] を返す。asset は bars/ind/feats/adv などを持つ dict。"""
    specs, meta = [], {}

    for sym, name, kind, src, note in config.EXTRA_ASSETS:
        specs.append((sym, src, sym))
        meta[sym] = dict(name=name, kind=kind, note=note, core=False,
                         leveraged=False, code=sym)

    if include_universe:
        for u in universe.load():
            if u["yahoo"] in meta:
                meta[u["yahoo"]]["code"] = u["code"]
                continue
            specs.append((u["yahoo"], "yahoo", u["yahoo"]))
            meta[u["yahoo"]] = dict(name=u["name"], kind=u["kind"], note="",
                                    core=False, leveraged=u["leveraged"],
                                    code=u["code"])

    for sym, name in config.FX_PAIRS:
        if sym in meta:
            continue
        specs.append((sym, "yahoo", sym))
        meta[sym] = dict(name=name, kind="fx", note="", core=False,
                         leveraged=False, code=sym)

    for sym, name in list(config.MARKET_CONTEXT) + list(config.REGIME_SYMBOLS):
        if sym in meta:
            continue
        specs.append((sym, "yahoo", sym))
        meta[sym] = dict(name=name, kind="index", note="", core=False,
                         leveraged=False, code=sym)

    # 重複排除
    seen, uniq = set(), []
    for s in specs:
        if s[0] in seen:
            continue
        seen.add(s[0])
        uniq.append(s)

    if progress:
        print(f"  {len(uniq)} 銘柄を取得中...")
    raw = sources.fetch_many(uniq, workers=6, use_cache=use_cache, progress=progress)

    # 分割の遡及調整やデータ断絶の修復は株式・ETFにのみ適用する。
    # 指数・FX・暗号資産には分割がなく、実際に1日で大きく動くことがあるため。
    NO_REPAIR = {"index", "fx", "crypto"}

    assets, missing, repaired = [], [], []
    for key, bars in raw.items():
        if not bars or len(bars["c"]) < 60:
            missing.append(key)
            continue
        m = meta[key]
        if m["kind"] not in NO_REPAIR:
            n_split, trimmed, notes = clean.repair(bars)
            if notes:
                repaired.append((key, m["name"], trimmed, notes))
        if len(bars["c"]) < 60:
            missing.append(key)
            continue
        assets.append(_prep(key, m["name"], m["kind"], bars,
                            extra={"note": m["note"], "core": m["core"],
                                   "leveraged": m["leveraged"], "code": m["code"]}))
    if progress:
        print("  分析対象 {} 銘柄 / 取得失敗 {} 件{}".format(
            len(assets), len(missing),
            (": " + ", ".join(missing[:10])) if missing else ""))
        if repaired:
            print("  価格データを修復 {} 銘柄".format(len(repaired)))

    if regime_mode is None:
        attach_regime(assets, config.REGIME_MODE_LONG, config.REGIME_MODE_FX, progress)
    else:
        attach_regime(assets, regime_mode, progress=progress)
    return assets


def attach_regime(assets, mode, mode_fx=None, progress=False):
    """各銘柄のバーに、前営業日時点の市場レジームを割り当てる。

    mode_fx を渡すと、FXだけ別のレジーム定義を使う。実測では株とFXで
    効き方が逆だったため、本番では使い分けている。
    """
    reg_long = market.build(assets, mode)
    reg_fx = reg_long if (mode_fx is None or mode_fx == mode) else market.build(assets, mode_fx)
    for a in assets:
        r = reg_fx if a["kind"] == "fx" else reg_long
        a["regime"] = r.series_for(a["bars"]) if r.levels > 1 else None
    if progress:
        print("  市場レジーム: 長期={}（{}段階） / FX={}（{}段階）".format(
            mode, reg_long.levels, mode_fx or mode, reg_fx.levels))
    return reg_fx if (mode_fx and reg_fx.levels > 1) else reg_long


def by_key(assets):
    return {a["key"]: a for a in assets}
