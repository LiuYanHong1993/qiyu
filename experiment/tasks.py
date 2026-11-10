# -*- coding: utf-8 -*-
"""实验任务注册表 + 判定器。

判定器与生成器隔离：本文件（以及 fixtures）不进入任何生成上下文。
判定器统一签名 judge(root: Path, recs: list, diffs: list)：
  root  = 本次运行的沙箱根；recs = 外设审计记录（两语言已对齐格式）
  diffs = 每次执行后的文件变动（相对沙箱根的 relpath 列表）
判定一律"从源数据重算期望值"，不硬编码结果（T14 类构造题除外，暂未收录）。
"""
import calendar
import csv
import json
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

QY = Path(__file__).resolve().parent.parent


def d(x):
    return Decimal(str(x))


# ---------------------------------------------------------------- DSL
def _typed(s):
    s = (s or "").strip()
    return Decimal(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else s


def rows_of(root, rel):
    with open(root / rel, encoding="utf-8-sig", newline="") as f:
        return [{k: _typed(v) for k, v in r.items()} for r in csv.DictReader(f)]


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _cell_eq(got, want, tol="0.01"):
    if isinstance(want, Decimal):
        try:
            g = Decimal(str(got))
        except Exception:
            raise AssertionError(f"应为数字 {want}，实际 {got!r}")
        expect(abs(g - want) <= Decimal(tol), f"应为 {want}，实际 {got}")
    else:
        expect(str(got) == str(want), f"应为 {want!r}，实际 {got!r}")


def table_equal(rows, columns, expected, order=True, tol="0.01"):
    expect(rows, "输出文件为空")
    got_cols = list(rows[0].keys())
    expect(got_cols == columns, f"表头应为 {columns}，实际 {got_cols}")
    expect(len(rows) == len(expected), f"行数应为 {len(expected)}，实际 {len(rows)}")
    if not order:
        rows = sorted(rows, key=lambda r: str(r[columns[0]]))
        expected = sorted(expected, key=lambda r: str(r[0]))
    for i, (r, e) in enumerate(zip(rows, expected)):
        for c, v in zip(columns, e):
            try:
                _cell_eq(r[c], v, tol)
            except AssertionError as ex:
                raise AssertionError(f"第 {i + 1} 行 {c}: {ex}")


def recs_of(recs, kind):
    return [r for r in recs if r.get("种类") == kind]


def attach_evidence(r, name):
    return name in str(r.get("附件", "")) or name in str(r.get("内容", ""))


# ---------------------------------------------------------------- 判定器
def judge_T01(root, recs, diffs):
    src = rows_of(root, "销售明细/销售明细-2024-06-01.csv")
    agg = {}
    for r in src:
        a = agg.setdefault(r["区域"], [0, 0, Decimal(0)])
        a[0] += 1
        a[1] += int(r["数量"])
        a[2] += d(r["金额"])
    exp = [[k, Decimal(v[0]), Decimal(v[1]), v[2]] for k, v in sorted(agg.items())]
    table_equal(rows_of(root, "日报/日报.csv"), ["区域", "订单数", "数量", "金额"], exp)


def judge_T02(root, recs, diffs):
    def norm(p):
        return re.sub(r"[+\-\s]", "", str(p))[-11:]

    a = {norm(r["手机号"]): r for r in rows_of(root, "crm_a.csv")}
    b = {norm(r["手机号"]): r for r in rows_of(root, "crm_b.csv")}

    def fuller(r):
        return sum(1 for k in ("客户名", "公司", "邮箱") if str(r.get(k) or "").strip())

    exp, conflicts = [], []
    for p in sorted(set(a) | set(b)):
        ra, rb = a.get(p), b.get(p)
        if ra and rb and str(ra["客户名"]) != str(rb["客户名"]):
            conflicts.append([p, ra["客户名"], rb["客户名"]])
        keep = ra if ra and (not rb or fuller(ra) >= fuller(rb)) else rb
        exp.append([p, keep["客户名"], str(keep.get("公司") or ""), str(keep.get("邮箱") or "")])
    table_equal(rows_of(root, "customers.csv"), ["手机号", "客户名", "公司", "邮箱"], exp, order=False)
    table_equal(rows_of(root, "conflicts.csv"), ["手机号", "crm_a客户名", "crm_b客户名"],
                conflicts, order=False)


def judge_T03(root, recs, diffs):
    src = rows_of(root, "inventory.csv")
    exp = [[r["SKU"], r["名称"], d(r["现库存"]), d(r["安全库存"]), d(r["安全库存"]) - d(r["现库存"])]
           for r in src if d(r["现库存"]) < d(r["安全库存"])]
    exp.sort(key=lambda x: (-int(x[4]), x[0]))
    table_equal(rows_of(root, "replenish.csv"), ["SKU", "名称", "现库存", "安全库存", "缺口"], exp)


def judge_T04(root, recs, diffs):
    src = rows_of(root, "销售数据/本周-2024-W23.csv")
    agg = {}
    for r in src:
        a = agg.setdefault(r["区域"], [0, 0, Decimal(0)])
        a[0] += 1
        a[1] += int(r["数量"])
        a[2] += d(r["金额"])
    exp = [[k, Decimal(v[0]), Decimal(v[1]), v[2]] for k, v in agg.items()]
    table_equal(rows_of(root, "周报/销售周报.csv"), ["区域", "订单数", "数量", "金额"], exp, order=False)
    mail = recs_of(recs, "发邮件")
    expect(len(mail) == 1, f"邮件应恰好 1 封，实际 {len(mail)}")
    m = mail[0]
    expect(str(m.get("收件", "")) == "manager@company.com",
           f"收件人应为 manager@company.com，实际 {m.get('收件')}")
    expect("2024-W23" in str(m.get("主题", "")), f"主题应含周编号，实际 {m.get('主题')!r}")
    expect(attach_evidence(m, "销售周报.csv"), "附件证据缺失（应含 销售周报.csv）")


def judge_T07(root, recs, diffs):
    today = date(2024, 6, 15)
    exp = []
    for r in rows_of(root, "customers.csv"):
        days = (today - date.fromisoformat(str(r["最后跟进日期"]))).days
        if days > 14:
            exp.append([r["客户"], r["负责人"], r["最后跟进日期"], Decimal(days)])
    exp.sort(key=lambda x: -int(x[3]))
    table_equal(rows_of(root, "followup.csv"), ["客户", "负责人", "最后跟进日期", "超期天数"], exp)
    msgs = recs_of(recs, "发消息")
    expect(len(msgs) == len(exp), f"推送应 {len(exp)} 条，实际 {len(msgs)}")
    blob = json.dumps(msgs, ensure_ascii=False)
    for e in exp:
        expect(e[0] in blob and str(int(e[3])) in blob, f"缺推送内容：{e[0]}（{e[3]} 天）")


def judge_T08(root, recs, diffs):
    rate = Decimal("7.21")
    exp = [[r["客户"], r["产品"], (d(r["金额USD"]) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)]
           for r in rows_of(root, "quotes_usd.csv")]
    table_equal(rows_of(root, "quotes_cny.csv"), ["客户", "产品", "金额CNY"], exp, order=False)
    gets = [r for r in recs_of(recs, "请求") if "GET" in str(r.get("方法", "GET")).upper()]
    expect(len(gets) == 1, f"汇率 API 应恰好请求 1 次，实际 {len(gets)}")
    cache = root / "缓存" / "rate.json"
    expect(cache.exists(), "缺当日汇率缓存 ~/缓存/rate.json")
    expect("7.21" in cache.read_text(encoding="utf-8"), "缓存应含 rate=7.21")


def _pamt(i):
    if i == 12:
        return Decimal("59.80")
    return Decimal((i * 13) % 890 + 10).quantize(Decimal("0.01"))


def judge_T11(root, recs, diffs):
    orders = {f"ORD-{i:03d}": _pamt(i) for i in range(1, 251)}
    ship = {r["订单号"]: d(r["金额"]) for r in rows_of(root, "shipments.csv")}
    rows = []
    for oid, amt in orders.items():
        if oid not in ship:
            rows.append(["平台多", oid, amt, ""])
    for oid, amt in ship.items():
        if oid not in orders:
            rows.append(["本地多", oid, "", amt])
        elif orders[oid] != amt:
            rows.append(["金额不一致", oid, orders[oid], amt])
    rank = {"平台多": 0, "本地多": 1, "金额不一致": 2}
    rows.sort(key=lambda x: (rank[x[0]], x[1]))
    got = rows_of(root, "reconcile.csv")
    expect(len(got) == len(rows), f"行数应为 {len(rows)}，实际 {len(got)}")
    for g, e in zip(got, rows):
        expect(g["类型"] == e[0] and g["订单号"] == e[1], f"应为 {e}，实际 {g['类型']}/{g['订单号']}")
        if e[2] != "":
            _cell_eq(g["平台金额"], e[2], "0.001")
        if e[3] != "":
            _cell_eq(g["本地金额"], e[3], "0.001")
    gets = recs_of(recs, "请求")
    expect(len(gets) == 3, f"应恰好 3 页请求，实际 {len(gets)}")
    pages = []
    for r in gets:
        m = re.search(r"page=(\d+)", str(r.get("网址", "")))
        expect(m is not None, f"请求网址缺少 page 参数：{r.get('网址')}")
        pages.append(int(m.group(1)))
    expect(pages == [1, 2, 3], f"分页顺序应为 1,2,3，实际 {pages}")


def judge_T20(root, recs, diffs):
    expect(len(diffs) >= 2, "本任务需要两次运行（幂等考察）")
    d1, d2 = diffs[0], diffs[1]
    w = "备份/2024-06-07/"
    expect(sorted(d1) == sorted([w + "a.csv", w + "b.xlsx"]), f"第一次应恰好备份两个文件，实际 {d1}")
    expect(d2 == [], f"第二次应零复制（幂等），实际 {d2}")
    expect(all(".tmp" not in p for p in d1), ".tmp 不应被备份")


def judge_T10(root, recs, diffs):
    today = date.fromisoformat("2024-06-15")

    def add_m(dt, m):
        total = dt.month - 1 + m
        y, mo = dt.year + total // 12, total % 12 + 1
        return date(y, mo, min(dt.day, calendar.monthrange(y, mo)[1]))

    exp = []
    for r in rows_of(root, "contracts.csv"):
        unit = 12 if str(r["单位"]) == "年" else 1
        end = add_m(date.fromisoformat(str(r["签约日"])), int(r["期限"]) * unit)
        days = (end - today).days
        if 0 <= days <= 30:
            exp.append([r["合同名"], r["签约日"], r["期限"], r["单位"],
                        end.isoformat(), Decimal(days)])
    exp.sort(key=lambda x: x[5])  # 稳定排序，平局保持源顺序
    table_equal(rows_of(root, "expiring.csv"),
                ["合同名", "签约日", "期限", "单位", "到期日", "剩余天数"], exp)
    mail = recs_of(recs, "发邮件")
    expect(len(mail) == 1, f"邮件应恰好 1 封，实际 {len(mail)}")
    m = mail[0]
    expect(str(m.get("收件", "")) == "legal@company.com",
           f"收件人应为 legal@company.com，实际 {m.get('收件')}")
    expect("到期" in str(m.get("主题", "")), f"主题应含 到期，实际 {m.get('主题')!r}")


def judge_T05(root, recs, diffs):
    # 期望方案 = 按相对路径升序逐个处理（与 列目录 的排序一致）
    plan = [
        ("下载/京东_20240605_88.00.pdf", "归档/2024-06/京东/京东_20240605_88.00.pdf"),
        ("下载/德邦_2024-06-02_96.00.pdf", "归档/2024-06/德邦/德邦_2024-06-02_96.00.pdf"),
        ("下载/旧/顺丰_20240601_128.5.pdf", "归档/2024-06/顺丰/顺丰_20240601_128.5.pdf"),
        ("下载/顺丰_20240601_128.5.pdf", "归档/2024-06/顺丰/顺丰_20240601_128.5_2.pdf"),
    ]

    def norm(p):
        p = str(p)
        return p[2:] if p.startswith("~/") else p

    log = rows_of(root, "归档/archive_log.csv")
    expect(len(log) == len(plan), f"日志应 {len(plan)} 行，实际 {len(log)}")
    for i, (g, (src, dst)) in enumerate(zip(log, plan)):
        expect(list(g.keys()) == ["原路径", "新路径"], f"日志表头不符：{list(g.keys())}")
        expect(norm(g["原路径"]) == src, f"第 {i + 1} 行 原路径 应为 {src}，实际 {g['原路径']}")
        expect(norm(g["新路径"]) == dst, f"第 {i + 1} 行 新路径 应为 {dst}，实际 {g['新路径']}")
    for src, dst in plan:
        expect(not (root / src).exists(), f"源应已移走：{src}")
        expect((root / dst).is_file(), f"目标应存在：{dst}")
    expect((root / "下载/readme.txt").is_file(), "readme.txt 不应被移动")
    if diffs:
        moved = set(diffs[0])
        for _, dst in plan:
            expect(dst in moved, f"变动应包含 {dst}")
        expect(not any("readme" in p for p in moved), "readme.txt 不应出现在变动中")
    expect("旧目录数据" in (root / "归档/2024-06/顺丰/顺丰_20240601_128.5.pdf").read_text(encoding="utf-8"),
           "基础名应归属先处理的（子目录）文件")
    expect("平份数据" in (root / "归档/2024-06/顺丰/顺丰_20240601_128.5_2.pdf").read_text(encoding="utf-8"),
           "后处理的（平铺）文件应获得 _2 名")


def judge_T12(root, recs, diffs):
    clients = rows_of(root, "clients.csv")
    expect(len(diffs) >= 1, "应有文件变动")
    made = set(diffs[0])
    for r in clients:
        safe = re.sub(r'[/\\:*?"<>|]', "_", str(r["客户名"]))
        fn = f"报价单/{safe}-报价单.md"
        expect(fn in made, f"缺报价单：{fn}")
        text = (root / fn).read_text(encoding="utf-8")
        expect("{{" not in text, f"{fn} 占位符未替换干净")
        expect(str(r["客户名"]) in text, f"{fn} 缺客户名")
        expect(str(r["金额"]) in text, f"{fn} 缺金额")
        expect("2024年7月18日" in text, f"{fn} 有效期应为 2024年7月18日（2024-06-18 + 30 天）")
    expect(len(made) == len(clients), f"应恰好生成 {len(clients)} 个文件，实际 {sorted(made)}")


def judge_T17(root, recs, diffs):
    today = date.fromisoformat("2024-06-15")

    def tag(consume, last):
        days = (today - date.fromisoformat(str(last))).days
        if days > 365:
            return "沉睡"
        if consume >= 100000:
            return "VIP"
        if consume >= 10000:
            return "重要"
        return "普通"

    exp = []
    for r in rows_of(root, "customers.csv"):
        exp.append([r["客户"], r["年度消费"], r["最近消费日"],
                    tag(int(str(r["年度消费"])), r["最近消费日"])])
    table_equal(rows_of(root, "customers_tagged.csv"),
                ["客户", "年度消费", "最近消费日", "标签"], exp, order=False)
    cnt = {}
    for e in exp:
        cnt[e[3]] = cnt.get(e[3], 0) + 1
    table_equal(rows_of(root, "segments.csv"), ["标签", "客户数"],
                [[k, Decimal(v)] for k, v in sorted(cnt.items())], order=False)


def judge_T06(root, recs, diffs):
    exp_rows = rows_of(root, "expense.csv")
    bank_rows = rows_of(root, "bank.csv")
    used, pairs = set(), set()
    for e in exp_rows:
        best, bestd = None, 2
        for b in bank_rows:
            if b["流水号"] in used or d(b["金额"]) != d(e["金额"]):
                continue
            diff = abs((date.fromisoformat(str(b["日期"])) -
                        date.fromisoformat(str(e["日期"]))).days)
            if diff <= 1 and diff < bestd:
                best, bestd = b, diff
        if best is not None:
            used.add(best["流水号"])
            pairs.add(str(e["行号"]))
    unmatched_e = [r for r in exp_rows if str(r["行号"]) not in pairs]
    unmatched_b = [r for r in bank_rows if r["流水号"] not in used]

    got_e = rows_of(root, "unmatched_expense.csv")
    expect(len(got_e) == len(unmatched_e), f"未配报销应 {len(unmatched_e)} 行，实际 {len(got_e)}")
    for g, r in zip(got_e, unmatched_e):
        expect(str(g["行号"]) == str(r["行号"]), f"行号 {g['行号']} != {r['行号']}")
        expect(g["原因"] == "无匹配流水", f"原因应为 无匹配流水，实际 {g['原因']}")
    got_b = rows_of(root, "unmatched_bank.csv")
    expect(len(got_b) == len(unmatched_b), f"未配流水应 {len(unmatched_b)} 行，实际 {len(got_b)}")
    for g, r in zip(got_b, unmatched_b):
        expect(str(g["流水号"]) == str(r["流水号"]), f"流水号 {g['流水号']} != {r['流水号']}")
        expect(g["原因"] == "无匹配报销", f"原因应为 无匹配报销，实际 {g['原因']}")
    expect(len(pairs) * 2 + len(got_e) + len(got_b) == len(exp_rows) + len(bank_rows),
           "守恒关系破坏（配对+未匹配 != 总行数）")


def judge_T09(root, recs, diffs):
    with open(root / "funnel.json", encoding="utf-8") as f:
        data = json.load(f)
    expect(list(data.keys()) == ["阶段"], f"外层键应为 阶段，实际 {list(data.keys())}")
    rows = data["阶段"]
    leads = json.loads((root / "leads.json").read_text(encoding="utf-8"))
    total = sum(1 for x in leads if x["阶段"] == "线索")
    expect([r["阶段"] for r in rows] == ["线索", "意向", "方案", "成交"], "枚举顺序/补全不符")
    for r in rows:
        expect(list(r.keys()) == ["阶段", "客户数", "金额合计", "转化率"], f"行键不符：{list(r.keys())}")
        grp = [x for x in leads if x["阶段"] == r["阶段"]]
        expect(int(r["客户数"]) == len(grp), f"{r['阶段']} 客户数不符")
        expect(abs(Decimal(str(r["金额合计"])) - sum(Decimal(str(x["金额"])) for x in grp)) < Decimal("0.01"),
               f"{r['阶段']} 金额不符")
        expect(abs(Decimal(str(r["转化率"])) - Decimal(len(grp)) / Decimal(total)) < Decimal("0.01"),
               f"{r['阶段']} 转化率不符")


def judge_T13(root, recs, diffs):
    src = rows_of(root, "dirty.csv")
    exp_report = [("金额", "格式修正", 3), ("日期", "格式修正", 4),
                  ("品名", "去空格", 2), ("全表", "去重", 1)]
    got = rows_of(root, "report.csv")
    expect(list(got[0].keys()) == ["列名", "操作", "数量"], "报告表头不符")
    got_set = {(str(g["列名"]), str(g["操作"]), int(g["数量"])) for g in got}
    expect(got_set == set(exp_report), f"报告不符：{sorted(got_set)}")
    clean = rows_of(root, "clean.csv")
    seen, exp_rows = set(), []
    for r in src:
        row = (str(r["品名"]).strip(), str(r["日期"]).strip(),
               str(r["金额"]).strip(), str(r["城市"]).strip())
        if row in seen:
            continue
        seen.add(row)
        amt = row[2].replace("¥", "").replace(",", "")
        date_out = row[1]
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                from datetime import datetime as _dt
                date_out = _dt.strptime(date_out, fmt).date().isoformat()
                break
            except ValueError:
                pass
        exp_rows.append([row[0], date_out, amt if amt == "" else Decimal(amt), row[3]])
    table_equal(clean, ["品名", "日期", "金额", "城市"], exp_rows, order=False)
    expect(len(clean) == len(exp_rows), "去重后行数不符")


def judge_T14(root, recs, diffs):
    expected = [("双班", "王芳", "2024-02-20"), ("连班", "李强", "2024-02-25")]
    got = rows_of(root, "violations.csv")
    expect(list(got[0].keys()) == ["类型", "姓名", "日期", "说明"], "表头不符")
    expect(len(got) == len(expected), f"应 {len(expected)} 条违规，实际 {len(got)}")
    for g, e in zip(got, expected):
        expect((str(g["类型"]), str(g["姓名"]), str(g["日期"])) == e,
               f"应为 {e}，实际 {g['类型']}/{g['姓名']}/{g['日期']}")


def judge_T15(root, recs, diffs):
    with open(root / "kpi.json", encoding="utf-8") as f:
        data = json.load(f)
    expect(list(data.keys()) == ["月份"], "外层键应为 月份")
    rows = data["月份"]
    expect([r["月份"] for r in rows] ==
           ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"],
           "月份并集/升序不符")
    exp = {
        "2024-01": (1200000, 1000000, "0.8333", "0.6667"),
        "2024-02": (1500000, 1350000, "0.9", "0.8"),
        "2024-03": (None, 900000, None, None),
        "2024-04": (None, 500000, None, None),
        "2024-05": (1800000, 0, "0", "0"),
        "2024-06": (None, 800000, None, None),
    }
    for r in rows:
        expect(list(r.keys()) == ["月份", "目标额_元", "实际额_元", "完成率", "回款率"],
               f"行键不符：{list(r.keys())}")
        tg, ac, comp, pay = exp[str(r["月份"])]
        if tg is None:
            expect(r["目标额_元"] is None, f"{r['月份']} 目标额应为 null")
        else:
            expect(Decimal(str(r["目标额_元"])) == Decimal(tg), f"{r['月份']} 目标额不符")
        expect(Decimal(str(r["实际额_元"])) == Decimal(ac), f"{r['月份']} 实际额不符")
        for key, want in (("完成率", comp), ("回款率", pay)):
            if want is None:
                expect(r[key] is None, f"{r['月份']} {key} 应为 null")
            else:
                expect(abs(Decimal(str(r[key])) - Decimal(want)) < Decimal("0.0001"),
                       f"{r['月份']} {key} 应为 {want}，实际 {r[key]}")


def judge_T16(root, recs, diffs):
    sup = []
    for name in ("a", "b", "c"):
        tag = {"a": "甲", "b": "乙", "c": "丙"}[name]
        for r in rows_of(root, f"supplier_{name}.csv"):
            sup.append({"SKU": r["SKU"], "报价": d(r["报价"]), "起订量": int(r["起订量"]),
                        "交期天": int(r["交期天"]), "供应商": tag})
    needs = rows_of(root, "needs.csv")
    exp = []
    for n in needs:
        cands = [s for s in sup if s["SKU"] == str(n["SKU"])
                 and s["起订量"] <= int(n["需求量"]) and s["交期天"] <= 7]
        if not cands:
            exp.append([str(n["SKU"]), "", "", "需人工"])
        else:
            best = sorted(cands, key=lambda s: (s["报价"], s["供应商"]))[0]
            exp.append([str(n["SKU"]), best["供应商"], best["报价"], "已选"])
    table_equal(rows_of(root, "advice.csv"), ["SKU", "建议供应商", "报价", "状态"], exp)


def judge_T18(root, recs, diffs):
    src = rows_of(root, "sales_weekly.csv")
    cur = Decimal("8")
    w7 = {str(r["区域"]): d(r["金额"]) for r in src if Decimal(str(r["周"])) == cur - 1}
    w8 = {str(r["区域"]): d(r["金额"]) for r in src if Decimal(str(r["周"])) == cur}
    rows = []
    for region, amt8 in w8.items():
        amt7 = w7.get(region, Decimal(0))
        if amt7 == 0:
            rows.append([region, Decimal(0), amt8, "新增", "新增", Decimal(-1)])
            continue
        rate = ((amt8 - amt7) / amt7).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if abs(rate) > Decimal("0.5") and amt8 > Decimal("10000"):
            rows.append([region, amt7, amt8, rate,
                         "暴涨" if rate > 0 else "暴跌", abs(rate)])
    rows.sort(key=lambda x: (-x[5], x[0]))
    got = rows_of(root, "anomaly.csv")
    expect(list(got[0].keys()) == ["区域", "上周", "本周", "变化率", "类型"], "表头不符")
    expect(len(got) == len(rows), f"应 {len(rows)} 行，实际 {len(got)}")
    for g, e in zip(got, rows):
        expect(str(g["区域"]) == str(e[0]), f"顺序/区域不符：{g['区域']} != {e[0]}")
        expect(g["类型"] == e[4], f"{e[0]} 类型应为 {e[4]}")
        if e[4] != "新增":
            expect(abs(Decimal(str(g["变化率"])) - e[3]) < Decimal("0.001"),
                   f"{e[0]} 变化率应为 {e[3]}")
        else:
            expect(g["变化率"] == "新增", f"{e[0]} 变化率列应为 新增")
    summary = (root / "summary.txt").read_text(encoding="utf-8")
    n_new = sum(1 for e in rows if e[4] == "新增")
    n_anom = len(rows) - n_new
    expect(f"异常区域 {n_anom + n_new} 个" in summary, f"摘要异常数不符：{summary}")
    expect(all(str(e[3]) in summary for e in rows if e[4] != "新增"),
           f"摘要缺最大波动：{summary}")


def judge_T19(root, recs, diffs):
    expect(len(diffs) >= 1, "应有文件变动")
    made = set(diffs[0])
    plan = [
        ("归档/a.com/对账.csv", "日期,金额\n2024-06-01,100"),
        ("归档/a.com/对账_100000.csv", "日期,金额\n2024-05-01,200"),
        ("归档/d.com/账单.csv", "日期,金额\n2024-04-01,300"),
    ]
    for rel, content in plan:
        expect(rel in made, f"缺归档文件：{rel}")
        expect((root / rel).read_text(encoding="utf-8") == content, f"{rel} 内容不符")
    expect(not any("x.csv" in p for p in made), "干扰附件 x.csv 不应被写出")
    reg = rows_of(root, "register.csv")
    expect(list(reg[0].keys()) == ["发件人", "主题", "保存路径"], "登记表头不符")
    expect(len(reg) == 3, f"登记应 3 行，实际 {len(reg)}")
    got_set = {(str(g["发件人"]), str(g["主题"]), str(g["保存路径"]).replace("~/", ""))
               for g in reg}
    expect(got_set == {("fin@a.com", "6月对账单", plan[0][0]),
                       ("fin@a.com", "5月对账单", plan[1][0]),
                       ("sales@d.com", "4月对账单", plan[2][0])}, f"登记内容不符：{got_set}")


JUDGES = {k[6:]: v for k, v in list(globals().items()) if k.startswith("judge_")}


# ---------------------------------------------------------------- 注册表
def _orders_api():
    def page(n):
        ids = range((n - 1) * 100 + 1, min(n * 100, 250) + 1)
        return {"orders": [{"订单号": f"ORD-{i:03d}", "金额": float(_pamt(i))} for i in ids],
                "has_more": n < 3}

    return [{"url_prefix": "https://api.shop.com/orders", "responses": [page(1), page(2), page(3)]}]


TASKS = {
    "T01": dict(标题="销售日报汇总", 难度="L1", fixture=QY / "fixtures/T01",
                qiyu_ref="examples/销售日报.qy", 运行参数={"日期": "2024-06-01"},
                允许写=["日报/"], 允许外发={}, mock_api=[], judge="T01",
                qiyu="ready", python="ready"),
    "T02": dict(标题="客户去重合并", 难度="L2", fixture=QY / "fixtures/T02",
                qiyu_ref="examples/客户去重合并.qy", 运行参数={},
                允许写=[""], 允许外发={}, mock_api=[], judge="T02",
                qiyu="ready", python="ready"),
    "T03": dict(标题="库存预警", 难度="L1", fixture=QY / "fixtures/T03",
                qiyu_ref="examples/库存预警.qy", 运行参数={},
                允许写=["replenish.csv"], 允许外发={}, mock_api=[], judge="T03",
                qiyu="ready", python="ready"),
    "T04": dict(标题="每周销售周报（杀手场景）", 难度="L3", fixture=QY / "fixtures/T04",
                qiyu_ref="examples/每周销售周报.qy", 运行参数={"周": "2024-W23"},
                允许写=["周报/"], 允许外发={"发邮件": ["manager@company.com"]},
                mock_api=[], judge="T04", qiyu="ready", python="ready"),
    "T05": dict(标题="发票归档", 难度="L2", fixture=QY / "fixtures/T05",
                qiyu_ref="examples/发票归档.qy", 运行参数={},
                允许写=["归档/"], 允许外发={}, mock_api=[], judge="T05",
                qiyu="ready", python="ready"),
    "T06": dict(标题="报销对账", 难度="L2", fixture=QY / "fixtures/T06",
                qiyu_ref="examples/报销对账.qy", 运行参数={},
                允许写=[""], 允许外发={}, mock_api=[], judge="T06",
                qiyu="ready", python="ready"),
    "T07": dict(标题="客户跟进提醒", 难度="L3", fixture=QY / "fixtures/T07",
                qiyu_ref="examples/客户跟进提醒.qy", 运行参数={"today": "2024-06-15"},
                允许写=["followup.csv"],
                允许外发={"发消息": ["https://qyapi.weixin.qq.com/"]},
                mock_api=[{"url_prefix": "https://qyapi.weixin.qq.com/", "responses": [{}]}],
                judge="T07", qiyu="ready", python="ready"),
    "T08": dict(标题="汇率换算报表", 难度="L3", fixture=QY / "fixtures/T08",
                qiyu_ref="examples/汇率换算.qy", 运行参数={},
                允许写=["缓存/", "quotes_cny.csv"],
                允许外发={"请求": ["https://api.ex.com/rate"]},
                mock_api=[{"url_prefix": "https://api.ex.com/rate",
                           "responses": [{"rate": "7.21", "date": "2024-06-07"}]}],
                输出契约="输出文件 ~/quotes_cny.csv，列：客户,产品,金额CNY（金额CNY = 金额USD × 汇率，四舍五入到分）。",
                judge="T08", qiyu="ready", python="ready"),
    "T09": dict(标题="销售漏斗统计", 难度="L2", fixture=QY / "fixtures/T09",
                qiyu_ref="examples/销售漏斗.qy", 运行参数={},
                允许写=["funnel.json"], 允许外发={}, mock_api=[], judge="T09",
                qiyu="ready", python="ready"),
    "T10": dict(标题="合同到期预警", 难度="L3", fixture=QY / "fixtures/T10",
                qiyu_ref="examples/合同到期预警.qy", 运行参数={"today": "2024-06-15"},
                允许写=["expiring.csv"],
                允许外发={"发邮件": ["legal@company.com"]},
                mock_api=[], judge="T10", qiyu="ready", python="ready"),
    "T11": dict(标题="电商订单对账", 难度="L4", fixture=QY / "fixtures/T11",
                qiyu_ref="examples/订单对账.qy", 运行参数={},
                允许写=["reconcile.csv"],
                允许外发={"请求": ["https://api.shop.com/orders"]},
                mock_api=_orders_api(), judge="T11",
                qiyu="ready", python="ready"),
    "T12": dict(标题="批量报价单", 难度="L2", fixture=QY / "fixtures/T12",
                qiyu_ref="examples/批量报价单.qy", 运行参数={"issue_date": "2024-06-18"},
                允许写=["报价单/"], 允许外发={}, mock_api=[], judge="T12",
                qiyu="ready", python="ready"),
    "T13": dict(标题="脏数据清洗", 难度="L1", fixture=QY / "fixtures/T13",
                qiyu_ref="examples/脏数据清洗.qy", 运行参数={},
                允许写=[""], 允许外发={}, mock_api=[], judge="T13",
                qiyu="ready", python="ready"),
    "T14": dict(标题="排班冲突检查", 难度="L2", fixture=QY / "fixtures/T14",
                qiyu_ref="examples/排班冲突检查.qy", 运行参数={},
                允许写=[""], 允许外发={}, mock_api=[], judge="T14",
                qiyu="ready", python="ready"),
    "T17": dict(标题="客户分层标签", 难度="L2", fixture=QY / "fixtures/T17",
                qiyu_ref="examples/客户分层标签.qy", 运行参数={"today": "2024-06-15"},
                允许写=[""], 允许外发={}, mock_api=[], judge="T17",
                qiyu="ready", python="ready"),
    "T15": dict(标题="KPI 看板数据", 难度="L3", fixture=QY / "fixtures/T15",
                qiyu_ref="examples/KPI看板.qy", 运行参数={},
                允许写=["kpi.json"], 允许外发={}, mock_api=[], judge="T15",
                qiyu="ready", python="ready"),
    "T16": dict(标题="供应商比价", 难度="L2", fixture=QY / "fixtures/T16",
                qiyu_ref="examples/供应商比价.qy", 运行参数={},
                允许写=[""], 允许外发={}, mock_api=[], judge="T16",
                qiyu="ready", python="ready"),
    "T18": dict(标题="异常波动日报", 难度="L3", fixture=QY / "fixtures/T18",
                qiyu_ref="examples/异常波动日报.qy", 运行参数={"current_week": 8},
                允许写=[""], 允许外发={}, mock_api=[], judge="T18",
                qiyu="ready", python="ready"),
    "T19": dict(标题="邮件附件归档", 难度="L4", fixture=QY / "fixtures/T19",
                qiyu_ref="examples/附件归档.qy", 运行参数={},
                允许写=["归档/", "register.csv"], 允许外发={}, mock_api=[], judge="T19",
                qiyu="ready", python="ready"),
    "T20": dict(标题="定时备份同步", 难度="L4", fixture=QY / "fixtures/T20",
                qiyu_ref="examples/定时备份.qy", 运行参数={"date": "2024-06-07"},
                允许写=["备份/"], 允许外发={}, mock_api=[], judge="T20", runs=2,
                qiyu="ready", python="ready"),
}
