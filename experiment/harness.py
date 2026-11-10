# -*- coding: utf-8 -*-
"""契语 vs Python · 批量对比实验 harness（生成 → 执行 → 错误回喂修复 → 判定 → results.csv）。

用法（工作目录任意）：
  python -X utf8 experiment/harness.py --任务 T01,T03,T04 --语言 both --生成器 mock
  python -X utf8 experiment/harness.py --任务 all --语言 both --生成器 api --模型 m1,m2,m3 --种子 3

真实模型用 OpenAI 兼容接口，经环境变量配置：
  QIYU_EXP_BASE_URL  例如 https://api.openai.com/v1
  QIYU_EXP_API_KEY

协议要点（与 02-实验方案.md 对齐）：
  - 契语组 system prompt = 03-语言规范v0.md 全文；Python 组 = 环境说明（不含解法提示）
  - 两组任务提示逐字相同（任务卡「标准化提示词」+ 运行参数/输出契约附录）
  - 判定器（experiment/tasks.py）与生成上下文完全隔离
  - 修复回路：失败把结构化错误（契语）/ traceback（Python）回喂，最多 3 轮
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
QY = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(QY / "src"))
import tasks as T      # noqa: E402
import qiyu as QYENG   # noqa: E402

RESULTS = HERE / "results" / "results.csv"
ROW = ["task", "model", "lang", "seed", "compile_pass", "test_pass",
       "repair_rounds", "tokens", "undeclared_effects", "notes"]
SKIP_MODELS = {"mock", "dummy", ""}


def passed_keys():
    """台账里已通过的 (task,model,lang,seed) —— 断点续跑用。"""
    done = set()
    if RESULTS.exists():
        for r in csv.DictReader(RESULTS.open(encoding="utf-8-sig")):
            if (r["model"] not in SKIP_MODELS and r["test_pass"] == "1"
                    and "生成器错误" not in (r["notes"] or "")):
                done.add((r["task"], r["model"], r["lang"], r["seed"]))
    return done

SPEC = (QY / "03-语言规范v0.md").read_text(encoding="utf-8")

FEWSHOT_FILES = ["examples/库存预警.qy", "examples/报销对账.qy", "examples/客户跟进提醒.qy"]
FEWSHOT_TASKS = {"T03", "T06", "T07"}  # few-shot 泄漏的任务退出评分


def build_sys_qiyu(fewshot: bool):
    s = SPEC + "\n\n只输出一个完整 .qy 源文件（可放在代码块中），不要任何解释。"
    if fewshot:
        s += "\n\n## 15. 参考实现示例（写法以此为准）\n"
        for f in FEWSHOT_FILES:
            s += "\n```text\n" + (QY / f).read_text(encoding="utf-8").strip() + "\n```"
        s += "\n\n只输出一个完整 .qy 源文件（可放在代码块中），不要任何解释。"
    return s

SYS = {
    "qiyu": SPEC + "\n\n只输出一个完整 .qy 源文件（可放在代码块中），不要任何解释。",
    "python": (
        "你是资深数据自动化工程师。只输出一个可直接运行的 Python 脚本"
        "（可用标准库与 requests、smtplib），不要任何解释。\n"
        "环境：脚本的工作目录就是数据根目录；\"~/\" 路径请用 os.path.expanduser 解析"
        "（已指向数据根）。\n"
        "外设已 mock：import smtplib / requests 即可，调用会被环境记录用于审计。"
    ),
}

RUNNER = '''# -*- coding: utf-8 -*-
import os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import pyshim
pyshim.install()
src = open(os.path.join(BASE, "_solution.py"), encoding="utf-8").read()
g = {"__name__": "__main__", "__file__": os.path.join(BASE, "_solution.py")}
exec(compile(src, "_solution.py", "exec"), g)
'''


# ---------------------------------------------------------------- 提示词
def card_prompt(tid):
    card = next((QY / "tasks").glob(f"{tid}-*.md"))
    grab, out = False, []
    for ln in card.read_text(encoding="utf-8").splitlines():
        if ln.startswith("## "):
            if out:
                break
            grab = ln.strip().startswith("## 标准化提示词")
            continue
        if grab and ln.startswith(">"):
            out.append(ln.lstrip("> ").strip())
        elif grab and out:
            break
    text = " ".join(x for x in out if x)
    assert text, f"{tid} 卡片缺少标准化提示词"
    return text


def full_prompt(tid, cfg):
    parts = [card_prompt(tid)]
    if cfg.get("运行参数"):
        parts.append("本次运行参数：" + "，".join(f"{k}={v}" for k, v in cfg["运行参数"].items()) + "。")
    if cfg.get("输出契约"):
        parts.append(cfg["输出契约"])
    return "\n".join(parts)


# ---------------------------------------------------------------- 生成器
def strip_fence(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def gen_mock(tid, lang, seed, rnd, error, cfg, prompt, model):
    ext = ".qy" if lang == "qiyu" else ".py"
    cand = HERE / "canned" / f"{tid}.{lang}.r{rnd}{ext}"
    if cand.exists():
        return cand.read_text(encoding="utf-8"), 0
    if lang == "qiyu" and cfg.get("qiyu_ref"):
        return (QY / cfg["qiyu_ref"]).read_text(encoding="utf-8"), 0
    return None, 0


def gen_api(base, key):
    def _gen(tid, lang, seed, rnd, error, cfg, prompt, model):
        msgs = [{"role": "system", "content": SYS[lang]},
                {"role": "user", "content": prompt}]
        if error:
            msgs.append({"role": "user", "content":
                         "上一版程序未能通过，错误信息：\n" + str(error) +
                         "\n请修复，重新输出完整程序。"})
        body = json.dumps({"model": model, "messages": msgs,
                           "temperature": 0.2, "seed": seed}).encode("utf-8")
        req = urllib.request.Request(
            base.rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        last = None
        for _ in range(2):  # 推理型模型可能超过普通超时：600s + 重试一次
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    data = json.loads(r.read().decode("utf-8"))
                text = data["choices"][0]["message"]["content"]
                tok = int(data.get("usage", {}).get("total_tokens") or 0)
                return strip_fence(text), tok
            except Exception as e:
                last = e
        raise last
    return _gen


# ---------------------------------------------------------------- 执行与取证
def snap(root: Path):
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if rel.startswith("_") or rel == "pyshim.py" or "__pycache__" in rel:
                continue
            try:
                out[rel] = p.read_bytes()
            except OSError:
                pass
    return out


def file_diff(before, after):
    changed = [r for r in set(after) & set(before) if after[r] != before[r]]
    return sorted(set(after) - set(before)) + sorted(changed)


def qiyu_cmd(sandbox, params):
    cmd = [sys.executable, "-X", "utf8", str(QY / "src" / "qiyu.py"),
           "run", str(sandbox / "_solution.qy")]
    for k, v in params.items():
        cmd += ["--参数", f"{k}={v}"]
    cmd += ["--根", str(sandbox)]
    return cmd


def extract_qiyu_error(stderr):
    for ln in reversed(stderr.splitlines()):
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.dumps(json.loads(ln), ensure_ascii=False)
            except Exception:
                pass
    return stderr[-800:]


def extract_records_qiyu(stdout):
    try:
        return json.loads(stdout).get("操作记录", [])
    except Exception:
        return []


def read_py_records(sandbox):
    p = sandbox / "_mock_records.jsonl"
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def count_undeclared(cfg, recs, diffs):
    n = 0
    for dset in diffs:
        for rel in dset:
            if not any(rel == w or rel.startswith(w) for w in cfg.get("允许写", [])):
                n += 1
    ext = cfg.get("允许外发", {})
    for r in recs:
        k = r.get("种类")
        if k in ("发邮件", "发消息", "请求"):
            tgt = str(r.get("收件") or r.get("到") or r.get("网址") or "")
            if not any(tgt == a or tgt.startswith(a) for a in ext.get(k, [])):
                n += 1
    return n


# ---------------------------------------------------------------- 单次运行
def run_one(tid, lang, model, seed, gen):
    cfg = T.TASKS[tid]
    sandbox = HERE / "runs" / f"{tid}.{lang}.s{seed}"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    shutil.copytree(cfg["fixture"], sandbox)
    shutil.copy(HERE / "pyshim.py", sandbox / "pyshim.py")
    (sandbox / "_mock_api.json").write_text(
        json.dumps(cfg.get("mock_api", []), ensure_ascii=False), encoding="utf-8")
    (sandbox / "_runner.py").write_text(RUNNER, encoding="utf-8")

    prompt = full_prompt(tid, cfg)
    params = cfg.get("运行参数", {})
    runs_n = int(cfg.get("runs", 1))
    error, tokens, compile_pass, ok, rnd_used = None, 0, 0, False, None
    note, last_recs, last_diffs = "", [], []

    for rnd in range(4):
        try:
            code, tok = gen(tid, lang, seed, rnd, error, cfg, prompt, model)
        except Exception as e:
            print(f"[生成失败] {tid} {lang} s{seed}: {e}")
            note = f"生成器错误：{e}"[:160]
            code, tok = None, 0
        tokens += tok
        if code is None:
            note = note or "生成器无可用程序"
            break
        # 先存档再编译：任何失败都可取证（含词法器/解释器自身崩溃）
        ext = ".qy" if lang == "qiyu" else ".py"
        (sandbox / f"_attempt_r{rnd}{ext}").write_text(code, encoding="utf-8")
        # 编译（契语 = 解析 + 静态能力检查；Python = 语法编译）
        if lang == "qiyu":
            try:
                tool = QYENG.parse_source(code)
                QYENG.static_check(tool)
            except QYENG.QiyuError as e:
                error = json.dumps(e.json(), ensure_ascii=False)
                note = f"r{rnd} 编译未过（{e.code}）"
                continue
            except Exception as e:  # 解释器自身崩溃 = 语言 bug，作废该格并留痕
                error = f"解释器崩溃：{type(e).__name__}: {e}"
                note = f"r{rnd} 解释器内部错误"
                continue
            (sandbox / "_solution.qy").write_text(code, encoding="utf-8")
        else:
            try:
                compile(code, "_solution.py", "exec")
            except SyntaxError as e:
                error = f"SyntaxError: {e}"
                note = f"r{rnd} 语法错误"
                continue
            (sandbox / "_solution.py").write_text(code, encoding="utf-8")

        # 执行 runs_n 次（多跑用于幂等考察），逐次取证；每轮清空外设记录
        (sandbox / "_mock_records.jsonl").unlink(missing_ok=True)
        recs, diffs = [], []
        before = snap(sandbox)
        failed = False
        for _ in range(runs_n):
            if lang == "qiyu":
                p = subprocess.run(qiyu_cmd(sandbox, params), capture_output=True,
                                   text=True, encoding="utf-8")
                recs += extract_records_qiyu(p.stdout)
                if p.returncode != 0:
                    error, failed = extract_qiyu_error(p.stderr), True
            else:
                env = dict(os.environ)
                env["USERPROFILE"] = env["HOME"] = str(sandbox)
                p = subprocess.run([sys.executable, "-X", "utf8", str(sandbox / "_runner.py")],
                                   capture_output=True, text=True, encoding="utf-8",
                                   cwd=str(sandbox), env=env)
                recs += read_py_records(sandbox)
                if p.returncode != 0:
                    error, failed = (p.stderr or p.stdout)[-1500:], True
            after = snap(sandbox)
            diffs.append(file_diff(before, after))
            before = after
            if failed:
                break
        last_recs, last_diffs = recs, diffs
        if failed:
            note = f"r{rnd} 运行失败"
            continue
        compile_pass = 1
        try:
            T.JUDGES[cfg["judge"]](sandbox, recs, diffs)
            ok, rnd_used = True, rnd
            note = "通过"
            break
        except AssertionError as e:
            error = f"验收未通过：{e}"
            note = f"r{rnd} 验收未通过"
        except (KeyError, IndexError, AttributeError, TypeError) as e:
            # 判定器防弹层：模型输出的结构意外不应崩掉批次，转为干净失败
            error = f"验收未通过（产物结构意外：{type(e).__name__}: {e}）"
            note = f"r{rnd} 验收未通过（结构）"

    undeclared = count_undeclared(cfg, last_recs, last_diffs)
    row = [tid, model, lang, seed, compile_pass, 1 if ok else 0,
           rnd_used if ok else 3, tokens, undeclared,
           note or "未通过"]
    return row, ok


def load_env_file():
    """从 qiyu/.env 或 experiment/.env 读取 KEY=VALUE；系统环境变量优先于文件。"""
    for cand in (QY / ".env", HERE / ".env"):
        if cand.exists():
            for ln in cand.read_text(encoding="utf-8-sig").splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    load_env_file()
    ap = argparse.ArgumentParser()
    ap.add_argument("--任务", default="all")
    ap.add_argument("--语言", default="both", choices=["both", "qiyu", "python"])
    ap.add_argument("--生成器", default="mock", choices=["mock", "api"])
    ap.add_argument("--模型", default="")
    ap.add_argument("--种子", type=int, default=1)
    ap.add_argument("--跳过已过", action="store_true", help="跳过台账中已通过的格子（断点续跑）")
    ap.add_argument("--示例", action="store_true", help="契语组 system prompt 附 3 个参考实现（few-shot A/B）")
    args = ap.parse_args()
    if args.示例:
        SYS["qiyu"] = build_sys_qiyu(True)
    done = passed_keys() if args.跳过已过 else set()

    tids = list(T.TASKS) if args.任务 == "all" else \
        [t.strip() for t in args.任务.split(",") if t.strip()]
    langs = {"both": ["qiyu", "python"], "qiyu": ["qiyu"], "python": ["python"]}[args.语言]
    models = [m.strip() for m in args.模型.split(",") if m.strip()] or ["mock"]
    base = os.environ.get("QIYU_EXP_BASE_URL", "")
    key = os.environ.get("QIYU_EXP_API_KEY", "")
    if args.生成器 == "api" and not (base and key):
        print("需要环境变量 QIYU_EXP_BASE_URL / QIYU_EXP_API_KEY")
        return 2

    gen = gen_mock if args.生成器 == "mock" else gen_api(base, key)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    new_file = not RESULTS.exists()
    n_pass = n_all = 0
    with open(RESULTS, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        if new_file:
            w.writerow(ROW)
        for tid in tids:
            cfg = T.TASKS.get(tid)
            if cfg is None or not cfg.get("judge"):
                print(f"[跳过] {tid}: 未注册或缺判定器")
                continue
            for lang in langs:
                if lang == "qiyu" and cfg.get("qiyu") != "ready":
                    print(f"[跳过] {tid} qiyu：{cfg['qiyu']}")
                    continue
                for model in models:
                    for seed in range(1, args.种子 + 1):
                        if (tid, model, lang, str(seed)) in done:
                            print(f"[跳过] {tid} {lang} s{seed}: 台账已通过")
                            continue
                        try:
                            row, ok = run_one(tid, lang, model, seed, gen)
                        except Exception as e:  # 框架层兜底：单格崩溃不炸批
                            row = [tid, model, lang, seed, 0, 0, 3, 0, 0,
                                   f"框架错误：{type(e).__name__}: {e}"[:160]]
                            ok = False
                        w.writerow(row)
                        f.flush()
                        n_all += 1
                        n_pass += 1 if ok else 0
                        print(("✅" if ok else "❌") +
                              f" {tid} {lang} {model} s{seed} → rounds={row[6]} "
                              f"undeclared={row[8]} | {row[9]}")
    print(f"\n完成：{n_pass}/{n_all} 通过；结果已写入 {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
