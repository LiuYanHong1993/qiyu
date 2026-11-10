import json
import os

with open(os.path.expanduser("~/leads.json"), encoding="utf-8") as f:
    leads = json.load(f)

stages = ["线索", "意向", "方案", "成交"]
total_leads = sum(1 for x in leads if x["阶段"] == "线索")
funnel = []
for s in stages:
    grp = [x for x in leads if x["阶段"] == s]
    funnel.append({"阶段": s, "客户数": len(grp),
                   "金额合计": sum(int(x["金额"]) for x in grp),
                   "转化率": round(len(grp) / total_leads, 2)})

with open(os.path.expanduser("~/funnel.json"), "w", encoding="utf-8") as f:
    json.dump({"阶段": funnel}, f, ensure_ascii=False, indent=2)
    f.write("\n")
