"""Backfill and update the embedded daily snapshot in index.html."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

NOW = datetime.now(timezone.utc)
PAGE = Path(__file__).with_name("index.html")
MARKER = "<!-- SNAPSHOT -->"
TAG = '<script type="application/json" id="snapshot">'
START_YEARS = {"^GSPC": 1927, "^IXIC": 1970, "^SOX": 1994, "^TWII": 1997,
               "2330.TW": 2000, "0050.TW": 2009, "GC=F": 2000, "BTC-USD": 2014}

def get_json(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=25) as response:
        return json.load(response)

GOLD_CSV = "https://www.goldprice.com/gold-price-history.csv"

def gold_rows(lines):
    rows = {}
    records = csv.DictReader(line for line in lines if line.strip() and not line.startswith("#"))
    for row in records:
        day = datetime.fromisoformat(row["date"])
        close = float(row["close_usd_per_troy_oz"])
        if day.weekday() < 5 and day.date() < NOW.date() and close > 0:
            rows[day.date().isoformat()] = close
    if len(rows) < 14000 or min(rows)[:4] != "1968":
        raise ValueError("incomplete GoldPrice.com history")
    return rows

def spot_gold():
    request = Request(GOLD_CSV, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=25) as response:
        return gold_rows(response.read().decode("utf-8-sig").splitlines())

def january(year):
    return int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())

def yahoo(job):
    symbol, start, end = job
    encoded = quote(symbol, safe="")
    errors = []
    for host in ("query2", "query1"):
        try:
            url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{encoded}"
                   f"?period1={start}&period2={end}&interval=1d")
            result = get_json(url)["chart"]["result"][0]
            if result["meta"]["dataGranularity"] != "1d":
                raise ValueError("daily candles were not returned")
            zone = ZoneInfo(result["meta"]["exchangeTimezoneName"])
            today = NOW.astimezone(zone).date().isoformat()
            closes = result["indicators"]["quote"][0]["close"]
            rows = {}
            for stamp, close in zip(result["timestamp"], closes, strict=True):
                day = datetime.fromtimestamp(stamp, zone).date().isoformat()
                if start <= stamp < end and day < today and close is not None and close > 0:
                    rows[day] = round(close, 6)
            if not rows:
                raise ValueError("no daily closes")
            return symbol, rows
        except (OSError, KeyError, ValueError, TypeError, IndexError) as error:
            errors.append(str(error))
    raise RuntimeError(f"{symbol} {start}–{end}: {errors}")

def early_bitcoin():
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
           "?assets=btc&metrics=PriceUSD&start_time=2010-01-01&end_time=2014-12-31&page_size=1000")
    rows = {}
    while url:
        result = get_json(url)
        rows.update({item["time"][:10]: float(item["PriceUSD"]) for item in result["data"] if item.get("PriceUSD")})
        url = result.get("next_page_url")
    if len(rows) < 1400 or "2010-12-31" not in rows or "2014-12-31" not in rows:
        raise ValueError("incomplete Coin Metrics BTC history")
    return rows

if __name__ == "__main__":
    before, snapshot, after = PAGE.read_text(encoding="utf-8").split(MARKER)
    assets = json.loads(snapshot.removeprefix(TAG).removesuffix("</script>"))
    jobs = []
    for asset in assets:
        symbol = asset["symbol"]
        if symbol == "XAUUSD":
            continue
        first = int(asset["rows"][0][0][:4])
        for year in range(START_YEARS[symbol], first, 10):
            jobs.append((symbol, january(year), january(min(year+10, first+1))))
        latest = datetime.fromisoformat(asset["rows"][-1][0]).replace(tzinfo=timezone.utc)
        if int(NOW.timestamp()-latest.timestamp()) > 86400:
            jobs.append((symbol, int(latest.timestamp()), int(NOW.timestamp())))
    extended = defaultdict(dict)
    with ThreadPoolExecutor(max_workers=10) as pool:
        bitcoin = next(asset for asset in assets if asset["symbol"] == "BTC-USD")
        btc = pool.submit(early_bitcoin) if bitcoin["rows"][0][0] > "2010-12-31" else None
        gold = pool.submit(spot_gold) if any(asset["symbol"] == "XAUUSD" for asset in assets) else None
        for job, task in [(job,pool.submit(yahoo,job)) for job in jobs]:
            try:
                symbol, rows = task.result()
                extended[symbol].update(rows)
            except RuntimeError as error:
                print(error, flush=True)
        if gold:
            try:
                extended["XAUUSD"].update(gold.result())
            except (OSError, ValueError, KeyError) as error:
                print(f"GoldPrice.com update skipped: {error}", flush=True)
        if btc:
            try:
                extended["BTC-USD"].update(btc.result())
            except (OSError, ValueError, KeyError) as error:
                print(f"Coin Metrics backfill skipped: {error}", flush=True)
    for asset in assets:
        symbol = asset["symbol"]
        old = dict(asset["rows"])
        new = extended[symbol]
        if symbol == "BTC-USD" and btc and "2010-12-31" in new:
            old = {day: close for day, close in old.items() if day >= "2015-01-01"}
        ordered = sorted((new | old).items())
        asset["rows"] = ordered
        print(symbol, ordered[0][0], ordered[-1][0], len(ordered), flush=True)
    payload = json.dumps(assets, ensure_ascii=False, separators=(",", ":"))
    temp = PAGE.with_suffix(".tmp")
    temp.write_text(MARKER.join((before, TAG+payload+"</script>", after)), encoding="utf-8")
    temp.replace(PAGE)
