# -*- coding: utf-8 -*-
"""指標の健全性チェック。標準ライブラリのみで実行可能。"""
import os, sys, math, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import indicators as I

fails = []
def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        fails.append(name)

random.seed(42)
n = 500
c = [100.0]
for _ in range(n - 1):
    c.append(max(1.0, c[-1] * (1 + random.gauss(0.0005, 0.018))))
h = [x * (1 + abs(random.gauss(0, 0.006))) for x in c]
l = [x * (1 - abs(random.gauss(0, 0.006))) for x in c]
v = [1e6 * (1 + abs(random.gauss(0, 0.4))) for _ in c]
bars = {"t": list(range(n)), "o": c, "h": h, "l": l, "c": c, "v": v}
r = I.compute_all(bars)

print("== 長さの整合 ==")
for k, arr in r.items():
    check(f"len({k})", len(arr) == n, f"{len(arr)} != {n}")

print("== 値域 ==")
rsi_v = [x for x in r["rsi14"] if x is not None]
check("RSI 0..100", all(0 <= x <= 100 for x in rsi_v), f"min={min(rsi_v):.2f} max={max(rsi_v):.2f}")
check("RSI 開始位置=14", r["rsi14"][13] is None and r["rsi14"][14] is not None)
adx_v = [x for x in r["adx14"] if x is not None]
check("ADX 0..100", all(0 <= x <= 100 for x in adx_v), f"min={min(adx_v):.2f} max={max(adx_v):.2f}")
atr_v = [x for x in r["atr14"] if x is not None]
check("ATR > 0", all(x > 0 for x in atr_v))
check("ATR 開始位置=14", r["atr14"][13] is None and r["atr14"][14] is not None)
vol_v = [x for x in r["vol20"] if x is not None]
check("年率ボラが妥当(0.1〜1.0)", 0.1 < sum(vol_v) / len(vol_v) < 1.0,
      f"平均={sum(vol_v)/len(vol_v):.3f} 理論値≈{0.018*math.sqrt(252):.3f}")
dh = [x for x in r["dist_high"] if x is not None]
check("52週高値乖離 <= 0", all(x <= 1e-12 for x in dh), f"max={max(dh)}")

print("== 手計算との一致 ==")
check("SMA20", abs(r["sma20"][-1] - sum(c[-20:]) / 20) < 1e-9)
check("SMA200", abs(r["sma200"][-1] - sum(c[-200:]) / 200) < 1e-9)
check("ROC20", abs(r["roc20"][-1] - (c[-1] / c[-21] - 1)) < 1e-12)
k = 2 / 21.0
manual = sum(c[:20]) / 20
for i in range(20, n):
    manual = c[i] * k + manual * (1 - k)
check("EMA20", abs(r["ema20"][-1] - manual) < 1e-9)
mid = sum(c[-20:]) / 20
sd = math.sqrt(sum((x - mid) ** 2 for x in c[-20:]) / 20)
check("BB %B", abs(r["bb_pctb"][-1] - (c[-1] - (mid - 2 * sd)) / (4 * sd)) < 1e-9)
check("MACD = EMA12-EMA26",
      abs(r["macd"][-1] - (I.ema(c, 12)[-1] - I.ema(c, 26)[-1])) < 1e-9)
check("MACD hist = line - signal",
      abs(r["macd_hist"][-1] - (r["macd"][-1] - r["macd_signal"][-1])) < 1e-9)

print("== 既知系列でのRSI検証（Wilder原典の終値） ==")
w = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
     45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
rw = I.rsi(w, 14)
check("RSI(14) 15本目 ≈ 70.46", abs(rw[14] - 70.46) < 0.05, f"実測={rw[14]:.2f}")
check("RSI(14) 16本目 ≈ 66.25", abs(rw[15] - 66.25) < 0.05, f"実測={rw[15]:.2f}")
check("RSI(14) 20本目 ≈ 57.90", abs(rw[19] - 57.90) < 0.05, f"実測={rw[19]:.2f}")

print("== 単調系列での挙動 ==")
up = [100.0 * (1.01 ** i) for i in range(60)]
uh = [x * 1.001 for x in up]; ul = [x * 0.999 for x in up]
check("連続上昇でRSI=100", abs(I.rsi(up, 14)[-1] - 100) < 1e-6, f"{I.rsi(up,14)[-1]}")
check("連続上昇でADX>60", I.adx(uh, ul, up, 14)[-1] > 60, f"{I.adx(uh,ul,up,14)[-1]:.1f}")
flat = [100.0] * 60
check("横ばいでATR=0", I.atr([100.0]*60, [100.0]*60, flat, 14)[-1] == 0)

print("== 短い系列で落ちない ==")
try:
    I.compute_all({"t": [1, 2], "o": [1.0, 2.0], "h": [1.0, 2.0],
                   "l": [1.0, 2.0], "c": [1.0, 2.0], "v": [1.0, 2.0]})
    check("2本の系列でも例外なし", True)
except Exception as e:
    check("2本の系列でも例外なし", False, str(e))

print()
print(f"結果: {'全て合格' if not fails else str(len(fails)) + ' 件不合格: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
