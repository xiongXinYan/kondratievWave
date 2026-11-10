#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结构自检：只检查形式与引用，不参与研究判断。

用法：
    python scripts/check.py

检查项：
  1. 研究文件是否含规定的十节结构
  2. 「反对证据」是否至少 3 条、「结论失效条件」是否至少 2 条（不得留空）
  3. 内部 Markdown 引用是否可解析
  4. 是否出现已禁用的表述（概率断言、精确拐点年份）
  5. 归因等级是否残留「A（偏 B）」这类模糊写法
  6. 含「结论失效条件」的研究文件是否已在假设台账登记（覆盖率）

退出码：0 无 error；1 存在 error。
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED_SECTIONS = [
    "核心结论", "支持证据", "反对证据", "关键数据",
    "当前判断", "未来观察指标", "结论失效条件", "参考来源",
]

# 非研究文件：索引、模板、迁移说明、复盘记录、台账
EXCLUDE_NAMES = {
    "README.md", "CHANGELOG.md", "MIGRATION.md",
    "data-sources.md", "books.md", "academic-papers.md",
    "research-template.md", "monthly-review.md", "quarterly-review.md",
    "assumptions-ledger.md",
}

BANNED_PATTERNS = [
    (re.compile(r"\d{4}\s*[–\-~]\s*\d{4}\s*进入"), "精确年份区间断言"),
    (re.compile(r"必然(会|将|进入|发生)"), "确定性断言"),
    (re.compile(r"概率\s*(为|是)\s*\d+"), "数值概率断言"),
    (re.compile(r"[ABC]\s*（偏\s*[ABC]）"), "归因等级括号模糊写法"),
]

# 这些词出现在同一行时，说明是在描述"已删除/已禁止"的内容，不是真的在用
NEGATION_HINTS = ("删除", "移除", "原写", "原文", "不再", "禁止", "禁用",
                  "而非", "不是", "不得", "不许", "已改", "改为", "去模糊", "旧稿")

# 历史记录与模板占位：允许引用已删除的文件
LINK_EXEMPT_NAMES = {"MIGRATION.md", "CHANGELOG.md",
                     "monthly-review.md", "quarterly-review.md"}

errors = []
warnings = []
has_fail_cond = []  # 含「结论失效条件」的研究文件，用于台账覆盖率检查

LEDGER = os.path.join(ROOT, "08-monitoring", "assumptions-ledger.md")


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def collect_md():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in {".git", ".idea", ".workbuddy", "node_modules"}]
        for fn in filenames:
            if fn.endswith(".md"):
                out.append(os.path.join(dirpath, fn))
    return out


def is_research(path):
    name = os.path.basename(path)
    if name in EXCLUDE_NAMES or name.startswith("_legacy"):
        return False
    relpath = rel(path)
    if relpath.startswith("templates/"):
        return False
    if relpath.startswith("08-monitoring/reviews/"):
        return False
    return True


def strip_code_blocks(text):
    return re.sub(r"```.*?```", "", text, flags=re.S)


def section_body(text, title):
    """取某个二级标题下的内容，直到下一个二级标题。"""
    m = re.search(r"^##[^#].*?" + re.escape(title) + r".*?$", text, flags=re.M)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^##[^#]", rest, flags=re.M)
    return rest[: nxt.start()] if nxt else rest


def count_table_rows(body):
    return len(re.findall(r"^\|\s*\d+\s*\|", body, flags=re.M))


def count_numbered(body):
    return len(re.findall(r"^\s*\d+\.\s+\S", body, flags=re.M))


def main():
    files = collect_md()
    all_basenames = {os.path.basename(f) for f in files}

    for path in sorted(files):
        raw = open(path, encoding="utf-8").read()
        text = strip_code_blocks(raw)
        name = rel(path)

        # 1-2 结构检查
        if is_research(path):
            for sec in REQUIRED_SECTIONS:
                body = section_body(text, sec)
                if body is None:
                    errors.append(f"{name}: 缺少章节「{sec}」")
                    continue
                if "反对证据" in sec and count_table_rows(body) < 3:
                    warnings.append(f"{name}: 「反对证据」不足 3 条（当前 {count_table_rows(body)}）")
                if "结论失效条件" in sec and count_numbered(body) < 2:
                    errors.append(f"{name}: 「结论失效条件」不足 2 条或为空")
            has_fail_cond.append(name)

        # 3 内部引用
        if not (os.path.basename(path) in LINK_EXEMPT_NAMES or name.split("/")[-1].startswith("_legacy")):
            for m in re.finditer(r"([\w\-./]+\.md)", text):
                target = m.group(1)
                if target.startswith("http"):
                    continue
                if os.path.basename(target) not in all_basenames:
                    errors.append(f"{name}: 引用了不存在的文件 `{target}`")

        # 4 禁用表述 / 5 归因模糊（存档文件豁免：其价值就在于保留原始表述）
        if not name.split("/")[-1].startswith("_legacy"):
            for pat, label in BANNED_PATTERNS:
                for m in pat.finditer(text):
                    line_start = text.rfind("\n", 0, m.start()) + 1
                    line_end = text.find("\n", m.end())
                    line = text[line_start: line_end if line_end != -1 else len(text)]
                    if any(h in line for h in NEGATION_HINTS):
                        continue
                    lineno = text[: m.start()].count("\n") + 1
                    warnings.append(f"{name}:{lineno}: 命中「{label}」→ {m.group(0)!r}")

    # 6 台账覆盖率：含「结论失效条件」的研究文件必须已在台账登记
    if not os.path.exists(LEDGER):
        errors.append("缺少 08-monitoring/assumptions-ledger.md，失效条件无处登记")
        ledger_entries = 0
    else:
        ledger_text = open(LEDGER, encoding="utf-8").read()
        ledger_names = {os.path.basename(t) for t in re.findall(r"[\w\-./]+\.md", ledger_text)}
        ledger_entries = len(re.findall(r"^\|\s*[THAMPS]-\d{3}\s*\|", ledger_text, flags=re.M))
        for name in has_fail_cond:
            if os.path.basename(name) not in ledger_names:
                errors.append(f"{name}: 含「结论失效条件」但未在 assumptions-ledger.md 登记")

    print(f"扫描 {len(files)} 个 Markdown 文件 · 台账 {ledger_entries} 条断言 · 需登记文件 {len(has_fail_cond)} 个\n")

    if errors:
        print(f"ERROR ({len(errors)})")
        for e in dict.fromkeys(errors):
            print("  ✗", e)
        print()
    if warnings:
        print(f"WARN ({len(warnings)})")
        for w in dict.fromkeys(warnings):
            print("  !", w)
        print()
    if not errors and not warnings:
        print("全部通过。")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
