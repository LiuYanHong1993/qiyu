import csv
import os
from datetime import date


def load(p):
    with open(os.path.expanduser(p), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


expenses, banks = load("~/expense.csv"), load("~/bank.csv")
used, unmatched_e = set(), []
for e in expenses:
    best, bestd = None, 2
    for b in banks:
        if b["流水号"] in used or float(b["金额"]) != float(e["金额"]):
            continue
        diff = abs((date.fromisoformat(b["日期"]) - date.fromisoformat(e["日期"])).days)
        if diff <= 1 and diff < bestd:
            best, bestd = b, diff
    if best is None:
        unmatched_e.append([e["行号"], e["报销人"], e["金额"], e["日期"], "无匹配流水"])
    else:
        used.add(best["流水号"])

unmatched_e.sort(key=lambda x: int(x[0]))
unmatched_b = [[b["行号"], b["流水号"], b["金额"], b["日期"], "无匹配报销"]
               for b in banks if b["流水号"] not in used]
unmatched_b.sort(key=lambda x: int(x[0]))

with open(os.path.expanduser("~/unmatched_expense.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["行号", "报销人", "金额", "日期", "原因"])
    w.writerows(unmatched_e)
with open(os.path.expanduser("~/unmatched_bank.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["行号", "流水号", "金额", "日期", "原因"])
    w.writerows(unmatched_b)
