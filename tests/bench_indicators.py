import os, sys, time, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import indicators as I
random.seed(7)
for n in (500, 2500):
    c = [100.0]
    for _ in range(n - 1):
        c.append(max(1.0, c[-1] * (1 + random.gauss(0.0004, 0.017))))
    h = [x * 1.005 for x in c]; l = [x * 0.995 for x in c]
    v = [1e6] * n
    bars = {"t": list(range(n)), "o": c, "h": h, "l": l, "c": c, "v": v}
    t0 = time.time()
    for _ in range(3):
        I.compute_all(bars)
    dt = (time.time() - t0) / 3
    print(f"  {n:5}本: {dt*1000:7.1f} ms/銘柄  -> 650銘柄で {dt*650:.1f} 秒")
