import csv
import os
from decimal import Decimal

src = os.path.expanduser("~/销售明细/销售明细-2024-06-01.csv")
out = os.path.expanduser("~/日报/日报.csv")
os.makedirs(os.path.dirname(out), exist_ok=True)

agg = {}
with open(src, encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        a = agg.setdefault(r["区域"], [0, 0, Decimal("0")])
        a[0] += 1
        a[1] += int(r["数量"])
        a[2] += Decimal(r["金额"])

with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["区域", "订单数", "数量", "金额"])
    for k in sorted(agg):
        n, q, m = agg[k]
        w.writerow([k, n, q, str(m)])
