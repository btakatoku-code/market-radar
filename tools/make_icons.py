# -*- coding: utf-8 -*-
"""アプリアイコンを生成する（外部ライブラリ不使用）。"""
import math, os, struct, zlib

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "icons")

BG_TOP    = (16, 24, 52)
BG_BOTTOM = (9, 13, 28)
LINE      = (91, 140, 255)
LINE2     = (37, 208, 160)

# 折れ線の形（0〜1の相対座標）
PATH = [(0.10, 0.68), (0.26, 0.52), (0.40, 0.60), (0.55, 0.36), (0.70, 0.44), (0.90, 0.20)]


def _dist_to_seg(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    L = vx * vx + vy * vy
    t = 0.0 if L == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / L))
    dx, dy = ax + t * vx - px, ay + t * vy - py
    return math.sqrt(dx * dx + dy * dy), t


def render(size):
    radius = size * 0.225           # 角丸
    thick = size * 0.052            # 線の太さ
    pts = [(x * size, y * size) for x, y in PATH]
    total = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            # 角丸のアルファ
            cx = min(x + .5, size - x - .5)
            cy = min(y + .5, size - y - .5)
            a = 255
            if cx < radius and cy < radius:
                d = math.hypot(radius - cx, radius - cy)
                if d > radius:
                    a = 0
                elif d > radius - 1.2:
                    a = int(255 * (radius - d) / 1.2)
            if a == 0:
                row += b"\x00\x00\x00\x00"
                continue
            # 背景のグラデーション
            t = y / max(1, size - 1)
            r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
            g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
            b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
            # 折れ線
            best, pos = 1e9, 0.0
            acc = 0.0
            for i in range(len(pts) - 1):
                seg = math.dist(pts[i], pts[i + 1])
                d, tt = _dist_to_seg(x + .5, y + .5, pts[i][0], pts[i][1],
                                     pts[i + 1][0], pts[i + 1][1])
                if d < best:
                    best = d
                    pos = (acc + tt * seg) / total if total else 0
                acc += seg
            if best < thick:
                f = 1.0 if best < thick - 1.4 else (thick - best) / 1.4
                lr = int(LINE[0] + (LINE2[0] - LINE[0]) * pos)
                lg = int(LINE[1] + (LINE2[1] - LINE[1]) * pos)
                lb = int(LINE[2] + (LINE2[2] - LINE[2]) * pos)
                r = int(r + (lr - r) * f)
                g = int(g + (lg - g) * f)
                b = int(b + (lb - b) * f)
            row += bytes((r, g, b, a))
        rows.append(row)

    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    return png


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for s in (180, 192, 512):
        p = os.path.join(OUT, "icon-{}.png".format(s))
        with open(p, "wb") as f:
            f.write(render(s))
        print("  {}  {:,} bytes".format(p, os.path.getsize(p)))
