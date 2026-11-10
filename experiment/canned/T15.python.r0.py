import csv
import json
import os


def load(p, col):
    with open(os.path.expanduser(p), encoding="utf-8-sig", newline="") as f:
        return {r["月份"]: float(r[col]) for r in csv.DictReader(f)}


targets = {m: v * 10000 for m, v in load("~/targets.csv", "目标额").items()}  # 万元→元
actuals = load("~/actuals.csv", "实际额")
payments = load("~/payments.csv", "回款额")

months = sorted(set(targets) | set(actuals) | set(payments))
kpi = []
for m in months:
    tg = targets.get(m)
    ac = actuals.get(m, 0)
    pay = payments.get(m, 0)
    if tg is None or tg == 0:
        kpi.append({"月份": m, "目标额_元": None, "实际额_元": int(ac) if ac == int(ac) else ac,
                    "完成率": None, "回款率": None})
    else:
        kpi.append({"月份": m, "目标额_元": int(tg) if tg == int(tg) else tg,
                    "实际额_元": int(ac) if ac == int(ac) else ac,
                    "完成率": round(ac / tg, 4), "回款率": round(pay / tg, 4)})

with open(os.path.expanduser("~/kpi.json"), "w", encoding="utf-8") as f:
    json.dump({"月份": kpi}, f, ensure_ascii=False, indent=2)
    f.write("\n")
