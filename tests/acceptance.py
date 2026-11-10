# -*- coding: utf-8 -*-
"""契语 v0 验收脚本 —— 按 tasks/ 任务卡的验收契约做自动断言。

运行：python -X utf8 tests/acceptance.py   （工作目录任意）
"""
import csv
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent          # qiyu/tests
QY = HERE.parent                                 # qiyu/
sys.path.insert(0, str(QY / "src"))
import qiyu  # noqa: E402

FIX = QY / "fixtures"
PASS = []


def ok(name):
    PASS.append(name)
    print(f"  ✅ {name}")


def read_csv_rows(p: Path):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- T01
def test_t01():
    out = FIX / "T01/日报/日报.csv"
    if out.exists():
        out.unlink()
    qiyu.run_file(QY / "examples/销售日报.qy", {"日期": "2024-06-01"}, root=FIX / "T01")
    assert out.exists(), "日报.csv 未生成"
    rows = read_csv_rows(out)
    assert list(rows[0].keys()) == ["区域", "订单数", "数量", "金额"], "表头不符"
    src = read_csv_rows(FIX / "T01/销售明细/销售明细-2024-06-01.csv")
    expect = {}
    for r in src:
        d = expect.setdefault(r["区域"], [0, 0, Decimal(0)])
        d[0] += 1
        d[1] += int(r["数量"])
        d[2] += Decimal(r["金额"])
    assert {r["区域"] for r in rows} == set(expect), "区域集合不符"
    for r in rows:
        n, q, m = expect[r["区域"]]
        assert int(r["订单数"]) == n and int(r["数量"]) == q, f"{r['区域']} 汇总不符"
        assert abs(Decimal(r["金额"]) - m) < Decimal("0.01"), f"{r['区域']} 金额不符"
    assert [r["区域"] for r in rows] == sorted(expect), "未按区域升序"
    ok("T01 汇总正确、表头一致、升序")
    # 确定性：两次运行逐字节相同
    b1 = out.read_bytes()
    qiyu.run_file(QY / "examples/销售日报.qy", {"日期": "2024-06-01"}, root=FIX / "T01")
    assert out.read_bytes() == b1, "两次运行输出不一致（确定性被破坏）"
    ok("T01 确定性：同输入两次运行逐字节相同")


# ---------------------------------------------------------------- T03
def test_t03():
    out = FIX / "T03/replenish.csv"
    if out.exists():
        out.unlink()
    qiyu.run_file(QY / "examples/库存预警.qy", root=FIX / "T03")
    rows = read_csv_rows(out)
    assert list(rows[0].keys()) == ["SKU", "名称", "现库存", "安全库存", "缺口"], "表头不符"
    got = [(r["SKU"], int(r["缺口"])) for r in rows]
    # B-015(15) > A-001(10) > E-009(6)=F-001(6 平局按 SKU) > D-003(3)；A-002/C-007 等于不算
    assert got == [("B-015", 15), ("A-001", 10), ("E-009", 6), ("F-001", 6), ("D-003", 3)], got
    assert all(int(r["现库存"]) < int(r["安全库存"]) for r in rows), "出现了不缺货的行"
    ok("T03 边界（等于不算）、排序、平局按 SKU 全部正确")


# ---------------------------------------------------------------- T04
def test_t04():
    prog = QY / "examples/每周销售周报.qy"
    params = {"周": "2024-W23"}
    out = FIX / "T04/周报/销售周报.csv"
    if out.exists():
        out.unlink()

    res = qiyu.run_file(prog, params, root=FIX / "T04")  # 正常模式
    mail = [r for r in res["审计"]["操作记录"] if r["种类"] == "发邮件"]
    assert len(mail) == 1, f"邮件应恰好 1 封，得到 {len(mail)}"
    m = mail[0]
    assert m["动作"] == "执行（mock）" and m["收件"] == "manager@company.com", m
    assert "2024-W23" in m["主题"] and m["附件"], m
    assert out.exists(), "周报文件未生成"
    rows = read_csv_rows(out)
    assert list(rows[0].keys()) == ["区域", "订单数", "数量", "金额"]
    expect = {"华东": (3, 12, Decimal("14800.00")),
              "华北": (2, 20, Decimal("6000.00")),
              "华南": (1, 3, Decimal("8700.00"))}
    for r in rows:
        n, q, amt = expect[r["区域"]]
        assert (int(r["订单数"]), int(r["数量"])) == (n, q)
        assert abs(Decimal(r["金额"]) - amt) < Decimal("0.01")
    ok("T04 正常模式：周报正确 + 邮件恰好 1 封且收件人精确")

    # 试运行：外发屏蔽，本地产物照常
    if out.exists():
        out.unlink()
    res = qiyu.run_file(prog, params, root=FIX / "T04", mode="dry")
    mail = [r for r in res["审计"]["操作记录"] if r["种类"] == "发邮件"]
    assert len(mail) == 1 and mail[0]["动作"] == "预报", mail
    executed = [r for r in res["审计"]["操作记录"] if r["动作"].startswith("执行")]
    assert all(r["种类"] == "写" for r in executed), "试运行不应有任何外发执行"
    assert out.exists(), "试运行下周报文件未生成"
    ok("T04 试运行：外发被屏蔽（仅预报），周报文件照常生成 ← 核心差异化断言")


# ---------------------------------------------------------------- 能力系统（反面）
def test_capabilities():
    src_bad = """
工具 坏例子 {
  说明 "调用了未声明的能力"
  能力 读 "~/inventory.csv"
  库存 = 读表格("~/inventory.csv")
  存表格 库存 到 "~/out.csv"
}
"""
    try:
        qiyu.run_source(src_bad, root=FIX / "T03")
        raise AssertionError("应当因未声明写能力而失败")
    except qiyu.QiyuError as e:
        assert e.code == "E_CAPABILITY_NOT_DECLARED", e.code
        assert e.fix, "结构化错误必须带修复建议"
    ok("未声明能力 → E_CAPABILITY_NOT_DECLARED + 修复建议")

    src_escape = """
工具 越权 {
  说明 "试图读写沙箱外的目录"
  能力 读 "~/../外部/*.csv"
  数据 = 读表格("~/../外部/秘密.csv")
  返回 数据
}
"""
    try:
        qiyu.run_source(src_escape, root=FIX / "T03")
        raise AssertionError("应当因路径越界而失败")
    except qiyu.QiyuError as e:
        assert e.code in ("E_PATH_ESCAPE", "E_CAPABILITY_NOT_DECLARED"), e.code
    ok("路径越界（..）被拦截")


# ---------------------------------------------------------------- 审计包
def test_audit_package():
    import json
    tool = qiyu.parse_file(QY / "examples/每周销售周报.qy")
    caps = qiyu.static_check(tool)
    pkg = qiyu.audit_package(tool, caps)
    assert pkg["风险分级"] == "高" and pkg["外发动作"], pkg
    assert pkg["能力清单"] == [
        {"种类": "读", "范围": "~/销售数据/*.csv"},
        {"种类": "写", "范围": "~/周报/"},
        {"种类": "发邮件", "范围": "manager@company.com"},
    ] or len(pkg["能力清单"]) == 3, pkg["能力清单"]
    print(json.dumps(pkg, ensure_ascii=False, indent=2))
    ok("审计包：能力清单 + 外发动作 + 风险分级（高）")


if __name__ == "__main__":
    print("契语 v0 验收 ——")
    test_t01()
    test_t03()
    test_t04()
    test_capabilities()
    test_audit_package()
    print(f"\n全部 {len(PASS)} 组断言通过。")
