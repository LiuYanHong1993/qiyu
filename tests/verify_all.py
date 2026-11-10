# -*- coding: utf-8 -*-
"""双后端一致性验证：同一批 .qy 程序分别跑 qiyu.exe（编译器）与
python src/qiyu.py（解释器），逐格比对退出码 / 结果 JSON / 产物文件哈希。"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

QY = Path(__file__).resolve().parent.parent
EXE = QY / "dist/qiyu.exe"
PY = sys.executable
INTERP = QY / "src/qiyu.py"

# (名称, 程序, fixture根或None, 参数, 试运行, 运行次数)
CASES = [
    ("你好·默认",   "examples/你好.qy",       None,          {},                                False, 1),
    ("你好·传参",   "examples/你好.qy",       None,          {"名字": "世界"},                   False, 1),
    ("T01 日报",    "examples/销售日报.qy",    "fixtures/T01", {"日期": "2024-06-01"},            False, 1),
    ("T02 客户合并", "examples/客户去重合并.qy", "fixtures/T02", {},                                False, 1),
    ("T03 库存预警", "examples/库存预警.qy",    "fixtures/T03", {},                                False, 1),
    ("T04 周报·正常", "examples/每周销售周报.qy", "fixtures/T04", {"周": "2024-W23"},               False, 1),
    ("T04 周报·试运行", "examples/每周销售周报.qy", "fixtures/T04", {"周": "2024-W23"},             True,  1),
    ("T05 发票归档", "examples/发票归档.qy",    "fixtures/T05", {},                                False, 1),
    ("T06 报销对账", "examples/报销对账.qy",    "fixtures/T06", {},                                False, 1),
    ("T10 合同预警", "examples/合同到期预警.qy", "fixtures/T10", {"today": "2024-06-15"},           False, 1),
    ("T12 批量报价", "examples/批量报价单.qy",   "fixtures/T12", {"issue_date": "2024-06-18"},      False, 1),
    ("T14 排班冲突", "examples/排班冲突检查.qy",  "fixtures/T14", {},                                False, 1),
    ("T17 客户分层", "examples/客户分层标签.qy",  "fixtures/T17", {"today": "2024-06-15"},           False, 1),
    ("T20 备份幂等", "examples/定时备份.qy",     "fixtures/T20", {"date": "2024-06-07"},            False, 2),
]

SKIP = {"pyshim.py"}


def snap(root: Path):
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if rel.startswith("_") or rel == "pyshim.py" or "__pycache__" in rel:
                continue
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out


def prep(fixture, tag):
    root = QY / "verify" / tag
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    if fixture:
        shutil.copytree(QY / fixture, root, dirs_exist_ok=True)
    return root


def run_backend(backend, program, root, params, dry, runs):
    if backend == "exe":
        cmd = [str(EXE), "run", str(QY / program)]
    else:
        cmd = [PY, "-X", "utf8", str(INTERP), "run", str(QY / program)]
    for k, v in params.items():
        cmd += ["--参数", f"{k}={v}"]
    cmd += ["--根", str(root)]
    if dry:
        cmd += ["--试运行"]
    env = dict(os.environ)
    env["USERPROFILE"] = env["HOME"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    rc, out, err = 0, "", ""
    for _ in range(runs):
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", cwd=str(root), env=env)
        rc, out, err = p.returncode, p.stdout, p.stderr
    return rc, out, err


def norm(stdout):
    try:
        return json.dumps(json.loads(stdout), sort_keys=True, ensure_ascii=False)
    except Exception:
        return stdout.strip()


fails = 0
print(f"{'案例':<14}{'exe退出':>6}{'解释器退出':>8}  {'结果一致':>6}  {'产物一致':>6}")
for name, program, fixture, params, dry, runs in CASES:
    outputs = {}
    for backend in ("exe", "interp"):
        root = prep(fixture, f"{name}-{backend}")
        rc, out, err = run_backend(backend, program, root, params, dry, runs)
        files = snap(root)
        outputs[backend] = {"rc": rc, "norm": norm(out), "files": files, "err": err}
    a, b = outputs["exe"], outputs["interp"]
    same_rc = a["rc"] == b["rc"]
    same_out = (a["rc"] == 0 and b["rc"] == 0) and a["norm"] == b["norm"]
    same_files = a["files"] == b["files"]
    ok = same_rc and same_out and same_files
    fails += 0 if ok else 1
    mark = "✅" if ok else "❌"
    print(f"{mark} {name:<12}{a['rc']:>6}{b['rc']:>8}  {str(same_out):>6}  {str(same_files):>6}")
    if not ok:
        print(f"     exe  : {a['norm'][:120]} {a['err'][:120]}")
        print(f"     interp: {b['norm'][:120]} {b['err'][:120]}")
        if not same_files:
            only_a = set(a["files"]) - set(b["files"])
            only_b = set(b["files"]) - set(a["files"])
            diff = {k for k in set(a["files"]) & set(b["files"]) if a["files"][k] != b["files"][k]}
            print(f"     仅exe有: {sorted(only_a)}  仅解释器有: {sorted(only_b)}  内容不同: {sorted(diff)}")

total = len(CASES)
print(f"\n双后端一致性：{total - fails}/{total} 全等（退出码+结果JSON+产物哈希）")
sys.exit(1 if fails else 0)
