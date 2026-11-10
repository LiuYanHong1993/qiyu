import csv
import json
import os
from decimal import Decimal, ROUND_HALF_UP

import requests

qf = os.path.expanduser("~/quotes_usd.csv")
cf = os.path.expanduser("~/缓存/rate.json")
out = os.path.expanduser("~/quotes_cny.csv")
os.makedirs(os.path.dirname(out), exist_ok=True)

rate, rate_date = None, None
if os.path.exists(cf):
    with open(cf, encoding="utf-8") as f:
        c = json.load(f)
    rate, rate_date = Decimal(c["rate"]), c["date"]
if rate is None:
    data = requests.get("https://api.ex.com/rate?from=USD&to=CNY").json()
    rate, rate_date = Decimal(data["rate"]), data["date"]
    os.makedirs(os.path.dirname(cf), exist_ok=True)  # ← r0 漏了这行：缓存目录不存在
    with open(cf, "w", encoding="utf-8") as f:
        json.dump({"rate": str(rate), "date": rate_date}, f, ensure_ascii=False)

with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["客户", "产品", "金额CNY"])
    with open(qf, encoding="utf-8-sig", newline="") as src:
        for r in csv.DictReader(src):
            amt = (Decimal(r["金额USD"]) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            w.writerow([r["客户"], r["产品"], str(amt)])
