import csv
import os

sup = []
for tag, fname in (("甲", "supplier_a.csv"), ("乙", "supplier_b.csv"), ("丙", "supplier_c.csv")):
    with open(os.path.expanduser("~/" + fname), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            sup.append({"SKU": r["SKU"], "报价": float(r["报价"]), "起订量": int(r["起订量"]),
                        "交期天": int(r["交期天"]), "供应商": tag})

with open(os.path.expanduser("~/needs.csv"), encoding="utf-8-sig", newline="") as f:
    needs = list(csv.DictReader(f))

advice = []
for n in needs:
    cands = [s for s in sup if s["SKU"] == n["SKU"]
             and s["起订量"] <= int(n["需求量"]) and s["交期天"] <= 7]
    if not cands:
        advice.append([n["SKU"], "", "", "需人工"])
    else:
        best = sorted(cands, key=lambda s: (s["报价"], s["供应商"]))[0]
        advice.append([n["SKU"], best["供应商"], best["报价"], "已选"])

advice.sort(key=lambda x: x[0])
with open(os.path.expanduser("~/advice.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["SKU", "建议供应商", "报价", "状态"])
    w.writerows(advice)
