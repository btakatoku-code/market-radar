# -*- coding: utf-8 -*-
"""実運用の成績が、検証値から離れていないかの監視。

検証で確認できた優位性は、いつまでも続く保証がない。市場が変われば消える。
問題は「消えたことにいつ気づくか」で、後から基準を決めると都合よく
解釈してしまう。だから**基準を先に決めて記録しておく**。

ここで決めている規則（実績を見る前に固定したもの）:

  対象      FXのシグナル（確信度56%以上）
  想定      的中率 60.6%（検証時点の並びを変えた3標本の平均）
  最低件数  30件。これ未満では何も判定しない
  警告      想定を下回る片側検定の p 値が 0.05 未満のとき
  停止検討  的中率の95%区間の上端が 50% を下回ったとき
            （＝優位性がある可能性そのものが否定される水準）

停止の基準を「勝率が下がったら」ではなく区間で決めているのは、
少ない件数のブレで止めたり続けたりしないため。
"""
import math

MIN_SAMPLES = 30
ALARM_P = 0.05
STOP_UPPER = 0.50


def binom_cdf(k, n, p):
    """n回中k回以下になる確率。"""
    if n <= 0:
        return 1.0
    k = max(0, min(k, n))
    total = 0.0
    log_p = math.log(p) if p > 0 else float("-inf")
    log_q = math.log(1 - p) if p < 1 else float("-inf")
    for i in range(k + 1):
        lc = (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1))
        total += math.exp(lc + i * log_p + (n - i) * log_q)
    return min(1.0, total)


def wilson(k, n, z=1.96):
    """勝率の信頼区間（ウィルソン法）。少ない件数でも極端に外れにくい。"""
    if n <= 0:
        return (0.0, 1.0)
    ph = k / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


def needed_for_alarm(expected, min_n=MIN_SAMPLES):
    """何件たまれば判定できるようになるかの目安。"""
    return min_n


def check(wins, n, expected, min_n=MIN_SAMPLES):
    """実績が想定から離れていないかを判定する。"""
    lo, hi = wilson(wins, n)
    hit = (wins / n) if n else None
    res = {
        "n": n, "wins": wins, "hit": hit, "expected": expected,
        "ci_low": lo, "ci_high": hi, "min_samples": min_n,
        "p_value": None, "verdict": "not_enough",
        "label": "まだ判定できません",
        "detail": "判定には{}件必要です（いま{}件）。".format(min_n, n),
    }
    if n < min_n:
        res["remaining"] = min_n - n
        return res
    p = binom_cdf(wins, n, expected)      # 想定を下回る側の片側検定
    res["p_value"] = p
    if hi < STOP_UPPER:
        res["verdict"] = "stop"
        res["label"] = "停止を検討してください"
        res["detail"] = ("的中率の95%区間の上端が{:.1f}%で、五分を下回っています。"
                         "優位性があるとは言えない水準です。").format(hi * 100)
    elif p < ALARM_P:
        res["verdict"] = "below"
        res["label"] = "想定を下回っています"
        res["detail"] = ("想定{:.1f}%に対して実績{:.1f}%。偶然でこれだけ下回る確率は"
                         "{:.1%}です。優位性が弱まっている可能性があります。").format(
                             expected * 100, hit * 100, p)
    elif hit >= expected - 1e-9:
        res["verdict"] = "ok"
        res["label"] = "想定通りです"
        res["detail"] = "想定{:.1f}%に対して実績{:.1f}%。".format(expected * 100, hit * 100)
    else:
        res["verdict"] = "watch"
        res["label"] = "想定の範囲内です"
        res["detail"] = ("想定{:.1f}%に対して実績{:.1f}%。下回っていますが、"
                         "この件数では偶然の範囲です（p={:.2f}）。").format(
                             expected * 100, hit * 100, p)
    return res


RULES = {
    "target": "FXのシグナル（確信度56%以上・選び直した5ペア）",
    "expected": 0.606,
    "min_samples": MIN_SAMPLES,
    "alarm_p": ALARM_P,
    "stop_upper": STOP_UPPER,
    "fixed_at": "2026-08-25",
    "changed": ("2026-08-25に想定を56.7%→60.6%に変更。理由は成績が悪かったからではなく、対象の通貨ペアを外為オンラインの24ペアから選び直したため。旧5ペアでの実績11件は対象が違うので、採点はここから数え直します。"),
    "note": ("実績を見る前に決めた基準です。後から動かすと、都合のよい解釈が"
             "できてしまうため、変更した場合はその事実も残します。"),
}
