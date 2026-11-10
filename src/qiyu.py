# -*- coding: utf-8 -*-
"""契语（Qiyu）v0 解释器 —— 能力系统 · 试运行 · 审计包。

用法：
  python -X utf8 qiyu.py check FILE                              # 静态检查，输出审计包 JSON
  python -X utf8 qiyu.py run   FILE [--根 DIR] [--参数 k=v ...]
                       [--试运行 [全部]] [--审计 FILE]

规范见 ../03-语言规范v0.md。
"""
from __future__ import annotations

import argparse
import calendar
import csv
import fnmatch
import json
import re
import shutil
import sys
from datetime import date as _date, datetime as _datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext
from pathlib import Path

getcontext().prec = 34

EFFECTFUL = ("存表格", "存JSON", "复制文件", "移动文件", "写文本", "发邮件", "发消息", "请求")
AGGS = ("计数", "求和", "平均", "最小", "最大")
STDLIB_EXPR = ("读表格", "取列", "读文本", "列目录", "四舍五入", "转数字", "转文本",
               "替换", "正则替换", "分割", "取段", "标准日期", "格式日期", "净化文件名",
               "右取", "左取", "中取", "切除", "长度", "日期加", "日期差",
               "文件存在", "文件大小", "空表", "加入行", "查找", "为空", "不为空", "绝对值",
               "读记录", "列表成表格", "去重", "含", "连接") + AGGS
CAP_KINDS = ("读", "写", "发邮件", "发消息", "请求")
TYPES = ("文本", "数字", "真假")
CAP_FOR_EFFECT = {"存表格": "写", "存JSON": "写", "复制文件": "写", "移动文件": "写",
                  "写文本": "写", "发邮件": "发邮件", "发消息": "发消息", "请求": "请求"}
NUM_RE = re.compile(r"-?\d+(\.\d+)?")

# 全角标点 → 半角：中文母语模型的高频产物，词法层直接宽容（v1.5，实验归因）
FULLWIDTH = {"，": ",", "；": ";", "：": ":", "（": "(", "）": ")",
             "［": "[", "］": "]", "！": "!", "、": ","}


# ---------------------------------------------------------------- 错误模型
class QiyuError(Exception):
    def __init__(self, code, message, line=None, col=None, fix=""):
        self.code, self.message, self.line, self.col, self.fix = code, message, line, col, fix
        super().__init__(self.human())

    def human(self):
        loc = f"（行 {self.line}，列 {self.col}）" if self.line else ""
        fx = f"　修复：{self.fix}" if self.fix else ""
        return f"[{self.code}]{loc} {self.message}{fx}"

    def json(self):
        return {"code": self.code, "message": self.message,
                "line": self.line, "col": self.col, "fix": self.fix}


def err(code, message, tok=None, fix=""):
    raise QiyuError(code, message,
                    getattr(tok, "line", None), getattr(tok, "col", None), fix)


# ---------------------------------------------------------------- 词法
TOKEN_RE = re.compile(r"""
    (?P<WS>[ \t\r]+)
  | (?P<NL>\n)
  | (?P<COMMENT>\#[^\n]*)
  | (?P<NUM>\d+(?:\.\d+)?)
  | (?P<STR>"(?:[^"\\\n]|\\.)*")
  | (?P<NAME>[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*)
  | (?P<OP>==|!=|<=|>=|[{}(),.:<>=+\-*/\[\]])
""", re.VERBOSE)

ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}


def unescape(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in ESCAPES:
            out.append(ESCAPES[s[i + 1]])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


class Tok:
    __slots__ = ("kind", "value", "line", "col")

    def __init__(self, kind, value, line, col):
        self.kind, self.value, self.line, self.col = kind, value, line, col

    def __repr__(self):
        return f"Tok({self.kind},{self.value!r}@{self.line}:{self.col})"


def lex(src):
    toks, line, col, pos = [], 1, 1, 0
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if not m:
            ch = src[pos]
            if ch == "~" and pos + 1 < len(src) and src[pos + 1] == "/":
                # 裸路径：~/ 开头不加引号，读到空白或收尾符为止（v1.7，实验归因）
                j = pos
                while j < len(src) and src[j] not in ' \t\r\n)],':
                    j += 1
                text = src[pos:j]
                toks.append(Tok("STR", text, line, col))
                pos = j
                col += len(text)
                continue
            mapped = FULLWIDTH.get(ch)
            if mapped:
                toks.append(Tok("OP", mapped, line, col))
                pos += 1
                col += 1
                continue
            err("E_LEX", f"无法识别的字符 {ch!r}", Tok("?", "?", line, col),
                "删除该字符，或检查是否误用了全角符号")
        kind, text = m.lastgroup, m.group()
        if kind == "NL":
            toks.append(Tok("NL", "\\n", line, col))
        elif kind == "NUM":
            toks.append(Tok("NUM", text, line, col))
        elif kind == "STR":
            toks.append(Tok("STR", unescape(text[1:-1]), line, col))
        elif kind in ("NAME", "OP"):
            toks.append(Tok(kind, text, line, col))
        # WS / COMMENT 跳过
        nl = text.count("\n")
        if nl:
            line += nl
            col = len(text) - text.rfind("\n")
        else:
            col += len(text)
        pos = m.end()
    toks.append(Tok("EOF", "", line, col))
    return toks


# ---------------------------------------------------------------- 语法
class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def peek(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def at(self, kind, value=None):
        t = self.peek()
        return t.kind == kind and (value is None or t.value == value)

    def expect(self, kind, value=None):
        t = self.peek()
        if not self.at(kind, value):
            want = value if value is not None else kind
            err("E_PARSE", f"这里应当是「{want}」，但看到「{t.value or t.kind}」", t,
                "对照规范第 3–4 节修正该行写法")
        return self.next()

    def skip_nl(self):
        while self.at("NL"):
            self.next()

    # ---- 程序 --------------------------------------------------------
    def parse_program(self):
        self.skip_nl()
        self.expect("NAME", "工具")
        name = self.expect("NAME")
        self.expect("OP", "{")
        body = []
        while True:
            self.skip_nl()
            if self.at("OP", "}"):
                self.next()
                break
            if self.at("EOF"):
                err("E_PARSE", "工具体缺少收尾的 }", self.peek(), "补上 }")
            body.append(self.parse_item())
        self.skip_nl()
        if not self.at("EOF"):
            err("E_PARSE", "v0 限制：一个源文件只允许一个 工具", self.peek(),
                "把第二个 工具 移到另一个文件")
        return {"name": name.value, "body": body}

    def parse_item(self):
        t = self.peek()
        if t.kind != "NAME":
            err("E_PARSE", f"这里应当是子句或语句，但看到「{t.value or t.kind}」", t,
                "工具体里只允许 参数/能力/说明/保证/返回/赋值/效果调用")
        v = t.value
        if v == "参数":
            return self.parse_param()
        if v == "能力":
            return self.parse_cap()
        if v == "说明":
            self.next()
            if self.at("OP", ":"):
                self.next()
            if self.at("STR"):
                s = self.next()
                return {"t": "doc", "text": s.value, "line": t.line}
            parts = []  # 裸文本说明：中文模型的高频写法（v1.5）
            while not (self.at("NL") or self.at("EOF")):
                parts.append(str(self.next().value))
            return {"t": "doc", "text": "".join(parts), "line": t.line}
        if v == "保证":
            self.next()
            e = self.parse_expr()
            return {"t": "guarantee", "expr": e, "line": t.line}
        if v == "返回":
            self.next()
            e = self.parse_expr()
            return {"t": "return", "expr": e, "line": t.line}
        return self.parse_stmt()

    def parse_stmt(self):
        t = self.peek()
        if t.kind != "NAME":
            err("E_PARSE", f"这里应当是语句，但看到「{t.value or t.kind}」", t,
                "语句只允许 赋值/效果调用/对每个/若")
        v = t.value
        if v == "对每个" or v == "对每行":
            return self.parse_loop()
        if v == "对":
            # 循环的三种自然拼法（v1.6）：对 每个 行 在… / 对 每行 在…（隐式行）/ 对 行 在…
            t0 = self.next()
            nxt = self.peek()
            if nxt.kind == "NAME" and nxt.value in ("每个", "每行"):
                self.next()
                var_value = "行" if nxt.value == "每行" else self.expect("NAME").value
            else:
                var_value = self.expect("NAME").value
            self.expect("NAME", "在")
            seq = self.parse_expr()
            if self.at("OP", "{"):
                self.next()
                body = self.parse_block()
            else:
                self.skip_nl()
                body = [self.parse_stmt()]  # 无大括号单语句体（v1.7）
            return {"t": "loop", "var": var_value, "seq": seq,
                    "body": body, "line": t0.line}
        if v == "若":
            return self.parse_if()
        if v in ("派生", "筛选", "排列"):
            # 语句形式 = 就地重绑（v1.5：派生 X {…} ≡ X = 派生 X {…}，实验归因）
            t0 = self.next()
            target = self.expect("NAME")
            base = {"t": "name", "v": target.value, "line": t0.line}
            if v == "派生":
                expr = {"t": "derive", "table": base, "entries": self._derive_entries(),
                        "line": t0.line}
            elif v == "筛选":
                expr = {"t": "filter", "table": base, "cond": self._filter_cond(),
                        "line": t0.line}
            else:
                expr = {"t": "sort", "table": base, "keys": self._sort_keys(), "line": t0.line}
            return {"t": "assign", "name": target.value, "expr": expr, "line": t0.line}
        if v == "返回":
            err("E_PARSE", "v1.1 限制：返回 只能写在工具体里（不能出现在 对每个/若 块内）", t,
                "把 返回 移到块外")
        if v == "加入行":
            # 语句形式 = 就地重绑（v1.7）：括号或空格两种写法
            t0 = self.next()
            if self.at("OP", "("):
                self.next()
                target = self.expect("NAME")
                self.expect("OP", ",")
                row_expr = self.parse_expr()
                self.expect("OP", ")")
            else:
                target = self.expect("NAME")
                row_expr = self.parse_expr()
            expr = {"t": "call", "name": "加入行",
                    "args": [("pos", {"t": "name", "v": target.value, "line": t0.line}),
                             ("pos", row_expr)], "line": t0.line}
            return {"t": "assign", "name": target.value, "expr": expr, "line": t0.line}
        if self.peek(1).kind == "OP" and self.peek(1).value == "=":
            return self.parse_assign()
        return self.parse_effect_stmt()

    def parse_block(self):
        body = []
        while True:
            self.skip_nl()
            if self.at("OP", "}"):
                self.next()
                break
            if self.at("EOF"):
                err("E_PARSE", "块缺少收尾的 }", self.peek(), "补上 }")
            body.append(self.parse_stmt())
        return body

    def parse_loop(self):
        t = self.next()  # 对每个 / 对每行
        if t.value == "对每行":
            var_value = "行"  # 隐式行变量（v1.5，实验归因：模型的自然写法）
        else:
            var_value = self.expect("NAME").value
        self.expect("NAME", "在")
        seq = self.parse_expr()
        if self.at("OP", "{"):
            self.next()
            return {"t": "loop", "var": var_value, "seq": seq,
                    "body": self.parse_block(), "line": t.line}
        return {"t": "loop", "var": var_value, "seq": seq,  # 无大括号单语句体（v1.7）
                "body": [self.parse_stmt()], "line": t.line}

    def parse_if(self):
        t = self.next()  # 若
        cond = self.parse_expr()
        self.skip_nl()
        if self.at("OP", "{"):
            self.next()
            then = self.parse_block()
        else:
            then = [self.parse_stmt()]  # 无大括号单语句体（v1.7）
        els = []
        self.skip_nl()
        if self.at("NAME", "否则"):
            self.next()
            self.skip_nl()
            if self.at("NAME", "若"):  # 否则 若 = else-if 链（v1.6，实验归因）
                els = [self.parse_if()]
            elif not self.at("OP", "{"):
                els = [self.parse_stmt()]  # 无大括号单语句体（v1.7）
            else:
                self.next()
                els = self.parse_block()
        return {"t": "if", "cond": cond, "then": then, "else": els, "line": t.line}

    def parse_param(self):
        t = self.next()  # 参数
        name = self.expect("NAME")
        ty = "文本"  # 类型注解可省（v1.7，实验归因）
        if self.at("OP", ":"):
            self.next()
            ty = self.expect("NAME").value  # 归一为字符串
            if ty not in TYPES:
                err("E_PARSE", f"参数类型只能是 {'、'.join(TYPES)}", self.toks[self.i - 1], "改成 文本 / 数字 / 真假")
        default = None
        if self.at("OP", "="):
            self.next()
            if ty == "文本":  # 文本默认值：读到行尾（如 2024-06-15）
                parts = []
                while not (self.at("NL") or self.at("EOF")):
                    parts.append(str(self.next().value))
                default = "".join(parts)
            else:
                d = self.peek()
                if d.kind == "NUM":
                    default = Decimal(d.value)
                    self.next()
                elif d.kind == "NAME" and d.value in ("真", "假"):
                    default = d.value == "真"
                    self.next()
                else:
                    err("E_PARSE", "该类型参数的默认值只能是 数字/真假 字面量", d, "...")
        return {"t": "param", "name": name.value, "type": ty,
                "default": default, "line": t.line}

    def parse_cap(self):
        t = self.next()  # 能力
        kind = self.expect("NAME")
        if kind.value not in CAP_KINDS:
            err("E_PARSE", f"能力种类只能是 {'、'.join(CAP_KINDS)}", kind, "...")
        pattern = self.expect("STR")
        return {"t": "cap", "kind": kind.value, "pattern": pattern.value, "line": t.line}

    def parse_assign(self):
        name = self.next()
        self.next()  # =
        t = self.peek()
        if t.kind == "NAME" and t.value in ("请求", "分页请求"):
            # 可出现在赋值右侧的效果调用（它们返回数据）
            self.next()
            if t.value == "请求":
                kws = self.parse_kwargs()
                args = [("kw", k, e) for k, e in kws]
            else:  # 分页请求：括号调用式
                args = self.parse_args()
            return {"t": "assign", "name": name.value,
                    "expr": {"t": "effectcall", "name": t.value,
                             "args": args, "line": t.line},
                    "line": name.line}
        return {"t": "assign", "name": name.value, "expr": self.parse_expr(),
                "line": name.line}

    def parse_effect_stmt(self):
        t = self.next()
        if t.value not in EFFECTFUL:
            err("E_PARSE", f"「{t.value}」不是效果调用", t,
                "效果调用：" + "、".join(EFFECTFUL) + "；其余计算要写进 赋值")
        if t.value in ("存表格", "复制文件", "移动文件", "写文本"):
            first = self.parse_expr()
            self.expect("NAME", "到")
            path = self.parse_expr()
            return {"t": "effect", "name": t.value, "args": [("pos", first), ("pos", path)],
                    "line": t.line}
        if t.value == "分页请求":
            return {"t": "effect", "name": "分页请求", "args": self.parse_args(),
                    "line": t.line}
        if t.value == "存JSON":
            first = self.parse_expr()
            second = self.parse_expr()
            self.expect("NAME", "到")
            path = self.parse_expr()
            return {"t": "effect", "name": "存JSON",
                    "args": [("pos", first), ("pos", second), ("pos", path)],
                    "line": t.line}
        kws = self.parse_kwargs()
        return {"t": "effect", "name": t.value, "args": [("kw", k, e) for k, e in kws],
                "line": t.line}

    def parse_kwargs(self):
        kws = []
        while True:
            if self.at("EOF") or self.at("NL"):
                break
            if self.at("OP", ","):
                self.next()
                continue
            if self.at("NAME") and self.peek(1).kind == "OP" and self.peek(1).value == "=":
                name = self.next().value
                self.next()  # =
                kws.append((name, self.parse_expr()))
            else:
                err("E_PARSE", "效果调用的实参应当写成 名字=值", self.peek(),
                    '例如 收件="a@b.com" 主题="日报"')
        return kws

    # ---- 表达式 ------------------------------------------------------
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        l = self.parse_and()
        while self.at("NAME", "或"):
            op = self.next()
            l = {"t": "binop", "op": "或", "l": l, "r": self.parse_and(), "line": op.line}
        return l

    def parse_and(self):
        l = self.parse_not()
        while self.at("NAME", "且"):
            op = self.next()
            l = {"t": "binop", "op": "且", "l": l, "r": self.parse_not(), "line": op.line}
        return l

    def parse_not(self):
        if self.at("NAME") and self.peek().value in ("非", "不"):  # 不=非（v1.7）
            self.next()
            self.skip_nl()
            return {"t": "not", "e": self.parse_not(), "line": self.toks[self.i - 1].line}
        return self.parse_cmp()

    def parse_cmp(self):
        l = self.parse_add()
        if self.at("OP") and self.peek().value in ("==", "!=", "<", "<=", ">", ">="):
            op = self.next()
            r = self.parse_add()
            return {"t": "binop", "op": op.value, "l": l, "r": r, "line": op.line}
        return l

    def parse_add(self):
        l = self.parse_mul()
        while self.at("OP") and self.peek().value in ("+", "-"):
            op = self.next()
            r = self.parse_mul()
            l = {"t": "binop", "op": op.value, "l": l, "r": r, "line": op.line}
        return l

    def parse_mul(self):
        l = self.parse_unary()
        while self.at("OP") and self.peek().value in ("*", "/"):
            op = self.next()
            r = self.parse_unary()
            l = {"t": "binop", "op": op.value, "l": l, "r": r, "line": op.line}
        return l

    def parse_unary(self):
        if self.at("OP", "-"):
            op = self.next()
            return {"t": "neg", "e": self.parse_unary(), "line": op.line}
        return self.parse_postfix()

    def parse_postfix(self):
        e = self.parse_atom()
        while self.at("OP", "."):
            dot = self.next()
            name = self.expect("NAME")
            e = {"t": "member", "base": e, "name": name.value, "line": dot.line}
        return e

    def parse_atom(self):
        t = self.peek()
        if t.kind == "NUM":
            self.next()
            return {"t": "num", "v": Decimal(t.value), "line": t.line}
        if t.kind == "STR":
            self.next()
            return {"t": "str", "v": t.value, "line": t.line}
        if t.kind == "OP" and t.value == "(":
            self.next()
            e = self.parse_expr()
            self.expect("OP", ")")
            return e
        if t.kind == "OP" and t.value == "[":
            self.next()
            items = []
            while not self.at("OP", "]"):
                self.skip_nl()
                if self.at("OP", "]"):
                    break
                items.append(self.parse_expr())
                self.skip_nl()
                if self.at("OP", ","):
                    self.next()
                elif not self.at("OP", "]"):
                    err("E_PARSE", "列表项之间用逗号分隔", self.peek(), "...")
            self.next()
            return {"t": "list", "items": items, "line": t.line}
        if t.kind == "NAME":
            v = t.value
            if v == "汇总":
                return self.parse_summary()
            if v == "筛选":
                return self.parse_filter()
            if v == "派生":
                return self.parse_derive()
            if v == "排列":
                return self.parse_sort()
            if v == "空":
                self.next()
                return {"t": "none", "line": t.line}
            if v in ("真", "假"):
                self.next()
                return {"t": "bool", "v": v == "真", "line": t.line}
            if v in EFFECTFUL:
                err("E_PARSE", f"效果调用「{v}」只能单独成行，不能出现在表达式里", t,
                    "把它移出来写成单独一行语句")
            self.next()
            if self.at("OP", "("):
                if v not in STDLIB_EXPR:
                    err("E_UNKNOWN_BUILTIN", f"没有叫「{v}」的标准库函数", t,
                        "可用：" + "、".join(STDLIB_EXPR) + "；效果调用：" + "、".join(EFFECTFUL))
                return {"t": "call", "name": v, "args": self.parse_args(), "line": t.line}
            return {"t": "name", "v": v, "line": t.line}
        err("E_PARSE", f"这里应当是一个表达式，但看到「{t.value or t.kind}」", t, "...")

    def parse_args(self):
        self.expect("OP", "(")
        args = []
        while not self.at("OP", ")"):
            if self.at("NAME") and self.peek(1).kind == "OP" and self.peek(1).value == "=":
                name = self.next().value
                self.next()
                args.append(("kw", name, self.parse_expr()))
            else:
                args.append(("pos", self.parse_expr()))
            if self.at("OP", ","):
                self.next()
            elif not self.at("OP", ")"):
                err("E_PARSE", "实参之间用逗号分隔", self.peek(), "...")
        self.expect("OP", ")")
        return args

    def parse_summary(self):
        t = self.next()  # 汇总
        table = self.parse_postfix()
        self.expect("NAME", "按")
        by = self.expect("NAME")
        self.expect("OP", "{")
        entries = []
        while True:
            self.skip_nl()
            if self.at("OP", "}"):
                self.next()
                break
            if self.at("EOF"):
                err("E_PARSE", "汇总缺少收尾的 }", self.peek(), "补上 }")
            name = self.expect("NAME")
            self.expect("OP", "=")
            agg = self.expect("NAME")
            if agg.value not in AGGS:
                err("E_PARSE", f"汇总里只能用聚合函数：{'、'.join(AGGS)}", agg, "...")
            self.expect("OP", "(")
            col = None
            if agg.value != "计数" or self.at("NAME"):
                col = self.expect("NAME").value
            self.expect("OP", ")")
            entries.append((name.value, agg.value, col))
            if self.at("OP", ","):
                self.next()
        return {"t": "summary", "table": table, "by": by.value,
                "entries": entries, "line": t.line}

    def parse_filter(self):
        t = self.next()  # 筛选
        table = self.parse_postfix()
        return {"t": "filter", "table": table, "cond": self._filter_cond(), "line": t.line}

    def _filter_cond(self):
        self.expect("NAME", "条件")
        self.expect("OP", "(")
        cond = self.parse_expr()
        self.expect("OP", ")")
        return cond

    def parse_derive(self):
        t = self.next()  # 派生
        table = self.parse_postfix()
        return {"t": "derive", "table": table, "entries": self._derive_entries(), "line": t.line}

    def _derive_entries(self):
        self.expect("OP", "{")
        entries = []
        while True:
            self.skip_nl()
            if self.at("OP", "}"):
                self.next()
                break
            if self.at("EOF"):
                err("E_PARSE", "派生 缺少收尾的 }", self.peek(), "补上 }")
            name = self.expect("NAME")
            self.expect("OP", "=")
            entries.append((name.value, self.parse_expr()))
            if self.at("OP", ","):
                self.next()
        return entries

    def parse_sort(self):
        t = self.next()  # 排列
        table = self.parse_postfix()
        return {"t": "sort", "table": table, "keys": self._sort_keys(), "line": t.line}

    def _sort_keys(self):
        self.expect("NAME", "按")
        keys = []
        while True:
            col = self.expect("NAME")
            direction = "升序"
            if self.at("NAME") and self.peek().value in ("升序", "降序"):
                direction = self.next().value
            keys.append((col.value, direction))
            if self.at("OP", ","):
                self.next()
                continue
            break
        return keys


def parse_source(src):
    return Parser(lex(src)).parse_program()


def parse_file(path):
    return parse_source(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 静态检查
def walk_expr(e, fn):
    if not isinstance(e, dict):
        return
    fn(e)
    for key in ("l", "r", "base", "e", "table", "cond"):
        if key in e:
            walk_expr(e[key], fn)
    if e.get("t") == "call":
        for a in e["args"]:
            walk_expr(a[-1], fn)
    if e.get("t") == "derive":
        for _, ex in e["entries"]:
            walk_expr(ex, fn)
    if e.get("t") == "list":
        for x in e["items"]:
            walk_expr(x, fn)


def static_check(tool):
    caps = {}
    for st in tool["body"]:
        if st["t"] == "cap":
            caps.setdefault(st["kind"], []).append(st["pattern"])

    def check_expr(e):
        if e.get("t") == "call" and e["name"] == "读表格" and "读" not in caps:
            raise QiyuError("E_CAPABILITY_NOT_DECLARED",
                            "「读表格」需要「读」能力，但工具没有声明",
                            e.get("line"), fix='添加能力声明：能力 读 "~/路径/*"')

    for st in tool["body"]:
        if st["t"] == "assign":
            walk_expr(st["expr"], check_expr)
        elif st["t"] == "return":
            walk_expr(st["expr"], check_expr)
        elif st["t"] == "effect":
            kind = CAP_FOR_EFFECT[st["name"]]
            if kind not in caps:
                raise QiyuError("E_CAPABILITY_NOT_DECLARED",
                                f"调用「{st['name']}」需要「{kind}」能力，但工具没有声明",
                                st["line"],
                                fix=f'在工具头部添加一行：能力 {kind} "~/范围"')
    return caps


# ---------------------------------------------------------------- 运行时
class QiyuRuntimeError(QiyuError):
    pass


class ParamNS:
    def __init__(self, params):
        self.params = params

    def get(self, name, line=None):
        if name in self.params:
            return self.params[name]
        raise QiyuError("E_PARAM_MISSING", f"缺少参数「{name}」", line,
                        fix=f"运行时传入 --参数 {name}=…")


class RowNS:
    def __init__(self, row):
        self.row = row

    def get(self, name, line=None):
        if name in self.row:
            return self.row[name]
        raise QiyuError("E_TYPE", f"表格没有列「{name}」", line,
                        fix="检查列名拼写，或先 派生 出该列")


class RespNS:
    """请求 的返回：状态（数字）/ 文本 / 数据（解析后的 JSON：记录/列表/标量）。"""

    def __init__(self, status, text, data):
        self.status, self.text, self.data = status, text, data

    def member(self, name, line=None):
        if name == "状态":
            return Decimal(self.status)
        if name == "文本":
            return self.text
        if name == "数据":
            return wrap_json(self.data)
        raise QiyuError("E_TYPE", f"响应 只有 状态/文本/数据，没有「{name}」", line,
                        fix="取数据用 响应.数据.键名")


def wrap_json(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: wrap_json(x) for k, x in v.items()}
    if isinstance(v, list):
        return [wrap_json(x) for x in v]
    return v


class Table:
    def __init__(self, columns, rows):
        self.columns = list(columns)
        self.rows = rows

    @property
    def 行数(self):
        return len(self.rows)

    @property
    def 列数(self):
        return len(self.columns)


class Ctx:
    def __init__(self, root: Path, caps, mode, records):
        self.root = root
        self.caps = caps
        self.mode = mode  # normal | dry | dry_all
        self.records = records


def norm_rel(path_str, line=None):
    rel = path_str[2:] if path_str.startswith("~/") else (
        path_str[1:] if path_str.startswith("/") else path_str)
    rel = rel.replace("\\", "/")
    trailing = rel.endswith("/")
    parts = [seg for seg in rel.split("/") if seg not in ("", ".")]
    if ".." in parts:
        raise QiyuError("E_PATH_ESCAPE", f"路径「{path_str}」包含 ..，越出了沙箱根", line,
                        fix="路径必须落在沙箱根内")
    out = "/".join(parts)
    return out + "/" if (trailing and out) else out


def cap_match(kind, pattern, value):
    if kind in ("读", "写"):
        if pattern.startswith("~/"):
            pat = pattern[2:]
        elif pattern.startswith("/"):
            pat = pattern[1:]
        else:
            pat = pattern
        pat = pat.replace("\\", "/").strip("/")
        if pat == "":
            return True  # 授权整个沙箱根
        if pattern.endswith("/"):
            return value.startswith(pat + "/")
        return fnmatch.fnmatchcase(value, pat)
    if kind == "发邮件":
        return fnmatch.fnmatchcase(value, pattern)
    return value.startswith(pattern)  # 发消息 / 请求：前缀


def require_cap(ctx, kind, value, line, what):
    for pattern in ctx.caps.get(kind, []):
        if cap_match(kind, pattern, value):
            return
    raise QiyuError("E_CAPABILITY_NOT_DECLARED",
                    f"操作 {what} 不在已声明的「{kind}」能力内", line,
                    fix=f'添加能力声明：能力 {kind} "{value}"（或更宽的授权范围）')


def read_csv_table(path: Path, line=None):
    with open(path, encoding="utf-8-sig", newline="") as f:
        raw = [r for r in csv.reader(f)]
    raw = [r for r in raw if any(c.strip() for c in r)]
    if not raw:
        return Table([], [])
    header = [c.strip() for c in raw[0]]
    data = []
    for r in raw[1:]:
        r = list(r) + [""] * (len(header) - len(r))
        data.append(r[:len(header)])
    numeric = []
    for j in range(len(header)):
        vals = [row[j].strip() for row in data if row[j].strip()]
        numeric.append(bool(vals) and all(NUM_RE.fullmatch(v) for v in vals))
    rows = []
    for r in data:
        d = {}
        for j, name in enumerate(header):
            raw = r[j]
            s = raw.strip()
            d[name] = Decimal(s) if (numeric[j] and s) else raw  # 文本保留原样：清洗是用户程序的事
        rows.append(d)
    return Table(header, rows)


def fmt_cell(v):
    if isinstance(v, bool):
        return "真" if v else "假"
    if v is None:
        return ""
    return str(v)


def write_csv_table(tb: Table, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(tb.columns)
        for r in tb.rows:
            w.writerow([fmt_cell(r.get(c, "")) for c in tb.columns])


def is_num(x):
    return isinstance(x, Decimal) or (isinstance(x, int) and not isinstance(x, bool))


def to_dec(x):
    return x if isinstance(x, Decimal) else Decimal(x)


def type_name(x):
    if isinstance(x, Table):
        return "表格"
    if isinstance(x, bool):
        return "真假"
    if is_num(x):
        return "数字"
    if isinstance(x, str):
        return "文本"
    if x is None:
        return "空"
    return type(x).__name__


def truthy(v):
    if isinstance(v, bool):
        return v
    if is_num(v):
        return to_dec(v) != 0
    if isinstance(v, str):
        return v != ""
    return v is not None


def interp_expr(e, env, ctx):
    t = e["t"]
    if t == "num":
        return e["v"]
    if t == "str":
        return e["v"]
    if t == "name":
        v = e["v"]
        if v in env:
            return env[v]
        ps = env.get("参数")
        if isinstance(ps, ParamNS) and v in ps.params:
            return ps.params[v]  # 参数直接可用：裸名即 参数.名（v1.4，按实验归因增加）
        raise QiyuError("E_UNKNOWN_NAME", f"没有定义「{v}」", e["line"],
                        fix="先给它赋值，或检查拼写；工具变量与参数可直接用名字")
    if t == "member":
        base = interp_expr(e["base"], env, ctx)
        name = e["name"]
        if isinstance(base, (ParamNS, RowNS)):
            return base.get(name, e["line"])
        if base is None:
            raise QiyuError("E_TYPE", "对空值取成员", e["line"],
                            fix="先用 为空(…) 判断查找是否命中，再取成员")
        if isinstance(base, RespNS):
            return base.member(name, e["line"])
        if isinstance(base, dict):
            if name in base:
                return wrap_json(base[name])
            raise QiyuError("E_TYPE", f"记录没有键「{name}」", e["line"],
                            fix="可用键：" + "、".join(map(str, base.keys())))
        if isinstance(base, list):
            if name == "条数":
                return Decimal(len(base))
            raise QiyuError("E_TYPE", f"列表只有 条数 属性，没有「{name}」", e["line"], fix="...")
        if isinstance(base, Table):
            if name == "行数":
                return Decimal(base.行数)
            if name == "列数":
                return Decimal(base.列数)
            raise QiyuError("E_TYPE", f"表格只有 行数/列数 属性，没有「{name}」", e["line"],
                            fix="用 汇总/派生 计算所需的列")
        raise QiyuError("E_TYPE", f"{type_name(base)} 没有成员「{name}」", e["line"], fix="...")
    if t == "neg":
        v = interp_expr(e["e"], env, ctx)
        if not is_num(v):
            raise QiyuError("E_TYPE", f"负号只能用于数字，得到 {type_name(v)}", e["line"], fix="...")
        return -to_dec(v)
    if t == "none":
        return None
    if t == "bool":
        return e["v"]
    if t == "list":
        return [interp_expr(x, env, ctx) for x in e["items"]]
    if t == "binop":
        if e["op"] in ("且", "或"):
            l = interp_expr(e["l"], env, ctx)
            if e["op"] == "且":
                return truthy(interp_expr(e["r"], env, ctx)) if truthy(l) else False
            return True if truthy(l) else truthy(interp_expr(e["r"], env, ctx))
        return interp_binop(e, env, ctx)
    if t == "not":
        return not truthy(interp_expr(e["e"], env, ctx))
    if t == "call":
        return interp_call(e, env, ctx)
    if t == "summary":
        return interp_summary(e, env, ctx)
    if t == "filter":
        return interp_filter(e, env, ctx)
    if t == "derive":
        return interp_derive(e, env, ctx)
    if t == "sort":
        return interp_sort(e, env, ctx)
    raise QiyuError("E_INTERNAL", f"未知表达式节点 {t}")


def interp_binop(e, env, ctx):
    a = interp_expr(e["l"], env, ctx)
    b = interp_expr(e["r"], env, ctx)
    op = e["op"]
    if op == "+":
        if is_num(a) and is_num(b):
            return to_dec(a) + to_dec(b)
        if isinstance(a, str) and isinstance(b, str):
            return a + b
        raise QiyuError("E_TYPE", f"不能把 {type_name(a)} 和 {type_name(b)} 相加", e["line"],
                        fix="数字加数字、文本接文本；需要拼接时先用转换")
    if op in ("-", "*", "/"):
        if not (is_num(a) and is_num(b)):
            raise QiyuError("E_TYPE", f"「{op}」只能用于数字，得到 {type_name(a)} 与 {type_name(b)}",
                            e["line"], fix="...")
        x, y = to_dec(a), to_dec(b)
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if y == 0:
            raise QiyuError("E_DIV_ZERO", "除以零", e["line"], fix="先筛选或判断分母不为零")
        return x / y
    # 比较
    comparable = (is_num(a) and is_num(b)) or (isinstance(a, str) and isinstance(b, str)) \
        or (isinstance(a, bool) and isinstance(b, bool))
    if not comparable:
        raise QiyuError("E_TYPE", f"不能比较 {type_name(a)} 与 {type_name(b)}", e["line"],
                        fix="数字比数字、文本比文本、真假比真假")
    x, y = (to_dec(a), to_dec(b)) if is_num(a) else (a, b)
    if op == "==":
        return x == y
    if op == "!=":
        return x != y
    if op == "<":
        return x < y
    if op == "<=":
        return x <= y
    if op == ">":
        return x > y
    return x >= y


def interp_call(e, env, ctx):
    name = e["name"]
    if name == "读表格":
        if len(e["args"]) != 1 or e["args"][0][0] != "pos":
            raise QiyuError("E_TYPE", "读表格 接受一个路径参数", e["line"], fix='读表格 "~/目录/文件.csv"')
        p = interp_expr(e["args"][0][1], env, ctx)
        if not isinstance(p, str):
            raise QiyuError("E_TYPE", f"读表格 的路径应是文本，得到 {type_name(p)}", e["line"], fix="...")
        rel = norm_rel(p, e["line"])
        require_cap(ctx, "读", rel, e["line"], f"读 {rel}")
        root = ctx.root
        if any(ch in rel for ch in "*?["):
            files = sorted(x for x in root.glob(rel) if x.is_file())
            if not files:
                raise QiyuError("E_FILE_NOT_FOUND", f"模式 {rel} 没有匹配到文件", e["line"],
                                fix="确认文件存在，或放宽能力与路径模式")
            tables = [read_csv_table(f, e["line"]) for f in files]
            cols = tables[0].columns
            for tb in tables[1:]:
                if tb.columns != cols:
                    raise QiyuError("E_TYPE", "拼接的文件列不一致", e["line"],
                                    fix="确认各文件表头一致")
            all_rows = [r for tb in tables for r in tb.rows]
            return Table(cols, all_rows)
        f = root / rel
        if not f.is_file():
            raise QiyuError("E_FILE_NOT_FOUND", f"找不到文件 {rel}", e["line"],
                            fix="确认文件存在；能力声明与路径都相对沙箱根")
        return read_csv_table(f, e["line"])
    if name in ("替换", "正则替换", "右取", "左取", "中取", "切除", "长度",
                "转数字", "转文本", "日期加", "日期差", "文件存在", "文件大小", "取列",
                "读文本", "列目录", "分割", "取段", "标准日期", "格式日期",
                "净化文件名", "空表", "加入行", "查找", "为空", "不为空", "绝对值",
                "读记录", "列表成表格", "去重", "含", "连接"):
        return interp_misc(name, e, env, ctx)
    if name == "四舍五入":
        vals = [interp_expr(a[-1], env, ctx) for a in e["args"]]
        if len(vals) != 2 or not is_num(vals[0]) or not is_num(vals[1]):
            raise QiyuError("E_TYPE", "四舍五入(数, 位数) 需要两个数字", e["line"], fix="...")
        q = Decimal(1).scaleb(-int(vals[1]))
        return to_dec(vals[0]).quantize(q, rounding=ROUND_HALF_UP)
    raise QiyuError("E_INTERNAL", f"未知调用 {name}")


def pos_vals(e, env, ctx):
    return [interp_expr(a[1], env, ctx) for a in e["args"] if a[0] == "pos"]


def _need_str(v, fname, line):
    if not isinstance(v, str):
        raise QiyuError("E_TYPE", f"{fname} 的实参应是文本，得到 {type_name(v)}", line, fix="...")
    return v


def _need_num(v, fname, line):
    if not is_num(v):
        raise QiyuError("E_TYPE", f"{fname} 的实参应是数字，得到 {type_name(v)}", line, fix="...")
    return to_dec(v)


def add_months(dt, m):
    total = dt.month - 1 + m
    y, mo = dt.year + total // 12, total % 12 + 1
    return _date(y, mo, min(dt.day, calendar.monthrange(y, mo)[1]))


def parse_date(s, line):
    try:
        return _date.fromisoformat(s)
    except Exception:
        raise QiyuError("E_TYPE", f"「{s}」不是日期", line,
                        fix="日期一律用 YYYY-MM-DD 文本表示")


def interp_misc(name, e, env, ctx):
    line = e["line"]
    v = pos_vals(e, env, ctx)
    if name == "替换":
        s, old, new = (_need_str(x, name, line) for x in v)
        return s.replace(old, new)
    if name == "正则替换":
        s, pat, new = (_need_str(x, name, line) for x in v)
        try:
            return re.sub(pat, lambda m: new, s)
        except re.error as ex:
            raise QiyuError("E_TYPE", f"正则模式有误：{ex}", line, fix="检查模式写法")
    if name == "右取":
        s = _need_str(v[0], name, line)
        n = int(_need_num(v[1], name, line))
        return s[-n:] if n > 0 else ""
    if name == "左取":
        s = _need_str(v[0], name, line)
        n = int(_need_num(v[1], name, line))
        return s[:n] if n > 0 else ""
    if name == "中取":
        s = _need_str(v[0], name, line)
        a = int(_need_num(v[1], name, line))
        b = int(_need_num(v[2], name, line))
        return s[max(a - 1, 0):b]
    if name == "切除":
        return _need_str(v[0], name, line).strip()
    if name == "长度":
        x = v[0]
        if isinstance(x, (str, list)):
            return Decimal(len(x))
        raise QiyuError("E_TYPE", f"长度 的实参应是文本/列表，得到 {type_name(x)}", line, fix="...")
    if name == "转数字":
        if isinstance(v[0], bool):
            return Decimal(1 if v[0] else 0)
        try:
            return Decimal(str(v[0]).strip())
        except Exception:
            raise QiyuError("E_TYPE", f"「{v[0]}」不能转成数字", line, fix="检查该值是否为数字文本")
    if name == "转文本":
        return fmt_cell(v[0])
    if name == "日期加":
        base = parse_date(_need_str(v[0], name, line), line)
        n = int(_need_num(v[1], name, line))
        unit = _need_str(v[2], name, line)
        if unit == "日":
            out = base + timedelta(days=n)
        elif unit == "月":
            out = add_months(base, n)
        elif unit == "年":
            out = add_months(base, 12 * n)
        else:
            raise QiyuError("E_TYPE", f"日期加 的单位只能是 日/月/年，得到「{unit}」", line, fix="...")
        return out.isoformat()
    if name == "日期差":
        a = parse_date(_need_str(v[0], name, line), line)
        b = parse_date(_need_str(v[1], name, line), line)
        return Decimal((a - b).days)
    if name == "文件存在":
        rel = norm_rel(_need_str(v[0], name, line), line)
        require_cap(ctx, "读", rel, line, f"读 {rel}")
        return (ctx.root / rel).exists()
    if name == "文件大小":
        rel = norm_rel(_need_str(v[0], name, line), line)
        require_cap(ctx, "读", rel, line, f"读 {rel}")
        f = ctx.root / rel
        if not f.is_file():
            raise QiyuError("E_FILE_NOT_FOUND", f"找不到文件 {rel}", line, fix="...")
        return Decimal(f.stat().st_size)
    if name == "取列":
        tb = v[0]
        if not isinstance(tb, Table):
            raise QiyuError("E_TYPE", f"取列 的对象应是表格，得到 {type_name(tb)}", line, fix="...")
        cols = [_need_str(x, name, line) for x in v[1:]]
        for c in cols:
            if c not in tb.columns:
                raise QiyuError("E_TYPE", f"表格没有列「{c}」", line, fix="检查列名")
        rows = [{c: r.get(c, "") for c in cols} for r in tb.rows]
        return Table(cols, rows)
    if name == "读文本":
        rel = norm_rel(_need_str(v[0], name, line), line)
        require_cap(ctx, "读", rel, line, f"读 {rel}")
        f = ctx.root / rel
        if not f.is_file():
            raise QiyuError("E_FILE_NOT_FOUND", f"找不到文件 {rel}", line, fix="确认文件存在")
        return f.read_text(encoding="utf-8-sig")
    if name == "列目录":
        rel = norm_rel(_need_str(v[0], name, line), line)
        files = set()
        for pattern in ({rel, rel.replace("**/", "")} if "**/" in rel else {rel}):
            try:
                files |= {x for x in ctx.root.glob(pattern) if x.is_file()}
            except (ValueError, OSError):
                pass
        files = sorted(files, key=lambda p: p.relative_to(ctx.root).as_posix())
        if not files:
            raise QiyuError("E_FILE_NOT_FOUND", f"模式 {rel} 没有匹配到文件", line,
                            fix="确认文件存在，或放宽模式（** 可递归匹配子目录）")
        out = []
        for f in files:
            frel = f.relative_to(ctx.root).as_posix()
            require_cap(ctx, "读", frel, line, f"读 {frel}")
            out.append({"路径": frel, "名字": f.name, "大小": Decimal(f.stat().st_size)})
        return out
    if name == "分割":
        s = _need_str(v[0], name, line)
        sep = _need_str(v[1], name, line)
        return s.split(sep)
    if name == "取段":
        s = _need_str(v[0], name, line)
        sep = _need_str(v[1], name, line)
        idx = int(_need_num(v[2], name, line))
        parts = s.split(sep)
        return parts[idx - 1] if 1 <= idx <= len(parts) else ""
    if name == "查找":
        tb = v[0]
        if not isinstance(tb, Table):
            raise QiyuError("E_TYPE", f"查找 的对象应是表格，得到 {type_name(tb)}", line, fix="...")
        col = _need_str(v[1], name, line)
        if col not in tb.columns:
            raise QiyuError("E_TYPE", f"表格没有列「{col}」", line, fix="检查列名")
        for r in tb.rows:
            if r.get(col) == v[2]:
                return dict(r)
        return None
    if name == "为空":
        return v[0] is None or v[0] == ""
    if name == "不为空":
        return not (v[0] is None or v[0] == "")
    if name == "绝对值":
        return abs(_need_num(v[0], name, line))
    if name == "读记录":
        rel = norm_rel(_need_str(v[0], name, line), line)
        require_cap(ctx, "读", rel, line, f"读 {rel}")
        f = ctx.root / rel
        if not f.is_file():
            raise QiyuError("E_FILE_NOT_FOUND", f"找不到文件 {rel}", line, fix="确认文件存在")
        try:
            return wrap_json(json.loads(f.read_text(encoding="utf-8-sig")))
        except Exception as ex:
            raise QiyuError("E_TYPE", f"{rel} 不是合法 JSON：{ex}", line, fix="检查 JSON 语法")
    if name == "列表成表格":
        items = v[0]
        if not isinstance(items, list):
            raise QiyuError("E_TYPE", f"列表成表格 的实参应是列表，得到 {type_name(items)}",
                            line, fix="读记录 返回的列表可直接转换")
        cols = []
        for it in items:
            if isinstance(it, dict):
                for k in it:
                    if k not in cols:
                        cols.append(k)
        rows = [{c: it.get(c, "") for c in cols} for it in items if isinstance(it, dict)]
        return Table(cols, rows)
    if name == "含":
        return _need_str(v[1], name, line) in _need_str(v[0], name, line)
    if name == "连接":
        a, b = v[0], v[1]
        if not (isinstance(a, Table) and isinstance(b, Table)):
            raise QiyuError("E_TYPE", "连接(表格甲, 表格乙)", line, fix="...")
        if a.columns != b.columns:
            raise QiyuError("E_TYPE", f"连接 的两表列不一致", line,
                            fix=f"甲={a.columns} 乙={b.columns}")
        return Table(a.columns, a.rows + b.rows)
    if name == "去重":
        tb = v[0]
        if not isinstance(tb, Table):
            raise QiyuError("E_TYPE", f"去重 的对象应是表格，得到 {type_name(tb)}", line, fix="...")
        seen, rows = set(), []
        for r in tb.rows:
            key = tuple((type(r.get(c)).__name__, str(r.get(c, ""))) for c in tb.columns)
            if key not in seen:
                seen.add(key)
                rows.append(r)
        return Table(tb.columns, rows)
    if name == "标准日期":
        s = _need_str(v[0], name, line).strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                return _datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                pass
        raise QiyuError("E_TYPE", f"「{s}」不是可识别的日期", line,
                        fix="支持 2024-06-01 / 20240601 / 2024/6/1")
    if name == "格式日期":
        s = _need_str(v[0], name, line).strip()
        d0 = None
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                d0 = _datetime.strptime(s, fmt).date()
                break
            except ValueError:
                pass
        if d0 is None:
            raise QiyuError("E_TYPE", f"「{s}」不是可识别的日期", line,
                            fix="支持 2024-06-01 / 20240601 / 2024/6/1")
        mode = _need_str(v[1], name, line)
        return (mode.replace("YYYY", f"{d0.year:04d}").replace("MM", f"{d0.month:02d}")
                    .replace("DD", f"{d0.day:02d}").replace("M", str(d0.month))
                    .replace("D", str(d0.day)))
    if name == "净化文件名":
        return re.sub(r'[/\\:*?"<>|]', "_", _need_str(v[0], name, line))
    if name == "空表":
        cols = [_need_str(x, name, line) for x in v]
        return Table(cols, [])
    if name == "加入行":
        tb, row = v[0], v[1]
        if not isinstance(tb, Table) or not isinstance(row, list):
            raise QiyuError("E_TYPE", f"加入行(表格, 列表) 得到 {type_name(tb)}/{type_name(row)}",
                            line, fix="行值写成 [值1, 值2, …]")
        if len(row) != len(tb.columns):
            raise QiyuError("E_TYPE", f"该表有 {len(tb.columns)} 列，提供了 {len(row)} 个值",
                            line, fix="值的个数须与建表时一致")
        return Table(tb.columns, tb.rows + [{c: x for c, x in zip(tb.columns, row)}])
    raise QiyuError("E_INTERNAL", f"未知内建 {name}")


def interp_summary(e, env, ctx):
    tb = interp_expr(e["table"], env, ctx)
    if not isinstance(tb, Table):
        raise QiyuError("E_TYPE", f"汇总 的对象应是表格，得到 {type_name(tb)}", e["line"], fix="...")
    by = e["by"]
    groups = {}
    for row in tb.rows:
        if by not in row:
            raise QiyuError("E_TYPE", f"表格没有列「{by}」", e["line"],
                            fix="检查 汇总…按 的列名")
        groups.setdefault(row[by], []).append(row)
    cols = [by] + [n for n, _, _ in e["entries"]]
    out = []
    for key, grp in groups.items():
        d = {by: key}
        for name, agg, col in e["entries"]:
            if agg == "计数":
                d[name] = Decimal(len(grp))
                continue
            vals = [r[col] for r in grp if isinstance(r.get(col), Decimal)]
            if agg == "求和":
                d[name] = sum(vals, Decimal(0))
            elif agg == "平均":
                d[name] = sum(vals, Decimal(0)) / Decimal(len(vals)) if vals else Decimal(0)
            elif agg == "最小":
                d[name] = min(vals) if vals else Decimal(0)
            else:
                d[name] = max(vals) if vals else Decimal(0)
        out.append(d)
    return Table(cols, out)


def interp_filter(e, env, ctx):
    tb = interp_expr(e["table"], env, ctx)
    if not isinstance(tb, Table):
        raise QiyuError("E_TYPE", f"筛选 的对象应是表格，得到 {type_name(tb)}", e["line"], fix="...")
    rows = []
    for row in tb.rows:
        env2 = dict(env)
        env2["行"] = RowNS(row)
        if truthy(interp_expr(e["cond"], env2, ctx)):
            rows.append(row)
    return Table(tb.columns, rows)


def interp_derive(e, env, ctx):
    tb = interp_expr(e["table"], env, ctx)
    if not isinstance(tb, Table):
        raise QiyuError("E_TYPE", f"派生 的对象应是表格，得到 {type_name(tb)}", e["line"], fix="...")
    new_cols = [n for n, _ in e["entries"]]
    rows = []
    for row in tb.rows:
        env2 = dict(env)
        env2["行"] = RowNS(row)
        d = dict(row)
        for name, ex in e["entries"]:
            d[name] = interp_expr(ex, env2, ctx)
        rows.append(d)
    return Table(tb.columns + new_cols, rows)


def interp_sort(e, env, ctx):
    tb = interp_expr(e["table"], env, ctx)
    if not isinstance(tb, Table):
        raise QiyuError("E_TYPE", f"排列 的对象应是表格，得到 {type_name(tb)}", e["line"], fix="...")
    rows = list(tb.rows)
    for col, direction in reversed(e["keys"]):
        try:
            rows.sort(key=lambda r: r.get(col, ""), reverse=(direction == "降序"))
        except TypeError:
            raise QiyuError("E_TYPE", f"列「{col}」混有不同类型的值，无法排序", e["line"],
                            fix="统一该列类型（清洗），或改用其他列排序")
    return Table(tb.columns, rows)


def kwarg(e, name, line, required=True):
    for a in e["args"]:
        if a[0] == "kw" and a[1] == name:
            return a[2]
    if required:
        raise QiyuError("E_TYPE", f"{e['name']} 缺少实参「{name}」", line,
                        fix=f"写成 {name}=值")
    return None


def interp_opt(node, env, ctx, default=""):
    return interp_expr(node, env, ctx) if node is not None else default


def interp_effect(st, env, ctx):
    name = st["name"]
    if name == "存表格":
        tb = interp_expr(st["args"][0][1], env, ctx)
        if not isinstance(tb, Table):
            raise QiyuError("E_TYPE", f"存表格 需要表格，得到 {type_name(tb)}", st["line"], fix="...")
        p = interp_expr(st["args"][1][1], env, ctx)
        if not isinstance(p, str):
            raise QiyuError("E_TYPE", f"存表格 的路径应是文本，得到 {type_name(p)}", st["line"], fix="...")
        rel = norm_rel(p, st["line"])
        require_cap(ctx, "写", rel, st["line"], f"写 {rel}")
        if ctx.mode == "dry_all":
            ctx.records.append({"种类": "写", "动作": "预报", "路径": rel})
            return
        write_csv_table(tb, ctx.root / rel)
        ctx.records.append({"种类": "写", "动作": "执行", "路径": rel})
        return
    if name == "发邮件":
        to = interp_expr(kwarg(st, "收件", st["line"]), env, ctx)
        subject = interp_opt(kwarg(st, "主题", st["line"], False), env, ctx)
        body = interp_opt(kwarg(st, "正文", st["line"], False), env, ctx)
        attach = interp_opt(kwarg(st, "附件", st["line"], False), env, ctx)
        for v, label in ((to, "收件"), (subject, "主题"), (attach, "附件")):
            if not isinstance(v, str):
                raise QiyuError("E_TYPE", f"发邮件 的「{label}」应是文本，得到 {type_name(v)}",
                                st["line"], fix="...")
        require_cap(ctx, "发邮件", to, st["line"], f"发邮件 给 {to}")
        action = "预报" if ctx.mode in ("dry", "dry_all") else "执行（mock）"
        ctx.records.append({"种类": "发邮件", "动作": action, "收件": to,
                            "主题": subject, "附件": attach, "正文": body})
        return
    if name == "发消息":
        to = interp_expr(kwarg(st, "到", st["line"]), env, ctx)
        content = interp_expr(kwarg(st, "内容", st["line"]), env, ctx) or ""
        if not isinstance(to, str) or not isinstance(content, str):
            raise QiyuError("E_TYPE", "发消息 的 到/内容 应是文本", st["line"], fix="...")
        require_cap(ctx, "发消息", to, st["line"], f"发消息 到 {to}")
        action = "预报" if ctx.mode in ("dry", "dry_all") else "执行（mock）"
        ctx.records.append({"种类": "发消息", "动作": action, "到": to, "内容": content})
        return
    if name in ("复制文件", "移动文件", "写文本"):
        return do_file_effect(st, env, ctx)
    if name == "存JSON":
        return do_save_json(st, env, ctx)
    if name == "请求":
        return do_request(st, env, ctx)
    if name == "分页请求":
        return do_paged_request(st, env, ctx)
    raise QiyuError("E_INTERNAL", f"未知效果 {name}")


def do_file_effect(st, env, ctx):
    vals = [interp_expr(a[1], env, ctx) for a in st["args"]]
    if len(vals) != 2 or not isinstance(vals[0], str) or not isinstance(vals[1], str):
        raise QiyuError("E_TYPE", "路径/文本 实参应是文本", st["line"],
                        fix="写成 复制文件 源 到 目标 / 写文本 内容 到 路径")
    a, b = vals
    line = st["line"]
    if st["name"] == "写文本":
        rel = norm_rel(b, line)
        require_cap(ctx, "写", rel, line, f"写 {rel}")
        if ctx.mode == "dry_all":
            ctx.records.append({"种类": "写", "动作": "预报", "路径": rel})
            return
        dest = ctx.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(a, encoding="utf-8")
        ctx.records.append({"种类": "写", "动作": "执行", "路径": rel})
        return
    # 复制文件 / 移动文件（源支持通配 → 批量；目标以 / 结尾 = 目录）
    src_rel = norm_rel(a, line)
    is_glob = any(ch in src_rel for ch in "*?[")
    if is_glob:
        matches = sorted(x for x in ctx.root.glob(src_rel) if x.is_file())
        matches = [m for m in matches if m.exists()]
        if not matches:
            raise QiyuError("E_FILE_NOT_FOUND", f"模式 {src_rel} 没有匹配到文件", line,
                            fix="确认源文件存在")
    else:
        f0 = ctx.root / src_rel
        if not f0.is_file():
            raise QiyuError("E_FILE_NOT_FOUND", f"找不到 {src_rel}", line, fix="确认源文件存在")
        matches = [f0]
    dst_rel = norm_rel(b, line)
    for f in matches:
        s_rel = f.relative_to(ctx.root).as_posix()
        if st["name"] == "移动文件":
            require_cap(ctx, "写", s_rel, line, f"写 {s_rel}")  # 移动要删除源
        require_cap(ctx, "读", s_rel, line, f"读 {s_rel}")
        dest = dst_rel if (not is_glob and not dst_rel.endswith("/")) else dst_rel + f.name
        require_cap(ctx, "写", dest, line, f"写 {dest}")
        if ctx.mode == "dry_all":
            ctx.records.append({"种类": "写", "动作": "预报", "路径": dest})
            continue
        (ctx.root / dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, ctx.root / dest)
        if st["name"] == "移动文件":
            f.unlink()
        ctx.records.append({"种类": "写", "动作": "执行", "路径": dest})


def row_json(r, cols):
    out = {}
    for c in cols:
        v = r.get(c, "")
        if v is None or v == "":
            out[c] = None
        elif isinstance(v, bool):
            out[c] = v
        elif isinstance(v, Decimal):
            out[c] = int(v) if v == v.to_integral_value() else float(v)
        else:
            out[c] = v
    return out


def do_save_json(st, env, ctx):
    line = st["line"]
    vals = [interp_expr(a[1], env, ctx) for a in st["args"]]
    if (len(vals) != 3 or not isinstance(vals[0], Table)
            or not isinstance(vals[1], str) or not isinstance(vals[2], str)):
        raise QiyuError("E_TYPE", '存JSON 表格 "包裹键" 到 路径', line,
                        fix='存JSON 漏斗 "阶段" 到 "~/funnel.json"')
    tb, wrap_key, p = vals
    rel = norm_rel(p, line)
    require_cap(ctx, "写", rel, line, f"写 {rel}")
    if ctx.mode == "dry_all":
        ctx.records.append({"种类": "写", "动作": "预报", "路径": rel})
        return
    data = {wrap_key: [row_json(r, tb.columns) for r in tb.rows]}
    dest = ctx.root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ctx.records.append({"种类": "写", "动作": "执行", "路径": rel})


def do_request(st, env, ctx):
    url = interp_expr(kwarg(st, "网址", st["line"]), env, ctx)
    method = interp_opt(kwarg(st, "方法", st["line"], False), env, ctx, "GET")
    if not isinstance(url, str) or not isinstance(method, str):
        raise QiyuError("E_TYPE", "请求 的 网址/方法 应是文本", st["line"], fix="...")
    require_cap(ctx, "请求", url, st["line"], f"请求 {url}")
    status, body = 200, None
    mp = ctx.root / "_mock_api.json"
    if mp.exists():
        entries = json.loads(mp.read_text(encoding="utf-8"))
        for entry in entries:
            if url.startswith(entry["url_prefix"]):
                idx = entry.get("_i", 0)
                body = entry["responses"][min(idx, len(entry["responses"]) - 1)]
                entry["_i"] = idx + 1
                break
        else:
            status, body = 404, {"错误": "mock 未配置该 URL"}
    action = "预报" if ctx.mode in ("dry", "dry_all") else "执行（mock）"
    ctx.records.append({"种类": "请求", "动作": action, "方法": method, "网址": url, "状态": status})
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    try:
        data = json.loads(text) if isinstance(body, str) else body
    except Exception:
        data = None
    return RespNS(status, text, data)


def exec_stmt(st, env, ctx):
    """执行一条语句；返回非 None 表示工具返回。作用域共享（块内赋值对外可见）。"""
    t = st["t"]
    if t == "assign":
        ex = st["expr"]
        env[st["name"]] = (interp_effect(ex, env, ctx)
                           if ex.get("t") == "effectcall" else interp_expr(ex, env, ctx))
        return None
    if t == "effect":
        interp_effect(st, env, ctx)
        return None
    if t == "loop":
        seq = interp_expr(st["seq"], env, ctx)
        if isinstance(seq, Table):
            items = seq.rows
        elif isinstance(seq, list):
            items = seq
        else:
            raise QiyuError("E_TYPE", f"对每个 只能遍历 表格/列表，得到 {type_name(seq)}",
                            st["line"], fix="表格用 列目录/读表格 产生；遍历 行.列名 取成员")
        had, old = st["var"] in env, env.get(st["var"])
        try:
            for item in items:
                env[st["var"]] = dict(item) if isinstance(item, dict) else wrap_json(item)
                r = exec_stmts(st["body"], env, ctx)
                if r is not None:
                    return r
        finally:
            if had:
                env[st["var"]] = old
            else:
                env.pop(st["var"], None)
        return None
    if t == "if":
        if truthy(interp_expr(st["cond"], env, ctx)):
            return exec_stmts(st["then"], env, ctx)
        return exec_stmts(st["else"], env, ctx)
    raise QiyuError("E_INTERNAL", f"未知语句 {t}")


def exec_stmts(stmts, env, ctx):
    for st in stmts:
        r = exec_stmt(st, env, ctx)
        if r is not None:
            return r
    return None


def do_paged_request(st, env, ctx):
    """分页请求：网址模板用 {页} 作页码占位，按 响应.数据.has_more 判断终止，拼接列表为表格。"""
    line = st["line"]
    vals = [interp_expr(a[1], env, ctx) for a in st["args"] if a[0] == "pos"]
    if len(vals) != 2 or not isinstance(vals[0], str) or not isinstance(vals[1], str):
        raise QiyuError("E_TYPE", "分页请求(网址模板, 列表键)", line,
                        fix='分页请求("https://…/orders?page={页}&size=100", "orders")')
    tpl, list_key = vals
    mp = ctx.root / "_mock_api.json"
    entries = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else []
    cols, rows, page = [], [], 1
    while page <= 999:
        url = tpl.replace("{页}", str(page))
        require_cap(ctx, "请求", url, line, f"请求 {url}")
        status, body = 200, None
        for entry in entries:
            if url.startswith(entry["url_prefix"]):
                idx = entry.get("_i", 0)
                body = entry["responses"][min(idx, len(entry["responses"]) - 1)]
                entry["_i"] = idx + 1
                break
        else:
            status, body = 404, {}
        action = "预报" if ctx.mode in ("dry", "dry_all") else "执行（mock）"
        ctx.records.append({"种类": "请求", "动作": action, "方法": "GET",
                            "网址": url, "状态": status})
        if status != 200 or not isinstance(body, dict):
            break
        for it in body.get(list_key, []):
            if isinstance(it, dict):
                for k in it:
                    if k not in cols:
                        cols.append(k)
                rows.append({k: wrap_json(v) for k, v in it.items()})
        if not truthy(wrap_json(body.get("has_more", False))):
            break
        page += 1
    if page > 999:
        raise QiyuError("E_TYPE", "分页超过 999 页，疑似终止条件错误", line,
                        fix="检查数据源 has_more 字段")
    return Table(cols, rows)


def run_tool(tool, params, root: Path, mode):
    caps = static_check(tool)
    params = dict(params)
    for st in tool["body"]:  # 应用参数默认值（v1.7.1：之前只解析未注入）
        if st["t"] == "param" and st["name"] not in params and st["default"] is not None:
            params[st["name"]] = st["default"]
    records = []
    ctx = Ctx(root, caps, mode, records)
    env = {"参数": ParamNS(params)}
    returned = None
    for st in tool["body"]:
        t = st["t"]
        if t in ("param", "cap", "doc", "guarantee"):
            continue
        if t == "return":
            returned = interp_expr(st["expr"], env, ctx)
            break
        r = exec_stmt(st, env, ctx)
        if r is not None:
            returned = r
            break
    for st in tool["body"]:
        if st["t"] != "guarantee":
            continue
        env2 = dict(env)
        if returned is not None:
            env2["返回值"] = returned
        if not truthy(interp_expr(st["expr"], env2, ctx)):
            raise QiyuError("E_CONTRACT_FAILED", f"第 {st['line']} 行的 保证 不成立", st["line"],
                            fix="检查输入数据，或修正/放宽该 保证 表达式")
    return returned, records, caps


def summarize(v):
    if isinstance(v, Table):
        return {"类型": "表格", "行数": v.行数, "列": v.columns}
    if isinstance(v, bool):
        return "真" if v else "假"
    if is_num(v):
        return str(to_dec(v))
    return v


# ---------------------------------------------------------------- 审计包
def audit_package(tool, caps):
    sends = [st for st in tool["body"]
             if st["t"] == "effect" and st["name"] in ("发邮件", "发消息", "请求")]
    writes = ("写" in caps) or any(
        st["t"] == "effect" and st["name"] == "存表格" for st in tool["body"])
    risk = "高" if sends else ("中" if writes else "低")
    doc = next((st["text"] for st in tool["body"] if st["t"] == "doc"), "（未提供说明）")
    params = [st["name"] for st in tool["body"] if st["t"] == "param"]
    return {
        "工具": tool["name"],
        "说明": doc,
        "参数": params,
        "能力清单": [{"种类": k, "范围": p} for k, ps in sorted(caps.items()) for p in ps],
        "外发动作": [{"调用": s["name"], "行": s["line"]} for s in sends],
        "保证条数": sum(1 for st in tool["body"] if st["t"] == "guarantee"),
        "风险分级": risk,
        "静态检查": "通过",
    }


# ---------------------------------------------------------------- 对外 API / CLI
def run_source(src, params=None, root="home", mode="normal"):
    tool = parse_source(src)
    returned, records, caps = run_tool(tool, params or {}, Path(root), mode)
    return {"结果": summarize(returned),
            "审计": {"工具": tool["name"], "模式": mode, "参数": params or {},
                     "操作记录": records, "风险分级": audit_package(tool, caps)["风险分级"]}}


def run_file(path, params=None, root="home", mode="normal"):
    return run_source(Path(path).read_text(encoding="utf-8"), params, root, mode)


def coerce(s):
    if s == "真":
        return True
    if s == "假":
        return False
    if NUM_RE.fullmatch(s):
        return Decimal(s)
    return s


def main(argv):
    try:  # 独立 exe（PyInstaller 打包）下也强制 UTF-8 输出
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(argv) < 2 or argv[1] not in ("check", "run"):
        print("用法：python -X utf8 qiyu.py check FILE | run FILE [--根 DIR] "
              "[--参数 k=v ...] [--试运行 [全部]] [--审计 FILE]")
        return 2
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("file")
    ap.add_argument("--根", default="home")
    ap.add_argument("--参数", action="append", default=[])
    ap.add_argument("--试运行", nargs="?", const="dry", default=None)
    ap.add_argument("--审计")
    a = ap.parse_args(argv[2:])
    params = {}
    for kv in a.参数:
        if "=" not in kv:
            print(f"[E_PARAM_MISSING] --参数 需要 k=v 形式，得到 {kv!r}", file=sys.stderr)
            return 1
        k, v = kv.split("=", 1)
        params[k] = coerce(v)
    try:
        if argv[1] == "check":
            tool = parse_file(a.file)
            caps = static_check(tool)
            print(json.dumps(audit_package(tool, caps), ensure_ascii=False, indent=2))
        else:
            mode = "normal" if a.试运行 is None else ("dry_all" if a.试运行 == "全部" else "dry")
            tool = parse_file(a.file)
            returned, records, caps = run_tool(tool, params, Path(a.根), mode)
            audit = {"工具": tool["name"], "模式": mode, "参数": params,
                     "操作记录": records, "结果": summarize(returned)}
            out = json.dumps(audit, ensure_ascii=False, indent=2, default=str)
            if a.审计:
                Path(a.审计).parent.mkdir(parents=True, exist_ok=True)
                Path(a.审计).write_text(out, encoding="utf-8")
            print(out)
        return 0
    except QiyuError as e:
        print(e.human(), file=sys.stderr)
        print(json.dumps(e.json(), ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
