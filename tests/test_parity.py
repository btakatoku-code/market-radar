# -*- coding: utf-8 -*-
"""照合の検査そのものが効くかを確かめる。

一度も失敗しない検査は意味がない。わざと不具合を戻して、
ちゃんと異常として捕まえられることを確認する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import config
import dataset
import parity

if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    fx = [a for a in assets if a["kind"] == "fx"]
    base = next(a for a in fx if a["key"] == "USDJPY=X")
    ok_all = True

    for off in (20, 60, 120):
        ts = base["bars"]["t"][-off]
        normal = parity.summarize(
            parity.compare(fx, config.FX_SIGNAL_PAIRS, ts, config.HORIZON_FX))
        broken = parity.summarize(
            parity.compare(fx, config.FX_SIGNAL_PAIRS, ts, config.HORIZON_FX,
                           extra_bars=1))
        pass1 = normal["ok"]
        pass2 = not broken["ok"]
        ok_all = ok_all and pass1 and pass2
        print("  {}本前 : 正常なら一致 {}  /  不具合を戻すと検出 {}".format(
            off, "PASS" if pass1 else "FAIL", "PASS" if pass2 else "FAIL"))
        if not pass2:
            print("     ※ 検査が異常を見逃した。これでは意味がない。")

    print()
    print("結果:", "全て合格" if ok_all else "不合格")
    sys.exit(0 if ok_all else 1)
