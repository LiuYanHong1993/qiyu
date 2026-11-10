import csv
import os
from decimal import Decimal

with open(os.path.expanduser("~/inventory.csv"), encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

out = []
for r in rows:
    x, y = Decimal(r["现库存"]), Decimal(r["安全库存"])
    if x < y:
        out.append([r["SKU"], r["名称"], str(x), str(y), str(y - x)])
out.sort(key=lambda r: (-int(Decimal(r[4])), r[0]))

with open(os.path.expanduser("~/replenish.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["SKU", "名称", "现库存", "安全库存", "缺口"])
    w.writerows(out)
