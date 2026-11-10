import csv
import os
from datetime import date

today = date(2024, 6, 15)  # 本次运行参数：today=2024-06-15


def tag(days, consume):
    if days > 365:
        return "沉睡"
    if consume >= 100000:
        return "VIP"
    if consume >= 10000:
        return "重要"
    return "普通"


rows, segments = [], {}
with open(os.path.expanduser("~/customers.csv"), encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        days = (today - date.fromisoformat(r["最近消费日"])).days
        t = tag(days, int(r["年度消费"]))
        rows.append([r["客户"], r["年度消费"], r["最近消费日"], t])
        segments[t] = segments.get(t, 0) + 1

rows.sort(key=lambda x: x[0])
with open(os.path.expanduser("~/customers_tagged.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["客户", "年度消费", "最近消费日", "标签"])
    w.writerows(rows)

with open(os.path.expanduser("~/segments.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["标签", "客户数"])
    for k in sorted(segments):
        w.writerow([k, segments[k]])
