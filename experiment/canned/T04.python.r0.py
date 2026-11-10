import csv
import os
import smtplib
from decimal import Decimal

week = "2024-W23"
src = os.path.expanduser("~/销售数据/本周-" + week + ".csv")
out = os.path.expanduser("~/周报/销售周报.csv")
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

msg = ("From: bot@company.com\r\n"
       "To: manager@company.com\r\n"
       "Subject: 销售周报（" + week + "）\r\n"
       "Content-Type: text/plain; charset=utf-8\r\n"
       "\r\n"
       "本周销售周报已生成，附件=销售周报.csv\r\n")
with smtplib.SMTP("mock.local") as s:
    s.sendmail("bot@company.com", ["manager@company.com"], msg)
