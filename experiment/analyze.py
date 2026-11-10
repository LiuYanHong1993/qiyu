# -*- coding: utf-8 -*-
"""汇总 results.csv → 指标表（自动过滤 mock/dummy 调试行）。

用法：python -X utf8 experiment/analyze.py [--任务明细]
"""
import csv
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP = {"mock", "dummy", ""}


def load():
    path = HERE / "results/results.csv"
    if "--台账" in sys.argv:
        path = Path(sys.argv[sys.argv.index("--台账") + 1])
    if not path.exists():
        return [], []
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    rows = [r for r in rows if r["model"] not in SKIP]
    infra = [r for r in rows if "生成器错误" in (r["notes"] or "")]
    valid = [r for r in rows if "生成器错误" not in (r["notes"] or "")]
    # 多轮重跑下同一格会有多行：每格取台账中最后一行（最终状态）
    latest = {}
    for r in valid:
        latest[(r["task"], r["model"], r["lang"], r["seed"])] = r
    return list(latest.values()), infra


def agg_of(rows, key_fn):
    agg = defaultdict(lambda: {"n": 0, "compile": 0, "test": 0, "onetime": 0,
                               "rounds": 0, "tokens": 0, "undeclared": 0})
    for r in rows:
        a = agg[key_fn(r)]
        a["n"] += 1
        a["compile"] += int(r["compile_pass"] or 0)
        a["test"] += int(r["test_pass"] or 0)
        a["onetime"] += 1 if (r["test_pass"] == "1" and r["repair_rounds"] == "0") else 0
        a["rounds"] += int(r["repair_rounds"] or 0)
        a["tokens"] += int(r["tokens"] or 0)
        a["undeclared"] += int(r["undeclared_effects"] or 0)
    return agg


def pct(x, n):
    return f"{x / n * 100:.1f}%" if n else "-"


def main():
    rows, infra = load()
    if not rows:
        print("results.csv 里还没有真模型数据")
        return
    print(f"共 {len(rows)} 格有效数据；另有 {len(infra)} 格因生成器错误（超时/网络）作废不计入指标\n")
    agg = agg_of(rows, lambda r: (r["model"], r["lang"]))
    print(f"{'模型':<14}{'语言':<8}{'格数':>4} {'编译':>8} {'通过':>8} {'一次':>8} {'均轮':>6} {'tokens':>10} {'未声明':>7}")
    for (model, lang), a in sorted(agg.items()):
        n = a["n"]
        print(f"{model:<14}{lang:<8}{n:>4} {pct(a['compile'], n):>8} {pct(a['test'], n):>8} "
              f"{pct(a['onetime'], n):>8} {a['rounds'] / n:>6.2f} {a['tokens']:>10} {a['undeclared']:>7}")

    # 通过线判定：一次通过率 契语 vs Python
    q = agg.get((rows[0]["model"], "qiyu"))
    p = agg.get((rows[0]["model"], "python"))
    if q and p and q["n"] and p["n"]:
        q1, p1 = q["onetime"] / q["n"], p["onetime"] / p["n"]
        print(f"\n一次通过率：契语 {q1:.1%} vs Python {p1:.1%} → "
              f"{'✅ 达标（≥2×）' if q1 >= 2 * p1 else '❌ 未达 2× 通过线'}")
        print(f"安全口径：契语未声明副作用 0（结构性保证）；契语'过宽声明'（声明超出登记表允许范围）{q['undeclared']} 格；"
              f"Python 未声明副作用 {p['undeclared']} 格（无保证，纯观察）")

    if "--任务明细" in sys.argv:
        print("\n按任务（一次通过率）:")
        tagg = agg_of(rows, lambda r: (r["task"], r["lang"]))
        tasks = sorted({t for t, _ in tagg})
        print(f"{'任务':<6}{'契语':>10}{'Python':>10}")
        for t in tasks:
            tq = tagg.get((t, "qiyu"), {"n": 0, "onetime": 0})
            tp = tagg.get((t, "python"), {"n": 0, "onetime": 0})
            print(f"{t:<6}{pct(tq['onetime'], tq['n']):>10}{pct(tp['onetime'], tp['n']):>10}")


import sys  # noqa: E402

if __name__ == "__main__":
    main()
