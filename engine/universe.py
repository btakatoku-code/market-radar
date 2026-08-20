# -*- coding: utf-8 -*-
"""PayPay証券の取扱銘柄ユニバース。公式サイトの取扱銘柄一覧から取得。"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# Yahoo Finance 側の表記が PayPay 表記と異なる銘柄
YAHOO_OVERRIDE = {"BRKB": "BRK-B"}


def _read_tsv(name):
    path = os.path.join(HERE, name)
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            rows.append(line.split("\t"))
    return rows


def yahoo_symbol(code, market):
    """PayPayの銘柄コード → Yahoo Finance のティッカー"""
    if market == "jp":
        return f"{code}.T"
    return YAHOO_OVERRIDE.get(code, code)


def load():
    """[{code, name, yahoo, kind, market, tradable}] を返す"""
    out = []

    for code, name in [(r[0], r[1]) for r in _read_tsv("universe_us.tsv")]:
        out.append(dict(code=code, name=name, yahoo=yahoo_symbol(code, "us"),
                        kind="us_stock", market="us", leveraged=False))

    for r in _read_tsv("universe_us_etf.tsv"):
        code, name, tag = r[0], r[1], (r[2] if len(r) > 2 else "std")
        out.append(dict(code=code, name=name, yahoo=yahoo_symbol(code, "us"),
                        kind="us_etf", market="us", leveraged=(tag == "lev")))

    for code, name in [(r[0], r[1]) for r in _read_tsv("universe_jp.tsv")]:
        out.append(dict(code=code, name=name, yahoo=yahoo_symbol(code, "jp"),
                        kind="jp_stock", market="jp", leveraged=False))

    for r in _read_tsv("universe_jp_etf.tsv"):
        code, name, tag = r[0], r[1], (r[2] if len(r) > 2 else "std")
        kind = "jp_reit" if tag == "reit" else "jp_etf"
        out.append(dict(code=code, name=name, yahoo=yahoo_symbol(code, "jp"),
                        kind=kind, market="jp", leveraged=(tag == "lev")))

    return out


if __name__ == "__main__":
    u = load()
    from collections import Counter
    print(f"合計 {len(u)} 銘柄")
    for k, v in Counter(x["kind"] for x in u).items():
        print(f"  {k}: {v}")
    print(f"  レバレッジ/インバース型: {sum(1 for x in u if x['leveraged'])}")
