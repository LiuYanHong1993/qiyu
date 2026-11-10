import csv
import os
import re


def load(p):
    with open(os.path.expanduser(p), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def norm(p):
    return re.sub(r"[+\-\s]", "", p)[-11:]


a = {norm(r["手机号"]): r for r in load("~/crm_a.csv")}
b = {norm(r["手机号"]): r for r in load("~/crm_b.csv")}


def fuller(r):
    return sum(1 for k in ("客户名", "公司", "邮箱") if (r.get(k) or "").strip())


cust, conf = [], []
for p in sorted(set(a) | set(b)):
    ra, rb = a.get(p), b.get(p)
    if ra and rb and ra["客户名"] != rb["客户名"]:
        conf.append([p, ra["客户名"], rb["客户名"]])
    keep = ra if ra and (not rb or fuller(ra) >= fuller(rb)) else rb
    cust.append([p, keep["客户名"], keep.get("公司") or "", keep.get("邮箱") or ""])

with open(os.path.expanduser("~/customers.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["手机号", "客户名", "公司", "邮箱"])
    w.writerows(cust)

with open(os.path.expanduser("~/conflicts.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["手机号", "crm_a客户名", "crm_b客户名"])
    w.writerows(conf)
