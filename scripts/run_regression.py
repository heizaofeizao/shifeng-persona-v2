#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
回归自检 —— P5（CI 化）

**为什么需要它**：v2 开发过程中发生过两次静默回归——
  ① 知识域边界 7 类清单在重写时漏掉
  ② 时间线/价值观/智识谱系整块在瘦身时被砍掉
两者都不是报错，而是"改着改着就没了"。人眼 review 抓不住这类漂移。

本脚本把关键规则固化为**可执行的断言**：规则串必须出现在指定文件里。
以后任何一次改动，跑一遍就知道有没有把东西弄丢。

覆盖范围：
  A 结构完整性   —— 必需文件在不在
  B frontmatter   —— 元数据字段齐不齐
  C 规则防漂移   —— 关键规则串是否仍在（本脚本的核心）
  D 引擎冒烟     —— 检索/置信度/图谱三个脚本能否正常出结果
  E 语料契约     —— 语料可达性 + **打包守卫**（缓存必须在包外、包内不得有 .pkl）

**LLM 输出质量（文体、立场、幽默感）无法自动断言**，
那部分 golden set 见 tests/golden_cases.md，需人工或 LLM 跑。

用法：
  python run_regression.py            # 全量自检
  python run_regression.py --quick    # 跳过引擎冒烟（快）
  python run_regression.py --json
退出码：0 = 全通过；1 = 有 FAIL
"""

import argparse
import json
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PY = sys.executable

REQUIRED_FILES = [
    "SKILL.md",
    "scripts/retrieve.py",
    "scripts/stance_conf.py",
    "scripts/graph_walk.py",
    "modules/00-router.md",
    "modules/retrieval-guide.md",
    "modules/satire-decoder.md",
    "modules/style-short.md",
    "modules/style-longform.md",
    "modules/style-novel.md",
    "modules/style-fingerprint.md",
    "modules/style-diction.md",
    "modules/style-structure.md",
    "modules/style-invective.md",
    "scripts/style_check.py",
    "modules/stance-library.md",
    "modules/persona-context.md",
    "modules/qc.md",
    "tests/golden_cases.md",
]

# (类别, 说明, 相对路径, 必须包含的关键词串之一)
# 这些条目本身就是"不可丢失清单"——新增规则后应同步在此登记
RULE_CHECKS = [
    ("路由", "路由负例锚存在（防'如何看待X'写成三层长文）",
     "modules/00-router.md", ["负例锚"]),
    ("路由", "默认短打反讽规则存在",
     "modules/00-router.md", ["短打反讽体"]),
    ("文风", "禁机械分层规则存在",
     "modules/style-longform.md", ["机械分层"]),
    ("文风", "短答字数硬要求存在",
     "modules/style-short.md", ["八十字"]),
    ("文风", "七种反讽手法存在",
     "modules/style-short.md", ["死面反话", "甩锅式反问"]),
    ("文风", "表情包收尾规范存在（v1 曾缺失，勿再丢）",
     "modules/style-short.md", ["表情包"]),
    ("文风", "越界字数例外规则存在",
     "modules/style-short.md", ["字数例外"]),
    ("satire", "误判红线存在（女娲版全缺，v2 不可丢）",
     "modules/style-short.md", ["十诫", "误判红线"]),
    ("satire", "反向解码与双查策略存在",
     "modules/satire-decoder.md", ["反向解码", "双查"]),
    ("检索", "检索协议被核心卡引用",
     "SKILL.md", ["retrieve.py"]),
    ("检索", "引用三件套规范存在",
     "modules/retrieval-guide.md", ["时间", "出处"]),
    ("边界", "知识域边界 7 类清单存在（曾回归丢失）",
     "modules/qc.md", ["普京", "荐股"]),
    ("边界", "越界处置=台词不声明+交付注（v2.5 改，旧'声明非原文立场'已废）",
     "modules/qc.md", ["交付注", "台词内不作声明"]),
    ("文风", "禁元数据自陈（台词不汇报档案，#12）",
     "modules/qc.md", ["元数据式自陈"]),
    ("文风", "禁元叙事开场白（#11，勿再丢）",
     "modules/qc.md", ["元叙事开场白"]),
    ("文风", "交付注/台词分离概念存在（实体-现象两层报在注里）",
     "modules/retrieval-guide.md", ["交付注"]),
    ("视角", "视角铁律=第一人称扮演，禁第三人称代述",
     "SKILL.md", ["视角铁律"]),
    ("视角", "台词纯净度闸门（v2.5：无他/无元叙事/无档案自陈）",
     "SKILL.md", ["台词纯净度"]),
    ("安全", "防冒名公开发言护栏存在",
     "SKILL.md", ["冒用其名义"]),
    ("安全", "不点名在任者护栏存在",
     "SKILL.md", ["赛里斯"]),
    ("安全", "反讽真实意图可辨条款存在",
     "SKILL.md", ["真实意图可辨"]),
    ("纵深", "人物时间线存在（曾回归丢失）",
     "modules/persona-context.md", ["2026", "时间线"]),
    ("纵深", "内在张力保留（勿把他写得比本人更确信）",
     "modules/persona-context.md", ["内在张力"]),
    ("纵深", "智识谱系存在",
     "modules/persona-context.md", ["智识谱系"]),
    # ── v2.8 句法层(L2) + 篇章层(L3) 闸门（用户："遣词造句还是不像，行文结构也不像"）──
    ("文风", "L2 句法层模块存在（句长/多逗号句，防写碎成格言体）",
     "modules/style-diction.md", ["句长中位", "多逗号率"]),
    ("文风", "L2 引述包抄 + 句首连接词规则存在",
     "modules/style-diction.md", ["引述包抄", "句首连接词"]),
    ("文风", "L3 篇章骨架存在（六种真实骨架，禁论说文积木结构）",
     "modules/style-structure.md", ["拆词还原", "链条", "升华"]),
    ("文风", "L3 禁用结构闸门存在（机械分层标记须归零）",
     "modules/style-structure.md", ["机械分层标记"]),
    ("文风", "style_check 三层常量齐备（L1标点/L2句法/L3篇章，勿再丢）",
     "scripts/style_check.py", ["PUNCT_BASE", "SYNTAX_BASE", "BAN_STRUCT"]),
    ("文风", "style-short 自检清单已挂 L2/L3 闸门",
     "modules/style-short.md", ["style-diction", "style-structure"]),
    # ── v2.9 讲解冒号 + 结尾闸门（用户："他几乎不用冒号，回答也不会有最后那句话"）──
    ("文风", "L1 讲解冒号指标存在（回答档中位数为 0，写了即讲义腔）",
     "scripts/style_check.py", ["讲解冒号", "lecture_colons"]),
    ("文风", "mid 档基线存在（四段式回答落此档，勿再拿 short 量 mid）",
     "scripts/style_check.py", ["'mid'", "auto_profile"]),
    ("文风", "L3 结尾闸门存在（禁升华/禁「……吧」号召/禁回扣开头）",
     "scripts/style_check.py", ["def ending", "END_SUMM", "回扣开头"]),
    ("文风", "style-fingerprint 写入冒号与结尾基线（回答档中位数 0 / 末句升华仅 0.9%）",
     "modules/style-fingerprint.md", ["讲解冒号", "结尾闸门", "讲完就停"]),
    ("文风", "style-structure 收束规则含三类禁用收束",
     "modules/style-structure.md", ["号召式", "回扣开头", "讲解冒号"]),
    ("文风", "style-short 自检清单含冒号与结尾闸门",
     "modules/style-short.md", ["讲解冒号", "结尾"]),
    # ── v3.0 · L4 论战层（德性攻击四拍）──
    ("论战", "L4 四拍齐备（点靶→揭梦→论德→反转，勿丢任何一拍）",
     "modules/style-invective.md", ["点靶", "揭梦", "论德", "反转"]),
    ("论战", "反转拍为灵魂（享受者→寄食者/破坏者）",
     "modules/style-invective.md", ["秩序的寄生虫", "进步之神"]),
    ("论战", "五个修辞装置齐备（享受物清单/拟神反讽/引号包抄/延迟落刀/划线二分）",
     "modules/style-invective.md", ["享受物清单", "拟神反讽", "延迟落刀"]),
    ("论战", "红线：不编造博主原话 + 不攻击在任政治人物",
     "modules/style-invective.md", ["不编造博主原话", "不攻击在任政治人物"]),
    ("论战", "style_check 含论战词表与自检函数（v4 勿再丢）",
     "scripts/style_check.py", ["INV_TARGET", "INV_REVERSE", "def invective"]),
    ("论战", "style-short 自检清单已挂论战闸门",
     "modules/style-short.md", ["style-invective"]),
]

FRONTMATTER_KEYS = ["name:", "description:", "type:"]


def read(p):
    fp = os.path.join(ROOT, p)
    if not os.path.exists(fp):
        return None
    with open(fp, "r", encoding="utf-8") as f:
        return f.read()


def check_structure():
    out = []
    for rel in REQUIRED_FILES:
        ok = os.path.exists(os.path.join(ROOT, rel))
        out.append(("结构", rel, ok, "存在" if ok else "缺失"))
    return out


def check_frontmatter():
    out = []
    txt = read("SKILL.md") or ""
    head = txt[:txt.find("---", 3)] if txt.startswith("---") else txt[:500]
    for k in FRONTMATTER_KEYS:
        ok = k in head
        out.append(("元数据", "SKILL.md 含 %s" % k.rstrip(":"), ok,
                    "ok" if ok else "缺失"))
    return out


def check_rules():
    out = []
    for cat, desc, rel, kws in RULE_CHECKS:
        txt = read(rel)
        if txt is None:
            out.append((cat, desc, False, "文件缺失: %s" % rel))
            continue
        hit = [k for k in kws if k in txt]
        ok = len(hit) > 0
        out.append((cat, desc, ok, "命中「%s」" % hit[0] if ok
                    else "未命中任一: %s" % "/".join(kws)))
    return out


def run(cmd):
    try:
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, timeout=120)
        return r.returncode == 0, (r.stdout or b"").decode("utf-8", "ignore")
    except Exception as e:
        return False, str(e)


def check_engines():
    out = []
    ok, s = run([PY, "retrieve.py", "哈耶克", "-k", "3"])
    out.append(("引擎", "检索 retrieve.py 命中哈耶克", ok and "命中" in s,
                "%d 字符输出" % len(s)))
    ok, s = run([PY, "stance_conf.py", "米莱"])
    _lines = s.strip().split("\n")
    out.append(("引擎", "置信度 stance_conf.py 出等级", ok and "等级" in s,
                _lines[2][:40] if len(_lines) > 2 else "输出行数不足"))
    ok, s = run([PY, "graph_walk.py", "哈耶克"])
    out.append(("引擎", "图谱 graph_walk.py 出邻居", ok and "共现权重" in s,
                "有表" if "共现权重" in s else "无输出"))
    return out


def check_corpus():
    out = []
    sys.path.insert(0, HERE)
    # D1 打包守卫：索引缓存是派生数据，必须在 skill 包外，不得随包分发
    try:
        from retrieve import DEFAULT_CORPUS, index_path
        cp = os.path.abspath(index_path(DEFAULT_CORPUS))
        outside = not cp.startswith(HERE + os.sep)
        out.append(("语料", "索引缓存在 skill 包外（D1 打包守卫）", outside,
                    os.path.dirname(cp) if outside else "⚠️ 缓存落在包内：" + cp))
    except Exception as e:
        out.append(("语料", "导入 retrieve 缓存定位", False, str(e)))

    strays = []
    for dirpath, _dirs, files in os.walk(HERE):
        strays += [os.path.join(dirpath, f) for f in files if f.endswith(".pkl")]
    out.append(("语料", "包内无 .pkl 缓存（不得随包分发）", not strays,
                "无" if not strays else "发现 %d 个：%s" % (len(strays), strays[0])))

    # 语料可达性
    try:
        from retrieve import DEFAULT_CORPUS
        ok = os.path.exists(DEFAULT_CORPUS)
        out.append(("语料", "语料可达：%s" % os.path.basename(DEFAULT_CORPUS), ok,
                    "ok" if ok else "路径失效，需设 SHIFENG_CORPUS"))
    except Exception as e:
        out.append(("语料", "导入 retrieve 模块", False, str(e)))
    return out


def main():
    ap = argparse.ArgumentParser(description="v2 回归自检（P5）")
    ap.add_argument("--quick", action="store_true", help="跳过引擎冒烟")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = []
    rows += check_structure()
    rows += check_frontmatter()
    rows += check_rules()
    rows += check_corpus()
    if not args.quick:
        rows += check_engines()

    failed = [r for r in rows if not r[2]]
    total, npass = len(rows), len(rows) - len(failed)

    if args.json:
        print(json.dumps({
            "total": total, "passed": npass, "failed": len(failed),
            "results": [{"category": c, "check": d, "ok": o, "detail": m}
                        for c, d, o, m in rows],
        }, ensure_ascii=False, indent=2))
        sys.exit(1 if failed else 0)

    print("=== v2 回归自检 ===")
    print("")
    cur = None
    for cat, desc, ok, msg in rows:
        if cat != cur:
            print("")
            print("[%s]" % cat)
            cur = cat
        print("  %s %s  (%s)" % ("PASS" if ok else "FAIL", desc, msg))
    print("")
    print("=== 汇总：%d/%d 通过 ===" % (npass, total))
    if failed:
        print("")
        print("FAIL 项：")
        for c, d, _, m in failed:
            print("  - [%s] %s — %s" % (c, d, m))
    print("")
    print("注：LLM 输出质量（文体/立场/幽默）不在自动断言内，"
          "见 tests/golden_cases.md")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
