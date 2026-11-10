import csv
import os
from datetime import date, timedelta

rows = []
with open(os.path.expanduser("~/shifts.csv"), encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        rows.append((r["姓名"], r["日期"], r["班次"]))
rows.sort(key=lambda x: (x[0], x[1]))

violations = []
prev_name, prev_date, streak = "", "", 1
for name, d, _ in rows:
    if name == prev_name:
        if d == prev_date:
            violations.append(["双班", name, d, "同日多个班次"])
        elif date.fromisoformat(d) - date.fromisoformat(prev_date) == timedelta(days=1):
            streak += 1
            if streak == 7:
                first = (date.fromisoformat(d) - timedelta(days=6)).isoformat()
                violations.append(["连班", name, first, "连续 7 天以上有班"])
        else:
            streak = 1
    else:
        streak = 1
    prev_name, prev_date = name, d

violations.sort(key=lambda x: (x[0], x[1], x[2]))
with open(os.path.expanduser("~/violations.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["类型", "姓名", "日期", "说明"])
    w.writerows(violations)
