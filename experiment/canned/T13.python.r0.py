import csv
import os
from datetime import datetime


def load(p):
    with open(os.path.expanduser(p), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


rows = load("~/dirty.csv")
clean, seen = [], set()
report = {"金额-格式修正": 0, "日期-格式修正": 0, "品名-去空格": 0}
for r in rows:
    name = r["品名"].strip()
    city = r["城市"].strip()
    if r["品名"] != name:
        report["品名-去空格"] += 1
    amt = r["金额"].strip()
    if amt == "":
        amt_out = ""
    else:
        std = amt.replace("¥", "").replace(",", "")
        if std != amt:
            report["金额-格式修正"] += 1
        amt_out = std
    d = r["日期"].strip()
    if d == "":
        date_out = ""
    else:
        date_out = d
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                date_out = datetime.strptime(d, fmt).date().isoformat()
                break
            except ValueError:
                pass
        if date_out != d:
            report["日期-格式修正"] += 1
    key = (name, date_out, amt_out, city)
    if key in seen:
        continue
    seen.add(key)
    clean.append([name, date_out, amt_out, city])

dedup = len(rows) - len(clean)
with open(os.path.expanduser("~/clean.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["品名", "日期", "金额", "城市"])
    w.writerows(clean)

report_rows = [["金额", "格式修正", report["金额-格式修正"]],
               ["日期", "格式修正", report["日期-格式修正"]],
               ["品名", "去空格", report["品名-去空格"]],
               ["全表", "去重", dedup]]
with open(os.path.expanduser("~/report.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["列名", "操作", "数量"])
    for row in report_rows:
        if row[2] > 0:
            w.writerow(row)
