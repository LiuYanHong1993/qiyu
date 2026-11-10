import csv
import os
from decimal import Decimal, ROUND_HALF_UP

cur = Decimal("8")
with open(os.path.expanduser("~/sales_weekly.csv"), encoding="utf-8-sig", newline="") as f:
    allrows = list(csv.DictReader(f))
w7 = {r["区域"]: Decimal(r["金额"]) for r in allrows if Decimal(r["周"]) == cur - 1}
w8 = {r["区域"]: Decimal(r["金额"]) for r in allrows if Decimal(r["周"]) == cur}

anomalies, fresh = [], []
for region, amt8 in w8.items():
    amt7 = w7.get(region, Decimal(0))
    if amt7 == 0:
        fresh.append([region, "0", str(amt8), "新增", "新增", Decimal(-1)])
        continue
    rate = ((amt8 - amt7) / amt7).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if abs(rate) > Decimal("0.5") and amt8 > Decimal("10000"):
        anomalies.append([region, str(amt7), str(amt8), str(rate),
                          "暴涨" if rate > 0 else "暴跌", abs(rate)])

rows = sorted(anomalies + fresh, key=lambda x: (-x[5], x[0]))
with open(os.path.expanduser("~/anomaly.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["区域", "上周", "本周", "变化率", "类型"])
    for r in rows:
        w.writerow(r[:5])

n = len(rows)
mx = max((x[5] for x in anomalies), default=Decimal(0))
with open(os.path.expanduser("~/summary.txt"), "w", encoding="utf-8") as f:
    f.write(f"异常区域 {n} 个，最大波动 {mx}")
