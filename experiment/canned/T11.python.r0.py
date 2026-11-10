import csv
import os
from decimal import Decimal

import requests

orders = {}
page = 1
while True:
    data = requests.get(f"https://api.shop.com/orders?page={page}&size=100").json()
    for o in data["orders"]:
        orders[o["订单号"]] = Decimal(o["金额"])
    if not data["has_more"]:
        break
    page += 1

ship = {}
with open(os.path.expanduser("~/shipments.csv"), encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        ship[r["订单号"]] = Decimal(r["金额"])

rank = {"平台多": 0, "本地多": 1, "金额不一致": 2}
rows = []
for oid, amt in orders.items():
    if oid not in ship:
        rows.append((0, oid, "平台多", amt, ""))
for oid, amt in ship.items():
    if oid not in orders:
        rows.append((1, oid, "本地多", "", amt))
    elif orders[oid] != amt:
        rows.append((2, oid, "金额不一致", orders[oid], amt))
rows.sort(key=lambda x: (x[0], x[1]))

with open(os.path.expanduser("~/reconcile.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["订单号", "类型", "平台金额", "本地金额"])
    for _, oid, ty, pa, la in rows:
        w.writerow([oid, ty, "" if pa == "" else str(pa), "" if la == "" else str(la)])
