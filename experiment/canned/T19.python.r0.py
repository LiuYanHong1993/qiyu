import csv
import json
import os

with open(os.path.expanduser("~/inbox.json"), encoding="utf-8") as f:
    inbox = json.load(f)

archive = os.path.expanduser("~/归档")
register = []
for mail in inbox:
    if "对账单" not in mail["主题"]:
        continue
    domain = mail["发件人"].split("@")[1]
    ts = mail["日期"][11:19].replace(":", "")
    for att in mail.get("附件", []):
        target = os.path.join(archive, domain, att["文件名"])
        if os.path.exists(target):
            stem, _, ext = att["文件名"].rpartition(".")
            target = os.path.join(archive, domain, f"{stem}_{ts}.{ext}")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as g:
            g.write(att["内容"])
        register.append([mail["发件人"], mail["主题"], target])

register = [[s, t, os.path.relpath(p, os.path.expanduser("~")).replace("\\", "/")]
            for s, t, p in register]
register.sort(key=lambda x: x[2])
with open(os.path.expanduser("~/register.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["发件人", "主题", "保存路径"])
    w.writerows(register)
