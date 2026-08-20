# -*- coding: utf-8 -*-
"""データ取得の実地確認。ネットワークに接続して実際に叩く。"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import sources, universe

print("== 単体取得 ==")
for kind, sym in [("yahoo", "NVDA"), ("yahoo", "7203.T"), ("yahoo", "GC=F"),
                  ("yahoo", "USDJPY=X"), ("binance", "BTCUSDT")]:
    b = sources.fetch_binance(sym) if kind == "binance" else sources.fetch_yahoo(sym)
    if b:
        print(f"  OK   {sym:12} {len(b['c']):4}本  終値={b['c'][-1]:.2f} {b['currency']}")
    else:
        print(f"  NG   {sym}")

print()
print("== ユニバース全件の並列取得 ==")
u = universe.load()
specs = [(x["code"], "yahoo", x["yahoo"]) for x in u]
t0 = time.time()
res = sources.fetch_many(specs, workers=6, use_cache=True)
el = time.time() - t0
ok = {k: v for k, v in res.items() if v}
bad = [k for k, v in res.items() if not v]
print(f"  成功 {len(ok)}/{len(specs)}   {el:.1f}秒")
if bad:
    print(f"  取得できず ({len(bad)}件): {', '.join(bad[:40])}")
short = [(k, len(v['c'])) for k, v in ok.items() if len(v['c']) < 300]
if short:
    print(f"  履歴300本未満 ({len(short)}件): {', '.join(f'{k}({n})' for k, n in short[:30])}")
