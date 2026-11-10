import csv
import json
import os
from datetime import date

import requests

today = date(2024, 6, 15)  # 本次运行参数：today=2024-06-15
url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=qiyu-mock"

rows = []
with open(os.path.expanduser("~/customers.csv"), encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        days = (today - date.fromisoformat(r["最后跟进日期"])).days
        if days > 14:
            rows.append((r["客户"], r["负责人"], r["最后跟进日期"], days))
rows.sort(key=lambda x: -x[3])

with open(os.path.expanduser("~/followup.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["客户", "负责人", "最后跟进日期", "超期天数"])
    for 客户, 负责人, 日期, days in rows:
        w.writerow([客户, 负责人, 日期, days])
        requests.post(url, json={"msgtype": "text",
                                 "text": {"content": f"客户 {客户} 已超期 {days} 天，负责人 {负责人}，请尽快跟进"}})
