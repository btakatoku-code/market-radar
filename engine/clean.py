# -*- coding: utf-8 -*-
"""価格系列の修復。

データ提供元の価格には次のような欠陥が混ざる。
  - 株式分割が価格に反映されていない（特に日本株）
  - 分割比率そのものが異常（1:20000000 など）
  - 数日だけ桁違いの価格が入っている
  - 数か月〜数年にわたって別物の価格が入っている

一方、決算や治験結果で本当に1日で2倍になる銘柄もあるため、
「壊れたデータ」と「実際の急変動」を区別しなければならない。

処理の順序:
  1. 短期間だけ突出したバーの並びを取り除く（前後と比べて桁が違うもの）
  2. 提供元の分割履歴のうち、比率が常識的な範囲のものを遡及適用する
  3. 残った大きな段差を、次の順で判定する
     a. 3倍以内の動きで出来高が急増 → 実際の急変動。そのまま残す
     b. 既知の分割比率に近い        → 未記録の分割として遡及調整
     c. 1日で3倍を超える段差        → 実在しない。データ断絶とみなす
     d. それ以外                    → 段差ぶんだけ調整して連続にする
  4. データ断絶が見つかった場合、最後の断絶より後だけを残す
"""

# 分割としてよくある比率（逆分割も含む）
COMMON_RATIOS = [1.2, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0,
                 12.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 100.0, 200.0]
JUMP_THRESHOLD = 0.55      # 1日の変化率がこれを超えたら精査する
BREAK_MAGNITUDE = 3.0      # 1日で3倍・3分の1を超える動きは実在しないものとして扱う
RATIO_TOLERANCE = 0.04     # 既知の分割比率に丸める許容誤差
SPLIT_WINDOW = 3           # 分割日の前後何本まで段差を探すか
MIN_SPLIT_RATIO = 0.01     # これを外れる分割比率は提供元の誤りとみなす
MAX_SPLIT_RATIO = 100.0
VOLUME_SPIKE = 2.0         # 出来高が中央値の何倍なら実際の急変動とみなすか
SPIKE_DEV = 0.5            # 突出バー判定: 前後の水準からの乖離
SPIKE_LEVEL_TOL = 0.35     # 突出区間の前後で水準が揃っているとみなす許容差
MAX_SPIKE_RUN = 3          # 何本続きまでを突出区間として除去するか


def _scale_before(bars, upto, factor):
    """位置 upto より前の価格を factor で割る（出来高は factor 倍する）"""
    if factor <= 0 or abs(factor - 1.0) < 1e-12:
        return
    for k in ("o", "h", "l", "c"):
        arr = bars[k]
        for i in range(upto):
            arr[i] /= factor
    v = bars["v"]
    for i in range(upto):
        v[i] *= factor
    t = bars.get("t")
    divs = bars.get("dividends")
    if divs and t and upto < len(t):
        cut = t[upto]
        bars["dividends"] = [(ts, (a / factor if ts < cut else a)) for ts, a in divs]


def _drop_range(bars, i0, i1):
    for k in ("t", "o", "h", "l", "c", "v"):
        del bars[k][i0:i1]


def _match_ratio(r):
    """r が単純な分割比率に近ければ、その比率に丸めて返す。近くなければ None。"""
    best, err = None, RATIO_TOLERANCE
    for base in COMMON_RATIOS:
        for cand in (base, 1.0 / base):
            e = abs(r / cand - 1.0)
            if e <= err:
                best, err = cand, e
    return best


def remove_spikes(bars, max_passes=30):
    """前後の水準から突出した短い区間（1〜3本）を取り除く。"""
    removed = 0
    for _ in range(max_passes):
        c = bars["c"]
        hit = None
        for run in range(1, MAX_SPIKE_RUN + 1):
            for i in range(1, len(c) - run):
                before, after = c[i - 1], c[i + run]
                if before <= 0 or after <= 0:
                    continue
                # 区間の前後で水準が揃っていること
                if abs(after / before - 1.0) > SPIKE_LEVEL_TOL:
                    continue
                # 区間内の全バーが前後の水準から乖離していること
                if all(x > 0 and abs(x / before - 1.0) > SPIKE_DEV
                       for x in c[i:i + run]):
                    hit = (i, i + run)
                    break
            if hit:
                break
        if not hit:
            break
        _drop_range(bars, hit[0], hit[1])
        removed += hit[1] - hit[0]
    return removed


def apply_splits(bars):
    """提供元の分割履歴を遡及適用する。異常な比率は無視する。適用件数を返す。"""
    splits = bars.get("splits") or []
    if not splits:
        return 0
    applied = 0
    for date, ratio in sorted(splits):
        if not (MIN_SPLIT_RATIO <= ratio <= MAX_SPLIT_RATIO):
            continue                 # 提供元の誤り
        if abs(ratio - 1.0) < 1e-9:
            continue
        t, c = bars["t"], bars["c"]
        anchor = None
        for i, tt in enumerate(t):
            if tt >= date:
                anchor = i
                break
        if anchor is None or anchor == 0:
            continue
        best, best_err = None, 0.35
        for pos in range(max(1, anchor - SPLIT_WINDOW),
                         min(len(c), anchor + SPLIT_WINDOW + 1)):
            if c[pos - 1] <= 0 or c[pos] <= 0:
                continue
            err = abs((c[pos - 1] / c[pos]) / ratio - 1.0)
            if err < best_err:
                best, best_err = pos, err
        if best is None:
            continue                 # 段差なし → すでに調整済み
        _scale_before(bars, best, ratio)
        applied += 1
    return applied


def _volume_spike(bars, i, window=20):
    """バー i の出来高が直近中央値の何倍か。判定できない場合は None。"""
    v = bars["v"]
    prev = [x for x in v[max(0, i - window):i] if x > 0]
    if len(prev) < 5 or v[i] <= 0:
        return None
    prev.sort()
    med = prev[len(prev) // 2]
    return v[i] / med if med > 0 else None


def repair(bars, max_passes=30):
    """価格系列を修復する。

    戻り値: (適用した分割数, 切り捨てた本数, 説明のリスト)
    """
    notes = []

    n_spike = remove_spikes(bars)
    if n_spike:
        notes.append("突出した{}本を除去".format(n_spike))

    n_split = apply_splits(bars)
    if n_split:
        notes.append("分割履歴を{}件適用".format(n_split))

    truncate_at = 0
    scan_from = 0
    for _ in range(max_passes):
        c = bars["c"]
        found = None
        for i in range(scan_from + 1, len(c)):
            if c[i - 1] <= 0:
                continue
            r = c[i] / c[i - 1]
            if abs(r - 1.0) > JUMP_THRESHOLD:
                found = (i, r)
                break
        if not found:
            break
        i, r = found
        # 上下で尺度を揃えるため、倍率の大きさで判定する
        mag = max(r, 1.0 / r) if r > 0 else float("inf")
        factor = 1.0 / r if r > 0 else None
        snapped = _match_ratio(factor) if factor else None
        spike = _volume_spike(bars, i)

        # 1. 常識的な範囲の動きで出来高の裏付けがある → 実際の急変動として残す
        if mag <= BREAK_MAGNITUDE and spike is not None and spike >= VOLUME_SPIKE:
            scan_from = i
            continue

        # 2. 既知の分割比率に近い → 未記録の分割として遡及調整
        if snapped is not None:
            _scale_before(bars, i, snapped)
            notes.append("未記録の分割とみなし{:.4g}倍で調整".format(snapped))
            continue

        # 3. 実在しない大きさの段差 → データ断絶
        if mag > BREAK_MAGNITUDE:
            scan_from = i
            truncate_at = i
            notes.append("データ断絶（{:+.4g}%）".format((r - 1) * 100))
            continue

        # 4. 原因不明の段差 → 段差ぶんだけ遡及調整して連続にする
        _scale_before(bars, i, factor)
        notes.append("段差{:+.1f}%を連続化".format((r - 1) * 100))

    trimmed = 0
    if truncate_at > 0:
        trimmed = truncate_at
        for k in ("t", "o", "h", "l", "c", "v"):
            bars[k] = bars[k][truncate_at:]
    return n_split, trimmed, notes


def sanity_ok(bars, min_bars=60, max_mag=BREAK_MAGNITUDE):
    """修復後もなお異常が残っていないかの最終確認"""
    c = bars["c"]
    if len(c) < min_bars:
        return False
    for i in range(1, len(c)):
        if c[i - 1] <= 0 or c[i] <= 0:
            return False
        r = c[i] / c[i - 1]
        if max(r, 1.0 / r) > max_mag:
            return False
    return True
