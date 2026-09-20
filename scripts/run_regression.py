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
    # ── v3.2（2026-09-20）L2b 欧式长句 + L2c 反口语化 ──
    ("欧化", "L2b 欧式长句模块存在（六装置：定语链/关联配套/名词化/关系化/分号/破折号）",
     "modules/style-euro.md", ["的-定语链", "关联词配套", "名词化", "分号长复句"]),
    ("欧化", "L2b 与 L3 作文腔的区分讲清楚（去作文腔时勿把欧化一起铲掉）",
     "modules/style-euro.md", ["欧化 ≠ 作文腔", "纵向", "横向"]),
    ("欧化", "L2b 带缺口实测表（四稿联动配套/的链/分号全为 0 的举证）",
     "modules/style-euro.md", ["缺口实测", "全军覆没"]),
    ("口语", "L2c 反口语化硬禁表存在（每条须回语料核验 ≤0.2%）",
     "modules/style-euro.md", ["硬禁句式", "你去…就明白", "哪门子"]),
    ("口语", "L2c 句尾语气词只禁他近乎不用的（呢/吗/吧/啊/嘛 必须放行）",
     "modules/style-euro.md", ["呗 啦 哦 哟 咯 嗯 呀", "签名"]),
    ("欧化", "style_check 含 L2b/L2c 常量与函数（v5 勿再丢）",
     "scripts/style_check.py", ["EURO_BASE", "COLLOQ_BAN", "COLLOQ_TAIL_BAN",
                               "def euro", "def colloquial"]),
    ("文风", "style-diction 已订正黑名单误报（赋能/闭环/破局/生态位 是他真用词）",
     "modules/style-diction.md", ["2026-09-20 订正", "生态位"]),
    ("文风", "style-diction 已挂 L2b 指针（长度够≠肌理对）",
     "modules/style-diction.md", ["style-euro.md", "长度相同，句法血统不同"]),
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

    # 黑名单语料守卫（2026-09-20）：UNWANTED 是「他没说过」的断言 —— 每个词都必须
    # 回语料验证。2026-09-20 实测发现原表 8 词里 4 个是他真用过的（生态位 10 篇 /
    # 赋能 2 篇 / 闭环 2 篇 / 破局 1 篇），闸门因此误伤。此断言把该 bug 钉死。
    try:
        import importlib
        sc = importlib.import_module("style_check")
        raw = open(DEFAULT_CORPUS, encoding="utf-8").read()
        bad = [w for w in sc.UNWANTED if w in raw]
        out.append(("文风", "UNWANTED 黑名单词均未被语料使用（防误报，勿再把他说过的词加回）",
                    not bad,
                    "ok，%d 词全部零命中" % len(sc.UNWANTED) if not bad
                    else "⚠️ 他其实用过，不应列黑名单：%s" % "、".join(bad)))
    except Exception as e:
        out.append(("文风", "黑名单语料守卫", False, str(e)))

    # L2c 口语硬禁表语料守卫（v3.2）：同 UNWANTED 的道理，但更严 —— 每条 pattern
    # 的篇占比必须 ≤0.2%（全语料最多 2 篇）。加词前若不验，就会把他写过的话判成错。
    try:
        import importlib, json, re as _re
        sc = importlib.import_module("style_check")
        N = 0
        viol = []
        rx_all = [(p, _re.compile(p), why) for p, why in sc.COLLOQ_BAN]
        for line in open(DEFAULT_CORPUS, encoding="utf-8"):
            d = json.loads(line)
            if d.get("category") == "fiction":
                continue
            t = (d.get("text") or "").strip()
            if len(t) < 120:
                continue
            N += 1
            for p, rx, why in rx_all:
                if rx.search(t):
                    viol.append((p, why))
        cnt = {}
        for p, why in viol:
            cnt[p] = cnt.get(p, 0) + 1
        lim = getattr(sc, "COLLOQ_BAN_MAXRATE", 0.005)
        over = [(p, c) for p, c in cnt.items() if c / max(N, 1) > lim]
        out.append(("口语", "L2c 硬禁表每条篇占比 ≤%.1f%%（加词前必须回语料核验）" % (lim * 100),
                    not over,
                    "ok，%d 条全部达标（语料 %d 篇）" % (len(sc.COLLOQ_BAN), N) if not over
                    else "⚠️ 他其实写过，不该硬禁：%s" % "；".join(
                        "%s(%d篇)" % (p, c) for p, c in over)))
    except Exception as e:
        out.append(("口语", "L2c 硬禁表语料守卫", False, str(e)))

    # L2c 非空转验证（v3.2）：闸门必须真的会响。探针含「你去…就明白」+「哪门子」+
    # 「呗。」各一处，应至少报出 L2c 硬禁与句尾语气词；干净文本则不应报 L2c。
    try:
        import importlib
        sc = importlib.import_module("style_check")
        dirty = "你去那几个问题底下扫一眼就明白，这算哪门子自由主义，意思一下得了呗。"
        clean = ("保守主义意味着将社会变革转化为社会革新，没有秩序的变革无论动机好坏"
                 "最终都只会得到弱肉强食的无序状态。")
        d_hard, d_over, d_tail, _ = sc.colloquial(dirty)
        c_hard, c_over, c_tail, _ = sc.colloquial(clean)
        ok = bool(d_hard) and bool(d_tail) and not c_hard and not c_tail
        out.append(("口语", "L2c 非空转：脏文本必报、净文本不报（闸门不许空转）", ok,
                    "ok，脏文本硬禁 %d 处 / 语气词 %d 处；净文本 0" % (len(d_hard), len(d_tail))
                    if ok else "⚠️ 脏=%s/%s 净=%s/%s" % (d_hard, d_tail, c_hard, c_tail)))
    except Exception as e:
        out.append(("口语", "L2c 非空转验证", False, str(e)))

    # L2b 非空转验证（v3.2）：有欧化装置的文本，四项均须 >0。
    try:
        import importlib
        sc = importlib.import_module("style_check")
        euro_txt = ("尽管股市缓慢攀升，但本国的劳动者并未享受到许多上层人士所享有的复苏；"
                    "也正因为如此，他对实在论的坚持、对自然法的推崇、对自发秩序的认同，"
                    "无论动机好坏最终都只会得到弱肉强食的无序状态。")
        e = sc.euro(euro_txt)
        ok = e["关联配套"] > 0 and e["的定语链"] > 0 and e["_分号长复句"] >= 1
        out.append(("欧化", "L2b 非空转：含欧化装置的文本必须被检出（闸门不许空转）", ok,
                    "ok，配套 %.1f / 的链 %.1f / 分号 %d" % (
                        e["关联配套"], e["的定语链"], e["_分号长复句"])
                    if ok else "⚠️ 未检出：%s" % e))
    except Exception as e:
        out.append(("欧化", "L2b 非空转验证", False, str(e)))
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
