# -*- coding: utf-8 -*-
"""イベント情報。決算日と配当。

1か月先を予測するとき、その期間に決算をまたぐかどうかで話がまったく違う。
決算は数％〜数十％動く一発勝負なので、テクニカルの延長では読めない。
「またぐ」ことが分かるだけでも判断材料になる。

  決算日 … Nasdaq の決算カレンダー（米国株のみ・無料・キー不要）
  配当   … Yahoo の配当履歴から直近12か月の配当利回りを計算

日本株の決算日は無料で安定して取れる先が見つからなかったため未対応。
PER・PBR などの指標も、Yahoo の該当APIが認証必須になったため取得できない。
"""
import datetime
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import sources

NASDAQ_URL = "https://api.nasdaq.com/api/calendar/earnings?date={}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
      "Accept": "application/json"}


def _fetch_day(date_str):
    try:
        req = urllib.request.Request(NASDAQ_URL.format(date_str), headers=UA)
        raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        d = json.loads(raw)
        rows = ((d.get("data") or {}).get("rows")) or []
        return [r.get("symbol") for r in rows if r.get("symbol")]
    except Exception:
        return []


def earnings_calendar(days=35, use_cache=True):
    """これから days 日分の決算予定を {ティッカー: 日付} で返す。"""
    def _do():
        today = datetime.date.today()
        dates = []
        for i in range(days):
            d = today + datetime.timedelta(days=i)
            if d.weekday() < 5:
                dates.append(d.isoformat())
        out = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            for ds, syms in zip(dates, ex.map(_fetch_day, dates)):
                for sym in syms:
                    out.setdefault(sym.strip().upper(), ds)
        return out
    key = "earnings_{}_{}".format(datetime.date.today().isoformat(), days)
    return sources._cached(key, _do, use_cache) or {}


def dividend_yield(bars, price):
    """直近12か月の配当合計 ÷ 現在値。配当履歴がなければ None。"""
    divs = bars.get("dividends") or []
    if not divs or not price:
        return None
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=365)).timestamp()
    total = sum(amount for ts, amount in divs if ts >= cutoff)
    return (total / price) if total > 0 else None


def annotate(item, asset, calendar, due_ts):
    """銘柄に決算・配当の情報を付ける。

    due_ts は予測の期限。その日までに決算があるかどうかを見る。
    """
    code = item.get("code") or item.get("key")
    date_str = calendar.get(str(code).upper()) if calendar else None
    item["earnings_date"] = date_str
    item["earnings_in_horizon"] = False
    item["days_to_earnings"] = None
    if date_str:
        try:
            d = datetime.date.fromisoformat(date_str)
            days = (d - datetime.date.today()).days
            item["days_to_earnings"] = days
            due = datetime.date.fromtimestamp(due_ts)
            item["earnings_in_horizon"] = d <= due
        except Exception:
            pass
    item["dividend_yield"] = dividend_yield(asset["bars"], asset["price"])
    return item
