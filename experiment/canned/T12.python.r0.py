import csv
import os
import re
from datetime import datetime, timedelta

issue = datetime.strptime("2024-06-18", "%Y-%m-%d").date()  # 本次运行参数
effective = issue + timedelta(days=30)
eff_text = f"{effective.year}年{effective.month}月{effective.day}日"
out_dir = os.path.expanduser("~/报价单")
os.makedirs(out_dir, exist_ok=True)

with open(os.path.expanduser("~/报价模板.md"), encoding="utf-8") as f:
    template = f.read()

with open(os.path.expanduser("~/clients.csv"), encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        safe = re.sub(r'[/\\:*?"<>|]', "_", r["客户名"])
        text = template.replace("{{客户名}}", r["客户名"])
        text = text.replace("{{金额}}", r["金额"])
        text = text.replace("{{有效期}}", eff_text)
        with open(os.path.join(out_dir, f"{safe}-报价单.md"), "w", encoding="utf-8") as g:
            g.write(text)
