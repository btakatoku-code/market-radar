import os, sys, time, datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import sources
for kind, sym in [("yahoo","NVDA"),("yahoo","7203.T"),("yahoo","GC=F"),
                  ("yahoo","USDJPY=X"),("binance","BTCUSDT"),("binance","SOLUSDT")]:
    b = sources.fetch_binance(sym) if kind=="binance" else sources.fetch_yahoo(sym)
    if b:
        d0 = datetime.date.fromtimestamp(b["t"][0]); d1 = datetime.date.fromtimestamp(b["t"][-1])
        print(f"  {sym:12} {len(b['c']):5}本  {d0} 〜 {d1}")
    else:
        print(f"  {sym:12} 取得失敗")
