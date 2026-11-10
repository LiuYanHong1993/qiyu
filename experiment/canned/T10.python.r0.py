import calendar
import csv
import os
import smtplib
from datetime import date

today = date(2024, 6, 15)  # 本次运行参数：today=2024-06-15


def add_months(dt, m):
    total = dt.month - 1 + m
    y, mo = dt.year + total // 12, total % 12 + 1
    return date(y, mo, min(dt.day, calendar.monthrange(y, mo)[1]))


rows = []
with open(os.path.expanduser("~/contracts.csv"), encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        unit = 12 if r["单位"] == "年" else 1
        end = add_months(date.fromisoformat(r["签约日"]), int(r["期限"]) * unit)
        days = (end - today).days
        if 0 <= days <= 30:
            rows.append([r["合同名"], r["签约日"], r["期限"], r["单位"], end.isoformat(), days])
rows.sort(key=lambda x: x[5])

with open(os.path.expanduser("~/expiring.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["合同名", "签约日", "期限", "单位", "到期日", "剩余天数"])
    w.writerows(rows)

msg = ("From: bot@company.com\r\n"
       "To: legal@company.com\r\n"
       "Subject: 合同到期预警\r\n"
       "Content-Type: text/plain; charset=utf-8\r\n"
       "\r\n"
       f"30 天内到期合同 {len(rows)} 份，明细见 expiring.csv\r\n")
with smtplib.SMTP("mock.local") as s:
    s.sendmail("bot@company.com", ["legal@company.com"], msg)
