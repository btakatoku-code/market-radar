# -*- coding: utf-8 -*-
"""売買コストの計算。

予測が +1% でも、往復のコストが 1.4% なら実質マイナス。
予測値だけを見せるのは判断材料として不十分なので、
必ず「コストを引いたあとの期待値」を併記する。

PayPay証券の実際のコスト（公式の取引ルールより）:
  日本株・国内ETF・REIT … 基準価格に対しスプレッド 0.5%（片道）
  米国株・米国ETF       … スプレッド 0.5%（現地9:30-16:00）/ 0.7%（それ以外）
                          加えて円貨と外貨の交換で 1米ドルあたり35銭（片道）
  ※ いずれも取引価格に含まれる形で、別途手数料はかからない

税金は利益に対して 20.315%（特定口座・源泉徴収あり）。
NISA口座なら非課税。回転コストとは性質が違うので分けて扱う。
"""
import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))

SPREAD_JP = 0.005            # 日本株・国内ETF・REIT（東証立会時間内）
SPREAD_US_REGULAR = 0.005    # 米国株・米国ETF（現地立会時間内）
SPREAD_US_OFF = 0.007        # 同上（時間外・予約注文）
FX_FEE_YEN = 0.35            # 1米ドルあたり35銭（片道）
TAX_RATE = 0.20315           # 譲渡益課税（特定口座）

JP_KINDS = ("jp_stock", "jp_etf", "jp_reit")
US_KINDS = ("us_stock", "us_etf")


def us_market_open(now=None):
    """米国の立会時間内か（日本時間）。夏時間は3月第2日曜〜11月第1日曜。"""
    now = now or datetime.datetime.now(JST)
    y = now.year
    # 夏時間の開始・終了（米国）を日本時間の日付として近似
    mar = datetime.date(y, 3, 8)
    dst_start = mar + datetime.timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime.date(y, 11, 1)
    dst_end = nov + datetime.timedelta(days=(6 - nov.weekday()) % 7)
    summer = dst_start <= now.date() <= dst_end
    h = now.hour + now.minute / 60.0
    # 夏時間 22:30〜翌5:00 / 冬時間 23:30〜翌6:00（日本時間）
    lo, hi = (22.5, 5.0) if summer else (23.5, 6.0)
    return h >= lo or h < hi


def one_way(kind, usdjpy=None, in_hours=None):
    """片道のコスト（価格に対する比率）。取扱いのない資産は None。"""
    if kind in JP_KINDS:
        return SPREAD_JP
    if kind in US_KINDS:
        if in_hours is None:
            in_hours = us_market_open()
        spread = SPREAD_US_REGULAR if in_hours else SPREAD_US_OFF
        fx = (FX_FEE_YEN / usdjpy) if usdjpy else 0.0
        return spread + fx
    return None


def round_trip(kind, usdjpy=None, in_hours=None):
    """往復のコスト。買って売るまでに必ずかかる。"""
    c = one_way(kind, usdjpy, in_hours)
    return None if c is None else c * 2


def breakdown(kind, usdjpy=None, in_hours=None):
    """内訳つきで返す（アプリでの説明用）"""
    if kind in JP_KINDS:
        return {"tradable": True, "spread": SPREAD_JP, "fx": 0.0,
                "one_way": SPREAD_JP, "round_trip": SPREAD_JP * 2,
                "in_hours": True,
                "note": "日本株のスプレッド0.5%（片道）"}
    if kind in US_KINDS:
        if in_hours is None:
            in_hours = us_market_open()
        spread = SPREAD_US_REGULAR if in_hours else SPREAD_US_OFF
        fx = (FX_FEE_YEN / usdjpy) if usdjpy else 0.0
        return {"tradable": True, "spread": spread, "fx": fx,
                "one_way": spread + fx, "round_trip": (spread + fx) * 2,
                "in_hours": in_hours,
                "note": "米国株のスプレッド{:.1f}%＋為替35銭（片道）{}".format(
                    spread * 100, "" if in_hours else "／いまは時間外の料率")}
    return {"tradable": False, "spread": None, "fx": None,
            "one_way": None, "round_trip": None, "in_hours": None,
            "note": "PayPay証券では取扱いがないため、コストは試算していません"}


def net_return(gross, kind, usdjpy=None, in_hours=None):
    """コストを引いたあとの期待リターン。取扱いがなければ gross をそのまま返す。"""
    rt = round_trip(kind, usdjpy, in_hours)
    return gross if rt is None else gross - rt


def after_tax(net, nisa=False):
    """利益が出た場合の税引き後。損失には課税されない。"""
    if nisa or net <= 0:
        return net
    return net * (1 - TAX_RATE)


def breakeven(kind, usdjpy=None, in_hours=None):
    """コストを取り返すのに必要な上昇率"""
    return round_trip(kind, usdjpy, in_hours)


def hold_months_to_justify(gross_monthly, kind, usdjpy=None, in_hours=None):
    """1か月の期待リターンに対し、コストを回収するのに何か月保有が必要か。

    回転が速いほどコスト負けする、という関係を数字で示すために使う。
    """
    rt = round_trip(kind, usdjpy, in_hours)
    if rt is None or gross_monthly is None or gross_monthly <= 0:
        return None
    return rt / gross_monthly
