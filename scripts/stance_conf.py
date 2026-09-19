#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
立场置信度量化器 —— P3

解决的问题：语料里 2016 年的一条临时感慨，和 2026 年反复表态的稳定立场，
在静态 skill 里权重相同。这会让模型对"他随口说过一次"的东西也斩钉截铁。

本脚本给定议题，统计真实证据强度（条数 / 跨年反复度 / 分类置信 / satire 混入比），
换算成信心等级，并直接给出**应该用什么语气说话**。

    A  斩钉截铁       —— "很明显""必须""归根结底"
    B  正常陈述
    C  留白           —— "这个我不确定""我在这里没有很强的直觉"
    D  声明没谈过      —— 改用方法论推演并标明，禁止编造

用法：
  python stance_conf.py "米莱"
  python stance_conf.py "衡水" --loose        # 宽松匹配(OR)，默认精确(AND)
  python stance_conf.py "十诫" --json
  python stance_conf.py "做题家" --top 5      # 附带列出证据条目
"""

import argparse
import json
import os
import statistics
import sys
import unicodedata

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from retrieve import load_corpus, DEFAULT_CORPUS, make_snippet  # noqa: E402


def haystack(d):
    return "\n".join([
        d.get("_title", ""), d.get("stance", ""),
        d.get("themes", ""), d.get("mentions", ""), d.get("text", ""),
    ])


def match(docs, query, loose=False):
    # 归一化：NFKC + 小写。避免 "Hayek"/"hayek"、全角/半角、部分变体漏匹配
    # （retrieve.py 的分词走同一套归一，两边口径保持一致）
    terms = [unicodedata.normalize("NFKC", t).lower() for t in query.split() if t]
    if not terms:
        return []
    hits = []
    for d in docs:
        hay = unicodedata.normalize("NFKC", haystack(d)).lower()
        n = sum(1 for t in terms if t in hay)
        if loose:
            ok = n >= 1
        else:
            ok = n == len(terms)      # 默认 AND：全部词都出现才算相关
        if ok:
            hits.append((d, n))
    hits.sort(key=lambda x: (-x[1], x[0].get("created", "")))
    return hits


def grade(n, nyears, avgconf, satire_ratio):
    """可解释的加分制，不做黑箱打分。"""
    s = 0
    reasons = []
    if n >= 8:
        s += 2; reasons.append("语料充足(%d条)" % n)
    elif n >= 3:
        s += 1; reasons.append("语料中等(%d条)" % n)
    else:
        reasons.append("语料单薄(%d条)" % n)

    if nyears >= 3:
        s += 2; reasons.append("跨%d年反复表态" % nyears)
    elif nyears >= 2:
        s += 1; reasons.append("跨%d年出现" % nyears)
    else:
        reasons.append("仅单一年份出现")

    if avgconf >= 0.85:
        s += 1; reasons.append("分类置信高(%.2f)" % avgconf)
    else:
        reasons.append("分类置信一般(%.2f)" % avgconf)

    if satire_ratio > 0.5:
        s -= 2; reasons.append("过半为 satire(%.0f%%)，立场需反向解码" % (satire_ratio * 100))
    elif satire_ratio > 0.2:
        s -= 1; reasons.append("含 %.0f%% satire，混入反讽" % (satire_ratio * 100))

    if n == 0:
        return "D", s, ["无命中"]
    if s >= 4:
        return "A", s, reasons
    if s >= 2:
        return "B", s, reasons
    # n>=1 时最低只到 C（"谈过但证据薄"）。D 严格只留给零命中。
    # 旧版在此处再写 `return "D"` 是 bug：它把"单条+单年+置信一般"(s 累计为 0) 错判成
    # "从未谈过"，会让 skill 对着一条真实存在的话说"他没谈过"。
    return "C", s, reasons


TONE = {
    "A": ("斩钉截铁", "「很明显…」「必须…」「归根结底…」——可直接下判断，不必 hedging"),
    "B": ("正常陈述", "陈述立场即可，语气平稳，无需刻意留白"),
    "C": ("留白", "证据薄，别装确信。用**当下的口语反应**（「这个我真不懂」「说不好」），**不要**交代'谈没谈过'"),
    "D": ("零命中（未覆盖）", "台词**不自我汇报**：直接答现象层（若有据），或干脆说'不懂'。'未覆盖/属推演'的标注放**交付注**（回答之外），绝不写进台词"),
}


def main():
    ap = argparse.ArgumentParser(description="立场置信度量化（P3）")
    ap.add_argument("query", help="议题关键词")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--loose", action="store_true", help="宽松匹配(OR)，默认精确(AND)")
    ap.add_argument("--top", type=int, default=0, help="附带列出前 N 条证据")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    corpus = os.path.abspath(args.corpus)
    if not os.path.exists(corpus):
        print("找不到语料：%s" % corpus, file=sys.stderr)
        sys.exit(1)
    docs = load_corpus(corpus)
    hits = match(docs, args.query, loose=args.loose)

    n = len(hits)
    years = sorted({d["created"][:4] for d, _ in hits if d.get("created")})
    nyears = len(years)
    confs = [float(d["confidence"]) for d, _ in hits]
    avgconf = statistics.mean(confs) if confs else 0.0
    cats = {}
    for d, _ in hits:
        cats[d["category"]] = cats.get(d["category"], 0) + 1
    satire_ratio = cats.get("satire", 0) / n if n else 0.0

    g, score, reasons = grade(n, nyears, avgconf, satire_ratio)
    tone_name, tone_how = TONE[g]

    if args.json:
        print(json.dumps({
            "query": args.query, "n": n, "years": years, "nyears": nyears,
            "avg_confidence": round(avgconf, 3), "categories": cats,
            "satire_ratio": round(satire_ratio, 3), "grade": g, "score": score,
            "reasons": reasons, "tone": tone_name, "tone_how": tone_how,
            "evidence": [{"created": d["created"], "category": d["category"],
                          "confidence": d["confidence"], "url": d["url"],
                          "stance": d["stance"]} for d, _ in hits[:args.top]],
        }, ensure_ascii=False, indent=2))
        return

    print("## 立场置信度：%s" % args.query)
    print("")
    print("**等级 %s**（得分 %d） ｜ 建议语气：**%s**" % (g, score, tone_name))
    print("")
    print("> %s" % tone_how)
    print("")
    print("### 证据构成")
    print("")
    print("| 指标 | 值 |")
    print("|---|---|")
    print("| 命中条数 | %d |" % n)
    print("| 年份分布 | %s |" % ("、".join(years) if years else "—"))
    print("| 跨年数 | %d |" % nyears)
    print("| 平均分类置信 | %.2f |" % avgconf)
    print("| 分类构成 | %s |" % ("、".join("%s×%d" % (k, v) for k, v in
                                          sorted(cats.items(), key=lambda x: -x[1])) or "—"))
    print("| satire 占比 | %.0f%% |" % (satire_ratio * 100))
    print("")
    print("### 判定依据")
    print("")
    for r in reasons:
        print("- %s" % r)

    if g == "D" and n == 0:
        print("")
        print("> ⚠️ **无命中**。禁止据此编造他的立场——改走方法论推演并标明，"
              "或诚实说「他好像没公开谈过这个」。")
    if satire_ratio > 0.5:
        print("")
        print("> ⚠️ **过半命中为 satire**，该议题下他的表述多为反话。"
              "引用前必须走 `satire-decoder.md` 双查反向解码。")

    if args.top:
        print("")
        print("### 证据条目（前 %d）" % min(args.top, n))
        print("")
        for i, (d, _) in enumerate(hits[:args.top], 1):
            print("%d. `%s` · %s · conf %.2f · %s" % (
                i, d["category"], d["created"], float(d["confidence"]), d["kind"]))
            if d["stance"]:
                print("   - 立场摘要：%s" % d["stance"])
            print("   - <%s>" % d["url"])


if __name__ == "__main__":
    main()
